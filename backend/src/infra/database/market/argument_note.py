"""AI 陪练论证库表 + 仓储（2026-10 六层第⑥件）。

方向约定：LLM 只产 bull/bear **初稿**（基于库内真实数据的上下文），
用户核对修订后**归档**才是该公司的论证库成员——AI 产初稿与反方论证，
事实一律回原始材料核对。每 symbol+side 只保留一份 draft（重新生成
覆盖），archived 为历史沉淀。
"""
import datetime as dt
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class ArgumentNote(SQLModel, table=True):
    """一条论证（bull/bear），draft=AI初稿，archived=已验证归档。"""

    __tablename__ = "argument_note"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    side: str = "bull"                    # bull | bear
    status: str = "draft"                 # draft | archived
    content: str = ""
    evidence: Optional[str] = None        # 用户核实的关键事实/出处
    generated_by: Optional[str] = None    # 生成模型（manual=手写）
    context: Optional[dict] = Field(
        default=None, sa_column=Column(JSON))
    # 生成时的数据上下文摘要（供日后核对当时看到了什么）
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ArgumentNoteRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def save_draft(self, symbol: str, side: str, content: str,
                   generated_by: Optional[str] = None,
                   context: Optional[dict] = None) -> dict:
        """保存/覆盖 draft（symbol+side 单草稿，重新生成即覆盖）。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(ArgumentNote).where(
                    ArgumentNote.symbol == symbol,
                    ArgumentNote.side == side,
                    ArgumentNote.status == "draft",
                )
            ).first()
            if row is None:
                row = ArgumentNote(symbol=symbol, side=side)
                s.add(row)
            row.content = content
            row.generated_by = generated_by
            row.context = context
            row.updated_at = datetime.now()
            s.flush()
            return self._dict(row)

    def add_manual(self, data: dict) -> dict:
        with self._db.session_scope() as s:
            row = ArgumentNote(
                **{**data, "status": "archived", "generated_by": "manual"})
            s.add(row)
            s.flush()
            return self._dict(row)

    def list(self, symbol: str) -> list:
        """draft 优先在前、archived 按时间倒序。"""
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ArgumentNote)
                .where(ArgumentNote.symbol == symbol)
                .order_by(ArgumentNote.status.desc(),
                          ArgumentNote.updated_at.desc())
            ).all()
            return [self._dict(r) for r in rows]

    def get(self, row_id: int) -> Optional[dict]:
        with self._db.session_scope() as s:
            r = s.get(ArgumentNote, row_id)
            return self._dict(r) if r else None

    def update(self, row_id: int, content: Optional[str] = None,
               evidence: Optional[str] = None) -> Optional[dict]:
        with self._db.session_scope() as s:
            r = s.get(ArgumentNote, row_id)
            if not r:
                return None
            if content is not None:
                r.content = content
            if evidence is not None:
                r.evidence = evidence
            r.updated_at = datetime.now()
            s.add(r)
            return self._dict(r)

    def archive(self, row_id: int,
                evidence: Optional[str] = None) -> Optional[dict]:
        """验证归档——论证库的正身；可同时补核实依据。"""
        with self._db.session_scope() as s:
            r = s.get(ArgumentNote, row_id)
            if not r:
                return None
            r.status = "archived"
            if evidence:
                r.evidence = evidence
            r.updated_at = datetime.now()
            s.add(r)
            return self._dict(r)

    def delete(self, row_id: int) -> bool:
        with self._db.session_scope() as s:
            r = s.get(ArgumentNote, row_id)
            if not r:
                return False
            s.delete(r)
            return True

    @staticmethod
    def _dict(r: ArgumentNote) -> dict:
        return {
            "id": r.id, "symbol": r.symbol, "side": r.side,
            "status": r.status, "content": r.content,
            "evidence": r.evidence, "generated_by": r.generated_by,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }


_db_connection: DBConnection | None = None


def create_argument_note_repository(
    db_connection: DBConnection | None = None,
) -> ArgumentNoteRepository:
    global _db_connection
    if db_connection is None:
        if _db_connection is None:
            _db_connection = create_db_connection(get_dsn())
        db_connection = _db_connection
    return ArgumentNoteRepository(db_connection)
