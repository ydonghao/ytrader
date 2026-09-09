"""DDM 股利折现纯函数测试。课程案例：长江电力 230 亿分红、r=5.5%、g=2%。"""
import pytest

from src.domain.market.fundamental.ddm import (
    ddm_intrinsic_value,
    ddm_margin_of_safety,
)


class TestDdmIntrinsicValue:
    def test_changjiang_case(self):
        # 230 * 1.02 / (0.055 - 0.02) = 234.6 / 0.035 ≈ 6702.86 亿
        v = ddm_intrinsic_value(230, growth_rate=0.02, discount_rate=0.055)
        assert v == pytest.approx(6702.86, abs=0.01)

    def test_default_params(self):
        # 默认 g=2%, r=5.5%
        v = ddm_intrinsic_value(100)
        assert v == pytest.approx(100 * 1.02 / 0.035, abs=0.01)

    def test_zero_dividend(self):
        assert ddm_intrinsic_value(0) is None
        assert ddm_intrinsic_value(-10) is None

    def test_rate_invalid(self):
        # r <= g 无法计算
        assert ddm_intrinsic_value(100, growth_rate=0.06, discount_rate=0.05) is None
        assert ddm_intrinsic_value(100, growth_rate=0.05, discount_rate=0.05) is None


class TestDdmMarginOfSafety:
    def test_overvalued(self):
        # 内在 6702.86 vs 市值 7338 → 高估约 -8.66%
        m = ddm_margin_of_safety(6702.86, 7338)
        assert m == pytest.approx(-0.0866, abs=0.001)

    def test_undervalued(self):
        assert ddm_margin_of_safety(1000, 800) == pytest.approx(0.25)

    def test_invalid(self):
        assert ddm_margin_of_safety(None, 100) is None
        assert ddm_margin_of_safety(1000, 0) is None
