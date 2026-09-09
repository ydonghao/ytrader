from .trading_router import router as trading_router
from .strategy_router import router as strategy_router
from .system_router import router as system_router
from .alerts_router import router as alerts_router
from .settings_router import router as settings_router

__all__ = [
    'trading_router',
    'strategy_router',
    'system_router',
    'alerts_router',
    'settings_router',
]
