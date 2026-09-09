"""
数据库公共模块
提供数据库连接、会话管理和工厂函数的公共实现
"""
import logging
import os
import time
from contextlib import contextmanager
from typing import TypeVar, Generic, Type, Optional, List, Any

from sqlalchemy import event
from sqlmodel import SQLModel, Field, Session, create_engine, select
from sqlmodel.pool import StaticPool

from src.infra.database.database_interface import (
    IDatabaseSession,
    IDatabaseConnection,
)

T = TypeVar('T')

logger = logging.getLogger("slowquery")

# 慢查询阈值（秒）。超过则记录 warning 日志。可通过环境变量 SLOW_QUERY_THRESHOLD_SECONDS 覆盖。
SLOW_QUERY_THRESHOLD_SECONDS = float(os.getenv("SLOW_QUERY_THRESHOLD_SECONDS", "0.3"))


def _install_slow_query_hook(engine) -> None:
    """
    为 SQLAlchemy engine 安装慢查询监测：记录执行耗时超过阈值的语句。

    这让 "慢 SQL" 可观测——任何执行超过 SLOW_QUERY_THRESHOLD_SECONDS 的语句都会被记录
    （语句文本 + 耗时 + 参数数量），便于在生产排查热点查询。
    """
    threshold = SLOW_QUERY_THRESHOLD_SECONDS

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        context._query_start_time = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        start = getattr(context, "_query_start_time", None)
        if start is None:
            return
        elapsed = time.perf_counter() - start
        if elapsed >= threshold:
            stmt_preview = " ".join(statement.split())[:300]
            logger.warning(
                "慢SQL %.0fms | %s | params=%d",
                elapsed * 1000,
                stmt_preview,
                len(parameters) if parameters is not None else 0,
            )


class DBSession(IDatabaseSession):
    """数据库会话实现"""

    def __init__(self, session: Session):
        self._session = session

    def add(self, entity: Any) -> None:
        self._session.add(entity)

    def delete(self, entity: Any) -> None:
        self._session.delete(entity)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def refresh(self, entity: Any) -> None:
        self._session.refresh(entity)

    def flush(self) -> None:
        self._session.flush()

    def query(self, model: Type[T]) -> Any:
        return self._session.exec(select(model))

    def exec(self, statement: Any) -> Any:
        """执行 SQL 语句"""
        return self._session.exec(statement)

    def close(self) -> None:
        self._session.close()

    def __getattr__(self, name: str):
        """代理其他方法调用到内部 session"""
        return getattr(self._session, name)


class DBConnection(IDatabaseConnection):
    """数据库连接实现"""

    def __init__(
        self,
        database_url: str,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        auto_create_tables: bool = True,
    ):
        """
        初始化数据库连接

        Args:
            database_url: 数据库连接字符串
            echo: 是否打印SQL语句
            pool_size: 连接池大小
            max_overflow: 最大溢出连接数
            auto_create_tables: 是否自动建表（仅启动时用 True，测试可传 False）
        """
        if database_url.startswith("sqlite"):
            self._engine = create_engine(
                database_url,
                echo=echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool
            )
        else:
            # 对 PG：设置 statement_timeout（10s，防止单条慢查询拖垮连接池）
            # 和 pool_recycle（防止数据库端踢掉空闲连接）。
            self._engine = create_engine(
                database_url,
                echo=echo,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_pre_ping=True,
                pool_recycle=1800,
                connect_args={
                    "options": "-c statement_timeout=10000",
                },
            )

        # 安装慢查询监测（对所有后端生效，包括 sqlite 测试）
        _install_slow_query_hook(self._engine)

        if auto_create_tables:
            SQLModel.metadata.create_all(self._engine)

    def get_session(self) -> IDatabaseSession:
        # expire_on_commit=False: commit 后对象属性保持可读, 避免
        # repository 返回对象在 session 关闭后被访问时报
        # DetachedInstanceError。现有 repository(在 session 内访问属性)
        # 不受影响; 新 repository(返回对象给调用方)受益。
        return DBSession(
            Session(self._engine, expire_on_commit=False)
        )

    @contextmanager
    def session_scope(self):
        """会话上下文管理器"""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        self._engine.dispose()

    def health_check(self) -> bool:
        try:
            with self._engine.connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False


def create_db_connection(
    database_url: str,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    auto_create_tables: bool = True,
) -> DBConnection:
    """创建数据库连接。"""
    return DBConnection(
        database_url, echo, pool_size, max_overflow,
        auto_create_tables=auto_create_tables,
    )
