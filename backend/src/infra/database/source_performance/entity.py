"""数据源表现追踪表。

移植自 ai-trend-publish 的 editorial_source_performance 表。按数据源
(source_key) 聚合每次抓取运行统计：运行次数 / 成功 / 失败 / 空结果 /
文章总数 / 最近状态 / 最近 provider / 最近错误，用于数据源健康度监控
和源筛选排序。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourcePerformanceEntity(SQLModel, table=True):
    """单数据源运行表现聚合记录（按 source_key 唯一）。"""

    __tablename__ = "source_performance"

    # source_key 形如 "<provider>:<category>" / URL
    source_key: str = Field(primary_key=True)
    provider: str = Field(default="", index=True)
    category: str = Field(default="")
    group_name: str = Field(default="")
    runs: int = 0
    successes: int = 0
    failures: int = 0
    # 列名 empty_runs（empty 在多数 SQL 方言中偏保留字）。
    empty: int = Field(default=0, sa_column_kwargs={"name": "empty_runs"})
    total_articles: int = 0
    last_status: str = ""  # success / failure / empty
    last_provider: str = ""
    last_error: str = ""
    last_run_id: str = ""
    updated_at: datetime = Field(default_factory=_utcnow, index=True)
