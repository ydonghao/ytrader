"""均值±1σ 估值带纯函数测试。"""
import pytest

from src.domain.market.fundamental.valuation_band import valuation_band

# [10,12,14,16,18,20] → mean=15, std≈3.4157, μ-σ≈11.584, μ+σ≈18.416
SERIES = [10, 12, 14, 16, 18, 20]


class TestValuationBand:
    def test_mean_std(self):
        r = valuation_band(SERIES, 15)
        assert r["mean"] == pytest.approx(15.0)
        assert r["std"] == pytest.approx(3.4157, abs=0.001)

    def test_oversold(self):
        r = valuation_band(SERIES, 10)
        assert r["state"] == "超跌"
        assert r["z_score"] < 0

    def test_reasonable_low(self):
        r = valuation_band(SERIES, 14)
        assert r["state"] == "合理偏低"

    def test_reasonable_high(self):
        r = valuation_band(SERIES, 16)
        assert r["state"] == "合理偏高"

    def test_bubble(self):
        r = valuation_band(SERIES, 21)
        assert r["state"] == "虚高"
        assert r["z_score"] > 0

    def test_window(self):
        # 取末 3 个 [16,18,20] → mean=18
        r = valuation_band(SERIES, 17, window=3)
        assert r["mean"] == pytest.approx(18.0)

    def test_too_few_samples(self):
        assert valuation_band([10], 10) is None

    def test_zero_std(self):
        # 全相同 → std=0；current==mean → 合理偏低
        r = valuation_band([10, 10, 10], 10)
        assert r["std"] == 0
        assert r["state"] == "合理偏低"
        r2 = valuation_band([10, 10, 10], 12)
        assert r2["state"] == "虚高"

    def test_invalid_current(self):
        assert valuation_band(SERIES, None) is None
        assert valuation_band(SERIES, "x") is None

    def test_filters_non_numeric(self):
        r = valuation_band([10, None, 12, "x", 14, 16, 18, 20], 10)
        assert r["state"] == "超跌"
