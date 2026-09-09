"""
策略基类
=========
所有交易策略的抽象基类。
"""
from abc import ABC, abstractmethod
from typing import Optional

from ..sync.sync_provider import OHLCVBar
from .signals import Signal


class Strategy(ABC):
    """
    策略抽象基类
    
    所有策略必须实现 generate_signals 方法，
    输入K线数据，输出交易信号列表。
    """

    name: str = "BaseStrategy"
    description: str = ""

    @abstractmethod
    def generate_signals(self, bars: list[OHLCVBar]) -> list[Signal]:
        """
        生成交易信号
        
        Args:
            bars: OHLCVBar 列表（按时间升序）
            
        Returns:
            Signal 列表
        """
        ...

    def get_required_intervals(self) -> list[str]:
        """
        该策略需要的K线周期。
        
        Returns:
            如 ["1d"] 或 ["5m", "60m"]
        """
        return ["1d"]

    def get_params(self) -> dict:
        """返回当前参数（用于记录和优化）"""
        return {}

    def __str__(self) -> str:
        return f"{self.name}({self.get_params()})"


class SingleSymbolStrategy(Strategy):
    """
    单标的策略（辅助类）
    
    很多策略只需要关注单个标的，
    这个类把多标的K线分发给单标的处理。
    """

    @abstractmethod
    def generate_signals_for_symbol(
        self, symbol: str, bars: list[OHLCVBar]
    ) -> list[Signal]:
        """
        对单个标的生成信号
        
        默认实现：直接把 bars 传给策略，
        子类可覆盖以实现更复杂逻辑。
        """
        ...

    def generate_signals(self, bars: list[OHLCVBar]) -> list[Signal]:
        if not bars:
            return []
        
        # 按 symbol 分组
        from collections import defaultdict
        by_symbol: dict[str, list[OHLCVBar]] = defaultdict(list)
        for bar in bars:
            by_symbol[bar.symbol].append(bar)

        signals = []
        for symbol, symbol_bars in by_symbol.items():
            symbol_bars.sort(key=lambda x: x.trade_time)
            sigs = self.generate_signals_for_symbol(symbol, symbol_bars)
            signals.extend(sigs)
        
        return signals
