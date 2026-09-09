"""
布林带策略
===========
价格触及下轨 → BUY（超卖反弹）
价格触及上轨 → SELL（超买回落）
"""
from ..base import SingleSymbolStrategy
from ..signals import Action, Signal
from ..indicators import bollinger_bands
from ...sync.sync_provider import OHLCVBar


class BollingerStrategy(SingleSymbolStrategy):
    """
    布林带策略
    
    参数：
        period: 布林带周期（默认 20）
        std_dev: 标准差倍数（默认 2.0）
        buy_on_lower: True=价格触及下轨买入（默认 True）
        sell_on_upper: True=价格触及上轨卖出（默认 True）
    """

    name = "Bollinger"
    description = "布林带超买超卖策略"

    def __init__(
        self,
        period: int = 20,
        std_dev: float = 2.0,
        buy_on_lower: bool = True,
        sell_on_upper: bool = True,
    ):
        self.period = period
        self.std_dev = std_dev
        self.buy_on_lower = buy_on_lower
        self.sell_on_upper = sell_on_upper

    def generate_signals_for_symbol(
        self, symbol: str, bars: list[OHLCVBar]
    ) -> list[Signal]:
        if len(bars) < self.period + 1:
            return []

        closes = [b.close_ for b in bars]
        upper, mid, lower = bollinger_bands(closes, self.period, self.std_dev)

        signals = []
        for i in range(1, len(bars)):
            bar = bars[i]
            curr_upper = upper[i]
            curr_lower = lower[i]

            if curr_upper is None or curr_lower is None:
                continue

            prev_close = bars[i - 1].close_

            # 价格从下轨下方回升 → BUY
            if self.buy_on_lower:
                prev_in_lower = prev_close <= (lower[i - 1] if lower[i - 1] else float('inf'))
                curr_above_lower = bar.close_ >= curr_lower
                if not prev_in_lower and curr_above_lower:
                    signals.append(Signal(
                        symbol=symbol,
                        action=Action.BUY,
                        price=bar.close_,
                        confidence=0.7,
                        reason=f"布林下轨反弹: close({bar.close_:.2f}) >= lower({curr_lower:.2f})",
                        timestamp=bar.trade_time,
                    ))

            # 价格从上轨上方回落 → SELL
            if self.sell_on_upper:
                prev_above_upper = prev_close >= (upper[i - 1] if upper[i - 1] else -float('inf'))
                curr_in_upper = bar.close_ <= curr_upper
                if prev_above_upper and curr_in_upper:
                    signals.append(Signal(
                        symbol=symbol,
                        action=Action.SELL,
                        price=bar.close_,
                        confidence=0.7,
                        reason=f"布林上轨回落: close({bar.close_:.2f}) <= upper({curr_upper:.2f})",
                        timestamp=bar.trade_time,
                    ))

        return signals

    def get_params(self) -> dict:
        return {
            "period": self.period,
            "std_dev": self.std_dev,
            "buy_on_lower": self.buy_on_lower,
            "sell_on_upper": self.sell_on_upper,
        }

    def get_required_intervals(self) -> list[str]:
        return ["1d"]
