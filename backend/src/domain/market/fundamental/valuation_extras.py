"""股票投资课程——估值方法补强（docs 15/17/22）纯函数。

簇 2 已实现 DCF（绝对估值）+ 均值±1σ 估值带（相对估值）。本模块补齐课程
强调但尚未覆盖的三类**相对/反推估值**工具：

    PEG 比率              PE / 增速(%); <1 低估、1~2 合理、>2 偏贵（成长股核心）
    隐含增长率（反推）    由当前股价反推市场隐含的永续增速，判断预期是否离谱
    股债性价比            盈利收益率(1/PE) vs 无风险利率，大类资产择时信号

全部纯函数，无 DB/IO 依赖。增速统一为小数（0.15 = 15%）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ── PEG 比率 ─────────────────────────────────────────────────────────────────

@dataclass
class PegRatio:
    peg: Optional[float]      # PE / 增速(%); None = 增速<=0 无法算 PEG
    verdict: str              # undervalued / fair / expensive / n/a


def peg_ratio(
    pe: Optional[float],
    earnings_growth: Optional[float],
) -> Optional[PegRatio]:
    """PEG = PE / 盈利增速(%)（docs 15/17）。

    课程逻辑：成长股不能只看 PE 绝对值，要看 PE 相对增速是否合理。
    彼得·林奇法则：PEG<1 低估、=1 合理、>1 偏贵、>2 明显高估。

    Args:
        pe:               市盈率（TTM 优先）。
        earnings_growth:  未来 3~5 年预期盈利增速（小数，0.20 = 20%）。

    Returns:
        PegRatio；PE<=0 或增速<=0 返回 None（PEG 对衰退/周期股无意义）。
    """
    if pe is None or earnings_growth is None or pe <= 0:
        return None
    if earnings_growth <= 0:
        # 负增长/零增长：PE 无增速消化，PEG 不适用
        return PegRatio(peg=None, verdict="n/a")
    peg = pe / (earnings_growth * 100.0)
    if peg < 1.0:
        verdict = "undervalued"
    elif peg <= 2.0:
        verdict = "fair"
    else:
        verdict = "expensive"
    return PegRatio(peg=peg, verdict=verdict)


# ── 隐含增长率（反推估值）────────────────────────────────────────────────────

@dataclass
class ImpliedGrowth:
    earnings_yield: float       # = 1 / PE
    implied_growth: Optional[float]  # = required_return − earnings_yield
    verdict: str                # 要求增速 vs 合理区间判断


def implied_growth_from_price(
    pe: Optional[float],
    required_return: float = 0.09,
    *,
    max_reasonable_growth: float = 0.25,
) -> Optional[ImpliedGrowth]:
    """由当前 PE 反推市场隐含的永续增速（doc 15）。

    Gordon 模型变形：``P = E / (r − g)`` → ``g = r − E/P = r − 盈利收益率``。
    解读：当前股价隐含公司必须永续以 ``implied_growth`` 增长才能满足
    要求回报。若隐含增速 >25%（远超任何公司永续能力），说明估值透支。

    Args:
        pe:               当前市盈率。
        required_return:  投资者要求回报率（默认 9%，= 股权风险溢价后）。
        max_reasonable_growth: 永续增速合理上限，默认 25%。

    Returns:
        ImpliedGrowth；PE<=0 返回 None。
    """
    if pe is None or pe <= 0:
        return None
    ey = 1.0 / pe
    implied = required_return - ey
    if implied > max_reasonable_growth:
        verdict = "stretched"          # 估值透支，隐含增速不现实
    elif implied < 0:
        verdict = "deep_value"         # 盈利收益率已超要求回报，零增长也划算
    else:
        verdict = "reasonable"
    return ImpliedGrowth(
        earnings_yield=ey,
        implied_growth=implied,
        verdict=verdict,
    )


# ── 股债性价比（盈利收益率 vs 无风险利率）──────────────────────────────────

@dataclass
class EquityBondParity:
    earnings_yield: float       # 1/PE
    bond_yield: float           # 无风险利率（如 10Y 国债）
    risk_premium: float         # 盈利收益率 − 国债（股的风险补偿）
    verdict: str                # equity_cheap / balanced / equity_expensive


def equity_bond_parity(
    pe: Optional[float],
    bond_yield: Optional[float],
    *,
    fair_premium: float = 0.03,
) -> Optional[EquityBondParity]:
    """盈利收益率(1/PE) vs 国债收益率 → 股债性价比（doc 22 / 美林）。

    课程逻辑：股票盈利收益率高于国债的风险溢价越大，股票越便宜；
    溢价消失甚至倒挂（如 2007/2015 顶部），说明股票相对债券已无吸引力。

    Args:
        pe:          股票/指数市盈率。
        bond_yield:  无风险利率（10Y 国债，小数）。
        fair_premium: 合理风险溢价中枢，默认 3%。

    Returns:
        EquityBondParity；输入非法返回 None。
        溢价 >5% ``equity_cheap`` / 1~5% ``balanced`` / <1% ``equity_expensive``。
    """
    if pe is None or bond_yield is None or pe <= 0 or bond_yield < 0:
        return None
    ey = 1.0 / pe
    premium = ey - bond_yield
    if premium >= fair_premium + 0.02:   # >=5%
        verdict = "equity_cheap"
    elif premium >= fair_premium - 0.02:  # 1%~5%
        verdict = "balanced"
    else:
        verdict = "equity_expensive"
    return EquityBondParity(
        earnings_yield=ey,
        bond_yield=bond_yield,
        risk_premium=premium,
        verdict=verdict,
    )
