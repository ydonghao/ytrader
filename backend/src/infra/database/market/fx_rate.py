"""fx_rate 表：汇率日线（标量比率，非 K 线）。"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

# 字段名 `date` 会遮蔽 datetime.date 类型，故以模块别名 dt.date
# 引用类型注解，避免 pydantic 解析失败。
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class FxRate(SQLModel, table=True):
    """汇率日线记录。

    `rate` 为收盘标量（兼容 portfolio 标量路径，如 USDCNY 中行折算价/100）；
    `open_/high_/low_` 为可选 OHLC（forex_hist_em 拉取的货币对填写）。
    """

    __tablename__ = "fx_rate"

    date: dt.date = Field(primary_key=True)
    pair: str = Field(primary_key=True)  # "USDCNY" | "USDCNH" | "EURUSD" ...
    rate: float                              # close
    open_: Optional[float] = Field(default=None)
    high_: Optional[float] = Field(default=None)
    low_: Optional[float] = Field(default=None)
    source: str = "akshare"
    created_at: datetime = Field(default_factory=datetime.now)


class FxRateRepository:
    """汇率数据访问（守 SQLModel ORM 规范）。"""

    def __init__(self, db: DBConnection):
        # db 须提供 session_scope() contextmanager（DBConnection 协议）
        self._db = db

    def upsert(
        self,
        date_: dt.date,
        pair: str,
        rate: float,
        source: str = "akshare",
        open_: Optional[float] = None,
        high_: Optional[float] = None,
        low_: Optional[float] = None,
    ) -> None:
        """插入或更新（按 date+pair 主键）一条汇率记录。

        OHLC 三列为可选：forex_hist_em 拉取的货币对填写；
        仅 close 的中行折算价路径可不传（保持 None）。
        """
        with self._db.session_scope() as s:
            existing = s.exec(
                select(FxRate).where(
                    FxRate.date == date_, FxRate.pair == pair
                )
            ).first()
            if existing:
                existing.rate = rate
                existing.open_ = open_
                existing.high_ = high_
                existing.low_ = low_
                existing.source = source
            else:
                s.add(
                    FxRate(
                        date=date_, pair=pair, rate=rate,
                        open_=open_, high_=high_, low_=low_,
                        source=source,
                    )
                )

    def get_latest_date(self, pair: str) -> Optional[dt.date]:
        """返回指定货币对最新记录的日期；无数据为 None。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(FxRate)
                .where(FxRate.pair == pair)
                .order_by(FxRate.date.desc())
            ).first()
            return row.date if row else None

    def get_rate(
        self, pair: str, on_or_before: dt.date
    ) -> Optional[float]:
        """返回指定货币对在 on_or_before 当天或最近的汇率。

        用于组合净值折算: 交易当日若缺汇率(如节假日), 取最近可用值,
        与收盘价的"最近交易日"语义一致。
        """
        with self._db.session_scope() as s:
            row = s.exec(
                select(FxRate)
                .where(FxRate.pair == pair, FxRate.date <= on_or_before)
                .order_by(FxRate.date.desc())
            ).first()
            return row.rate if row else None


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


def create_fx_rate_repository(
    db_connection: DBConnection | None = None,
) -> FxRateRepository:
    """创建汇率仓储实例。"""
    return FxRateRepository(db_connection or _get_db_connection())
