"""数据源表现追踪模块。

import 本包即注册 SourcePerformanceEntity 到 SQLModel.metadata,
首次建引擎时自动建表（与 intel entity 通过 repository 加载的模式一致）。
"""
from src.infra.database.source_performance.entity import (  # noqa: F401
    SourcePerformanceEntity,
)
from src.infra.database.source_performance.repository import (
    create_source_performance_repository,
    get_source_performance,
    list_source_performance,
    record_source_run,
    reset_source_performance,
)

__all__ = [
    "SourcePerformanceEntity",
    "create_source_performance_repository",
    "record_source_run",
    "list_source_performance",
    "get_source_performance",
    "reset_source_performance",
]
