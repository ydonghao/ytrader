"""index_pe 纯函数单测（手算锁定，模式同 test_market_cap_growth.py）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.domain.market.fundamental.index_pe import (
    compute_index_pe,
    gate_by_sample_count,
    mean_std,
)


def _cum(rd, np_, cnt):
    return {"report_date": rd, "net_profit": np_, "sample_count": cnt}


# ── gate_by_sample_count ────────────────────────────────────────────

def test_gate_hides_partial_disclosure():
    rows = [
        _cum("2025-12-31", 6.0, 300),
        _cum("2026-03-31", 1.4, 300),
        _cum("2026-06-30", 0.5, 34),   # 中报仅 34/300 披露
    ]
    out = gate_by_sample_count(rows)
    assert out[2]["net_profit"] is None
    assert out[0]["net_profit"] == 6.0


def test_gate_boundary_80pct_kept():
    rows = [
        _cum("2025-12-31", 6.0, 300),
        _cum("2026-06-30", 2.5, 240),  # 恰好 80% → 保留
    ]
    assert gate_by_sample_count(rows)[1]["net_profit"] == 2.5


# ── compute_index_pe ────────────────────────────────────────────────

# 累计净利（亿）：FY2022=6.0、2022Q1=0.9、2023Q1=1.0、FY2023=7.0、2024Q1=1.4
# TTM：2023Q1=6.0+1.0−0.9=6.1；FY2023=7.0；2024Q1=7.0+1.4−1.0=7.4
CUM = [
    _cum("2022-03-31", 0.9, 300),
    _cum("2022-12-31", 6.0, 300),
    _cum("2023-03-31", 1.0, 300),
    _cum("2023-12-31", 7.0, 300),
    _cum("2024-03-31", 1.4, 300),
]


def test_compute_pe_ttm_and_align():
    monthly = [
        {"date": "2022-02-28", "total_mv": 6000.0},  # 早于首报告期 → None
        {"date": "2023-04-28", "total_mv": 6100.0},  # 2023Q1 TTM 6.1 → 1000
        {"date": "2024-02-28", "total_mv": 7000.0},  # FY2023 7.0 → 1000
        {"date": "2024-04-30", "total_mv": 7400.0},  # 2024Q1 TTM 7.4 → 1000
    ]
    out = compute_index_pe(monthly, CUM)
    assert [p["pe"] for p in out] == [None, 1000.0, 1000.0, 1000.0]
    assert out[0]["date"] == "2022-02-28"


def test_compute_pe_disclosure_gap_breaks_line():
    cum = [
        _cum("2025-03-31", 1.0, 300),
        _cum("2025-06-30", 2.0, 300),
        _cum("2025-12-31", 6.0, 300),
        _cum("2026-03-31", 1.4, 300),
        _cum("2026-06-30", 0.5, 34),   # 门控：若无门控 TTM=6.0+0.5−2.0=4.5
    ]
    monthly = [
        {"date": "2026-05-31", "total_mv": 6400.0},  # 2026Q1 TTM=6.0+1.4−1.0=6.4
        {"date": "2026-07-31", "total_mv": 4500.0},  # 2026中报被门控 → 断线
    ]
    out = compute_index_pe(monthly, cum)
    assert out[0]["pe"] == 1000.0
    assert out[1]["pe"] is None


def test_compute_pe_nonpositive_profit_none():
    cum = [_cum("2023-12-31", -2.0, 300)]   # 年报 TTM=全年=−2.0（亏损）
    out = compute_index_pe([{"date": "2024-02-28", "total_mv": 5000.0}], cum)
    assert out[0]["pe"] is None


# ── mean_std ────────────────────────────────────────────────────────

def test_mean_std():
    ms = mean_std([1, 2, 3])
    assert ms["mean"] == 2.0
    assert abs(ms["std"] - 0.816496580927726) < 1e-9   # pstdev([1,2,3])=√(2/3)
    assert ms["sample_size"] == 3
    assert mean_std([1]) is None
    assert mean_std([1, None, "x", 3])["sample_size"] == 2
