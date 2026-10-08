"""capital_allocation 纯函数测试。"""
from src.domain.market.fundamental.capital_allocation import (
    capital_allocation,
)


def test_friendly_full_inputs():
    r = capital_allocation(
        dividend_years=[True] * 8, payout_pct=40.0, roic_pct=15.0,
        holder_change_pct=-15.0,
    )
    assert r["consecutive_dividend_years"] == 8
    assert r["iron_rooster"] is False
    assert r["score"] >= 70
    assert r["verdict"] == "shareholder_friendly"
    assert r["holder_change"]["label"] == "集中"


def test_consecutive_years_count_from_recent():
    # 中间断一年：自最近往前连续 3 年
    r = capital_allocation(
        dividend_years=[True, True, False, True, True, True],
        payout_pct=30.0, roic_pct=10.0, holder_change_pct=None,
    )
    assert r["consecutive_dividend_years"] == 3


def test_iron_rooster_with_low_roic_is_concerning():
    r = capital_allocation(
        dividend_years=[False] * 9, payout_pct=0.0, roic_pct=4.0,
        holder_change_pct=None,
    )
    assert r["iron_rooster"] is True
    assert r["verdict"] == "concerning"   # 硬规则


def test_growth_no_dividend_high_roic_ok():
    r = capital_allocation(
        dividend_years=[False] * 5, payout_pct=0.0, roic_pct=20.0,
        holder_change_pct=None,
    )
    # 无分红但 ROIC 20：非铁公鸡判定需≥8年数据；5年False→连续0
    assert r["verdict"] != "concerning"


def test_payout_zones():
    high = capital_allocation([True] * 5, 95.0, 10.0, None)
    assert any("不可持续" in x for x in high["flags"])
    ok = capital_allocation([True] * 5, 40.0, 10.0, None)
    assert not any("不可持续" in x for x in ok["flags"])


def test_roic_zones():
    low = capital_allocation([True] * 5, 30.0, 5.0, None)
    assert any("毁灭" in x for x in low["flags"])
    hi = capital_allocation([True] * 5, 30.0, 15.0, None)
    assert not any("毁灭" in x for x in hi["flags"])


def test_holder_change_zones():
    up = capital_allocation([True] * 5, 40.0, 10.0, 40.0)
    assert up["holder_change"]["label"] == "分散"
    flat = capital_allocation([True] * 5, 40.0, 10.0, 5.0)
    assert flat["holder_change"]["label"] == "平稳"


def test_missing_inputs_normalize():
    r = capital_allocation(None, None, None, None)
    assert r["score"] is None and r["verdict"] == "unknown"
    r2 = capital_allocation([True] * 5, None, 12.0, None)
    assert r2["score"] is not None  # 剩余维度归一化
