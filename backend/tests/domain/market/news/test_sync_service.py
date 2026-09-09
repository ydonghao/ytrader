"""
NewsSyncService 测试
====================
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.domain.market.news.models import NewsArticle
from src.domain.market.news.sync_service import NewsSyncService, NewsSyncStats


class TestNewsSyncStats:
    """NewsSyncStats 测试"""

    def test_stats_defaults(self):
        """默认值正确"""
        stats = NewsSyncStats()
        assert stats.total == 0
        assert stats.saved == 0
        assert stats.duplicates == 0
        assert stats.errors == 0

    def test_stats_all_fields(self):
        """所有字段正确"""
        stats = NewsSyncStats(
            total=10,
            saved=5,
            duplicates=4,
            errors=1,
            duration_seconds=1.5,
        )
        assert stats.total == 10
        assert stats.saved == 5
        assert stats.duplicates == 4
        assert stats.errors == 1
        assert stats.duration_seconds == 1.5


class TestNewsSyncService:
    """NewsSyncService 测试"""

    @pytest.fixture
    def mock_provider(self):
        """Mock news provider"""
        provider = MagicMock()
        provider.name = "test_provider"
        return provider

    @pytest.fixture
    def mock_repository(self):
        """Mock news repository"""
        return MagicMock()

    @pytest.fixture
    def sample_articles(self):
        """示例新闻文章"""
        return [
            NewsArticle(
                symbol="sh600000",
                title="新闻1",
                content="内容1",
                url="https://example.com/1",
                source="新浪",
                publish_time=datetime(2024, 1, 15, 10, 0, 0),
                provider="test_provider",
            ),
            NewsArticle(
                symbol="sh600000",
                title="新闻2",
                content="内容2",
                url="https://example.com/2",
                source="东方财富",
                publish_time=datetime(2024, 1, 15, 11, 0, 0),
                provider="test_provider",
            ),
        ]

    def test_sync_stock_news(
        self, mock_provider, mock_repository, sample_articles
    ):
        """sync_stock_news 正确同步"""
        mock_provider.fetch_stock_news.return_value = sample_articles
        mock_repository.save.return_value = 2

        service = NewsSyncService(mock_provider, mock_repository)
        stats = service.sync_stock_news("sh600000", days_back=7)

        mock_provider.fetch_stock_news.assert_called_once_with(
            symbol="sh600000", days_back=7
        )
        mock_repository.save.assert_called_once_with(sample_articles)
        assert stats.total == 2
        assert stats.saved == 2
        assert stats.duplicates == 0

    def test_sync_stock_news_handles_empty(
        self, mock_provider, mock_repository
    ):
        """sync_stock_news 处理空列表"""
        mock_provider.fetch_stock_news.return_value = []

        service = NewsSyncService(mock_provider, mock_repository)
        stats = service.sync_stock_news("sh600000")

        assert stats.total == 0
        assert stats.saved == 0
        mock_repository.save.assert_not_called()

    def test_sync_stock_news_with_save_duplicates(
        self, mock_provider, mock_repository, sample_articles
    ):
        """sync_stock_news 处理重复（save 返回已存在）"""
        mock_provider.fetch_stock_news.return_value = sample_articles
        mock_repository.save.return_value = 0

        service = NewsSyncService(mock_provider, mock_repository)
        stats = service.sync_stock_news("sh600000")

        assert stats.total == 2
        assert stats.duplicates == 2

    def test_sync_market_news(self, mock_provider, mock_repository):
        """sync_market_news 正确同步"""
        articles = [
            NewsArticle(
                symbol=None,
                title="市场新闻",
                content="内容",
                url="https://example.com/market/1",
                source="新浪",
                publish_time=datetime(2024, 1, 15, 10, 0, 0),
                provider="test_provider",
            )
        ]
        mock_provider.fetch_news.return_value = articles
        mock_repository.save.return_value = 1

        service = NewsSyncService(mock_provider, mock_repository)
        stats = service.sync_market_news(hours_back=24)

        mock_provider.fetch_news.assert_called_once_with(
            symbol=None, max_results=50
        )
        mock_repository.save.assert_called_once()
        assert stats.total == 1
        assert stats.saved == 1

    def test_sync_service_records_duration(
        self, mock_provider, mock_repository, sample_articles
    ):
        """同步服务记录耗时"""
        mock_provider.fetch_stock_news.return_value = sample_articles
        mock_repository.save.return_value = 2

        service = NewsSyncService(mock_provider, mock_repository)
        stats = service.sync_stock_news("sh600000")

        assert stats.duration_seconds >= 0
