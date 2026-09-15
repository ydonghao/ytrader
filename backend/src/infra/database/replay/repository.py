"""replay 会话/成交的 SQLModel 仓储（惯例同 watchlist.repository）。"""

from __future__ import annotations  # 类内方法名 list 会遮蔽内建，延迟求值注解

import threading
from datetime import date, datetime
from typing import Optional

from sqlmodel import select

from src.infra.database.replay.models import ReplaySession, ReplayTrade
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_replay_repository(
    db_connection: DBConnection | None = None,
) -> "ReplayRepository":
    return ReplayRepository(db_connection or _get_db_connection())


class ReplayRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def create(self, s: ReplaySession) -> ReplaySession:
        with self._db.session_scope() as sess:
            sess.add(s)
            sess.flush()
            sess.refresh(s)
            return s

    def list(self) -> list[ReplaySession]:
        with self._db.session_scope() as sess:
            return list(
                sess.exec(
                    select(ReplaySession).order_by(ReplaySession.id.desc())
                ).all()
            )

    def get(self, session_id: int) -> Optional[ReplaySession]:
        with self._db.session_scope() as sess:
            return sess.get(ReplaySession, session_id)

    def save_state(
        self,
        session_id: int,
        current_date: date,
        cash: float,
        state: dict,
    ) -> bool:
        with self._db.session_scope() as sess:
            row = sess.get(ReplaySession, session_id)
            if row is None:
                return False
            row.current_date = current_date
            row.cash = cash
            row.state = state  # 整体赋值（JSONB 原地 mutate 不会被跟踪）
            row.updated_at = datetime.now()
            sess.add(row)
            return True

    def bump_current_date(self, session_id: int, new_date: date) -> bool:
        """advance 推进服务端日历游标（不碰 cash/state，防防抖存档窗口期重复推进）。"""
        with self._db.session_scope() as sess:
            row = sess.get(ReplaySession, session_id)
            if row is None:
                return False
            row.current_date = new_date
            row.updated_at = datetime.now()
            sess.add(row)
            return True

    def set_status(self, session_id: int, status: str) -> bool:
        with self._db.session_scope() as sess:
            row = sess.get(ReplaySession, session_id)
            if row is None:
                return False
            row.status = status
            row.updated_at = datetime.now()
            sess.add(row)
            return True

    def delete(self, session_id: int) -> None:
        with self._db.session_scope() as sess:
            trades = sess.exec(
                select(ReplayTrade).where(ReplayTrade.session_id == session_id)
            ).all()
            for t in trades:
                sess.delete(t)
            row = sess.get(ReplaySession, session_id)
            if row is not None:
                sess.delete(row)

    def add_trade(self, t: ReplayTrade) -> ReplayTrade:
        with self._db.session_scope() as sess:
            sess.add(t)
            sess.flush()
            sess.refresh(t)
            return t

    def list_trades(self, session_id: int) -> list[ReplayTrade]:
        with self._db.session_scope() as sess:
            return list(
                sess.exec(
                    select(ReplayTrade)
                    .where(ReplayTrade.session_id == session_id)
                    .order_by(ReplayTrade.trade_date, ReplayTrade.id)
                ).all()
            )
