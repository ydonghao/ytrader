"""簇 6 股权/IPO 结构纯函数测试。"""
import pytest

from src.domain.market.equity.structure import (
    share_dilution_track,
    ownership_stability,
    manipulation_risk_score,
    ah_premium,
    financing_dividend_ratio,
)


class TestShareDilution:
    def test_basic_dilution(self):
        ev = [{"type": "issuance", "shares_delta": 20_000_000}]
        r = share_dilution_track(100_000_000, ev)
        assert r.final_shares == 120_000_000
        assert r.dilution_ratio == pytest.approx(0.20)
        assert r.stake_retention == pytest.approx(100 / 120)

    def test_buyback_offsets(self):
        ev = [
            {"type": "issuance", "shares_delta": 30_000_000},
            {"type": "buyback", "shares_delta": -10_000_000},
        ]
        r = share_dilution_track(100_000_000, ev)
        assert r.net_new_shares == 20_000_000
        assert r.dilution_ratio == pytest.approx(0.20)

    def test_no_events(self):
        r = share_dilution_track(100_000_000, [])
        assert r.dilution_ratio == 0.0
        assert r.stake_retention == 1.0

    def test_invalid_initial(self):
        assert share_dilution_track(0, []) is None

    def test_invalid_event_skipped(self):
        ev = [{"type": "issuance", "shares_delta": "abc"}, {"shares_delta": 10}]
        r = share_dilution_track(100, ev)
        assert r.net_new_shares == 10.0


class TestOwnershipStability:
    def test_stable_by_largest(self):
        r = ownership_stability([0.30, 0.10, 0.05])
        assert r.stable is True
        assert r.largest_pct == 0.30

    def test_stable_by_top3(self):
        r = ownership_stability([0.20, 0.18, 0.12])
        assert r.stable is True
        assert r.top3_pct == pytest.approx(0.50)

    def test_dispersed_unstable(self):
        r = ownership_stability([0.10, 0.08, 0.05])
        assert r.stable is False
        assert any("分散" in n for n in r.notes)

    def test_esop_warning(self):
        r = ownership_stability([0.30, 0.10], esop_reducing=True)
        assert any("员工持股" in n for n in r.notes)

    def test_empty(self):
        assert ownership_stability([]) is None


class TestManipulationRisk:
    def test_all_factors_suspicious(self):
        r = manipulation_risk_score(
            market_cap_yi=15, float_ratio=0.3, price_change_pct=0.8, net_profit_yi=0.2)
        assert r.score == 100
        assert r.verdict == "suspicious"
        assert len(r.triggered) == 4

    def test_clean(self):
        r = manipulation_risk_score(
            market_cap_yi=500, float_ratio=0.9, price_change_pct=0.1, net_profit_yi=50)
        assert r.score == 0
        assert r.verdict == "clean"

    def test_watch(self):
        r = manipulation_risk_score(
            market_cap_yi=20, float_ratio=0.4, price_change_pct=0.1, net_profit_yi=50)
        assert r.score == 50
        assert r.verdict == "watch"

    def test_none_skip(self):
        assert manipulation_risk_score(None, None, None, None).score == 0


class TestAhPremium:
    def test_a_premium(self):
        # A 10 RMB, H 8 HKD fx 0.9 → H_cny=7.2, premium=(10-7.2)/7.2
        r = ah_premium(a_price=10, h_price_hkd=8, hkd_cny_fx=0.9)
        assert r.h_price_cny == pytest.approx(7.2)
        assert r.premium == pytest.approx((10 - 7.2) / 7.2)
        assert r.premium > 0

    def test_h_discount(self):
        r = ah_premium(5, 8, 1.0)
        assert r.premium < 0

    def test_invalid(self):
        assert ah_premium(0, 8, 1.0) is None
        assert ah_premium(10, 8, 0) is None


class TestFinancingDividendRatio:
    def test_generous_moutai(self):
        # 茅台：累计分红3000亿 / 累计融资23亿
        r = financing_dividend_ratio(3000e8, 23e8)
        assert r.ratio > 1
        assert r.verdict == "generous"

    def test_normal(self):
        r = financing_dividend_ratio(50e8, 100e8)
        assert r.verdict == "normal"

    def test_stingy(self):
        r = financing_dividend_ratio(10e8, 100e8)
        assert r.verdict == "stingy"

    def test_zero_financing(self):
        assert financing_dividend_ratio(100, 0) is None
