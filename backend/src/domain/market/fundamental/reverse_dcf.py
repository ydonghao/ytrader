"""Reverse DCF：反解市场隐含预期（价值投资三期 G1）。

给定市值与其他假设，二分求解使内在值=市值的永续增长率——
"市场先生当前在定价什么"。单调性：g 越大内在值越大，可二分。
"""
from typing import Optional

from src.domain.market.fundamental.dcf import dcf_intrinsic_value


def implied_terminal_growth(
    market_value: float, *, wacc: float = 0.09,
    growth_rate: float = 0.08, latest_fcf: float = 0.0,
    projection_years: int = 10, g_lo: float = -0.10,
    g_hi: Optional[float] = None,
) -> dict:
    """二分解隐含永续增长 g∈[g_lo, wacc-0.005]。"""
    if g_hi is None:
        g_hi = wacc - 0.005
    if not market_value or market_value <= 0 or latest_fcf <= 0:
        return {"status": "invalid_input",
                "implied_terminal_growth": None}

    def _iv(g):
        return dcf_intrinsic_value(
            latest_fcf, growth_rate=growth_rate, terminal_growth=g,
            wacc=wacc, projection_years=projection_years,
        )

    lo_v, hi_v = _iv(g_lo), _iv(g_hi)
    if lo_v is None or hi_v is None:
        return {"status": "invalid_input",
                "implied_terminal_growth": None}
    if market_value > hi_v:
        return {"status": "above_range",
                "implied_terminal_growth": None,
                "message": "现价隐含预期超出合理上限"
                           f"（g>{g_hi:.1%}），警惕故事溢价"}
    if market_value < lo_v:
        return {"status": "below_range",
                "implied_terminal_growth": None,
                "message": "现价隐含预期低于 g=-10%（深度悲观定价），"
                           "检查 FCF 是否异常"}
    for _ in range(60):
        mid = (g_lo + g_hi) / 2
        v = _iv(mid)
        if v is None:
            break
        if v > market_value:
            g_hi = mid
        else:
            g_lo = mid
    g = (g_lo + g_hi) / 2
    return {
        "status": "ok",
        "implied_terminal_growth": round(g, 5),
        "implied_growth_pct": round(g * 100, 2),
        "fcf_yield_pct": round(latest_fcf / market_value * 100, 2),
        "assumptions": {
            "wacc": wacc, "stage_growth": growth_rate,
            "projection_years": projection_years,
        },
        "note": "隐含永续增长=当前价格定价的长期预期；与自己的"
                "假设对照，差距即分歧所在。",
    }
