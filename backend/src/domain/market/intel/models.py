from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class NewsCategory(str, Enum):
    FUTURE_TECH = "future_tech"
    FINANCE = "finance"
    HOTLIST = "hotlist"
    CCTV_NEWS = "cctv_news"


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    source_type: str  # rss / api / mcp / rss_archive
    category: str
    language: str = "en"
    content: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    sentiment: Optional[float] = None
    importance: Optional[float] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime = field(default_factory=datetime.now)
    platform: Optional[str] = None
    rank: Optional[int] = None
    heat_score: Optional[float] = None
    metadata: dict = field(default_factory=dict)
    data_provider: str = ""  # legacy provider label


@dataclass
class IntelSource:
    name: str
    provider_type: str
    category: str
    config: dict = field(default_factory=dict)
    is_active: bool = True
    last_fetched_at: Optional[datetime] = None
    last_error: Optional[str] = None
    fetch_count: int = 0
    error_count: int = 0
