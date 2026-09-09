"""通用分位算法工具测试。"""
import datetime as dt
import pytest
from src.domain.market.fundamental.percentile import (
    calc_percentile,
    percentile_stats,
    downsample_monthly,
    SAMPLE_MIN,
)


def _big(samples_n: int) -> list[float]:
    """生成 >= SAMPLE_MIN 的样本，确保进入正常分位计算。"""
    return [float(i) for i in range(samples_n)]


class TestCalcPercentile:
    def test_basic(self):
        # 用足够大的样本测正常分位逻辑
        samples = _big(100)
        # current=0，<=0 的只有 0 自己（rank=1），分位 = 1/100 = 0.01
        assert calc_percentile(samples, 0) == pytest.approx(0.01)

    def test_current_at_max(self):
        samples = _big(100)
        assert calc_percentile(samples, 99.0) == pytest.approx(1.0)

    def test_current_below_min(self):
        samples = _big(100)
        assert calc_percentile(samples, -5.0) == pytest.approx(0.0)

    def test_current_between_samples(self):
        # 50 个样本 0..49，current=25 → <=25 有 26 个 → 26/50 = 0.52
        samples = _big(50)
        assert calc_percentile(samples, 25.0) == pytest.approx(0.52)

    def test_insufficient_samples_returns_none(self):
        assert calc_percentile([1.0, 2.0], 1.5) is None  # < SAMPLE_MIN

    def test_empty_samples_returns_none(self):
        assert calc_percentile([], 1.0) is None

    def test_exactly_30_samples(self):
        samples = [float(i) for i in range(SAMPLE_MIN)]
        assert calc_percentile(samples, 15) is not None

    def test_just_below_threshold_returns_none(self):
        samples = [float(i) for i in range(SAMPLE_MIN - 1)]
        assert calc_percentile(samples, 5.0) is None


class TestPercentileStats:
    def test_returns_full_stats(self):
        samples = [float(i) for i in range(30)]
        stats = percentile_stats(samples, 15.0)
        assert stats is not None
        assert stats["current"] == 15.0
        assert stats["sample_size"] == 30
        assert stats["min"] == 0.0
        assert stats["max"] == 29.0
        assert 0.4 < stats["percentile"] < 0.6

    def test_insufficient_returns_none(self):
        assert percentile_stats([1.0, 2.0], 1.5) is None

    def test_quantiles_nearest_rank(self):
        # 100 个样本 0..99，nearest-rank：p_q = ordered[round(q*(n-1))]
        samples = [float(i) for i in range(100)]
        stats = percentile_stats(samples, 50.0)
        # p25 = ordered[round(0.25*99)] = ordered[25] = 25
        assert stats["p25"] == 25.0
        # p50 = ordered[round(0.50*99)] = ordered[50] = 50（round(49.5)=50 最近偶数）
        assert stats["p50"] == 50.0
        # p75 = ordered[round(0.75*99)] = ordered[round(74.25)] = ordered[74] = 74
        assert stats["p75"] == 74.0


class TestDownsampleMonthly:
    def test_keeps_last_per_month(self):
        pts = [
            {"date": "2024-01-05", "value": 1.0},
            {"date": "2024-01-20", "value": 2.0},
            {"date": "2024-02-03", "value": 3.0},
            {"date": "2024-02-28", "value": 4.0},
        ]
        out = downsample_monthly(pts)
        assert len(out) == 2
        assert out[0]["value"] == 2.0  # 1月最后
        assert out[1]["value"] == 4.0  # 2月最后

    def test_empty(self):
        assert downsample_monthly([]) == []

    def test_skips_invalid_dates(self):
        pts = [{"date": "", "value": 1.0}, {"date": "2024-03-15", "value": 2.0}]
        out = downsample_monthly(pts)
        assert len(out) == 1
