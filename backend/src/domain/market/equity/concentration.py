"""股票投资课程——筹码集中度（docs 18/21）纯函数。

簇 6 的 ownership_stability 看十大股东持股；本模块看**全体股东户数**的时序
变化——课程 doc 18/21 强调：股东户数减少 = 筹码向少数人（主力）集中（利好），
户数增加 = 筹码分散到散户（利空）。这是散户可观察的"主力收集"信号。

    concentration_trend   户数环比变化趋势（连续减少/增加/平稳）
    per_capita_holding    人均持股 = 流通股本 / 股东户数（上升=集中）

数据：股东户数来自定期报告（季报/半年报/年报），akshare
``stock_zh_a_gdhs_detail_em``。全部纯函数。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class ConcentrationTrend:
    latest_count: Optional[int]
    latest_change: Optional[float]       # 最近一期户数环比（负=减少=集中）
    consecutive_decline: int             # 连续减少期数
    consecutive_increase: int            # 连续增加期数
    verdict: str                         # concentrating / dispersing / stable
    total_change: Optional[float]        # 首末期数总变化


def concentration_trend(holder_counts: list[int]) -> Optional[ConcentrationTrend]:
    """股东户数变化趋势（doc 18/21）。

    Args:
        holder_counts: 按时间**升序**的股东户数序列（每期一个整数）。

    Returns:
        ConcentrationTrend；序列<2 返回 None。
        verdict: 连续减少>=2 ``concentrating``（筹码集中，主力收集）；
                 连续增加>=2 ``dispersing``（筹码分散，散户化）；
                 否则 ``stable``。
    """
    vals = [c for c in (holder_counts or []) if c is not None and c > 0]
    if len(vals) < 2:
        return None
    latest = vals[-1]
    prev = vals[-2]
    latest_change = (latest - prev) / prev if prev > 0 else None

    # 从末尾往前数连续减少/增加
    consec_dec = consec_inc = 0
    for i in range(len(vals) - 1, 0, -1):
        d = vals[i] - vals[i - 1]
        if d < 0:
            if consec_inc == 0:
                consec_dec += 1
            else:
                break
        elif d > 0:
            if consec_dec == 0:
                consec_inc += 1
            else:
                break
        else:
            break

    first = vals[0]
    total_change = (latest - first) / first if first > 0 else None

    if consec_dec >= 2:
        verdict = "concentrating"
    elif consec_inc >= 2:
        verdict = "dispersing"
    else:
        verdict = "stable"
    return ConcentrationTrend(
        latest_count=latest,
        latest_change=latest_change,
        consecutive_decline=consec_dec,
        consecutive_increase=consec_inc,
        verdict=verdict,
        total_change=total_change,
    )


@dataclass
class PerCapitaHolding:
    latest: float                # 最新人均持股
    change: Optional[float]      # 环比变化（正=集中）
    verdict: str                 # rising(集中) / falling(分散) / flat


def per_capita_holding(
    float_shares: Optional[float],
    holder_counts: list[int],
) -> Optional[PerCapitaHolding]:
    """人均持股 = 流通股本 / 股东户数（doc 18）。

    人均持股上升 = 筹码集中（大户收集）；下降 = 分散。

    Args:
        float_shares:   最新流通股本（股）。
        holder_counts:  升序股东户数序列。

    Returns:
        PerCapitaHolding；股本/户数不足返回 None。
    """
    vals = [c for c in (holder_counts or []) if c is not None and c > 0]
    if float_shares is None or float_shares <= 0 or len(vals) < 1:
        return None
    latest = float_shares / vals[-1]
    change = None
    if len(vals) >= 2:
        prev = float_shares / vals[-2]  # 简化：假设股本期内不变
        change = (latest - prev) / prev if prev > 0 else None
    if change is None:
        verdict = "flat"
    elif change > 0.02:
        verdict = "rising"
    elif change < -0.02:
        verdict = "falling"
    else:
        verdict = "flat"
    return PerCapitaHolding(latest=latest, change=change, verdict=verdict)
