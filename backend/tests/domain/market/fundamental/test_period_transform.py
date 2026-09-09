"""单季换算纯函数测试。"""
from datetime import date

from src.domain.market.fundamental.period_transform import (
    FLOW_FIELDS,
    STOCK_FIELDS,
    filter_year_only,
    transform_to_quarter,
)


def _row(rd: str, revenue=100.0, net_profit=10.0,
         total_assets=500.0, total_liabilities=200.0,
         operating_cost=80.0) -> dict:
    """构造一行报告期 dict（模拟 stock_financial_detail 的字段）。"""
    return {
        "report_date": date.fromisoformat(rd),
        "revenue": revenue,
        "operating_cost": operating_cost,
        "net_profit": net_profit,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
    }


def test_flow_fields_classified():
    """流量项含利润表/现金流科目；存量项含资产负债表科目。"""
    assert "revenue" in FLOW_FIELDS
    assert "net_profit" in FLOW_FIELDS
    assert "ocf" in FLOW_FIELDS
    assert "total_assets" in STOCK_FIELDS
    assert "inventory" in STOCK_FIELDS
    assert "cash_end" in STOCK_FIELDS


def test_quarterly_diff_within_year():
    """同年内累计值做差 → 单季值。"""
    rows = [
        _row("2024-03-31", revenue=100),   # Q1 累计
        _row("2024-06-30", revenue=250),   # H1 累计 → 单季 150
        _row("2024-09-30", revenue=400),   # Q3 累计 → 单季 150
        _row("2024-12-31", revenue=500),   # 年报 → 单季 100
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    assert out[0]["revenue"] == 100   # Q1 不变
    assert out[1]["revenue"] == 150
    assert out[2]["revenue"] == 150
    assert out[3]["revenue"] == 100


def test_quarterly_diff_resets_across_years():
    """跨年时，新一年的 Q1 不减上一年的年报（单季重置）。"""
    rows = [
        _row("2023-12-31", revenue=500),
        _row("2024-03-31", revenue=120),   # 2024Q1，不减 2023 年报
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    assert out[1]["revenue"] == 120


def test_stock_fields_not_differenced():
    """存量项（资产负债表）不做差，保持当期值。"""
    rows = [
        _row("2024-03-31", total_assets=500),
        _row("2024-06-30", total_assets=600),
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    assert out[1]["total_assets"] == 600   # 不做 600-500


def test_derived_margins_recomputed():
    """换算后毛利率用单季值重算。"""
    # Q1: revenue=100, cost=80 → 毛利20, 毛利率20%
    # H1: revenue=250(单季150), cost=200(单季120) → 毛利30, 毛利率20%
    rows = [
        _row("2024-03-31", revenue=100, operating_cost=80),
        _row("2024-06-30", revenue=250, operating_cost=200),
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    # Q1 单季毛利率
    assert out[0]["gross_margin"] == round(20 / 100 * 100, 4)
    # H1 单季：毛利 = 150-120 = 30，毛利率 = 30/150
    assert out[1]["gross_margin"] == round(30 / 150 * 100, 4)


def test_filter_year_only_keeps_december():
    rows = [
        _row("2023-03-31"),
        _row("2023-12-31"),
        _row("2024-06-30"),
        _row("2024-12-31"),
    ]
    out = filter_year_only(rows)
    assert [r["report_date"].isoformat() for r in out] == [
        "2023-12-31", "2024-12-31"
    ]


def test_quarterly_none_value_preserved():
    """None 字段做差时保持 None（不报错）。"""
    rows = [
        _row("2024-03-31", revenue=None),
        _row("2024-06-30", revenue=250),
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    # Q1 为 None → H1 无法做差，保持原累计值（降级为累计）
    assert out[1]["revenue"] == 250


def test_quarterly_first_period_of_year_unchanged():
    """每年第一期（Q1）保持累计值不变（无可减的上期）。"""
    rows = [
        _row("2023-12-31", revenue=999),
        _row("2024-03-31", revenue=100),
        _row("2024-06-30", revenue=250),
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    assert out[1]["revenue"] == 100   # 2024Q1 不变
