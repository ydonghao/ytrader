"""指数/申万行业估值日线表。

两张表结构相同，分别存宽基指数（沪深300/上证50/中证500/1000）和
申万一级行业的估值日线。数据来源：
  - akshare sw_index_first_info（当天快照，每日落盘）
  - 成分股加权自算（历史回填，source='computed'）

口径：PE_TTM/PB/PS_TTM/股息率/总市值合计。
"""
import threading
import datetime as dt
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


class IndexValuationDaily(SQLModel, table=True):
    """宽基指数估值日线。"""
    __tablename__ = "index_valuation_daily"

    symbol: str = Field(primary_key=True)      # 000300 / 000016 / 000905 / 000852
    trade_date: dt.date = Field(primary_key=True)
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    dv_ttm: Optional[float] = None
    total_mv: Optional[float] = None           # 成分股总市值合计(亿)
    close: Optional[float] = None              # 指数收盘
    source: str = Field(default="akshare")     # akshare | computed
    created_at: datetime = Field(
        sa_column=Column(DateTime, server_default=func.now(), nullable=False)
    )


class SwIndexValuationDaily(SQLModel, table=True):
    """申万一级行业估值日线。"""
    __tablename__ = "sw_index_valuation_daily"

    sw_code: str = Field(primary_key=True)     # sw801010
    trade_date: dt.date = Field(primary_key=True)
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    dv_ttm: Optional[float] = None
    total_mv: Optional[float] = None
    close: Optional[float] = None
    source: str = Field(default="akshare")
    created_at: datetime = Field(
        sa_column=Column(DateTime, server_default=func.now(), nullable=False)
    )


class IndexValuationRepository:
    """指数/行业估值数据访问。同时管理两张表。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def upsert_index(
        self, symbol: str, trade_date: dt.date,
        pe_ttm=None, pb=None, ps_ttm=None, dv_ttm=None,
        total_mv=None, close=None, source="akshare",
    ) -> None:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(IndexValuationDaily).where(
                    IndexValuationDaily.symbol == symbol,
                    IndexValuationDaily.trade_date == trade_date,
                )
            ).first()
            if existing:
                existing.pe_ttm = pe_ttm
                existing.pb = pb
                existing.ps_ttm = ps_ttm
                existing.dv_ttm = dv_ttm
                existing.total_mv = total_mv
                existing.close = close
                existing.source = source
            else:
                s.add(IndexValuationDaily(
                    symbol=symbol, trade_date=trade_date,
                    pe_ttm=pe_ttm, pb=pb, ps_ttm=ps_ttm, dv_ttm=dv_ttm,
                    total_mv=total_mv, close=close, source=source,
                ))

    def upsert_sw(
        self, sw_code: str, trade_date: dt.date,
        pe_ttm=None, pb=None, ps_ttm=None, dv_ttm=None,
        total_mv=None, close=None, source="akshare",
    ) -> None:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(SwIndexValuationDaily).where(
                    SwIndexValuationDaily.sw_code == sw_code,
                    SwIndexValuationDaily.trade_date == trade_date,
                )
            ).first()
            if existing:
                existing.pe_ttm = pe_ttm
                existing.pb = pb
                existing.ps_ttm = ps_ttm
                existing.dv_ttm = dv_ttm
                existing.total_mv = total_mv
                existing.close = close
                existing.source = source
            else:
                s.add(SwIndexValuationDaily(
                    sw_code=sw_code, trade_date=trade_date,
                    pe_ttm=pe_ttm, pb=pb, ps_ttm=ps_ttm, dv_ttm=dv_ttm,
                    total_mv=total_mv, close=close, source=source,
                ))

    def get_index_range(
        self, symbol: str, start: dt.date, end: dt.date,
        source: Optional[str] = None,
    ) -> list[IndexValuationDaily]:
        """按 symbol+日期区间取日线；可选 source 过滤（None=不过滤）。"""
        with self._db.session_scope() as s:
            stmt = select(IndexValuationDaily).where(
                IndexValuationDaily.symbol == symbol,
                IndexValuationDaily.trade_date >= start,
                IndexValuationDaily.trade_date <= end,
            )
            if source:
                stmt = stmt.where(IndexValuationDaily.source == source)
            stmt = stmt.order_by(IndexValuationDaily.trade_date.asc())
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_sw_range(
        self, sw_code: str, start: dt.date, end: dt.date,
    ) -> list[SwIndexValuationDaily]:
        with self._db.session_scope() as s:
            rows = list(s.exec(
                select(SwIndexValuationDaily).where(
                    SwIndexValuationDaily.sw_code == sw_code,
                    SwIndexValuationDaily.trade_date >= start,
                    SwIndexValuationDaily.trade_date <= end,
                ).order_by(SwIndexValuationDaily.trade_date.asc())
            ).all())
            for r in rows:
                s.expunge(r)
            return rows

    def bulk_upsert_index(self, rows: list[dict]) -> int:
        return self._bulk_upsert(rows, "index_valuation_daily", "symbol")

    def bulk_upsert_index_mv(self, rows: list[dict]) -> int:
        """写 total_mv/pe_ttm 的批量 upsert（不覆盖 pb 等其他列）。"""
        if not rows:
            return 0
        values = []
        for r in rows:
            td = r.get("trade_date")
            if hasattr(td, "date"):
                td = td.date()
            values.append((r["symbol"], td, r.get("total_mv"),
                           r.get("pe_ttm"), r.get("source", "computed")))
        sql = """
            INSERT INTO index_valuation_daily
                (symbol, trade_date, total_mv, pe_ttm, source)
            VALUES %s
            ON CONFLICT (trade_date, symbol) DO UPDATE SET
                total_mv=EXCLUDED.total_mv, pe_ttm=EXCLUDED.pe_ttm,
                source=EXCLUDED.source
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def delete_index_mv(self, symbol: str) -> int:
        """删除某指数全部 computed 市值行（覆盖率门控重算前清理）。

        只删 source='computed'，不影响潜在 akshare 源的行。
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM index_valuation_daily "
                    "WHERE symbol = %s AND source = 'computed'",
                    (symbol,),
                )
                n = cur.rowcount
            conn.commit()
        finally:
            conn.close()
        return n

    def bulk_upsert_sw(self, rows: list[dict]) -> int:
        return self._bulk_upsert(rows, "sw_index_valuation_daily", "sw_code")

    def _bulk_upsert(
        self, rows: list[dict], table: str, code_key: str,
    ) -> int:
        if not rows:
            return 0
        values = []
        for r in rows:
            td = r.get("trade_date")
            if hasattr(td, "date"):
                td = td.date()
            values.append((
                r[code_key], td,
                r.get("pe_ttm"), r.get("pb"), r.get("ps_ttm"),
                r.get("dv_ttm"), r.get("total_mv"), r.get("close"),
                r.get("source", "akshare"),
            ))
        sql = f"""
            INSERT INTO {table}
                ({code_key}, trade_date, pe_ttm, pb, ps_ttm,
                 dv_ttm, total_mv, close, source)
            VALUES %s
            ON CONFLICT (trade_date, {code_key}) DO UPDATE SET
                pe_ttm=EXCLUDED.pe_ttm, pb=EXCLUDED.pb, ps_ttm=EXCLUDED.ps_ttm,
                dv_ttm=EXCLUDED.dv_ttm, total_mv=EXCLUDED.total_mv,
                close=EXCLUDED.close, source=EXCLUDED.source
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)


# ======== 工厂函数（遵循 valuation.py 单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_index_valuation_repository(
    db_connection: DBConnection | None = None,
) -> IndexValuationRepository:
    """创建指数/行业估值仓储实例。"""
    return IndexValuationRepository(db_connection or _get_db_connection())
