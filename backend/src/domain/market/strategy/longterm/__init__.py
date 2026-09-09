"""
长期投资组合回测模块
====================
经典长期投资算法的量化回测引擎。与短期 TA 引擎（strategy/）、做T引擎
（t_trading/）并列，专门处理"多标的 + 定期调仓 + 目标权重"的组合管理。

子模块：
  - models:                RebalanceSignal / Position / PortfolioState /
                           LongTermTrade / LongTermResult
  - base:                  LongTermStrategy 基类 + ParamSpec
  - metrics:               Sharpe / Sortino / CAGR / MaxDrawdown / Alpha-Beta
  - calendar:              调仓频率判断 + 日线重采样
  - portfolio_backtester:  组合回测引擎
  - strategies/            7 个经典长期策略（动量/价值/趋势/资产配置/定投）
"""
from .base import LongTermStrategy, ParamSpec
from .calendar import FREQS, is_rebalance_day, resample_ohlcv
from .metrics import (
    alpha_beta,
    annualized_volatility,
    cagr,
    daily_returns,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    win_rate_from_trades,
)
from .models import (
    LongTermResult,
    LongTermTrade,
    PortfolioState,
    Position,
    RebalanceSignal,
)
from .portfolio_backtester import PortfolioBacktester

__all__ = [
    "LongTermStrategy",
    "ParamSpec",
    "FREQS",
    "is_rebalance_day",
    "resample_ohlcv",
    "alpha_beta",
    "annualized_volatility",
    "cagr",
    "daily_returns",
    "max_drawdown",
    "sharpe_ratio",
    "sortino_ratio",
    "win_rate_from_trades",
    "LongTermResult",
    "LongTermTrade",
    "PortfolioState",
    "Position",
    "RebalanceSignal",
    "PortfolioBacktester",
]
