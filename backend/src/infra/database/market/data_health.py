"""data_health_result 表：体检结果（每日全量替换 + 历史保留 180 天）。"""
import threading
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class DataHealthResult(SQLModel, table=True):
    """单次检查结果（check_id+checked_at 唯一，每日 replace）。"""

    __tablename__ = "data_health_result"

    id: Optional[int] = Field(default=None, primary_key=True)
    check_id: str = Field(index=True)
    checked_at: datetime = Field(default_factory=datetime.now,
                                 index=True)
    table_name: str = ""
    severity: str = "warn"
    status: str = "ok"
    metric: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    message: str = ""


class DataHealthRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def replace_today(self, results: list) -> int:
        """写入今日结果，并清掉同 check_id 今日旧行（幂等重跑）。"""
        day_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with self._db.session_scope() as s:
            olds = s.exec(select(DataHealthResult).where(
                DataHealthResult.checked_at >= day_start)).all()
            for o in olds:
                s.delete(o)
            for r in results:
                s.add(DataHealthResult(
                    check_id=r.check_id,
                    table_name=r.table, severity=r.severity,
                    status=r.status, metric=r.metric,
                    message=r.message,
                ))
            return len(results)

    def latest_status_map(self) -> dict:
        """{check_id: 上次(今日之前最近一次) status}——边沿去重依据。"""
        day_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with self._db.session_scope() as s:
            rows = s.exec(
                select(DataHealthResult)
                .where(DataHealthResult.checked_at < day_start)
                .order_by(DataHealthResult.checked_at.desc())
                .limit(2000)
            ).all()
        seen: dict = {}
        for r in rows:
            if r.check_id not in seen:
                seen[r.check_id] = r.status
        return seen

    def today(self) -> list:
        day_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with self._db.session_scope() as s:
            rows = s.exec(
                select(DataHealthResult)
                .where(DataHealthResult.checked_at >= day_start)
                .order_by(DataHealthResult.check_id)
            ).all()
            return [
                {
                    "check_id": r.check_id, "table": r.table_name,
                    "severity": r.severity, "status": r.status,
                    "metric": r.metric, "message": r.message,
                    "checked_at": r.checked_at.isoformat(),
                }
                for r in rows
            ]

    def history(self, check_id: str, days: int = 60) -> list:
        cutoff = datetime.now() - timedelta(days=days)
        with self._db.session_scope() as s:
            rows = s.exec(
                select(DataHealthResult)
                .where(DataHealthResult.check_id == check_id,
                       DataHealthResult.checked_at >= cutoff)
                .order_by(DataHealthResult.checked_at.desc())
                .limit(500)
            ).all()
            return [
                {
                    "checked_at": r.checked_at.isoformat(),
                    "status": r.status, "metric": r.metric,
                    "message": r.message,
                }
                for r in rows
            ]

    def prune(self, days: int = 180) -> int:
        cutoff = datetime.now() - timedelta(days=days)
        with self._db.session_scope() as s:
            rows = s.exec(select(DataHealthResult).where(
                DataHealthResult.checked_at < cutoff)).all()
            for r in rows:
                s.delete(r)
            return len(rows)


_db: DBConnection | None = None
_lock = threading.Lock()


def create_data_health_repository(
    db_connection: DBConnection | None = None,
) -> DataHealthRepository:
    global _db
    if db_connection is None:
        if _db is None:
            with _lock:
                if _db is None:
                    _db = create_db_connection(get_dsn())
        db_connection = _db
    return DataHealthRepository(db_connection)
