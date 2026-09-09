"""ShareholderCountSyncJob — 全市场股东户数同步（筹码集中度）。

逐标的拉股东户数时序（ak.stock_zh_a_gdhs_detail_em）→ stock_shareholder_count。
供 equity.concentration 筹码集中度分析。

用法:
  python -m src.domain.market.sync.jobs.shareholder_count_sync --symbols sh600519,sz000001
  python -m src.domain.market.sync.jobs.shareholder_count_sync   # 全市场
"""
import argparse
import logging
import sys
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.providers.akshare_provider import AkshareProvider  # noqa: E402
from src.infra.database.market.shareholder_count import (  # noqa: E402
    create_shareholder_count_repository,
)

log = logging.getLogger("shareholder_count_sync")


def _sync_one(provider: AkshareProvider, repo, symbol: str) -> int:
    try:
        rows = provider.fetch_shareholder_count(symbol)
        if not rows:
            return 0
        return repo.bulk_upsert([{**r, "symbol": symbol} for r in rows])
    except Exception as e:  # noqa: BLE001
        log.warning(f"[shareholder_count] {symbol} 异常: {e}")
        return 0


def run(symbols: list[str] = None, workers: int = 6) -> dict:
    """同步股东户数。symbols 为空则取全 A 股。"""
    provider = AkshareProvider()
    repo = create_shareholder_count_repository()
    if not symbols:
        from src.domain.market.strategy.longterm.data_loader import (
            fetch_universe_symbols,
        )
        symbols = fetch_universe_symbols()
    log.info(f"待同步股东户数: {len(symbols)} 只")

    total = written = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_sync_one, provider, repo, s): s for s in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                n = fut.result()
                total += 1
                written += n
                if n == 0:
                    failed += 1
            except Exception as e:  # noqa: BLE001
                total += 1
                failed += 1
                log.warning(f"{sym} 失败: {e}")
    return {
        "total": total, "written_rows": written, "no_data": failed,
        "synced_at": dt.datetime.now().isoformat(),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="逗号分隔；空=全市场")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
    print(run(symbols=syms, workers=args.workers))
