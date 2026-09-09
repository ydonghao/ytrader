"""rebalance_advisor 单元测试。

纯函数测试, 无 DB 依赖。覆盖:
- 超配类 → 卖出指令
- 低配类 → 买入指令
- 多标的同类按比例分摊
- 未超阈值 → 无指令
- 总市值为 0 → 无指令
"""
import pytest

from src.domain.market.portfolio.nav_calculator import (
    NavItemInput,
    calc_portfolio_nav,
)
from src.domain.market.portfolio.rebalance_advisor import (
    suggest_rebalance,
)


def _build_result(prices: dict[str, float]):
    """构造一个 4 等权组合并算净值结果, 用其 items/breakdowns 测再平衡。"""
    defaults = {
        "equity": 10.0,
        "bond": 100.0,
        "gold": 5.0,
        "cash": 1.0,
    }
    defaults.update(prices)
    items = [
        NavItemInput(1, "e", "equity", 0.25, 2500, defaults["equity"]),
        NavItemInput(2, "b", "bond", 0.25, 250, defaults["bond"]),
        NavItemInput(3, "g", "gold", 0.25, 5000, defaults["gold"]),
        NavItemInput(4, "c", "cash", 0.25, 25000, defaults["cash"]),
    ]
    return calc_portfolio_nav(100000.0, 0.05, items)


class TestRebalanceAdvisor:
    """再平衡建议引擎测试。"""

    def test_overweight_triggers_sell(self):
        """股票超配 → 产生 SELL 指令。"""
        # 股票价格翻倍, 股票类市值从 25000 → 50000, 总市值 125000
        # 股票实际 40% vs 目标 25%, drift=+0.15
        result = _build_result({"equity": 20.0})
        actions = suggest_rebalance(
            result.items,
            result.breakdowns,
            result.total_value_cny,
            threshold=0.05,
        )
        sell_actions = [a for a in actions if a.action == "SELL"]
        assert len(sell_actions) == 1
        a = sell_actions[0]
        assert a.symbol == "e"
        assert a.asset_class == "equity"
        assert a.shares_delta > 0

    def test_underweight_triggers_buy(self):
        """某类低配 → 产生 BUY 指令。"""
        # 股票大跌, 股票类市值从 25000 → 12500, 总市值 87500
        # 股票实际 14.3% vs 目标 25%, drift=-0.107
        result = _build_result({"equity": 5.0})
        actions = suggest_rebalance(
            result.items,
            result.breakdowns,
            result.total_value_cny,
            threshold=0.05,
        )
        buy_actions = [a for a in actions if a.action == "BUY"]
        assert len(buy_actions) == 1
        a = buy_actions[0]
        assert a.symbol == "e"
        assert a.action == "BUY"
        assert a.shares_delta > 0

    def test_no_drift_no_action(self):
        """等权组合无偏离 → 无指令。"""
        result = _build_result({})  # 各类市值相等, drift=0
        actions = suggest_rebalance(
            result.items,
            result.breakdowns,
            result.total_value_cny,
            threshold=0.05,
        )
        assert actions == []

    def test_zero_value_no_action(self):
        """总市值为 0 → 无指令(避免除零)。"""
        items = [NavItemInput(1, "e", "equity", 1.0, 0, 10.0)]
        from src.domain.market.portfolio.nav_calculator import (
            AssetClassBreakdown,
        )
        breakdowns = [
            AssetClassBreakdown("equity", 1.0, 0.0, -1.0)
        ]
        actions = suggest_rebalance(items, breakdowns, 0.0, 0.05)
        assert actions == []

    def test_multi_instrument_sell_split(self):
        """同类多标的超配: 按市值比例分摊卖出。

        股票类两只: A(1000股×10=10000) + B(100股×100=10000)
        都翻倍后 A=20000, B=20000, 按市值各占 50% 分摊卖出。
        """
        items_in = [
            NavItemInput(1, "a", "equity", 0.125, 1000, 20.0),
            NavItemInput(2, "b", "equity", 0.125, 100, 200.0),
            NavItemInput(3, "bond", "bond", 0.25, 250, 100.0),
            NavItemInput(4, "gold", "gold", 0.25, 5000, 5.0),
            NavItemInput(5, "cash", "cash", 0.25, 25000, 1.0),
        ]
        result = calc_portfolio_nav(100000.0, 0.05, items_in)
        actions = suggest_rebalance(
            result.items,
            result.breakdowns,
            result.total_value_cny,
            threshold=0.05,
        )
        sell_actions = [a for a in actions if a.action == "SELL"]
        # 两只都应被卖出
        assert len(sell_actions) == 2
        symbols = {a.symbol for a in sell_actions}
        assert symbols == {"a", "b"}
