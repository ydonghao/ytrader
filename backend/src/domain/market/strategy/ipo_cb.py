"""股票投资课程簇 5——打新 / 可转债（docs 28/29）纯函数。

课程把"A 股打新"和"可转债打新/投资"称为散户福利。本模块实现三类计算器：

    5.1 打新额度与中签概率
        沪市 1 万市值 = 1 个申购单位 = 1000 股
        深市 5000 市值 = 1 个申购单位 = 500 股
        P(≥1 签) = 1 − (1 − p)^N
    5.2 可转债转股溢价率
        转股价值 = 正股价 × (100 / 转股价)
        溢价率  = 可转债市价 / 转股价值 − 1
    5.3 可转债三条款预警（相对转股价的触发比例）
        下修触发  正股价 / 转股价 ≤ 85%
        强制赎回  正股价 / 转股价 ≥ 130%（持续）
        回售触发  正股价 / 转股价 ≤ 70%

5.1 为纯数学（无需数据源）；5.2/5.3 需要可转债基本参数（正股价/转股价/市价），
可由 akshare ``bond_zh_cov`` + 正股行情供给（同步管道另建）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ── 5.1 打新额度与中签概率 ───────────────────────────────────────────────────

# 沪/深两市申购单位口径（市值门槛 / 每单位股数）。
IPO_UNIT_RULES = {
    "sh": {"value_per_unit": 10_000.0, "shares_per_unit": 1000},
    "sz": {"value_per_unit": 5_000.0, "shares_per_unit": 500},
}


@dataclass
class IpoLotAllocation:
    market: str
    market_value: float
    units: int                # 申购单位数
    max_shares: int           # = units × shares_per_unit


def ipo_lot_allocation(market_value: float, market: str = "sh") -> Optional[IpoLotAllocation]:
    """按持仓市值计算打新申购单位与顶格股数（doc 28）。

    Args:
        market_value: T-2 前 20 日日均持仓市值（元）。
        market:       ``"sh"`` 沪市 / ``"sz"`` 深市。

    Returns:
        IpoLotAllocation；市值<=0 或未知市场返回 None。
    """
    rule = IPO_UNIT_RULES.get(market)
    if rule is None or market_value is None or market_value <= 0:
        return None
    units = int(market_value // rule["value_per_unit"])
    return IpoLotAllocation(
        market=market,
        market_value=market_value,
        units=units,
        max_shares=units * rule["shares_per_unit"],
    )


def ipo_win_probability(base_prob: float, units: int) -> Optional[float]:
    """N 个申购单位的中签概率：P(≥1 签) = 1 − (1 − p)^N（doc 28）。

    Args:
        base_prob: 单个单位中签概率（小数，如 0.01）。
        units:     申购单位数。

    Returns:
        至少中 1 签的概率；输入非法返回 None。
    """
    if (base_prob is None or units is None or units <= 0
            or base_prob < 0 or base_prob > 1):
        return None
    if base_prob == 1.0:
        return 1.0
    return 1.0 - math.pow(1.0 - base_prob, units)


# ── 5.2 可转债转股溢价率 ─────────────────────────────────────────────────────

@dataclass
class CbConversionPremium:
    conversion_value: float     # 转股价值 = 正股价 × (100/转股价)
    premium: float              # 溢价率 = 市价/转股价值 − 1
    verdict: str                # discount(折价<0) / fair(0~10%) / expensive(>10%)


def cb_conversion_premium(
    stock_price: Optional[float],
    conv_price: Optional[float],
    cb_price: Optional[float],
) -> Optional[CbConversionPremium]:
    """可转债转股溢价率（doc 29）。

    Args:
        stock_price: 正股现价。
        conv_price:  转股价。
        cb_price:    可转债现价（面值 100 元为基准）。

    Returns:
        CbConversionPremium；任一价<=0 返回 None。
    """
    if not stock_price or not conv_price or not cb_price or conv_price <= 0:
        return None
    conv_value = stock_price * (100.0 / conv_price)
    premium = cb_price / conv_value - 1.0
    if premium < 0:
        verdict = "discount"
    elif premium <= 0.10:
        verdict = "fair"
    else:
        verdict = "expensive"
    return CbConversionPremium(
        conversion_value=conv_value, premium=premium, verdict=verdict,
    )


# ── 5.3 可转债三条款预警 ─────────────────────────────────────────────────────

# 触发比例（相对转股价）。课程 doc 29：下修≤85% / 强赎≥130% / 回售≤70%。
CB_CLAUSE_THRESHOLDS = {"downward_revision": 0.85, "forced_redemption": 1.30, "put_back": 0.70}


@dataclass
class CbClauseWarnings:
    ratio: float                          # 正股价 / 转股价
    downward_revision: bool               # 下修触发
    forced_redemption: bool               # 强赎触发
    put_back: bool                        # 回售触发
    warnings: list[str]


def cb_clause_warnings(
    stock_price: Optional[float],
    conv_price: Optional[float],
    *,
    thresholds: Optional[dict] = None,
) -> Optional[CbClauseWarnings]:
    """可转债三条款预警（doc 29）。

    Args:
        stock_price: 正股现价。
        conv_price:  转股价。
        thresholds:  自定义触发比例（默认下修 0.85 / 强赎 1.30 / 回售 0.70）。

    Returns:
        CbClauseWarnings；价格非法返回 None。
    """
    if not stock_price or not conv_price or conv_price <= 0:
        return None
    th = {**CB_CLAUSE_THRESHOLDS, **(thresholds or {})}
    ratio = stock_price / conv_price
    downward = ratio <= th["downward_revision"]
    forced = ratio >= th["forced_redemption"]
    put_back = ratio <= th["put_back"]
    warns: list[str] = []
    if downward:
        warns.append(f"下修触发：正股价跌至转股价 {ratio:.1%}（≤{th['downward_revision']:.0%}）")
    if forced:
        warns.append(f"强赎触发：正股价涨至转股价 {ratio:.1%}（≥{th['forced_redemption']:.0%}）")
    if put_back:
        warns.append(f"回售触发：正股价跌至转股价 {ratio:.1%}（≤{th['put_back']:.0%}）")
    return CbClauseWarnings(
        ratio=ratio,
        downward_revision=downward,
        forced_redemption=forced,
        put_back=put_back,
        warnings=warns,
    )
