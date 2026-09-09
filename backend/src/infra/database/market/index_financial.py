"""指数/行业季度财务聚合表。

把指数（沪深300等）或申万一级行业当作整体，按报告期聚合成分股财务：
  ROE（净资产加权）、净利率/毛利率（净利/营收加总比）、
  营收/净利/资产总额（成分股加总）。

scope_type: "index"（宽基）| "sw"（申万行业）
scope_code: 指数代码 或 申万行业代码
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


class IndexFinancialQuarterly(SQLModel, table=True):
    """指数/行业季度财务聚合。"""
    __tablename__ = "index_financial_quarterly"

    scope_type: str = Field(primary_key=True)   # index | sw
    scope_code: str = Field(primary_key=True)   # 000300 | sw801010
    report_date: dt.date = Field(primary_key=True)
    roe: Optional[float] = None                 # 净资产加权 ROE (%)
    net_margin: Optional[float] = None          # 净利率 = Σ净利/Σ营收 (%)
    gross_margin: Optional[float] = None        # 毛利率 (%)
    revenue_sum: Optional[float] = None         # 成分股营收加总(亿)
    net_profit_sum: Optional[float] = None      # 成分股净利加总(亿)
    assets_sum: Optional[float] = None          # 成分股总资产加总(亿)
    sample_count: int = 0                       # 纳入计算的成分股数
    created_at: datetime = Field(
        sa_column=Column(DateTime, server_default=func.now(), nullable=False)
    )


class IndexFinancialRepository:
    """指数/行业财务聚合数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def upsert(self, scope_type: str, scope_code: str, report_date: dt.date,
               roe=None, net_margin=None, gross_margin=None,
               revenue_sum=None, net_profit_sum=None, assets_sum=None,
               sample_count=0) -> None:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(IndexFinancialQuarterly).where(
                    IndexFinancialQuarterly.scope_type == scope_type,
                    IndexFinancialQuarterly.scope_code == scope_code,
                    IndexFinancialQuarterly.report_date == report_date,
                )
            ).first()
            if existing:
                existing.roe = roe
                existing.net_margin = net_margin
                existing.gross_margin = gross_margin
                existing.revenue_sum = revenue_sum
                existing.net_profit_sum = net_profit_sum
                existing.assets_sum = assets_sum
                existing.sample_count = sample_count
            else:
                s.add(IndexFinancialQuarterly(
                    scope_type=scope_type, scope_code=scope_code,
                    report_date=report_date, roe=roe, net_margin=net_margin,
                    gross_margin=gross_margin, revenue_sum=revenue_sum,
                    net_profit_sum=net_profit_sum, assets_sum=assets_sum,
                    sample_count=sample_count,
                ))

    def get_series(
        self, scope_type: str, scope_code: str,
        start: Optional[dt.date] = None, end: Optional[dt.date] = None,
    ) -> list[IndexFinancialQuarterly]:
        with self._db.session_scope() as s:
            stmt = select(IndexFinancialQuarterly).where(
                IndexFinancialQuarterly.scope_type == scope_type,
                IndexFinancialQuarterly.scope_code == scope_code,
            )
            if start:
                stmt = stmt.where(IndexFinancialQuarterly.report_date >= start)
            if end:
                stmt = stmt.where(IndexFinancialQuarterly.report_date <= end)
            stmt = stmt.order_by(IndexFinancialQuarterly.report_date.asc())
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def bulk_upsert(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        values = []
        for r in rows:
            rd = r.get("report_date")
            if hasattr(rd, "date"):
                rd = rd.date()
            values.append((
                r["scope_type"], r["scope_code"], rd,
                r.get("roe"), r.get("net_margin"), r.get("gross_margin"),
                r.get("revenue_sum"), r.get("net_profit_sum"),
                r.get("assets_sum"), r.get("sample_count", 0),
            ))
        sql = """
            INSERT INTO index_financial_quarterly
                (scope_type, scope_code, report_date, roe, net_margin,
                 gross_margin, revenue_sum, net_profit_sum, assets_sum,
                 sample_count)
            VALUES %s
            ON CONFLICT (scope_type, scope_code, report_date) DO UPDATE SET
                roe=EXCLUDED.roe, net_margin=EXCLUDED.net_margin,
                gross_margin=EXCLUDED.gross_margin, revenue_sum=EXCLUDED.revenue_sum,
                net_profit_sum=EXCLUDED.net_profit_sum, assets_sum=EXCLUDED.assets_sum,
                sample_count=EXCLUDED.sample_count
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)


# ======== 工厂函数 ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_index_financial_repository(
    db_connection: DBConnection | None = None,
) -> IndexFinancialRepository:
    """创建指数/行业财务聚合仓储实例。"""
    return IndexFinancialRepository(db_connection or _get_db_connection())
