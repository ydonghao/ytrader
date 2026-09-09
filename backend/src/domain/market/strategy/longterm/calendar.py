"""
日历 / 周期工具
===============
- 调仓频率判断（daily/weekly/monthly/quarterly）
- 日线聚合成周/月/季线，供趋势判断

约定：所有"是否调仓日"的判断基于交易日序列（已剔除非交易日），
因此 weekly = 每周首个交易日、monthly = 每月首个交易日，依此类推。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from ...sync.sync_provider import OHLCVBar

FREQS = ("daily", "weekly", "monthly", "quarterly", "yearly")


def _as_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return d


def is_rebalance_day(today: date, prev: Optional[date], freq: str) -> bool:
    """
    判断 today 是否为 freq 频率的调仓日（prev 为上一交易日）。

    daily:     每个交易日都调仓
    weekly:    每周首个交易日（prev 为 None 或跨周）
    monthly:   每月首个交易日（跨月）
    quarterly: 每季首个交易日（跨季度）
    yearly:    每年首个交易日（跨年）
    """
    freq = (freq or "monthly").lower()
    if freq == "daily":
        return True
    if prev is None:
        return True
    if freq == "weekly":
        return today.isocalendar()[1] != prev.isocalendar()[1] or today.year != prev.year
    if freq == "monthly":
        return today.month != prev.month or today.year != prev.year
    if freq == "quarterly":
        return _quarter(today) != _quarter(prev) or today.year != prev.year
    if freq == "yearly":
        return today.year != prev.year
    # 未知频率默认每月
    return today.month != prev.month or today.year != prev.year


def _quarter(d: date) -> int:
    return (d.month - 1) // 3 + 1


def resample_ohlcv(
    bars: list[OHLCVBar], freq: str
) -> list[OHLCVBar]:
    """
    将日线 OHLCV 按周/月/季聚合成更粗粒度的 K 线。

    用于趋势策略：例如 200 日均线在月线上 ≈ 用月线自身的均线判断。
    聚合规则：open=组首 open，close=组末 close，
              high=max，low=min，volume/amount=sum。

    Args:
        bars: 日线（按 trade_time 升序）
        freq: weekly / monthly / quarterly

    Returns:
        聚合后的 K 线列表（按时间升序），interval 字段填 freq。
    """
    if not bars or freq == "daily":
        return list(bars)
    freq = freq.lower()
    out: list[OHLCVBar] = []
    bucket: list[OHLCVBar] = []
    bucket_key = None

    def key_of(b: OHLCVBar):
        d = _as_date(b.trade_time)
        if freq == "weekly":
            iso = d.isocalendar()
            return (d.year, iso[1])
        if freq == "monthly":
            return (d.year, d.month)
        if freq == "quarterly":
            return (d.year, _quarter(d))
        return (d.year,)

    for b in sorted(bars, key=lambda x: x.trade_time):
        k = key_of(b)
        if bucket_key is None:
            bucket_key = k
            bucket = [b]
        elif k == bucket_key:
            bucket.append(b)
        else:
            out.append(_merge_bucket(bucket, freq))
            bucket = [b]
            bucket_key = k
    if bucket:
        out.append(_merge_bucket(bucket, freq))
    return out


def _merge_bucket(bucket: list[OHLCVBar], freq: str) -> OHLCVBar:
    first = bucket[0]
    last = bucket[-1]
    return OHLCVBar(
        symbol=first.symbol,
        trade_time=last.trade_time,
        open_=first.open_,
        close_=last.close_,
        high_=max(b.high_ for b in bucket),
        low_=min(b.low_ for b in bucket),
        volume=sum(b.volume for b in bucket),
        amount=sum(b.amount for b in bucket),
        interval=freq,
        market=first.market,
        provider=first.provider,
    )
