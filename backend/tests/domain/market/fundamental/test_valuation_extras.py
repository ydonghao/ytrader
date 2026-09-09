"""估值补强（PEG/隐含增速/股债性价比）纯函数测试。"""
import pytest

from src.domain.market.fundamental.valuation_extras import (
    peg_ratio,
    implied_growth_from_price,
    equity_bond_parity,
)


class TestPegRatio:
    def test_undervalued(self):
        # PE=20, 增速 30% → PEG=20/30≈0.67 <1
        r = peg_ratio(20, 0.30)
        assert r.peg == pytest.approx(20 / 30)
        assert r.verdict == "undervalued"

    def test_fair(self):
        # PE=20, 增速 15% → PEG≈1.33
        r = peg_ratio(20, 0.15)
        assert r.verdict == "fair"

    def test_expensive(self):
        # PE=50, 增速 10% → PEG=5
        r = peg_ratio(50, 0.10)
        assert r.verdict == "expensive"

    def test_zero_growth_na(self):
        r = peg_ratio(20, 0.0)
        assert r.peg is None
        assert r.verdict == "n/a"

    def test_negative_growth_na(self):
        r = peg_ratio(20, -0.05)
        assert r.verdict == "n/a"

    def test_invalid_pe(self):
        assert peg_ratio(0, 0.2) is None
        assert peg_ratio(None, 0.2) is None


class TestImpliedGrowth:
    def test_deep_value(self):
        # PE=8, r=9% → earnings_yield=12.5% > 9% → implied=-3.5% <0 → deep_value
        r = implied_growth_from_price(8, required_return=0.09)
        assert r.earnings_yield == pytest.approx(0.125)
        assert r.implied_growth < 0
        assert r.verdict == "deep_value"

    def test_reasonable(self):
        # PE=20, r=9% → ey=5%, implied=4%
        r = implied_growth_from_price(20, required_return=0.09)
        assert r.implied_growth == pytest.approx(0.04)
        assert r.verdict == "reasonable"

    def test_stretched(self):
        # PE=100, r=9% → ey=1%, implied=8%? no → 用更低 PE 让 implied>25%
        # implied = r - 1/PE; 要 >0.25 → 1/PE < r-0.25。r=0.09 → 1/PE < -0.16 不可能
        # 所以 stretched 在 r=9% 下不可达；提高 r 到 0.30 测
        r = implied_growth_from_price(50, required_return=0.30)
        # ey=2%, implied=28% >25% → stretched
        assert r.implied_growth == pytest.approx(0.28)
        assert r.verdict == "stretched"

    def test_invalid(self):
        assert implied_growth_from_price(0) is None
        assert implied_growth_from_price(None) is None


class TestEquityBondParity:
    def test_equity_cheap(self):
        # PE=10 → ey=10%, bond=3% → premium 7% >=5%
        r = equity_bond_parity(10, 0.03)
        assert r.risk_premium == pytest.approx(0.07)
        assert r.verdict == "equity_cheap"

    def test_balanced(self):
        # PE=20 → ey=5%, bond=3% → premium 2%
        r = equity_bond_parity(20, 0.03)
        assert r.verdict == "balanced"

    def test_equity_expensive(self):
        # PE=50 → ey=2%, bond=3% → premium -1% <1%
        r = equity_bond_parity(50, 0.03)
        assert r.verdict == "equity_expensive"
        assert r.risk_premium < 0

    def test_invalid(self):
        assert equity_bond_parity(0, 0.03) is None
        assert equity_bond_parity(20, None) is None
