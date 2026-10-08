"""数据健康检查框架测试（假 query 注入，无 DB）。"""
import datetime as dt

from src.domain.market.health.registry import all_checks, CheckResult
from src.domain.market.health.runner import edge_transitions, run_checks


TODAY = dt.date(2026, 9, 27)


def _fake_query_factory(table_dates, extra=None):
    """table_dates={table: max_date}; extra 按表给覆盖行数。"""
    def query(sql):
        sql_l = sql.lower()
        for t, d in table_dates.items():
            if "max" in sql_l and f"from {t}" in sql_l:
                return [{"d": d}]
        if "count(*) filter" in sql_l:
            return [{"total": 5000, "zeros": 4999}]
        if "count(*)" in sql_l:
            if "stock_valuation" in sql_l:
                if "> '" in sql_l.split("where")[1]:
                    # 近5日 vs 基线: 按日期片段返回
                    frag = sql.split("WHERE")[1]
                    if "and trade_date" in frag.lower():
                        return [{"c": 450000}]    # 基线90日
                    return [{"c": 24000}]         # 近5日
            return [{"c": 100}]
        return []
    return query


def test_freshness_rules_run():
    q = _fake_query_factory({
        "stock_ohlcv": TODAY - dt.timedelta(days=2),
        "index_ohlcv": TODAY - dt.timedelta(days=9),   # 断线
    })
    results = run_checks(q, today=TODAY)
    assert len(results) == len(all_checks()) == 13
    by = {r.check_id: r for r in results}
    assert by["freshness_stock_ohlcv"].status == "ok"
    assert by["freshness_index_ohlcv"].status == "warn"
    assert by["freshness_index_ohlcv"].metric["age_days"] == 9


def test_missing_table_fails():
    q = _fake_query_factory({"stock_ohlcv": None})
    results = run_checks(q, today=TODAY)
    by = {r.check_id: r for r in results}
    assert by["freshness_stock_ohlcv"].status == "fail"


def test_north_flow_structural_is_ok_info():
    q = _fake_query_factory({"north_flow_daily": dt.date(2026, 8, 17)})
    results = run_checks(q, today=TODAY)
    by = {r.check_id: r for r in results}
    r = by["structural_north_flow"]
    assert r.status == "ok" and r.severity == "info"


def test_change_pct_zero_warns():
    q = _fake_query_factory({"stock_ohlcv": TODAY})
    results = run_checks(q, today=TODAY)
    by = {r.check_id: r for r in results}
    # 假 query 给 zeros 4999/5000 → 零值率>90% → warn
    assert by["zero_stock_ohlcv_change_pct"].status == "warn"


def _res(cid, status, sev="warn"):
    return CheckResult(check_id=cid, table="t", severity=sev,
                       status=status)


def test_edge_transitions_dedup():
    results = [_res("a", "fail"), _res("b", "ok"), _res("c", "warn")]
    # a 持续 fail 不推; b 从 fail 恢复推; c 新告警推
    hist = {"a": "fail", "b": "fail", "c": "ok"}
    notify = edge_transitions(results, hist)
    ids = {r.check_id for r in notify}
    assert ids == {"b", "c"}


def test_edge_ignores_info():
    results = [_res("n", "ok", sev="info")]
    notify = edge_transitions(results, {"n": "fail"})
    assert notify == []


# ── 阶段三: 自愈候选(纯函数) ───────────────────────────────────────────────
from src.domain.market.health.heal import collect_heal_candidates


def test_heal_candidates_with_safety_valves():
    ok = CheckResult(check_id="freshness_stock_ohlcv", table="t",
                     severity="critical", status="ok")
    healable = CheckResult(
        check_id="freshness_stock_valuation", table="t",
        severity="critical", status="fail",
        metric={"age_days": 10})
    too_old = CheckResult(   # >30 天窗口 → 安全阀拦截不回补
        check_id="freshness_stock_valuation", table="t",
        severity="critical", status="fail",
        metric={"age_days": 60})
    cands = collect_heal_candidates([ok, healable, too_old])
    assert len(cands) == 1 and cands[0]["check_id"] == \
        "freshness_stock_valuation"


def test_heal_candidates_max_five():
    rs = [CheckResult(check_id="freshness_market_thermometer_daily",
                      table="t", severity="warn", status="fail",
                      metric={"age_days": 5})] * 8
    assert len(collect_heal_candidates(rs)) == 5


# ── sw 统一诊断: 最近邻偏差 ────────────────────────────────────────────────
from src.domain.market.health.sw_unify import nearest_neighbor_deviation


def test_nn_deviation_median():
    computed = [
        ("801010", "2026-08-17", 30.0),
        ("801040", "2026-08-17", 15.0),
    ]
    akshare = [
        # 801010: 8-16 对 computed 8-17 → dev 10%
        ("801010", "2026-08-16", 27.0),
        # 801040: 超出10日窗 → 不参与
        ("801040", "2026-07-01", 15.0),
    ]
    out = nearest_neighbor_deviation(akshare, computed,
                                     metric="pe_ttm", max_gap_days=10)
    assert out["pairs"] == 1
    assert abs(out["median_dev_pct"] - 10.0) < 1e-9
    assert out["by_industry"]["801010"]["dev_pct"] == 10.0


def test_merge_sw_series_computed_priority():
    import datetime as dt
    from src.domain.market.health.sw_unify import merge_sw_series
    computed = [
        {"trade_date": dt.date(2026, 8, 17), "pe_ttm": 30.0},
        {"trade_date": dt.date(2026, 8, 20), "pe_ttm": 31.0},
    ]
    akshare = [
        {"trade_date": dt.date(2026, 8, 17), "pe_ttm": 29.0},  # 重叠→丢
        {"trade_date": dt.date(2026, 8, 18), "pe_ttm": 29.5},  # 补缺
    ]
    merged = merge_sw_series(computed, akshare)
    assert [r["trade_date"] for r in merged] == [
        dt.date(2026, 8, 17), dt.date(2026, 8, 18), dt.date(2026, 8, 20),
    ]
    assert merged[0]["pe_ttm"] == 30.0     # computed 优先
    assert merged[1]["pe_ttm"] == 29.5     # akshare 补缺
