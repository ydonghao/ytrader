"""
参数寻优器测试
==============
验证：网格展开、自动派生 param_grid、寻优排序、不同 metric、异常处理。
用合成数据（不依赖网络/DB）。
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from src.domain.market.strategy.longterm.optimizer import (
    SUPPORTED_METRICS,
    LongTermGridOptimizer,
    _frange,
)
from src.domain.market.sync.sync_provider import OHLCVBar


# ── 合成数据 ──────────────────────────────────────────────────────────────

def _bar(symbol, date_str, close):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return OHLCVBar(
        symbol=symbol, trade_time=dt, open_=close, close_=close,
        high_=close * 1.01, low_=close * 0.99, volume=10000, amount=0,
        interval="1d", market="A", provider="test",
    )


def _series(symbol, start_str, n, base=10.0, trend=0.001):
    """n 个交易日的日线，每日 +1 自然日。"""
    start = datetime.strptime(start_str, "%Y-%m-%d")
    out = []
    px = base
    for i in range(n):
        out.append(_bar(symbol, (start + timedelta(days=i)).strftime("%Y-%m-%d"), px))
        px *= 1 + trend
    return out


# ── _frange 展开 ─────────────────────────────────────────────────────────

def test_frange_basic():
    assert _frange(2, 10, 2, max_points=5) == [2, 4, 6, 8, 10]


def test_frange_max_points():
    # 限制点数
    vals = _frange(0, 100, 1, max_points=4)
    assert len(vals) <= 4


def test_frange_degenerate():
    assert _frange(10, 2, 1) == [10]  # lo >= hi
    assert _frange(2, 10, 0) == [2]   # step <= 0


# ── 自动派生 param_grid ──────────────────────────────────────────────────

def test_derive_grid_from_paramspec():
    """sma_trend 有 symbol(select) + period(number)，应派生出 grid。"""
    grid = LongTermGridOptimizer._derive_grid("sma_trend")
    # period 是 number，应被展开
    assert "period" in grid
    assert len(grid["period"]) >= 2


def test_derive_grid_unknown_strategy():
    """未知策略返回空 dict（不抛异常）。"""
    grid = LongTermGridOptimizer._derive_grid("nonexistent_strategy")
    assert grid == {}


# ── 寻优器构造 ────────────────────────────────────────────────────────────

def test_optimizer_unsupported_metric():
    with pytest.raises(ValueError, match="不支持的指标"):
        LongTermGridOptimizer("sma_trend", metric="nonexistent")


def test_optimizer_supported_metrics():
    for m in SUPPORTED_METRICS:
        opt = LongTermGridOptimizer("sma_trend", metric=m)
        assert opt.metric == m


# ── 寻优执行 ──────────────────────────────────────────────────────────────

def test_optimize_sma_trend_basic():
    """单标的 SMA 趋势寻优：不同 period 组合应返回排序结果。"""
    bars = {"sh510300": _series("sh510300", "2024-01-01", 400, trend=0.001)}
    opt = LongTermGridOptimizer(
        strategy_name="sma_trend",
        param_grid={"period": [20, 50, 100, 200]},
        metric="total_return_pct",
        top_k=4,
    )
    result = opt.optimize(bars_by_symbol=bars)
    assert result.total_combos == 4
    assert len(result.comparison) <= 4
    assert result.best is not None
    # comparison 按收益降序
    rets = [c.total_return_pct for c in result.comparison]
    assert rets == sorted(rets, reverse=True)


def test_optimize_max_drawdown_ascending():
    """max_drawdown 指标应升序（越小越好）。"""
    bars = {"sh510300": _series("sh510300", "2024-01-01", 400, trend=0.001)}
    opt = LongTermGridOptimizer(
        strategy_name="sma_trend",
        param_grid={"period": [50, 100, 200]},
        metric="max_drawdown",
        top_k=3,
    )
    result = opt.optimize(bars_by_symbol=bars)
    dds = [c.max_drawdown for c in result.comparison]
    assert dds == sorted(dds)  # 升序


def test_optimize_auto_grid():
    """param_grid 为空时自动派生，能跑通。"""
    bars = {"sh510300": _series("sh510300", "2024-01-01", 400, trend=0.001)}
    opt = LongTermGridOptimizer(
        strategy_name="sma_trend",
        param_grid=None,  # 自动派生
        metric="sharpe_ratio",
        top_k=5,
    )
    result = opt.optimize(bars_by_symbol=bars)
    assert result.total_combos >= 1
    assert result.best_params  # 有最优参数


def test_optimize_to_dict_serializable():
    bars = {"sh510300": _series("sh510300", "2024-01-01", 200, trend=0.001)}
    opt = LongTermGridOptimizer(
        strategy_name="sma_trend",
        param_grid={"period": [50, 100]},
        metric="sharpe_ratio",
    )
    result = opt.optimize(bars_by_symbol=bars)
    import json
    d = result.to_dict()
    json.dumps(d)
    assert "best" in d
    assert "comparison" in d


def test_optimize_empty_grid_single_combo():
    """param_grid={} 是 falsy，会触发自动派生（symbol×period 组合）。
    验证空 dict 不会报错、能跑出结果。"""
    bars = {"sh510300": _series("sh510300", "2024-01-01", 200, trend=0.001)}
    opt = LongTermGridOptimizer(
        strategy_name="sma_trend",
        param_grid={},  # falsy → 自动派生
        metric="sharpe_ratio",
    )
    result = opt.optimize(bars_by_symbol=bars)
    # 自动派生会展开 symbol×period 多组合，不应是 0
    assert result.total_combos >= 1
    assert result.best is not None
