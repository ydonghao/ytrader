"""财报季景气雷达三表:词典 / 扫描命中 / 候选池。

session-loop upsert(非 execute_values):日频量级小(千级),换取
方言无关(sqlite 单测 + PG 生产都可跑)。
"""
import datetime as dt
import threading
from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy import JSON, Column, DateTime, Text, UniqueConstraint, func
from sqlmodel import Field, SQLModel, Session, select

from src.domain.market.boom.keywords import SEED_KEYWORDS
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)

_CANDIDATE_COLS = (
    "symbol", "report_date", "forecast_type", "company_name", "announce_date",
    "change_pct", "forecast_type_label", "categories", "keyword_count",
    "news_hit_count",
)


class BoomKeywordTable(SQLModel, table=True):
    __tablename__ = "boom_keyword"
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True)
    keyword: str = Field(unique=True)
    weight: int = Field(default=1)
    enabled: bool = Field(default=True)


class BoomScanHitTable(SQLModel, table=True):
    __tablename__ = "boom_scan_hit"
    __table_args__ = (
        UniqueConstraint("source_type", "source_ref", "keyword",
                         name="uq_boom_hit"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)              # 纯 6 位
    source_type: str = Field()                   # forecast / news / survey
    source_ref: str = Field()                    # forecast主键串 / 新闻url / 调研日期串
    source_date: Optional[dt.date] = Field(default=None)
    keyword: str = Field()
    category: str = Field(index=True)
    snippet: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.now)


class BoomCandidateTable(SQLModel, table=True):
    __tablename__ = "boom_candidate"
    symbol: str = Field(primary_key=True)        # 纯 6 位
    report_date: dt.date = Field(primary_key=True)
    forecast_type: str = Field(default="preannounce")
    company_name: Optional[str] = None
    announce_date: Optional[dt.date] = None
    change_pct: Optional[float] = None
    forecast_type_label: Optional[str] = None
    categories: Any = Field(default=[], sa_column=Column(JSON))
    keyword_count: int = Field(default=0)
    news_hit_count: int = Field(default=0)
    news_synced: bool = Field(default=False)     # 新闻已同步过,重跑跳过
    llm_score: Optional[int] = None
    llm_verdict: Optional[str] = None            # focus / watch / exclude
    llm_summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    llm_analyzed_at: Optional[datetime] = None
    status: str = Field(default="new")           # new/confirmed/dismissed/added_watchlist
    updated_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now()),
    )


class BoomRepository:
    def __init__(self, session_scope: Callable):
        self._scope = session_scope

    # ── 词典 ──────────────────────────────────────────────
    def seed_keywords(self) -> int:
        with self._scope() as s:
            existing = {k.keyword for k in s.exec(select(BoomKeywordTable)).all()}
            new = [BoomKeywordTable(category=k.category, keyword=k.keyword,
                                    weight=k.weight)
                   for k in SEED_KEYWORDS if k.keyword not in existing]
            s.add_all(new)
            s.commit()
            return len(new)

    def list_keywords(self, enabled_only: bool = True) -> list[BoomKeywordTable]:
        with self._scope() as s:
            stmt = select(BoomKeywordTable)
            if enabled_only:
                stmt = stmt.where(BoomKeywordTable.enabled == True)  # noqa: E712
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_keyword(self, kid: int) -> Optional[BoomKeywordTable]:
        with self._scope() as s:
            return s.get(BoomKeywordTable, kid)

    def create_keyword(self, category: str, keyword: str, weight: int = 1):
        with self._scope() as s:
            row = BoomKeywordTable(category=category, keyword=keyword, weight=weight)
            s.add(row)
            s.commit()
            s.refresh(row)
            s.expunge(row)
            return row

    def update_keyword(self, kid: int, **fields):
        with self._scope() as s:
            row = s.get(BoomKeywordTable, kid)
            if row is None:
                return None
            for k, v in fields.items():
                setattr(row, k, v)
            s.commit()
            return row

    def delete_keyword(self, kid: int) -> bool:
        with self._scope() as s:
            row = s.get(BoomKeywordTable, kid)
            if row is None:
                return False
            s.delete(row)
            s.commit()
            return True

    # ── 命中明细 ──────────────────────────────────────────
    def upsert_hits(self, rows: list[dict]) -> int:
        added = 0
        with self._scope() as s:
            for r in rows:
                stmt = select(BoomScanHitTable).where(
                    BoomScanHitTable.source_type == r["source_type"],
                    BoomScanHitTable.source_ref == r["source_ref"],
                    BoomScanHitTable.keyword == r["keyword"],
                )
                if s.exec(stmt).first() is not None:
                    continue
                s.add(BoomScanHitTable(**r))
                added += 1
            s.commit()
        return added

    def get_hits(self, symbol: str, report_date: Optional[dt.date] = None):
        with self._scope() as s:
            stmt = select(BoomScanHitTable).where(
                BoomScanHitTable.symbol == symbol
            ).order_by(BoomScanHitTable.source_date.desc())
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_hits_as_of(self, symbols: list[str], max_source_date: dt.date):
        """回测用:只取 source_date ≤ max_source_date 的命中(前视守卫数据腿)。"""
        if not symbols:
            return []
        with self._scope() as s:
            stmt = select(BoomScanHitTable).where(
                BoomScanHitTable.symbol.in_(symbols),
                BoomScanHitTable.source_date <= max_source_date,
            )
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    # ── 候选池 ────────────────────────────────────────────
    def upsert_candidates(self, rows: list[dict]) -> int:
        with self._scope() as s:
            for r in rows:
                existing = s.get(BoomCandidateTable,
                                 (r["symbol"], r["report_date"]))
                if existing is None:
                    s.add(BoomCandidateTable(**{k: r[k] for k in _CANDIDATE_COLS
                                                if k in r}))
                else:
                    for k in _CANDIDATE_COLS:
                        if k in r:
                            setattr(existing, k, r[k])
            s.commit()
        return len(rows)

    def get_candidates(self, report_date: Optional[dt.date] = None,
                       limit: int = 1000) -> list[BoomCandidateTable]:
        with self._scope() as s:
            stmt = select(BoomCandidateTable)
            if report_date is None:
                latest = s.exec(select(BoomCandidateTable.report_date)
                                .order_by(BoomCandidateTable.report_date.desc())
                                ).first()
                if latest is None:
                    return []
                report_date = latest
            stmt = (stmt.where(BoomCandidateTable.report_date == report_date)
                    .order_by(BoomCandidateTable.change_pct.desc())
                    .limit(limit))
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_report_dates(self, limit: int = 8) -> list:
        """候选池内 distinct report_date(降序,默认前8)——报告期下拉用。"""
        with self._scope() as s:
            rows = list(s.exec(
                select(BoomCandidateTable.report_date).distinct()
                .order_by(BoomCandidateTable.report_date.desc()).limit(limit)
            ).all())
            return rows

    def get_candidate(self, symbol: str, report_date: dt.date):
        with self._scope() as s:
            row = s.get(BoomCandidateTable, (symbol, report_date))
            if row is not None:
                s.expunge(row)
            return row

    def mark_news_synced(self, symbol: str, report_date: dt.date):
        with self._scope() as s:
            row = s.get(BoomCandidateTable, (symbol, report_date))
            if row is not None:
                row.news_synced = True
                s.commit()

    def mark_llm(self, symbol: str, report_date: dt.date,
                 score: Optional[int], verdict: Optional[str],
                 summary: Optional[str]):
        with self._scope() as s:
            row = s.get(BoomCandidateTable, (symbol, report_date))
            if row is not None:
                row.llm_score = score
                row.llm_verdict = verdict
                row.llm_summary = summary
                row.llm_analyzed_at = datetime.now()
                s.commit()

    def set_status(self, symbol: str, report_date: dt.date, status: str):
        with self._scope() as s:
            row = s.get(BoomCandidateTable, (symbol, report_date))
            if row is not None:
                row.status = status
                s.commit()


_db_connection: Optional[DBConnection] = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_boom_repository() -> BoomRepository:
    return BoomRepository(_get_db_connection().session_scope)
