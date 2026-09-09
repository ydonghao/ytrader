"""股票投资课程——中美利差与资本流动信号（doc 02/31）纯函数。

簇 4 的 money_supply_gap 看国内 M2/GDP；本模块看**中美国债利差**——课程 doc 02/31
强调：中美利差是跨境资本流动的核心驱动，影响汇率与 A 股外资流向。

    cn_us_yield_differential   中美国债利差（中国 10Y − 美国 10Y）
    capital_flow_signal        利差走阔/收窄 → 资本流入/流出压力
    rate_trend                 利差时序趋势（连续走阔/收窄）

数据：中国 10Y 国债收益率来自 akshare bond_china_yield；美国 10Y 可经
fred_provider 或宏观同步。可存为 macro_indicator（cn_bond_10y / us_bond_10y）。
全部纯函数，收益率为小数（0.025 = 2.5%）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class YieldDifferential:
    cn_yield: float
    us_yield: float
    differential: float        # cn − us（正 = 中国利率更高）
    inverted: bool             # 倒挂（cn < us）


def cn_us_yield_differential(
    cn_10y: Optional[float], us_10y: Optional[float]
) -> Optional[YieldDifferential]:
    """中美国债 10 年期利差（doc 02/31）。

    Args:
        cn_10y: 中国 10Y 国债收益率（小数）。
        us_10y: 美国 10Y 国债收益率（小数）。

    Returns:
        YieldDifferential；输入缺失返回 None。differential>0 中国利率更高
        （吸引外资），<0 中美利差倒挂（资本流出压力）。
    """
    if cn_10y is None or us_10y is None:
        return None
    diff = cn_10y - us_10y
    return YieldDifferential(
        cn_yield=cn_10y, us_yield=us_10y,
        differential=diff, inverted=diff < 0,
    )


@dataclass
class CapitalFlowSignal:
    differential: float
    prev_differential: Optional[float]
    widening: Optional[bool]    # 利差走阔（中国相对更吸引）
    verdict: str                # inflow_pressure / outflow_pressure / neutral


def capital_flow_signal(
    cn_10y: Optional[float],
    us_10y: Optional[float],
    prev_cn_10y: Optional[float] = None,
    prev_us_10y: Optional[float] = None,
) -> Optional[CapitalFlowSignal]:
    """中美利差变化 → 资本流动信号（doc 31）。

    课程逻辑：中美利差走阔（中国利率相对上升）→ 人民币资产吸引力增强、
    资本流入压力（利好 A 股/债）；利差收窄或倒挂 → 资本流出压力。

    Args:
        cn_10y/us_10y:         当期中美国债 10Y 收益率。
        prev_cn_10y/prev_us_10y: 上期收益率（算趋势，可选）。

    Returns:
        CapitalFlowSignal；当期缺数据返回 None。
    """
    cur = cn_us_yield_differential(cn_10y, us_10y)
    if cur is None:
        return None
    prev_diff = None
    widening = None
    if prev_cn_10y is not None and prev_us_10y is not None:
        prev_diff = prev_cn_10y - prev_us_10y
        widening = cur.differential > prev_diff

    if cur.inverted:
        verdict = "outflow_pressure"
    elif widening is True:
        verdict = "inflow_pressure"
    elif widening is False:
        verdict = "outflow_pressure"
    else:
        verdict = "neutral"
    return CapitalFlowSignal(
        differential=cur.differential,
        prev_differential=prev_diff,
        widening=widening,
        verdict=verdict,
    )


@dataclass
class RateTrend:
    latest: float
    slope: Optional[float]
    widening: Optional[bool]
    consecutive_widening: int
    consecutive_narrowing: int
    verdict: str               # widening / narrowing / stable


def rate_trend(differentials: list[float]) -> Optional[RateTrend]:
    """中美利差时序趋势（doc 31）。

    Args:
        differentials: 升序的中美利差序列（小数）。

    Returns:
        RateTrend；序列<2 返回 None。
    """
    vals = [d for d in (differentials or []) if d is not None]
    if len(vals) < 2:
        return None
    latest = vals[-1]
    # 连续走阔/收窄
    cw = cn = 0
    for i in range(len(vals) - 1, 0, -1):
        delta = vals[i] - vals[i - 1]
        if delta > 0:
            if cn == 0:
                cw += 1
            else:
                break
        elif delta < 0:
            if cw == 0:
                cn += 1
            else:
                break
        else:
            break
    n = len(vals)
    xs = list(range(n))
    xm = sum(xs) / n
    ym = sum(vals) / n
    num = sum((x - xm) * (y - ym) for x, y in zip(xs, vals))
    den = sum((x - xm) ** 2 for x in xs)
    slope = num / den if den else 0.0

    if cw >= 2:
        verdict = "widening"
    elif cn >= 2:
        verdict = "narrowing"
    else:
        verdict = "stable"
    return RateTrend(
        latest=latest, slope=slope, widening=(slope > 0),
        consecutive_widening=cw, consecutive_narrowing=cn, verdict=verdict,
    )
