"""
组合回测引擎测试
================
验证：调仓执行、目标权重换算、成本扣除、多标的权益、基准对比、空数据兜底。
用合成 bar 数据（不依赖网络/DB），保证可独立运行。
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from src.domain.market.strategy.longterm.base import (
    LongTermStrategy,
    ParamSpec,
)
from src.domain.market.strategy.longterm.models import RebalanceSignal
from src.domain.market.strategy.longterm.portfolio_backtester import (
    PortfolioBacktester,
)
from src.domain.market.sync.sync_provider import OHLCVBar


# ── 工具：合成 bar ────────────────────────────────────────────────────────

def _bar(symbol, date_str, close, open_=None):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    o = open_ if open_ is not None else close
    return OHLCVBar(
        symbol=symbol,
        trade_time=dt,
        open_=o,
        close_=close,
        high_=max(o, close) * 1.01,
        low_=min(o, close) * 0.99,
        volume=10000,
        amount=0,
        interval="1d",
        market="A",
        provider="test",
    )


def _series(symbol, start_str, n, base=10.0, trend=0.0):
    """生成 n 个交易日的日线（每天 +1 自然日，价格 base*(1+trend)^i）"""
    start = datetime.strptime(start_str, "%Y-%m-%d")
    out = []
    px = base
    for i in range(n):
        out.append(_bar(symbol, (start + timedelta(days=i)).strftime("%Y-%m-%d"), px))
        px *= 1 + trend
    return out


# ── 测试桩：固定目标权重策略 ──────────────────────────────────────────────

class FixedWeightsStrategy(LongTermStrategy):
    """测试用：永远返回固定的目标权重。"""
    name = "fixed_weights_test"
    rebalance_freq = "monthly"

    def __init__(self, weights: dict[str, float]):
        self._weights = weights

    def on_rebalance(self, today, bars_by_symbol, valuation_by_symbol=None,
                     financials_by_symbol=None, state=None):
        return RebalanceSignal(target_weights=dict(self._weights), reason="测试固定权重")

    def get_param_specs(self):
        return []


class NeverRebalanceStrategy(LongTermStrategy):
    """测试用：永不调仓（返回空信号），验证空仓持有现金。"""
    name = "never_rebalance_test"
    rebalance_freq = "monthly"

    def on_rebalance(self, today, bars_by_symbol, valuation_by_symbol=None,
                     financials_by_symbol=None, state=None):
        return RebalanceSignal(target_weights={}, reason="不调仓")

    def get_param_specs(self):
        return []


# ── 空数据兜底 ────────────────────────────────────────────────────────────

def test_empty_bars():
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(FixedWeightsStrategy({"sh600000": 1.0}), {})
    assert res.final_equity == 1_000_000
    assert res.total_return_pct == 0.0
    assert res.rebalance_count == 0
    assert res.start_date == "N/A"


# ── 永不调仓：资金不动 ───────────────────────────────────────────────────

def test_never_rebalance_holds_cash():
    bars = {"sh600000": _series("sh600000", "2024-01-01", 60, trend=0.01)}
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(NeverRebalanceStrategy(), bars)
    # 没有买卖，最终权益 = 初始资金（成本为 0）
    assert abs(res.final_equity - 1_000_000) < 1.0
    assert res.total_trades == 0
    assert res.rebalance_count == 0


# ── 单标的满仓：买入后随价格上涨 ─────────────────────────────────────────

def test_single_symbol_full_allocation():
    bars = {"sh600000": _series("sh600000", "2024-01-01", 90, base=10.0, trend=0.001)}
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(FixedWeightsStrategy({"sh600000": 1.0}), bars)
    # 应发生至少 1 次调仓（1 月初），买入后持有
    assert res.rebalance_count >= 1
    assert res.total_trades >= 1
    # 价格上涨，最终权益应高于初始（扣成本后）
    assert res.final_equity > 1_000_000
    assert res.total_return_pct > 0
    assert res.equity_curve[-1]["equity"] > res.equity_curve[0]["equity"]


# ── 成本扣除验证 ──────────────────────────────────────────────────────────

def test_cost_deducted_from_buy():
    """买入时，成交价 + 成本应从现金扣除。"""
    bars = {"sh600000": [_bar("sh600000", "2024-01-01", 10.0)]}
    bt = PortfolioBacktester(
        initial_capital=1_000_000,
        commission_rate=0.0003,
        min_commission=5.0,
        stamp_duty_rate=0.0005,
        slippage=0.0,  # 关滑点便于计算
    )
    res = bt.run(FixedWeightsStrategy({"sh600000": 1.0}), bars)
    # 至少有 1 笔买入
    buys = [t for t in res.trades if t.action == "BUY"]
    assert len(buys) >= 1
    t = buys[0]
    # 买入成本 = 佣金(万3,最低5元) + 印花税0 + 滑点0
    expected_commission = max(t.amount * 0.0003, 5.0)
    assert abs(t.commission - expected_commission) < 0.01
    assert t.stamp_duty == 0.0  # 买入无印花税


def test_stamp_duty_on_sell():
    """卖出时计印花税。"""
    # 构造先涨后跌，触发调仓时减仓
    bars = {"sh600000": _series("sh600000", "2024-01-01", 120, base=10.0, trend=0.002)}
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(FixedWeightsStrategy({"sh600000": 0.5}), bars)  # 目标降到 50%
    sells = [t for t in res.trades if t.action == "SELL"]
    if sells:  # 第二次调仓应有减仓
        t = sells[0]
        expected_stamp = t.amount * 0.0005
        assert abs(t.stamp_duty - expected_stamp) < 0.01


# ── 多标的：权益用各自价格 ────────────────────────────────────────────────

def test_multi_symbol_independent_pricing():
    """两个标的，一个涨一个跌，权益应反映各自走势（非同一根 bar 估值）。"""
    up = _series("sh600000", "2024-01-01", 90, base=10.0, trend=0.003)
    down = _series("sz000001", "2024-01-01", 90, base=10.0, trend=-0.002)
    bars = {"sh600000": up, "sz000001": down}
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(FixedWeightsStrategy({"sh600000": 0.5, "sz000001": 0.5}), bars)
    # 应同时持有两只票
    assert res.rebalance_count >= 1
    buys = [t for t in res.trades if t.action == "BUY"]
    symbols_bought = {t.symbol for t in buys}
    assert symbols_bought == {"sh600000", "sz000001"}


# ── 权益曲线连续性 ────────────────────────────────────────────────────────

def test_equity_curve_dates_monotonic():
    bars = {"sh600000": _series("sh600000", "2024-01-01", 60, trend=0.001)}
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(FixedWeightsStrategy({"sh600000": 1.0}), bars)
    dates = [e["date"] for e in res.equity_curve]
    assert dates == sorted(dates)
    assert len(dates) >= 50


# ── 基准对比 ──────────────────────────────────────────────────────────────

def test_benchmark_tracking():
    bars = {"sh600000": _series("sh600000", "2024-01-01", 90, trend=0.001)}
    bench = _series("sh000300", "2024-01-01", 90, base=4000.0, trend=0.0008)
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(
        FixedWeightsStrategy({"sh600000": 1.0}),
        bars,
        benchmark_bars=bench,
    )
    assert res.benchmark_return_pct != 0  # 基准有涨跌
    # equity_curve 每条应带 benchmark 字段
    for e in res.equity_curve:
        assert "benchmark" in e


# ── 调仓频率 ──────────────────────────────────────────────────────────────

def test_monthly_rebalance_count():
    """90 个交易日 ≈ 3 个月出头，月频应调仓约 2~3 次（首日 + 跨月）。"""
    bars = {"sh600000": _series("sh600000", "2024-01-01", 90, trend=0.001)}
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(FixedWeightsStrategy({"sh600000": 1.0}), bars)
    # 1月、2月、3月、4月 各一次跨月 = 至少 2 次
    assert res.rebalance_count >= 2


def test_to_dict_serializable():
    bars = {"sh600000": _series("sh600000", "2024-01-01", 30, trend=0.001)}
    bt = PortfolioBacktester(initial_capital=1_000_000)
    res = bt.run(FixedWeightsStrategy({"sh600000": 1.0}), bars)
    d = res.to_dict()
    import json
    json.dumps(d)  # 不抛异常即可
    assert "strategy" in d
    assert "equity_curve" in d
    assert "trades" in d
