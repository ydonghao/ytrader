"""index_ohlcv 表：A 股指数日线（宽基 / 行业 / 主题）。

与 commodity_ohlcv 同为"非个股资产类独立建表"，但指数量级小、无 asset_class
细分，故 market 列统一填 'INDEX'，前端按 symbol 区分。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

# 字段名 `date` 会遮蔽 datetime.date，用模块别名 dt.date 引用类型注解。
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class IndexOhlcv(SQLModel, table=True):
    """指数日线记录（沪深300 / 上证综指 / 创业板指 等）。"""

    __tablename__ = "index_ohlcv"

    symbol: str = Field(primary_key=True)        # sh000300 / sz399001 ...
    date: dt.date = Field(primary_key=True)
    open_: Optional[float] = None
    high_: Optional[float] = None
    low_: Optional[float] = None
    close_: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    market: str = Field(default="INDEX")
    created_at: datetime = Field(default_factory=datetime.now)


class IndexOhlcvRepository:
    """指数数据访问（守 SQLModel ORM 规范）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def upsert(
        self,
        symbol: str,
        date_: dt.date,
        open_: Optional[float] = None,
        high_: Optional[float] = None,
        low_: Optional[float] = None,
        close_: Optional[float] = None,
        volume: Optional[float] = None,
        amount: Optional[float] = None,
    ) -> None:
        """插入或更新（按 symbol+date 主键）一条指数日线。"""
        with self._db.session_scope() as s:
            existing = s.exec(
                select(IndexOhlcv).where(
                    IndexOhlcv.symbol == symbol, IndexOhlcv.date == date_
                )
            ).first()
            if existing:
                existing.open_ = open_
                existing.high_ = high_
                existing.low_ = low_
                existing.close_ = close_
                existing.volume = volume
                existing.amount = amount
            else:
                s.add(
                    IndexOhlcv(
                        symbol=symbol, date=date_,
                        open_=open_, high_=high_, low_=low_,
                        close_=close_, volume=volume, amount=amount,
                    )
                )

    def get_latest_date(self, symbol: str) -> Optional[dt.date]:
        """返回指定指数最新记录的日期；无数据为 None。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(IndexOhlcv)
                .where(IndexOhlcv.symbol == symbol)
                .order_by(IndexOhlcv.date.desc())
            ).first()
            return row.date if row else None


# ======== 工厂函数（遵循 intel/blog 单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_index_ohlcv_repository(
    db_connection: DBConnection | None = None,
) -> IndexOhlcvRepository:
    """创建指数仓储实例。"""
    return IndexOhlcvRepository(db_connection or _get_db_connection())
