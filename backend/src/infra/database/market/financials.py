"""stock_financials 表：A 股个股财务指标（ROE 等，按报告期）。

记录按季度报告期的核心财务质量指标，供价值策略做点-in-time 质量筛选。
注意：财务数据有披露滞后（季报通常滞后 1~3 个月），调用方应使用
report_date <= T - N 天的记录以避免未来函数。

数据来源：akshare ak.stock_financial_analysis_indicator（新浪）。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class StockFinancials(SQLModel, table=True):
    """个股财务指标记录（按报告期）。"""

    __tablename__ = "stock_financials"

    symbol: str = Field(primary_key=True)
    report_date: dt.date = Field(primary_key=True)    # 报告期（季末日期）
    roe_weighted: Optional[float] = None              # 加权净资产收益率 %
    roe_diluted: Optional[float] = None               # 摊薄净资产收益率 %
    gross_margin: Optional[float] = None              # 销售毛利率 %
    net_margin: Optional[float] = None                # 销售净利率 %
    debt_ratio: Optional[float] = None                # 资产负债率 %
    created_at: datetime = Field(default_factory=datetime.now)


class StockFinancialsRepository:
    """个股财务指标数据访问（守 SQLModel ORM 规范）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def upsert(
        self,
        symbol: str,
        report_date: dt.date,
        roe_weighted: Optional[float] = None,
        roe_diluted: Optional[float] = None,
        gross_margin: Optional[float] = None,
        net_margin: Optional[float] = None,
        debt_ratio: Optional[float] = None,
    ) -> None:
        """插入或更新（按 symbol+report_date 主键）一条财务记录。"""
        with self._db.session_scope() as s:
            existing = s.exec(
                select(StockFinancials).where(
                    StockFinancials.symbol == symbol,
                    StockFinancials.report_date == report_date,
                )
            ).first()
            if existing:
                existing.roe_weighted = roe_weighted
                existing.roe_diluted = roe_diluted
                existing.gross_margin = gross_margin
                existing.net_margin = net_margin
                existing.debt_ratio = debt_ratio
            else:
                s.add(
                    StockFinancials(
                        symbol=symbol,
                        report_date=report_date,
                        roe_weighted=roe_weighted,
                        roe_diluted=roe_diluted,
                        gross_margin=gross_margin,
                        net_margin=net_margin,
                        debt_ratio=debt_ratio,
                    )
                )

    def get_latest_report_date(self, symbol: str) -> Optional[dt.date]:
        """返回指定个股最新财务报告期；无数据为 None。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(StockFinancials)
                .where(StockFinancials.symbol == symbol)
                .order_by(StockFinancials.report_date.desc())
            ).first()
            return row.report_date if row else None

    def get_as_of(
        self, symbol: str, as_of: dt.date
    ) -> Optional[StockFinancials]:
        """
        点-in-time 查询：返回 report_date <= as_of 的最新一期财务记录。

        调用方应在 as_of 中预留财报披露滞后（通常 as_of = 决策日 - 60 天），
        以确保只用到决策日时点已公开披露的财报。
        """
        with self._db.session_scope() as s:
            return s.exec(
                select(StockFinancials)
                .where(
                    StockFinancials.symbol == symbol,
                    StockFinancials.report_date <= as_of,
                )
                .order_by(StockFinancials.report_date.desc())
            ).first()

    def get_history(
        self,
        symbol: str,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        limit: int = 200,
    ) -> list[StockFinancials]:
        """返回报告期序列（按升序），可选区间过滤。默认上限 200 期。"""
        limit = max(1, min(int(limit), 500))
        with self._db.session_scope() as s:
            stmt = select(StockFinancials).where(
                StockFinancials.symbol == symbol
            )
            if start is not None:
                stmt = stmt.where(StockFinancials.report_date >= start)
            if end is not None:
                stmt = stmt.where(StockFinancials.report_date <= end)
            stmt = stmt.order_by(StockFinancials.report_date.asc()).limit(limit)
            return list(s.exec(stmt).all())

    def bulk_upsert(self, rows: list[dict]) -> int:
        """
        批量插入/更新（一次 SQL，ON CONFLICT 覆盖）。

        Args:
            rows: 每条 dict 需含 symbol, report_date，其余可选：
                  roe_weighted, roe_diluted, gross_margin, net_margin, debt_ratio

        Returns:
            写入行数
        """
        if not rows:
            return 0
        values = []
        for r in rows:
            rd = r.get("report_date")
            if hasattr(rd, "date"):
                rd = rd.date()
            values.append((
                r["symbol"], rd,
                r.get("roe_weighted"), r.get("roe_diluted"),
                r.get("gross_margin"), r.get("net_margin"), r.get("debt_ratio"),
            ))
        sql = """
            INSERT INTO stock_financials
                (symbol, report_date, roe_weighted, roe_diluted,
                 gross_margin, net_margin, debt_ratio)
            VALUES %s
            ON CONFLICT (report_date, symbol) DO UPDATE SET
                roe_weighted = EXCLUDED.roe_weighted,
                roe_diluted = EXCLUDED.roe_diluted,
                gross_margin = EXCLUDED.gross_margin,
                net_margin = EXCLUDED.net_margin,
                debt_ratio = EXCLUDED.debt_ratio
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)


# ======== 工厂函数（遵循 index_ohlcv 单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_stock_financials_repository(
    db_connection: DBConnection | None = None,
) -> StockFinancialsRepository:
    """创建财务指标仓储实例。"""
    return StockFinancialsRepository(db_connection or _get_db_connection())
