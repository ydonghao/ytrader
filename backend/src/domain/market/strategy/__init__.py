"""
策略框架
=========
导出主要类供外部使用。
"""
from .signals import Action, Position, Signal, Trade
from .base import Strategy, SingleSymbolStrategy
from .backtester import Backtester, BacktestResult
from .optimizer import GridOptimizer
from .strategies import get_strategy, STRATEGY_REGISTRY

__all__ = [
    "Action", "Signal", "Position", "Trade",
    "Strategy", "SingleSymbolStrategy",
    "Backtester", "BacktestResult",
    "GridOptimizer",
    "get_strategy", "STRATEGY_REGISTRY",
]
