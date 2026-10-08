"""管理层承诺表 + 仓储（2026-10 言行追踪 V1）。

source=forecast 行由业绩预告导入幂等 upsert（唯一键 symbol+metric+
target_report_date）；manual 行人工录入、人工验证。
"""
import datetime as dt
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class ManagementPromise(SQLModel, table=True):
    """一条管理层承诺及其兑现状态。"""

    __tablename__ = "management_promise"
    __table_args__ = (
        # forecast 导入幂等；manual 行 metric 为 NULL 不参与冲突
        UniqueConstraint(
            "symbol", "source", "metric", "target_report_date",
            name="uq_promise_forecast",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)          # sh600519（前缀码）
    source: str = "manual"                   # forecast | manual
    category: str = "业绩指引"                # 业绩指引|资本开支|分红|回购|增持|其他
    content: str = ""                        # 承诺内容（forecast=指标+类型）
    promise_date: Optional[dt.date] = None   # 承诺/公告日
    target_report_date: Optional[dt.date] = Field(
        default=None, index=True)            # 目标报告期
    metric: Optional[str] = None             # 预告指标（forecast 行）
    forecast_value: Optional[float] = None
    actual_value: Optional[float] = None
    status: str = "pending"                  # pending|fulfilled|beat|broken
    deviation_pct: Optional[float] = None
    detail: Optional[str] = None
    evidence: Optional[str] = None           # 人工验证依据
    verified_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    # raw 预告原始行（forecast 行回看公告原因）
    raw: Optional[dict] = Field(default=None, sa_column=Column(JSON))


class ManagementPromiseRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def upsert_forecast(self, row: dict) -> str:
        """业绩预告承诺幂等落库；已存在则刷新实际值/状态。返回
        inserted|updated。"""
        with self._db.session_scope() as s:
            exists = s.exec(
                select(ManagementPromise).where(
                    ManagementPromise.symbol == row["symbol"],
                    ManagementPromise.source == "forecast",
                    ManagementPromise.metric == row["metric"],
                    ManagementPromise.target_report_date
                    == row["target_report_date"],
                )
            ).first()
            if exists:
                for k in ("content", "promise_date", "forecast_value",
                          "actual_value", "status", "deviation_pct",
                          "detail", "raw"):
                    if k in row:
                        setattr(exists, k, row[k])
                exists.updated_at = datetime.now()
                return "updated"
            s.add(ManagementPromise(**row, source="forecast"))
            return "inserted"

    def add_manual(self, data: dict) -> dict:
        with self._db.session_scope() as s:
            p = ManagementPromise(**data, source="manual")
            s.add(p)
            s.flush()
            return self._dict(p)

    def add_annual_report(self, data: dict) -> str:
        """年报 MD&A 抽取的承诺落库；同 symbol+source 内容重复跳过。

        返回 inserted|duplicated。状态恒 pending——"预计/力争"类承诺
        由人工验证闭环（V2 纪律：LLM 只抽取，不判兑现）。
        """
        with self._db.session_scope() as s:
            dup = s.exec(
                select(ManagementPromise).where(
                    ManagementPromise.symbol == data["symbol"],
                    ManagementPromise.source == "annual_report",
                    ManagementPromise.content == data["content"],
                )
            ).first()
            if dup:
                return "duplicated"
            s.add(ManagementPromise(
                **{**data, "source": "annual_report",
                   "status": "pending"}))
            return "inserted"

    def list(self, symbol: str) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ManagementPromise)
                .where(ManagementPromise.symbol == symbol)
                .order_by(ManagementPromise.target_report_date.desc(),
                          ManagementPromise.id.desc())
            ).all()
            return [self._dict(r) for r in rows]

    def get(self, row_id: int) -> Optional[dict]:
        with self._db.session_scope() as s:
            r = s.get(ManagementPromise, row_id)
            return self._dict(r) if r else None

    def verify(self, row_id: int, status: str,
               evidence: Optional[str]) -> Optional[dict]:
        """人工验证（manual 承诺的主闭环；forecast 行也可纠偏）。"""
        with self._db.session_scope() as s:
            r = s.get(ManagementPromise, row_id)
            if not r:
                return None
            r.status = status
            r.evidence = evidence
            r.verified_at = datetime.now()
            r.updated_at = datetime.now()
            s.add(r)
            return self._dict(r)

    def delete(self, row_id: int) -> bool:
        with self._db.session_scope() as s:
            r = s.get(ManagementPromise, row_id)
            if not r:
                return False
            s.delete(r)
            return True

    @staticmethod
    def _dict(r: ManagementPromise) -> dict:
        return {
            "id": r.id, "symbol": r.symbol, "source": r.source,
            "category": r.category, "content": r.content,
            "promise_date": r.promise_date.isoformat()
            if r.promise_date else None,
            "target_report_date": r.target_report_date.isoformat()
            if r.target_report_date else None,
            "metric": r.metric,
            "forecast_value": r.forecast_value,
            "actual_value": r.actual_value,
            "status": r.status, "deviation_pct": r.deviation_pct,
            "detail": r.detail, "evidence": r.evidence,
            "verified_at": r.verified_at.isoformat()
            if r.verified_at else None,
            "created_at": r.created_at.isoformat(),
        }


_db_connection: DBConnection | None = None


def create_management_promise_repository(
    db_connection: DBConnection | None = None,
) -> ManagementPromiseRepository:
    global _db_connection
    if db_connection is None:
        if _db_connection is None:
            _db_connection = create_db_connection(get_dsn())
        db_connection = _db_connection
    return ManagementPromiseRepository(db_connection)
