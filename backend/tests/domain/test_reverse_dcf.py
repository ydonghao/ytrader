"""Reverse DCF 纯函数测试。"""
from src.domain.market.fundamental.reverse_dcf import (
    implied_terminal_growth,
)


def test_implied_growth_solves_to_market_value():
    from src.domain.market.fundamental.dcf import dcf_intrinsic_value
    # 造目标: g=0.04 时的内在值当市值 → 反解应≈0.04
    fcf = 100.0
    target = dcf_intrinsic_value(
        fcf, growth_rate=0.08, terminal_growth=0.04,
        wacc=0.09, projection_years=10,
    )
    out = implied_terminal_growth(
        target, wacc=0.09, growth_rate=0.08,
        latest_fcf=fcf, projection_years=10,
    )
    assert out["status"] == "ok"
    assert abs(out["implied_terminal_growth"] - 0.04) < 1e-4


def test_implied_growth_out_of_range_high():
    # 市值远超 g 上限的内在值 → 超出区间
    from src.domain.market.fundamental.dcf import dcf_intrinsic_value
    ceiling = dcf_intrinsic_value(
        100.0, growth_rate=0.08, terminal_growth=0.085,
        wacc=0.09, projection_years=10,
    )
    out = implied_terminal_growth(
        ceiling * 1.5, wacc=0.09, growth_rate=0.08,
        latest_fcf=100.0,
    )
    assert out["status"] == "above_range"


def test_implied_growth_below_range():
    # 市值低于 g=-10% 的内在值 → 深度悲观
    from src.domain.market.fundamental.dcf import dcf_intrinsic_value
    floor = dcf_intrinsic_value(
        100.0, growth_rate=0.08, terminal_growth=-0.10,
        wacc=0.09, projection_years=10,
    )
    out = implied_terminal_growth(
        floor * 0.5, wacc=0.09, growth_rate=0.08,
        latest_fcf=100.0,
    )
    assert out["status"] == "below_range"
