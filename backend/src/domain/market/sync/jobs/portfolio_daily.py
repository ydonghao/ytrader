"""
Portfolio Daily Sync
===================
配置组合篮子每日同步（供 cron 调用）。

标的清单来源(优先级):
  1. portfolio_instrument 表 (WHERE enabled=true) — 用户 UI 管理的标的池
  2. 回退 config.yaml portfolio_universe.bars     — DB 表为空时(向后兼容)

汇率同步:
  遍历活跃组合涉及的所有币种(从标的池推导), 同步对应 CNY 汇率。
  默认始终同步 USDCNY/HKDCNY。

  - 标的 → stock_ohlcv（首拉 full / 增量 incremental）
  - 汇率 → fx_rate（基于表内最大日期增量）

crontab 示例（工作日 16:30 收盘后）:
  30 16 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_daily >> logs/portfolio_sync.log 2>&1
"""
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from conf import app_config
from src.domain.market.sync import ProgressTracker, SyncService
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.domain.market.sync.sync_service import SyncConfig, SyncResult
from src.infra.database.market.fx_rate import create_fx_rate_repository

PROVIDER_NAME = "akshare"

log = logging.getLogger("portfolio_sync")


def _build_provider() -> AkshareProvider:
    return AkshareProvider()


def _build_tracker() -> ProgressTracker:
    return ProgressTracker()


def _build_service(
    provider: AkshareProvider, tracker: ProgressTracker
) -> SyncService:
    from src.domain.market.sync.jobs.daily import _get_dsn
    return SyncService(provider, tracker, SyncConfig(db_dsn=_get_dsn()))


def _load_instruments() -> list:
    """加载标的清单。

    优先从 portfolio_instrument 表读(DB 管理), 表空时回退 config.yaml
    (向后兼容, 保证首次部署 DB 未 seed 时仍可同步)。
    返回具有 .symbol / .market / .ccy / .name / .asset 属性的对象列表。
    """
    try:
        from src.infra.database.portfolio.repository import (
            create_portfolio_repository,
        )
        repo = create_portfolio_repository()
        insts = repo.list_instruments(enabled_only=True)
        if insts:
            log.info(
                f"从 DB 加载 {len(insts)} 个标的"
            )
            return insts
        log.warning(
            "portfolio_instrument 表为空, 回退 config.yaml"
        )
    except Exception as e:
        log.warning(
            f"读取 portfolio_instrument 表失败({e}), 回退 config.yaml"
        )
    return app_config.portfolio_universe.bars


def _collect_fx_pairs(instruments: list) -> set[str]:
    """从标的清单推导需同步的汇率 pair。

    所有非 CNY 币种 → {ccy}CNY。始终包含 USDCNY/HKDCNY。
    """
    pairs = {"USDCNY"}
    for inst in instruments:
        ccy = getattr(inst, "ccy", None)
        if ccy and ccy != "CNY":
            pairs.add(f"{ccy}CNY")
    return pairs


def run() -> None:
    provider = _build_provider()
    tracker = _build_tracker()
    service = _build_service(provider, tracker)

    instruments = _load_instruments()
    for item in instruments:
        last = tracker.get_last_sync(PROVIDER_NAME, item.symbol, "1d")
        mode = "incremental" if last is not None else "full"
        result = service.backfill(
            symbols=[item.symbol], interval="1d", mode=mode
        )
        log.info(
            f"[{item.symbol}] {mode}: "
            f"done={result.done_symbols} "
            f"failed={result.failed_symbols} "
            f"rows={result.total_rows}"
        )

    # 汇率: 从标的清单推导所有需要的 pair
    fx_pairs = _collect_fx_pairs(instruments)
    for pair in fx_pairs:
        sync_fx(pair)
    log.info(
        f"portfolio sync complete, fx pairs: {sorted(fx_pairs)}"
    )


def sync_fx(pair: str = "USDCNY") -> None:
    """同步单个汇率 pair(增量: 基于表内最大日期)。"""
    provider = _build_provider()
    repo = create_fx_rate_repository()
    latest = repo.get_latest_date(pair)
    rows = provider.fetch_fx_daily(pair)
    for d, rate in rows:
        if latest and d <= latest:
            continue
        repo.upsert(d, pair, rate)


if __name__ == "__main__":
    run()
