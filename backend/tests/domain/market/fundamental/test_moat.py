"""定价权/护城河评分纯函数测试。"""
import pytest

from src.domain.market.fundamental.moat import (
    gross_margin_trend,
    pricing_power_score,
    moat_score,
)


class TestGrossMarginTrend:
    def test_improving_stable(self):
        trend = gross_margin_trend([0.40, 0.42, 0.44, 0.46])
        assert trend.current == 0.46
        assert trend.improving is True
        assert trend.stable is True  # std 小

    def test_declining_volatile(self):
        trend = gross_margin_trend([0.50, 0.30, 0.45, 0.25])
        assert trend.volatility > 0.05
        assert trend.stable is False

    def test_empty(self):
        t = gross_margin_trend([])
        assert t.current is None

    def test_single_point(self):
        t = gross_margin_trend([0.45])
        assert t.current == 0.45
        assert t.slope is None


class TestPricingPowerScore:
    def test_strong_moutai_like(self):
        # 持续高毛利且稳定上行
        pp = pricing_power_score([0.88, 0.89, 0.90, 0.91])
        assert pp.score >= 70
        assert pp.verdict == "strong"
        assert pp.breakdown["level"] == 40

    def test_weak_commodity(self):
        # 低毛利波动
        pp = pricing_power_score([0.15, 0.10, 0.18, 0.12])
        assert pp.score < 40
        assert pp.verdict == "weak"

    def test_moderate(self):
        # 中等毛利 + 稳定 + 略降 → moderate（水平25+稳定30+趋势0=55）
        pp = pricing_power_score([0.45, 0.42, 0.46, 0.43])
        assert pp.verdict == "moderate"

    def test_empty(self):
        assert pricing_power_score([]) is None

    def test_declining_reduces_score(self):
        # 高毛利但下行 → 无趋势分
        pp = pricing_power_score([0.75, 0.72, 0.68, 0.65])
        assert pp.breakdown["momentum"] == 0
        assert pp.verdict in ("moderate", "strong")


class TestMoatScore:
    def test_wide_moat(self):
        # 高毛利稳定 + 高 ROE + 低负债
        pp_input = [0.85, 0.86, 0.86, 0.87]
        fin = {"net_profit": 25, "equity": 100, "debt_ratio": 0.25}
        m = moat_score(pp_input, fin)
        assert m.score >= 70
        assert m.verdict == "wide"

    def test_no_moat(self):
        pp_input = [0.12, 0.15, 0.10, 0.13]
        fin = {"net_profit": 3, "equity": 100, "debt_ratio": 0.75}
        m = moat_score(pp_input, fin)
        assert m.verdict == "none"

    def test_roic_overrides_roe(self):
        # 提供 ROIC 优先于 ROE
        pp_input = [0.80, 0.80, 0.80]
        m = moat_score(pp_input, fin={"debt_ratio": 0.30}, roic=0.25)
        assert m.breakdown["capital_return_30"] == 30

    def test_missing_fin_defaults_neutral(self):
        m = moat_score([0.50, 0.50])
        # 无 fin → 资本回报/杠杆给中性分
        assert m is not None
        assert m.breakdown["capital_return_30"] == 15

    def test_empty_returns_none(self):
        assert moat_score([]) is None
