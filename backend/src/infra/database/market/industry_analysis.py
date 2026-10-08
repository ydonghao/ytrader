# backend/src/infra/database/market/industry_analysis.py
"""行业分析三表:破净率序列/资金流历史/景气分快照(规格 2026-09-20 §3)。

写走 psycopg2 execute_values(sw_industry.py 同款),读走 SQLModel session。
"""
import datetime as dt
import threading
from datetime import datetime
from typing import Any, Optional

import psycopg2
from psycopg2.extras import execute_values, Json
from sqlalchemy import JSON, Column, DateTime, func
from sqlmodel import SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

PB_BREAK_COLUMNS = ("trade_date", "scope", "scope_code", "total_count",
                    "break_count", "break_rate", "median_pb")
FLOW_COLUMNS = ("trade_date", "em_industry_name", "main_net_inflow",
                "close_change_pct")
PROSPERITY_COLUMNS = ("trade_date", "sw_code", "score", "score_profit",
                      "score_valuation", "score_momentum", "score_flow",
                      "inputs")


class IndustryPbBreakTable(SQLModel, table=True):
    __tablename__ = "industry_pb_break_daily"
    trade_date: dt.date = Field(primary_key=True)
    scope: str = Field(primary_key=True)          # market / industry
    scope_code: str = Field(primary_key=True)     # market='ALL'; 行业=申万码
    total_count: int = 0
    break_count: int = 0
    break_rate: Optional[float] = None            # 0-1 小数
    median_pb: Optional[float] = None


class IndustryFundFlowTable(SQLModel, table=True):
    __tablename__ = "industry_fund_flow_daily"
    trade_date: dt.date = Field(primary_key=True)
    em_industry_name: str = Field(primary_key=True)   # 东财口径(~90个)
    main_net_inflow: Optional[float] = None           # 元
    close_change_pct: Optional[float] = None          # 行业当日涨跌幅%
    updated_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, server_default=func.now()),
    )


class IndustryProsperityTable(SQLModel, table=True):
    __tablename__ = "industry_prosperity_daily"
    trade_date: dt.date = Field(primary_key=True)
    sw_code: str = Field(primary_key=True)        # 纯6位
    score: Optional[float] = None                 # 0-100,全缺为 None
    score_profit: Optional[float] = None
    score_valuation: Optional[float] = None
    score_momentum: Optional[float] = None
    score_flow: Optional[float] = None
    inputs: Any = Field(default={}, sa_column=Column(JSON))  # 原始输入快照


class IndustryAnalysisRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    # ── 写(execute_values upsert)────────────────────────────

    def _upsert(self, table: str, cols: tuple, rows: list[dict],
                json_cols: tuple = (),
                conflict: tuple | None = None) -> int:
        if not rows:
            return 0
        conflict = conflict or cols[:2]      # 默认前两列为冲突目标
        values = []
        for r in rows:
            values.append(tuple(
                Json(r.get(c)) if c in json_cols
                else (r[c].isoformat() if isinstance(r.get(c), dt.date) and
                      c == "trade_date" else r.get(c))
                for c in cols
            ))
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
            f"ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET "
            + ", ".join(f"{c}=EXCLUDED.{c}" for c in cols
                        if c not in conflict)
        )
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def upsert_pb_break(self, rows: list[dict]) -> int:
        return self._upsert("industry_pb_break_daily", PB_BREAK_COLUMNS, rows,
                            conflict=("trade_date", "scope", "scope_code"))

    def upsert_fund_flow(self, rows: list[dict]) -> int:
        return self._upsert("industry_fund_flow_daily", FLOW_COLUMNS, rows)

    def upsert_prosperity(self, rows: list[dict]) -> int:
        return self._upsert("industry_prosperity_daily", PROSPERITY_COLUMNS,
                            rows, json_cols=("inputs",))

    # ── 破净率读 ────────────────────────────────────────────

    def get_pb_break_series(self, scope: str, scope_code: str,
                            start: dt.date, end: dt.date) -> list[dict]:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(IndustryPbBreakTable).where(
                    IndustryPbBreakTable.scope == scope,
                    IndustryPbBreakTable.scope_code == scope_code,
                    IndustryPbBreakTable.trade_date >= start,
                    IndustryPbBreakTable.trade_date <= end,
                ).order_by(IndustryPbBreakTable.trade_date)
            ).all()
            return [self._pb_row(r) for r in rows]

    def get_pb_break_latest(self, scope: str) -> Optional[dict]:
        with self._db.session_scope() as s:
            row = s.exec(
                select(IndustryPbBreakTable)
                .where(IndustryPbBreakTable.scope == scope)
                .order_by(IndustryPbBreakTable.trade_date.desc())
            ).first()
            return self._pb_row(row) if row else None

    @staticmethod
    def _pb_row(r: IndustryPbBreakTable) -> dict:
        return {"trade_date": r.trade_date, "scope": r.scope,
                "scope_code": r.scope_code, "total_count": r.total_count,
                "break_count": r.break_count, "break_rate": r.break_rate,
                "median_pb": r.median_pb}

    # ── 资金流读 ────────────────────────────────────────────

    def get_flow_latest_date(self) -> Optional[dt.date]:
        with self._db.session_scope() as s:
            return s.exec(select(func.max(IndustryFundFlowTable.trade_date))
                          ).one()

    def get_flow_rows(self, start: dt.date) -> list[dict]:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(IndustryFundFlowTable)
                .where(IndustryFundFlowTable.trade_date >= start)
                .order_by(IndustryFundFlowTable.trade_date)
            ).all()
            return [{"trade_date": r.trade_date,
                     "em_industry_name": r.em_industry_name,
                     "main_net_inflow": r.main_net_inflow,
                     "close_change_pct": r.close_change_pct} for r in rows]

    # ── 景气分读 ────────────────────────────────────────────

    def get_prosperity(self, trade_date: dt.date) -> list[dict]:
        with self._db.session_scope() as s:
            rows = s.exec(select(IndustryProsperityTable).where(
                IndustryProsperityTable.trade_date == trade_date)).all()
            return [{"sw_code": r.sw_code, "score": r.score,
                     "score_profit": r.score_profit,
                     "score_valuation": r.score_valuation,
                     "score_momentum": r.score_momentum,
                     "score_flow": r.score_flow, "inputs": r.inputs or {}}
                    for r in rows]

    def get_prosperity_latest_date(self) -> Optional[dt.date]:
        with self._db.session_scope() as s:
            return s.exec(select(func.max(IndustryProsperityTable.trade_date))
                          ).one()

    # ── 评分输入读(裸 SQL,跨表 JOIN 一次到位)────────────────

    def get_cross_section_latest_two(
        self, level: int = 1, as_of=None,
    ) -> dict[str, list]:
        """两个最新报告期截面; as_of 截断(point-in-time, 修复
        历史景气评分盈利分项用全局最新报告期的前视)。"""
        cutoff = "AND report_date <= %(as_of)s" if as_of else ""
        sql = f"""
            SELECT sw_code, report_date, revenue_yoy, net_profit_sum
            FROM sw_industry_cross_section
            WHERE level = %(lv)s AND sw_code IN (
                SELECT DISTINCT sw_code FROM sw_industry_cross_section
                WHERE level = %(lv)s
                  AND report_date = (SELECT max(report_date)
                                     FROM sw_industry_cross_section
                                     WHERE level = %(lv)s {cutoff})
            )
            AND report_date >= (SELECT max(report_date)
                                FROM sw_industry_cross_section
                                WHERE level = %(lv)s {cutoff}) - interval '550 days'
            ORDER BY sw_code, report_date
        """
        # SQLModel session.exec 仅支持 select;原生 SQL 走 connection
        params = {"lv": level}
        if as_of:
            params["as_of"] = as_of
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        out: dict[str, list] = {}
        for sw_code, report_date, rev_yoy, np_sum in rows:
            out.setdefault(sw_code, []).append({
                "report_date": report_date, "revenue_yoy": rev_yoy,
                "net_profit_sum": np_sum})
        return out

    def get_concentration(self, sw_code: str, level: int = 1) -> Optional[dict]:
        sql = ("SELECT report_date, sample_count, revenue_yoy, "
               "net_profit_sum, cr4, cr8, hhi, distribution "
               "FROM sw_industry_cross_section "
               "WHERE sw_code = %(c)s AND level = %(lv)s "
               "ORDER BY report_date DESC LIMIT 1")
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"c": sw_code, "lv": level})
                r = cur.fetchone()
        finally:
            conn.close()
        if not r:
            return None
        return {"report_date": r[0], "sample_count": r[1],
                "revenue_yoy": r[2], "net_profit_sum": r[3], "cr4": r[4],
                "cr8": r[5], "hhi": r[6], "distribution": r[7]}

    def get_member_valuations(self, trade_date: dt.date) -> list[dict]:
        sql = """
            SELECT m.symbol, m.name, m.sw_code_l1, m.sw_name_l1,
                   v.pb, v.pe_ttm, v.total_mv
            FROM sw_industry_member m
            JOIN stock_valuation v ON v.symbol = m.symbol
                                 AND v.trade_date = %(d)s
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"d": trade_date})
                rows = cur.fetchall()
        finally:
            conn.close()
        return [{"symbol": r[0], "name": r[1], "sw_code_l1": r[2],
                 "sw_name_l1": r[3], "pb": r[4], "pe_ttm": r[5],
                 "total_mv": r[6]} for r in rows]

    def get_stock_valuation_dates(self, start: dt.date,
                                  end: dt.date) -> list[dt.date]:
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT trade_date FROM stock_valuation "
                    "WHERE trade_date BETWEEN %s AND %s "
                    "ORDER BY trade_date", (start, end))
                return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

    def get_index_closes(self, symbols: list[str], start: dt.date,
                         end: dt.date) -> dict[str, list]:
        sql = ("SELECT symbol, trade_date, close_ FROM index_ohlcv "
               "WHERE symbol = ANY(%(syms)s) AND trade_date BETWEEN "
               "%(s)s AND %(e)s AND close_ IS NOT NULL "
               "ORDER BY symbol, trade_date")
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"syms": symbols, "s": start, "e": end})
                rows = cur.fetchall()
        finally:
            conn.close()
        out: dict[str, list] = {}
        for sym, d, close in rows:
            out.setdefault(sym, []).append((d, float(close)))
        return out

    def get_sw_valuation_window(self, sw_codes: list[str], start: dt.date,
                                end: dt.date) -> dict[str, list]:
        # 库内 sw_code 带 'sw' 前缀(如 sw801010);归一成纯6位再匹配/返回
        # 统一口径: computed 优先 + akshare 补缺(诊断中位偏差≤2.4%)
        sql = ("WITH merged AS ("
               "  SELECT DISTINCT ON (right(sw_code, 6), trade_date) "
               "    right(sw_code, 6) AS code6, trade_date, pe_ttm, pb "
               "  FROM sw_index_valuation_daily "
               "  WHERE right(sw_code, 6) = ANY(%(cs)s) "
               "    AND trade_date BETWEEN %(s)s AND %(e)s "
               "    AND pb IS NOT NULL "
               "  ORDER BY right(sw_code, 6), trade_date, "
               "    CASE source WHEN 'computed' THEN 0 ELSE 1 END"
               ") SELECT code6, trade_date, pe_ttm, pb FROM merged "
               "ORDER BY code6, trade_date")
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"cs": sw_codes, "s": start, "e": end})
                rows = cur.fetchall()
        finally:
            conn.close()
        out: dict[str, list] = {}
        for code, d, pe, pb in rows:
            out.setdefault(code, []).append(
                {"trade_date": d, "pe_ttm": pe, "pb": pb})
        return out


# ======== 工厂(模式同 sw_industry.py)========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_industry_analysis_repository(
    db_connection: DBConnection | None = None,
) -> IndustryAnalysisRepository:
    """创建行业分析仓储(首次调用触发惰性建表)。"""
    return IndustryAnalysisRepository(db_connection or _get_db_connection())
