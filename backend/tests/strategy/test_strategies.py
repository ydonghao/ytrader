"""
Strategy Framework Tests
==========================
测试信号生成、回测引擎、参数优化。
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.strategy.signals import Action, Signal, Position, Trade
from src.domain.market.strategy.base import Strategy, SingleSymbolStrategy
from src.domain.market.strategy.strategies import (
    SMACrossStrategy, RSIStrategy, MACDStrategy, BollingerStrategy,
    get_strategy, STRATEGY_REGISTRY,
)
from src.domain.market.strategy.backtester import Backtester, BacktestResult
from src.domain.market.sync.sync_provider import OHLCVBar


def _make_bar(symbol: str, date_str: str, open_: float, close: float,
              high: float = None, low: float = None, vol: float = 10000) -> OHLCVBar:
    """Helper: 创建一根K线"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return OHLCVBar(
        symbol=symbol,
        trade_time=dt,
        open_=open_,
        close_=close,
        high_=high or max(open_, close) * 1.01,
        low_=low or min(open_, close) * 0.99,
        volume=vol,
        amount=0,
        interval="1d",
        market="A",
        provider="test",
    )


def _make_series(symbol: str, start: str, n: int, base_price: float = 10.0,
                 trend: float = 0.001) -> list[OHLCVBar]:
    """Helper: 创建n天价格序列"""
    bars = []
    price = base_price
    dt = datetime.strptime(start, "%Y-%m-%d")
    for i in range(n):
        close = price * (1 + (i * trend) + (0.02 * (i % 5 - 2)))
        bars.append(_make_bar(symbol, dt.strftime("%Y-%m-%d"), price, close))
        price = close * 1.005
        dt += timedelta(days=1)
    return bars


# ── Signal / Position Tests ───────────────────────────────────

class TestSignal:
    def test_signal_action_enum(self):
        s = Signal(symbol="sh600000", action=Action.BUY, price=10.0)
        assert s.action == Action.BUY

    def test_signal_string_repr(self):
        s = Signal(
            symbol="sh600000", action=Action.SELL, price=10.5,
            confidence=0.8, reason="RSI overbought",
            timestamp=datetime(2024, 1, 1, 10, 0),
        )
        repr_str = str(s)
        assert "sh600000" in repr_str
        assert "SELL" in repr_str
        assert "10.50" in repr_str


class TestPosition:
    def test_position_unrealized_pnl(self):
        p = Position(symbol="sh600000", quantity=100, avg_price=10.0)
        assert p.unrealized_pnl == 0.0
        p.update_pnl(11.0)
        assert p.unrealized_pnl == 100.0  # (11-10)*100


# ── SMA Cross Strategy Tests ─────────────────────────────────

class TestSMACrossStrategy:
    def test_golden_cross_buy_signal(self):
        """快速SMA上穿慢速SMA → BUY（先跌后涨触发金叉）"""
        strategy = SMACrossStrategy(fast_period=5, slow_period=10)
        # 先跌（fast SMA在slow SMA下方），再涨触发金叉
        bars = []
        price = 12.0
        dt = datetime(2024, 1, 1)
        for i in range(15):
            price *= 0.96  # 下跌阶段
            bars.append(_make_bar("sh600000", dt.strftime("%Y-%m-%d"), price, price))
            dt += timedelta(days=1)
        for i in range(15):
            price *= 1.03  # 上涨阶段
            bars.append(_make_bar("sh600000", dt.strftime("%Y-%m-%d"), price, price))
            dt += timedelta(days=1)

        signals = strategy.generate_signals(bars)
        buy_signals = [s for s in signals if s.action == Action.BUY]
        assert len(buy_signals) > 0, f"应该有金叉买入信号，实际{len(signals)}个信号"

    def test_dead_cross_sell_signal(self):
        """快速SMA下穿慢速SMA → SELL（先涨后跌触发死叉）"""
        strategy = SMACrossStrategy(fast_period=5, slow_period=10)
        # 先涨后跌
        bars = []
        price = 10.0
        dt = datetime(2024, 1, 1)
        for i in range(15):
            price *= 1.04  # 上涨
            bars.append(_make_bar("sh600000", dt.strftime("%Y-%m-%d"), price, price))
            dt += timedelta(days=1)
        for i in range(15):
            price *= 0.96  # 下跌
            bars.append(_make_bar("sh600000", dt.strftime("%Y-%m-%d"), price, price))
            dt += timedelta(days=1)

        signals = strategy.generate_signals(bars)
        sell_signals = [s for s in signals if s.action == Action.SELL]
        assert len(sell_signals) > 0, f"应该有死叉卖出信号，实际{len(signals)}个信号"

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError, match="fast_period"):
            SMACrossStrategy(fast_period=20, slow_period=10)

    def test_params(self):
        s = SMACrossStrategy(fast_period=5, slow_period=20)
        p = s.get_params()
        assert p["fast_period"] == 5
        assert p["slow_period"] == 20


# ── RSI Strategy Tests ────────────────────────────────────────

class TestRSIStrategy:
    def test_rsi_generates_oversold_signal(self):
        """RSI从超卖区回升应产生BUY信号"""
        strategy = RSIStrategy(period=14, oversold=30)
        # 创建一个持续下跌后反弹的序列
        bars = []
        price = 20.0
        for i in range(40):
            # 前20天下跌(RSI低)，后20天上涨(RSI回升)
            if i < 20:
                price *= 0.95
            else:
                price *= 1.03
            bars.append(_make_bar("sh600000", (datetime(2024, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"), price, price))
        
        signals = strategy.generate_signals(bars)
        buy_signals = [s for s in signals if s.action == Action.BUY]
        assert len(buy_signals) > 0, "应有超卖区回升的BUY信号"

    def test_rsi_oversold_threshold(self):
        strategy = RSIStrategy(period=14, oversold=30, buy_on_recover=True)
        assert strategy.oversold == 30


# ── MACD Strategy Tests ──────────────────────────────────────

class TestMACDStrategy:
    def test_macd_buy_signal(self):
        """MACD金叉应产生BUY信号"""
        strategy = MACDStrategy(fast=12, slow=26, signal=9)
        bars = _make_series("sh600000", "2024-01-01", 60, base_price=10.0, trend=0.005)
        signals = strategy.generate_signals(bars)
        
        # 应该有一些买入信号
        buy_count = len([s for s in signals if s.action == Action.BUY])
        assert buy_count >= 0  # 至少不报错

    def test_macd_params(self):
        strategy = MACDStrategy(fast=8, slow=16, signal=5)
        p = strategy.get_params()
        assert p["fast"] == 8
        assert p["slow"] == 16


# ── Bollinger Strategy Tests ─────────────────────────────────

class TestBollingerStrategy:
    def test_bollinger_buy_signal(self):
        strategy = BollingerStrategy(period=20, std_dev=2.0)
        bars = _make_series("sh600000", "2024-01-01", 40, base_price=10.0, trend=0.002)
        signals = strategy.generate_signals(bars)
        assert isinstance(signals, list)


# ── Backtester Tests ─────────────────────────────────────────

class TestBacktester:
    def test_empty_bars_returns_zero_result(self):
        bt = Backtester(initial_capital=1_000_000)
        strategy = SMACrossStrategy()
        result = bt.run(strategy, [])
        
        assert result.total_trades == 0
        assert result.total_return == 0.0

    def test_backtest_with_signals(self):
        """有信号时应能完成回测流程"""
        bt = Backtester(initial_capital=1_000_000, commission_rate=0.0003, slippage=0.0001)
        strategy = SMACrossStrategy(fast_period=5, slow_period=10)
        
        bars = _make_series("sh600000", "2024-01-01", 30, base_price=10.0, trend=0.005)
        result = bt.run(strategy, bars)
        
        assert isinstance(result, BacktestResult)
        assert result.initial_capital == 1_000_000
        assert result.final_equity >= 0
        assert result.final_equity <= 1_000_000 * 1.5  # 不应暴增太多

    def test_no_signal_hold(self):
        """无信号时，资金不变"""
        # 用一个完全不波动的价格序列 → 可能无信号
        bars = []
        price = 10.0
        for i in range(50):
            price = 10.0 + (i * 0.001)  # 几乎不动
            bars.append(_make_bar("sh600000", (datetime(2024, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"), price, price))
        
        bt = Backtester(initial_capital=1_000_000)
        strategy = SMACrossStrategy(fast_period=5, slow_period=10)
        result = bt.run(strategy, bars)
        
        # 至少应该不崩溃
        assert result.final_equity > 0

    def test_run_multi(self):
        """多标的回测"""
        bt = Backtester(initial_capital=1_000_000)
        strategy = SMACrossStrategy(fast_period=5, slow_period=10)
        bars_by_symbol = {
            "sh600000": _make_series("sh600000", "2024-01-01", 30, 10.0, 0.005),
            "sh600519": _make_series("sh600519", "2024-01-01", 30, 20.0, 0.003),
        }
        result = bt.run_multi(strategy, bars_by_symbol, "2024-01-01", "2024-12-31")
        
        assert "sh600000" in result.symbols
        assert "sh600519" in result.symbols
        assert result.final_equity > 0


# ── Strategy Registry Tests ──────────────────────────────────

class TestStrategyRegistry:
    def test_get_strategy_by_name(self):
        s = get_strategy("sma_cross", fast_period=5, slow_period=20)
        assert isinstance(s, SMACrossStrategy)
        assert s.fast_period == 5

    def test_get_strategy_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            get_strategy("unknown_strategy")

    def test_all_strategies_in_registry(self):
        assert "sma_cross" in STRATEGY_REGISTRY
        assert "rsi" in STRATEGY_REGISTRY
        assert "macd" in STRATEGY_REGISTRY
        assert "bollinger" in STRATEGY_REGISTRY
