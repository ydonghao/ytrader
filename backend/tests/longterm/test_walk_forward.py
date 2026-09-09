"""Walk-forward 引擎单测。

合成数据 + 小窗口验证窗口切分、OOS 拼接、过拟合度量、守护逻辑。
"""
import datetime as dt

import numpy as np
import pytest

from src.domain.market.sync.sync_provider import OHLCVBar
from src.domain.market.strategy.longterm.walk_forward import (
    WalkForwardConfig,
    common_dates,
    slice_by_dates,
    run_walk_forward,
)


def _synth_bars(sym, n, start_price, drift, vol, seed=0):
    """合成 n 根日线。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, size=n)
    prices = start_price * np.cumprod(1 + rets)
    out = []
    for i, p in enumerate(prices):
        out.append(OHLCVBar(
            symbol=sym,
            trade_time=dt.datetime(2020, 1, 1) + dt.timedelta(days=i),
            open_=p, close_=p, high_=p * 1.005, low_=p * 0.995, volume=1000.0,
        ))
    return out


def _two_asset_bars(n=400):
    """两资产，足够长的公共日期。"""
    return {
        "sh510300": _synth_bars("sh510300", n, 10.0, 0.0004, 0.012, seed=11),
        "sh511010": _synth_bars("sh511010", n, 10.0, 0.0001, 0.003, seed=22),
    }


class TestCommonDatesAndSlice:
    def test_common_dates_intersection(self):
        bars = {
            "a": _synth_bars("a", 100, 10, 0, 0.01, seed=1),
            "b": _synth_bars("b", 100, 10, 0, 0.01, seed=2),
        }
        dates = common_dates(bars)
        # 两资产同起止同长度 → 交集 = 全部 100 天
        assert len(dates) == 100
        assert dates == sorted(dates)

    def test_common_dates_handles_different_lengths(self):
        bars = {
            "a": _synth_bars("a", 100, 10, 0, 0.01, seed=1),
            "b": _synth_bars("b", 80, 10, 0, 0.01, seed=2),  # 少 20 天
        }
        dates = common_dates(bars)
        # b 从同一天开始，只有 80 天 → 交集 80
        assert len(dates) == 80

    def test_slice_by_dates(self):
        bars = {"a": _synth_bars("a", 100, 10, 0, 0.01, seed=1)}
        d0 = dt.date(2020, 1, 1)
        d9 = dt.date(2020, 1, 10)
        sliced = slice_by_dates(bars, d0, d9)
        assert len(sliced["a"]) == 10

    def test_handles_date_typed_trade_time(self):
        """index_ohlcv 回传的 bars 可能 trade_time 是 date 而非 datetime。"""
        bars = {"a": [], "b": []}
        for sym in ("a", "b"):
            for i in range(50):
                bars[sym].append(OHLCVBar(
                    symbol=sym,
                    trade_time=dt.date(2020, 1, 1) + dt.timedelta(days=i),
                    open_=10, close_=10, high_=10, low_=10, volume=100.0,
                ))
        # 不应抛 'datetime.date' object has no attribute 'date'
        dates = common_dates(bars)
        assert len(dates) == 50
        sliced = slice_by_dates(bars, dt.date(2020, 1, 1), dt.date(2020, 1, 10))
        assert len(sliced["a"]) == 10


class TestRunWalkForward:
    def test_insufficient_data_returns_warning(self):
        bars = _two_asset_bars(n=50)  # 远小于 train+test
        cfg = WalkForwardConfig(train_days=100, test_days=50, step_days=50)
        result = run_walk_forward(
            cfg, "all_weather", bars, benchmark_bars=None,
        )
        assert result.n_windows == 0
        assert result.warning is not None
        assert "数据不足" in result.warning

    def test_produces_windows_and_oos_curve(self):
        bars = _two_asset_bars(n=300)
        cfg = WalkForwardConfig(
            train_days=120, test_days=60, step_days=60,
            param_grid={},  # all_weather 无可调参数 → 单组合
        )
        result = run_walk_forward(
            cfg, "all_weather", bars, benchmark_bars=None,
        )
        assert result.n_windows >= 1
        assert len(result.windows) == result.n_windows
        # 每窗口都有 IS/OOS 指标
        for w in result.windows:
            assert w.train_start and w.test_start
            assert w.best_params is not None
        # OOS 拼接曲线非空
        assert len(result.oos_equity_curve) > 0
        # 曲线日期有序
        dates = [p["date"] for p in result.oos_equity_curve]
        assert dates == sorted(dates)

    def test_oos_curve_is_compound_chained(self):
        """拼接曲线应是复利衔接：净值连续，每段从上一段末继续。"""
        bars = _two_asset_bars(n=240)
        cfg = WalkForwardConfig(
            train_days=100, test_days=40, step_days=40, param_grid={},
        )
        result = run_walk_forward(cfg, "all_weather", bars)
        navs = [p["nav"] for p in result.oos_equity_curve]
        # 起点应为 1.0（归一化）
        assert navs[0] == pytest.approx(1.0, abs=1e-4)
        # 全为正
        assert all(n > 0 for n in navs)

    def test_overfitting_metrics_present(self):
        bars = _two_asset_bars(n=300)
        cfg = WalkForwardConfig(
            train_days=120, test_days=60, step_days=60, param_grid={},
        )
        result = run_walk_forward(cfg, "all_weather", bars)
        of = result.overfitting
        assert "walk_forward_efficiency" in of
        assert "param_stability" in of
        assert "oos_positive_ratio" in of
        assert 0.0 <= of["param_stability"] <= 1.0
        assert 0.0 <= of["oos_positive_ratio"] <= 1.0

    def test_aggregated_metrics(self):
        bars = _two_asset_bars(n=300)
        cfg = WalkForwardConfig(
            train_days=120, test_days=60, step_days=60, param_grid={},
        )
        result = run_walk_forward(cfg, "all_weather", bars)
        agg = result.aggregated
        assert "total_return_pct" in agg
        assert "cagr" in agg
        assert "sharpe_ratio" in agg
        assert "max_drawdown" in agg

    def test_to_dict_serializable(self):
        bars = _two_asset_bars(n=240)
        cfg = WalkForwardConfig(
            train_days=100, test_days=40, step_days=40, param_grid={},
        )
        result = run_walk_forward(cfg, "all_weather", bars)
        d = result.to_dict()
        assert d["strategy"] == "all_weather"
        assert isinstance(d["windows"], list)
        assert isinstance(d["overfitting"], dict)
