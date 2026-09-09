"""
Subscription repository implementation.
"""
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select

from src.domain.market.intel.subscription import ISubscriptionRepository
from src.infra.database.subscription.entity import Subscription
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn


# ── Singleton DB connection ────────────────────────────────────

_db_connection: Optional[DBConnection] = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


# ── Repository ─────────────────────────────────────────────────

class SubscriptionRepository(ISubscriptionRepository):
    """SQLModel-backed subscription repository."""

    def __init__(self, db_connection: DBConnection):
        self._db = db_connection

    def add_subscription(self, sub: Subscription) -> Subscription:
        with self._db.session_scope() as session:
            session.add(sub)
            session.flush()
            session.expunge(sub)
            return sub

    def remove_subscription(self, id: int) -> bool:
        with self._db.session_scope() as session:
            sub = session.get(Subscription, id)
            if sub is None:
                return False
            session.delete(sub)
            return True

    def list_subscriptions(
        self, source_type: str | None = None,
    ) -> list[Subscription]:
        with self._db.session_scope() as session:
            if source_type:
                stmt = select(Subscription).where(
                    Subscription.source_type == source_type
                ).order_by(Subscription.created_at.desc())
            else:
                stmt = select(Subscription).order_by(
                    Subscription.created_at.desc()
                )
            rows = session.exec(stmt).all()
            session.expunge_all()
            return list(rows)

    def get_active_subscriptions(self) -> list[Subscription]:
        with self._db.session_scope() as session:
            stmt = select(Subscription).where(
                Subscription.is_active == True  # noqa: E712
            ).order_by(Subscription.created_at.desc())
            rows = session.exec(stmt).all()
            session.expunge_all()
            return list(rows)

    def get_by_id(self, id: int) -> Subscription | None:
        with self._db.session_scope() as session:
            sub = session.get(Subscription, id)
            if sub is not None:
                session.expunge(sub)
            return sub

    def update_subscription_status(
        self, id: int, is_active: bool,
    ) -> Subscription | None:
        with self._db.session_scope() as session:
            sub = session.get(Subscription, id)
            if sub is None:
                return None
            sub.is_active = is_active
            session.flush()
            session.expunge(sub)
            return sub

    def update_fetch_result(
        self, id: int, error: str | None = None,
    ) -> Subscription | None:
        with self._db.session_scope() as session:
            sub = session.get(Subscription, id)
            if sub is None:
                return None
            sub.last_fetched_at = datetime.now(timezone.utc)
            sub.last_error = error
            session.flush()
            session.expunge(sub)
            return sub


# ── Factory ────────────────────────────────────────────────────

def create_subscription_repository(
    db_connection: DBConnection | None = None,
) -> SubscriptionRepository:
    conn = db_connection or _get_db_connection()
    return SubscriptionRepository(conn)
