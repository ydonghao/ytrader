"""
信号与持仓数据模型
====================
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Action(Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"   # 平仓
    HOLD = "HOLD"


@dataclass
class Signal:
    """交易信号"""
    symbol: str
    action: Action
    price: float
    quantity: int = 0
    confidence: float = 1.0   # 0.0 ~ 1.0
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if isinstance(self.action, str):
            self.action = Action(self.action.upper())

    def __str__(self):
        return (
            f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] "
            f"{self.symbol} {self.action.value} @ {self.price:.2f} "
            f"(confidence={self.confidence:.0%}, reason={self.reason})"
        )


@dataclass
class Position:
    """持仓"""
    symbol: str
    quantity: int
    avg_price: float
    unrealized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.avg_price

    def update_pnl(self, current_price: float) -> float:
        self.unrealized_pnl = (current_price - self.avg_price) * self.quantity
        return self.unrealized_pnl


@dataclass
class Trade:
    """成交记录"""
    symbol: str
    action: Action          # BUY or SELL/CLOSE
    price: float
    quantity: int
    commission: float       # 手续费
    timestamp: datetime
    pnl: float = 0.0       # 平仓盈亏（SELL时计算）

    @property
    def amount(self) -> float:
        return self.price * self.quantity
