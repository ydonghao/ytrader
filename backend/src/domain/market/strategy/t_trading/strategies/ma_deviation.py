"""
均线偏离做T（MA Deviation）
============================
原理：用分钟线计算移动平均线 MA(N)。价格偏离均线超过阈值 K% 时反向操作：
  - 价格低于 MA*(1-K%) → 买入（超跌）
  - 价格高于 MA*(1+K%) → 卖出（超涨）
  - 回归均线附近 → 平掉该笔（由收盘恢复底仓兜底）

大白话："用一条平均价作为"准星"。价格离平均价太远（不管是高是低）
就认为它"会回来"，于是低位买、高位卖，赚它回归平均的差价。"

适用：震荡+温和趋势，比固定网格更"聪明"（自适应）。
"""
from collections import deque
from dataclasses import dataclass, field

from ....sync.sync_provider import OHLCVBar
from ..models import TSignal, TStrategyState
from .base import ParamSpec, TStrategy


@dataclass
class MADeviationStrategy(TStrategy):
    """
    均线偏离做T

    Args:
        ma_period:     均线周期（分钟 bar 数）
        dev_threshold: 触发偏离阈值（小数，0.005 = 0.5%）
        qty:           每次交易股数
    """
    name: str = "ma_deviation"
    display_name: str = "均线偏离"
    one_liner: str = "价格离均线太远就反向操作，赚它回归平均的差价"
    description: str = (
        "实时计算 N 分钟收盘价的移动平均线 MA。当价格相对 MA 偏离超过"
        "阈值时认为短期超买/超卖：低于 MA 一定比例就买入（等它回升），"
        "高于 MA 一定比例就卖出（等它回落）。比网格更自适应——波动大时"
        "网格线会失效，而均线能动态跟随。"
    )
    market_fit: str = "震荡 + 温和趋势"
    pros: list = field(default_factory=lambda: [
        "均线动态跟随，比固定网格更聪明",
        "趋势中也能吃到部分回调差价",
    ])
    risks: list = field(default_factory=lambda: [
        "强趋势中反复打脸（买在半山腰）",
        "均线周期选错会频繁误触发",
    ])

    ma_period: int = 20
    dev_threshold: float = 0.005
    qty: int = 100

    def __post_init__(self):
        self._window: deque = deque(maxlen=self.ma_period)
        self._position = 0   # 1=日内已买入待卖, -1=已卖出待买

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="ma_period", label="均线周期", type="number",
                default=20, min=5, max=120, step=1, unit="根",
                help="用多少根分钟K线算均线，周期越长越平滑",
            ),
            ParamSpec(
                key="dev_threshold", label="偏离阈值", type="number",
                default=0.5, min=0.1, max=3.0, step=0.1, unit="%",
                help="价格偏离均线多少就触发，0.5% = 偏离半个百分点",
            ),
            ParamSpec(
                key="qty", label="每次股数", type="number",
                default=100, min=100, max=10000, step=100, unit="股",
                help="每次触发买卖多少股",
            ),
        ]

    def get_params(self) -> dict:
        return {
            "ma_period": self.ma_period,
            "dev_threshold": self.dev_threshold,
            "qty": self.qty,
        }

    def on_day_start(self, day_open: float, prev_close: float) -> None:
        self._window.clear()
        self._position = 0

    def on_bar(
        self, bar: OHLCVBar, state: TStrategyState
    ) -> list[TSignal]:
        self._window.append(bar.close_)
        if len(self._window) < self.ma_period:
            return []

        ma = sum(self._window) / len(self._window)
        price = bar.close_
        dev = (price - ma) / ma

        signals: list[TSignal] = []

        # 超跌买入（只在未持仓或已卖出时）
        if dev <= -self.dev_threshold and self._position <= 0:
            signals.append(TSignal(
                action="BUY",
                quantity=self.qty,
                reason=f"价格低于MA {abs(dev)*100:.2f}%（超跌买入）",
            ))
            self._position = 1
        # 超涨卖出（只在已买入时，形成低买高卖闭环）
        elif dev >= self.dev_threshold and self._position >= 0:
            signals.append(TSignal(
                action="SELL",
                quantity=self.qty,
                reason=f"价格高于MA {dev*100:.2f}%（超涨卖出）",
            ))
            self._position = -1

        return signals
