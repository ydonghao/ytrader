"""宽基指数成分股快照表。

index_constituent: 中证系宽基指数（沪深300/中证500/…）最新成分快照，
  job 全量重灌（事务内 DELETE + INSERT，幂等）。
  历史成分不做回溯（csindex 只有最新快照）——下游聚合以当前成分近似
  历史口径（幸存者偏差，数据行 source='computed' 标注）。

下游：指数财务聚合（index_financial_quarterly scope='index'）、
      指数市值回填（index_valuation_daily.total_mv）。
表由 SQLModel.metadata.create_all 惰性建表（同 sw_industry_member 惯例）。
"""
import datetime as dt
import threading
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import Column, DateTime, func
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class IndexConstituent(SQLModel, table=True):
    """宽基指数成分股快照（PK(index_code, stock_symbol)）。"""
    __tablename__ = "index_constituent"

    index_code: str = Field(primary_key=True)    # 000300
    stock_symbol: str = Field(primary_key=True)  # sh600519
    stock_name: Optional[str] = None
    weight: Optional[float] = None               # 权重%
    as_of_date: Optional[dt.date] = None         # 成分快照日
    synced_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now()),
    )


_MEMBER_COLUMNS = (
    "index_code", "stock_symbol", "stock_name", "weight", "as_of_date",
)


class IndexConstituentRepository:
    """指数成分股数据访问（SQLModel 读 + psycopg2 批量写）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def replace_members(self, index_code: str, rows: list[dict]) -> int:
        """单指数全量重灌（单事务 DELETE + INSERT，幂等）。"""
        if not rows:
            return 0
        values = [tuple(r.get(c) for c in _MEMBER_COLUMNS) for r in rows]
        dele = "DELETE FROM index_constituent WHERE index_code = %s"
        ins = """
            INSERT INTO index_constituent ({cols})
            VALUES %s
        """.format(cols=", ".join(_MEMBER_COLUMNS))
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(dele, (index_code,))
                execute_values(cur, ins, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def get_members(self, index_code: str) -> list[str]:
        """成分股 symbol 列表（sh600519…）。"""
        with self._db.session_scope() as s:
            rows = list(s.exec(
                select(IndexConstituent.stock_symbol).where(
                    IndexConstituent.index_code == index_code
                )
            ).all())
            return [r for r in rows if r]


# ======== 工厂函数（模式同 index_financial.py）========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_index_constituent_repository(
    db_connection: DBConnection | None = None,
) -> IndexConstituentRepository:
    """创建指数成分股仓储实例（首次调用触发惰性建表）。"""
    return IndexConstituentRepository(db_connection or _get_db_connection())
