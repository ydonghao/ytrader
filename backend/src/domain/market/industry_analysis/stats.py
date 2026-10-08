# backend/src/domain/market/industry_analysis/stats.py
"""统计小工具(纯函数,无 IO)。"""
from __future__ import annotations

from typing import Optional, Sequence


def percentile_rank(value: Optional[float],
                    series: Sequence[float]) -> Optional[float]:
    """midrank 百分位(0-100):并列值取中位,避免并列全部 100 的偏置。"""
    if value is None:
        return None
    vals = [v for v in series if v is not None]
    if not vals:
        return None
    lt = sum(1 for v in vals if v < value)
    eq = sum(1 for v in vals if v == value)
    return (lt + 0.5 * eq) / len(vals) * 100.0


def median(values: Sequence[Optional[float]]) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return None
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def histogram(values: Sequence[Optional[float]], bins: int = 20,
              lo: Optional[float] = None,
              hi: Optional[float] = None) -> dict:
    vals = [v for v in values if v is not None]
    if lo is not None:
        vals = [v for v in vals if v >= lo]
    if hi is not None:
        vals = [v for v in vals if v <= hi]
    if not vals or bins <= 0:
        return {"edges": [], "counts": [0] * max(bins, 0)}
    a = min(vals) if lo is None else lo
    b = max(vals) if hi is None else hi
    if a == b:
        b = a + 1.0
    width = (b - a) / bins
    counts = [0] * bins
    for v in vals:
        i = min(int((v - a) / width), bins - 1)
        counts[i] += 1
    edges = [round(a + i * width, 4) for i in range(bins + 1)]
    return {"edges": edges, "counts": counts}
