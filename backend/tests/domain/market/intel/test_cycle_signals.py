"""簇 4 宏观周期纯函数测试。"""
import pytest

from src.domain.market.intel.macro.cycle_signals import (
    THREE_SECTOR_INDICATORS,
    classify_indicator,
    three_sector_checklist,
    business_cycle_phase,
    equity_macro_divergence,
    industry_rotation,
    INDUSTRY_ROTATION,
    money_supply_gap,
    PHASE_DOWNTURN,
    PHASE_RECOVERY,
    PHASE_OVERHEAT,
    PHASE_STAGFLATION,
)


class TestClassifyIndicator:
    def test_high_good_with_threshold(self):
        spec = THREE_SECTOR_INDICATORS["enterprise"]["pmi"]
        assert classify_indicator(spec, 52.0) == "good"   # >=50
        assert classify_indicator(spec, 40.0) == "bad"    # < 50*0.9
        assert classify_indicator(spec, 49.0) == "neutral"  # 介于 45~50

    def test_low_good_with_threshold(self):
        spec = THREE_SECTOR_INDICATORS["household"]["unemployment_rate"]
        assert classify_indicator(spec, 0.04) == "good"   # <=5.5%
        assert classify_indicator(spec, 0.06) == "neutral"  # 5.5%~6.05%

    def test_range(self):
        spec = THREE_SECTOR_INDICATORS["household"]["cpi_yoy"]
        assert classify_indicator(spec, 0.02) == "good"
        assert classify_indicator(spec, 0.06) == "neutral"

    def test_none_value(self):
        spec = THREE_SECTOR_INDICATORS["enterprise"]["pmi"]
        assert classify_indicator(spec, None) is None


class TestThreeSectorChecklist:
    def test_structure_and_overall(self):
        readings = {
            "pmi": 52.0, "ppi_yoy": 0.03, "cpi_yoy": 0.02,
            "unemployment_rate": 0.05, "m2_growth": 0.10, "gdp_growth": 0.05,
        }
        r = three_sector_checklist(readings)
        assert set(r.keys()) >= {"household", "enterprise", "government", "overall_health"}
        assert r["enterprise"]["pmi"]["status"] == "good"
        assert 0.0 <= r["overall_health"] <= 1.0

    def test_missing_indicators_neutral(self):
        r = three_sector_checklist({"pmi": 52.0})
        assert r["overall_health"] is not None
        # household 部门无数据
        assert all(v["status"] is None for v in r["household"].values())

    def test_empty(self):
        r = three_sector_checklist({})
        assert r["overall_health"] is None


class TestBusinessCyclePhase:
    def test_downturn(self):
        r = business_cycle_phase(pmi=48.0, ppi_yoy=-0.02)
        assert r["phase"] == PHASE_DOWNTURN

    def test_recovery(self):
        r = business_cycle_phase(pmi=51.0, ppi_yoy=-0.01)
        assert r["phase"] == PHASE_RECOVERY

    def test_overheat(self):
        r = business_cycle_phase(pmi=53.0, ppi_yoy=0.05)
        assert r["phase"] == PHASE_OVERHEAT

    def test_stagflation(self):
        r = business_cycle_phase(pmi=49.0, ppi_yoy=0.06)
        assert r["phase"] == PHASE_STAGFLATION

    def test_boundary_pmi_50_is_expanding(self):
        r = business_cycle_phase(pmi=50.0, ppi_yoy=-0.01)
        assert r["pmi_expanding"] is True
        assert r["phase"] == PHASE_RECOVERY

    def test_missing(self):
        assert business_cycle_phase(None, 0.03) is None
        assert business_cycle_phase(50.0, None) is None


class TestEquityMacroDivergence:
    def test_bubble_warning(self):
        r = equity_macro_divergence(index_return=0.50, profit_growth=0.10)
        assert r.divergence == pytest.approx(0.40)
        assert r.bubble_warning is True

    def test_aligned_no_warning(self):
        r = equity_macro_divergence(index_return=0.15, profit_growth=0.12)
        assert r.bubble_warning is False

    def test_custom_threshold(self):
        # divergence = 0.35 - 0.10 = 0.25 >= 0.20 → 警报
        r = equity_macro_divergence(0.35, 0.10, warning_gap=0.20)
        assert r.bubble_warning is True
        # divergence = 0.25 - 0.10 = 0.15 < 0.30 → 无警报
        r2 = equity_macro_divergence(0.25, 0.10, warning_gap=0.30)
        assert r2.bubble_warning is False

    def test_missing(self):
        assert equity_macro_divergence(None, 0.1) is None


class TestIndustryRotation:
    def test_recovery_lists(self):
        r = industry_rotation(PHASE_RECOVERY)
        assert "有色金属" in r["overweight"]
        assert "非银金融" in r["overweight"]

    def test_downturn_defensive(self):
        r = industry_rotation(PHASE_DOWNTURN)
        assert "食品饮料" in r["overweight"]
        assert "公用事业" in r["overweight"]

    def test_all_phases_have_rationale(self):
        for phase, entry in INDUSTRY_ROTATION.items():
            assert "overweight" in entry and "rationale" in entry, phase

    def test_none_returns_none(self):
        assert industry_rotation(None) is None
        assert industry_rotation("xxx") is None


class TestMoneySupplyGap:
    def test_loose(self):
        r = money_supply_gap(m2_growth=0.12, gdp_growth=0.05)
        assert r.nominal_gap == pytest.approx(0.07)
        assert r.verdict == "loose"

    def test_tight(self):
        r = money_supply_gap(m2_growth=0.05, gdp_growth=0.10)
        assert r.verdict == "tight"

    def test_neutral(self):
        r = money_supply_gap(m2_growth=0.06, gdp_growth=0.05)
        assert r.verdict == "neutral"

    def test_real_gap_with_cpi(self):
        r = money_supply_gap(m2_growth=0.12, gdp_growth=0.05, cpi=0.02)
        assert r.real_gap == pytest.approx(0.12 - 0.05 - 0.02)

    def test_real_gap_none_without_cpi(self):
        r = money_supply_gap(0.10, 0.05)
        assert r.real_gap is None

    def test_missing(self):
        assert money_supply_gap(None, 0.05) is None
