"""
均线趋势择时（SMA Trend）
==========================
最经典的趋势跟随：价格在 N 日均线之上满仓，之下空仓。
200 日均线是华尔街公认的牛熊分界线。

规则（单标的）：
  - 收盘价 > SMA(period) → 满仓持有
  - 收盘价 < SMA(period) → 清仓持现金

适用：单标的趋势跟随（指数/ETF），抓大波段、躲大回撤。
局限：震荡市频繁假突破，来回损耗。
"""
from dataclasses import dataclass, field
from datetime import date

from ..base import LongTermStrategy, ParamSpec
from ..models import RebalanceSignal
from ....sync.sync_provider import OHLCVBar


@dataclass
class SMATrendStrategy(LongTermStrategy):
    """均线趋势择时（线上满仓/线下空仓）。"""

    name: str = "sma_trend"
    display_name: str = "均线趋势择时"
    one_liner: str = "价格站上均线就买、跌破就卖，跟着大趋势走"
    description: str = (
        "经典趋势跟随。200 日均线是华尔街公认的牛熊分界线："
        "收盘价在均线之上视为上升趋势，满仓持有；跌破均线视为转弱，清仓避险。"
    )
    market_fit: str = "单标的（指数/ETF）大波段趋势跟随"
    pros: list = field(default_factory=lambda: [
        "规则极简，纪律性强",
        "能抓住大级别牛市，躲开大级别熊市",
        "不抄底、不猜顶，情绪稳定",
    ])
    risks: list = field(default_factory=lambda: [
        "震荡市频繁假突破，来回损耗",
        "信号滞后，顶底都会少一截",
    ])
    family: str = "趋势"
    rebalance_freq: str = "daily"

    symbol: str = "sh510300"
    period: int = 200                # 均线周期

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="symbol", label="跟踪标的", type="select",
                default=self.symbol,
                options=["sh000300", "sh510300", "sz159915", "sh000001"],
                help="趋势跟随的指数/ETF",
            ),
            ParamSpec(
                key="period", label="均线周期", type="number",
                default=200, min=20, max=500, step=10, unit="日",
                help="200 日均线是经典牛熊分界线",
            ),
        ]

    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol=None,
        financials_by_symbol=None,
        state=None,
    ) -> RebalanceSignal:
        bars = bars_by_symbol.get(self.symbol, [])
        above = self.above_sma(bars, self.period)

        if above is None:
            return RebalanceSignal({}, reason="数据不足，无法判断均线趋势")

        if above:
            return RebalanceSignal(
                {self.symbol: 1.0},
                reason=f"价格站上{self.period}日均线，满仓持有",
            )
        else:
            return RebalanceSignal(
                {},
                reason=f"价格跌破{self.period}日均线，清仓避险",
            )
