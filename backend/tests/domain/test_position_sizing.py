"""position_sizing 纯函数测试。"""
from src.domain.market.fundamental.position_sizing import (
    suggest_position_size,
)


def test_strong_tier_and_cap():
    r = suggest_position_size(80, 30.0)
    assert r["tier"] == "strong"
    assert r["band"] == {"low": 15.0, "high": 20.0}
    # p = 0.45+0.12+0.075 = 0.645; U=30/70*100=42.86
    assert abs(r["p"] - 0.645) < 1e-9
    assert abs(r["upside_pct"] - 42.857) < 0.01
    # kelly = (0.645/0.25 - 0.355/0.4286)*100 = 175.2 → half 87.6
    assert r["kelly_full_pct"] > 100
    # suggested = min(clamp(15,20,87.6), 20) = 20
    assert r["suggested_pct"] == 20.0
    assert r["capped_by"] == "single_cap"


def test_medium_tier():
    r = suggest_position_size(65, 18.0)
    assert r["tier"] == "medium"
    assert r["band"] == {"low": 8.0, "high": 12.0}
    assert r["suggested_pct"] == 12.0   # kelly_half 仍高于区间上界
    assert r["capped_by"] == "band_high"


def test_weak_tier_low_kelly():
    r = suggest_position_size(55, 8.0)
    assert r["tier"] == "weak"
    # p = 0.45+0.0825+0.02 = 0.5525; U=8/92*100=8.70
    # kelly = (0.5525/0.25 - 0.4475/0.087)*100 = (2.21-5.14)*100 < 0 → 0
    assert r["kelly_full_pct"] == 0.0
    assert r["suggested_pct"] == 0.0
    assert r["capped_by"] == "kelly_zero"


def test_p_bounds():
    # 公式上限 0.45+0.15+0.10 = 0.70（clamp 0.75 不可达，防御性存在）
    r = suggest_position_size(100, 60.0)
    assert r["p"] == 0.70
    r2 = suggest_position_size(0, 0.0)
    assert r2["p"] == 0.45


def test_zero_margin_means_no_bet():
    r = suggest_position_size(80, 0.0)
    assert r["upside_pct"] == 0.0
    assert r["suggested_pct"] == 0.0


def test_ladder_structure_and_amounts():
    r = suggest_position_size(80, 30.0, total_capital=1000000,
                              current_price=100.0)
    assert [l["drop_pct"] for l in r["ladder"]] == [0, -8, -16]
    assert [l["weight_of_position"] for l in r["ladder"]] == [0.4, 0.3, 0.3]
    # 建议仓位20%×100万=20万; 第一档 8万 @100 → 800股(整百)
    l0 = r["ladder"][0]
    assert l0["amount"] == 80000.0
    assert l0["shares"] == 800
    l1 = r["ladder"][1]
    assert l1["price_level"] == 92.0
    assert l1["amount"] == 60000.0


def test_data_missing():
    r = suggest_position_size(None, 30.0)
    assert r["data_missing"] is True and r["suggested_pct"] is None
    r2 = suggest_position_size(80, None)
    assert r2["data_missing"] is True and r2["suggested_pct"] is None


def test_ladder_min_one_lot_for_high_price():
    # 8万 × 茅台级高价：不足一手 → 至少一手
    r = suggest_position_size(80, 30.0, total_capital=1000000,
                              current_price=1257.0)
    assert r["ladder"][0]["shares"] == 100
