"""
NewsRepository 接口
===================
新闻文章的持久化接口。
"""
from abc import ABC, abstractmethod
from typing import Protocol

from src.domain.market.news.models import NewsArticle


class NewsRepository(Protocol):
    """新闻文章仓库接口"""

    def save(self, articles: list[NewsArticle]) -> int:
        """
        保存新闻文章列表。

        Args:
            articles: NewsArticle 列表。

        Returns:
            保存的文章数量。
        """
        ...

    def find_by_symbol(self, symbol: str, days_back: int = 7) -> list[NewsArticle]:
        """
        按股票代码查询新闻。

        Args:
            symbol: 股票代码（如 sh600000）。
            days_back: 回溯天数。

        Returns:
            NewsArticle 列表。
        """
        ...

    def find_by_category(
        self, category: str, days_back: int = 7
    ) -> list[NewsArticle]:
        """
        按分类查询新闻。

        Args:
            category: 分类名称。
            days_back: 回溯天数。

        Returns:
            NewsArticle 列表。
        """
        ...

    def find_recent(self, limit: int = 100) -> list[NewsArticle]:
        """
        查询最近的新闻。

        Args:
            limit: 返回数量限制。

        Returns:
            NewsArticle 列表。
        """
        ...
