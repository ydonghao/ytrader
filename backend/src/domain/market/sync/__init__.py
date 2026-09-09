"""
Market Data Sync Module
=======================
可复用的行情数据同步框架。

支持：
  - 全量回填（历史数据）
  - 增量同步（每日定时）
  - 多数据源（Sina / Tencent / Akshare）
  - 断点续传

架构：
  SyncService (核心服务)
      ├── SinaProvider      (Provider 实现)
      ├── TencentProvider   (Provider 实现)
      └── ProgressTracker   (进度跟踪)
              │
              ├── BackfillJob    (一次性回填)
              └── DailyJob       (每日增量)

使用方式：
  # 一次性回填
  from src.domain.market.sync.jobs.backfill import BackfillJob
  job = BackfillJob(provider="sina", interval="1d")
  job.run()

  # 每日定时（由cron调用）
  from src.domain.market.sync.jobs.daily import DailyJob
  DailyJob().run()
"""
from .sync_service import SyncService
from .progress import ProgressTracker, SyncStatus
from .sync_provider import SyncProvider, OHLCVBar

__all__ = [
    "SyncService",
    "ProgressTracker",
    "SyncStatus",
    "SyncProvider",
    "OHLCVBar",
]
