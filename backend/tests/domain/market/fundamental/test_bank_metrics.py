"""簇 7 银行专项纯函数测试。"""
import pytest

from src.domain.market.fundamental.bank_metrics import (
    extract_bank_subjects,
    loan_to_deposit_ratio,
    net_interest_margin,
    net_interest_spread,
    provision_coverage_ratio,
    npl_ratio,
    bank_revenue_split,
    compute_bank_report,
)


class TestExtractBankSubjects:
    def test_extract_known_subjects(self):
        detail = {"利息收入": "3000", "利息支出": "1500", "发放贷款及垫款": "80000",
                  "吸收存款": "100000", "手续费及佣金收入": "500"}
        out = extract_bank_subjects(detail)
        assert out["interest_income"] == 3000.0
        assert out["interest_expense"] == 1500.0
        assert out["loans_balance"] == 80000.0
        assert out["deposits_balance"] == 100000.0
        assert out["fee_income"] == 500.0

    def test_missing_skipped(self):
        out = extract_bank_subjects({"利息收入": "100"})
        assert out == {"interest_income": 100.0}

    def test_non_dict(self):
        assert extract_bank_subjects(None) == {}
        assert extract_bank_subjects("abc") == {}

    def test_invalid_value_skipped(self):
        out = extract_bank_subjects({"利息收入": "abc"})
        assert out == {}


class TestLoanDepositRatio:
    def test_normal(self):
        r = loan_to_deposit_ratio(80000, 100000)
        assert r.ratio == pytest.approx(0.8)
        assert r.verdict == "normal"

    def test_idle_low(self):
        r = loan_to_deposit_ratio(60000, 100000)
        assert r.verdict == "idle_low"

    def test_high_stretch(self):
        r = loan_to_deposit_ratio(120000, 100000)
        assert r.verdict == "high_stretch"

    def test_zero_deposit(self):
        assert loan_to_deposit_ratio(100, 0) is None

    def test_missing(self):
        assert loan_to_deposit_ratio(None, 100) is None


class TestNetInterestMargin:
    def test_healthy(self):
        # (3000-1500)/60000 = 0.025
        r = net_interest_margin(3000, 1500, 60000)
        assert r.nim == pytest.approx(0.025)
        assert r.verdict == "healthy"

    def test_normal(self):
        # 净息差 1200 / 60000 = 0.02 → normal 区间 (1.8%~2.5%)
        r = net_interest_margin(2700, 1500, 60000)
        assert r.nim == pytest.approx(0.02)
        assert r.verdict == "normal"

    def test_pressured(self):
        r = net_interest_margin(2000, 1000, 60000)  # 1000/60000≈0.0167
        assert r.verdict == "pressured"

    def test_missing(self):
        assert net_interest_margin(None, 100, 1000) is None
        assert net_interest_margin(100, 50, 0) is None


class TestNetInterestSpread:
    def test_basic(self):
        assert net_interest_spread(0.045, 0.018) == pytest.approx(0.027)

    def test_missing(self):
        assert net_interest_spread(None, 0.02) is None


class TestProvisionCoverage:
    def test_top(self):
        # 4000/1000 = 4.0
        r = provision_coverage_ratio(4000, 1000)
        assert r.ratio == pytest.approx(4.0)
        assert r.verdict == "top"

    def test_solid(self):
        r = provision_coverage_ratio(2000, 1000)  # 2.0
        assert r.verdict == "solid"

    def test_low_below_regulatory(self):
        r = provision_coverage_ratio(1000, 1000)  # 1.0 < 1.5
        assert r.verdict == "low"

    def test_zero_npl(self):
        assert provision_coverage_ratio(1000, 0) is None


class TestNplRatio:
    def test_excellent(self):
        r = npl_ratio(50, 100000)  # 0.05% < 1%
        assert r.verdict == "excellent"

    def test_normal(self):
        r = npl_ratio(150, 10000)  # 1.5%
        assert r.verdict == "normal"

    def test_high(self):
        r = npl_ratio(300, 10000)  # 3%
        assert r.verdict == "high"

    def test_missing(self):
        assert npl_ratio(None, 1000) is None
        assert npl_ratio(10, 0) is None


class TestBankRevenueSplit:
    def test_basic_shares(self):
        r = bank_revenue_split(interest_income=3000, interest_expense=1500,
                               fee_income=500, fee_expense=100, other_income=100)
        # nii=1500, fee_net=400, other=100, total=2000
        assert r.net_interest_income == 1500
        assert r.fee_income_net == 400
        assert r.total_revenue == pytest.approx(2000)
        assert r.interest_share == pytest.approx(0.75)
        assert r.fee_share == pytest.approx(0.20)

    def test_fee_optional(self):
        r = bank_revenue_split(3000, 1500)
        assert r.fee_income_net == 0.0
        assert r.interest_share == 1.0

    def test_missing_interest(self):
        assert bank_revenue_split(None, 100) is None

    def test_zero_total(self):
        assert bank_revenue_split(100, 100) is None


class TestComputeBankReport:
    def test_full_report(self):
        fin = {"interest_income": 3000, "interest_expense": 1500,
               "loans_balance": 80000, "deposits_balance": 100000,
               "loan_loss_provision": 4000, "fee_income": 500, "fee_expense": 100}
        rep = compute_bank_report(fin, npl_balance=1000)
        assert rep["loan_deposit"].verdict == "normal"
        assert rep["nim"] is not None
        assert rep["provision_coverage"].verdict == "top"
        # 1000/80000 = 1.25% → normal
        assert rep["npl"].verdict == "normal"
        # fee_net=400, total=nii1500+fee400=1900 → 400/1900≈0.2105
        assert rep["revenue_split"].fee_share == pytest.approx(400 / 1900)

    def test_no_npl_skips_two_metrics(self):
        fin = {"loans_balance": 80000, "deposits_balance": 100000}
        rep = compute_bank_report(fin)
        assert rep["loan_deposit"] is not None
        assert rep["provision_coverage"] is None  # 需 npl_balance
        assert rep["npl"] is None
