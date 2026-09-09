"""stock_dividend 表：A 股个股分红明细（每次分红事件一行）。

记录历次现金分红（派息）、送股、转增，按除权除息日，
供 TTM 股息率计算（fundamental.dividend_yield）与红利可持续性分析使用。

数据来源：akshare ak.stock_history_dividend_detail(symbol, indicator="分红")。

注意：表已落地的股息率 dv_ratio/dv_ttm 存在 stock_valuation 表（日线）；
本表是「明细」层，由 dividend_yield 纯函数聚合后回写 stock_valuation。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlmodel import SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class StockDividend(SQLModel, table=True):
    """个股分红明细记录（每次分红事件一行，按除权除息日）。"""

    __tablename__ = "stock_dividend"

    symbol: str = Field(primary_key=True)
    ex_date: dt.date = Field(primary_key=True)        # 除权除息日（生效日）
    announce_date: Optional[dt.date] = None           # 公告日期
    div_per_share: Optional[float] = None             # 每股派息（税前，元/股）
    stock_div: Optional[float] = None                 # 每股送股
    convert: Optional[float] = None                   # 每股转增
    progress: Optional[str] = None                    # 进度（实施/预案…）
    created_at: datetime = Field(default_factory=datetime.now)


class StockDividendRepository:
    """个股分红明细数据访问（守 SQLModel ORM 规范）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def upsert(
        self,
        symbol: str,
        ex_date: dt.date,
        announce_date: Optional[dt.date] = None,
        div_per_share: Optional[float] = None,
        stock_div: Optional[float] = None,
        convert: Optional[float] = None,
        progress: Optional[str] = None,
    ) -> None:
        """插入或更新（按 symbol+ex_date 主键）一条分红明细。"""
        with self._db.session_scope() as s:
            existing = s.exec(
                select(StockDividend).where(
                    StockDividend.symbol == symbol,
                    StockDividend.ex_date == ex_date,
                )
            ).first()
            if existing:
                existing.announce_date = announce_date
                existing.div_per_share = div_per_share
                existing.stock_div = stock_div
                existing.convert = convert
                existing.progress = progress
            else:
                s.add(
                    StockDividend(
                        symbol=symbol,
                        ex_date=ex_date,
                        announce_date=announce_date,
                        div_per_share=div_per_share,
                        stock_div=stock_div,
                        convert=convert,
                        progress=progress,
                    )
                )

    def bulk_upsert(self, rows: list[dict]) -> int:
        """
        批量插入/更新（一次 SQL，ON CONFLICT 覆盖）。

        Args:
            rows: 每条 dict 需含 symbol, ex_date，其余可选：
                  announce_date, div_per_share, stock_div, convert, progress

        Returns:
            写入行数
        """
        if not rows:
            return 0
        values = []
        for r in rows:
            ex = r.get("ex_date")
            if hasattr(ex, "date") and callable(ex.date):
                ex = ex.date()
            an = r.get("announce_date")
            if hasattr(an, "date") and callable(an.date):
                an = an.date()
            values.append((
                r["symbol"], ex,
                an, r.get("div_per_share"),
                r.get("stock_div"), r.get("convert"),
                r.get("progress"),
            ))
        sql = """
            INSERT INTO stock_dividend
                (symbol, ex_date, announce_date, div_per_share,
                 stock_div, convert, progress)
            VALUES %s
            ON CONFLICT (ex_date, symbol) DO UPDATE SET
                announce_date = EXCLUDED.announce_date,
                div_per_share = EXCLUDED.div_per_share,
                stock_div = EXCLUDED.stock_div,
                convert = EXCLUDED.convert,
                progress = EXCLUDED.progress
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def get_history(
        self,
        symbol: str,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
    ) -> list[StockDividend]:
        """返回分红明细（按除权除息日升序），可选区间过滤。"""
        with self._db.session_scope() as s:
            stmt = select(StockDividend).where(
                StockDividend.symbol == symbol
            )
            if start is not None:
                stmt = stmt.where(StockDividend.ex_date >= start)
            if end is not None:
                stmt = stmt.where(StockDividend.ex_date <= end)
            stmt = stmt.order_by(StockDividend.ex_date.asc())
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_latest_ex_date(self, symbol: str) -> Optional[dt.date]:
        """返回指定个股最新分红除权除息日；无数据为 None。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(StockDividend)
                .where(StockDividend.symbol == symbol)
                .order_by(StockDividend.ex_date.desc())
            ).first()
            return row.ex_date if row else None


# ======== 工厂函数（遵循 stock_valuation 单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_stock_dividend_repository(
    db_connection: DBConnection | None = None,
) -> StockDividendRepository:
    """创建分红明细仓储实例。"""
    return StockDividendRepository(db_connection or _get_db_connection())
