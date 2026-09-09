"""
IndexBackfillJob
================
A 股指数日线一次性全量回填（新浪源 stock_zh_index_daily，~10 年历史）。

首次部署时运行一次灌入历史；之后由 quant_daily 的 index_daily 段做每日增量保活。

用法：
  python -m src.domain.market.sync.jobs.index_backfill
  python -m src.domain.market.sync.jobs.index_backfill --years 5 --workers 4
"""
import argparse
import logging
import socket
import sys
from pathlib import Path

# 全局 socket 超时兜底，防止 akshare 请求挂死（见 full_sync.py 注释）
socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

from conf import app_config  # noqa: E402
from src.domain.market.sync.jobs.full_sync import (  # noqa: E402
    _build_service, _ensure_schema, _today, _years_ago,
)
from src.domain.market.sync.sync_service import INDEX_INSERT_SQL, SyncResult  # noqa: E402

log = logging.getLogger("index_backfill")


def run(years: int = None, workers: int = 6) -> SyncResult:
    """全量回填所有配置的 A 股指数日线。

    Args:
        years:   回填年数（默认取 quant_universe.daily_years）
        workers: 并发数
    """
    _ensure_schema()
    years = years if years is not None else app_config.quant_universe.daily_years
    svc = _build_service(workers)

    symbols = [i.symbol for i in app_config.quant_universe.indices]
    if not symbols:
        log.warning("quant_universe.indices 为空，无可回填指数")
        return SyncResult(provider="akshare", interval="1d")

    start, end = _years_ago(years), _today()
    log.info(f"[index_backfill] {len(symbols)} 只指数, {start}~{end}")
    return svc.backfill_range(
        symbols=symbols, interval="1d", start_date=start, end_date=end,
        insert_sql=INDEX_INSERT_SQL, is_index=True, mode="full",
    )


def main():
    parser = argparse.ArgumentParser(description="A 股指数日线全量回填")
    parser.add_argument("--years", type=int, default=None,
                        help="回填年数（默认 quant_universe.daily_years）")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                _BACKEND / "logs" / "index_backfill.log", encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )

    r = run(years=args.years, workers=args.workers)
    log.info(
        f"=== index_backfill 完成：{r.done_symbols}/{r.total_symbols} 成功, "
        f"{r.total_rows:,} 行 ==="
    )
    if r.errors:
        for e in r.errors[:10]:
            log.warning(f"    {e}")


if __name__ == "__main__":
    main()
