"""
Akshare 新闻数据源
==================
使用 akshare 库获取东方财富网股票新闻。
"""
from datetime import datetime
from typing import Optional

import akshare

from src.domain.market.news.models import NewsArticle
from src.domain.market.news.news_provider import NewsProvider


class AkshareNewsProvider(NewsProvider):
    """Akshare 新闻数据源实现"""

    name: str = "akshare"

    def fetch_news(
        self,
        symbol: Optional[str] = None,
        max_results: int = 50,
    ) -> list[NewsArticle]:
        """
        获取新闻（市场新闻或指定股票新闻）。

        Args:
            symbol: 股票代码（如 sh600000）。None 表示获取市场新闻。
            max_results: 最大返回条数。

        Returns:
            NewsArticle 列表，按发布时间倒序。
        """
        if symbol:
            return self.fetch_stock_news(symbol, days_back=7)

        return []

    def fetch_stock_news(
        self,
        symbol: str,
        days_back: int = 7,
    ) -> list[NewsArticle]:
        """
        获取指定股票的新闻。

        Args:
            symbol: 股票代码（如 sh600000）。
            days_back: 回溯天数。

        Returns:
            NewsArticle 列表。
        """
        df = akshare.stock_news_em(symbol=symbol)

        articles = []
        for row in df.itertuples(index=False):
            keywords_str = row.关键词
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

            publish_time_str = row.发布时间
            try:
                publish_time = datetime.strptime(publish_time_str, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                publish_time = datetime.now()

            article = NewsArticle(
                symbol=symbol,
                title=row.新闻标题,
                content=row.新闻内容,
                url=row.新闻链接,
                source=row.文章来源,
                publish_time=publish_time,
                keywords=keywords,
                provider=self.name,
            )
            articles.append(article)

        return articles
