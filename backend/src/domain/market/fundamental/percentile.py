"""通用分位（百分位）算法工具。

供个股/指数/行业估值分位共用。提取自
strategy/longterm/strategies/value_averaging.py 的 _pe_percentile，
泛化为任意指标的分位计算。

口径约定：
  - 样本数 < 30 返回 None（样本不足，统计无意义）
  - 分位 = (样本中 <= current 的个数) / 样本总数，范围 [0, 1]
  - 调用方负责过滤负值/None（PE/PS 为负不应纳入分位）
"""
from __future__ import annotations

import datetime as dt
from typing import Optional


SAMPLE_MIN = 30


def calc_percentile(samples: list[float], current: float) -> Optional[float]:
    """当前值在样本中的分位 (0~1)。

    Args:
        samples: 历史样本值（已剔除 None/负值）。
        current: 当前值。

    Returns:
        分位 (0~1)；样本数 < SAMPLE_MIN 返回 None。
    """
    if len(samples) < SAMPLE_MIN:
        return None
    rank = sum(1 for v in samples if v <= current)
    return rank / len(samples)


def percentile_stats(samples: list[float], current: float) -> Optional[dict]:
    """返回当前值的分位 + 窗口统计量。

    Returns:
        {current, percentile, sample_size, min, max, p25, p50, p75}；
        样本不足返回 None。
    """
    if len(samples) < SAMPLE_MIN:
        return None
    ordered = sorted(samples)
    n = len(ordered)

    def _pct(q: float) -> float:
        idx = max(0, min(n - 1, int(round(q * (n - 1)))))
        return ordered[idx]

    return {
        "current": current,
        "percentile": calc_percentile(samples, current),
        "sample_size": n,
        "min": ordered[0],
        "max": ordered[-1],
        "p25": _pct(0.25),
        "p50": _pct(0.50),
        "p75": _pct(0.75),
    }


def downsample_monthly(points: list[dict]) -> list[dict]:
    """按月降采样：每个自然月保留最后一个有效点。

    用于把日频分位时序降到月频，控制前端渲染量。
    points 每条含 {"date": "YYYY-MM-DD", "value": float}，按 date 升序传入。

    Returns:
        降采样后的点列表（每行原样返回，仅做了月内去重保留最后一条）。
    """
    if not points:
        return []
    last_per_month: dict[str, dict] = {}
    for p in points:
        d = p.get("date", "")
        if len(d) < 7:
            continue
        month_key = d[:7]  # YYYY-MM
        last_per_month[month_key] = p
    return list(last_per_month.values())
