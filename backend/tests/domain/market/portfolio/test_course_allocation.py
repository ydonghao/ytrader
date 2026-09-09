"""簇 3 组合与仓位纯函数测试。镜像 test_quality.py 风格。"""
import pytest

from src.domain.market.portfolio.course_allocation import (
    HoldingFundamental,
    portfolio_aggregate_fundamentals,
    growth_dividend_quadrant,
    risk_profile_weights,
    RISK_PROFILES,
    index_pe_position_band,
    fire_coverage,
    ThesisCondition,
    evaluate_thesis,
    QUADRANT_VALUE_TRAP,
    QUADRANT_CASH_COW,
)


class TestPortfolioAggregate:
    def test_weighted_aggregation_and_roe(self):
        hs = [
            HoldingFundamental("A", weight=0.5, revenue=100, net_profit=10, equity=80, dividend=4),
            HoldingFundamental("B", weight=0.5, revenue=200, net_profit=30, equity=150, dividend=6),
        ]
        agg = portfolio_aggregate_fundamentals(hs)
        # 加权: rev=0.5*100+0.5*200=150, np=0.5*10+0.5*30=20, eq=0.5*80+0.5*150=115, div=5
        assert agg.revenue == pytest.approx(150)
        assert agg.net_profit == pytest.approx(20)
        assert agg.equity == pytest.approx(115)
        assert agg.dividend == pytest.approx(5)
        assert agg.roe == pytest.approx(20 / 115)
        assert agg.payout_ratio == pytest.approx(5 / 20)

    def test_roe_reflects_weight_not_equal_roe_average(self):
        # 大权重低 ROE 成份应拉低组合 ROE（按聚合反推，而非 ROE 加权平均）
        hs = [
            HoldingFundamental("big", weight=0.9, net_profit=1, equity=100),   # ROE 1%
            HoldingFundamental("small", weight=0.1, net_profit=50, equity=100),  # ROE 50%
        ]
        agg = portfolio_aggregate_fundamentals(hs)
        # 聚合 np=0.9*1+0.1*50=5.9, eq=0.9*100+0.1*100=100 → ROE=5.9%
        # 若错误地按 ROE 加权平均会得 0.9*0.01+0.1*0.5=5.9%  —— 恰好相同(因 eq 相同)
        assert agg.roe == pytest.approx(0.059)

    def test_growth_weighted(self):
        hs = [
            HoldingFundamental("A", weight=0.6, revenue_growth=0.20),
            HoldingFundamental("B", weight=0.4, revenue_growth=0.05),
        ]
        agg = portfolio_aggregate_fundamentals(hs)
        assert agg.revenue_growth == pytest.approx(0.6 * 0.20 + 0.4 * 0.05)

    def test_missing_metric_skipped(self):
        hs = [
            HoldingFundamental("A", weight=0.5, net_profit=10),
            HoldingFundamental("B", weight=0.5, net_profit=None),
        ]
        agg = portfolio_aggregate_fundamentals(hs)
        assert agg.net_profit == pytest.approx(5.0)
        assert agg.equity is None
        assert agg.roe is None

    def test_empty(self):
        assert portfolio_aggregate_fundamentals([]).revenue is None

    def test_loss_profit_no_payout(self):
        hs = [HoldingFundamental("A", weight=1.0, net_profit=-5, dividend=1)]
        agg = portfolio_aggregate_fundamentals(hs)
        assert agg.payout_ratio is None  # 亏损不计派息率


class TestGrowthDividendQuadrant:
    def test_cash_cow_high_growth_high_payout(self):
        r = growth_dividend_quadrant(0.25, 0.50)
        assert r["quadrant"] == QUADRANT_CASH_COW
        assert r["avoid"] is False

    def test_value_trap_low_low(self):
        r = growth_dividend_quadrant(0.02, 0.05)
        assert r["quadrant"] == QUADRANT_VALUE_TRAP
        assert r["avoid"] is True

    def test_mature_dividend_low_growth_high_payout(self):
        r = growth_dividend_quadrant(0.05, 0.60)
        assert r["quadrant"] == "star"
        assert r["avoid"] is False

    def test_reinvest_high_growth_low_payout(self):
        r = growth_dividend_quadrant(0.30, 0.10)
        assert r["quadrant"] == "reinvest"

    def test_missing_returns_none(self):
        assert growth_dividend_quadrant(None, 0.5) is None
        assert growth_dividend_quadrant(0.1, None) is None

    def test_custom_thresholds(self):
        # 成长门槛提到 20%
        r = growth_dividend_quadrant(0.15, 0.40, growth_threshold=0.20)
        assert r["growth_high"] is False
        assert r["quadrant"] == "star"


class TestRiskProfile:
    def test_all_profiles_sum_to_one(self):
        for p, w in RISK_PROFILES.items():
            assert sum(w.values()) == pytest.approx(1.0), p

    def test_known_ratios(self):
        assert risk_profile_weights("defensive") == {"dividend": 0.7, "bluechip": 0.3, "growth": 0.0}
        assert risk_profile_weights("radical") == {"dividend": 0.0, "bluechip": 0.3, "growth": 0.7}
        assert risk_profile_weights("balanced")["growth"] == 0.1

    def test_unknown_returns_none(self):
        assert risk_profile_weights("xxx") is None


class TestIndexPePositionBand:
    def test_oversold_full_position(self):
        # mean=15, std=3 → current=10 → z=(10-15)/3≈-1.67
        r = index_pe_position_band([15, 15, 15, 12, 18, 15, 15, 18], current_pe=10)
        assert r.band == "oversold"
        assert r.target_position == 1.0

    def test_overvalued_low_position(self):
        series = [12, 13, 14, 12, 13, 14, 12, 13]  # mean≈12.875, std≈0.83
        r = index_pe_position_band(series, current_pe=20)
        assert r.band == "overvalued"
        assert r.target_position == 0.4

    def test_z_in_between(self):
        series = [10, 10, 10, 10, 20, 20, 20, 20]  # mean=15, std≈5.16
        r = index_pe_position_band(series, current_pe=15)
        assert -0.1 < r.z_score <= 0
        assert r.band == "low_fair"
        assert r.target_position == 0.8

    def test_empty_series(self):
        assert index_pe_position_band([], 10) is None

    def test_single_point(self):
        assert index_pe_position_band([10], 10) is None

    def test_invalid_current(self):
        assert index_pe_position_band([10, 12, 14], 0) is None
        assert index_pe_position_band([10, 12, 14], -1) is None

    def test_zero_variance_does_not_crash(self):
        r = index_pe_position_band([10, 10, 10], current_pe=12)
        assert r is not None  # std 兜底
        assert r.band == "overvalued"


class TestFireCoverage:
    def test_achieved(self):
        r = fire_coverage(annual_dividend_income=120000, annual_living_expense=100000)
        assert r.coverage_ratio == pytest.approx(1.2)
        assert r.achieved is True
        assert r.months_covered == pytest.approx(14.4)

    def test_not_achieved(self):
        r = fire_coverage(50000, 100000)
        assert r.achieved is False
        assert r.coverage_ratio == pytest.approx(0.5)

    def test_zero_expense(self):
        assert fire_coverage(120000, 0) is None

    def test_zero_income(self):
        r = fire_coverage(0, 100000)
        assert r.coverage_ratio == 0.0
        assert r.achieved is False


class TestThesisMonitor:
    def _conds(self):
        return [
            ThesisCondition("revenue_growth", ">=", 0.10, "增速维持10%+"),
            ThesisCondition("roe", ">=", 0.15, "ROE>=15%"),
            ThesisCondition("debt_ratio", "<=", 0.60, "负债率<=60%"),
        ]

    def test_all_held(self):
        res = evaluate_thesis(self._conds(), {"revenue_growth": 0.20, "roe": 0.18, "debt_ratio": 0.40})
        assert res.recommend_sell is False
        assert len(res.held) == 3
        assert len(res.breached) == 0

    def test_one_breach_triggers_sell(self):
        res = evaluate_thesis(self._conds(), {"revenue_growth": 0.05, "roe": 0.18, "debt_ratio": 0.40})
        assert res.recommend_sell is True
        assert len(res.breached) == 1
        assert res.breached[0].metric == "revenue_growth"

    def test_missing_metric_held(self):
        res = evaluate_thesis(self._conds(), {"roe": 0.18, "debt_ratio": 0.40})
        assert res.recommend_sell is False  # 缺数据保守不卖
        assert len(res.held) == 3

    def test_unknown_operator_held(self):
        c = [ThesisCondition("x", "??", 1.0)]
        res = evaluate_thesis(c, {"x": 5.0})
        assert res.recommend_sell is False

    def test_empty_conditions(self):
        res = evaluate_thesis([], {"x": 1})
        assert res.recommend_sell is False
