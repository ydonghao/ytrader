"""时光机模拟驾驶舱 — 旅程会话与成交记录表。

本模块必须在 main.py 启动时被 import，否则主服务进程的 create_all
看不到这些表（参考 watchlist.models 的注册方式）。
"""

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ReplaySession(SQLModel, table=True):
    """一次时光机旅程。单用户/全局（无 user_id，同 watchlist）。"""

    __tablename__ = "replay_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    status: str = "active"  # active | revealed
    start_date: date
    current_date: date
    end_date: Optional[date] = None
    initial_capital: float
    cash: float  # 冗余快照，列表页展示用
    benchmark_symbol: str = "sh000300"
    # {pool: [symbol], positions: [{symbol,shares,cost_price,buy_date}],
    #  nav: [{date, value}]}
    state: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ReplayTrade(SQLModel, table=True):
    """旅程内一笔成交（当日收盘价撮合）。"""

    __tablename__ = "replay_trade"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="replay_session.id", index=True)
    trade_date: date
    symbol: str
    side: str  # buy | sell
    price: float  # stock_ohlcv 原样口径
    shares: int
    fee: float  # 佣金
    tax: float = 0.0  # 印花税（卖出）
    note: Optional[str] = None  # 下单理由，复盘回看
    created_at: datetime = Field(default_factory=datetime.now)
