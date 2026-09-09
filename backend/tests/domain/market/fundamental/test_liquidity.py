"""流动性比率纯函数测试。"""
import pytest

from src.domain.market.fundamental.liquidity import (
    current_ratio,
    quick_ratio,
    cash_ratio,
    working_capital,
    compute_liquidity,
)


class TestCurrentRatio:
    def test_basic(self):
        assert current_ratio(300, 200) == pytest.approx(1.5)

    def test_zero_liab(self):
        assert current_ratio(300, 0) is None


class TestQuickRatio:
    def test_basic(self):
        # (300-100)/200 = 1.0
        assert quick_ratio(300, 100, 200) == pytest.approx(1.0)

    def test_missing_inventory(self):
        assert quick_ratio(300, None, 200) is None


class TestCashRatio:
    def test_basic(self):
        # (50+20)/200 = 0.35
        assert cash_ratio(50, 20, 200) == pytest.approx(0.35)

    def test_optional_assets(self):
        # 交易性金融资产 None 按 0
        assert cash_ratio(50, None, 200) == pytest.approx(0.25)


class TestWorkingCapital:
    def test_positive(self):
        assert working_capital(300, 200) == 100

    def test_negative(self):
        assert working_capital(150, 200) == -50


class TestComputeLiquidity:
    def test_strong(self):
        r = compute_liquidity(500, 200, inventory=100, monetary_funds=150, trading_financial_assets=50)
        assert r.current_ratio == pytest.approx(2.5)
        assert r.verdict == "strong"
        assert r.quick_ratio == pytest.approx(2.0)
        assert r.working_capital == 300

    def test_healthy(self):
        # current 1.6, quick 0.9
        r = compute_liquidity(320, 200, inventory=140)
        assert r.verdict == "healthy"

    def test_stretched(self):
        # current 1.1
        r = compute_liquidity(220, 200, inventory=50)
        assert r.verdict == "stretched"

    def test_risky(self):
        # current 0.8
        r = compute_liquidity(160, 200, inventory=40)
        assert r.verdict == "risky"

    def test_quick_ratio_override_to_strong(self):
        # current 1.8 但 quick 1.6 → strong
        r = compute_liquidity(360, 200, inventory=40)
        assert r.quick_ratio == pytest.approx(1.6)
        assert r.verdict == "strong"

    def test_missing_data(self):
        r = compute_liquidity(None, 200)
        assert r.current_ratio is None
        assert r.verdict == "risky"
