"""
NewsProvider 接口
=================
新闻数据源必须实现的接口。
"""
from abc import ABC, abstractmethod
from typing import Optional
from src.domain.market.news.models import NewsArticle


class NewsProvider(ABC):
    """新闻数据源抽象接口"""

    name: str = "base"

    @abstractmethod
    def fetch_news(
        self,
        symbol: Optional[str] = None,
        max_results: int = 50,
    ) -> list[NewsArticle]:
        """
        获取新闻。

        Args:
            symbol: 股票代码（如 sh600000）。None 表示市场新闻。
            max_results: 最大返回条数。

        Returns:
            NewsArticle 列表，按发布时间倒序。
        """
        ...

    @abstractmethod
    def fetch_stock_news(
        self,
        symbol: str,
        days_back: int = 7,
    ) -> list[NewsArticle]:
        """
        获取指定股票的新闻（带时间范围）。

        Args:
            symbol: 股票代码。
            days_back: 回溯天数。

        Returns:
            NewsArticle 列表。
        """
        ...
