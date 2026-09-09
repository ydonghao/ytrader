"""market-cap-growth 端点测试（mock 仓储，模式抄 test_five_forces.py）。"""
import json
import os
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


def _clear_cache():
    import src.api.handler.financial_detail_handler as h
    h._mcg_cache["data"].clear()
    h._mcg_cache["ts"].clear()


def _fin_row(rd, rev, np_, cnt):
    return SimpleNamespace(report_date=date.fromisoformat(rd),
                           revenue_sum=rev, net_profit_sum=np_,
                           sample_count=cnt)


def _val_row(td, mv):
    return SimpleNamespace(trade_date=date.fromisoformat(td), total_mv=mv)


# 冻结「今天」：handler 用 date.today() 推窗口起点（start=今日−years，
# 保月日），不冻结的话测试结果随运行日期漂移（定时炸弹：边缘测试曾
# 只在今日落在 (2026-06-30, 2026-09-30] 内才碰巧夹住窗口边界）。
# 注：不能改成「相对今天动态造日期」——今日若在 1~3 月，任何 years 的
# start 都落在 Q1 段，窗口首期必为 Q1（累计=单季），边界场景根本构不出来。
_FROZEN_TODAY = date(2026, 8, 27)
# 2-29 运行日：旧 date(y-years, 2, 29) 在平年会 ValueError（relativedelta 安全）
_LEAP_TODAY = date(2028, 2, 29)


def _frozen_handler(today=_FROZEN_TODAY):
    import src.api.handler.financial_detail_handler as h

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return today

    return patch.object(h, "date", _FrozenDate)


class _FinRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_series(self, scope_type, scope_code, start=None, end=None):
        # 与真实仓储同语义：按 start 过滤。否则 handler 即使回退成
        # 「只取窗口内数据」（丢差分基准），mock 照样喂全量行，测试失聪。
        assert scope_type == "index"
        if start is not None:
            return [r for r in self._rows if r.report_date >= start]
        return self._rows


class _IdxValRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_index_range(self, symbol, start, end):
        return self._rows


FIN_ROWS = [
    _fin_row("2023-03-31", 10.0, 1.0, 300),
    _fin_row("2023-12-31", 60.0, 6.0, 300),
    _fin_row("2024-03-31", 14.0, 1.4, 300),
]
VAL_ROWS = [
    _val_row("2023-03-31", 500000.1234),   # 带小数：锁定 mv_series round 2
    _val_row("2024-03-31", 5.5e5),
]


def _call_index(code="000300", fin_rows=None, years=10, today=_FROZEN_TODAY):
    from src.api.handler.financial_detail_handler import (
        market_cap_growth_index,
    )
    _clear_cache()
    with _frozen_handler(today), patch(
        "src.infra.database.market.index_financial."
        "create_index_financial_repository",
        return_value=_FinRepo(FIN_ROWS if fin_rows is None else fin_rows),
    ), patch(
        "src.infra.database.market.index_valuation."
        "create_index_valuation_repository",
        return_value=_IdxValRepo(VAL_ROWS),
    ):
        return json.loads(market_cap_growth_index(code, years=years).body)


def test_index_shape_and_ttm():
    body = _call_index()
    assert body["code"] == 0
    d = body["data"]
    assert d["kind"] == "index" and d["code"] == "000300"
    assert d["name"]                      # 配置名（沪深300）
    assert set(d["bars"]) == {"quarter", "cumulative", "ttm"}
    # 2024Q1 TTM = FY2023 + YTD2024Q1 − YTD2023Q1 = 60+14−10
    ttm = {b["report_date"]: b for b in d["bars"]["ttm"]}
    assert ttm["2024-03-31"]["revenue"] == 64.0
    # 2023 年报单季 = 60 − 10
    q = {b["report_date"]: b for b in d["bars"]["quarter"]}
    assert q["2023-12-31"]["revenue"] == 50.0
    # mv 对齐：2023-03-31 → 500000.1234 round 2 位；2023-12-31 → 取 ≤ 的
    # 最近点 2023-03-31（同值）
    mv = {p["report_date"]: p["total_mv"] for p in d["mv_series"]}
    assert mv["2023-03-31"] == 500000.12
    assert mv["2023-12-31"] == 500000.12
    assert d["sample_count"][0]["count"] == 300


def test_index_leap_today_no_value_error():
    """2-29 运行日：窗口起点须可构造（relativedelta），不得 ValueError。"""
    body = _call_index(today=_LEAP_TODAY)
    assert body["code"] == 0
    assert body["data"]["bars"]["quarter"]


def test_index_unknown_code_error():
    body = _call_index(code="999999")
    assert body["code"] != 0


# ── 窗口边界 fixture（今天已冻结为 2026-08-27 → start=2016-08-27，
# 恰好夹在 2016-06-30 与 2016-09-30 之间，任何日期运行结果恒定）──
EDGE_FIN_ROWS = [
    _fin_row("2016-06-30", 10.0, 1.0, 300),   # 窗口外基准（H1 累计）
    _fin_row("2016-09-30", 32.0, 3.2, 300),   # 窗口内首期 = Q3
    _fin_row("2016-12-31", 44.0, 4.4, 300),
]


def test_index_window_edge_quarter_diff():
    """窗口首期非Q1时须用窗口外上期差分，不得把累计值当单季透出。"""
    body = _call_index(fin_rows=EDGE_FIN_ROWS, years=10)
    assert body["code"] == 0
    d = body["data"]
    q = {b["report_date"]: b for b in d["bars"]["quarter"]}
    assert q["2016-09-30"]["revenue"] == 22.0   # 32 − 10
    assert q["2016-12-31"]["revenue"] == 12.0   # 44 − 32
    # 基准期不外泄：输出序列只含窗口内报告期
    assert [b["report_date"] for b in d["bars"]["cumulative"]] == [
        "2016-09-30", "2016-12-31"]
    assert len(d["mv_series"]) == 2
    assert [s["report_date"] for s in d["sample_count"]] == [
        "2016-09-30", "2016-12-31"]


class _SDetailRepo:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else [
            SimpleNamespace(report_date=date.fromisoformat("2023-03-31"),
                            revenue=3.0e10, net_profit_parent=3.0e9),
            SimpleNamespace(report_date=date.fromisoformat("2023-12-31"),
                            revenue=1.2e11, net_profit_parent=1.2e10),
            SimpleNamespace(report_date=date.fromisoformat("2024-03-31"),
                            revenue=4.0e10, net_profit_parent=4.0e9),
        ]

    def get_history(self, symbol, statement_type, start=None, end=None):
        # 同 _FinRepo：按 start 过滤，锁定取数窗口语义。
        assert statement_type == "income"
        if start is not None:
            return [r for r in self._rows if r.report_date >= start]
        return self._rows


class _SValRepo:
    def get_range(self, symbol, start, end):
        # 单查询替代 N 次 get_as_of（性能修复后 handler 只调 get_range）。
        return [
            SimpleNamespace(trade_date=date.fromisoformat("2016-08-01"),
                            total_mv=2.0e12),
            SimpleNamespace(trade_date=date.fromisoformat("2026-08-20"),
                            total_mv=3.0e12),
        ]


def _call_stock(symbol="sh600519", rows=None, years=10, today=_FROZEN_TODAY):
    from src.api.handler.financial_detail_handler import (
        market_cap_growth_stock,
    )
    _clear_cache()
    with _frozen_handler(today), patch(
        "src.infra.database.market.financial_full."
        "create_financial_detail_repository",
        return_value=_SDetailRepo(rows),
    ), patch(
        "src.infra.database.market.valuation."
        "create_stock_valuation_repository",
        return_value=_SValRepo(),
    ):
        return json.loads(market_cap_growth_stock(symbol, years=years).body)


def test_stock_units_yi_and_shape():
    body = _call_stock()
    assert body["code"] == 0
    d = body["data"]
    assert d["kind"] == "stock"
    cum = {b["report_date"]: b for b in d["bars"]["cumulative"]}
    assert cum["2023-03-31"]["revenue"] == 300.0   # 3e10 元 → 300 亿
    ttm = {b["report_date"]: b for b in d["bars"]["ttm"]}
    assert ttm["2024-03-31"]["revenue"] == 400.0 + 1200.0 - 300.0
    assert d["mv_series"][0]["total_mv"] == 20000.0  # 2e12 元 → 20000 亿（/1e8）
    assert "sample_count" not in d


def test_stock_non_a_empty_with_note():
    body = _call_stock(symbol="hk00700")
    assert body["code"] == 0
    assert body["data"]["bars"]["quarter"] == []
    assert body["data"]["note"]


EDGE_S_ROWS = [
    SimpleNamespace(report_date=date.fromisoformat("2016-06-30"),
                    revenue=1.0e10, net_profit_parent=1.0e9),
    SimpleNamespace(report_date=date.fromisoformat("2016-09-30"),
                    revenue=3.2e10, net_profit_parent=3.2e9),
]


def test_stock_window_edge_quarter_diff():
    """个股版同窗口边界：Q3 单季 = 9M − H1，基准期不外泄。"""
    body = _call_stock(rows=EDGE_S_ROWS, years=10)
    assert body["code"] == 0
    d = body["data"]
    q = {b["report_date"]: b for b in d["bars"]["quarter"]}
    assert q["2016-09-30"]["revenue"] == 220.0   # (3.2e10−1.0e10)/1e8
    assert [b["report_date"] for b in d["bars"]["cumulative"]] == [
        "2016-09-30"]
    assert len(d["mv_series"]) == 1


def test_stock_leap_today_no_value_error():
    """个股版同款：2-29 运行日窗口起点须可构造。"""
    body = _call_stock(today=_LEAP_TODAY)
    assert body["code"] == 0
    assert body["data"]["bars"]["quarter"]


def test_routes_registered():
    from src.api.router.financial_router import router
    paths = {r.path for r in router.routes}
    assert "/financial/market-cap-growth/index/{code}" in paths
    assert "/financial/market-cap-growth/stock/{symbol}" in paths


def test_index_partial_disclosure_hidden():
    """部分披露期(样本数<满覆盖80%)不出柱——披露季"34家H1−300家Q1"负柱假象。"""
    rows = [
        _fin_row("2025-12-31", 60.0, 6.0, 300),
        _fin_row("2026-03-31", 14.0, 1.4, 300),
        _fin_row("2026-06-30", 6.0, 0.5, 34),   # 中报仅 34/300 披露
    ]
    body = _call_index(fin_rows=rows)
    assert body["code"] == 0
    d = body["data"]
    for k in ("quarter", "cumulative", "ttm"):
        last = {b["report_date"]: b for b in d["bars"][k]}["2026-06-30"]
        assert last["revenue"] is None and last["net_profit"] is None, k
    # 市值线不受财报披露影响,照常返回(取 ≤2026-06-30 最近月度点)
    mv = {p["report_date"]: p["total_mv"] for p in d["mv_series"]}
    assert mv["2026-06-30"] == 550000.0
    assert "披露" in (d.get("note") or "")


def test_index_disclosure_boundary_kept():
    """披露率恰好 80%(240/300) 的期保留。"""
    rows = [
        _fin_row("2025-12-31", 60.0, 6.0, 300),
        _fin_row("2026-03-31", 14.0, 1.4, 300),
        _fin_row("2026-06-30", 30.0, 2.5, 240),
    ]
    body = _call_index(fin_rows=rows)
    cum = {b["report_date"]: b for b in body["data"]["bars"]["cumulative"]}
    assert cum["2026-06-30"]["revenue"] == 30.0
