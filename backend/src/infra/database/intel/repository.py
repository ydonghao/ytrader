"""
资讯仓储实现
"""
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from sqlalchemy import text, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from loguru import logger

from src.domain.market.intel.repository_interface import IIntelRepository
from src.infra.database.intel.entity import (
    IntelNewsTable, IntelSourcesTable, HotlistRankSnapshotTable,
)
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn


# ======== 工具方法 ========

def _serialize_dt(record: dict, *fields: str) -> dict:
    """Convert datetime fields to ISO strings for JSON serialization."""
    for f in fields:
        val = record.get(f)
        if val and hasattr(val, "isoformat"):
            record[f] = val.isoformat()
    return record


# ======== 仓储实现 ========

class IntelRepository(IIntelRepository):
    """资讯数据仓储，使用 SQLModel ORM。"""

    def __init__(self, db_connection: DBConnection):
        self._db = db_connection

    # ── News queries ──────────────────────────────────

    def find_news_paginated(
        self, category=None, source=None,
        language=None, importance_min=None,
        tags: list[str] | None = None,
        processed: bool | None = None,
        page=1, size=20,
    ) -> tuple[list[dict], int]:
        with self._db.session_scope() as session:
            conditions = []
            if category:
                conditions.append(IntelNewsTable.category == category)
            if source:
                conditions.append(
                    (IntelNewsTable.source == source)
                    | (IntelNewsTable.data_provider == source)
                )
            if language:
                conditions.append(IntelNewsTable.language == language)
            if importance_min is not None:
                conditions.append(IntelNewsTable.importance >= importance_min)
            if tags:
                conditions.append(
                    IntelNewsTable.tags.op('@>')(tags))
            if processed is not None:
                conditions.append(IntelNewsTable.processed == processed)

            count_stmt = select(func.count()).select_from(IntelNewsTable)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            total = session.exec(count_stmt).one()

            offset = (page - 1) * size
            stmt = (
                select(IntelNewsTable)
                .where(*conditions) if conditions else select(IntelNewsTable)
            )
            stmt = stmt.order_by(
                IntelNewsTable.published_at.desc().nullslast()
            ).offset(offset).limit(size)

            rows = session.exec(stmt).all()
            records = [_serialize_dt(
                {
                    "id": r.id, "title": r.title, "summary": r.summary,
                    "url": r.url, "source": r.source,
                    "source_type": r.source_type,
                    "data_provider": r.data_provider,
                    "category": r.category,
                    "tags": r.tags, "sentiment": r.sentiment,
                    "importance": r.importance, "language": r.language,
                    "published_at": r.published_at, "fetched_at": r.fetched_at,
                    "processed": r.processed, "platform": r.platform,
                    "rank": r.rank, "heat_score": r.heat_score,
                    "metadata": r.metadata_,
                },
                "published_at", "fetched_at",
            ) for r in rows]
        return records, total

    def find_news_by_sources(
        self, source_names: list[str],
        category: str | None = None,
        page: int = 1, size: int = 20,
    ) -> tuple[list[dict], int]:
        """Query intel_news by a list of source names (IN clause)."""
        if not source_names:
            return [], 0

        with self._db.session_scope() as session:
            conditions = [IntelNewsTable.source.in_(source_names)]
            if category:
                conditions.append(IntelNewsTable.category == category)

            count_stmt = (
                select(func.count())
                .select_from(IntelNewsTable)
                .where(*conditions)
            )
            total = session.exec(count_stmt).one()

            offset = (page - 1) * size
            stmt = (
                select(IntelNewsTable)
                .where(*conditions)
                .order_by(
                    IntelNewsTable.published_at.desc().nullslast()
                )
                .offset(offset)
                .limit(size)
            )

            rows = session.exec(stmt).all()
            records = [_serialize_dt(
                {
                    "id": r.id, "title": r.title, "summary": r.summary,
                    "url": r.url, "source": r.source,
                    "source_type": r.source_type,
                    "data_provider": r.data_provider,
                    "category": r.category,
                    "tags": r.tags, "sentiment": r.sentiment,
                    "importance": r.importance, "language": r.language,
                    "published_at": r.published_at, "fetched_at": r.fetched_at,
                    "processed": r.processed, "platform": r.platform,
                    "rank": r.rank, "heat_score": r.heat_score,
                    "metadata": r.metadata_,
                },
                "published_at", "fetched_at",
            ) for r in rows]
        return records, total

    def find_trending(self, hours: int, limit: int) -> list[dict]:
        with self._db.session_scope() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            stmt = (
                select(IntelNewsTable)
                .where(IntelNewsTable.published_at >= cutoff)
                .where(IntelNewsTable.importance.is_not(None))
                .order_by(IntelNewsTable.importance.desc(), IntelNewsTable.published_at.desc())
                .limit(limit)
            )
            rows = session.exec(stmt).all()
            records = [_serialize_dt(
                {
                    "id": r.id, "title": r.title, "summary": r.summary,
                    "url": r.url, "source": r.source,
                    "data_provider": r.data_provider,
                    "category": r.category,
                    "tags": r.tags, "sentiment": r.sentiment,
                    "importance": r.importance, "language": r.language,
                    "published_at": r.published_at,
                    "metadata": r.metadata_,
                },
                "published_at",
            ) for r in rows]
        return records

    def search_news(
        self, query: str, page: int, size: int,
    ) -> tuple[list[dict], int]:
        with self._db.session_scope() as session:
            pattern = f"%{query}%"
            like_cond = or_(
                IntelNewsTable.title.ilike(pattern),
                IntelNewsTable.summary.ilike(pattern),
                IntelNewsTable.content.ilike(pattern),
            )
            count_stmt = select(func.count()).select_from(IntelNewsTable).where(like_cond)
            total = session.exec(count_stmt).one()

            offset = (page - 1) * size
            stmt = (
                select(IntelNewsTable)
                .where(like_cond)
                .order_by(IntelNewsTable.published_at.desc().nullslast())
                .offset(offset)
                .limit(size)
            )
            rows = session.exec(stmt).all()
            records = [_serialize_dt(
                {
                    "id": r.id, "title": r.title, "summary": r.summary,
                    "url": r.url, "source": r.source,
                    "data_provider": r.data_provider,
                    "category": r.category,
                    "tags": r.tags, "sentiment": r.sentiment,
                    "importance": r.importance, "language": r.language,
                    "published_at": r.published_at,
                    "metadata": r.metadata_,
                },
                "published_at",
            ) for r in rows]
        return records, total

    def find_news_by_category(
        self, category: str,
        hours: int = 24, limit: int = 100,
    ) -> list[dict]:
        with self._db.session_scope() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            stmt = (
                select(IntelNewsTable)
                .where(IntelNewsTable.category == category)
                .where(IntelNewsTable.published_at >= cutoff)
                .order_by(IntelNewsTable.published_at.desc())
                .limit(limit)
            )
            rows = session.exec(stmt).all()
            return [_serialize_dt(
                {
                    "id": r.id, "title": r.title, "summary": r.summary,
                    "url": r.url, "source": r.source,
                    "data_provider": r.data_provider,
                    "category": r.category, "tags": r.tags,
                    "sentiment": r.sentiment, "importance": r.importance,
                    "published_at": r.published_at, "metadata": r.metadata_,
                },
                "published_at",
            ) for r in rows]

    # ── Source status ─────────────────────────────────

    def get_latest_fetch_by_provider(self) -> dict[str, str]:
        with self._db.session_scope() as session:
            stmt = (
                select(
                    IntelNewsTable.data_provider,
                    func.max(IntelNewsTable.fetched_at),
                )
                .where(IntelNewsTable.data_provider.is_not(None))
                .group_by(IntelNewsTable.data_provider)
            )
            rows = session.exec(stmt).all()
            return {
                provider: ts.isoformat()
                for provider, ts in rows
                if provider and ts
            }

    def get_latest_fetch_by_source(self) -> dict[str, str]:
        with self._db.session_scope() as session:
            stmt = (
                select(
                    IntelNewsTable.source,
                    func.max(IntelNewsTable.fetched_at),
                )
                .where(IntelNewsTable.source.is_not(None))
                .group_by(IntelNewsTable.source)
            )
            rows = session.exec(stmt).all()
            return {
                source: ts.isoformat()
                for source, ts in rows
                if source and ts
            }

    def find_sources(self) -> list[dict]:
        with self._db.session_scope() as session:
            stmt = select(IntelSourcesTable).order_by(
                IntelSourcesTable.category, IntelSourcesTable.name,
            )
            rows = session.exec(stmt).all()
            sources = [_serialize_dt(
                {
                    "name": r.name, "provider_type": r.provider_type,
                    "category": r.category, "is_active": r.is_active,
                    "last_fetched_at": r.last_fetched_at,
                    "last_error": r.last_error,
                    "fetch_count": r.fetch_count,
                    "error_count": r.error_count,
                },
                "last_fetched_at",
            ) for r in rows]
        return sources

    def upsert_source_status(
        self, name: str, category: str,
        success: bool, error: str | None = None,
        provider_type: str = "unknown",
    ):
        with self._db.session_scope() as session:
            if success:
                stmt = pg_insert(IntelSourcesTable).values(
                    name=name, provider_type=provider_type,
                    category=category,
                    last_fetched_at=datetime.now(timezone.utc),
                    fetch_count=1, is_active=True,
                ).on_conflict_do_update(
                    index_elements=["name"],
                    set_={
                        "provider_type": provider_type,
                        "last_fetched_at": datetime.now(timezone.utc),
                        "fetch_count": IntelSourcesTable.fetch_count + 1,
                        "last_error": None,
                    },
                )
            else:
                stmt = pg_insert(IntelSourcesTable).values(
                    name=name, provider_type=provider_type,
                    category=category,
                    last_error=error, error_count=1, is_active=True,
                ).on_conflict_do_update(
                    index_elements=["name"],
                    set_={
                        "provider_type": provider_type,
                        "last_error": error,
                        "error_count": IntelSourcesTable.error_count + 1,
                    },
                )
            session.exec(stmt)

    # ── News persistence (for collector) ──────────────

    def insert_news_items(
        self, items, provider_name: str, provider_category: str,
    ) -> int:
        """Batch insert news items, skip duplicates by URL."""
        inserted = 0
        with self._db.session_scope() as session:
            for item in items:
                if not item.title or not item.url:
                    continue
                try:
                    stmt = pg_insert(IntelNewsTable).values(
                        title=item.title[:500],
                        content=item.content if item.content else None,
                        url=item.url,
                        source=item.source,
                        source_type=item.source_type,
                        data_provider=(
                            item.data_provider
                            if item.data_provider else None
                        ),
                        category=item.category,
                        language=item.language,
                        published_at=item.published_at,
                        fetched_at=datetime.now(timezone.utc),
                        platform=item.platform,
                        rank=item.rank,
                        heat_score=item.heat_score,
                        metadata_=item.metadata if item.metadata else None,
                    ).on_conflict_do_nothing(index_elements=["url"])
                    result = session.exec(stmt)
                    # rowcount not directly available via session.exec,
                    # attempt alternative check
                    session.flush()
                    inserted += 1
                except Exception as e:
                    logger.debug(f"[IntelRepository] Skip item {item.url}: {e}")
        return inserted

    def find_urls_with_content(
        self, urls: list[str],
    ) -> set[str]:
        """Return the subset of `urls` already stored with non-empty content."""
        if not urls:
            return set()
        with self._db.session_scope() as session:
            rows = session.exec(
                select(IntelNewsTable.url).where(
                    IntelNewsTable.url.in_(urls),
                    IntelNewsTable.content.is_not(None),
                    IntelNewsTable.content != "",
                )
            ).all()
            return set(rows)

    # ── Stats ─────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._db.session_scope() as session:
            # 限定 30 天窗口：stats 面板只关心近期分布，避免对持续增长的
            # intel_news 做全表 GROUP BY 扫描。idx_intel_news_published 覆盖该过滤。
            result = session.execute(text("""
                SELECT category, COUNT(*) as count,
                       COUNT(*) FILTER (WHERE processed = TRUE) as processed_count,
                       AVG(sentiment) as avg_sentiment,
                       AVG(importance) as avg_importance
                FROM intel_news
                WHERE published_at >= NOW() - INTERVAL '30 days'
                GROUP BY category
            """))
            by_category = [dict(row._mapping) for row in result.fetchall()]

            result = session.execute(text("""
                SELECT COUNT(*) as last_24h FROM intel_news
                WHERE fetched_at >= NOW() - INTERVAL '24 hours'
            """))
            row = result.fetchone()
            last_24h = row._mapping["last_24h"] if row else 0
        return {
            "by_category": by_category,
            "last_24h_count": last_24h,
        }

    # ── AI Processing queries ─────────────────────────

    def find_unprocessed(self, batch_size: int) -> list[dict]:
        with self._db.session_scope() as session:
            stmt = (
                select(IntelNewsTable)
                .where(IntelNewsTable.processed == False)  # noqa: E712
                .order_by(IntelNewsTable.published_at.desc())
                .limit(batch_size)
            )
            rows = session.exec(stmt).all()
        return [
            {
                "id": r.id, "title": r.title,
                "content": r.content, "source": r.source,
                "category": r.category, "language": r.language,
            }
            for r in rows
        ]

    def update_processed(
        self, news_id: int, summary: str,
        sentiment: float, tags: list, importance: float,
        metadata: dict | None = None,
    ):
        with self._db.session_scope() as session:
            stmt = select(IntelNewsTable).where(IntelNewsTable.id == news_id)
            row = session.exec(stmt).first()
            if row:
                row.summary = summary
                row.sentiment = sentiment
                row.tags = tags
                row.importance = importance
                row.processed = True
                if metadata:
                    row.metadata_ = metadata

    # ── Daily summary query ───────────────────────────

    def get_category_summary(self) -> list[dict]:
        with self._db.session_scope() as session:
            result = session.execute(text("""
                SELECT category,
                       COUNT(*) as count,
                       AVG(sentiment) as avg_sentiment,
                       AVG(importance) as avg_importance
                FROM intel_news
                WHERE published_at >= NOW() - INTERVAL '24 hours'
                GROUP BY category
                ORDER BY avg_importance DESC
            """))
            categories = [dict(row._mapping) for row in result.fetchall()]
        return categories

    def get_top_tags_for_category(self, category: str) -> list[str]:
        with self._db.session_scope() as session:
            result = session.execute(text("""
                SELECT t, COUNT(*) AS freq
                FROM intel_news, unnest(tags) AS t
                WHERE category = :category
                    AND published_at >= NOW() - INTERVAL '30 days'
                    AND length(t) >= 3
                GROUP BY t
                HAVING COUNT(*) >= 2
                ORDER BY freq DESC
                LIMIT 20
            """), {"category": category})
            tags = [row[0] for row in result.fetchall()]
        return tags

    # ── Data retention ──────────────────────────────────

    def cleanup_old_news(self, retention_days: int = 90) -> int:
        """Delete news older than retention_days. Returns deleted count."""
        with self._db.session_scope() as session:
            result = session.execute(text("""
                DELETE FROM intel_news
                WHERE fetched_at < NOW() - (:days || ' days')::interval
            """), {"days": retention_days})
            deleted = result.rowcount
            logger.info(
                f"[IntelRepository] Cleaned up {deleted} "
                f"news older than {retention_days} days")
        return deleted

    def get_unprocessed_counts(self) -> dict:
        """Return unprocessed news counts per category."""
        with self._db.session_scope() as session:
            result = session.execute(text("""
                SELECT category, COUNT(*) as unprocessed_count
                FROM intel_news
                WHERE processed = FALSE
                GROUP BY category
            """))
            counts = {
                row.category: row.unprocessed_count
                for row in result.fetchall()
            }
        return counts

    def find_analyzed_news(
        self, category=None, page=1, size=20,
    ) -> tuple[list[dict], int]:
        """Return paginated news that have deep_analysis results."""
        with self._db.session_scope() as session:
            conditions = ["deep_analysis IS NOT NULL"]
            params: dict = {}
            if category:
                conditions.append("category = :category")
                params["category"] = category

            where = " AND ".join(conditions)

            count_q = text(
                f"SELECT COUNT(*) FROM intel_news WHERE {where}"
            )
            total = session.execute(count_q, params).scalar()

            offset = (page - 1) * size
            data_q = text(f"""
                SELECT id, title, url, source, category,
                       data_provider,
                       tags, sentiment, importance,
                       published_at, deep_analysis
                FROM intel_news
                WHERE {where}
                ORDER BY published_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """)
            params["limit"] = size
            params["offset"] = offset
            rows = session.execute(data_q, params).fetchall()

            records = []
            for r in rows:
                rec = dict(r._mapping)
                _serialize_dt(rec, "published_at")
                records.append(rec)
        return records, total

    # ── Hotlist rank tracking ──────────────────────────

    def record_rank_snapshots(self, items: list) -> int:
        """Append rank snapshots for hotlist items."""
        inserted = 0
        now = datetime.now(timezone.utc)
        with self._db.session_scope() as session:
            for item in items:
                if not item.title:
                    continue
                try:
                    row = HotlistRankSnapshotTable(
                        title=item.title[:500],
                        platform=item.platform,
                        url=item.url,
                        rank=item.rank,
                        crawled_at=now,
                    )
                    session.add(row)
                    inserted += 1
                except Exception as e:
                    logger.debug(
                        f"[IntelRepository] Skip rank snapshot: {e}")
        return inserted

    def get_current_hotlist(
        self, platform: str | None = None, limit: int = 50,
    ) -> list[dict]:
        """Get latest hotlist: one row per (platform, title) from
        the most recent crawl, ordered by platform then rank."""
        with self._db.session_scope() as session:
            params: dict = {"limit": limit}
            platform_filter = ""
            if platform:
                platform_filter = "AND platform = :platform"
                params["platform"] = platform

            q = text(f"""
                SELECT DISTINCT ON (platform, title)
                       title, platform, url, rank, crawled_at
                FROM hotlist_rank_snapshot
                WHERE crawled_at >= NOW() - INTERVAL '1 hour'
                      {platform_filter}
                ORDER BY platform, title, crawled_at DESC
            """)
            rows = session.execute(q, params).fetchall()

            # Group by platform, sort by rank within each
            items = [_serialize_dt(dict(r._mapping), "crawled_at")
                     for r in rows]
            items.sort(key=lambda x: (
                x.get("platform") or "", x.get("rank") or 999))
        return items[:limit]

    def get_rank_history(
        self, title: str, platform: str, hours: int = 24,
    ) -> list[dict]:
        """Get rank timeline for a specific title on a platform."""
        with self._db.session_scope() as session:
            q = text("""
                SELECT rank, crawled_at
                FROM hotlist_rank_snapshot
                WHERE title = :title
                  AND platform = :platform
                  AND crawled_at >= NOW() - (:hours || ' hours')::interval
                ORDER BY crawled_at
            """)
            rows = session.execute(q, {
                "title": title, "platform": platform,
                "hours": hours,
            }).fetchall()
            return [_serialize_dt(dict(r._mapping), "crawled_at")
                    for r in rows]

    def get_distinct_sources(self) -> list[str]:
        """Return distinct source names ordered alphabetically."""
        with self._db.session_scope() as session:
            rows = session.execute(text("""
                SELECT DISTINCT source FROM intel_news
                WHERE source IS NOT NULL
                ORDER BY source
            """)).fetchall()
            return [r[0] for r in rows]

    def cleanup_old_snapshots(self, retention_days: int = 90) -> int:
        """Delete snapshots older than retention_days."""
        with self._db.session_scope() as session:
            result = session.execute(text("""
                DELETE FROM hotlist_rank_snapshot
                WHERE crawled_at < NOW()
                    - (:days || ' days')::interval
            """), {"days": retention_days})
            deleted = result.rowcount
            logger.info(
                f"[IntelRepository] Cleaned up {deleted} "
                f"rank snapshots older than {retention_days} days")
        return deleted

    # ── CRUD operations ───────────────────────────────────

    def get_news_by_id(self, news_id: int) -> dict | None:
        with self._db.session_scope() as session:
            stmt = select(IntelNewsTable).where(
                IntelNewsTable.id == news_id)
            row = session.exec(stmt).first()
            if not row:
                return None
            return _serialize_dt(
                {
                    "id": row.id, "title": row.title,
                    "content": row.content, "summary": row.summary,
                    "url": row.url, "source": row.source,
                    "source_type": row.source_type,
                    "data_provider": row.data_provider,
                    "category": row.category,
                    "tags": row.tags, "sentiment": row.sentiment,
                    "importance": row.importance,
                    "language": row.language,
                    "platform": row.platform,
                    "rank": row.rank, "heat_score": row.heat_score,
                    "published_at": row.published_at,
                    "fetched_at": row.fetched_at,
                    "processed": row.processed,
                    "deep_analysis": row.deep_analysis,
                    "metadata": row.metadata_,
                },
                "published_at", "fetched_at",
            )

    def create_news(self, data: dict) -> dict:
        with self._db.session_scope() as session:
            row = IntelNewsTable(
                title=data.get("title", ""),
                content=data.get("content"),
                summary=data.get("summary"),
                url=data.get("url"),
                source=data.get("source"),
                source_type=data.get("source_type"),
                data_provider=data.get("data_provider"),
                category=data.get("category"),
                tags=data.get("tags"),
                language=data.get("language"),
                platform=data.get("platform"),
                published_at=data.get("published_at"),
                fetched_at=datetime.now(timezone.utc),
                processed=data.get("processed", False),
                metadata_=data.get("metadata"),
            )
            session.add(row)
            session.flush()
            return _serialize_dt(
                {
                    "id": row.id, "title": row.title,
                    "content": row.content, "summary": row.summary,
                    "url": row.url, "source": row.source,
                    "category": row.category,
                    "published_at": row.published_at,
                },
                "published_at", "fetched_at",
            )

    def update_news(
        self, news_id: int, data: dict,
    ) -> dict | None:
        with self._db.session_scope() as session:
            stmt = select(IntelNewsTable).where(
                IntelNewsTable.id == news_id)
            row = session.exec(stmt).first()
            if not row:
                return None
            for field in (
                "title", "content", "summary", "url", "source",
                "source_type", "data_provider", "category", "tags",
                "language", "platform", "published_at", "processed",
            ):
                if field in data:
                    setattr(row, field, data[field])
            if "metadata" in data:
                row.metadata_ = data["metadata"]
            session.flush()
            return _serialize_dt(
                {
                    "id": row.id, "title": row.title,
                    "content": row.content, "summary": row.summary,
                    "url": row.url, "source": row.source,
                    "category": row.category,
                    "published_at": row.published_at,
                },
                "published_at", "fetched_at",
            )

    def delete_news(self, news_id: int) -> bool:
        with self._db.session_scope() as session:
            stmt = select(IntelNewsTable).where(
                IntelNewsTable.id == news_id)
            row = session.exec(stmt).first()
            if not row:
                return False
            session.delete(row)
            return True


# ======== 工厂函数 ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_intel_repository(
    db_connection: DBConnection | None = None,
) -> IntelRepository:
    """创建资讯仓储实例。"""
    return IntelRepository(db_connection or _get_db_connection())
