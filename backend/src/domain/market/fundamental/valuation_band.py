"""
均值±1σ 估值带（纯函数）
=====================
课程 21/24/25 集反复使用的参数化估值方法：对 PE/PB 时序算均值 μ 与标准差 σ，
把当前值放到 ±1σ 通道里判四态。与现有 percentile.py（经验分位秩）互补——
分位是非参数的，本方法是参数化（正态假设）的，课程作者惯用此形态。

默认窗口由调用方截（课程建议约 8 年）；本函数只负责统计算子与四分类。
"""
from __future__ import annotations

from typing import Optional


def _nums(values) -> list[float]:
    out = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def valuation_band(
    series: list,
    current: float,
    window: Optional[int] = None,
) -> Optional[dict]:
    """均值±1σ 估值带四分类。

    Args:
        series:  历史 PE/PB 升序值列表（剔除非数）。
        current: 当前值。
        window:  仅取末尾 window 个样本（默认全部）。

    Returns:
        {mean, std, z_score, state}；样本 < 2、std==0 退化、current 非数 → None。
        state：超跌(<μ−σ) / 合理偏低(μ−σ..μ) / 合理偏高(μ..μ+σ) / 虚高(>μ+σ)。
        （std==0 时按 current 与 mean 大小判合理偏低/偏高。）
    """
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return None
    vals = _nums(series)
    if window:
        vals = vals[-window:]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    var = sum((x - mean) ** 2 for x in vals) / len(vals)  # 总体方差
    std = var ** 0.5
    if std == 0:
        state = "合理偏低" if current < mean else ("虚高" if current > mean else "合理偏低")
        z = 0.0
    else:
        z = (current - mean) / std
        if current < mean - std:
            state = "超跌"
        elif current < mean:
            state = "合理偏低"
        elif current <= mean + std:
            state = "合理偏高"
        else:
            state = "虚高"
    return {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "z_score": round(z, 4),
        "state": state,
    }
