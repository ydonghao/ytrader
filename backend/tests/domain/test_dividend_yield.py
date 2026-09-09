"""TTM 股息率计算纯函数测试。"""
import datetime as dt

import pytest

from src.domain.market.fundamental.dividend_yield import (
    ttm_dividend_per_share,
    dividend_yield_ttm,
)


def _div(ex_date: str, dps):
    return {
        "ex_date": dt.date.fromisoformat(ex_date),
        "div_per_share": dps,
    }


class TestTtmDividendPerShare:
    def test_sums_within_window(self):
        divs = [_div("2024-03-15", 0.30), _div("2024-09-20", 0.50)]
        as_of = dt.date(2024, 12, 31)
        assert ttm_dividend_per_share(divs, as_of) == pytest.approx(0.80)

    def test_excludes_outside_window(self):
        # 2023-01-10 距 2024-12-31 > 365 天，排除
        divs = [_div("2023-01-10", 0.20), _div("2024-06-01", 0.40)]
        as_of = dt.date(2024, 12, 31)
        assert ttm_dividend_per_share(divs, as_of) == pytest.approx(0.40)

    def test_excludes_future(self):
        divs = [_div("2025-06-01", 0.40)]
        as_of = dt.date(2024, 12, 31)
        assert ttm_dividend_per_share(divs, as_of) is None

    def test_ex_date_equal_as_of_included(self):
        divs = [_div("2024-12-31", 0.50)]
        as_of = dt.date(2024, 12, 31)
        assert ttm_dividend_per_share(divs, as_of) == pytest.approx(0.50)

    def test_none_div_per_share_skipped(self):
        divs = [_div("2024-06-01", None), _div("2024-09-01", 0.30)]
        as_of = dt.date(2024, 12, 31)
        assert ttm_dividend_per_share(divs, as_of) == pytest.approx(0.30)

    def test_empty_returns_none(self):
        assert ttm_dividend_per_share([], dt.date(2024, 1, 1)) is None

    def test_all_outside_returns_none(self):
        divs = [_div("2010-01-01", 0.10)]
        assert ttm_dividend_per_share(divs, dt.date(2024, 1, 1)) is None


class TestDividendYieldTtm:
    def test_basic(self):
        divs = [_div("2024-06-01", 0.50)]
        as_of = dt.date(2024, 12, 31)
        # 0.50 / 10.0 * 100 = 5.0%
        assert dividend_yield_ttm(divs, 10.0, as_of) == pytest.approx(5.0)

    def test_two_dividends(self):
        divs = [_div("2024-04-01", 0.25), _div("2024-10-01", 0.35)]
        as_of = dt.date(2024, 12, 31)
        # 0.60 / 12.0 * 100 = 5.0%
        assert dividend_yield_ttm(divs, 12.0, as_of) == pytest.approx(5.0)

    def test_zero_price_returns_none(self):
        divs = [_div("2024-06-01", 0.50)]
        assert dividend_yield_ttm(divs, 0.0, dt.date(2024, 12, 31)) is None

    def test_negative_price_returns_none(self):
        divs = [_div("2024-06-01", 0.50)]
        assert dividend_yield_ttm(divs, -1.0, dt.date(2024, 12, 31)) is None

    def test_no_dividend_returns_none(self):
        divs = [_div("2010-01-01", 0.50)]  # 窗口外
        assert dividend_yield_ttm(divs, 10.0, dt.date(2024, 12, 31)) is None
