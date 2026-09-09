"""stock_shareholder_count 表：A 股个股股东户数时序（每期报告一行）。

记录定期报告披露的股东户数、户均流通股、人均持股，供筹码集中度分析
（equity.concentration）使用。

数据来源：akshare ``stock_zh_a_gdhs_detail_em``（东方财富）。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlmodel import SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class StockShareholderCount(SQLModel, table=True):
    """个股股东户数记录（按 symbol + report_date）。"""

    __tablename__ = "stock_shareholder_count"

    symbol: str = Field(primary_key=True)
    report_date: dt.date = Field(primary_key=True)   # 报告期（如 2024-06-30）
    holder_count: Optional[int] = None               # 股东户数
    holder_count_avg: Optional[float] = None         # 区间平均户数
    per_capita_holding: Optional[float] = None       # 户均流通股
    price_change_pct: Optional[float] = None         # 报告期股价变化
    created_at: datetime = Field(default_factory=datetime.now)


class StockShareholderCountRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def bulk_upsert(self, rows: list[dict]) -> int:
        """批量插入/更新（ON CONFLICT 覆盖）。"""
        if not rows:
            return 0
        values = []
        for r in rows:
            rd = r.get("report_date")
            if hasattr(rd, "date") and callable(rd.date):
                rd = rd.date()
            values.append((
                r["symbol"], rd,
                r.get("holder_count"), r.get("holder_count_avg"),
                r.get("per_capita_holding"), r.get("price_change_pct"),
            ))
        sql = """
            INSERT INTO stock_shareholder_count
                (symbol, report_date, holder_count, holder_count_avg,
                 per_capita_holding, price_change_pct)
            VALUES %s
            ON CONFLICT (symbol, report_date) DO UPDATE SET
                holder_count = EXCLUDED.holder_count,
                holder_count_avg = EXCLUDED.holder_count_avg,
                per_capita_holding = EXCLUDED.per_capita_holding,
                price_change_pct = EXCLUDED.price_change_pct
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def get_history(
        self, symbol: str, limit: int = 20
    ) -> list[StockShareholderCount]:
        """返回股东户数历史（按报告期升序），默认最近 20 期。"""
        with self._db.session_scope() as s:
            stmt = (
                select(StockShareholderCount)
                .where(StockShareholderCount.symbol == symbol)
                .order_by(StockShareholderCount.report_date.desc())
                .limit(limit)
            )
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            rows.reverse()
            return rows


_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_shareholder_count_repository(
    db_connection: DBConnection | None = None,
) -> StockShareholderCountRepository:
    return StockShareholderCountRepository(db_connection or _get_db_connection())
