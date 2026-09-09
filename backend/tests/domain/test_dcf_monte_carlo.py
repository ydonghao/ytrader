"""DCF 蒙特卡洛模拟测试。"""
import pytest

from src.domain.market.fundamental.dcf import dcf_monte_carlo, dcf_intrinsic_value


class TestDcfMonteCarlo:
    def test_basic(self):
        mc = dcf_monte_carlo(100, growth_mean=0.08, growth_std=0.03,
                             wacc_mean=0.09, wacc_std=0.01, seed=42)
        assert mc is not None
        assert mc["mean"] > 0
        assert mc["std"] > 0
        assert mc["p5"] < mc["p50"] < mc["p95"]
        assert mc["sample_size"] > 100

    def test_zero_fcf_returns_none(self):
        assert dcf_monte_carlo(0) is None

    def test_negative_fcf_returns_none(self):
        assert dcf_monte_carlo(-50) is None

    def test_reproducible_with_same_seed(self):
        mc1 = dcf_monte_carlo(100, seed=42)
        mc2 = dcf_monte_carlo(100, seed=42)
        assert mc1["mean"] == mc2["mean"]
        assert mc1["std"] == mc2["std"]

    def test_higher_std_wider_distribution(self):
        mc_narrow = dcf_monte_carlo(100, growth_std=0.01, wacc_std=0.005, seed=42)
        mc_wide = dcf_monte_carlo(100, growth_std=0.05, wacc_std=0.02, seed=42)
        assert mc_wide["std"] > mc_narrow["std"]
        assert mc_wide["cv"] > mc_narrow["cv"]

    def test_histogram_structure(self):
        mc = dcf_monte_carlo(100, seed=42)
        assert len(mc["histogram"]) == 20
        assert all(h["count"] >= 0 for h in mc["histogram"])
        assert sum(h["count"] for h in mc["histogram"]) == mc["sample_size"]

    def test_mean_close_to_deterministic(self):
        """蒙特卡洛均值应接近确定性 DCF（g=mean, wacc=mean）。"""
        det = dcf_intrinsic_value(100, 0.08, 0.03, 0.09, 10)
        mc = dcf_monte_carlo(100, growth_mean=0.08, growth_std=0.02,
                             wacc_mean=0.09, wacc_std=0.005, seed=42)
        assert abs(mc["mean"] - det) / det < 0.20

    def test_percentiles_ordered(self):
        mc = dcf_monte_carlo(100, seed=42)
        assert mc["p5"] <= mc["p25"] <= mc["p50"] <= mc["p75"] <= mc["p95"]
