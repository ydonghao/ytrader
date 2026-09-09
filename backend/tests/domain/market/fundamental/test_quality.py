"""财务质量诊断纯函数测试。镜像 test_derived_metrics.py 风格。"""
import pytest

from src.domain.market.fundamental.quality import (
    cash_to_revenue,
    ocf_net_income_ratio,
    short_term_debt,
    cash_like,
    cash_coverage_short_debt,
    ar_vs_cash_flag,
    expense_to_gross_profit,
    gross_margin_class,
    dupont_decomposition,
    liability_split,
    asset_heaviness,
    inventory_to_revenue,
    goodwill_ratio,
    payout_ratio,
    cash_flow_stage,
    compute_quality_report,
)


class TestCashToRevenue:
    def test_basic(self):
        assert cash_to_revenue({"cash_from_sales": 120, "revenue": 100}) == pytest.approx(1.2)

    def test_missing_cash_from_sales(self):
        # ocf 不是 cash_from_sales，应返回 None
        assert cash_to_revenue({"ocf": 120, "revenue": 100}) is None

    def test_zero_revenue(self):
        assert cash_to_revenue({"cash_from_sales": 120, "revenue": 0}) is None


class TestOcfNetIncomeRatio:
    def test_basic(self):
        assert ocf_net_income_ratio({"ocf": 120, "net_profit": 100}) == pytest.approx(1.2)

    def test_loss_returns_none(self):
        assert ocf_net_income_ratio({"ocf": 120, "net_profit": -50}) is None

    def test_missing(self):
        assert ocf_net_income_ratio({"net_profit": 100}) is None


class TestShortTermDebt:
    def test_both(self):
        assert short_term_debt({"short_loan": 100, "non_current_liab_due_within_1y": 50}) == 150

    def test_short_only(self):
        assert short_term_debt({"short_loan": 100}) == 100

    def test_none(self):
        assert short_term_debt({}) is None


class TestCashLike:
    def test_both(self):
        assert cash_like({"monetary_funds": 100, "trading_financial_assets": 20}) == 120

    def test_monetary_only(self):
        assert cash_like({"monetary_funds": 100}) == 100

    def test_none(self):
        assert cash_like({}) is None


class TestCashCoverageShortDebt:
    def test_basic(self):
        # cash=120, 短期债务=100 → 1.2
        fin = {"monetary_funds": 120, "short_loan": 100}
        assert cash_coverage_short_debt(fin) == pytest.approx(1.2)

    def test_below_one(self):
        fin = {"monetary_funds": 20, "short_loan": 100, "non_current_liab_due_within_1y": 50}
        # cash=20, 短期债务=150 → 0.1333（实现保留 4 位）
        assert cash_coverage_short_debt(fin) == pytest.approx(0.1333, abs=0.0001)

    def test_no_debt(self):
        assert cash_coverage_short_debt({"monetary_funds": 100}) is None


class TestArVsCashFlag:
    def test_eliminate(self):
        r = ar_vs_cash_flag({"accounts_receivable": 150, "monetary_funds": 100})
        assert r["eliminate"] is True
        assert r["ratio"] == pytest.approx(1.5)

    def test_ok(self):
        r = ar_vs_cash_flag({"accounts_receivable": 50, "notes_receivable": 10, "monetary_funds": 100})
        assert r["eliminate"] is False
        assert r["receivables"] == 60

    def test_missing(self):
        assert ar_vs_cash_flag({"monetary_funds": 100}) is None


class TestExpenseToGrossProfit:
    def _fin(self, expense_total, gp=200):
        return {
            "sell_expense": expense_total, "gross_profit": gp,
        }

    def test_strong(self):
        # 40/200 = 0.2
        r = expense_to_gross_profit({"sell_expense": 40, "gross_profit": 200})
        assert r["ratio"] == pytest.approx(0.2)
        assert r["grade"] == "strong"

    def test_medium(self):
        r = expense_to_gross_profit({"sell_expense": 100, "gross_profit": 200})
        assert r["ratio"] == pytest.approx(0.5)
        assert r["grade"] == "medium"

    def test_weak(self):
        r = expense_to_gross_profit(
            {"sell_expense": 80, "admin_expense": 80, "gross_profit": 200}
        )
        assert r["ratio"] == pytest.approx(0.8)
        assert r["grade"] == "weak"

    def test_gp_from_revenue_cost(self):
        r = expense_to_gross_profit({"sell_expense": 40, "revenue": 300, "operating_cost": 100})
        # gp = 200, ratio 0.2
        assert r["gross_profit"] == 200
        assert r["grade"] == "strong"

    def test_negative_gp(self):
        assert expense_to_gross_profit({"sell_expense": 40, "revenue": 100, "operating_cost": 200}) is None


class TestGrossMarginClass:
    def test_pricing_power(self):
        assert gross_margin_class({"gross_margin": 70})["label"] == "pricing_power"

    def test_medium(self):
        assert gross_margin_class({"gross_margin": 45})["label"] == "medium"

    def test_boundary_60_is_medium(self):
        assert gross_margin_class({"gross_margin": 60})["label"] == "medium"

    def test_efficiency(self):
        assert gross_margin_class({"gross_margin": 20})["label"] == "efficiency"

    def test_from_revenue_cost(self):
        r = gross_margin_class({"revenue": 100, "operating_cost": 40})
        assert r["gross_margin"] == pytest.approx(60.0)
        assert r["label"] == "medium"


class TestDupont:
    def test_basic(self):
        # net=20,rev=100,assets=80,equity=40
        # nm=0.2, at=1.25, em=2.0, roe=0.5
        r = dupont_decomposition({
            "net_profit": 20, "revenue": 100,
            "total_assets": 80, "equity": 40,
        })
        assert r["net_margin"] == pytest.approx(0.2)
        assert r["asset_turnover"] == pytest.approx(1.25)
        assert r["equity_multiplier"] == pytest.approx(2.0)
        assert r["roe"] == pytest.approx(0.5)
        assert "profit" in r["driver"] and "efficiency" in r["driver"]

    def test_leverage_driver(self):
        # 低净利、低周转、高杠杆
        r = dupont_decomposition({
            "net_profit": 5, "revenue": 100,
            "total_assets": 200, "equity": 40,
        })
        # nm=0.05, at=0.5, em=5.0 → roe=0.125, driver=leverage
        assert r["driver"] == "leverage"

    def test_missing(self):
        assert dupont_decomposition({"net_profit": 20, "revenue": 100, "total_assets": 80}) is None

    def test_zero_equity(self):
        assert dupont_decomposition({
            "net_profit": 20, "revenue": 100, "total_assets": 80, "equity": 0,
        }) is None


class TestLiabilitySplit:
    def test_basic(self):
        fin = {
            "accounts_payable": 50, "contract_liability": 20, "advance_receipts": 10,
            "short_loan": 30, "long_loan": 40, "non_current_liab_due_within_1y": 5,
            "total_liabilities": 200,
        }
        r = liability_split(fin)
        assert r["operating_liability"] == 80
        assert r["interest_bearing_liability"] == 75
        assert r["operating_ratio"] == pytest.approx(0.4)
        assert r["interest_bearing_ratio"] == pytest.approx(0.375)

    def test_no_total(self):
        r = liability_split({"accounts_payable": 50, "short_loan": 30})
        assert r["operating_liability"] == 50
        assert r["interest_bearing_liability"] == 30
        assert r["operating_ratio"] is None


class TestAssetHeaviness:
    def test_heavy(self):
        r = asset_heaviness({"fixed_assets": 50, "construction_in_progress": 10, "total_assets": 100})
        assert r["ratio"] == pytest.approx(0.6)
        assert r["label"] == "heavy"

    def test_light(self):
        r = asset_heaviness({"fixed_assets": 15, "total_assets": 100})
        assert r["label"] == "light"

    def test_medium(self):
        r = asset_heaviness({"fixed_assets": 30, "total_assets": 100})
        assert r["label"] == "medium"

    def test_missing(self):
        assert asset_heaviness({"fixed_assets": 50}) is None


class TestInventoryToRevenue:
    def test_basic(self):
        assert inventory_to_revenue({"inventory": 50, "revenue": 200}) == pytest.approx(0.25)

    def test_missing(self):
        assert inventory_to_revenue({"inventory": 50}) is None


class TestGoodwillRatio:
    def test_alert(self):
        r = goodwill_ratio({"goodwill": 30, "total_assets": 100, "equity": 50})
        assert r["to_assets"] == pytest.approx(0.3)
        assert r["to_equity"] == pytest.approx(0.6)
        assert r["alert"] is True

    def test_no_alert(self):
        r = goodwill_ratio({"goodwill": 10, "total_assets": 100, "equity": 100})
        assert r["to_assets"] == pytest.approx(0.1)
        assert r["alert"] is False

    def test_no_goodwill(self):
        r = goodwill_ratio({"goodwill": None, "total_assets": 100})
        assert r["goodwill"] is None
        assert r["alert"] is False


class TestPayoutRatio:
    def test_normal(self):
        r = payout_ratio(100, 25)   # 25%
        assert r["ratio"] == pytest.approx(0.25)
        assert r["grade"] == "normal"
        assert r["draining"] is False

    def test_generous(self):
        r = payout_ratio(100, 50)   # 50%
        assert r["grade"] == "generous"

    def test_high_and_draining(self):
        r = payout_ratio(100, 120)  # 120% > 100% 掏空家底
        assert r["grade"] == "high"
        assert r["draining"] is True

    def test_loss_returns_none(self):
        assert payout_ratio(-50, 10) is None

    def test_no_dividend_returns_none(self):
        assert payout_ratio(100, 0) is None


class TestCashFlowStage:
    def test_self_funded_expansion(self):
        r = cash_flow_stage({"icf": -50, "fcf": -20})  # fcf 列 = 筹资 CF
        assert r["expanding"] is True
        assert r["borrowing"] is False
        assert r["stage"] == "self_funded_expansion"

    def test_borrowing_to_expand(self):
        r = cash_flow_stage({"icf": -50, "fcf": 30})
        assert r["stage"] == "borrowing_to_expand"

    def test_contracting_and_repaying(self):
        r = cash_flow_stage({"icf": 50, "fcf": -20})
        assert r["stage"] == "contracting_and_repaying"

    def test_borrowing_but_contracting(self):
        r = cash_flow_stage({"icf": 50, "fcf": 30})
        assert r["stage"] == "borrowing_but_contracting"

    def test_financing_unknown(self):
        r = cash_flow_stage({"icf": -50})
        assert r["stage"] == "expanding"

    def test_icf_missing(self):
        assert cash_flow_stage({"fcf": 30}) is None


class TestComputeQualityReport:
    def test_healthy_pass(self):
        fin = {
            "revenue": 1000, "operating_cost": 400, "gross_profit": 600,
            "sell_expense": 60, "admin_expense": 30, "rd_expense": 30, "fin_expense": 0,
            "monetary_funds": 500, "trading_financial_assets": 100,
            "short_loan": 50, "non_current_liab_due_within_1y": 50,
            "accounts_receivable": 50, "inventory": 60,
            "net_profit": 150, "ocf": 200, "icf": -100, "fcf": -40,
            "total_assets": 1000, "equity": 600, "total_liabilities": 400,
            "gross_margin": 60.0, "goodwill": 0,
        }
        r = compute_quality_report(fin)
        assert r["verdict"] == "pass"
        assert r["red_flags"] == []
        # 各组件：cash_safety cov=600/100=6 →100；earnings_quality 200/150=1.333→100；
        # expense 120/600=0.2 strong→100；gross_margin 60→medium 60；roe 0.25→100
        assert r["quality_score"] == pytest.approx(94.0)
        assert r["metrics"]["expense_to_gross_profit"]["grade"] == "strong"

    def test_eliminate_by_red_flags(self):
        fin = {
            "revenue": 100, "operating_cost": 90, "gross_profit": 10,
            "monetary_funds": 20, "short_loan": 100, "non_current_liab_due_within_1y": 50,
            "accounts_receivable": 200, "net_profit": -50, "goodwill": 0,
        }
        r = compute_quality_report(fin)
        assert r["verdict"] == "eliminate"
        assert "cash_coverage_below_1" in r["red_flags"]
        assert "receivables_exceed_cash" in r["red_flags"]
        assert "net_loss" in r["red_flags"]

    def test_review_middling(self):
        fin = {
            "revenue": 1000, "operating_cost": 700, "gross_profit": 300,
            "sell_expense": 150, "admin_expense": 50, "rd_expense": 30, "fin_expense": 20,
            "monetary_funds": 200, "short_loan": 100,
            "accounts_receivable": 50, "net_profit": 50, "ocf": 40,
            "total_assets": 1000, "equity": 600, "goodwill": 0,
            "gross_margin": 30.0,
        }
        r = compute_quality_report(fin)
        assert r["verdict"] == "review"
        assert r["red_flags"] == []
        # cash_safety=200/100=2→100; eq 40/50=0.8→66.67; expense 250/300=0.833 weak→20;
        # gm 30→medium 60; roe: 50/1000=0.05*1.0*1.667=0.0833→41.67
        # weighted = 25 + 13.333 + 4 + 9 + 8.333 = 59.667
        assert r["quality_score"] == pytest.approx(59.6667, abs=0.01)

    def test_missing_data_safe(self):
        r = compute_quality_report({})
        assert r["verdict"] in {"eliminate", "review"}
        assert r["quality_score"] is None
        assert r["metrics"]["cash_to_revenue"] is None
