# backend/src/domain/market/sync/jobs/industry_prosperity_backfill.py
"""景气分历史回填(手动):月末采样(规格§3.3——历史月末点+上线后逐日)。

用法: cd backend && uv run python -m \
  src.domain.market.sync.jobs.industry_prosperity_backfill [--start 2018-01-01]
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

from src.domain.market.sync.jobs.industry_prosperity_sync import run  # noqa: E402

log = logging.getLogger(__name__)


def month_end_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    """区间内各月末(不含 end 所在月未满月)。"""
    out: list[dt.date] = []
    y, m = start.year, start.month
    while True:
        nxt = dt.date(y + (m // 12), m % 12 + 1, 1) - dt.timedelta(days=1)
        if nxt > end:
            break
        if nxt >= start:
            out.append(nxt)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def main(start: str = "2018-01-01") -> dict:
    s = dt.date.fromisoformat(start)
    dates = month_end_dates(s, dt.date.today())
    log.info("[PROSPERITY_BACKFILL] %d month-ends from %s", len(dates), s)
    ok = 0
    for d in dates:
        try:
            r = run(trade_date=d)
            ok += 1 if r.get("rows") else 0
        except Exception as e:  # noqa: BLE001
            log.error("[PROSPERITY_BACKFILL] %s failed: %s", d, e)
    return {"done": ok, "total": len(dates)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    print(main(ap.parse_args().start))
