"""优化策略 on_rebalance 集成测试。

用合成 K 线（不同波动率）验证各策略产出合法 RebalanceSignal，
并覆盖降级路径（标的不足 / 历史不足）。
"""
import datetime as dt

import numpy as np
import pytest

from src.domain.market.sync.sync_provider import OHLCVBar
from src.domain.market.strategy.longterm.strategies import build_strategy


def _synth_bars(sym, n, start_price, daily_vol, seed=0):
    """合成 n 根日线：随机游走 + 给定日波动率。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, daily_vol, size=n)
    prices = start_price * np.cumprod(1 + rets)
    out = []
    base = dt.date(2024, 1, 1)
    for i, p in enumerate(prices):
        out.append(OHLCVBar(
            symbol=sym,
            trade_time=dt.datetime(2024, 1, 1) + dt.timedelta(days=i),
            open_=p, close_=p, high_=p * 1.01, low_=p * 0.99, volume=1000.0,
        ))
    return out


def _three_asset_bars():
    """三资产：低波动/中波动/高波动。"""
    return {
        "low_vol": _synth_bars("low_vol", 150, 10.0, 0.005, seed=1),
        "mid_vol": _synth_bars("mid_vol", 150, 10.0, 0.015, seed=2),
        "high_vol": _synth_bars("high_vol", 150, 10.0, 0.04, seed=3),
    }


TODAY = dt.date(2024, 6, 1)


class TestRiskParityStrategy:
    def test_produces_valid_weights(self):
        strat = build_strategy("risk_parity", {"max_weight": 0.6, "cash_buffer": 0.0})
        sig = strat.on_rebalance(TODAY, _three_asset_bars())
        assert sig.target_weights
        assert sum(sig.target_weights.values()) == pytest.approx(1.0, abs=1e-3)
        assert all(w >= 0 for w in sig.target_weights.values())
        assert all(w <= 0.6 + 1e-3 for w in sig.target_weights.values())

    def test_low_vol_gets_more_weight(self):
        strat = build_strategy("risk_parity", {"max_weight": 0.9, "cash_buffer": 0.0})
        sig = strat.on_rebalance(TODAY, _three_asset_bars())
        w = sig.target_weights
        # 低波动资产权重应高于高波动
        assert w["low_vol"] > w["high_vol"]

    def test_degrades_when_fewer_than_two_symbols(self):
        strat = build_strategy("risk_parity", {})
        sig = strat.on_rebalance(TODAY, {"only": _synth_bars("only", 150, 10, 0.01)})
        assert sig.target_weights == {}


class TestMinVarianceStrategy:
    def test_produces_valid_weights(self):
        strat = build_strategy("min_variance", {"max_weight": 0.5, "cash_buffer": 0.05})
        sig = strat.on_rebalance(TODAY, _three_asset_bars())
        assert sum(sig.target_weights.values()) == pytest.approx(0.95, abs=1e-3)
        assert all(w <= 0.5 + 1e-3 for w in sig.target_weights.values())

    def test_concentrates_on_low_vol(self):
        strat = build_strategy("min_variance", {"max_weight": 0.9, "cash_buffer": 0.0})
        sig = strat.on_rebalance(TODAY, _three_asset_bars())
        w = sig.target_weights
        assert w["low_vol"] > w["high_vol"]


class TestMVOStrategy:
    def test_produces_valid_weights(self):
        strat = build_strategy("mvo", {"max_weight": 0.5, "cash_buffer": 0.05})
        sig = strat.on_rebalance(TODAY, _three_asset_bars())
        assert sum(sig.target_weights.values()) == pytest.approx(0.95, abs=1e-3)
        assert sig.target_weights  # 非空

    def test_meta_has_risk_free_rate_param(self):
        strat = build_strategy("mvo", {"risk_free_rate": 0.02})
        keys = [p["key"] for p in strat.meta()["params"]]
        assert "risk_free_rate" in keys


class TestEqualWeightStrategy:
    def test_equal_weights(self):
        strat = build_strategy("equal_weight", {"cash_buffer": 0.0})
        sig = strat.on_rebalance(TODAY, _three_asset_bars())
        w = sig.target_weights
        assert len(w) == 3
        assert all(v == pytest.approx(1 / 3, abs=1e-6) for v in w.values())

    def test_respects_cash_buffer(self):
        strat = build_strategy("equal_weight", {"cash_buffer": 0.1})
        sig = strat.on_rebalance(TODAY, _three_asset_bars())
        assert sum(sig.target_weights.values()) == pytest.approx(0.9, abs=1e-6)

    def test_empty_when_no_bars(self):
        strat = build_strategy("equal_weight", {})
        sig = strat.on_rebalance(TODAY, {})
        assert sig.target_weights == {}


class TestFrontierCompute:
    def test_returns_frontier_points(self):
        from src.domain.market.strategy.optimization.mvo import (
            efficient_frontier_compute,
        )
        result = efficient_frontier_compute(
            _three_asset_bars(), lookback=120, n_points=10
        )
        assert "symbols" in result
        assert len(result["symbols"]) == 3
        assert len(result["frontier"]) >= 2
        assert result["min_variance"] is not None
        assert result["max_sharpe"] is not None
        # min_variance 风险应为前沿最小
        risks = [p["risk"] for p in result["frontier"]]
        assert result["min_variance"]["risk"] == pytest.approx(min(risks), abs=1e-4)

    def test_warning_when_insufficient_symbols(self):
        from src.domain.market.strategy.optimization.mvo import (
            efficient_frontier_compute,
        )
        result = efficient_frontier_compute(
            {"only": _synth_bars("only", 150, 10, 0.01)}, lookback=120
        )
        assert result["frontier"] == []
        assert "warning" in result
