"""src.domain.market.strategy.position_sizing 纯函数测试。"""
import math

from src.domain.market.strategy.position_sizing import (
    LadderRung,
    SizingResult,
    apply_buy_fill,
    apply_sell_fill,
    plan_laddering,
    size_by_margin,
)


# ── size_by_margin: margin 分档 ────────────────────────────────────────────────


def test_size_below_min_margin_skips():
    r = size_by_margin(0.05, 1_000_000, price=10.0)
    assert r.skipped is True
    assert r.quantity == 0
    assert "min_margin" in r.reason


def test_size_at_min_margin_is_about_zero():
    # margin 恰好等于 min_margin → raw=0 → weight=0 → 不足一手
    r = size_by_margin(0.10, 1_000_000, price=10.0, min_margin=0.10)
    assert r.weight == 0.0
    assert r.quantity == 0
    assert r.skipped is True


def test_size_max_margin_caps_at_max_weight():
    r = size_by_margin(1.0, 1_000_000, price=10.0, max_weight=0.25)
    assert r.skipped is False
    assert math.isclose(r.weight, 0.25)
    # 0.25 * 1_000_000 / 10 = 25000 → 取整到 100 的倍数 = 25000
    assert r.quantity == 25000
    assert math.isclose(r.target_value, 250_000.0)


def test_size_mid_margin_is_linear():
    # min_margin=0.1, margin=0.55 → raw=(0.55-0.1)/0.9=0.5 → weight=0.125
    r = size_by_margin(0.55, 1_000_000, price=10.0, max_weight=0.25,
                       min_margin=0.10)
    assert math.isclose(r.weight, 0.125, rel_tol=1e-9)
    # 0.125 * 1e6 = 125000; /10 = 12500 股(已整百)
    assert r.quantity == 12500


def test_size_clamps_margin_above_one():
    r = size_by_margin(1.5, 1_000_000, price=10.0, max_weight=0.25)
    # 等同 margin=1.0
    assert math.isclose(r.weight, 0.25)
    assert r.quantity == 25000


# ── size_by_margin: max_weight 约束 + 已持仓 ─────────────────────────────────


def test_max_weight_respected_with_existing_position():
    # 已持有 15000 股 @10 = 150000 = 15% ; max_weight 0.25 → 剩 10% 可加
    r = size_by_margin(
        1.0, 1_000_000, current_position=15000, price=10.0,
        max_weight=0.25,
    )
    assert math.isclose(r.weight, 0.10)
    # 0.10 * 1e6 / 10 = 10000 股
    assert r.quantity == 10000


def test_at_max_weight_with_full_position_skips():
    # 已持仓 25000 股 @10 = 25% = max_weight → 无可加仓
    r = size_by_margin(
        1.0, 1_000_000, current_position=25000, price=10.0,
        max_weight=0.25,
    )
    assert r.skipped is True
    assert r.quantity == 0
    assert "max_weight" in r.reason


# ── size_by_margin: 波动率缩放 ─────────────────────────────────────────────────


def test_volatility_scaling_reduces_size():
    base = size_by_margin(1.0, 1_000_000, price=10.0, max_weight=0.25)
    high_vol = size_by_margin(
        1.0, 1_000_000, price=10.0, max_weight=0.25, volatility=0.50,
    )  # vol_reference=0.25 → scale=0.5
    assert math.isclose(high_vol.vol_scale, 0.5)
    assert high_vol.quantity == base.quantity // 2


def test_volatility_floor_prevents_zero():
    # 极高波动(=10x reference)→ scale 被 vol_floor=0.25 截断
    r = size_by_margin(
        1.0, 1_000_000, price=10.0, max_weight=0.25,
        volatility=10.0, vol_reference=0.25, vol_floor=0.25,
    )
    assert math.isclose(r.vol_scale, 0.25)
    assert r.quantity > 0


def test_no_volatility_means_no_scaling():
    r = size_by_margin(1.0, 1_000_000, price=10.0, max_weight=0.25)
    assert math.isclose(r.vol_scale, 1.0)


# ── size_by_margin: lot 取整 ───────────────────────────────────────────────────


def test_lot_rounding_floors_below_one_lot():
    # weight 很小: 0.02 * 1e6 = 20000; / 500 (price) = 40 股 < 100 → 0
    r = size_by_margin(
        0.20, 1_000_000, price=500.0, max_weight=0.25, min_margin=0.10,
    )
    # raw=(0.2-0.1)/0.9≈0.111 → weight≈0.0278 → target≈27778 → /500≈55股 → 0
    assert r.quantity == 0
    assert r.skipped is True
    assert "lot" in r.reason


def test_zero_or_negative_capital_skips():
    assert size_by_margin(0.9, 0, price=10.0).skipped is True
    assert size_by_margin(0.9, -5, price=10.0).skipped is True


def test_sizing_result_bool_flag():
    assert not bool(size_by_margin(0.05, 1_000_000, price=10.0))
    assert bool(size_by_margin(1.0, 1_000_000, price=10.0))


# ── plan_laddering ────────────────────────────────────────────────────────


def test_laddering_returns_initial_plus_drop_rungs():
    rungs = plan_laddering(
        0.30, price=10.0, total_capital=1_000_000,
        steps=3, step_drop=0.05,
    )
    assert len(rungs) == 4
    assert all(isinstance(r, LadderRung) for r in rungs)
    # 初始档价格=现价, 跌幅 0
    assert math.isclose(rungs[0].price_level, 10.0)
    assert math.isclose(rungs[0].drop_pct, 0.0)
    # 价格逐档下跌
    assert rungs[1].price_level < rungs[0].price_level
    assert rungs[-1].price_level < rungs[1].price_level


def test_laddering_buys_more_as_price_drops():
    rungs = plan_laddering(
        0.40, price=10.0, total_capital=1_000_000,
        steps=3, step_drop=0.10, max_weight=0.25,
    )
    adds = [r.add_quantity for r in rungs]
    # 初始档 margin=0.40; 后续档 margin 升高 → 加仓量递增(越跌越买)
    assert adds[-1] >= adds[0]
    assert all(q >= 0 for q in adds)
    # cumulative 单调非减
    cums = [r.cumulative_quantity for r in rungs]
    assert cums == sorted(cums)


def test_laddering_includes_current_position_in_cumulative():
    rungs = plan_laddering(
        0.40, price=10.0, total_capital=1_000_000,
        current_position=500, steps=2,
    )
    # 初始档累计 >= 已持仓 500
    assert rungs[0].cumulative_quantity >= 500


def test_laddering_empty_when_margin_below_min():
    rungs = plan_laddering(
        0.05, price=10.0, total_capital=1_000_000, min_margin=0.10,
    )
    assert rungs == []


def test_laddering_empty_when_price_invalid():
    assert plan_laddering(0.40, price=0.0, total_capital=1e6) == []
    assert plan_laddering(0.40, price=10.0, total_capital=0) == []


# ── 成交回写算术 ───────────────────────────────────────────────────────────────


def test_apply_buy_fill_new_position():
    qty, avg = apply_buy_fill(0, 0.0, 100, 12.5)
    assert qty == 100
    assert math.isclose(avg, 12.5)


def test_apply_buy_fill_weighted_average():
    # 100@10 + 200@16 → 300 @ (1000+3200)/300 = 14
    qty, avg = apply_buy_fill(100, 10.0, 200, 16.0)
    assert qty == 300
    assert math.isclose(avg, 14.0)


def test_apply_buy_fill_zero_qty_unchanged():
    qty, avg = apply_buy_fill(100, 10.0, 0, 99.0)
    assert qty == 100
    assert math.isclose(avg, 10.0)


def test_apply_sell_fill_partial():
    # 300@14, 卖 100@18 → 剩 200@14, realized=(18-14)*100=400
    qty, avg, realized = apply_sell_fill(300, 14.0, 100, 18.0)
    assert qty == 200
    assert math.isclose(avg, 14.0)
    assert math.isclose(realized, 400.0)


def test_apply_sell_fill_full_clears_position():
    # 全平 100@10 卖 100@12 → 0 股, avg=0, realized=200
    qty, avg, realized = apply_sell_fill(100, 10.0, 100, 12.0)
    assert qty == 0
    assert avg == 0.0
    assert math.isclose(realized, 200.0)


def test_apply_sell_fill_clamps_oversell():
    # 卖出超过持仓只平掉持仓部分
    qty, avg, realized = apply_sell_fill(100, 10.0, 999, 12.0)
    assert qty == 0
    assert math.isclose(realized, 200.0)


def test_apply_sell_fill_loss():
    qty, avg, realized = apply_sell_fill(100, 10.0, 50, 8.0)
    assert qty == 50
    assert math.isclose(realized, -100.0)
