"""
DailyJob
========
每日增量同步任务（供 cron 调用）。

功能：
  - 每日定时运行（如每天 16:00 收盘后）
  - 只拉取自上次同步以来新增的数据
  - 全市场股票（A股 + H股）
  - 自动判断数据源（优先 Tencent，无限速）

使用（crontab 示例）：
  0 16 * * 1-5 cd /path/to/backend && python -m src.domain.market.sync.jobs.daily >> logs/daily_sync.log 2>&1
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync import ProgressTracker, SyncService
from src.domain.market.sync.providers import SinaProvider, TencentProvider
from src.domain.market.sync.sync_provider import SyncProvider
from src.domain.market.sync.sync_service import SyncConfig, SyncResult

log = logging.getLogger("daily_sync")


def _build_provider(name: str) -> SyncProvider:
    if name == "sina":
        return SinaProvider(rate_delay=1.0)
    elif name == "tencent":
        return TencentProvider(rate_delay=0.05)
    else:
        raise ValueError(f"Unknown provider: {name}")


def _get_dsn() -> str:
    # 优先读环境变量（兼容旧部署），否则用中央配置
    dsn = os.environ.get("TIMESCALE_DSN")
    if dsn:
        return dsn
    from src.infra.database.sql_engine.dsn import get_dsn as _get_dsn_central
    return _get_dsn_central()


def sync_market(
    provider: str,
    market: str,
    interval: str,
    max_workers: int,
    rate_delay: float,
) -> SyncResult:
    """同步指定市场和周期"""
    prov = _build_provider(provider)
    tracker = ProgressTracker()
    config = SyncConfig(
        max_workers=max_workers,
        rate_delay=rate_delay,
        db_dsn=_get_dsn(),
    )
    service = SyncService(prov, tracker, config)

    # 获取全量股票列表（用于发现新股）
    all_symbols = prov.get_stock_list(market=market)
    log.info(f"[{provider}/{interval}/{market}] 股票列表: {len(all_symbols)}")

    if not all_symbols:
        log.warning(f"[{provider}/{interval}/{market}] 股票列表为空，跳过")
        return SyncResult(provider=provider, interval=interval, mode="incremental")

    result = service.backfill(
        symbols=all_symbols,
        interval=interval,
        mode="incremental",
    )

    log.info(
        f"[{provider}/{interval}/{market}] 完成: "
        f"+{result.total_rows:,} 行, {result.done_symbols}/{result.total_symbols} 成功"
    )
    return result


def run(
    markets: list[str] = None,
    providers: list[str] = None,
    intervals: list[str] = None,
    max_workers: int = 4,
    sina_delay: float = 1.0,
    tencent_delay: float = 0.05,
) -> dict[str, SyncResult]:
    """
    执行每日增量同步

    Args:
        markets:    市场列表，默认 ["A", "HK"]
        providers:  数据源列表，默认 ["tencent"]（Sina 有日配额限制）
        intervals:  K线周期，默认 ["1d"]
        max_workers: 并发数
        sina_delay:    Sina 请求间隔（秒）
        tencent_delay: Tencent 请求间隔（秒）
    """
    markets = markets or ["A", "HK"]
    providers = providers or ["tencent"]
    intervals = intervals or ["1d"]

    log.info(f"=== DailySync {datetime.now():%Y-%m-%d %H:%M} ===")
    log.info(f"  markets={markets}, providers={providers}, intervals={intervals}")

    results = {}
    for provider in providers:
        delay = sina_delay if provider == "sina" else tencent_delay
        for market in markets:
            for interval in intervals:
                key = f"{provider}:{market}:{interval}"
                try:
                    result = sync_market(
                        provider=provider,
                        market=market,
                        interval=interval,
                        max_workers=max_workers,
                        rate_delay=delay,
                    )
                    results[key] = result
                except Exception as e:
                    log.error(f"[{key}] 同步失败: {e}", exc_info=True)
                    results[key] = SyncResult(
                        provider=provider, interval=interval, mode="incremental"
                    )

    # 汇总
    total_rows = sum(r.total_rows for r in results.values())
    total_done = sum(r.done_symbols for r in results.values())
    total_failed = sum(r.failed_symbols for r in results.values())

    log.info(f"=== DailySync 完成 ===")
    log.info(f"  总写入: {total_rows:,} 行")
    log.info(f"  成功: {total_done}, 失败: {total_failed}")

    for key, result in results.items():
        if result.errors:
            for err in result.errors[:3]:
                log.warning(f"  [{key}] {err}")

    return results


def main():
    parser = argparse.ArgumentParser(description="每日增量同步")
    parser.add_argument("--provider", default="tencent", choices=["sina", "tencent"])
    parser.add_argument("--market", default="A", choices=["A", "HK"])
    parser.add_argument("--interval", default="1d", choices=["1d", "5m", "15m", "60m"])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sina-delay", type=float, default=1.0)
    parser.add_argument("--tencent-delay", type=float, default=0.05)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                Path(__file__).parent.parent.parent.parent.parent
                / "logs" / "daily_sync.log",
                encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )

    # 确保 logs 目录存在
    logs_dir = Path(__file__).parent.parent.parent.parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    run(
        markets=[args.market],
        providers=[args.provider],
        intervals=[args.interval],
        max_workers=args.workers,
        sina_delay=args.sina_delay,
        tencent_delay=args.tencent_delay,
    )


if __name__ == "__main__":
    main()
