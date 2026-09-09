"""市值与业绩增长口径换算纯函数测试。"""
from datetime import date

from src.domain.market.fundamental.market_cap_growth import (
    align_mv,
    to_quarterly,
    to_ttm,
)


def _row(rd: str, revenue=None, net_profit=None) -> dict:
    return {
        "report_date": date.fromisoformat(rd),
        "revenue": revenue,
        "net_profit": net_profit,
    }


def test_to_quarterly_diff_and_year_reset():
    rows = [
        _row("2023-03-31", 10.0, 1.0),
        _row("2023-06-30", 25.0, 2.5),
        _row("2023-09-30", 40.0, 4.0),
        _row("2023-12-31", 60.0, 6.0),
        _row("2024-03-31", 14.0, 1.4),
        _row("2024-06-30", 30.0, 3.0),
    ]
    out = to_quarterly(rows)
    assert [r["revenue"] for r in out] == [10, 15, 15, 20, 14, 16]
    assert [r["net_profit"] for r in out] == [1.0, 1.5, 1.5, 2.0, 1.4, 1.6]
    # 不改调用方数据
    assert rows[1]["revenue"] == 25.0


def test_to_quarterly_empty_and_none_passthrough():
    assert to_quarterly([]) == []
    out = to_quarterly([_row("2023-03-31", None, None)])
    assert out[0]["revenue"] is None and out[0]["net_profit"] is None


def test_to_quarterly_none_breakpoint_not_degraded():
    """None 断点不降级为累计：基准期字段缺值时，下一期单季置 None。

    （transform_to_quarter 的 _diff_or_keep 会透出 cur=40 的累计量级，
    本口径后置拦截：9-30 单季既不是 40−10 也不是 40，而是 None。）
    """
    rows = [
        _row("2023-03-31", revenue=10.0),
        _row("2023-06-30", revenue=None),   # 断点
        _row("2023-09-30", revenue=40.0),   # 9M 累计
    ]
    out = to_quarterly(rows)
    assert out[0]["revenue"] == 10.0        # Q1 无基准，累计即单季
    assert out[1]["revenue"] is None        # 本期缺值
    assert out[2]["revenue"] is None        # 基准 6-30 缺值 → 不外推
    # net_profit 全程缺值：Q1 None，差分期同样 None
    assert out[2]["net_profit"] is None


def test_to_ttm_cross_year():
    rows = [
        _row("2023-03-31", 10.0, 1.0),
        _row("2023-06-30", 25.0, 2.5),
        _row("2023-09-30", 40.0, 4.0),
        _row("2023-12-31", 60.0, 6.0),
        _row("2024-03-31", 14.0, 1.4),
        _row("2024-06-30", 30.0, 3.0),
    ]
    out = to_ttm(rows)
    # 2023 各期缺 2022 年报与同期 → None；年报期 TTM=全年本身
    assert out[0]["revenue"] is None
    assert out[3]["revenue"] == 60.0
    # 2024Q1 = FY2023 + YTD2024Q1 − YTD2023Q1 = 60+14−10
    assert out[4]["revenue"] == 64.0
    # 2024H1 = 60+30−25
    assert out[5]["revenue"] == 65.0
    assert out[5]["net_profit"] == 6.0 + 3.0 - 2.5


def test_to_ttm_missing_dependency_none():
    rows = [
        _row("2023-06-30", 25.0),
        _row("2024-06-30", 30.0),   # 缺 2023 年报
    ]
    out = to_ttm(rows)
    assert out[0]["revenue"] is None   # 缺 2022 年报
    assert out[1]["revenue"] is None   # 缺 2023 年报


def test_align_mv_pick_latest_le():
    monthly = [
        {"date": "2023-01-31", "total_mv": 100.0},
        {"date": "2023-02-28", "total_mv": 110.0},
        {"date": "2023-03-31", "total_mv": 120.0},
    ]
    out = align_mv(monthly, [date(2023, 2, 15), "2023-03-31", "2022-12-31"])
    assert out == [
        {"report_date": "2023-02-15", "total_mv": 110.0},
        {"report_date": "2023-03-31", "total_mv": 120.0},
        {"report_date": "2022-12-31", "total_mv": None},
    ]
