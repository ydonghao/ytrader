"""
NewsSyncService
================
新闻同步服务，负责从 Provider 获取新闻并保存到 Repository。
"""
import time
from dataclasses import dataclass, field
from typing import Optional

from src.domain.market.news.models import NewsArticle
from src.domain.market.news.news_provider import NewsProvider
from src.domain.market.news.repository import NewsRepository


@dataclass
class NewsSyncStats:
    """新闻同步统计"""
    total: int = 0
    saved: int = 0
    duplicates: int = 0
    errors: int = 0
    duration_seconds: float = 0.0


class NewsSyncService:
    """新闻同步服务"""

    def __init__(
        self,
        provider: NewsProvider,
        repository: NewsRepository,
    ):
        """
        初始化同步服务。

        Args:
            provider: 新闻数据源。
            repository: 新闻仓库。
        """
        self.provider = provider
        self.repository = repository

    def sync_stock_news(
        self,
        symbol: str,
        days_back: int = 7,
    ) -> NewsSyncStats:
        """
        同步指定股票的新闻。

        Args:
            symbol: 股票代码（如 sh600000）。
            days_back: 回溯天数。

        Returns:
            NewsSyncStats 同步统计。
        """
        start_time = time.time()
        stats = NewsSyncStats()

        try:
            articles = self.provider.fetch_stock_news(
                symbol=symbol,
                days_back=days_back,
            )
            stats.total = len(articles)

            if not articles:
                return stats

            saved_count = self.repository.save(articles)
            stats.saved = saved_count
            stats.duplicates = stats.total - saved_count

        except Exception:
            stats.errors += 1

        finally:
            stats.duration_seconds = time.time() - start_time

        return stats

    def sync_market_news(
        self,
        hours_back: int = 24,
    ) -> NewsSyncStats:
        """
        同步市场新闻。

        Args:
            hours_back: 回溯小时数。

        Returns:
            NewsSyncStats 同步统计。
        """
        start_time = time.time()
        stats = NewsSyncStats()

        try:
            articles = self.provider.fetch_news(
                symbol=None,
                max_results=50,
            )
            stats.total = len(articles)

            if not articles:
                return stats

            saved_count = self.repository.save(articles)
            stats.saved = saved_count
            stats.duplicates = stats.total - saved_count

        except Exception:
            stats.errors += 1

        finally:
            stats.duration_seconds = time.time() - start_time

        return stats
