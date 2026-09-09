"""库存周期/信用周期纯函数测试。"""
import pytest

from src.domain.market.intel.macro.cycle_stages import (
    inventory_cycle,
    m1_m2_scissors,
    credit_cycle,
    STAGE_ACTIVE_DESTOCK,
    STAGE_PASSIVE_DESTOCK,
    STAGE_ACTIVE_RESTOCK,
    STAGE_PASSIVE_RESTOCK,
)


class TestInventoryCycle:
    def test_passive_destock_recovery(self):
        # 需求+10%, 库存-5% → 被动去库(复苏)
        r = inventory_cycle(demand_growth=0.10, inventory_growth=-0.05)
        assert r.stage == STAGE_PASSIVE_DESTOCK
        assert "复苏" in r.label

    def test_active_restock_boom(self):
        r = inventory_cycle(0.15, 0.08)
        assert r.stage == STAGE_ACTIVE_RESTOCK

    def test_passive_restock_pre_recession(self):
        r = inventory_cycle(-0.05, 0.06)
        assert r.stage == STAGE_PASSIVE_RESTOCK

    def test_active_destock_recession(self):
        r = inventory_cycle(-0.10, -0.08)
        assert r.stage == STAGE_ACTIVE_DESTOCK

    def test_industry_hints_present(self):
        r = inventory_cycle(0.10, -0.05)
        assert len(r.industry_hints) > 0

    def test_missing(self):
        assert inventory_cycle(None, 0.05) is None


class TestM1M2Scissors:
    def test_activating(self):
        # M1 12%, M2 8% → +4% >2% → 活化
        r = m1_m2_scissors(0.12, 0.08)
        assert r.scissors == pytest.approx(0.04)
        assert r.verdict == "activating"

    def test_termifying(self):
        r = m1_m2_scissors(0.05, 0.10)
        assert r.verdict == "termifying"

    def test_neutral(self):
        r = m1_m2_scissors(0.08, 0.09)
        assert r.verdict == "neutral"

    def test_missing(self):
        assert m1_m2_scissors(None, 0.08) is None


class TestCreditCycle:
    def test_easing(self):
        # 社融 10%, M2 9% → 宽信用
        r = credit_cycle(0.10, 0.09)
        assert r.phase == "easing"
        assert "扩张" in r.rationale

    def test_tightening(self):
        # 社融 2%, M2 2% → 紧信用
        r = credit_cycle(0.02, 0.02)
        assert r.phase == "tightening"

    def test_stable(self):
        # 社融高但 M2 低 → 中性
        r = credit_cycle(0.10, 0.01)
        assert r.phase == "stable"

    def test_missing_sf(self):
        assert credit_cycle(None, 0.08) is None
