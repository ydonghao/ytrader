"""预期收益率分解纯函数测试。课程：目标 15%、隐含增速门槛 10%。"""
import pytest

from src.domain.market.fundamental.expected_return import expected_return


class TestExpectedReturn:
    def test_meets_target(self):
        # 12% 增长 + 3% 股息 = 15%
        r = expected_return(12, 3)
        assert r["expected_return"] == pytest.approx(15.0)
        assert r["meets_target"] is True
        assert r["implied_growth_floor_met"] is True

    def test_below_target(self):
        # 5% 增长 + 7% 股息 = 12%（高股息弥补不了低增长）
        r = expected_return(5, 7)
        assert r["expected_return"] == pytest.approx(12.0)
        assert r["meets_target"] is False
        assert r["implied_growth_floor_met"] is False

    def test_with_valuation_drift(self):
        r = expected_return(12, 3, valuation_drift=-5)
        assert r["expected_return"] == pytest.approx(10.0)

    def test_none_inputs_treated_zero(self):
        r = expected_return(None, None)
        assert r["expected_return"] == 0.0
        assert r["meets_target"] is False

    def test_negative_growth(self):
        # 业绩下滑（格力型）
        r = expected_return(-3, 7)
        assert r["expected_return"] == pytest.approx(4.0)
        assert r["implied_growth_floor_met"] is False
