"""stock_percentile_batch 批量分位服务测试。"""
import sys
import os
import datetime as dt
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from src.domain.market.fundamental.percentile_batch import stock_percentile_batch


def _make_val_rows(symbol, pb_base=1.0):
    """造 40 个月的估值行（>= SAMPLE_MIN=30）。"""
    rows = []
    for i in range(40):
        d = dt.date(2021, 1, 1) + dt.timedelta(days=i * 30)
        rows.append(type("R", (), {
            "symbol": symbol, "trade_date": d,
            "pb": pb_base + i * 0.1, "pe_ttm": 10.0 + i * 0.5,
            "pe": None, "ps": None, "ps_ttm": None,
            "dv_ratio": None, "dv_ttm": None, "total_mv": None,
        })())
    return rows


class TestStockPercentileBatch:
    def test_pb_metric_basic(self):
        """PB 模式：返回 percentile/sample_size/current。"""
        rows_map = {"A": _make_val_rows("A", pb_base=1.0)}
        with patch(
            "src.domain.market.fundamental.percentile_batch.create_stock_valuation_repository"
        ) as mock_repo_fn:
            mock_repo = mock_repo_fn.return_value
            mock_repo.get_range_batch.return_value = rows_map
            result = stock_percentile_batch(
                ["A"], metric="pb", window="10y",
                as_of=dt.date(2024, 5, 1),
            )
        assert "A" in result
        info = result["A"]
        assert info["percentile"] is not None
        assert 0.0 <= info["percentile"] <= 1.0
        assert info["sample_size"] >= 30
        assert info["current"] is not None

    def test_pb_pe_composite_averages(self):
        """pb_pe 模式：percentile = (pb_pct + pe_pct)/2。"""
        rows_map = {"A": _make_val_rows("A")}
        with patch(
            "src.domain.market.fundamental.percentile_batch.create_stock_valuation_repository"
        ) as mock_repo_fn:
            mock_repo = mock_repo_fn.return_value
            mock_repo.get_range_batch.return_value = rows_map
            result = stock_percentile_batch(
                ["A"], metric="pb_pe", window="10y",
                as_of=dt.date(2024, 5, 1),
            )
        info = result["A"]
        assert info["pb_percentile"] is not None
        assert info["pe_percentile"] is not None
        expected = (info["pb_percentile"] + info["pe_percentile"]) / 2
        assert info["percentile"] == pytest.approx(expected, abs=0.01)

    def test_insufficient_samples_skipped(self):
        """样本 <30 的股票不出现结果里。"""
        short_rows = _make_val_rows("B")[:10]  # 只有 10 条
        rows_map = {"A": _make_val_rows("A"), "B": short_rows}
        with patch(
            "src.domain.market.fundamental.percentile_batch.create_stock_valuation_repository"
        ) as mock_repo_fn:
            mock_repo = mock_repo_fn.return_value
            mock_repo.get_range_batch.return_value = rows_map
            result = stock_percentile_batch(
                ["A", "B"], metric="pb", window="10y",
                as_of=dt.date(2024, 5, 1),
            )
        assert "A" in result
        assert "B" not in result

    def test_exclude_ranges_passed_through(self):
        """exclude_ranges 透传给 get_range_batch。"""
        rows_map = {"A": _make_val_rows("A")}
        excludes = [(dt.date(2022, 1, 1), dt.date(2022, 6, 30))]
        with patch(
            "src.domain.market.fundamental.percentile_batch.create_stock_valuation_repository"
        ) as mock_repo_fn:
            mock_repo = mock_repo_fn.return_value
            mock_repo.get_range_batch.return_value = rows_map
            stock_percentile_batch(
                ["A"], metric="pb", window="10y",
                as_of=dt.date(2024, 5, 1), exclude_ranges=excludes,
            )
            call_kwargs = mock_repo.get_range_batch.call_args
            assert call_kwargs[1]["exclude_ranges"] == excludes or \
                   call_kwargs[1].get("exclude_ranges") == excludes
