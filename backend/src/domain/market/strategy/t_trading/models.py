"""
做T数据模型
============
TTrade:        单笔做T成交
TSignal:       算法产生的交易意图（引擎校验 T+1 后才执行）
TStrategyState: 引擎维护的日内状态（透传给算法）
TDayResult:    单日做T结果
TBacktestResult: 整体回测结果
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .cost_model import CostBreakdown, TCostModel


@dataclass
class TTrade:
    """单笔做T成交"""
    timestamp: datetime
    action: str                 # "BUY" | "SELL"
    price: float
    quantity: int
    commission: float = 0.0
    stamp_duty: float = 0.0
    transfer_fee: float = 0.0
    slippage: float = 0.0
    reason: str = ""            # 触发原因（算法给出）

    @property
    def amount(self) -> float:
        """成交金额（不含成本）"""
        return self.price * self.quantity

    @property
    def total_cost(self) -> float:
        """该笔全部成本"""
        return self.commission + self.stamp_duty + self.transfer_fee + self.slippage

    @property
    def is_sell(self) -> bool:
        return self.action.upper() == "SELL"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M"),
            "action": self.action,
            "price": round(self.price, 3),
            "quantity": self.quantity,
            "amount": round(self.amount, 2),
            "commission": round(self.commission, 4),
            "stamp_duty": round(self.stamp_duty, 4),
            "transfer_fee": round(self.transfer_fee, 4),
            "slippage": round(self.slippage, 4),
            "total_cost": round(self.total_cost, 4),
            "reason": self.reason,
        }


@dataclass
class TSignal:
    """
    算法产生的交易意图。

    引擎会校验：
      - 卖出量 ≤ 当前可卖底仓（T+1：当日新买部分不可卖）
      - 买入量 ≤ 可用资金
    校验通过才转为 TTrade。
    """
    action: str                 # "BUY" | "SELL"
    quantity: int
    reason: str = ""


@dataclass
class TStrategyState:
    """
    引擎维护的日内状态，透传给算法 on_bar()，供算法决策。

    Attributes:
        base_shares:      底仓总股数（不变，恢复基准）
        sellable_shares:  当前可卖股数（= 底仓 - 日内已卖净额，受 T+1 限制）
        intraday_net:     日内净头寸（买入为正，卖出为负；归零表示底仓已恢复）
        cash:             可用现金（日内随买卖增减）
        day_open:         当日开盘价
        prev_close:       昨收价
        qty_today:        今日已成交股数（买入+卖出绝对值累计）
    """
    base_shares: int
    sellable_shares: int
    intraday_net: int = 0
    cash: float = 0.0
    day_open: float = 0.0
    prev_close: float = 0.0
    qty_today: int = 0


@dataclass
class TDayResult:
    """单日做T结果"""
    day: date
    trades: list[TTrade] = field(default_factory=list)
    gross_pnl: float = 0.0       # 毛收益（差价，未扣成本）
    net_pnl: float = 0.0         # 净收益（扣成本后）
    cost_total: float = 0.0      # 当日总成本
    cost_breakdown: CostBreakdown = field(default_factory=CostBreakdown)
    close_price: float = 0.0     # 当日收盘价（用于价格走势图）

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0

    def to_dict(self) -> dict:
        return {
            "day": self.day.isoformat(),
            "trades": len(self.trades),
            "gross_pnl": round(self.gross_pnl, 2),
            "net_pnl": round(self.net_pnl, 2),
            "cost_total": round(self.cost_total, 2),
            "cost_breakdown": self.cost_breakdown.to_dict(),
            "close_price": round(self.close_price, 3),
        }


@dataclass
class TBacktestResult:
    """
    做T回测整体结果。

    收益定义（小白直观）：
      做T收益 = 日内低买高卖产生的净现金流，与股票本身涨跌无关。
      收盘强制平掉日内净头寸恢复底仓，全程净赚的现金即做T价值。

    关键指标：
      - total_net_pnl:   做T总净收益（元）
      - total_return_pct: 做T收益率 = 总净收益 / 期初底仓市值 * 100%
      - cost_reduction:   降低持仓成本（元/股）= 总净收益 / 底仓股数
    """
    algorithm: str
    symbol: str
    interval: str
    start_date: str
    end_date: str
    base_shares: int
    base_price: float            # 期初底仓参考价（用于算市值/收益率）
    total_net_pnl: float = 0.0   # 做T总净收益（元）
    total_return_pct: float = 0.0  # 相对底仓市值的收益率%
    cost_reduction: float = 0.0  # 降低持仓成本（元/股）
    gross_pnl: float = 0.0       # 毛收益（未扣成本）
    total_cost: float = 0.0      # 总成本
    cost_breakdown: CostBreakdown = field(default_factory=CostBreakdown)
    total_trades: int = 0
    total_buys: int = 0
    total_sells: int = 0
    total_days: int = 0
    win_days: int = 0
    daily_results: list[TDayResult] = field(default_factory=list)
    trades: list[TTrade] = field(default_factory=list)
    price_series: list[dict] = field(default_factory=list)  # 价格走势+买卖点

    def to_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "symbol": self.symbol,
            "interval": self.interval,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "base_shares": self.base_shares,
            "base_price": round(self.base_price, 3),
            "base_market_value": round(self.base_shares * self.base_price, 2),
            "total_net_pnl": round(self.total_net_pnl, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "cost_reduction": round(self.cost_reduction, 4),
            "gross_pnl": round(self.gross_pnl, 2),
            "total_cost": round(self.total_cost, 2),
            "cost_breakdown": self.cost_breakdown.to_dict(),
            "total_trades": self.total_trades,
            "total_buys": self.total_buys,
            "total_sells": self.total_sells,
            "total_days": self.total_days,
            "win_days": self.win_days,
            "win_rate": round(self.win_days / self.total_days * 100, 2)
            if self.total_days
            else 0.0,
            "daily_results": [d.to_dict() for d in self.daily_results],
            "trades": [t.to_dict() for t in self.trades],
            "price_series": self.price_series,
        }
