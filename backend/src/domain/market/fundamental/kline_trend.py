"""K线趋势判定(买入体检 4.4,课程21集"K线判断")。纯函数,零 IO。

课程口径:K 线用于判断短期走势——上升/下降/横盘三态。
本模块用 MA20/MA60/MA120 排列 + 120 日收盘 OLS 斜率联合判定;
只做"展示型状态",不构成买卖信号(设计决策:只展示不下结论)。
"""
from typing import Optional


def sma(closes: list, period: int) -> Optional[float]:
    """简单移动平均(取末 period 个)。不足返回 None。"""
    if len(closes) < period:
        return None
    vals = [c for c in closes[-period:] if isinstance(c, (int, float))]
    if len(vals) < period:
        return None
    return sum(vals) / period


def ols_slope(values: list) -> Optional[float]:
    """一元线性回归斜率(最小二乘)。少于 2 点返回 None。"""
    n = len(values)
    if n < 2:
        return None
    mx = (n - 1) / 2
    my = sum(values) / n
    num = sum((x - mx) * (y - my) for x, y in zip(range(n), values))
    den = sum((x - mx) ** 2 for x in range(n))
    return num / den if den else None


def trend_state(closes: list) -> Optional[dict]:
    """日频收盘价(升序)→ {ma20, ma60, ma120, slope_pct, state}。

    - <120 根 → None(数据不足)
    - slope_pct = 120日OLS斜率 / 120日均值 × 100(日均变化百分比)
    - 多头排列(ma20>ma60>ma120)且 slope_pct>0.01 → 上升
    - 空头排列(ma20<ma60<ma120)且 slope_pct<-0.01 → 下降
    - 其余 → 横盘
    """
    vals = [c for c in closes if isinstance(c, (int, float)) and not isinstance(c, bool)]
    if len(vals) < 120:
        return None
    ma20, ma60, ma120 = sma(vals, 20), sma(vals, 60), sma(vals, 120)
    win = vals[-120:]
    slope = ols_slope(win)
    if ma20 is None or ma60 is None or ma120 is None or slope is None:
        return None
    mean = sum(win) / len(win)
    if mean <= 0:
        return None
    slope_pct = slope / mean * 100
    if ma20 > ma60 > ma120 and slope_pct > 0.01:
        state = "上升"
    elif ma20 < ma60 < ma120 and slope_pct < -0.01:
        state = "下降"
    else:
        state = "横盘"
    return {
        "ma20": round(ma20, 3),
        "ma60": round(ma60, 3),
        "ma120": round(ma120, 3),
        "slope_pct": round(slope_pct, 4),
        "state": state,
    }
