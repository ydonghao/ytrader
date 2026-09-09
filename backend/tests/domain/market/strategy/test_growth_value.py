"""成长vs价值分类 + 相对强度纯函数测试。"""
import pytest

from src.domain.market.strategy.growth_value import (
    classify_growth_value,
    STYLE_GROWTH,
    STYLE_VALUE,
    STYLE_BALANCED,
)
from src.domain.market.strategy.relative_strength import (
    relative_strength,
    rs_line,
    rs_trend,
    rank_relative_strength,
)


class TestClassifyGrowthValue:
    def test_quality_growth(self):
        # 增速 30%, PE 40, ROE 20% → 成长型+高质量
        r = classify_growth_value(0.30, 40, 0.20)
        assert r.style == STYLE_GROWTH
        assert r.quality == "quality"
        # PEG = 40/30 ≈ 1.33
        assert r.peg == pytest.approx(40 / 30, rel=1e-3)

    def test_low_quality_growth(self):
        # 增速高但 ROE 低 → weak
        r = classify_growth_value(0.25, 50, 0.05)
        assert r.style == STYLE_GROWTH
        assert r.quality == "weak"

    def test_deep_value(self):
        # 增速 3%, PE 10, ROE 12% → 价值型+深度价值
        r = classify_growth_value(0.03, 10, 0.12)
        assert r.style == STYLE_VALUE
        assert r.quality == "quality"

    def test_value_trap_risk(self):
        # 低增速 + 低 ROE → trap_risk
        r = classify_growth_value(0.02, 8, 0.05)
        assert r.style == STYLE_VALUE
        assert r.quality == "trap_risk"

    def test_balanced_garp(self):
        r = classify_growth_value(0.10, 20, 0.15)
        assert r.style == STYLE_BALANCED

    def test_peg_annotation(self):
        # PEG <1 标注低估
        r = classify_growth_value(0.30, 20, 0.18)  # PEG=0.67
        assert "PEG" in r.rationale and "偏低" in r.rationale

    def test_missing(self):
        assert classify_growth_value(None, 20) is None
        assert classify_growth_value(0.1, None) is None


class TestRelativeStrength:
    def test_outperform(self):
        r = relative_strength(0.20, 0.10)
        assert r.excess == pytest.approx(0.10)
        assert r.outperform is True

    def test_underperform(self):
        r = relative_strength(0.05, 0.15)
        assert r.outperform is False

    def test_missing(self):
        assert relative_strength(None, 0.1) is None


class TestRsLine:
    def test_rising_rs(self):
        # 标的翻倍, 基准持平 → RS 从 1 升到 2
        rs = rs_line([10, 12, 15, 20], [100, 100, 100, 100])
        assert rs[0] == pytest.approx(1.0)
        assert rs[-1] == pytest.approx(2.0)

    def test_falling_rs(self):
        rs = rs_line([10, 10, 10], [100, 110, 121])
        assert rs[-1] < 1.0

    def test_length_mismatch(self):
        assert rs_line([10, 12], [100]) is None

    def test_empty(self):
        assert rs_line([], []) is None


class TestRsTrend:
    def test_strengthening(self):
        rs = [1.0, 1.1, 1.2, 1.3]
        r = rs_trend(rs)
        assert r.strengthening is True
        assert r.verdict == "outperform"
        assert r.latest == pytest.approx(1.3)

    def test_weakening(self):
        rs = [1.2, 1.1, 1.0, 0.9]
        r = rs_trend(rs)
        assert r.strengthening is False
        assert r.verdict == "underperform"

    def test_too_short(self):
        assert rs_trend([1.0]) is None
        assert rs_trend([]) is None


class TestRankRelativeStrength:
    def test_ranking_descending(self):
        bench = [100, 100, 100, 100]
        targets = {
            "A": [10, 12, 14, 16],   # 翻 1.6x → RS 1.6
            "B": [10, 9, 8, 7],      # 跌 → RS 0.7
            "C": [10, 11, 12, 13],   # RS 1.3
        }
        rank = rank_relative_strength(targets, bench)
        assert rank is not None
        assert [e.symbol for e in rank] == ["A", "C", "B"]
        assert rank[0].outperform is True
        assert rank[-1].outperform is False

    def test_empty(self):
        assert rank_relative_strength({}, [100, 110]) is None
        assert rank_relative_strength({"A": [1, 2]}, []) is None

    def test_length_mismatch_skipped(self):
        bench = [100, 100]
        rank = rank_relative_strength({"A": [10, 11, 12], "B": [10, 11]}, bench)
        # 只有 B 长度匹配
        assert rank is not None
        assert [e.symbol for e in rank] == ["B"]
