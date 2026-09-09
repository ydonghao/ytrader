"""fundamental_report 表：个股基本面深度分析历史报告。

每次 fundamental_analysis（LLM 基本面分析）成功后存一份，
供历史对比 / 评分趋势 / 回看过往分析。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class FundamentalReport(SQLModel, table=True):
    """一次基本面分析的结构化报告记录。"""

    __tablename__ = "fundamental_report"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    overall_score: Optional[int] = None
    data_available: Optional[bool] = None
    one_line_conclusion: Optional[str] = None
    report: Any = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now)


class FundamentalReportRepository:
    """基本面报告历史数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def insert(self, symbol: str, report: dict) -> None:
        """存一份分析报告（overall_score/结论 从 report 顶层取）。"""
        with self._db.session_scope() as s:
            s.add(
                FundamentalReport(
                    symbol=symbol,
                    overall_score=report.get("overall_score"),
                    data_available=report.get("data_available"),
                    one_line_conclusion=report.get("one_line_conclusion"),
                    report=report,
                )
            )

    def list_history(
        self, symbol: str, limit: int = 20
    ) -> list[FundamentalReport]:
        """返回某股票的历史报告（按时间倒序，不含完整 report JSON）。"""
        with self._db.session_scope() as s:
            rows = list(
                s.exec(
                    select(FundamentalReport)
                    .where(FundamentalReport.symbol == symbol)
                    .order_by(FundamentalReport.created_at.desc())
                    .limit(limit)
                ).all()
            )
            for r in rows:
                s.expunge(r)
            return rows

    def get_by_id(self, report_id: int) -> Optional[FundamentalReport]:
        """取单份完整报告（含 report JSON）。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(FundamentalReport).where(
                    FundamentalReport.id == report_id
                )
            ).first()
            if row is not None:
                s.expunge(row)
            return row


# ======== 工厂函数（遵循 stock_valuation 单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_fundamental_report_repository(
    db_connection: DBConnection | None = None,
) -> FundamentalReportRepository:
    """创建基本面报告仓储实例。"""
    return FundamentalReportRepository(db_connection or _get_db_connection())
