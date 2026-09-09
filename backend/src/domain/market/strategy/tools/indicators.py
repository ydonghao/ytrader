"""
Indicators Tool
===============
Tool for computing technical indicators.
"""
from typing import Any

from ..indicators import (
    sma,
    ema,
    macd,
    rsi,
    bollinger_bands,
    atr,
)
from ..sync.sync_provider import OHLCVBar


# Supported indicators mapping
INDICATOR_MAP = {
    "close_50_sma": lambda bars: _sma_indicator(bars, 50),
    "close_200_sma": lambda bars: _sma_indicator(bars, 200),
    "close_10_ema": lambda bars: _ema_indicator(bars, 10),
    "macd": lambda bars: _macd_indicator(bars),
    "macds": lambda bars: _macd_signal_indicator(bars),
    "macdh": lambda bars: _macd_histogram_indicator(bars),
    "rsi": lambda bars: _rsi_indicator(bars),
    "boll": lambda bars: _bollinger_middle(bars),
    "boll_ub": lambda bars: _bollinger_upper(bars),
    "boll_lb": lambda bars: _bollinger_lower(bars),
    "atr": lambda bars: _atr_indicator(bars),
    "vwma": lambda bars: _vwma_indicator(bars),
}


def _sma_indicator(bars: list[OHLCVBar], period: int) -> list[float | None]:
    """Calculate SMA for close prices."""
    closes = [bar.close_ for bar in bars]
    return sma(closes, period)


def _ema_indicator(bars: list[OHLCVBar], period: int) -> list[float | None]:
    """Calculate EMA for close prices."""
    closes = [bar.close_ for bar in bars]
    return ema(closes, period)


def _macd_indicator(bars: list[OHLCVBar]) -> list[float | None]:
    """Calculate MACD line."""
    closes = [bar.close_ for bar in bars]
    macd_line, _, _ = macd(closes)
    return macd_line


def _macd_signal_indicator(bars: list[OHLCVBar]) -> list[float | None]:
    """Calculate MACD signal line."""
    closes = [bar.close_ for bar in bars]
    _, signal, _ = macd(closes)
    return signal


def _macd_histogram_indicator(bars: list[OHLCVBar]) -> list[float | None]:
    """Calculate MACD histogram."""
    closes = [bar.close_ for bar in bars]
    _, _, histogram = macd(closes)
    return histogram


def _rsi_indicator(bars: list[OHLCVBar], period: int = 14) -> list[float | None]:
    """Calculate RSI."""
    closes = [bar.close_ for bar in bars]
    return rsi(closes, period)


def _bollinger_middle(bars: list[OHLCVBar], period: int = 20, std_dev: float = 2.0) -> list[float | None]:
    """Calculate Bollinger Middle Band."""
    closes = [bar.close_ for bar in bars]
    _, middle, _ = bollinger_bands(closes, period, std_dev)
    return middle


def _bollinger_upper(bars: list[OHLCVBar], period: int = 20, std_dev: float = 2.0) -> list[float | None]:
    """Calculate Bollinger Upper Band."""
    closes = [bar.close_ for bar in bars]
    upper, _, _ = bollinger_bands(closes, period, std_dev)
    return upper


def _bollinger_lower(bars: list[OHLCVBar], period: int = 20, std_dev: float = 2.0) -> list[float | None]:
    """Calculate Bollinger Lower Band."""
    closes = [bar.close_ for bar in bars]
    _, _, lower = bollinger_bands(closes, period, std_dev)
    return lower


def _atr_indicator(bars: list[OHLCVBar], period: int = 14) -> list[float | None]:
    """Calculate ATR."""
    return atr(bars, period)


def _vwma_indicator(bars: list[OHLCVBar], period: int = 20) -> list[float | None]:
    """Calculate VWMA (Volume Weighted Moving Average)."""
    if len(bars) < period:
        return [None] * len(bars)
    
    result: list[float | None] = [None] * len(bars)
    
    for i in range(period - 1, len(bars)):
        sum_pv = 0.0
        sum_v = 0.0
        for j in range(i - period + 1, i + 1):
            pv = bars[j].close_ * bars[j].volume
            sum_pv += pv
            sum_v += bars[j].volume
        if sum_v > 0:
            result[i] = sum_pv / sum_v
    
    return result


def get_indicators(
    bars: list[OHLCVBar],
    indicator_names: list[str],
) -> dict[str, list[float | None]]:
    """
    Calculate technical indicators for given bars.
    
    Args:
        bars: List of OHLCV bars
        indicator_names: List of indicator names to calculate
        
    Returns:
        Dict mapping indicator name to list of values
    """
    result = {}
    
    for name in indicator_names:
        if name in INDICATOR_MAP:
            result[name] = INDICATOR_MAP[name](bars)
        else:
            result[name] = [None] * len(bars)
    
    return result


def format_indicators_for_prompt(indicators: dict[str, list[float | None]]) -> str:
    """
    Format indicators into a readable string for LLM prompts.
    
    Args:
        indicators: Dict of indicator name to values
        
    Returns:
        Formatted string with latest values
    """
    lines = []
    for name, values in indicators.items():
        # Get latest non-None value
        latest = None
        for v in reversed(values):
            if v is not None:
                latest = v
                break
        
        if latest is not None:
            lines.append(f"{name}: {latest:.4f}")
        else:
            lines.append(f"{name}: N/A")
    
    return "\n".join(lines)
