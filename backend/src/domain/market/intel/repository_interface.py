from abc import ABC, abstractmethod


class IIntelRepository(ABC):

    @abstractmethod
    def find_news_paginated(
        self, category=None, source=None,
        language=None, importance_min=None,
        tags: list[str] | None = None,
        processed: bool | None = None,
        page=1, size=20,
    ) -> tuple[list[dict], int]: ...

    @abstractmethod
    def find_trending(self, hours: int, limit: int) -> list[dict]: ...

    @abstractmethod
    def search_news(
        self, query: str, page: int, size: int,
    ) -> tuple[list[dict], int]: ...

    @abstractmethod
    def find_sources(self) -> list[dict]: ...

    @abstractmethod
    def upsert_source_status(
        self, name: str, category: str,
        success: bool, error: str | None = None,
    ): ...

    @abstractmethod
    def insert_news_items(
        self, items, provider_name: str, provider_category: str,
    ) -> int: ...

    @abstractmethod
    def find_urls_with_content(
        self, urls: list[str],
    ) -> set[str]:
        """Return the subset of `urls` already stored with non-empty content."""
        ...

    @abstractmethod
    def get_stats(self) -> dict: ...

    @abstractmethod
    def find_unprocessed(self, batch_size: int) -> list[dict]: ...

    @abstractmethod
    def update_processed(
        self, news_id: int, summary: str,
        sentiment: float, tags: list, importance: float,
        metadata: dict | None = None,
    ): ...

    @abstractmethod
    def get_category_summary(self) -> list[dict]: ...

    @abstractmethod
    def get_top_tags_for_category(self, category: str) -> list[str]: ...

    @abstractmethod
    def find_news_by_category(
        self, category: str,
        hours: int = 24, limit: int = 100,
    ) -> list[dict]: ...

    @abstractmethod
    def find_news_by_sources(
        self, source_names: list[str],
        category: str | None = None,
        page: int = 1, size: int = 20,
    ) -> tuple[list[dict], int]: ...

    @abstractmethod
    def cleanup_old_news(self, retention_days: int = 90) -> int: ...

    @abstractmethod
    def get_unprocessed_counts(self) -> dict: ...

    @abstractmethod
    def find_analyzed_news(
        self, category=None, page=1, size=20,
    ) -> tuple[list[dict], int]: ...

    # ── Hotlist rank tracking ──────────────────────────

    @abstractmethod
    def record_rank_snapshots(self, items: list) -> int:
        """Record rank snapshots for hotlist items. Returns inserted count."""
        ...

    @abstractmethod
    def get_current_hotlist(
        self, platform: str | None = None, limit: int = 50,
    ) -> list[dict]:
        """Get current hotlist from latest snapshots per platform+title."""
        ...

    @abstractmethod
    def get_rank_history(
        self, title: str, platform: str, hours: int = 24,
    ) -> list[dict]:
        """Get rank timeline for a specific item on a platform."""
        ...

    @abstractmethod
    def cleanup_old_snapshots(self, retention_days: int = 90) -> int:
        """Delete snapshots older than retention_days. Returns deleted count."""
        ...

    # ── Source lookup ─────────────────────────────────────

    @abstractmethod
    def get_distinct_sources(self) -> list[str]:
        """Return distinct source names from intel_news."""
        ...

    # ── CRUD operations ───────────────────────────────────

    @abstractmethod
    def get_news_by_id(self, news_id: int) -> dict | None:
        """Get a single news record by primary key."""
        ...

    @abstractmethod
    def create_news(self, data: dict) -> dict:
        """Create a new news record. Returns the created record."""
        ...

    @abstractmethod
    def update_news(
        self, news_id: int, data: dict,
    ) -> dict | None:
        """Update a news record by PK. Returns updated record or None."""
        ...

    @abstractmethod
    def delete_news(self, news_id: int) -> bool:
        """Delete a news record by PK. Returns True if deleted."""
        ...
