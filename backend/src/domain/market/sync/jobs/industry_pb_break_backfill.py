# backend/src/domain/market/sync/jobs/industry_pb_break_backfill.py
"""破净率全历史回填(手动,断点续传):逐 stock_valuation 交易日聚合。

用法: cd backend && uv run python -m \
  src.domain.market.sync.jobs.industry_pb_break_backfill [--start 1991-01-01]
"""
import argparse
import datetime as dt
import logging
import socket
import sys
from pathlib import Path

socket.setdefaulttimeout(60)
_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.jobs.industry_pb_break_sync import (  # noqa: E402
    aggregate_one_day,
)
from src.domain.market.sync.progress import ProgressTracker       # noqa: E402
from src.infra.database.market.industry_analysis import (        # noqa: E402
    create_industry_analysis_repository,
)
from src.infra.database.sql_engine.dsn import get_dsn           # noqa: E402

log = logging.getLogger(__name__)
_PROVIDER, _SYMBOL, _INTERVAL = "industry_pb_break", "ALL", "daily"


def plan_dates(dates: list[dt.date], last_done: str | None) -> list[dt.date]:
    """断点续传:last_done 之后的日期(相等也跳过——当日已完成)。"""
    if not last_done:
        return list(dates)
    pivot = dt.date.fromisoformat(last_done)
    return [d for d in dates if d > pivot]


def main(start: str = "1991-01-01", end: str | None = None) -> dict:
    import psycopg2

    repo = create_industry_analysis_repository()
    tracker = ProgressTracker()
    e = dt.date.fromisoformat(end) if end else dt.date.today()
    dates = repo.get_stock_valuation_dates(dt.date.fromisoformat(start), e)
    todo = plan_dates(dates, tracker.get_last_sync(_PROVIDER, _SYMBOL,
                                                   _INTERVAL))
    log.info("[PB_BREAK_BACKFILL] total=%d todo=%d", len(dates), len(todo))
    conn = psycopg2.connect(get_dsn())
    done = 0
    try:
        for d in todo:
            rows = aggregate_one_day(repo, conn, d)
            tracker.mark_done(_PROVIDER, _SYMBOL, _INTERVAL, d.isoformat(),
                              rows)
            tracker.flush()
            done += 1
            if done % 200 == 0:
                log.info("[PB_BREAK_BACKFILL] progress %d/%d", done,
                         len(todo))
    finally:
        conn.close()
        tracker.flush()
    log.info("[PB_BREAK_BACKFILL] finished %d dates", done)
    return {"done": done, "total": len(todo)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="1991-01-01")
    ap.add_argument("--end", default=None)
    a = ap.parse_args()
    print(main(a.start, a.end))
