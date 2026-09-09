"""
技术指标计算工具
==================
提供常用的技术指标计算函数。
"""
from typing import Optional
from ..sync.sync_provider import OHLCVBar


def sma(values: list[float], period: int) -> list[Optional[float]]:
    """
    简单移动平均线 SMA
    
    Args:
        values: 数值序列（按时间升序）
        period: 周期
        
    Returns:
        与输入等长的列表，不足period的位置为None
    """
    result: list[Optional[float]] = [None] * len(values)
    if period < 1 or len(values) < period:
        return result
    
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1:i + 1]) / period
    return result


def ema(values: list[float], period: int) -> list[Optional[float]]:
    """
    指数移动平均线 EMA
    
    Args:
        values: 数值序列（按时间升序）
        period: 周期
        
    Returns:
        与输入等长的列表
    """
    result: list[Optional[float]] = [None] * len(values)
    if period < 1 or len(values) < period:
        return result
    
    # 初始SMA
    result[period - 1] = sum(values[:period]) / period
    multiplier = 2 / (period + 1)
    
    for i in range(period, len(values)):
        result[i] = (values[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def macd(
    values: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    """
    MACD 指标
    
    Returns:
        (macd_line, signal_line, histogram)
        macd_line = fast_ema - slow_ema
        signal_line = macd的EMA(signal)
        histogram = macd_line - signal_line
    """
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    
    macd_line: list[Optional[float]] = [None] * len(values)
    for i in range(len(values)):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            macd_line[i] = fast_ema[i] - slow_ema[i]
    
    sig = ema([x if x is not None else 0 for x in macd_line], signal)
    
    histogram: list[Optional[float]] = [None] * len(values)
    for i in range(len(values)):
        if macd_line[i] is not None and sig[i] is not None:
            histogram[i] = macd_line[i] - sig[i]
    
    return macd_line, sig, histogram


def rsi(values: list[float], period: int = 14) -> list[Optional[float]]:
    """
    RSI 相对强弱指数
    
    Args:
        values: 价格序列
        period: 周期
        
    Returns:
        RSI值 0~100
    """
    if len(values) < period + 1:
        return [None] * len(values)
    
    gains = []
    losses = []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    
    result: list[Optional[float]] = [None] * len(values)
    
    # 初始平均
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - (100 / (1 + rs))
    
    return result


def bollinger_bands(
    values: list[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    """
    布林带
    
    Returns:
        (upper_band, middle_band, lower_band)
    """
    mid = sma(values, period)
    upper: list[Optional[float]] = [None] * len(values)
    lower: list[Optional[float]] = [None] * len(values)
    
    for i in range(period - 1, len(values)):
        if mid[i] is None:
            continue
        slice_vals = values[i - period + 1:i + 1]
        import statistics
        std = statistics.stdev(slice_vals)
        upper[i] = mid[i] + std_dev * std
        lower[i] = mid[i] - std_dev * std
    
    return upper, mid, lower


def atr(
    bars: list[OHLCVBar],
    period: int = 14,
) -> list[Optional[float]]:
    """
    ATR 平均真实波幅
    
    Args:
        bars: OHLCVBar 列表
        period: 周期
        
    Returns:
        ATR值序列
    """
    if len(bars) < 2:
        return [None] * len(bars)
    
    trs: list[float] = []
    for i in range(len(bars)):
        if i == 0:
            tr = bars[i].high_ - bars[i].low_
        else:
            h_l = bars[i].high_ - bars[i].low_
            h_c = abs(bars[i].high_ - bars[i - 1].close_)
            l_c = abs(bars[i].low_ - bars[i - 1].close_)
            tr = max(h_l, h_c, l_c)
        trs.append(tr)
    
    result: list[Optional[float]] = [None] * len(bars)
    if len(trs) < period:
        return result
    
    # 初始ATR
    result[period - 1] = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        result[i] = (result[i - 1] * (period - 1) + trs[i]) / period
    
    return result
