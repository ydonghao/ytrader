"""申万行业成分股与行业截面表。

sw_industry_member:      全市场申万一级/二级归属快照（job1 全量重灌）。
sw_industry_cross_section: 行业截面指标按报告期预计算（job2 全量重算
  upsert）——集中度 CR4/CR8/HHI（营收口径）、毛利率/净利率/ROE 分布、
  行业营收/净利总和与同比。下游：波特五力个股分析（课程 14 集）。

表由 SQLModel.metadata.create_all 惰性建表（项目无 Alembic，
同 national_team_holding 惯例）。
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


class SwIndustryMember(SQLModel, table=True):
    """申万成分股快照（PK(symbol, sw_code_l2) 防御偶发重复归属）。"""
    __tablename__ = "sw_industry_member"

    symbol: str = Field(primary_key=True)        # sh600519
    sw_code_l2: str = Field(primary_key=True)    # 801120（不带 .SI）
    code: str                                    # 纯6位
    name: Optional[str] = None
    sw_code_l1: str
    sw_name_l1: str
    sw_name_l2: str
    weight: Optional[float] = None               # akshare 最新权重%
    included_date: Optional[dt.date] = None
    synced_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now()),
    )


class SwIndustryCrossSection(SQLModel, table=True):
    """行业截面指标（PK(sw_code, report_date)；level=1/2 代码空间互斥）。"""
    __tablename__ = "sw_industry_cross_section"

    sw_code: str = Field(primary_key=True)
    report_date: dt.date = Field(primary_key=True)
    level: int                                    # 1=一级 2=二级
    sw_name: str
    sample_count: int = 0
    revenue_sum: Optional[float] = None           # 元（不转亿，前端格式化）
    net_profit_sum: Optional[float] = None
    cr4: Optional[float] = None                   # 0~1
    cr8: Optional[float] = None
    hhi: Optional[float] = None                   # 0~10000
    revenue_yoy: Optional[float] = None
    distribution: Any = Field(default=None, sa_column=Column(JSON))
    updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now()),
    )


_MEMBER_COLUMNS = (
    "symbol", "sw_code_l2", "code", "name",
    "sw_code_l1", "sw_name_l1", "sw_name_l2",
    "weight", "included_date",
)
_SECTION_COLUMNS = (
    "sw_code", "report_date", "level", "sw_name", "sample_count",
    "revenue_sum", "net_profit_sum", "cr4", "cr8", "hhi",
    "revenue_yoy", "distribution",
)


def _member_dict(r) -> dict:
    d = {c: getattr(r, c) for c in _MEMBER_COLUMNS}
    d["included_date"] = (
        d["included_date"].isoformat() if d.get("included_date") else None
    )
    return d


class SwIndustryRepository:
    """申万行业数据访问（SQLModel 读 + psycopg2 批量写）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 成分股 ──

    def replace_all_members(self, rows: list) -> int:
        """全量重灌（单事务 DELETE + INSERT，幂等）。"""
        if not rows:
            return 0
        values = [tuple(r.get(c) for c in _MEMBER_COLUMNS) for r in rows]
        sql = "DELETE FROM sw_industry_member"
        ins = """
            INSERT INTO sw_industry_member ({cols})
            VALUES %s
        """.format(cols=", ".join(_MEMBER_COLUMNS))
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                execute_values(cur, ins, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def get_member(self, symbol: str) -> Optional[dict]:
        with self._db.session_scope() as s:
            r = s.exec(
                select(SwIndustryMember).where(
                    SwIndustryMember.symbol == symbol,
                )
            ).first()
            return _member_dict(r) if r else None

    def fetch_members(self) -> list:
        with self._db.session_scope() as s:
            rows = list(
                s.exec(select(SwIndustryMember)).all()
            )
            return [_member_dict(r) for r in rows]

    # ── 截面 ──

    def upsert_sections(self, rows: list) -> int:
        """批量 upsert（ON CONFLICT (sw_code, report_date) DO UPDATE）。"""
        if not rows:
            return 0
        values = []
        for r in rows:
            rd = r.get("report_date")
            if hasattr(rd, "isoformat"):
                rd = rd.isoformat()
            values.append(tuple(
                Json(r[c]) if c == "distribution" else r.get(c)
                if c != "report_date" else rd
                for c in _SECTION_COLUMNS
            ))
        sql = """
            INSERT INTO sw_industry_cross_section ({cols})
            VALUES %s
            ON CONFLICT (sw_code, report_date) DO UPDATE SET
                level=EXCLUDED.level, sw_name=EXCLUDED.sw_name,
                sample_count=EXCLUDED.sample_count,
                revenue_sum=EXCLUDED.revenue_sum,
                net_profit_sum=EXCLUDED.net_profit_sum,
                cr4=EXCLUDED.cr4, cr8=EXCLUDED.cr8, hhi=EXCLUDED.hhi,
                revenue_yoy=EXCLUDED.revenue_yoy,
                distribution=EXCLUDED.distribution,
                updated_at=now()
        """.format(cols=", ".join(_SECTION_COLUMNS))
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def fetch_sections(self, sw_code: str, level: int,
                       limit: int = 200) -> list:
        """截面时序，report_date 降序（最新期在前）。"""
        with self._db.session_scope() as s:
            rows = list(s.exec(
                select(SwIndustryCrossSection)
                .where(SwIndustryCrossSection.sw_code == sw_code,
                       SwIndustryCrossSection.level == level)
                .order_by(SwIndustryCrossSection.report_date.desc())
                .limit(limit)
            ).all())
            out = []
            for r in rows:
                d = {c: getattr(r, c) for c in _SECTION_COLUMNS}
                d["report_date"] = d["report_date"].isoformat()
                out.append(d)
            return out

    def fetch_peer_details(self, sw_code: str, level: int,
                           report_date) -> list:
        """同行明细：member ⋈ income ⋈ balance（同期），roe 现算。

        revenue 为 None 的行不返回（spec 剔除口径）。
        """
        sw_col = "sw_code_l2" if level == 2 else "sw_code_l1"
        sql = f"""
            SELECT m.symbol, m.name,
                   i.revenue, i.net_profit, i.gross_margin, i.net_margin,
                   b.equity
            FROM sw_industry_member m
            JOIN stock_financial_detail i
              ON i.symbol = m.symbol
             AND i.statement_type = 'income'
             AND i.report_date = %(rd)s
            LEFT JOIN stock_financial_detail b
              ON b.symbol = i.symbol
             AND b.statement_type = 'balance'
             AND b.report_date = %(rd)s
            WHERE m.{sw_col} = %(sw)s
              AND i.revenue IS NOT NULL
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"rd": report_date, "sw": sw_code})
                raw = cur.fetchall()
        finally:
            conn.close()
        out = []
        for symbol, name, rev, np_, gm, nm, equity in raw:
            roe = None
            if np_ is not None and equity and equity > 0:
                roe = round(np_ / equity * 100, 4)
            out.append({
                "symbol": symbol, "name": name, "revenue": rev,
                "net_profit": np_, "gross_margin": gm,
                "net_margin": nm, "roe": roe,
            })
        return out


# ======== 工厂函数（模式同 index_financial.py）========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_sw_industry_repository(
    db_connection: DBConnection | None = None,
) -> SwIndustryRepository:
    """创建申万行业仓储实例（首次调用触发惰性建表）。"""
    return SwIndustryRepository(db_connection or _get_db_connection())
