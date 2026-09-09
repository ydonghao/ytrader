"""
做T算法模块（T-Trading）
========================
A 股 T+1 制度下，靠底仓日内高抛低吸降低持仓成本。

约束：
  - T+1：当日新买入的股票当日不可卖出，只能卖手中已有的底仓。
  - 日内净额平衡：收盘强制平掉日内净头寸，恢复底仓数量。

子模块：
  - cost_model: A 股做T成本（佣金/最低5元/印花税/过户费/滑点）
  - models:     TTrade / TDayResult / TBacktestResult
  - t_backtester: 做T回测引擎
  - strategies:  grid / fixed_band / ma_deviation / martingale
"""
from .cost_model import TCostModel, CostBreakdown
from .models import (
    TTrade,
    TDayResult,
    TBacktestResult,
    TSignal,
    TStrategyState,
)

__all__ = [
    "TCostModel",
    "CostBreakdown",
    "TTrade",
    "TDayResult",
    "TBacktestResult",
    "TSignal",
    "TStrategyState",
]
