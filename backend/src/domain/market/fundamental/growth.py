"""
成长性时序分析（纯函数）
=====================
对营收/净利润等年度序列做成长性判定，对应《股票投资课程》19/21 集强调的
"业绩长期不增长的公司直接淘汰"（格力：8 年营收原地踏步 ≈1800 亿）。

输入为数值列表（升序，最早→最新）；None 自动剔除。本模块不依赖 DB。
"""
from __future__ import annotations

from typing import Optional


def _nums(values) -> list[float]:
    """过滤出可用 float（剔除 bool/None/非法）。"""
    out = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def cagr(values: list, periods: Optional[int] = None) -> Optional[float]:
    """复合年增长率(小数) = (末值/初值)^(1/n) − 1。

    values 升序；n 默认 = 可用点数 − 1（假设为连续年度），可用 periods 显式指定。
    初值 <= 0、点数 < 2、n <= 0 返回 None。
    例：[100, 110, 121] → 0.1（10%）。
    """
    vals = _nums(values)
    if len(vals) < 2:
        return None
    start, end = vals[0], vals[-1]
    n = periods if periods else len(vals) - 1
    if start <= 0 or n <= 0:
        return None
    return round((end / start) ** (1.0 / n) - 1.0, 4)


def consecutive_declines(values: list) -> int:
    """从末尾往前的连续同比下滑期数（比较相邻元素）。

    返回整数；不足两点返回 0。例：[10, 12, 11, 9] → 2。
    """
    vals = _nums(values)
    if len(vals) < 2:
        return 0
    count = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] < vals[i - 1]:
            count += 1
        else:
            break
    return count


def is_stagnant(
    revenue_series: list,
    years: int = 8,
    threshold: float = 0.03,
) -> Optional[bool]:
    """成长停滞判定：近 years 年营收 CAGR 绝对值 < threshold。

    对应"长期原地踏步"公司（如格力 8 年营收不变）。数据不足（< years+1 个点）
    返回 None（无法判定）；否则返回 bool。例：8 年 CAGR ≈ 0 → True。
    """
    vals = _nums(revenue_series)
    if len(vals) < years + 1:
        return None
    g = cagr(vals[-(years + 1):], periods=years)
    if g is None:
        return None
    return abs(g) < threshold
