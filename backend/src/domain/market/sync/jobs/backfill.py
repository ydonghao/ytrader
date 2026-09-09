"""
BackfillJob
===========
一次性全量回填任务。

功能：
  - 从数据源拉取全量历史数据
  - 支持断点续传（跳过已完成symbol）
  - 支持多种数据源（Sina/Tencent）
  - 支持日线和分钟线

使用：
  python -m src.domain.market.sync.jobs.backfill --provider=sina --interval=1d
  python -m src.domain.market.sync.jobs.backfill --provider=tencent --interval=1d --market=HK
"""
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 path
_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync import ProgressTracker, SyncService
from src.domain.market.sync.providers import SinaProvider, TencentProvider
from src.domain.market.sync.sync_provider import SyncProvider
from src.domain.market.sync.sync_service import SyncConfig, SyncResult

log = logging.getLogger("backfill_job")


def _build_provider(name: str) -> SyncProvider:
    if name == "sina":
        return SinaProvider(rate_delay=1.0)   # Sina 限速保守
    elif name == "tencent":
        return TencentProvider(rate_delay=0.05)  # Tencent 高速
    else:
        raise ValueError(f"Unknown provider: {name}")


def _get_dsn() -> str:
    dsn = os.environ.get("TIMESCALE_DSN")
    if dsn:
        return dsn
    from src.infra.database.sql_engine.dsn import get_dsn as _g
    return _g()


def run(
    provider: str = "sina",
    interval: str = "1d",
    market: str = "A",
    max_workers: int = 8,
    rate_delay: float = 1.0,
) -> SyncResult:
    """
    执行全量回填

    Args:
        provider:   "sina" | "tencent"
        interval:   "1d" | "5m" | "15m" | "60m"
        market:     "A" | "HK"
        max_workers: 并发数
        rate_delay: 每次请求后等待秒数
    """
    log.info(f"=== BackfillJob {provider}/{interval}/{market} ===")

    # 1. 初始化组件
    prov = _build_provider(provider)
    tracker = ProgressTracker()
    config = SyncConfig(
        max_workers=max_workers,
        rate_delay=rate_delay,
        db_dsn=_get_dsn(),
    )
    service = SyncService(prov, tracker, config)

    # 2. 获取股票列表
    all_symbols = prov.get_stock_list(market=market)
    log.info(f"股票列表: {len(all_symbols)} 只")

    # 3. 执行同步
    result = service.backfill(
        symbols=all_symbols,
        interval=interval,
        mode="full",
    )

    # 4. 汇总
    log.info(f"=== BackfillJob 完成 ===")
    log.info(f"  写入: {result.total_rows:,} 行")
    log.info(f"  成功: {result.done_symbols} / {result.total_symbols}")
    if result.errors:
        for e in result.errors[:5]:
            log.warning(f"    {e}")
    return result


def main():
    parser = argparse.ArgumentParser(description="全量回填任务")
    parser.add_argument("--provider", default="sina", choices=["sina", "tencent"])
    parser.add_argument("--interval", default="1d", choices=["1d", "5m", "15m", "60m"])
    parser.add_argument("--market", default="A", choices=["A", "HK"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    run(
        provider=args.provider,
        interval=args.interval,
        market=args.market,
        max_workers=args.workers,
        rate_delay=args.delay,
    )


if __name__ == "__main__":
    main()
