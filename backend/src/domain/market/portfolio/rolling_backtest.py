"""滚动窗口累计收益计算引擎（纯函数，无 DB 依赖）。

按月滚动: 从起始时间开始, 每个月作为一个窗口起点,
算该窗口内（默认12个月）按目标权重配置的组合累计收益率。

优化: 一次性加载全部行情成 {symbol: {date: close}}, 然后内存切片,
避免对每个窗口都跑完整交易引擎(N 次回测 → 1 次 DB 查询 + N 次内存算)。

收益口径: 简单加权收益
    window_return = Π(1 + Σ(weight_i × monthly_return_i)) - 1
    其中 monthly_return_i = close_end/close_start - 1 (该标的在窗口内的涨幅)
不建模交易成本/按手取整, 因为滚动回测看的是配置策略的区间表现趋势,
精度要求低于单次完整回测。
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional
from collections import defaultdict


@dataclass
class RollingWindowResult:
    """单个滚动窗口的结果。"""

    start: str           # 窗口起始月 YYYY-MM
    end: str             # 窗口结束月 YYYY-MM
    return_pct: float    # 窗口累计收益率 %


def _month_iter(start: date, end: date):
    """生成 [start, end] 之间每个月的月初日期(含 start 当月)。"""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield date(y, m, 1)
        m += 1
        if m > 12:
            m = 1
            y += 1


def _month_end(d: date) -> date:
    """该月的下一个月初 - 1天 = 月末。"""
    y, m = d.year, d.month
    m += 1
    if m > 12:
        m = 1
        y += 1
    # 下月1号的前一天; 用 date 算术
    import datetime as dt
    return date(y, m, 1) + dt.timedelta(days=-1)


def _closest_close(
    prices: dict,
    target: date,
) -> Optional[float]:
    """在 prices {date: close} 里找 target 当天或最近的收盘价。

    找不到(窗口早于标的首个交易日)返回 None。
    向后找最近的有效日期(避免用未来数据, 用窗口起始附近的价)。
    """
    if not prices:
        return None
    if target in prices:
        return prices[target]
    # 向后找最近的交易日(最多找 45 天, 覆盖春节等长假)
    import datetime as dt
    for i in range(1, 46):
        d = target + dt.timedelta(days=i)
        if d in prices:
            return prices[d]
    return None


def calc_rolling_returns(
    prices_by_symbol: dict[str, dict[date, float]],
    target_weights: dict[str, float],
    start_date: date,
    end_date: date,
    window_months: int = 12,
) -> list[RollingWindowResult]:
    """计算滚动窗口累计收益率。

    Args:
        prices_by_symbol: {symbol: {date: close}} 各标的的历史收盘价。
        target_weights:   {symbol: weight} 目标权重(0~1)。
        start_date:       滚动起点(从该月开始滚)。
        end_date:         滚动终点(最后一个窗口的起始月不超过此)。
        window_months:    每个窗口的月数(默认12)。

    Returns:
        list[RollingWindowResult]: 每个窗口的累计收益率。
    """
    results: list[RollingWindowResult] = []
    import datetime as dt

    for window_start in _month_iter(start_date, end_date):
        window_end = _add_months(window_start, window_months)

        # 窗口内每个标的的涨幅
        weighted_return_sum = 0.0
        total_weight_used = 0.0
        for sym, weight in target_weights.items():
            prices = prices_by_symbol.get(sym, {})
            p_start = _closest_close(prices, window_start)
            p_end = _closest_close(prices, window_end)
            if p_start and p_end and p_start > 0:
                ret = p_end / p_start - 1
                weighted_return_sum += weight * ret
                total_weight_used += weight

        if total_weight_used == 0:
            continue  # 该窗口无可用数据

        # 归一化(若有标的缺数据, 用已有标的的权重归一)
        normalized = weighted_return_sum / total_weight_used
        results.append(
            RollingWindowResult(
                start=window_start.strftime("%Y-%m"),
                end=window_end.strftime("%Y-%m"),
                return_pct=round(normalized * 100, 2),
            )
        )

    return results


def _add_months(d: date, months: int) -> date:
    """日期加 N 个月。"""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # 处理月末溢出(如 1月31日 +1月 = 2月28日)
    import datetime as dt
    day = min(d.day, 28)  # 保守取 28 避免月末问题
    return date(y, m, day)
