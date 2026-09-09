"""筹码集中度 + 资金面 + 利差 纯函数测试。"""
import pytest

from src.domain.market.equity.concentration import (
    concentration_trend, per_capita_holding,
)
from src.domain.market.intel.macro.rate_differential import (
    cn_us_yield_differential, capital_flow_signal, rate_trend,
)
from src.domain.market.intel.market.fund_flow import (
    north_flow_signal, margin_sentiment,
)


class TestConcentrationTrend:
    def test_concentrating(self):
        # 户数连续减少 → 筹码集中
        r = concentration_trend([100000, 95000, 90000, 85000])
        assert r.verdict == "concentrating"
        assert r.consecutive_decline >= 2
        assert r.latest_change < 0

    def test_dispersing(self):
        r = concentration_trend([50000, 55000, 62000, 70000])
        assert r.verdict == "dispersing"
        assert r.consecutive_increase >= 2

    def test_stable(self):
        r = concentration_trend([100000, 105000, 99000])
        assert r.verdict == "stable"

    def test_total_change(self):
        r = concentration_trend([100000, 90000])
        assert r.total_change == pytest.approx(-0.10)

    def test_too_short(self):
        assert concentration_trend([100000]) is None
        assert concentration_trend([]) is None


class TestPerCapitaHolding:
    def test_rising(self):
        # 流通股本不变，户数减少 → 人均持股上升
        r = per_capita_holding(1e9, [100000, 90000])
        assert r.verdict == "rising"
        assert r.change > 0

    def test_falling(self):
        r = per_capita_holding(1e9, [100000, 120000])
        assert r.verdict == "falling"

    def test_missing(self):
        assert per_capita_holding(None, [100000]) is None
        assert per_capita_holding(1e9, []) is None


class TestYieldDifferential:
    def test_positive(self):
        r = cn_us_yield_differential(0.028, 0.022)
        assert r.differential == pytest.approx(0.006)
        assert r.inverted is False

    def test_inverted(self):
        r = cn_us_yield_differential(0.020, 0.030)
        assert r.inverted is True
        assert r.differential < 0

    def test_missing(self):
        assert cn_us_yield_differential(None, 0.02) is None


class TestCapitalFlowSignal:
    def test_widening_inflow(self):
        # 利差走阔 → 流入压力
        r = capital_flow_signal(0.030, 0.020, prev_cn_10y=0.028, prev_us_10y=0.022)
        assert r.widening is True
        assert r.verdict == "inflow_pressure"

    def test_narrowing_outflow(self):
        r = capital_flow_signal(0.025, 0.025, prev_cn_10y=0.030, prev_us_10y=0.020)
        assert r.widening is False
        assert r.verdict == "outflow_pressure"

    def test_inverted_outflow(self):
        # 利差倒挂 → 流出压力（无需历史）
        r = capital_flow_signal(0.020, 0.030)
        assert r.verdict == "outflow_pressure"

    def test_missing(self):
        assert capital_flow_signal(None, 0.02) is None


class TestRateTrend:
    def test_widening(self):
        r = rate_trend([0.005, 0.006, 0.007, 0.008])
        assert r.verdict == "widening"

    def test_narrowing(self):
        r = rate_trend([0.008, 0.007, 0.006, 0.005])
        assert r.verdict == "narrowing"

    def test_too_short(self):
        assert rate_trend([0.005]) is None


class TestNorthFlowSignal:
    def test_sustained_inflow(self):
        r = north_flow_signal([1e8, 2e8, 1.5e8, 3e8])
        assert r.momentum == "sustained_inflow"
        assert r.net_verdict == "inflow"
        assert r.cumulative > 0

    def test_sustained_outflow(self):
        r = north_flow_signal([-1e8, -2e8, -1e8, -3e8])
        assert r.momentum == "sustained_outflow"
        assert r.net_verdict == "outflow"

    def test_mixed(self):
        r = north_flow_signal([1e8, -1e8, 1e8])
        assert r.momentum == "mixed"

    def test_empty(self):
        assert north_flow_signal([]) is None


class TestMarginSentiment:
    def test_levering_up(self):
        r = margin_sentiment([1e11, 1.05e11, 1.1e11, 1.15e11])
        assert r.verdict == "levering_up"
        assert r.latest_change > 0

    def test_deleveraging(self):
        r = margin_sentiment([1.5e11, 1.4e11, 1.3e11])
        assert r.verdict == "deleveraging"

    def test_too_short(self):
        assert margin_sentiment([1e11]) is None
        assert margin_sentiment([]) is None
