"""股票投资课程——相对强度/相对强弱（doc 25 指数体系）纯函数。

簇 4 的 equity_macro_divergence 看大盘 vs 盈利的宏观背离；本模块聚焦**个股/
行业 vs 基准（沪深300）的相对收益**——课程 doc 25 强调：跑赢大盘的标的
往往有资金持续关注（动量），相对强度（RS）是趋势跟随与行业轮动的核心量。

    relative_strength      单期超额收益 = 标的收益 − 基准收益
    rs_line                相对强度线 = 标的累计收益 / 基准累计收益（rebase 1.0）
    rs_trend               RS 线趋势（走强/走弱 + 动量）

输入为价格/收益序列。全部纯函数，无 DB/IO 依赖。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class RelativeStrength:
    target_return: float
    benchmark_return: float
    excess: float             # 标的 − 基准
    outperform: bool          # excess > 0


def relative_strength(
    target_return: Optional[float],
    benchmark_return: Optional[float],
) -> Optional[RelativeStrength]:
    """单期相对强度 = 标的收益 − 基准收益（doc 25）。

    Args:
        target_return:     标的区间收益率（小数）。
        benchmark_return:  基准（沪深300）同期收益率（小数）。

    Returns:
        RelativeStrength；输入缺失返回 None。
    """
    if target_return is None or benchmark_return is None:
        return None
    excess = target_return - benchmark_return
    return RelativeStrength(
        target_return=target_return,
        benchmark_return=benchmark_return,
        excess=excess,
        outperform=excess > 0,
    )


def rs_line(
    target_prices: list[float],
    benchmark_prices: list[float],
) -> Optional[list[float]]:
    """相对强度线：标的/基准均 rebase 到 1.0 后求商（doc 25）。

    RS 线上升 = 标的持续跑赢基准；下降 = 跑输。用于识别中期资金流向。

    Args:
        target_prices:     标的价格序列（同长度、同日期）。
        benchmark_prices:  基准价格序列。

    Returns:
        RS 线序列（首值=1.0）；长度不一致/空/首价<=0 返回 None。
    """
    if (not target_prices or not benchmark_prices
            or len(target_prices) != len(benchmark_prices)):
        return None
    t0 = target_prices[0]
    b0 = benchmark_prices[0]
    if not t0 or not b0 or t0 <= 0 or b0 <= 0:
        return None
    out: list[float] = []
    for t, b in zip(target_prices, benchmark_prices):
        if t is None or b is None or b <= 0:
            return None
        out.append((t / t0) / (b / b0))
    return out


@dataclass
class RsTrend:
    latest: float              # 末值（>1 跑赢累计）
    total_change: float        # 首末变化（小数）
    slope: Optional[float]     # 每期斜率
    strengthening: Optional[bool]  # slope > 0
    verdict: str               # outperform / underperform


def rs_trend(rs_series: list[float], *, window: int = 0) -> Optional[RsTrend]:
    """RS 线趋势分析（doc 25）。

    Args:
        rs_series: rs_line 输出（或任意 rebase=1.0 的相对强度序列）。
        window:    动量计算窗口（取最近 window 期变化）；0 = 全程。

    Returns:
        RsTrend；序列长度<2 或含非法值返回 None。
    """
    vals = [v for v in (rs_series or []) if v is not None and math.isfinite(v)]
    if len(vals) < 2:
        return None
    latest = vals[-1]
    total_change = latest - vals[0]

    n = len(vals)
    xs = list(range(n))
    xm = sum(xs) / n
    ym = sum(vals) / n
    num = sum((x - xm) * (y - ym) for x, y in zip(xs, vals))
    den = sum((x - xm) ** 2 for x in xs)
    slope = num / den if den else 0.0
    strengthening = slope > 0

    verdict = "outperform" if latest > 1.0 else "underperform"
    return RsTrend(
        latest=latest,
        total_change=total_change,
        slope=slope,
        strengthening=strengthening,
        verdict=verdict,
    )


# ── 多标的相对强度排名 ──────────────────────────────────────────────────────

@dataclass
class RsRankEntry:
    symbol: str
    rs_latest: float          # RS 线末值（>1 跑赢基准）
    rs_slope: Optional[float]
    outperform: bool


def rank_relative_strength(
    targets: dict,
    benchmark_prices: list[float],
) -> Optional[list[RsRankEntry]]:
    """多个标的 vs 同一基准的相对强度排名（doc 25 选强势行业/个股）。

    Args:
        targets:            ``{symbol: price_series}``，各标的价格序列。
        benchmark_prices:   基准价格序列（与各 target 等长）。

    Returns:
        按 RS 末值降序排列的 RsRankEntry 列表；基准非法/空返回 None。
        RS 末值越大 = 越跑赢基准（动量越强）。
    """
    if not benchmark_prices or not targets:
        return None
    entries: list[RsRankEntry] = []
    for sym, prices in targets.items():
        line = rs_line(prices, benchmark_prices)
        if line is None:
            continue
        trend = rs_trend(line)
        if trend is None:
            continue
        entries.append(RsRankEntry(
            symbol=sym,
            rs_latest=trend.latest,
            rs_slope=trend.slope,
            outperform=trend.latest > 1.0,
        ))
    entries.sort(key=lambda e: e.rs_latest, reverse=True)
    return entries if entries else None
