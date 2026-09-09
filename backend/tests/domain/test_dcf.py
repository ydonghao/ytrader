"""DCF 内在价值与安全边际纯函数测试。"""
import datetime as dt

import pytest

from src.domain.market.fundamental.dcf import (
    dcf_intrinsic_value,
    margin_of_safety,
    ttm_fcf,
)


class TestDcfIntrinsicValue:
    def test_manual_single_year(self):
        # N=1, fcf=100, g=0, tg=0, wacc=0.1
        # FCF1=100; PV1=100/1.1=90.909
        # TV=100*(1+0)/(0.1-0)=1000; PV_TV=1000/1.1=909.09
        # total ≈ 1000
        v = dcf_intrinsic_value(100, 0.0, 0.0, 0.1, 1)
        assert v == pytest.approx(1000.0, rel=1e-3)

    def test_basic_positive_growth(self):
        v = dcf_intrinsic_value(100, 0.08, 0.03, 0.09, 10)
        assert v is not None and v > 0
        # 含增长 + 终值，应远大于单期 FCF
        assert v > 1000

    def test_zero_fcf_returns_none(self):
        assert dcf_intrinsic_value(0) is None

    def test_negative_fcf_returns_none(self):
        assert dcf_intrinsic_value(-50) is None

    def test_wacc_equal_terminal_returns_none(self):
        assert dcf_intrinsic_value(100, 0.08, 0.05, 0.05, 10) is None

    def test_wacc_below_terminal_returns_none(self):
        assert dcf_intrinsic_value(100, 0.08, 0.06, 0.05, 10) is None

    def test_higher_wacc_lower_value(self):
        v_low = dcf_intrinsic_value(100, 0.08, 0.03, 0.08, 10)
        v_high = dcf_intrinsic_value(100, 0.08, 0.03, 0.12, 10)
        assert v_low > v_high

    def test_higher_growth_higher_value(self):
        v_low = dcf_intrinsic_value(100, 0.05, 0.03, 0.09, 10)
        v_high = dcf_intrinsic_value(100, 0.12, 0.03, 0.09, 10)
        assert v_high > v_low

    def test_more_years_higher_value(self):
        v_short = dcf_intrinsic_value(100, 0.08, 0.03, 0.09, 5)
        v_long = dcf_intrinsic_value(100, 0.08, 0.03, 0.09, 15)
        assert v_long > v_short

    def test_zero_years_returns_none(self):
        assert dcf_intrinsic_value(100, 0.08, 0.03, 0.09, 0) is None


class TestMarginOfSafety:
    def test_undervalued_positive(self):
        # 内在 1500，市值 1000 → 0.5（低估 50%）
        assert margin_of_safety(1500, 1000) == pytest.approx(0.5)

    def test_overvalued_negative(self):
        # 内在 800，市值 1000 → -0.2（高估 20%）
        assert margin_of_safety(800, 1000) == pytest.approx(-0.2)

    def test_fair_value_zero(self):
        assert margin_of_safety(1000, 1000) == pytest.approx(0.0)

    def test_none_intrinsic(self):
        assert margin_of_safety(None, 1000) is None

    def test_none_market(self):
        assert margin_of_safety(1500, None) is None

    def test_zero_market_none(self):
        assert margin_of_safety(1500, 0) is None


class TestTtmFcf:
    """TTM 差分测试：A 股现金流量表为年初至今累计口径。

    一季报=3个月、中报=6个月、三季报=9个月，直接拿最新一期当
    年度基数会系统性偏差 2~4 倍，须还原成滚动 12 个月。
    """

    @staticmethod
    def _d(s: str) -> dt.date:
        return dt.date.fromisoformat(s)

    def test_latest_is_annual_used_directly(self):
        rows = [
            (self._d("2025-12-31"), 100.0),
            (self._d("2025-09-30"), 80.0),
            (self._d("2025-06-30"), 50.0),
        ]
        assert ttm_fcf(rows) == (100.0, self._d("2025-12-31"), "annual")

    def test_h1_latest_ttm_differencing(self):
        # 茅台真实形状：TTM = FY25 + H1'26 − H1'25
        rows = [
            (self._d("2026-06-30"), 698.586),
            (self._d("2026-03-31"), 263.05),
            (self._d("2025-12-31"), 583.94),
            (self._d("2025-09-30"), 359.14),
            (self._d("2025-06-30"), 115.23),
        ]
        val, base, method = ttm_fcf(rows)
        assert method == "ttm"
        assert base == self._d("2026-06-30")
        assert val == pytest.approx(583.94 + 698.586 - 115.23)

    def test_q1_latest_ttm_differencing(self):
        rows = [
            (self._d("2026-03-31"), 263.05),
            (self._d("2025-12-31"), 583.94),
            (self._d("2025-09-30"), 359.14),
            (self._d("2025-06-30"), 115.23),
            (self._d("2025-03-31"), 79.08),
        ]
        val, _, method = ttm_fcf(rows)
        assert method == "ttm"
        assert val == pytest.approx(583.94 + 263.05 - 79.08)

    def test_unsorted_input(self):
        rows = [
            (self._d("2025-12-31"), 583.94),
            (self._d("2026-06-30"), 698.586),
            (self._d("2025-06-30"), 115.23),
        ]
        val, _, method = ttm_fcf(rows)
        assert method == "ttm"
        assert val == pytest.approx(583.94 + 698.586 - 115.23)

    def test_missing_same_period_falls_back_to_annual(self):
        # 缺去年同期累计 → 退回最近年报（完整年度，宁可旧不可短）
        rows = [
            (self._d("2026-06-30"), 698.586),
            (self._d("2025-12-31"), 583.94),
        ]
        assert ttm_fcf(rows) == (583.94, self._d("2025-12-31"), "annual_fallback")

    def test_no_annual_returns_none(self):
        rows = [
            (self._d("2026-06-30"), 698.586),
            (self._d("2026-03-31"), 263.05),
        ]
        assert ttm_fcf(rows) is None

    def test_empty_returns_none(self):
        assert ttm_fcf([]) is None
