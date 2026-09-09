"""
做T算法测试
============
覆盖：成本模型、T+1 约束、收盘恢复底仓、网格策略触发、引擎汇总。
全部用构造的分钟线，无网络/akshare 依赖。
"""
import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.strategy.t_trading.cost_model import TCostModel
from src.domain.market.strategy.t_trading.t_backtester import TBacktester
from src.domain.market.strategy.t_trading.strategies import (
    build_strategy,
    algorithm_metas,
    T_STRATEGY_REGISTRY,
)
from src.domain.market.strategy.t_trading.models import TSignal
from src.domain.market.sync.sync_provider import OHLCVBar


# ── fixtures ───────────────────────────────────────────────────────────────────

def _bar(symbol, dt, price, interval="5m"):
    return OHLCVBar(
        symbol=symbol, trade_time=dt,
        open_=price, close_=price, high_=price, low_=price,
        volume=1000, amount=10000, interval=interval, market="A",
    )


def _swing_bars(symbol="sh600000"):
    """2 天震荡分钟线：先涨后跌再回升，足以触发网格/马丁。"""
    bars = []
    t0 = datetime(2024, 6, 3, 9, 30)
    day1 = [10.0, 10.1, 10.2, 10.3, 10.4, 10.3, 10.2,
            10.1, 10.0, 9.9, 9.8, 9.9, 10.0, 10.1]
    day2 = [10.0, 9.9, 9.8, 9.7, 9.8, 9.9, 10.0,
            10.1, 10.2, 10.1, 10.0, 10.1, 10.2, 10.1]
    for i, p in enumerate(day1):
        bars.append(_bar(symbol, t0 + timedelta(minutes=5 * i), p))
    for i, p in enumerate(day2):
        bars.append(_bar(
            symbol, t0 + timedelta(days=1) + timedelta(minutes=5 * i), p
        ))
    return bars


# ── TestCostModel ──────────────────────────────────────────────────────────────

class TestCostModel:
    """成本模型：佣金最低5元、印花税只计卖出、过户费双向"""

    def test_commission_min_floor(self):
        """小单佣金不足5元时取5元（做T关键成本）"""
        cm = TCostModel()
        cb = cm.calc(price=5.0, quantity=10, is_sell=False)
        # 5*10*0.00025 = 0.0125 < 5 → 取最低5元
        assert cb.commission == 5.0

    def test_commission_above_floor(self):
        """大单按费率计算佣金"""
        cm = TCostModel()
        cb = cm.calc(price=10.0, quantity=10000, is_sell=False)
        # 10*10000*0.00025 = 25 > 5
        assert cb.commission == pytest.approx(25.0)

    def test_stamp_duty_only_on_sell(self):
        """印花税仅在卖出时计提"""
        cm = TCostModel()
        buy = cm.calc(price=10.0, quantity=1000, is_sell=False)
        sell = cm.calc(price=10.0, quantity=1000, is_sell=True)
        assert buy.stamp_duty == 0.0
        assert sell.stamp_duty == pytest.approx(10.0 * 1000 * 0.0005)

    def test_transfer_fee_both_sides(self):
        """过户费买卖双向"""
        cm = TCostModel()
        buy = cm.calc(price=10.0, quantity=1000, is_sell=False)
        sell = cm.calc(price=10.0, quantity=1000, is_sell=True)
        expected = 10.0 * 1000 * 0.00001
        assert buy.transfer_fee == pytest.approx(expected)
        assert sell.transfer_fee == pytest.approx(expected)

    def test_total_property(self):
        """total = 四项之和"""
        cm = TCostModel()
        cb = cm.calc(price=10.0, quantity=1000, is_sell=True)
        assert cb.total == pytest.approx(
            cb.commission + cb.stamp_duty + cb.transfer_fee + cb.slippage
        )


# ── TestGridStrategy ───────────────────────────────────────────────────────────

class TestGridStrategy:
    """网格策略：价格下穿买入、上穿卖出"""

    def test_triggers_trades_on_swing(self):
        """震荡行情应产生买卖交易"""
        strat = build_strategy("grid", {"band_pct": 0.05, "grids": 4,
                                        "qty_per_grid": 100})
        bt = TBacktester(TCostModel(), base_shares=1000, cash_buffer=50000)
        res = bt.run(strat, _swing_bars())
        assert res.total_trades > 0
        assert res.total_buys > 0
        assert res.total_sells > 0

    def test_no_trades_on_flat(self):
        """完全平盘（价格不动）不应产生交易"""
        flat = [_bar("sh600000",
                     datetime(2024, 6, 3, 9, 30) + timedelta(minutes=5 * i),
                     10.0) for i in range(10)]
        strat = build_strategy("grid", {})
        bt = TBacktester(TCostModel(), base_shares=1000, cash_buffer=50000)
        res = bt.run(strat, flat)
        assert res.total_trades == 0


# ── TestBacktester ─────────────────────────────────────────────────────────────

class TestBacktester:
    """引擎：T+1 约束、收盘恢复底仓、收益汇总"""

    def test_t_plus_1_sell_capped_by_base(self):
        """T+1：卖出量不能超过底仓"""
        strat = build_strategy("grid", {"band_pct": 0.5, "grids": 2,
                                        "qty_per_grid": 9999})
        # qty_per_grid 远超底仓，引擎应裁剪到可卖底仓
        bt = TBacktester(TCostModel(), base_shares=500, cash_buffer=50000)
        res = bt.run(strat, _swing_bars())
        # 每笔卖出 ≤ 500（底仓）
        for t in res.trades:
            if t.is_sell:
                assert t.quantity <= 500, "卖出量超过底仓，违反 T+1"

    def test_closing_restores_base_position(self):
        """收盘强制平仓：日内净头寸应被恢复（每笔卖出对应可卖额）"""
        strat = build_strategy("fixed_band",
                               {"step_pct": 1.0, "levels": 2, "qty": 100})
        bt = TBacktester(TCostModel(), base_shares=1000, cash_buffer=50000)
        res = bt.run(strat, _swing_bars())
        # 至少有交易发生
        assert res.total_trades > 0
        # 应有"收盘强制平仓"记录
        closing = [t for t in res.trades if "恢复底仓" in t.reason]
        assert len(closing) > 0, "应存在收盘强制恢复底仓的交易"

    def test_net_pnl_equals_cash_change(self):
        """净收益 = 日内现金净变化（与股票涨跌无关）"""
        strat = build_strategy("grid", {"band_pct": 0.08, "grids": 4,
                                        "qty_per_grid": 100})
        cm = TCostModel()
        bt = TBacktester(cm, base_shares=1000, cash_buffer=50000)
        res = bt.run(strat, _swing_bars())
        # 毛收益 = 净收益 + 总成本
        assert res.gross_pnl == pytest.approx(res.total_net_pnl + res.total_cost,
                                              rel=1e-6)

    def test_empty_bars(self):
        """空数据应返回空结果，不报错"""
        strat = build_strategy("grid", {})
        bt = TBacktester(TCostModel(), base_shares=1000)
        res = bt.run(strat, [])
        assert res.total_trades == 0
        assert res.total_net_pnl == 0.0

    def test_all_algorithms_run(self):
        """4 种算法都能跑通不报错"""
        for algo in T_STRATEGY_REGISTRY:
            strat = build_strategy(algo, {})
            bt = TBacktester(TCostModel(), base_shares=1000,
                             cash_buffer=100000)
            res = bt.run(strat, _swing_bars())
            d = res.to_dict()
            assert d["algorithm"] == algo
            assert d["total_days"] == 2


# ── TestRegistry ───────────────────────────────────────────────────────────────

class TestRegistry:
    """注册表与元数据"""

    def test_four_algorithms_registered(self):
        """应有 4 种算法"""
        assert set(T_STRATEGY_REGISTRY.keys()) == {
            "grid", "fixed_band", "ma_deviation", "martingale"
        }

    def test_metas_complete(self):
        """元数据应包含原理、参数等字段"""
        metas = algorithm_metas()
        assert len(metas) == 4
        for m in metas:
            assert m["display_name"]
            assert m["one_liner"]
            assert m["description"]
            assert len(m["params"]) > 0
            assert isinstance(m["pros"], list)
            assert isinstance(m["risks"], list)

    def test_martingale_marked_danger(self):
        """马丁算法应标记为高风险"""
        metas = {m["name"]: m for m in algorithm_metas()}
        assert metas["martingale"]["danger"] is True
        # 其他算法非高风险
        for name in ("grid", "fixed_band", "ma_deviation"):
            assert metas[name]["danger"] is False

    def test_build_unknown_raises(self):
        """未知算法应抛错"""
        with pytest.raises(ValueError):
            build_strategy("nonexistent", {})

    def test_fixed_band_synthesizes_steps(self):
        """fixed_band 应把 step_pct/levels 合成为 steps 列表"""
        s = build_strategy("fixed_band",
                           {"step_pct": 1.5, "levels": 3, "qty": 200})
        assert s.steps == [0.015, 0.03, 0.045]
        assert s.qty == 200
