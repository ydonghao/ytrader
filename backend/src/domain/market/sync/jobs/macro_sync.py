"""MacroSyncJob
==============
宏观经济板块数据同步（供调度器 / cron 调用）。

同步内容：
  1. 宏观经济指标时序（CPI/PPI/PMI/M2/社融/LPR + 美国CPI/PMI/失业率/核心PCE）
     → macro_indicator 表（增量 upsert，幂等）
  2. 全球指数日线（道指/纳指/标普 + 恒生/国企）
     → index_ohlcv 表（复用，market 列区分 US_INDEX/HK_INDEX）
  3. 指标元数据 → macro_indicator_meta 表（每次全量刷新，幂等）

注：货币（USDCNY/JPYCNY）与商品（XAU/OIL）已由 quant_daily 同步，
    此处不重复，仅由 macro_view 验证阶段读取。

调用：
  python -m src.domain.market.sync.jobs.macro_sync
"""
import logging
import sys
from pathlib import Path

# 全局 socket 超时兜底，防止 akshare 请求挂死
import socket
socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

from conf import app_config  # noqa: E402
from src.domain.market.sync.providers.akshare_provider import AkshareProvider  # noqa: E402
from src.domain.market.sync.providers.fred_provider import FredProvider  # noqa: E402
from src.domain.market.sync.sync_service import INDEX_INSERT_SQL  # noqa: E402
from src.infra.database.market.macro_indicator import (  # noqa: E402
    create_macro_indicator_repository,
)
from src.infra.database.sql_engine.engine import create_db_connection  # noqa: E402
from src.infra.database.sql_engine.dsn import get_dsn  # noqa: E402

log = logging.getLogger("macro_sync")


def _get_dsn() -> str:
    from src.domain.market.sync.jobs.daily import _get_dsn as _g
    return _g()


def _sync_indicators(
    provider_ak: AkshareProvider, provider_fred: FredProvider, repo
) -> dict:
    """同步宏观经济指标 → macro_indicator 表（增量 upsert）。

    按 config 的 provider 字段分发：fred 走 FredProvider，其余走 AkshareProvider。
    fred 拉空（无 key / 失败）时，若该 code 在 akshare 也有 extractor，则 fallback 到 akshare，
    保证数据流不中断。
    """
    mu = app_config.macro_universe
    stats: dict[str, int] = {}
    for cfg in mu.indicators:
        used_provider = cfg.provider or "akshare"
        try:
            if used_provider == "fred":
                rows = provider_fred.fetch_macro_series(cfg.code)
                if not rows:
                    # FRED 无数据（无 key / 失败）→ 尝试 akshare 兜底
                    rows = provider_ak.fetch_macro_series(cfg.code)
                    if rows:
                        used_provider = "akshare"
                        log.warning(f"[indicator:{cfg.code}] FRED 无数据，已 fallback 到 akshare")
            else:
                rows = provider_ak.fetch_macro_series(cfg.code)
        except Exception as e:
            log.error(f"[indicator:{cfg.code}] 拉取失败: {e}")
            stats[cfg.code] = -1
            continue
        if not rows:
            log.warning(f"[indicator:{cfg.code}] 无数据")
            stats[cfg.code] = 0
            continue
        n = 0
        for report_date, value, freq, unit in rows:
            repo.upsert(
                indicator_code=cfg.code,
                report_date=report_date,
                value=value,
                freq=cfg.freq or freq,
                unit=cfg.unit or unit,
                source=cfg.source or "akshare",
                source_url=cfg.source_url or "",
                provider=used_provider,
            )
            n += 1
        stats[cfg.code] = n
        log.info(f"[indicator:{cfg.code}] +{n} 行（至 {rows[-1][0]}，via {used_provider}）")
    return stats


def _sync_indicator_meta(repo) -> int:
    """刷新指标元数据 → macro_indicator_meta 表（全量幂等）。"""
    mu = app_config.macro_universe
    for i, cfg in enumerate(mu.indicators):
        repo.upsert_meta({
            "code": cfg.code,
            "name": cfg.name,
            "unit": cfg.unit,
            "freq": cfg.freq,
            "category": cfg.category,
            "group": cfg.group,
            "provider": cfg.provider,
            "threshold_high": cfg.threshold_high,
            "threshold_low": cfg.threshold_low,
            "direction": cfg.direction,
            "sort_order": i,
            "description": cfg.description,
            "explanation": cfg.explanation,
            "doc_url": cfg.doc_url,
            "range_low": cfg.range_low,
            "range_high": cfg.range_high,
            "reference_lines": cfg.reference_lines or [],
        })
    log.info(f"[meta] 刷新 {len(mu.indicators)} 条指标元数据")
    return len(mu.indicators)


def _sync_global_indices(provider: AkshareProvider) -> dict:
    """同步全球指数日线 → index_ohlcv 表（market=US_INDEX/HK_INDEX）。

    走 raw SQL（INDEX_INSERT_SQL），与 quant_daily 一致：物理表由
    quant_schema.sql 建成，列名为 trade_date（非 ORM 的 date）。
    market 列由 INSERT 行自带（ON CONFLICT 不覆盖 market，故首写即定）。
    行元组须含末尾 created_at（datetime.now()），匹配 INDEX_INSERT_SQL 的 10 列。
    """
    import psycopg2
    from datetime import datetime
    from psycopg2.extras import execute_values

    mu = app_config.macro_universe
    dsn = _get_dsn()
    now = datetime.now()
    stats: dict[str, int] = {}
    for cfg in mu.global_indices:
        sym = cfg.symbol
        try:
            bars = provider.fetch_global_index_daily(sym)
        except Exception as e:
            log.error(f"[global:{sym}] 拉取失败: {e}")
            stats[sym] = -1
            continue
        if not bars:
            log.warning(f"[global:{sym}] 无数据")
            stats[sym] = 0
            continue
        market = AkshareProvider.global_index_market(sym)
        rows = [
            (sym, b.trade_time, b.open_, b.close_, b.high_, b.low_,
             b.volume, b.amount, market, now)
            for b in bars
        ]
        try:
            with psycopg2.connect(dsn) as conn:
                with conn.cursor() as cur:
                    execute_values(cur, INDEX_INSERT_SQL, rows)
        except Exception as e:
            log.error(f"[global:{sym}] 写入失败: {e}")
            stats[sym] = -1
            continue
        stats[sym] = len(rows)
        log.info(f"[global:{sym}] +{len(rows)} 行（market={market}）")
    return stats


def run() -> dict:
    provider_ak = AkshareProvider()
    provider_fred = FredProvider()
    db = create_db_connection(get_dsn())
    macro_repo = create_macro_indicator_repository(db)

    results: dict = {}
    results["indicators"] = _sync_indicators(provider_ak, provider_fred, macro_repo)
    results["meta"] = _sync_indicator_meta(macro_repo)
    results["global_indices"] = _sync_global_indices(provider_ak)

    total_ind = sum(v for v in results["indicators"].values() if v > 0)
    total_gi = sum(v for v in results["global_indices"].values() if v > 0)
    log.info(f"macro_sync 完成：指标 +{total_ind} 行，全球指数 +{total_gi} 行")
    return results


def main():
    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(_BACKEND / "logs" / "macro_sync.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    run()


if __name__ == "__main__":
    main()
