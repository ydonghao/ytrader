"""自选股 repository 实现。

职责:
- 分组 CRUD + 排序 (WatchlistGroup)
- 组内成员 CRUD + 备注 + 排序 + 跨组移动 (WatchlistItem)

遵循项目 Repository Pattern: 工厂 + session_scope(参考 portfolio.repository)。
"""
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlmodel import select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

from .models import WatchlistGroup, WatchlistItem


class DuplicateWatchlistItem(Exception):
    """同组内已存在该 symbol。"""


class WatchlistRepository:
    """自选股数据访问层。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 分组 ─────────────────────────────────────────────────────

    def list_groups(self) -> list[WatchlistGroup]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(WatchlistGroup).order_by(
                        WatchlistGroup.sort_index, WatchlistGroup.id
                    )
                ).all()
            )

    def get_group(self, group_id: int) -> Optional[WatchlistGroup]:
        with self._db.session_scope() as s:
            return s.get(WatchlistGroup, group_id)

    def create_group(
        self, name: str, sort_index: Optional[int] = None
    ) -> WatchlistGroup:
        with self._db.session_scope() as s:
            if sort_index is None:
                row = s.execute(
                    text(
                        "SELECT COALESCE(MAX(sort_index), -1) "
                        "FROM watchlist_group"
                    )
                ).first()
                sort_index = (row[0] if row else -1) + 1
            now = datetime.now()
            g = WatchlistGroup(
                name=name, sort_index=sort_index, created_at=now, updated_at=now
            )
            s.add(g)
            s.commit()
            s.refresh(g)
            return g

    def rename_group(
        self, group_id: int, name: str
    ) -> Optional[WatchlistGroup]:
        with self._db.session_scope() as s:
            g = s.get(WatchlistGroup, group_id)
            if not g:
                return None
            g.name = name
            g.updated_at = datetime.now()
            s.add(g)
            s.commit()
            s.refresh(g)
            return g

    def delete_group(self, group_id: int) -> bool:
        """删除分组及其成员(显式级联, 兼容 sqlite/PG)。"""
        with self._db.session_scope() as s:
            s.execute(
                text("DELETE FROM watchlist_item WHERE group_id = :gid"),
                {"gid": group_id},
            )
            g = s.get(WatchlistGroup, group_id)
            if g:
                s.delete(g)
            s.commit()
            return True

    def reorder_groups(self, ordered_ids: list[int]) -> None:
        with self._db.session_scope() as s:
            for pos, gid in enumerate(ordered_ids):
                g = s.get(WatchlistGroup, gid)
                if g:
                    g.sort_index = pos
                    g.updated_at = datetime.now()
                    s.add(g)
            s.commit()

    def count_items_by_group(self) -> dict[int, int]:
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT group_id, COUNT(*) FROM watchlist_item "
                    "GROUP BY group_id"
                )
            ).all()
            return {r[0]: r[1] for r in rows}

    # ── 成员 ─────────────────────────────────────────────────────

    def list_items(self, group_id: int) -> list[WatchlistItem]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(WatchlistItem)
                    .where(WatchlistItem.group_id == group_id)
                    .order_by(WatchlistItem.sort_index, WatchlistItem.id)
                ).all()
            )

    def add_item(
        self,
        group_id: int,
        symbol: str,
        note: Optional[str] = None,
        sort_index: Optional[int] = None,
    ) -> WatchlistItem:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(WatchlistItem).where(
                    WatchlistItem.group_id == group_id,
                    WatchlistItem.symbol == symbol,
                )
            ).first()
            if existing:
                raise DuplicateWatchlistItem(symbol)
            if sort_index is None:
                row = s.execute(
                    text(
                        "SELECT COALESCE(MAX(sort_index), -1) "
                        "FROM watchlist_item WHERE group_id = :gid"
                    ),
                    {"gid": group_id},
                ).first()
                sort_index = (row[0] if row else -1) + 1
            now = datetime.now()
            it = WatchlistItem(
                group_id=group_id,
                symbol=symbol,
                note=note,
                sort_index=sort_index,
                created_at=now,
                updated_at=now,
            )
            s.add(it)
            s.commit()
            s.refresh(it)
            return it

    def get_item(self, item_id: int) -> Optional[WatchlistItem]:
        with self._db.session_scope() as s:
            return s.get(WatchlistItem, item_id)

    def update_item_note(
        self, item_id: int, note: Optional[str]
    ) -> Optional[WatchlistItem]:
        with self._db.session_scope() as s:
            it = s.get(WatchlistItem, item_id)
            if not it:
                return None
            it.note = note
            it.updated_at = datetime.now()
            s.add(it)
            s.commit()
            s.refresh(it)
            return it

    def delete_item(self, item_id: int) -> bool:
        with self._db.session_scope() as s:
            it = s.get(WatchlistItem, item_id)
            if it:
                s.delete(it)
                s.commit()
                return True
            return False

    def move_item(
        self,
        item_id: int,
        to_group_id: int,
        sort_index: Optional[int] = None,
    ) -> Optional[WatchlistItem]:
        with self._db.session_scope() as s:
            it = s.get(WatchlistItem, item_id)
            if not it:
                return None
            dup = s.exec(
                select(WatchlistItem).where(
                    WatchlistItem.group_id == to_group_id,
                    WatchlistItem.symbol == it.symbol,
                    WatchlistItem.id != item_id,
                )
            ).first()
            if dup:
                raise DuplicateWatchlistItem(it.symbol)
            it.group_id = to_group_id
            if sort_index is None:
                row = s.execute(
                    text(
                        "SELECT COALESCE(MAX(sort_index), -1) "
                        "FROM watchlist_item WHERE group_id = :gid"
                    ),
                    {"gid": to_group_id},
                ).first()
                sort_index = (row[0] if row else -1) + 1
            it.sort_index = sort_index
            it.updated_at = datetime.now()
            s.add(it)
            s.commit()
            s.refresh(it)
            return it

    def reorder_items(self, group_id: int, ordered_ids: list[int]) -> None:
        with self._db.session_scope() as s:
            for pos, iid in enumerate(ordered_ids):
                it = s.get(WatchlistItem, iid)
                # 只重排本组成员, 混入的其它分组 id 一律忽略
                if it and it.group_id == group_id:
                    it.sort_index = pos
                    it.updated_at = datetime.now()
                    s.add(it)
            s.commit()


# ======== 工厂函数(遵循项目约定: 单例 + 工厂) ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_watchlist_repository(
    db_connection: DBConnection | None = None,
) -> WatchlistRepository:
    """创建自选股仓储实例。"""
    return WatchlistRepository(db_connection or _get_db_connection())
