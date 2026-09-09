"""自选股(分组) SQLModel 表定义。

两张表:
- WatchlistGroup: 分组(如 高股息 / 科技ETF / 港股通)
- WatchlistItem:  组内股票(symbol + 备注 + 排序)

通过 SQLModel.metadata.create_all 自动建表。
注意: 本模块必须在 main.py 启动时被 import, 否则主服务进程的
create_all 看不到这些表(参考 portfolio.models 的注册方式)。
"""
from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, UniqueConstraint


class WatchlistGroup(SQLModel, table=True):
    """自选股分组。单用户/全局(无 user_id)。"""

    __tablename__ = "watchlist_group"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    sort_index: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint("name", name="uq_watchlist_group_name"),
    )


class WatchlistItem(SQLModel, table=True):
    """组内股票。同组 (group_id, symbol) 唯一; 跨组可重复。"""

    __tablename__ = "watchlist_item"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="watchlist_group.id", index=True)
    symbol: str = Field(index=True)
    note: Optional[str] = None
    sort_index: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "group_id", "symbol", name="uq_watchlist_item_group_symbol"
        ),
    )
