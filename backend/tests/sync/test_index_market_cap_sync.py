"""指数市值回填 job 纯函数测试。"""
import datetime as dt
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.sync.jobs.index_market_cap_sync import (
    _filter_covered,
    _monthly_mv_sum,
)


def test_monthly_mv_sum_accumulates_and_counts():
    rows = {
        "sh600519": [
            SimpleNamespace(trade_date=dt.date(2024, 1, 31), total_mv=2.0e12),
            SimpleNamespace(trade_date=dt.date(2024, 2, 29), total_mv=2.1e12),
        ],
        "sz000001": [
            SimpleNamespace(trade_date=dt.date(2024, 1, 31), total_mv=3.0e11),
            SimpleNamespace(trade_date=dt.date(2024, 2, 29), total_mv=None),
        ],
    }
    out = _monthly_mv_sum(rows)
    assert [p["date"] for p in out] == [
        dt.date(2024, 1, 31), dt.date(2024, 2, 29),
    ]
    assert out[0]["total_mv"] == 2.3e12
    assert out[1]["total_mv"] == 2.1e12   # None 跳过
    assert out[0]["count"] == 2           # 两只当月都有值
    assert out[1]["count"] == 1           # None 不计入贡献


def test_filter_covered_drops_low_coverage():
    """覆盖率 <80% 的月度点剔除——早期成分股估值覆盖不足时不写假市值。"""
    monthly = [
        {"date": dt.date(2024, 1, 31), "total_mv": 1.0e14, "count": 60},
        {"date": dt.date(2024, 2, 29), "total_mv": 1.1e14, "count": 79},
        {"date": dt.date(2024, 3, 29), "total_mv": 1.2e14, "count": 80},
        {"date": dt.date(2024, 4, 30), "total_mv": 1.3e14, "count": 300},
    ]
    out = _filter_covered(monthly, n_symbols=100, min_ratio=0.8)
    # 60/100=0.6 与 79/100=0.79 丢弃；80/100=0.80 恰好达标保留（>=）
    assert [p["date"].month for p in out] == [3, 4]


def test_filter_covered_zero_symbols_safe():
    assert _filter_covered([], n_symbols=0, min_ratio=0.8) == []
    assert _filter_covered(
        [{"date": dt.date(2024, 1, 31), "total_mv": 1.0, "count": 1}],
        n_symbols=0, min_ratio=0.8,
    ) == []   # 除零守卫：无成分则全丢
