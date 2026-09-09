"""
MACD 策略
==========
MACD线 上穿Signal线 → BUY（金叉）
MACD线 下穿Signal线 → SELL（死叉）
histogram 由负转正 → BUY
histogram 由正转负 → SELL
"""
from ..base import SingleSymbolStrategy
from ..signals import Action, Signal
from ..indicators import macd
from ...sync.sync_provider import OHLCVBar


class MACDStrategy(SingleSymbolStrategy):
    """
    MACD 策略
    
    参数：
        fast: 快线周期（默认 12）
        slow: 慢线周期（默认 26）
        signal: signal线周期（默认 9）
        use_histogram: True=同时用histogram过滤信号（默认 True）
    """

    name = "MACD"
    description = "MACD 金叉死叉策略"

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        use_histogram: bool = True,
    ):
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.use_histogram = use_histogram

    def generate_signals_for_symbol(
        self, symbol: str, bars: list[OHLCVBar]
    ) -> list[Signal]:
        min_len = self.slow + self.signal_period + 1
        if len(bars) < min_len:
            return []

        closes = [b.close_ for b in bars]
        macd_line, signal_line, histogram = macd(
            closes, self.fast, self.slow, self.signal_period
        )

        signals = []
        prev_hist_positive = None

        for i in range(1, len(bars)):
            curr_macd = macd_line[i]
            prev_macd = macd_line[i - 1]
            curr_sig = signal_line[i]
            prev_sig = signal_line[i - 1]
            curr_hist = histogram[i]
            prev_hist = histogram[i - 1]

            if curr_macd is None or prev_macd is None:
                continue
            if curr_sig is None or prev_sig is None:
                continue

            bar = bars[i]

            # MACD 金叉
            if prev_macd <= prev_sig and curr_macd > curr_sig:
                # histogram 确认（可选）
                if self.use_histogram and curr_hist is not None and curr_hist < 0:
                    continue  # 在零轴下方，暂不买
                signals.append(Signal(
                    symbol=symbol,
                    action=Action.BUY,
                    price=bar.close_,
                    confidence=0.8,
                    reason=f"MACD金叉: {curr_macd:.4f} > signal({curr_sig:.4f})",
                    timestamp=bar.trade_time,
                ))

            # MACD 死叉
            if prev_macd >= prev_sig and curr_macd < curr_sig:
                if self.use_histogram and curr_hist is not None and curr_hist > 0:
                    continue  # 在零轴上方，暂不卖
                signals.append(Signal(
                    symbol=symbol,
                    action=Action.SELL,
                    price=bar.close_,
                    confidence=0.8,
                    reason=f"MACD死叉: {curr_macd:.4f} < signal({curr_sig:.4f})",
                    timestamp=bar.trade_time,
                ))

        return signals

    def get_params(self) -> dict:
        return {
            "fast": self.fast,
            "slow": self.slow,
            "signal": self.signal_period,
            "use_histogram": self.use_histogram,
        }

    def get_required_intervals(self) -> list[str]:
        return ["1d"]
