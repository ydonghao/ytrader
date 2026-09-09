"""
预期收益率分解（纯函数）
=====================
长期持有收益率 ≈ 业绩增长率 + 股息率 + 估值变化率（课程 17 集）。
作者合理预期目标：年化 15%，其中约 3% 由分红实现、12% 靠业绩增长 →
**所选公司业绩增速须高于 10%**。高股息弥补不了业绩下滑（格力：股息率 7% 但
业绩零增长且下滑 → 长期达不到理想收益）。

各项以百分数输入（如增速 12.0 = 12%），估值变化默认 0（不确定项放一边）。
"""
from __future__ import annotations

from typing import Optional

RETURN_TARGET = 15.0        # 合理预期年化目标
GROWTH_FLOOR = 10.0         # 隐含业绩增速门槛（支撑 15% 目标）


def _num(x) -> Optional[float]:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def expected_return(
    growth_rate: float,
    dividend_yield: float,
    valuation_drift: float = 0.0,
) -> dict:
    """长期预期年化收益率分解。

    Args:
        growth_rate:      业绩增速(%)，近 3–5 年营收/净利 CAGR 或预测值。
        dividend_yield:   股息率(%, TTM)。
        valuation_drift:  估值年化变化(%)，默认 0（保守，把不确定项放一边）。

    Returns:
        {growth, dividend_yield, valuation_drift, expected_return,
         meets_target(≥15%), implied_growth_floor_met(增速≥10%)}。
    缺失输入按 0 计。
    """
    g = _num(growth_rate) or 0.0
    d = _num(dividend_yield) or 0.0
    v = _num(valuation_drift) or 0.0
    total = g + d + v
    return {
        "growth": g,
        "dividend_yield": d,
        "valuation_drift": v,
        "expected_return": round(total, 4),
        "meets_target": total >= RETURN_TARGET,
        "implied_growth_floor_met": g >= GROWTH_FLOOR,
    }
