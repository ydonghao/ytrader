"""
资讯表模型定义
SQLModel table classes for the intel (news) domain.
"""
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import Column, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import SQLModel, Field


class IntelNewsTable(SQLModel, table=True):
    __tablename__ = "intel_news"
    __table_args__ = (
        Index("idx_intel_news_category", "category"),
        Index("idx_intel_news_published", "published_at"),
        Index("idx_intel_news_importance", "importance"),
        Index("idx_intel_news_tags", "tags", postgresql_using="gin"),
        Index("idx_intel_news_platform", "platform"),
        Index("idx_intel_news_cat_pub", "category", "published_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(Text, nullable=False))
    content: Optional[str] = Field(default=None, sa_column=Column(Text))
    summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    url: Optional[str] = Field(default=None, sa_column=Column(Text, unique=True))
    source: Optional[str] = Field(
        default=None, sa_column=Column(Text))
    source_type: Optional[str] = Field(default=None, max_length=20)
    data_provider: Optional[str] = Field(default=None, max_length=30)
    category: Optional[str] = Field(default=None, max_length=20)
    tags: Optional[List[str]] = Field(default=None, sa_column=Column(ARRAY(String)))
    sentiment: Optional[float] = Field(default=None)
    importance: Optional[float] = Field(default=None)
    language: Optional[str] = Field(default=None, max_length=5)
    platform: Optional[str] = Field(default=None, max_length=50)
    rank: Optional[int] = Field(default=None)
    heat_score: Optional[float] = Field(default=None)
    published_at: Optional[datetime] = Field(default=None)
    fetched_at: Optional[datetime] = Field(default_factory=datetime.now)
    processed: bool = Field(default=False)
    deep_analysis: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    metadata_: Optional[dict] = Field(default=None, sa_column=Column("metadata", JSONB))


class IntelSourcesTable(SQLModel, table=True):
    __tablename__ = "intel_sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None, max_length=100, unique=True, index=True)
    provider_type: Optional[str] = Field(default=None, max_length=20)
    category: Optional[str] = Field(default=None, max_length=20)
    config: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    is_active: bool = Field(default=True)
    last_fetched_at: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None, sa_column=Column(Text))
    fetch_count: int = Field(default=0)
    error_count: int = Field(default=0)


class HotlistRankSnapshotTable(SQLModel, table=True):
    """热点排名快照 — 每次爬取追加记录，用于排名时间线查询。"""
    __tablename__ = "hotlist_rank_snapshot"
    __table_args__ = (
        Index(
            "idx_hrs_platform_title_time",
            "platform", "title", "crawled_at",
        ),
        Index("idx_hrs_crawled_at", "crawled_at"),
        Index("idx_hrs_platform", "platform"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(Text, nullable=False))
    platform: Optional[str] = Field(default=None, max_length=50)
    url: Optional[str] = Field(default=None, sa_column=Column(Text))
    rank: Optional[int] = Field(default=None)
    crawled_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc))
