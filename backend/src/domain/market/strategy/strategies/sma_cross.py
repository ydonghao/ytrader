"""
SMA 金叉/死叉策略
==================
快速SMA上穿慢速SMA → BUY
快速SMA下穿慢速SMA → SELL
"""
from datetime import datetime
from typing import Optional

from ..base import SingleSymbolStrategy
from ..signals import Action, Signal
from ..indicators import sma
from ...sync.sync_provider import OHLCVBar


class SMACrossStrategy(SingleSymbolStrategy):
    """
    SMA 金叉死叉策略
    
    参数：
        fast_period: 快速SMA周期（默认 5）
        slow_period: 慢速SMA周期（默认 20）
        buy_on_cross: True=金叉买入，False=只做卖出
        sell_on_cross: True=死叉卖出，False=只做买入
    """

    name = "SMA_Cross"
    description = "简单移动平均线金叉/死叉策略"

    def __init__(
        self,
        fast_period: int = 5,
        slow_period: int = 20,
        buy_on_cross: bool = True,
        sell_on_cross: bool = True,
    ):
        if fast_period >= slow_period:
            raise ValueError(f"fast_period({fast_period}) 必须 < slow_period({slow_period})")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.buy_on_cross = buy_on_cross
        self.sell_on_cross = sell_on_cross

    def generate_signals_for_symbol(
        self, symbol: str, bars: list[OHLCVBar]
    ) -> list[Signal]:
        if len(bars) < self.slow_period + 1:
            return []

        closes = [b.close_ for b in bars]
        fast_sma = sma(closes, self.fast_period)
        slow_sma = sma(closes, self.slow_period)

        signals = []
        for i in range(1, len(bars)):
            prev_fast = fast_sma[i - 1]
            curr_fast = fast_sma[i]
            prev_slow = slow_sma[i - 1]
            curr_slow = slow_sma[i]

            if prev_fast is None or curr_fast is None:
                continue
            if prev_slow is None or curr_slow is None:
                continue

            bar = bars[i]

            # 金叉：快速线上穿慢速线
            if self.buy_on_cross and prev_fast <= prev_slow and curr_fast > curr_slow:
                signals.append(Signal(
                    symbol=symbol,
                    action=Action.BUY,
                    price=bar.close_,
                    confidence=0.8,
                    reason=f"SMA金叉: fast({curr_fast:.2f}) > slow({curr_slow:.2f})",
                    timestamp=bar.trade_time,
                ))

            # 死叉：快速线下穿慢速线
            if self.sell_on_cross and prev_fast >= prev_slow and curr_fast < curr_slow:
                signals.append(Signal(
                    symbol=symbol,
                    action=Action.SELL,
                    price=bar.close_,
                    confidence=0.8,
                    reason=f"SMA死叉: fast({curr_fast:.2f}) < slow({curr_slow:.2f})",
                    timestamp=bar.trade_time,
                ))

        return signals

    def get_params(self) -> dict:
        return {
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "buy_on_cross": self.buy_on_cross,
            "sell_on_cross": self.sell_on_cross,
        }

    def get_required_intervals(self) -> list[str]:
        return ["1d"]
