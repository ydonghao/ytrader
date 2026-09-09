"""
长期组合策略数据模型
====================
RebalanceSignal:   策略产生的调仓意图（目标权重）
Position:          持仓记录
PortfolioState:    引擎维护的组合状态，透传给策略
LongTermTrade:     单笔调仓成交
LongTermResult:    整体回测结果

设计要点：
  - 长线策略以"目标权重"表达持仓意图，引擎据此算买卖股数。
    这与做T/TA策略的"整仓买卖信号"不同，是组合管理的标准范式。
  - 组合状态（持仓/现金/总权益/当日价格）由引擎维护并透传给策略，
    策略只负责"在调仓日给出目标权重"，不关心执行细节。
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class RebalanceSignal:
    """
    调仓意图：各标的目标权重。

    weight 含义：占总权益的比例，0~1。
      - 0    表示清仓该标的
      - 0.25 表示占总权益 25%
    未列入的标的，目标权重视为 0（清仓）。
    所有标的权重之和应 ≤ 1.0；不足部分为现金。
    """
    target_weights: dict[str, float]
    reason: str = ""


@dataclass
class Position:
    """单个标的的持仓快照。"""
    symbol: str
    shares: int = 0
    avg_price: float = 0.0      # 持仓均价

    @property
    def market_value(self) -> float:
        """当前市值（需用最新价，由引擎在估值时填入）。"""
        return self._current_price * self.shares

    def __post_init__(self):
        self._current_price: float = 0.0

    def update_price(self, price: float) -> None:
        """引擎每日用收盘价更新。"""
        self._current_price = price


@dataclass
class PortfolioState:
    """
    引擎维护的组合状态，在调仓日透传给策略 on_rebalance()。

    Attributes:
        date:          当前日期
        holdings:      当前持仓 {symbol: Position}
        cash:          现金
        total_equity:  总权益 = 现金 + 持仓市值
        prices:        当日各标的收盘价 {symbol: price}
        universe:      可投资标的列表（策略选股池）
    """
    date: date
    holdings: dict[str, Position] = field(default_factory=dict)
    cash: float = 0.0
    total_equity: float = 0.0
    prices: dict[str, float] = field(default_factory=dict)
    universe: list[str] = field(default_factory=list)


@dataclass
class LongTermTrade:
    """单笔调仓成交。"""
    timestamp: datetime
    symbol: str
    action: str               # "BUY" | "SELL"
    shares: int
    price: float
    commission: float = 0.0
    stamp_duty: float = 0.0
    slippage_cost: float = 0.0
    reason: str = ""

    @property
    def amount(self) -> float:
        """成交金额（不含成本）。"""
        return self.price * self.shares

    @property
    def total_cost(self) -> float:
        return self.commission + self.stamp_duty + self.slippage_cost

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d"),
            "symbol": self.symbol,
            "action": self.action,
            "shares": self.shares,
            "price": round(self.price, 3),
            "amount": round(self.amount, 2),
            "commission": round(self.commission, 4),
            "stamp_duty": round(self.stamp_duty, 4),
            "total_cost": round(self.total_cost, 4),
            "reason": self.reason,
        }


@dataclass
class LongTermResult:
    """
    长期组合回测整体结果。

    关键指标（与做T结果口径不同，这里衡量的是组合净值表现）：
      - total_return_pct:  总收益率 %
      - cagr:              年化复合收益率 %
      - sharpe / sortino:  风险调整后收益（日频、年化）
      - max_drawdown:      最大回撤 %
      - max_dd_duration:   最大回撤持续天数
      - volatility:        年化波动率 %
      - benchmark_*:       基准（如沪深300买入持有）对照
      - alpha / beta:      相对基准
    """
    strategy: str
    symbols: list[str]
    start_date: str
    end_date: str
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    cagr: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_dd_duration: int = 0
    volatility: float = 0.0
    win_rate: float = 0.0
    rebalance_count: int = 0
    total_trades: int = 0
    benchmark_return_pct: float = 0.0
    benchmark_cagr: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    equity_curve: list[dict] = field(default_factory=list)
    rebalances: list[dict] = field(default_factory=list)
    trades: list[LongTermTrade] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "symbols": self.symbols,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": round(self.initial_capital, 2),
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "cagr": round(self.cagr, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_dd_duration": self.max_dd_duration,
            "volatility": round(self.volatility, 2),
            "win_rate": round(self.win_rate, 2),
            "rebalance_count": self.rebalance_count,
            "total_trades": self.total_trades,
            "benchmark_return_pct": round(self.benchmark_return_pct, 2),
            "benchmark_cagr": round(self.benchmark_cagr, 2),
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "equity_curve": self.equity_curve,
            "rebalances": self.rebalances,
            "trades": [t.to_dict() for t in self.trades],
        }
