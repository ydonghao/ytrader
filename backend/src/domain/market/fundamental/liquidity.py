"""股票投资课程——流动性比率（docs 12/19）纯函数。

簇 1 的 cash_coverage_short_debt 只看"现金 vs 短期刚性债务"；本模块补齐
课程 doc 12/19 强调的**完整短期偿债能力**四件套——流动比率/速动比率/
现金比率/营运资本。这是偿债能力分析的基础，quality.py 未覆盖。

    current_ratio    流动资产 / 流动负债  （>2 强、1.5~2 健康、<1 风险）
    quick_ratio      (流动资产−存货) / 流动负债  （>1 健康）
    cash_ratio       (货币资金+交易性金融资产) / 流动负债  （>0.5 健康）
    working_capital  流动资产 − 流动负债  （>0 才能覆盖短期债务）

数据：流动资产/负债合计在 detail JSONB（流动资产合计/流动负债合计），
货币资金/交易性金融资产/存货为固定列或 detail 科目。全部纯函数。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LiquidityRatios:
    current_ratio: Optional[float]
    quick_ratio: Optional[float]
    cash_ratio: Optional[float]
    working_capital: Optional[float]
    verdict: str          # strong / healthy / stretched / risky


def current_ratio(
    current_assets: Optional[float], current_liabilities: Optional[float]
) -> Optional[float]:
    """流动比率 = 流动资产 / 流动负债。"""
    if current_assets is None or current_liabilities is None or current_liabilities <= 0:
        return None
    return current_assets / current_liabilities


def quick_ratio(
    current_assets: Optional[float],
    inventory: Optional[float],
    current_liabilities: Optional[float],
) -> Optional[float]:
    """速动比率 = (流动资产 − 存货) / 流动负债（剔除变现慢的存货）。"""
    if (current_assets is None or inventory is None or current_liabilities is None
            or current_liabilities <= 0):
        return None
    return (current_assets - inventory) / current_liabilities


def cash_ratio(
    monetary_funds: Optional[float],
    trading_financial_assets: Optional[float],
    current_liabilities: Optional[float],
) -> Optional[float]:
    """现金比率 = (货币资金 + 交易性金融资产) / 流动负债（最保守口径）。"""
    if current_liabilities is None or current_liabilities <= 0:
        return None
    cash = (monetary_funds or 0.0) + (trading_financial_assets or 0.0)
    return cash / current_liabilities


def working_capital(
    current_assets: Optional[float], current_liabilities: Optional[float]
) -> Optional[float]:
    """营运资本 = 流动资产 − 流动负债（>0 才能覆盖短期债务）。"""
    if current_assets is None or current_liabilities is None:
        return None
    return current_assets - current_liabilities


def compute_liquidity(
    current_assets: Optional[float],
    current_liabilities: Optional[float],
    *,
    inventory: Optional[float] = None,
    monetary_funds: Optional[float] = None,
    trading_financial_assets: Optional[float] = None,
) -> LiquidityRatios:
    """流动性四件套聚合。

    Args:
        current_assets/current_liabilities: 流动资产/负债合计。
        inventory:                          存货（速动比率用）。
        monetary_funds:                     货币资金（现金比率用）。
        trading_financial_assets:           交易性金融资产（现金比率用）。

    Returns:
        LiquidityRatios（各项缺失为 None）。verdict 综合判定：
        current>2 或 quick>1 → strong；current>=1.5 → healthy；
        current>=1 → stretched；<1 → risky。
    """
    cr = current_ratio(current_assets, current_liabilities)
    qr = quick_ratio(current_assets, inventory, current_liabilities)
    casr = cash_ratio(monetary_funds, trading_financial_assets, current_liabilities)
    wc = working_capital(current_assets, current_liabilities)

    if cr is None:
        verdict = "risky"   # 无数据无法判偿债，保守
    elif cr >= 2.0 or (qr is not None and qr >= 1.5):
        verdict = "strong"
    elif cr >= 1.5:
        verdict = "healthy"
    elif cr >= 1.0:
        verdict = "stretched"
    else:
        verdict = "risky"
    return LiquidityRatios(
        current_ratio=cr, quick_ratio=qr, cash_ratio=casr,
        working_capital=wc, verdict=verdict,
    )
