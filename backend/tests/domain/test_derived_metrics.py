"""价值投资衍生指标纯函数测试。"""
import pytest

from src.domain.market.fundamental.derived_metrics import (
    interest_bearing_debt,
    invested_capital,
    ev,
    roic,
    earnings_yield,
    fcf_yield,
    roa,
    compute_value_metrics,
)


class TestInterestBearingDebt:
    def test_both_loans(self):
        assert interest_bearing_debt(
            {"short_loan": 100, "long_loan": 200}
        ) == 300

    def test_one_missing(self):
        assert interest_bearing_debt({"short_loan": 100}) == 100
        assert interest_bearing_debt({"long_loan": 200}) == 200

    def test_both_missing(self):
        assert interest_bearing_debt({}) is None


class TestInvestedCapital:
    def test_equity_plus_debt(self):
        assert invested_capital(
            {"equity": 500, "short_loan": 100, "long_loan": 200}
        ) == 800

    def test_equity_only(self):
        assert invested_capital({"equity": 500}) == 500


class TestEv:
    def test_mv_plus_debt_minus_cash(self):
        fin = {"short_loan": 100, "long_loan": 200, "monetary_funds": 50}
        val = {"total_mv": 1000}
        assert ev(fin, val) == 1250  # 1000 + 300 - 50

    def test_mv_only(self):
        assert ev({}, {"total_mv": 1000}) == 1000


class TestRoic:
    def test_basic(self):
        fin = {
            "operating_profit": 80,
            "equity": 500,
            "short_loan": 100,
            "long_loan": 200,
        }
        # EBIT=80, IC=800, ROIC=10%
        assert roic(fin) == pytest.approx(10.0)

    def test_zero_capital_returns_none(self):
        assert roic({"operating_profit": 80, "equity": 0}) is None


class TestEarningsYield:
    def test_basic(self):
        fin = {
            "operating_profit": 100,
            "short_loan": 100,
            "long_loan": 100,
            "monetary_funds": 50,
        }
        val = {"total_mv": 850}
        # EV = 850 + 200 - 50 = 1000; 100/1000 = 10%
        assert earnings_yield(fin, val) == pytest.approx(10.0)

    def test_zero_ev_returns_none(self):
        assert earnings_yield(
            {"operating_profit": 100}, {"total_mv": 0}
        ) is None


class TestFcfYield:
    def test_basic(self):
        fin = {"free_cash_flow": 50, "monetary_funds": 0}
        val = {"total_mv": 1000}
        # EV=1000; 50/1000 = 5%
        assert fcf_yield(fin, val) == pytest.approx(5.0)


class TestRoa:
    def test_basic(self):
        assert roa(
            {"net_profit": 50, "total_assets": 1000}
        ) == pytest.approx(5.0)


class TestComputeValueMetrics:
    def test_returns_all(self):
        fin = {
            "operating_profit": 100,
            "equity": 500,
            "short_loan": 100,
            "long_loan": 200,
            "monetary_funds": 50,
            "net_profit": 60,
            "total_assets": 1000,
            "free_cash_flow": 40,
        }
        val = {"total_mv": 850}
        m = compute_value_metrics(fin, val)
        # IC = 500 + 300 = 800; ROIC = 100/800 = 12.5%
        assert m["roic"] == pytest.approx(12.5)
        # EV = 850 + 300 - 50 = 1100
        assert m["ev"] == 1100
        # EBIT yield = 100/1100 ≈ 9.09%
        assert m["earnings_yield"] == pytest.approx(9.0909)
        # ROA = 60/1000 = 6%
        assert m["roa"] == pytest.approx(6.0)
        # FCF yield = 40/1100 ≈ 3.6364%
        assert m["fcf_yield"] == pytest.approx(3.6364)
