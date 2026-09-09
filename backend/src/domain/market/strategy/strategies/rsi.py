"""
RSI 超买超卖策略
=================
RSI > overbought → SELL
RSI < oversold   → BUY
"""
from ..base import SingleSymbolStrategy
from ..signals import Action, Signal
from ..indicators import rsi
from ...sync.sync_provider import OHLCVBar


class RSIStrategy(SingleSymbolStrategy):
    """
    RSI 策略
    
    参数：
        period: RSI周期（默认 14）
        overbought: 超买阈值（默认 70）
        oversold: 超卖阈值（默认 30）
        buy_on_recover: True=从超卖区回升时买入（默认 True）
        sell_on_drop: True=从超买区回落时卖出（默认 True）
    """

    name = "RSI"
    description = "RSI 超买超卖策略"

    def __init__(
        self,
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
        buy_on_recover: bool = True,   # 从超卖区回升
        sell_on_drop: bool = True,      # 从超买区回落
    ):
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.buy_on_recover = buy_on_recover
        self.sell_on_drop = sell_on_drop

    def generate_signals_for_symbol(
        self, symbol: str, bars: list[OHLCVBar]
    ) -> list[Signal]:
        if len(bars) < self.period + 2:
            return []

        closes = [b.close_ for b in bars]
        rsi_values = rsi(closes, self.period)

        signals = []
        prev_in_oversold = False
        prev_in_overbought = False

        for i in range(1, len(bars)):
            curr_rsi = rsi_values[i]
            prev_rsi = rsi_values[i - 1]

            if curr_rsi is None or prev_rsi is None:
                continue

            bar = bars[i]
            in_oversold = curr_rsi < self.oversold
            in_overbought = curr_rsi > self.overbought

            # 从超卖区回升 → 买入信号
            if self.buy_on_recover and prev_in_oversold and not in_oversold:
                signals.append(Signal(
                    symbol=symbol,
                    action=Action.BUY,
                    price=bar.close_,
                    confidence=0.75,
                    reason=f"RSI回升: {prev_rsi:.1f} → {curr_rsi:.1f} (oversold={self.oversold})",
                    timestamp=bar.trade_time,
                ))

            # 从超买区回落 → 卖出信号
            if self.sell_on_drop and prev_in_overbought and not in_overbought:
                signals.append(Signal(
                    symbol=symbol,
                    action=Action.SELL,
                    price=bar.close_,
                    confidence=0.75,
                    reason=f"RSI回落: {prev_rsi:.1f} → {curr_rsi:.1f} (overbought={self.overbought})",
                    timestamp=bar.trade_time,
                ))

            prev_in_oversold = in_oversold
            prev_in_overbought = in_overbought

        return signals

    def get_params(self) -> dict:
        return {
            "period": self.period,
            "overbought": self.overbought,
            "oversold": self.oversold,
            "buy_on_recover": self.buy_on_recover,
            "sell_on_drop": self.sell_on_drop,
        }

    def get_required_intervals(self) -> list[str]:
        return ["1d"]
