"""自定义看板 repository 实现。

遵循项目 Repository Pattern: 工厂 + session_scope(参考 watchlist.repository)。
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

from .models import AnalysisBoard


class AnalysisBoardRepository:
    """看板数据访问层。layout 由调用方(handler)保证为 dict 或 None。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def list_boards(self) -> list[AnalysisBoard]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(AnalysisBoard).order_by(
                        AnalysisBoard.sort_index, AnalysisBoard.id
                    )
                ).all()
            )

    def get_board(self, board_id: int) -> Optional[AnalysisBoard]:
        with self._db.session_scope() as s:
            return s.get(AnalysisBoard, board_id)

    def create_board(self, name: str, layout: dict) -> AnalysisBoard:
        with self._db.session_scope() as s:
            row = s.execute(
                text(
                    "SELECT COALESCE(MAX(sort_index), -1) "
                    "FROM analysis_board"
                )
            ).first()
            sort_index = (row[0] if row else -1) + 1
            now = datetime.now()
            b = AnalysisBoard(
                name=name,
                layout=layout,
                sort_index=sort_index,
                created_at=now,
                updated_at=now,
            )
            s.add(b)
            s.commit()
            s.refresh(b)
            return b

    def update_board(
        self,
        board_id: int,
        name: Optional[str] = None,
        layout: Optional[dict] = None,
    ) -> Optional[AnalysisBoard]:
        with self._db.session_scope() as s:
            b = s.get(AnalysisBoard, board_id)
            if not b:
                return None
            if name is not None:
                b.name = name
            if layout is not None:
                b.layout = layout
            b.updated_at = datetime.now()
            s.add(b)
            s.commit()
            s.refresh(b)
            return b

    def delete_board(self, board_id: int) -> bool:
        with self._db.session_scope() as s:
            b = s.get(AnalysisBoard, board_id)
            if not b:
                return False
            s.delete(b)
            s.commit()
            return True


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


def create_analysis_board_repository(
    db_connection: DBConnection | None = None,
) -> AnalysisBoardRepository:
    """创建看板仓储实例。"""
    return AnalysisBoardRepository(db_connection or _get_db_connection())
