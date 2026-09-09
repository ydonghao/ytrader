"""
内置策略集
"""
from .sma_cross import SMACrossStrategy
from .rsi import RSIStrategy
from .macd import MACDStrategy
from .bollinger import BollingerStrategy

STRATEGY_REGISTRY: dict[str, type] = {
    "sma_cross": SMACrossStrategy,
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "bollinger": BollingerStrategy,
}


def get_strategy(name: str, **kwargs):
    """通过名字获取策略实例"""
    cls = STRATEGY_REGISTRY.get(name.lower())
    if cls is None:
        available = ", ".join(STRATEGY_REGISTRY.keys())
        raise ValueError(f"Unknown strategy '{name}'. Available: {available}")
    return cls(**kwargs)


__all__ = [
    "SMACrossStrategy",
    "RSIStrategy",
    "MACDStrategy",
    "BollingerStrategy",
    "STRATEGY_REGISTRY",
    "get_strategy",
]
