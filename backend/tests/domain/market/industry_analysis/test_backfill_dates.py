# backend/tests/domain/market/industry_analysis/test_backfill_dates.py
"""回填日期规划纯函数。"""
import datetime as dt

from src.domain.market.sync.jobs.industry_pb_break_backfill import (
    plan_dates,
)
from src.domain.market.sync.jobs.industry_prosperity_backfill import (
    month_end_dates,
)


def test_plan_dates_resume_from_last():
    dates = [dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)]
    # 断点在 2026-01-02 → 只剩 01-03
    assert plan_dates(dates, last_done="2026-01-02") == [dt.date(2026, 1, 3)]
    assert plan_dates(dates, last_done=None) == dates


def test_plan_dates_tolerates_gap():
    dates = [dt.date(2026, 1, 1), dt.date(2026, 1, 5)]
    assert plan_dates(dates, last_done="2026-01-01") == [dt.date(2026, 1, 5)]


def test_month_end_dates():
    ds = month_end_dates(dt.date(2025, 11, 15), dt.date(2026, 2, 20))
    assert ds == [dt.date(2025, 11, 30), dt.date(2025, 12, 31),
                  dt.date(2026, 1, 31)]
