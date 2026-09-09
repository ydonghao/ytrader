"""北向资金 + 融资融券余额 表：A 股市场资金面日频数据。

两张日频市场级表（均按 trade_date 主键），供资金面信号分析
（intel.market.fund_flow）使用：

  north_flow_daily        北向资金（沪深港通）每日净买入
  margin_balance_daily    融资融券余额（上交所市场汇总）

数据来源：akshare stock_hsgt_hist_em / stock_margin_sse。
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


class NorthFlowDaily(SQLModel, table=True):
    """北向资金每日净买入（按 trade_date）。"""

    __tablename__ = "north_flow_daily"

    trade_date: dt.date = Field(primary_key=True)
    net_buy: Optional[float] = None          # 当日净买入额（元）
    created_at: datetime = Field(default_factory=datetime.now)


class MarginBalanceDaily(SQLModel, table=True):
    """融资融券余额日频（上交所市场汇总，按 trade_date）。"""

    __tablename__ = "margin_balance_daily"

    trade_date: dt.date = Field(primary_key=True)
    margin_balance: Optional[float] = None   # 融资融券余额（元）
    created_at: datetime = Field(default_factory=datetime.now)


def _bulk_upsert(table_name: str, rows: list[dict], fields: list[tuple]) -> int:
    """通用日频单主键表批量 upsert。
    fields: [(dict_key, col_name), ...]。
    """
    if not rows:
        return 0
    cols = [f for _, f in fields]
    placeholders = ", ".join(f"EXCLUDED.{c}" for _, c in fields[1:])  # 主键不更新
    col_list = ", ".join(cols)
    values = []
    for r in rows:
        row = []
        for k, _ in fields:
            v = r.get(k)
            if hasattr(v, "date") and callable(v.date):
                v = v.date()
            row.append(v)
        values.append(tuple(row))
    sql = (
        f"INSERT INTO {table_name} ({col_list}) VALUES %s "
        f"ON CONFLICT ({fields[0][1]}) DO UPDATE SET {placeholders}"
    )
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            execute_values(cur, sql, values)
        conn.commit()
    finally:
        conn.close()
    return len(values)


class MarketSentimentRepository:
    """北向资金 + 两融余额数据访问。"""

    def upsert_north_flow(self, rows: list[dict]) -> int:
        return _bulk_upsert(
            "north_flow_daily", rows,
            [("trade_date", "trade_date"), ("net_buy", "net_buy")],
        )

    def upsert_margin_balance(self, rows: list[dict]) -> int:
        return _bulk_upsert(
            "margin_balance_daily", rows,
            [("trade_date", "trade_date"), ("margin_balance", "margin_balance")],
        )

    def get_north_flow(self, limit: int = 60) -> list:
        """返回北向资金净买入序列（最近 N 个交易日，升序）。"""
        with self._db.session_scope() as s:
            stmt = (
                select(NorthFlowDaily)
                .order_by(NorthFlowDaily.trade_date.desc())
                .limit(limit)
            )
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            rows.reverse()
            return rows

    def get_margin_balance(self, limit: int = 60) -> list[MarginBalanceDaily]:
        with self._db.session_scope() as s:
            stmt = (
                select(MarginBalanceDaily)
                .order_by(MarginBalanceDaily.trade_date.desc())
                .limit(limit)
            )
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            rows.reverse()
            return rows

    def __init__(self, db: DBConnection):
        self._db = db


_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_market_sentiment_repository(
    db_connection: DBConnection | None = None,
) -> MarketSentimentRepository:
    return MarketSentimentRepository(db_connection or _get_db_connection())
