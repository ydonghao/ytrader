"""股票投资课程——定价权与护城河评分（doc 09 商业模式 / 14 战略）纯函数。

簇 1 的 gross_margin_class 只看毛利率静态分档；本模块从**动态可持续性**视角
量化"定价权"与"护城河"——课程 doc 09 强调：好商业模式 = 能持续赚高毛利
（品牌/技术溢价、规模效应、转换成本），体现为毛利率**高水平 + 低波动 + 上行趋势**，
配合高 ROIC 与低有息负债。

    gross_margin_trend     毛利率时序趋势（斜率/是否改善/波动率）
    pricing_power_score    定价权综合分（水平 + 稳定性 + 趋势，0~100）
    moat_score             护城河综合分（定价权 + ROE + 低杠杆，0~100）

输入为毛利率历史序列 + 当前基本面快照。全部纯函数。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def _slope(values: list[float]) -> Optional[float]:
    """简单线性回归斜率（自变量为 0,1,2,…）；<2 点返回 None。"""
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    xm = sum(xs) / n
    ym = sum(values) / n
    num = sum((x - xm) * (y - ym) for x, y in zip(xs, values))
    den = sum((x - xm) ** 2 for x in xs)
    return num / den if den else 0.0


def _stdev(values: list[float]) -> Optional[float]:
    """样本标准差；<2 点返回 None。"""
    n = len(values)
    if n < 2:
        return None
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


# ── 毛利率趋势 ───────────────────────────────────────────────────────────────

@dataclass
class GrossMarginTrend:
    current: Optional[float]
    slope: Optional[float]        # 每期变动（小数）
    improving: Optional[bool]     # slope > 0
    volatility: Optional[float]   # 标准差
    stable: Optional[bool]        # volatility < 0.03


def gross_margin_trend(gross_margins: list[float]) -> GrossMarginTrend:
    """毛利率时序趋势分析（doc 09）。

    Args:
        gross_margins: 按时间**升序**的毛利率序列（小数）。

    Returns:
        GrossMarginTrend（current/slope/improving/volatility/stable）。
    """
    vals = [g for g in (gross_margins or []) if g is not None and math.isfinite(g)]
    if not vals:
        return GrossMarginTrend(None, None, None, None, None)
    slope = _slope(vals)
    vol = _stdev(vals)
    return GrossMarginTrend(
        current=vals[-1],
        slope=slope,
        improving=(slope is not None and slope > 0),
        volatility=vol,
        stable=(vol is not None and vol < 0.03),
    )


# ── 定价权评分 ──────────────────────────────────────────────────────────────

@dataclass
class PricingPower:
    score: int                # 0~100
    verdict: str              # strong / moderate / weak
    breakdown: dict           # 各维度得分明细


def pricing_power_score(
    gross_margins: list[float],
) -> Optional[PricingPower]:
    """定价权综合分（doc 09）= 毛利率水平 + 稳定性 + 趋势。

    课程：强定价权公司（茅台/片仔癀）毛利率持续 >60% 且多年稳定甚至上行；
    无定价权公司毛利率低且随成本大幅波动。

    评分维度（满分 100）：
        水平     当前毛利率：>60% 满分40 / 40~60% 得25 / 20~40% 得10 / <20% 得0
        稳定性   历史标准差：<3% 满分30 / <6% 得20 / <10% 得10 / 否则0
        趋势     斜率：上行30 / 持平15 / 下行0

    Args:
        gross_margins: 升序毛利率序列（至少 1 期；趋势/稳定性需 >=3 期）。

    Returns:
        PricingPower；空序列返回 None。
    """
    trend = gross_margin_trend(gross_margins)
    if trend.current is None:
        return None

    # 水平（40 分）
    gm = trend.current
    if gm > 0.60:
        level = 40
    elif gm > 0.40:
        level = 25
    elif gm > 0.20:
        level = 10
    else:
        level = 0

    # 稳定性（30 分）
    vol = trend.volatility
    if vol is None:
        stability = 15   # 仅 1~2 期无法判稳定性，给中性分
    elif vol < 0.03:
        stability = 30
    elif vol < 0.06:
        stability = 20
    elif vol < 0.10:
        stability = 10
    else:
        stability = 0

    # 趋势（30 分）
    if trend.improving is None:
        momentum = 15
    elif trend.improving:
        momentum = 30
    else:
        momentum = 0

    score = level + stability + momentum
    if score >= 70:
        verdict = "strong"
    elif score >= 40:
        verdict = "moderate"
    else:
        verdict = "weak"
    return PricingPower(
        score=score,
        verdict=verdict,
        breakdown={"level": level, "stability": stability, "momentum": momentum},
    )


# ── 护城河综合评分 ──────────────────────────────────────────────────────────

@dataclass
class MoatScore:
    score: int                # 0~100
    verdict: str              # wide / narrow / none
    pricing_power: Optional[PricingPower]
    breakdown: dict


def moat_score(
    gross_margins: list[float],
    fin: Optional[dict] = None,
    *,
    roic: Optional[float] = None,
) -> Optional[MoatScore]:
    """护城河综合分（doc 09/14）= 定价权(50%) + 资本回报(30%) + 低杠杆(20%)。

    课程护城河画像：高毛利（定价权）+ 高 ROIC（资本回报持续超 WACC）
    + 低有息负债（不靠杠杆驱动）。三者俱佳 = 宽护城河。

    Args:
        gross_margins: 升序毛利率序列（喂定价权）。
        fin:           当前基本面快照（取 net_profit/equity 算 ROE、debt_ratio）。
        roic:          ROIC（若已有 derived_metrics 结果，优先用；否则用 ROE proxy）。

    Returns:
        MoatScore（0~100）；定价权无法计算返回 None。
    """
    pp = pricing_power_score(gross_margins)
    if pp is None:
        return None

    # 资本回报（30 分）：优先 ROIC，否则 ROE=net_profit/equity
    fin = fin or {}
    ret = roic
    if ret is None:
        np_ = fin.get("net_profit")
        eq = fin.get("equity")
        ret = (np_ / eq) if (np_ is not None and eq and eq > 0) else None
    if ret is None:
        return_score = 15   # 无数据给中性
    elif ret >= 0.20:
        return_score = 30
    elif ret >= 0.15:
        return_score = 22
    elif ret >= 0.10:
        return_score = 12
    else:
        return_score = 0

    # 低杠杆（20 分）：debt_ratio 越低越好
    dr = fin.get("debt_ratio")
    if dr is None:
        leverage = 10
    elif dr < 0.30:
        leverage = 20
    elif dr < 0.50:
        leverage = 14
    elif dr < 0.70:
        leverage = 6
    else:
        leverage = 0

    # 定价权映射到 50 分制
    pp_50 = round(pp.score * 0.5)
    score = pp_50 + return_score + leverage
    if score >= 70:
        verdict = "wide"
    elif score >= 45:
        verdict = "narrow"
    else:
        verdict = "none"
    return MoatScore(
        score=score,
        verdict=verdict,
        pricing_power=pp,
        breakdown={
            "pricing_power_50": pp_50,
            "capital_return_30": return_score,
            "low_leverage_20": leverage,
        },
    )
