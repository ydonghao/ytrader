"""stock_valuation 表：A 股个股估值日线（PE/PB/PS/股息率/总市值）。

与 index_ohlcv 同为"个股附属独立建表"，记录每个交易日的估值快照，
供价值/红利类长期策略回测做点-in-time 估值查询。

数据来源：PE/PB/PS/总市值 来自 ak.stock_value_em（东财）；个股股息率
dv_ratio/dv_ttm 由 stock_dividend 分红明细（ak.stock_history_dividend_detail）
经 fundamental.dividend_yield 计算 TTM 后回写。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

# 字段名 `date` 会遮蔽 datetime.date，用模块别名 dt.date 引用类型注解。
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class StockValuation(SQLModel, table=True):
    """个股估值日线记录（PE / PB / 股息率 / 总市值）。"""

    __tablename__ = "stock_valuation"

    symbol: str = Field(primary_key=True)        # sh600000 / sz000001 ...
    trade_date: dt.date = Field(primary_key=True)
    pe: Optional[float] = None                   # 静态市盈率
    pe_ttm: Optional[float] = None               # 滚动市盈率
    pb: Optional[float] = None                   # 市净率
    ps: Optional[float] = None                   # 市销率
    ps_ttm: Optional[float] = None               # 滚动市销率
    dv_ratio: Optional[float] = None             # 股息率
    dv_ttm: Optional[float] = None               # 滚动股息率
    total_mv: Optional[float] = None             # 总市值（元）
    created_at: datetime = Field(default_factory=datetime.now)


class StockValuationRepository:
    """个股估值数据访问（守 SQLModel ORM 规范）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def upsert(
        self,
        symbol: str,
        trade_date: dt.date,
        pe: Optional[float] = None,
        pe_ttm: Optional[float] = None,
        pb: Optional[float] = None,
        ps: Optional[float] = None,
        ps_ttm: Optional[float] = None,
        dv_ratio: Optional[float] = None,
        dv_ttm: Optional[float] = None,
        total_mv: Optional[float] = None,
    ) -> None:
        """插入或更新（按 symbol+trade_date 主键）一条估值日线。"""
        with self._db.session_scope() as s:
            existing = s.exec(
                select(StockValuation).where(
                    StockValuation.symbol == symbol,
                    StockValuation.trade_date == trade_date,
                )
            ).first()
            if existing:
                existing.pe = pe
                existing.pe_ttm = pe_ttm
                existing.pb = pb
                existing.ps = ps
                existing.ps_ttm = ps_ttm
                existing.dv_ratio = dv_ratio
                existing.dv_ttm = dv_ttm
                existing.total_mv = total_mv
            else:
                s.add(
                    StockValuation(
                        symbol=symbol,
                        trade_date=trade_date,
                        pe=pe, pe_ttm=pe_ttm, pb=pb,
                        ps=ps, ps_ttm=ps_ttm,
                        dv_ratio=dv_ratio, dv_ttm=dv_ttm,
                        total_mv=total_mv,
                    )
                )

    def get_latest_date(self, symbol: str) -> Optional[dt.date]:
        """返回指定个股最新估值记录的日期；无数据为 None。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(StockValuation)
                .where(StockValuation.symbol == symbol)
                .order_by(StockValuation.trade_date.desc())
            ).first()
            return row.trade_date if row else None

    def get_as_of(
        self, symbol: str, as_of: dt.date
    ) -> Optional[StockValuation]:
        """返回 as_of 当天（或之前最近一个交易日）的估值记录（点-in-time 查询）。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(StockValuation)
                .where(
                    StockValuation.symbol == symbol,
                    StockValuation.trade_date <= as_of,
                )
                .order_by(StockValuation.trade_date.desc())
            ).first()
            if row is not None:
                # 在 session 内 expunge，使对象可安全在 session 外使用
                s.expunge(row)
            return row

    def get_range(
        self,
        symbol: str,
        start: dt.date,
        end: dt.date,
    ) -> list[StockValuation]:
        """返回 [start, end] 区间内的估值记录（按日期升序）。"""
        with self._db.session_scope() as s:
            rows = list(
                s.exec(
                    select(StockValuation)
                        .where(
                        StockValuation.symbol == symbol,
                        StockValuation.trade_date >= start,
                        StockValuation.trade_date <= end,
                    )
                    .order_by(StockValuation.trade_date.asc())
                ).all()
            )
            for r in rows:
                s.expunge(r)
            return rows

    def get_range_batch(
        self,
        symbols: list[str],
        start: dt.date,
        end: dt.date,
        exclude_ranges: list[tuple[dt.date, dt.date]] | None = None,
        monthly: bool = True,
    ) -> dict[str, list[StockValuation]]:
        """
        批量拉多符号历史估值，SQL 层按月降采样（每月留最后交易日）。

        用 psycopg2 直查 + DISTINCT ON（与 data_loader 同款），绕开 ORM。
        exclude_ranges 在 Python 层过滤（避免复杂 SQL 构造）。

        Returns:
            {symbol: [StockValuation, ...]}，每符号按日期升序。
            无数据的符号不出现在结果里。
        """
        if not symbols:
            return {}
        exclude_ranges = exclude_ranges or []

        if monthly:
            sql = """
                SELECT * FROM (
                    SELECT DISTINCT ON (symbol, date_trunc('month', trade_date))
                        symbol, trade_date, pe, pe_ttm, pb, ps, ps_ttm,
                        dv_ratio, dv_ttm, total_mv
                    FROM stock_valuation
                    WHERE symbol = ANY(%s) AND trade_date >= %s AND trade_date <= %s
                    ORDER BY symbol, date_trunc('month', trade_date), trade_date DESC
                ) t ORDER BY symbol, trade_date ASC
            """
        else:
            sql = """
                SELECT symbol, trade_date, pe, pe_ttm, pb, ps, ps_ttm,
                       dv_ratio, dv_ttm, total_mv
                FROM stock_valuation
                WHERE symbol = ANY(%s) AND trade_date >= %s AND trade_date <= %s
                ORDER BY symbol, trade_date ASC
            """

        out: dict[str, list[StockValuation]] = {}
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (list(symbols), start, end))
                for r in cur.fetchall():
                    d = r["trade_date"]
                    if hasattr(d, "date"):
                        d = d.date()
                    # 剔除区间过滤
                    if any(rs <= d <= re_ for rs, re_ in exclude_ranges):
                        continue
                    sym = r["symbol"]
                    out.setdefault(sym, []).append(StockValuation(
                        symbol=sym, trade_date=d,
                        pe=r.get("pe"), pe_ttm=r.get("pe_ttm"),
                        pb=r.get("pb"), ps=r.get("ps"), ps_ttm=r.get("ps_ttm"),
                        dv_ratio=r.get("dv_ratio"), dv_ttm=r.get("dv_ttm"),
                        total_mv=r.get("total_mv"),
                    ))
        finally:
            conn.close()
        return out

    def bulk_upsert(self, rows: list[dict]) -> int:
        """
        批量插入/更新（一次 SQL，ON CONFLICT 覆盖）。
        比逐行 upsert 快 50~100 倍。

        Args:
            rows: 每条 dict 需含 symbol, trade_date，其余字段可选：
                  pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm, total_mv

        Returns:
            写入行数
        """
        if not rows:
            return 0
        # 规整字段
        values = []
        for r in rows:
            td = r.get("trade_date")
            if hasattr(td, "date"):
                td = td.date()
            values.append((
                r["symbol"], td,
                r.get("pe"), r.get("pe_ttm"), r.get("pb"),
                r.get("ps"), r.get("ps_ttm"),
                r.get("dv_ratio"), r.get("dv_ttm"), r.get("total_mv"),
            ))
        sql = """
            INSERT INTO stock_valuation
                (symbol, trade_date, pe, pe_ttm, pb, ps, ps_ttm,
                 dv_ratio, dv_ttm, total_mv)
            VALUES %s
            ON CONFLICT (trade_date, symbol) DO UPDATE SET
                pe = EXCLUDED.pe, pe_ttm = EXCLUDED.pe_ttm, pb = EXCLUDED.pb,
                ps = EXCLUDED.ps, ps_ttm = EXCLUDED.ps_ttm,
                dv_ratio = EXCLUDED.dv_ratio, dv_ttm = EXCLUDED.dv_ttm,
                total_mv = EXCLUDED.total_mv
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def update_dividend_yield(
        self,
        symbol: str,
        trade_date: dt.date,
        dv_ratio: Optional[float] = None,
        dv_ttm: Optional[float] = None,
    ) -> int:
        """
        仅更新指定 (symbol, trade_date) 记录的股息率字段。

        用于分红明细同步后回写 TTM 股息率（不触碰 PE/PB 等其他字段）。
        返回受影响行数（0 表示该日期无记录）。
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE stock_valuation
                       SET dv_ratio = %s, dv_ttm = %s
                     WHERE symbol = %s AND trade_date = %s
                    """,
                    (dv_ratio, dv_ttm, symbol, trade_date),
                )
                n = cur.rowcount
            conn.commit()
        finally:
            conn.close()
        return n


# ======== 工厂函数（遵循 index_ohlcv 单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_stock_valuation_repository(
    db_connection: DBConnection | None = None,
) -> StockValuationRepository:
    """创建估值仓储实例。"""
    return StockValuationRepository(db_connection or _get_db_connection())
