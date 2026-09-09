"""成长性时序纯函数测试。"""
import pytest

from src.domain.market.fundamental.growth import (
    cagr,
    consecutive_declines,
    is_stagnant,
)


class TestCagr:
    def test_two_periods(self):
        # (121/100)^(1/2)-1 = 0.1
        assert cagr([100, 110, 121]) == pytest.approx(0.1)

    def test_explicit_periods(self):
        assert cagr([100, 110, 121, 133.1], periods=3) == pytest.approx(0.1)

    def test_negative_growth(self):
        # 100 → 81 over 2 years = -0.1
        assert cagr([100, 90, 81]) == pytest.approx(-0.1)

    def test_too_few(self):
        assert cagr([100]) is None
        assert cagr([]) is None

    def test_nonpositive_start(self):
        assert cagr([0, 100, 200]) is None
        assert cagr([-50, 100]) is None

    def test_filters_none_default_n(self):
        # None 被剔除，存活点 [100,121] 视为连续 1 期 → 21%
        assert cagr([100, None, 121]) == pytest.approx(0.21)

    def test_filters_none_with_periods(self):
        # 用 periods 显式指定真实跨度（2 期）→ 端点 100→121 = 10%
        assert cagr([100, None, 121], periods=2) == pytest.approx(0.1)


class TestConsecutiveDeclines:
    def test_basic(self):
        assert consecutive_declines([10, 12, 11, 9]) == 2

    def test_all_declining(self):
        assert consecutive_declines([20, 15, 10, 5]) == 3

    def test_none_declining(self):
        assert consecutive_declines([10, 12, 13]) == 0

    def test_too_few(self):
        assert consecutive_declines([10]) == 0


class TestIsStagnant:
    def test_flat_is_stagnant(self):
        # 格力型：8 年原地踏步
        assert is_stagnant([1800] * 9, years=8) is True

    def test_growing_not_stagnant(self):
        series = [100 * (1.1 ** i) for i in range(9)]  # 8 年 10% 增长
        assert is_stagnant(series, years=8) is False

    def test_insufficient_returns_none(self):
        assert is_stagnant([100, 110], years=8) is None
