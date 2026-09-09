"""数据源表现追踪仓储。

提供 record_source_run（按 source_key upsert 累加统计）、列表 / 单条
查询 / 重置。record_source_run 永不抛异常，避免影响抓取主流程。

复刻 IntelRepository 的 DBConnection 单例模式（ytrader 无模块级
session_scope，session 由 DBConnection.session_scope() 上下文管理）。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import delete, func
from sqlmodel import select

from src.infra.database.source_performance.entity import (
    SourcePerformanceEntity,
)
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)

_VALID_STATUS = {"success", "failure", "empty"}


# ======== 数据库连接单例（与 intel repository 同构） ========

_db_connection: Optional[DBConnection] = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_source_performance_repository(
    db_connection: DBConnection | None = None,
) -> DBConnection:
    """获取数据库连接（source_performance 表在首次建引擎时自动建表）。"""
    return db_connection or _get_db_connection()


# ======== 序列化 ========


def _to_dict(row: SourcePerformanceEntity) -> dict:
    runs = row.runs or 0
    success_rate = (
        round((row.successes / runs) * 100, 2) if runs > 0 else 0.0
    )
    return {
        "source_key": row.source_key,
        "provider": row.provider,
        "category": row.category,
        "group_name": row.group_name,
        "runs": row.runs,
        "successes": row.successes,
        "failures": row.failures,
        "empty_runs": row.empty,
        "total_articles": row.total_articles,
        "last_status": row.last_status,
        "last_provider": row.last_provider,
        "last_error": row.last_error,
        "last_run_id": row.last_run_id,
        "success_rate": success_rate,
        "updated_at": row.updated_at.isoformat()
        if row.updated_at
        else None,
    }


# ======== 读写操作 ========


def record_source_run(
    *,
    source_key: str,
    status: str,
    provider: str = "",
    category: str = "",
    group_name: str = "",
    articles_count: int = 0,
    error: str = "",
    run_id: str = "",
) -> None:
    """记录一次数据源运行结果（按 source_key upsert，累加统计）。

    status ∈ {"success", "failure", "empty"}。
    永不抛异常（吞掉错误仅记日志），确保不影响抓取流程。
    """
    if status not in _VALID_STATUS:
        logger.warning(
            f"record_source_run 收到非法 status={status!r}，已忽略",
        )
        return

    try:
        # session_scope() yield 的是 DBSession，它代理了底层 SQLModel
        # Session 的 get/exec/add/commit 等，可直接当 Session 用。
        with _get_db_connection().session_scope() as session:
            row = session.get(SourcePerformanceEntity, source_key)
            now = datetime.now(timezone.utc)
            if row is None:
                row = SourcePerformanceEntity(
                    source_key=source_key,
                    provider=provider,
                    category=category,
                    group_name=group_name,
                    runs=1,
                    successes=1 if status == "success" else 0,
                    failures=1 if status == "failure" else 0,
                    empty=1 if status == "empty" else 0,
                    total_articles=articles_count,
                    last_status=status,
                    last_provider=provider,
                    last_error=error,
                    last_run_id=run_id,
                    updated_at=now,
                )
            else:
                row.runs += 1
                if status == "success":
                    row.successes += 1
                elif status == "failure":
                    row.failures += 1
                else:
                    row.empty += 1
                row.total_articles += articles_count
                # 仅在提供新值时覆盖 provider/category/group_name。
                if provider:
                    row.provider = provider
                if category:
                    row.category = category
                if group_name:
                    row.group_name = group_name
                row.last_status = status
                row.last_provider = provider or row.last_provider
                row.last_error = error
                row.last_run_id = run_id or row.last_run_id
                row.updated_at = now
            session.add(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"record_source_run 记录失败 source_key={source_key!r}: {exc}",
        )


def list_source_performance(
    *, provider: str | None = None
) -> list[dict]:
    """列出全部数据源表现，可按 provider 过滤。按 updated_at 倒序。"""
    with _get_db_connection().session_scope() as session:
        stmt = select(SourcePerformanceEntity).order_by(
            SourcePerformanceEntity.updated_at.desc()
        )
        if provider:
            stmt = stmt.where(
                SourcePerformanceEntity.provider == provider
            )
        rows = session.exec(stmt).all()
        return [_to_dict(r) for r in rows]


def get_source_performance(source_key: str) -> dict | None:
    """获取单数据源表现详情。"""
    with _get_db_connection().session_scope() as session:
        row = session.get(SourcePerformanceEntity, source_key)
        return _to_dict(row) if row else None


def reset_source_performance(source_key: str | None = None) -> int:
    """重置计数器。

    source_key 为 None 时重置全部（删除所有行）；否则仅重置该源
    （删除该行）。返回受影响行数。
    """
    with _get_db_connection().session_scope() as session:
        if source_key is None:
            # SQLAlchemy 2.0 bulk delete 不返回可靠 rowcount，先计数再删。
            count_stmt = select(func.count()).select_from(
                SourcePerformanceEntity
            )
            total = session.exec(count_stmt).one()
            session.exec(delete(SourcePerformanceEntity))
            return total or 0
        existed = session.get(SourcePerformanceEntity, source_key)
        if existed is None:
            return 0
        session.delete(existed)
        return 1
