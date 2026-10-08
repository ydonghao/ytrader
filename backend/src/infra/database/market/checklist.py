"""stock_checklist_item 表：买入体检手动项（每 symbol 每项一行）。

课程21集方法论：定性项研究清楚了再填，糊弄的数据不如不填；
投资后定期复检（加仓减仓前重新过表）→ updated_at 驱动复检提醒。
"""
import threading
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlmodel import SQLModel, Field, UniqueConstraint

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class StockChecklistItem(SQLModel, table=True):
    """买入体检手动项存储（symbol + item_key 唯一）。"""

    __tablename__ = "stock_checklist_item"
    __table_args__ = (UniqueConstraint("symbol", "item_key",
                                       name="uq_checklist_symbol_item"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)                 # 小写带前缀 sh600519
    item_key: str = Field(index=True)               # 如 pricing_power
    value_text: Optional[str] = None                # 多行文本
    value_choice: Optional[str] = None              # 单选值（中文）
    updated_at: datetime = Field(default_factory=datetime.now)


class StockChecklistItemRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def upsert_items(self, symbol: str, items: list[dict]) -> int:
        """批量插入/更新；value 均为 None 的行 = 清除内容（保留行）。"""
        if not items:
            return 0
        values = [
            (symbol, it["item_key"], it.get("value_text"),
             it.get("value_choice"), datetime.now())
            for it in items
        ]
        sql = """
            INSERT INTO stock_checklist_item
                (symbol, item_key, value_text, value_choice, updated_at)
            VALUES %s
            ON CONFLICT (symbol, item_key) DO UPDATE SET
                value_text = EXCLUDED.value_text,
                value_choice = EXCLUDED.value_choice,
                updated_at = EXCLUDED.updated_at
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def get_all(self, symbol: str) -> dict:
        """{item_key: {value_text, value_choice, updated_at(iso str)}}。"""
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT item_key, value_text, value_choice, updated_at
                       FROM stock_checklist_item WHERE symbol = %s""",
                    (symbol,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        out = {}
        for key, vt, vc, ua in rows:
            out[key] = {
                "value_text": vt,
                "value_choice": vc,
                "updated_at": ua.isoformat() if ua else None,
            }
        return out


_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_checklist_repository(
    db_connection: DBConnection | None = None,
) -> StockChecklistItemRepository:
    return StockChecklistItemRepository(db_connection or _get_db_connection())
