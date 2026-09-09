"""
NewsRepository 实现
===================
使用共享连接池（DBConnection）实现新闻文章的持久化。

性能要点：
- 所有读写都走 DBConnection 连接池，避免每次新建 TCP/DB 连接（原 psycopg2.connect 实现）。
- 读路径全部带 LIMIT，避免对持续增长的 news_articles 做无界扫描。
- 启动时幂等创建 (symbol, publish_time) / (category, publish_time) 索引。
"""
import threading
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from src.domain.market.news.models import NewsArticle
from src.domain.market.news.repository import NewsRepository
from src.domain.market.news.sentiment import analyze, classify_category, extract_keywords
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection

# 查询上限：读路径默认上限，避免一次返回过多行。
DEFAULT_LIMIT = 100


class NewsRepositoryImpl(NewsRepository):
    """NewsRepository 实现（走连接池）。"""

    def __init__(self, connection_string: Optional[str] = None):
        """
        初始化仓库。

        Args:
            connection_string: 兼容旧签名（保留参数），内部忽略——
                统一使用共享连接池。新代码请用 create_news_repository() 工厂。
        """
        self._db = _get_db_connection()
        _ensure_schema(self._db)

    def save(self, articles: list[NewsArticle]) -> int:
        """
        保存新闻文章列表。

        Args:
            articles: NewsArticle 列表。

        Returns:
            保存的文章数量。
        """
        if not articles:
            return 0

        with self._db.session_scope() as session:
            conn = session._session.connection()
            for article in articles:
                text_for_analysis = f"{article.title} {article.content}"

                if not article.sentiment or article.sentiment == "neutral":
                    sentiment, score, importance = analyze(text_for_analysis)
                    article.sentiment = sentiment
                    article.sentiment_score = score
                    article.importance = importance

                if not article.keywords:
                    article.keywords = extract_keywords(text_for_analysis)

                if not article.category or article.category == "general":
                    article.category = classify_category(article.title, article.content)

                conn.execute(
                    text(
                        """
                        INSERT INTO news_articles (
                            symbol, title, content, url, source, publish_time,
                            summary, category, sentiment, sentiment_score,
                            importance, keywords, provider
                        )
                        VALUES (:symbol, :title, :content, :url, :source, :publish_time,
                                :summary, :category, :sentiment, :sentiment_score,
                                :importance, :keywords, :provider)
                        ON CONFLICT (url) DO UPDATE SET
                            title = EXCLUDED.title,
                            content = EXCLUDED.content,
                            sentiment = EXCLUDED.sentiment,
                            sentiment_score = EXCLUDED.sentiment_score,
                            importance = EXCLUDED.importance,
                            keywords = EXCLUDED.keywords,
                            category = EXCLUDED.category
                        """
                    ),
                    {
                        "symbol": article.symbol,
                        "title": article.title,
                        "content": article.content,
                        "url": article.url,
                        "source": article.source,
                        "publish_time": article.publish_time,
                        "summary": article.summary,
                        "category": article.category,
                        "sentiment": article.sentiment,
                        "sentiment_score": article.sentiment_score,
                        "importance": article.importance,
                        "keywords": article.keywords,
                        "provider": article.provider,
                    },
                )
            return len(articles)

    def find_by_symbol(
        self, symbol: str, days_back: int = 7, limit: int = DEFAULT_LIMIT
    ) -> list[NewsArticle]:
        """
        按股票代码查询新闻。

        Args:
            symbol: 股票代码（如 sh600000）。
            days_back: 回溯天数。
            limit: 返回数量上限。

        Returns:
            NewsArticle 列表。
        """
        cutoff_time = datetime.now() - timedelta(days=days_back)
        with self._db.session_scope() as session:
            conn = session._session.connection()
            result = conn.execute(
                text(
                    """
                    SELECT id, symbol, title, content, url, source, publish_time,
                           summary, category, sentiment, sentiment_score, importance,
                           keywords, provider, created_at
                    FROM news_articles
                    WHERE symbol = :symbol AND publish_time >= :cutoff
                    ORDER BY publish_time DESC
                    LIMIT :limit
                    """
                ),
                {"symbol": symbol, "cutoff": cutoff_time, "limit": limit},
            )
            return [self._row_to_article(row) for row in result]

    def find_by_category(
        self, category: str, days_back: int = 7, limit: int = DEFAULT_LIMIT
    ) -> list[NewsArticle]:
        """
        按分类查询新闻。

        Args:
            category: 分类名称。
            days_back: 回溯天数。
            limit: 返回数量上限。

        Returns:
            NewsArticle 列表。
        """
        cutoff_time = datetime.now() - timedelta(days=days_back)
        with self._db.session_scope() as session:
            conn = session._session.connection()
            result = conn.execute(
                text(
                    """
                    SELECT id, symbol, title, content, url, source, publish_time,
                           summary, category, sentiment, sentiment_score, importance,
                           keywords, provider, created_at
                    FROM news_articles
                    WHERE category = :category AND publish_time >= :cutoff
                    ORDER BY publish_time DESC
                    LIMIT :limit
                    """
                ),
                {"category": category, "cutoff": cutoff_time, "limit": limit},
            )
            return [self._row_to_article(row) for row in result]

    def find_recent(self, limit: int = DEFAULT_LIMIT) -> list[NewsArticle]:
        """
        查询最近的新闻。

        Args:
            limit: 返回数量限制。

        Returns:
            NewsArticle 列表。
        """
        with self._db.session_scope() as session:
            conn = session._session.connection()
            result = conn.execute(
                text(
                    """
                    SELECT id, symbol, title, content, url, source, publish_time,
                           summary, category, sentiment, sentiment_score, importance,
                           keywords, provider, created_at
                    FROM news_articles
                    ORDER BY publish_time DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            return [self._row_to_article(row) for row in result]

    def _row_to_article(self, row) -> NewsArticle:
        """将数据库行转换为 NewsArticle"""
        # 兼容 sqlalchemy Row 与原生 tuple
        try:
            (
                id, symbol, title, content, url, source, publish_time,
                summary, category, sentiment, sentiment_score, importance,
                keywords, provider, created_at,
            ) = row
        except (TypeError, ValueError):
            row = tuple(row)
            (
                id, symbol, title, content, url, source, publish_time,
                summary, category, sentiment, sentiment_score, importance,
                keywords, provider, created_at,
            ) = row

        return NewsArticle(
            symbol=symbol,
            title=title,
            content=content,
            url=url,
            source=source,
            publish_time=publish_time,
            summary=summary or "",
            category=category or "general",
            sentiment=sentiment or "neutral",
            sentiment_score=sentiment_score or 0.0,
            importance=importance or "medium",
            keywords=keywords or [],
            provider=provider or "",
        )


# ======== schema / 索引（幂等） ========

_schema_lock = threading.Lock()
_schema_ready = False


def _ensure_schema(db: DBConnection) -> None:
    """
    幂等创建 news_articles 表（若不存在）及其读路径索引。

    仅在首次调用时执行一次 DDL，后续直接返回。
    """
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with db.session_scope() as session:
            conn = session._session.connection()
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS news_articles (
                        id SERIAL PRIMARY KEY,
                        symbol TEXT,
                        title TEXT NOT NULL,
                        content TEXT,
                        url TEXT UNIQUE,
                        source TEXT,
                        publish_time TIMESTAMP,
                        summary TEXT,
                        category TEXT,
                        sentiment TEXT,
                        sentiment_score REAL,
                        importance TEXT,
                        keywords TEXT[],
                        provider TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )
            )
            # 覆盖 find_by_symbol / find_by_category 的 ORDER BY publish_time DESC
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_news_articles_symbol_pub "
                    "ON news_articles (symbol, publish_time DESC)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_news_articles_category_pub "
                    "ON news_articles (category, publish_time DESC)"
                )
            )
        _schema_ready = True


# ======== 工厂函数（遵循单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_news_repository(db_connection: DBConnection | None = None) -> NewsRepositoryImpl:
    """创建 NewsRepository 实例（走连接池）。"""
    db = db_connection or _get_db_connection()
    impl = NewsRepositoryImpl.__new__(NewsRepositoryImpl)
    impl._db = db
    _ensure_schema(db)
    return impl
