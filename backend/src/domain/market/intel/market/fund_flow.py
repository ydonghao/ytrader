"""股票投资课程——资金面信号（docs 02/27/31）纯函数。

簇 4 看宏观指标；本模块看**市场资金面**——课程 doc 02/27/31 强调资金面是
A 股中短期走势的直接驱动：北向资金代表外资情绪，融资融券余额代表杠杆资金
情绪（散户/游资）。

    north_flow_signal       北向资金净流入序列 → 外资情绪（持续流入=看好）
    margin_sentiment        两融余额序列 → 杠杆情绪（余额上升=乐观加杠杆）

数据：北向资金（沪深港通净买入）来自 akshare ``stock_hsgt_hist_em``；
融资融券余额来自 akshare ``stock_margin_*``。全部纯函数。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class NorthFlowSignal:
    cumulative: float             # 区间累计净流入
    latest: float                 # 最新一期净流入
    consecutive_inflow: int       # 连续净流入天数/期数
    consecutive_outflow: int      # 连续净流出
    net_verdict: str              # inflow / outflow / balanced
    momentum: str                 # sustained_inflow / sustained_outflow / mixed


def north_flow_signal(net_flows: list[float]) -> Optional[NorthFlowSignal]:
    """北向资金净流入趋势（doc 31）。

    Args:
        net_flows: 升序的每日/每期北向净流入序列（元；正=流入）。

    Returns:
        NorthFlowSignal；序列为空返回 None。
        连续流入>=3 期 ``sustained_inflow``（外资持续看好，利好）；
        连续流出>=3 期 ``sustained_outflow``（外资撤离，利空）。
    """
    vals = [f for f in (net_flows or []) if f is not None]
    if not vals:
        return None
    cumulative = sum(vals)
    latest = vals[-1]
    # 末尾连续流入/流出
    ci = co = 0
    for v in reversed(vals):
        if v > 0:
            if co == 0:
                ci += 1
            else:
                break
        elif v < 0:
            if ci == 0:
                co += 1
            else:
                break
        else:
            break
    if ci >= 3:
        momentum = "sustained_inflow"
    elif co >= 3:
        momentum = "sustained_outflow"
    else:
        momentum = "mixed"
    if cumulative > 0:
        net_verdict = "inflow"
    elif cumulative < 0:
        net_verdict = "outflow"
    else:
        net_verdict = "balanced"
    return NorthFlowSignal(
        cumulative=cumulative, latest=latest,
        consecutive_inflow=ci, consecutive_outflow=co,
        net_verdict=net_verdict, momentum=momentum,
    )


@dataclass
class MarginSentiment:
    latest_balance: float
    latest_change: Optional[float]      # 环比（正=加杠杆）
    consecutive_increase: int           # 连续上升期数
    consecutive_decrease: int           # 连续下降
    verdict: str                        # levering_up / deleveraging / stable


def margin_sentiment(margin_balances: list[float]) -> Optional[MarginSentiment]:
    """融资融券余额趋势 → 杠杆情绪（doc 27）。

    课程逻辑：两融余额上升 = 杠杆资金进场、市场情绪乐观；余额下降 = 去杠杆、
    情绪转谨慎。连续上升/下降是趋势确认信号。

    Args:
        margin_balances: 升序的两融余额序列（元）。

    Returns:
        MarginSentiment；序列<2 返回 None。
    """
    vals = [b for b in (margin_balances or []) if b is not None and b > 0]
    if len(vals) < 2:
        return None
    latest = vals[-1]
    prev = vals[-2]
    latest_change = (latest - prev) / prev if prev > 0 else None
    ci = cd = 0
    for i in range(len(vals) - 1, 0, -1):
        d = vals[i] - vals[i - 1]
        if d > 0:
            if cd == 0:
                ci += 1
            else:
                break
        elif d < 0:
            if ci == 0:
                cd += 1
            else:
                break
        else:
            break
    if ci >= 2:
        verdict = "levering_up"
    elif cd >= 2:
        verdict = "deleveraging"
    else:
        verdict = "stable"
    return MarginSentiment(
        latest_balance=latest, latest_change=latest_change,
        consecutive_increase=ci, consecutive_decrease=cd, verdict=verdict,
    )
