"""job_run_log 表：APScheduler 事件监听留痕（数据治理阶段二）。"""
import threading
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Field, SQLModel, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class JobRunLog(SQLModel, table=True):
    """定时 job 执行记录（监听器写入，保留 180 天）。"""

    __tablename__ = "job_run_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    scheduled_at: Optional[datetime] = None
    finished_at: datetime = Field(default_factory=datetime.now)
    status: str = Field(default="success")   # success|error
    error_summary: Optional[str] = None


class JobRunLogRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def add(self, job_id: str, status: str,
            error_summary: Optional[str] = None,
            scheduled_at: Optional[datetime] = None) -> int:
        with self._db.session_scope() as s:
            row = JobRunLog(
                job_id=job_id, status=status,
                error_summary=(error_summary or "")[:500] or None,
                scheduled_at=scheduled_at,
            )
            s.add(row)
            s.flush()
            return row.id

    def summary(self, days: int = 30) -> list:
        cutoff = datetime.now() - timedelta(days=days)
        with self._db.session_scope() as s:
            rows = s.exec(
                select(JobRunLog)
                .where(JobRunLog.finished_at >= cutoff)
                .order_by(JobRunLog.finished_at.desc())
                .limit(5000)
            ).all()
        by: dict = {}
        for r in rows:
            g = by.setdefault(r.job_id, {
                "job_id": r.job_id, "total": 0, "errors": 0,
                "last_run": r.finished_at.isoformat(),
                "last_status": r.status,
                "last_error": r.error_summary,
            })
            g["total"] += 1
            if r.status == "error":
                g["errors"] += 1
        out = list(by.values())
        for g in out:
            g["success_rate"] = round(
                (g["total"] - g["errors"]) / g["total"] * 100, 1
            ) if g["total"] else None
        return out

    def prune(self, days: int = 180) -> int:
        cutoff = datetime.now() - timedelta(days=days)
        with self._db.session_scope() as s:
            rows = s.exec(select(JobRunLog).where(
                JobRunLog.finished_at < cutoff)).all()
            for r in rows:
                s.delete(r)
            return len(rows)


_db: DBConnection | None = None
_lock = threading.Lock()


def create_job_run_log_repository(
    db_connection: DBConnection | None = None,
) -> JobRunLogRepository:
    global _db
    if db_connection is None:
        if _db is None:
            with _lock:
                if _db is None:
                    _db = create_db_connection(get_dsn())
        db_connection = _db
    return JobRunLogRepository(db_connection)
