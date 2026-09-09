"""
NewsRepository 实现测试
=======================

覆盖走连接池（DBConnection）的实现。通过 mock session/connection 校验：
- save 正确批量 upsert
- find_by_symbol / find_by_category / find_recent 带 LIMIT 的查询
- 结果行正确映射为 NewsArticle
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.domain.market.news.models import NewsArticle
from src.infra.database import news_repository as news_mod
from src.infra.database.news_repository import NewsRepositoryImpl


def _make_repo_with_mock_conn(mock_conn):
    """
    构造一个 NewsRepositoryImpl，其底层 session_scope 产出的 session 连接被替换为 mock_conn。
    跳过幂等建表逻辑。
    """
    # 建表副作用在 __init__ 中触发，patch 掉 _ensure_schema 即可
    mock_session = MagicMock()
    mock_session._session.connection.return_value = mock_conn

    mock_db = MagicMock()
    # session_scope 是 contextmanager
    mock_db.session_scope.return_value.__enter__.return_value = mock_session
    mock_db.session_scope.return_value.__exit__.return_value = False

    with patch.object(news_mod, "_ensure_schema"):
        with patch.object(news_mod, "_get_db_connection", return_value=mock_db):
            return NewsRepositoryImpl()


class TestNewsRepositoryImpl:
    """NewsRepositoryImpl 测试（连接池实现）"""

    @pytest.fixture
    def sample_articles(self):
        """示例新闻文章"""
        return [
            NewsArticle(
                symbol="sh600000",
                title="测试新闻1",
                content="测试内容1",
                url="https://example.com/news/1",
                source="新浪",
                publish_time=datetime(2024, 1, 15, 10, 0, 0),
                summary="摘要1",
                category="company_announcement",
                sentiment="positive",
                sentiment_score=0.5,
                importance="high",
                keywords=["业绩", "增长"],
                provider="akshare",
            ),
            NewsArticle(
                symbol="sh600000",
                title="测试新闻2",
                content="测试内容2",
                url="https://example.com/news/2",
                source="东方财富",
                publish_time=datetime(2024, 1, 14, 10, 0, 0),
                summary="摘要2",
                category="market_news",
                sentiment="neutral",
                sentiment_score=0.0,
                importance="medium",
                keywords=["行情"],
                provider="akshare",
            ),
        ]

    def test_save_articles(self, sample_articles):
        """save 方法正确批量保存文章（每条一次 execute）"""
        mock_conn = MagicMock()
        repo = _make_repo_with_mock_conn(mock_conn)
        count = repo.save(sample_articles)

        assert count == 2
        assert mock_conn.execute.call_count == 2

    def test_save_empty_returns_zero(self):
        """空列表直接返回 0，不触发 DB"""
        mock_conn = MagicMock()
        repo = _make_repo_with_mock_conn(mock_conn)
        assert repo.save([]) == 0
        mock_conn.execute.assert_not_called()

    def test_find_by_symbol(self):
        """find_by_symbol 正确查询并映射"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value = [
            (
                1, "sh600000", "测试新闻", "测试内容", "https://example.com/1",
                "新浪", datetime(2024, 1, 15, 10, 0, 0), "摘要",
                "company_announcement", "positive", 0.5, "high",
                ["业绩", "增长"], "akshare", datetime(2024, 1, 15, 12, 0, 0),
            ),
        ]
        repo = _make_repo_with_mock_conn(mock_conn)
        articles = repo.find_by_symbol("sh600000", days_back=7)

        assert len(articles) == 1
        assert articles[0].title == "测试新闻"
        assert articles[0].symbol == "sh600000"
        assert articles[0].sentiment == "positive"

        # 校验 SQL 带 LIMIT 且参数绑定（参数是第二个位置参数）
        executed_sql = str(mock_conn.execute.call_args.args[0])
        assert "LIMIT" in executed_sql
        params = mock_conn.execute.call_args.args[1]
        assert params["symbol"] == "sh600000"
        assert params["limit"] == news_mod.DEFAULT_LIMIT

    def test_find_by_category(self):
        """find_by_category 正确查询并映射"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value = [
            (
                1, "sh600000", "测试新闻", "测试内容", "https://example.com/1",
                "新浪", datetime(2024, 1, 15, 10, 0, 0), "摘要",
                "company_announcement", "positive", 0.5, "high",
                ["业绩"], "akshare", datetime(2024, 1, 15, 12, 0, 0),
            ),
        ]
        repo = _make_repo_with_mock_conn(mock_conn)
        articles = repo.find_by_category("company_announcement", days_back=7)

        assert len(articles) == 1
        assert articles[0].category == "company_announcement"

        executed_sql = str(mock_conn.execute.call_args.args[0])
        assert "LIMIT" in executed_sql

    def test_find_recent(self):
        """find_recent 正确查询并映射"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value = [
            (
                1, "sh600000", "新闻1", "内容1", "https://example.com/1",
                "新浪", datetime(2024, 1, 15, 10, 0, 0), "摘要",
                "general", "neutral", 0.0, "medium", [], "akshare",
                datetime(2024, 1, 15, 12, 0, 0),
            ),
            (
                2, "sh600001", "新闻2", "内容2", "https://example.com/2",
                "东方财富", datetime(2024, 1, 14, 10, 0, 0), "摘要",
                "general", "neutral", 0.0, "medium", [], "akshare",
                datetime(2024, 1, 14, 12, 0, 0),
            ),
        ]
        repo = _make_repo_with_mock_conn(mock_conn)
        articles = repo.find_recent(limit=100)

        assert len(articles) == 2
        assert articles[0].title == "新闻1"
        assert articles[1].title == "新闻2"
