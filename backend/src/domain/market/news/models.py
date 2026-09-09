"""
新闻数据模型
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NewsArticle:
    """新闻文章"""
    symbol: Optional[str]          # 关联股票代码（如 sh600000）
    title: str                      # 标题
    content: str                    # 内容正文
    url: str                       # 原文链接
    source: str                     # 来源（新浪/东方财富/雪球等）
    publish_time: datetime          # 发布时间
    # 可选字段
    summary: str = ""               # 摘要
    category: str = "general"       # 类别：company_announcement/market/policy/research
    sentiment: str = "neutral"       # 情绪：positive/negative/neutral
    sentiment_score: float = 0.0     # 情绪分数 -1~1
    importance: str = "medium"      # 重要性：high/medium/low
    keywords: list[str] = field(default_factory=list)  # 关键词
    provider: str = ""              # 数据源 provider 名


@dataclass
class NewsStats:
    """新闻统计"""
    total: int = 0
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    high_importance: int = 0
