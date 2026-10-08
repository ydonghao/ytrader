"""thesis_monitor 纯函数测试：evaluate_thesis 搬迁后行为不变。"""
from src.domain.market.fundamental.thesis_monitor import (
    ThesisCondition,
    evaluate_thesis,
)


def _cond(metric, op, thr):
    return ThesisCondition(metric=metric, operator=op, threshold=thr)


def test_all_held():
    r = evaluate_thesis(
        [_cond("roe", ">=", 15), _cond("debt_ratio", "<=", 60)],
        {"roe": 18.0, "debt_ratio": 50.0},
    )
    assert r.breached == [] and len(r.held) == 2
    assert r.recommend_sell is False


def test_any_breach_recommends_sell():
    r = evaluate_thesis(
        [_cond("roe", ">=", 15), _cond("debt_ratio", "<=", 60)],
        {"roe": 12.0, "debt_ratio": 50.0},
    )
    assert len(r.breached) == 1 and r.breached[0].metric == "roe"
    assert r.recommend_sell is True


def test_missing_metric_is_held_not_breached():
    r = evaluate_thesis([_cond("roe", ">=", 15)], {"debt_ratio": 50.0})
    assert r.breached == [] and len(r.held) == 1
    assert r.recommend_sell is False


# ── Task 2: METRIC_REGISTRY / verdict / band ──────────────────────────────
from src.domain.market.fundamental.thesis_monitor import (
    METRIC_REGISTRY,
    check_price_band,
    compute_metric_values,
    reeval_verdict,
)


def test_registry_has_nine_metrics():
    assert set(METRIC_REGISTRY) == {
        "roe", "revenue_yoy", "net_profit_yoy", "gross_margin",
        "ocf_ratio", "debt_ratio", "pe_ttm", "pb", "dv_ttm",
    }


def test_compute_metric_values_full():
    v = compute_metric_values({
        "net_profit": 100.0, "equity": 500.0,
        "report_date": "2025-12-31",   # 年报: 年化系数×1
        "revenue": 1200.0, "revenue_prev": 1000.0,
        "net_profit_prev": 80.0,
        "ocf": 90.0, "gross_margin": 30.0,
        "total_assets": 900.0, "total_liabilities": 450.0,
        "pe_ttm": 12.0, "pb": 1.5, "dv_ttm": 3.0,
    })
    assert v["roe"] == 20.0            # 100/500*100*1
    assert v["revenue_yoy"] == 20.0    # (1200-1000)/1000*100
    assert v["net_profit_yoy"] == 25.0
    assert v["ocf_ratio"] == 0.9       # ocf/net_profit
    assert v["debt_ratio"] == 50.0     # 负债/资产*100
    assert v["gross_margin"] == 30.0
    assert v["pe_ttm"] == 12.0 and v["pb"] == 1.5 and v["dv_ttm"] == 3.0


def test_compute_metric_values_skips_missing():
    v = compute_metric_values({"revenue": 100.0})
    assert v.get("revenue_yoy") is None and v.get("roe") is None


def test_verdict_condition_breach_is_sell_signal():
    cr = [{"status": "breached"}]
    assert reeval_verdict({"score": 80}, {"score": 80}, cr) == "sell_signal"


def test_verdict_eliminate_is_sell_signal():
    assert reeval_verdict(
        {"score": 30, "verdict": "eliminate"}, {"score": 80}, []
    ) == "sell_signal"


def test_verdict_score_drop_is_review():
    assert reeval_verdict({"score": 60}, {"score": 80}, []) == "review"


def test_verdict_new_red_flag_is_review():
    assert reeval_verdict(
        {"score": 80, "red_flags": ["a"]}, {"score": 80, "red_flags": []}, []
    ) == "review"


def test_verdict_pass():
    assert reeval_verdict({"score": 80}, {"score": 80}, []) == "pass"


def test_verdict_no_base_quality_is_pass():
    assert reeval_verdict({"score": 50}, None, []) == "pass"


def test_band_price_reached():
    r = check_price_band({"metric": "price", "low": 40, "high": 50}, 51.0, {})
    assert r == {"metric": "price", "current": 51.0, "low": 40, "high": 50,
                 "reached": True}


def test_band_pe_not_reached():
    r = check_price_band(
        {"metric": "pe_ttm", "low": 20, "high": 30}, None, {"pe_ttm": 15.0}
    )
    assert r["reached"] is False and r["current"] == 15.0


def test_band_missing_current_is_unknown():
    r = check_price_band({"metric": "pb", "low": 2, "high": 3}, None, {})
    assert r["reached"] is None


def test_band_none_is_unknown():
    assert check_price_band(None, 10.0, {})["reached"] is None


# ── Task 3: build_sell_check 四区报告 ─────────────────────────────────────
import datetime as dt

from src.domain.market.fundamental.thesis_monitor import build_sell_check


def _base_inputs():
    thesis = {
        "buy_date": "2026-01-10", "buy_price": 30.0,
        "last_reviewed_at": dt.datetime.now() - dt.timedelta(days=100),
        "decision": None,
        "target_band": {"metric": "price", "low": 40, "high": 50},
        "thesis_text": "ROE 持续>15",
    }
    conditions = [
        {"id": 1, "metric_key": "roe", "operator": ">=",
         "threshold": 15.0, "label": "ROE>=15"},
    ]
    return thesis, conditions


def test_sell_check_sections_present():
    thesis, conditions = _base_inputs()
    r = build_sell_check(
        thesis, conditions, {"roe": 18.0},
        {"metric": "price", "current": 45.0, "low": 40, "high": 50,
         "reached": True},
        {"date": "2026-01-10", "price": 30.0,
         "quality": {"score": 80, "verdict": "pass", "red_flags": []},
         "valuation": {"dcf_upside": 35.0 / 30.0 - 1.0}},
        {"price": 45.0, "dcf_upside": 42.0 / 45.0 - 1.0},
        {"score": 75, "verdict": "pass", "red_flags": []},
    )
    assert set(r["sections"]) == {
        "thesis", "valuation", "fundamentals", "decision"
    }
    assert r["recommend_sell"] is False
    assert r["sections"]["thesis"]["items"][0]["status"] == "holding"
    assert r["sections"]["valuation"]["band"]["reached"] is True
    # 安全边际消耗: 登记时价30 vs dcf35 → +16.7%; 现在45 vs42 → +7.1%
    assert r["sections"]["valuation"]["margin_consumed"] > 0
    assert r["sections"]["fundamentals"]["score_diff"] == -5
    assert r["stale_days"] >= 100


def test_sell_check_breach_flags_recommend_sell():
    thesis, conditions = _base_inputs()
    r = build_sell_check(thesis, conditions, {"roe": 10.0},
                         None, None, None, None)
    assert r["recommend_sell"] is True
    assert r["sections"]["thesis"]["items"][0]["status"] == "breached"


def test_sell_check_missing_metric_is_unknown():
    thesis, conditions = _base_inputs()
    r = build_sell_check(thesis, conditions, {}, None, None, None, None)
    assert r["sections"]["thesis"]["items"][0]["status"] == "unknown"


# ── 第3期: build_review_summary ───────────────────────────────────────────
from src.domain.market.fundamental.thesis_monitor import (
    build_review_summary,
)


def _closed(sym, reason, buy, close):
    return {"symbol": sym, "close_reason": reason,
            "buy_price": buy, "close_price": close}


def test_review_summary_groups_and_stats():
    now = dt.datetime(2026, 9, 27)
    closed = [
        _closed("sh600519", "valuation_reached", 100.0, 150.0),  # +50%
        _closed("sz000001", "valuation_reached", 100.0, 110.0),  # +10%
        _closed("sh601318", "thesis_broken", 100.0, 80.0),       # -20%
        _closed("sh600036", None, 100.0, None),                  # 缺价不计
    ]
    journals = [
        {"symbol": "sh600519", "kind": "decision", "decision": "sell",
         "note": "", "price": 150.0,
         "created_at": "2026-09-20T10:00:00"},
        {"symbol": "sz000001", "kind": "note", "decision": None,
         "note": "手记", "price": None,
         "created_at": "2026-09-21T10:00:00"},
        {"symbol": "sh601318", "kind": "close",
         "decision": "thesis_broken", "note": "", "price": 80.0,
         "created_at": "2026-09-22T10:00:00"},
    ]
    r = build_review_summary(closed, journals,
                             dt.datetime(2026, 8, 20), now=now)
    stats = {s["reason"]: s for s in r["closed_stats"]}
    assert stats["valuation_reached"]["count"] == 2
    assert stats["valuation_reached"]["avg_pnl_pct"] == 30.0
    assert stats["valuation_reached"]["win_count"] == 2
    assert stats["thesis_broken"]["win_count"] == 0
    assert None not in stats  # 缺价/无原因的不产生分组
    # recent_decisions 只含 decision/close，倒序
    kinds = [d["kind"] for d in r["recent_decisions"]]
    assert kinds == ["close", "decision"]
    assert r["stale_review"] is True   # 8/20 → 9/27 = 38 天


def test_review_summary_stale_threshold():
    now = dt.datetime(2026, 9, 27)
    fresh = build_review_summary([], [], dt.datetime(2026, 9, 10),
                                  now=now)
    assert fresh["stale_review"] is False
    none_ = build_review_summary([], [], None, now=now)
    assert none_["stale_review"] is True


# ── 增强: 论点条件历史回测 ────────────────────────────────────────────────
from src.domain.market.fundamental.thesis_monitor import (
    backtest_conditions,
)


def _period(rd, **kw):
    base = {
        "revenue": 1000.0, "net_profit_parent": 100.0, "ocf": 90.0,
        "total_assets": 900.0, "total_liabilities": 450.0,
        "equity": 450.0, "gross_margin": 30.0,
    }
    base.update(kw)
    return {"report_date": rd, **base}


def test_backtest_roe_decline_breaches():
    # 年化 roe（×12/月）：40 / 15 / 10 / 36 —— 9月报15临界holding,
    # 年报10破, 一季报36回升holding
    periods = [
        _period("2025-06-30", net_profit_parent=90.0),    # ×2 → 40
        _period("2025-09-30", net_profit_parent=56.25),   # ×4/3 → 15
        _period("2025-12-31", net_profit_parent=45.0),    # ×1 → 10
        _period("2026-03-31", net_profit_parent=135.0),   # ×4 → 120? 用小值
    ]
    periods[3]["net_profit_parent"] = 54.0               # 54/450×4=48→holding? 用12→破
    periods[3]["net_profit_parent"] = 13.5               # 13.5/450×4=12 → 破
    conds = [{"metric_key": "roe", "operator": ">=", "threshold": 15.0}]
    r = backtest_conditions(conds, periods)
    s = r["summary"][0]
    assert s["evaluated"] == 3            # 自第2期起
    assert s["breached"] == 2             # 10、12 两期破
    assert abs(s["breach_rate"] - 2 / 3) < 1e-9
    assert s["first_breach_report_date"] == "2025-12-31"


def test_backtest_yoy_no_year_ago_base_is_unknown():
    # 相邻期无去年同报告期 → yoy unknown（不再用上一份报告冒充基期）
    periods = [
        _period("2025-06-30", revenue=1000.0),
        _period("2025-09-30", revenue=1200.0),
    ]
    conds = [{"metric_key": "revenue_yoy", "operator": ">=",
              "threshold": 10.0}]
    r = backtest_conditions(conds, periods)
    assert r["periods"][0]["conditions"][0]["status"] == "unknown"


def test_backtest_valuation_unsupported():
    periods = [_period("2025-06-30"), _period("2025-09-30")]
    conds = [{"metric_key": "pe_ttm", "operator": "<=",
              "threshold": 20.0}]
    r = backtest_conditions(conds, periods)
    assert r["valuation_unsupported"] == ["pe_ttm"]
    assert r["summary"][0]["evaluated"] == 0
    assert r["periods"][0]["conditions"][0]["status"] == "unknown"


def test_backtest_single_period_no_eval():
    r = backtest_conditions(
        [{"metric_key": "roe", "operator": ">=", "threshold": 15}],
        [_period("2025-06-30")],
    )
    assert r["summary"][0]["evaluated"] == 0 and r["periods"] == []


# ── 口径修复: ROE年化 + YoY同期基期 ────────────────────────────────────────
def test_roe_annualized_by_report_month():
    # 中报(6月)累计净利50/权益200=25% → 年化×2=50%
    v = compute_metric_values({
        "net_profit": 50.0, "equity": 200.0,
        "report_date": "2026-06-30",
    })
    assert v["roe"] == 50.0
    # 一季报 ×4
    v2 = compute_metric_values({
        "net_profit": 25.0, "equity": 200.0,
        "report_date": "2026-03-31",
    })
    assert v2["roe"] == 50.0
    # 无报告期日期 → 无法年化 → None（诚实缺失优于错误值）
    v3 = compute_metric_values({
        "net_profit": 50.0, "equity": 200.0,
    })
    assert v3["roe"] is None


def test_backtest_yoy_uses_year_ago_base():
    periods = [
        _period("2024-06-30", revenue=1000.0),
        _period("2024-09-30", revenue=1100.0),
        _period("2025-06-30", revenue=1200.0),   # 同期基期=2024-06-30 → +20%
        _period("2025-09-30", revenue=1210.0),   # 基期=2024-09-30 → +10%
    ]
    conds = [{"metric_key": "revenue_yoy", "operator": ">=",
              "threshold": 15.0}]
    r = backtest_conditions(conds, periods)
    statuses = [p["conditions"][0]["status"] for p in r["periods"]]
    # 2025-06-30(+20%)holding; 2025-09-30(+10%)breached
    assert statuses == ["unknown", "holding", "breached"]


def test_roe_ttm_preferred_over_annualization():
    # TTM 240（当期60+年报250−同期70）/ 权益 1000 = 24%（不季节失真）
    v = compute_metric_values({
        "net_profit": 60.0, "equity": 1000.0,
        "net_profit_ttm": 240.0, "report_date": "2026-03-31",
    })
    assert v["roe"] == 24.0


def test_backtest_roe_uses_ttm_when_available():
    # Q1-2026(60) + FY2025(250) − Q1-2025(70) = 240 → roe 24（非×4失真）
    periods = [
        _period("2024-12-31", net_profit_parent=230.0),
        _period("2025-03-31", net_profit_parent=70.0),
        _period("2025-12-31", net_profit_parent=250.0),
        _period("2026-03-31", net_profit_parent=60.0),
    ]
    conds = [{"metric_key": "roe", "operator": ">=", "threshold": 20.0}]
    r = backtest_conditions(conds, periods)
    # 2025-03-31: ttm=70+230−? 无2024Q1 → 年化×4=61.8 holding
    # 2026-03-31: ttm=240/1000? equity=450 → 240/450=53.3 holding
    currents = [p["conditions"][0]["current"] for p in r["periods"]]
    # periods: [2025-03(年化62.2), 2025-12(年报55.6), 2026-03(TTM 53.3)]
    assert abs(currents[2] - 240.0 / 450.0 * 100.0) < 1e-6


# ── F5: 建仓执行进度 ───────────────────────────────────────────────────────
from src.domain.market.fundamental.thesis_monitor import ladder_progress


def test_ladder_progress():
    ladder = [
        {"rung_index": 1, "drop_pct": 0, "price_level": 100.0,
         "weight_of_position": 0.4, "amount": 40000.0, "shares": 400},
        {"rung_index": 2, "drop_pct": -8, "price_level": 92.0,
         "weight_of_position": 0.3, "amount": 30000.0, "shares": 300},
        {"rung_index": 3, "drop_pct": -16, "price_level": 84.0,
         "weight_of_position": 0.3, "amount": 30000.0, "shares": 300},
    ]
    fills = [
        {"rung_index": 1, "price": 100.0, "shares": 400},
        {"rung_index": 2, "price": 93.5, "shares": 300},
    ]
    p = ladder_progress(ladder, fills)
    assert p["rungs_done"] == 2 and p["rungs_total"] == 3
    assert p["invested"] == 400 * 100 + 300 * 93.5
    assert p["planned_total"] == 100000.0
    assert p["invested_pct"] == 68.05      # 68050/100000
    assert abs(p["avg_fill_price"] - 68050.0 / 700) < 1e-3
    r2 = p["rungs"][1]
    assert r2["filled"] is True and r2["fill_price"] == 93.5


def test_ladder_progress_empty():
    p = ladder_progress([], [])
    assert p["rungs_total"] == 0 and p["invested_pct"] is None


# ── 三期G2: 卖出后表现 ────────────────────────────────────────────────────
from src.domain.market.fundamental.thesis_monitor import (
    closed_performance,
)


def test_closed_performance_with_summary():
    closed = [
        {"id": 1, "symbol": "a", "close_price": 100.0,
         "closed_at": "2026-06-01T10:00:00"},
        {"id": 2, "symbol": "b", "close_price": 50.0,
         "closed_at": "2026-07-01T10:00:00"},
        {"id": 3, "symbol": "c", "close_price": None,   # 无关闭价跳过
         "closed_at": "2026-07-01T10:00:00"},
    ]
    prices = {"a": 90.0, "b": 60.0}
    out = closed_performance(closed, prices)
    assert len(out["rows"]) == 2
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["a"]["since_close_pct"] == -10.0   # 卖对(继续跌)
    assert by["b"]["since_close_pct"] == 20.0    # 卖飞(继续涨)
    assert out["summary"]["count"] == 2
    assert out["summary"]["avg_pct"] == 5.0
    assert out["summary"]["sold_early_count"] == 1   # 涨=卖飞


# ── 三期G5: 研究管道 ──────────────────────────────────────────────────────
from src.domain.market.fundamental.thesis_monitor import pipeline_stages


def test_pipeline_stages_priority():
    out = pipeline_stages(
        watch={"a", "b", "c", "d", "e"},
        checked={"b"},            # 体检过
        noted={"c"},              # 有笔记
        active={"d"},             # 持仓中
        closed={"e"},             # 已关闭
    )
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["d"]["stage"] == "holding"
    assert by["a"]["stage"] == "watching"
    assert by["e"]["stage"] == "closed"
    # b 体检过但没登记 → 待决策; c 只有笔记 → 研究中
    assert by["b"]["stage"] == "checked"
    assert by["c"]["stage"] == "noted"
    counts = out["counts"]
    assert counts["holding"] == 1 and counts["watching"] == 1


# ── 决策日志补全: 错过复盘 + 信心度校准 ──────────────────────────────────
from src.domain.market.fundamental.thesis_monitor import (
    confidence_calibration,
    pass_performance,
)


def test_pass_performance_with_benchmark():
    rows = [
        {"id": 1, "symbol": "a", "decision_date": "2026-01-05",
         "price": 100.0},                       # +50% vs 基准+10% → 踏空
        {"id": 2, "symbol": "b", "decision_date": "2026-01-05",
         "price": 100.0},                       # 现价缺失 → 不计分
        {"id": 3, "symbol": "c", "decision_date": "2026-01-05",
         "price": 200.0},                       # -25% vs 基准+10% → 回避正确
    ]
    prices = {"a": 150.0, "c": 150.0}
    bench = [
        {"trade_date": "2026-01-05", "close": 4000.0},
        {"trade_date": "2026-06-30", "close": 4400.0},
    ]
    out = pass_performance(rows, prices, bench)
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["a"]["since_pct"] == 50.0
    assert by["a"]["bench_pct"] == 10.0
    assert by["a"]["excess_pct"] == 40.0
    assert by["a"]["verdict"] == "踏空"
    assert by["c"]["since_pct"] == -25.0
    assert by["c"]["excess_pct"] == -35.0
    assert by["c"]["verdict"] == "回避正确"
    assert by["b"]["verdict"] is None            # 无现价不计分
    assert out["summary"]["count"] == 2          # 只统计可计分行
    assert out["summary"]["missed_count"] == 1


def test_pass_performance_empty_benchmark():
    out = pass_performance(
        [{"id": 1, "symbol": "a", "decision_date": "2026-01-05",
          "price": 100.0}],
        {"a": 120.0}, [],
    )
    assert out["rows"][0]["since_pct"] == 20.0
    assert out["rows"][0]["excess_pct"] is None  # 无基准则不判
    assert out["summary"]["count"] == 0


def test_confidence_calibration_groups():
    closed = [
        {"id": 1, "buy_price": 100.0, "close_price": 150.0},
        {"id": 2, "buy_price": 100.0, "close_price": 80.0},
        {"id": 3, "buy_price": 100.0, "close_price": 130.0},
        {"id": 4, "buy_price": 100.0, "close_price": 120.0},  # 无信心记录
        {"id": 5, "buy_price": None, "close_price": 120.0},   # 无价不计
    ]
    journals = [
        # id=1 有两条 created: 取更早那条的信心度
        {"thesis_id": 1, "kind": "created", "confidence": 5,
         "created_at": "2026-01-01"},
        {"thesis_id": 1, "kind": "created", "confidence": 2,
         "created_at": "2026-03-01"},
        {"thesis_id": 2, "kind": "created", "confidence": 5,
         "created_at": "2026-01-02"},
        {"thesis_id": 3, "kind": "created", "confidence": 3,
         "created_at": "2026-01-03"},
        # id=3 的 decision 信心度不参与
        {"thesis_id": 3, "kind": "decision", "confidence": 1,
         "created_at": "2026-02-01"},
    ]
    out = confidence_calibration(closed, journals)
    by = {g["confidence"]: g for g in out["groups"]}
    assert by[5]["count"] == 2 and by[5]["win_count"] == 1
    assert by[5]["avg_pnl_pct"] == 15.0          # (+50% + -20%) / 2
    assert by[3]["win_rate"] == 1.0
    assert out["no_confidence_count"] == 1       # id=4
