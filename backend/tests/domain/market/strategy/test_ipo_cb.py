"""簇 5 打新/可转债纯函数测试。"""
import pytest

from src.domain.market.strategy.ipo_cb import (
    ipo_lot_allocation,
    ipo_win_probability,
    cb_conversion_premium,
    cb_clause_warnings,
)


class TestIpoLotAllocation:
    def test_sh_market(self):
        # 沪市：25万市值 → 25 单位 × 1000 = 25000 股
        r = ipo_lot_allocation(250_000, "sh")
        assert r.units == 25
        assert r.max_shares == 25_000

    def test_sz_market(self):
        # 深市：3万市值 → 6 单位 × 500 = 3000 股
        r = ipo_lot_allocation(30_000, "sz")
        assert r.units == 6
        assert r.max_shares == 3000

    def test_below_threshold(self):
        assert ipo_lot_allocation(5_000, "sh").units == 0

    def test_unknown_market(self):
        assert ipo_lot_allocation(100_000, "hk") is None

    def test_zero(self):
        assert ipo_lot_allocation(0, "sh") is None


class TestIpoWinProbability:
    def test_basic(self):
        # p=0.01, N=20 → 1-(0.99)^20 ≈ 0.1821
        r = ipo_win_probability(0.01, 20)
        assert r == pytest.approx(1 - 0.99 ** 20, rel=1e-6)

    def test_one_unit(self):
        assert ipo_win_probability(0.05, 1) == pytest.approx(0.05)

    def test_certain_prob(self):
        assert ipo_win_probability(1.0, 5) == 1.0

    def test_zero_units(self):
        assert ipo_win_probability(0.01, 0) is None

    def test_invalid_prob(self):
        assert ipo_win_probability(1.5, 5) is None
        assert ipo_win_probability(-0.1, 5) is None


class TestCbConversionPremium:
    def test_fair(self):
        # 正股10, 转股价10, cb价105 → 转股价值100, 溢价5% → fair
        r = cb_conversion_premium(stock_price=10, conv_price=10, cb_price=105)
        assert r.conversion_value == pytest.approx(100)
        assert r.premium == pytest.approx(0.05)
        assert r.verdict == "fair"

    def test_discount(self):
        # 正股12, 转股价10, cb价110 → 转股价值120, 溢价=110/120-1≈-0.083 → discount
        r = cb_conversion_premium(12, 10, 110)
        assert r.premium < 0
        assert r.verdict == "discount"

    def test_expensive(self):
        # 正股8, 转股价10, cb价115 → 转股价值80, 溢价=115/80-1≈0.4375 → expensive
        r = cb_conversion_premium(8, 10, 115)
        assert r.verdict == "expensive"

    def test_invalid(self):
        assert cb_conversion_premium(0, 10, 100) is None
        assert cb_conversion_premium(10, 0, 100) is None
        assert cb_conversion_premium(10, 10, 0) is None


class TestCbClauseWarnings:
    def test_downward_and_putback_triggered(self):
        # 正股7, 转股价10 → ratio 0.70 → 下修(≤0.85) + 回售(≤0.70)
        r = cb_clause_warnings(stock_price=7, conv_price=10)
        assert r.ratio == pytest.approx(0.70)
        assert r.downward_revision is True
        assert r.put_back is True
        assert r.forced_redemption is False
        assert len(r.warnings) == 2

    def test_forced_redemption_triggered(self):
        # 正股14, 转股价10 → ratio 1.40 ≥ 1.30
        r = cb_clause_warnings(14, 10)
        assert r.forced_redemption is True
        assert r.downward_revision is False
        assert len(r.warnings) == 1

    def test_no_trigger(self):
        # 正股10, 转股价10 → ratio 1.0
        r = cb_clause_warnings(10, 10)
        assert r.downward_revision is False
        assert r.forced_redemption is False
        assert r.put_back is False
        assert r.warnings == []

    def test_invalid(self):
        assert cb_clause_warnings(0, 10) is None
        assert cb_clause_warnings(10, 0) is None
