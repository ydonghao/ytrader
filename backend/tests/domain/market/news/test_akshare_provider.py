"""
AkshareNewsProvider 测试
=========================
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.domain.market.news.models import NewsArticle
from src.domain.market.news.providers.akshare_provider import AkshareNewsProvider


class TestAkshareNewsProvider:
    """AkshareNewsProvider 测试"""

    def test_provider_name(self):
        """provider 名称正确"""
        provider = AkshareNewsProvider()
        assert provider.name == "akshare"

    def test_fetch_news_returns_list(self):
        """fetch_news 返回新闻列表"""
        provider = AkshareNewsProvider()

        mock_df = MagicMock()
        mock_df.__iter__ = MagicMock(return_value=iter([
            {
                "关键词": "苹果,手机",
                "新闻标题": "苹果发布新手机",
                "新闻内容": "苹果公司今日发布新一代iPhone",
                "发布时间": "2024-01-15 10:00:00",
                "文章来源": "新浪财经",
                "新闻链接": "https://finance.sina.com.cn/news/123.html",
            }
        ]))
        mock_df.columns = [
            "关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"
        ]

        with patch("akshare.stock_news_em", return_value=mock_df):
            result = provider.fetch_news(symbol="sh600000", max_results=10)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], NewsArticle)
        assert result[0].title == "苹果发布新手机"
        assert result[0].content == "苹果公司今日发布新一代iPhone"
        assert result[0].source == "新浪财经"
        assert result[0].url == "https://finance.sina.com.cn/news/123.html"

    def test_fetch_news_handles_empty(self):
        """fetch_news 处理空数据"""
        provider = AkshareNewsProvider()

        mock_df = MagicMock()
        mock_df.__iter__ = MagicMock(return_value=iter([]))
        mock_df.columns = [
            "关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"
        ]

        with patch("akshare.stock_news_em", return_value=mock_df):
            result = provider.fetch_news(symbol="sh600000", max_results=10)

        assert isinstance(result, list)
        assert len(result) == 0

    def test_fetch_stock_news_returns_list(self):
        """fetch_stock_news 返回新闻列表"""
        provider = AkshareNewsProvider()

        mock_df = MagicMock()
        mock_df.__iter__ = MagicMock(return_value=iter([
            {
                "关键词": "业绩,增长",
                "新闻标题": "某公司业绩增长",
                "新闻内容": "某公司发布年报，业绩大幅增长",
                "发布时间": "2024-01-15 10:00:00",
                "文章来源": "东方财富",
                "新闻链接": "https://www.eastmoney.com/news/456.html",
            }
        ]))
        mock_df.columns = [
            "关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"
        ]

        with patch("akshare.stock_news_em", return_value=mock_df):
            result = provider.fetch_stock_news(symbol="sh600000", days_back=7)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].symbol == "sh600000"

    def test_fetch_news_maps_fields_correctly(self):
        """字段映射正确"""
        provider = AkshareNewsProvider()

        mock_df = MagicMock()
        mock_df.__iter__ = MagicMock(return_value=iter([
            {
                "关键词": "关键词1,关键词2",
                "新闻标题": "测试标题",
                "新闻内容": "测试内容正文",
                "发布时间": "2024-01-15 10:00:00",
                "文章来源": "测试来源",
                "新闻链接": "https://example.com/news/1",
            }
        ]))
        mock_df.columns = [
            "关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"
        ]

        with patch("akshare.stock_news_em", return_value=mock_df):
            result = provider.fetch_news(symbol="sh600000")

        article = result[0]
        assert article.symbol == "sh600000"
        assert article.title == "测试标题"
        assert article.content == "测试内容正文"
        assert article.url == "https://example.com/news/1"
        assert article.source == "测试来源"
        assert article.keywords == ["关键词1", "关键词2"]
        assert article.provider == "akshare"
