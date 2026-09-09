"""
马丁金字塔加仓做T（Martingale）
================================
原理：价格每下跌一个步长，就加倍买入（1, 2, 4, 8...）；一旦反弹到
目标收益，就把金字塔全部卖出。

大白话："赌它总会反弹——跌一点买1手，再跌买2手，再跌买4手……越跌买越多。
只要有一次反弹到目标价，前面所有的账就一起平掉还赚。"

⚠️ 高风险：单边大跌会一路加仓，资金呈指数级消耗，可能被套到爆仓。
本算法主要用于**风险教育**——展示"看似必胜"策略的危险。
"""
from dataclasses import dataclass, field

from ....sync.sync_provider import OHLCVBar
from ..models import TSignal, TStrategyState
from .base import ParamSpec, TStrategy


@dataclass
class MartingaleStrategy(TStrategy):
    """
    马丁金字塔加仓

    Args:
        drop_step:    每次加仓的下跌触发比例（0.02 = 2%）
        multiplier:   加仓倍数（2 = 每次1,2,4,8...）
        take_profit:  反弹到该收益比例时全部卖出（0.03 = 3%）
        base_qty:     第一次买入的基础股数
        max_levels:   最多加仓层数（防爆仓）
    """
    name: str = "martingale"
    display_name: str = "马丁金字塔"
    one_liner: str = "越跌加倍买，反弹一把全卖——看似必胜，实则危险"
    description: str = (
        "下跌时按倍数加仓（1→2→4→8手），把平均成本快速拉低；一旦价格"
        "反弹到目标收益，就把整座金字塔一次性卖出。理论上只要资金无限、"
        "价格终会反弹，就「必赚」。但现实中：单边大跌会让加仓量指数增长，"
        "资金迅速耗尽，越亏越多。"
    )
    market_fit: str = "温和震荡 / 小幅回调"
    pros: list = field(default_factory=lambda: [
        "反弹一次即可覆盖多次下跌",
        "平均成本快速降低",
    ])
    risks: list = field(default_factory=lambda: [
        "⚠️ 单边大跌 → 加仓量指数级膨胀，资金可能耗尽",
        "⚠️ 越亏越加，心理与账户双重压力",
        "本算法主要用于风险教育，谨慎实盘",
    ])
    danger: bool = True

    drop_step: float = 0.02
    multiplier: float = 2.0
    take_profit: float = 0.03
    base_qty: int = 100
    max_levels: int = 5

    def __post_init__(self):
        self._base = 0.0
        self._last_buy_price = 0.0   # 上次加仓价
        self._level = 0              # 当前金字塔层数
        self._avg_price = 0.0        # 金字塔加权均价
        self._total_qty = 0          # 金字塔累计股数

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="drop_step", label="加仓跌幅", type="number",
                default=2.0, min=0.5, max=5.0, step=0.5, unit="%",
                help="每跌多少触发一次加仓，2% = 每跌2%加一次",
            ),
            ParamSpec(
                key="multiplier", label="加仓倍数", type="number",
                default=2.0, min=1.5, max=3.0, step=0.5, unit="倍",
                help="每次加仓量是上次的几倍，2倍则序列为 1,2,4,8...",
            ),
            ParamSpec(
                key="take_profit", label="止盈涨幅", type="number",
                default=3.0, min=1.0, max=10.0, step=0.5, unit="%",
                help="反弹到均价以上多少全部卖出，3% = 赚3%就平仓",
            ),
            ParamSpec(
                key="base_qty", label="基础手数", type="number",
                default=100, min=100, max=2000, step=100, unit="股",
                help="第一次买入多少股，后续按倍数翻番",
            ),
            ParamSpec(
                key="max_levels", label="最大层数", type="number",
                default=5, min=2, max=8, step=1, unit="层",
                help="最多加仓几层（防爆仓安全阀）",
            ),
        ]

    def get_params(self) -> dict:
        return {
            "drop_step": self.drop_step,
            "multiplier": self.multiplier,
            "take_profit": self.take_profit,
            "base_qty": self.base_qty,
            "max_levels": self.max_levels,
        }

    def on_day_start(self, day_open: float, prev_close: float) -> None:
        self._base = day_open
        self._last_buy_price = day_open
        self._level = 0
        self._avg_price = 0.0
        self._total_qty = 0

    def on_bar(
        self, bar: OHLCVBar, state: TStrategyState
    ) -> list[TSignal]:
        price = bar.close_
        signals: list[TSignal] = []

        # 已有仓位：先判断是否到止盈
        if self._total_qty > 0 and self._avg_price > 0:
            profit_pct = (price - self._avg_price) / self._avg_price
            if profit_pct >= self.take_profit:
                signals.append(TSignal(
                    action="SELL",
                    quantity=self._total_qty,
                    reason=(
                        f"反弹至均价+{profit_pct*100:.2f}%，"
                        f"金字塔止盈卖出 {self._total_qty} 股"
                    ),
                ))
                # 重置金字塔（当日不再重建，由收盘兜底）
                self._total_qty = 0
                self._avg_price = 0.0
                self._level = 0
                self._last_buy_price = price
                return signals

        # 下跌加仓
        if self._level < self.max_levels:
            drop_from_last = (self._last_buy_price - price) / self._last_buy_price
            if drop_from_last >= self.drop_step or self._level == 0:
                # 本层股数 = base_qty * multiplier^level
                qty = int(self.base_qty * (self.multiplier ** self._level))
                if qty > 0:
                    signals.append(TSignal(
                        action="BUY",
                        quantity=qty,
                        reason=(
                            f"跌幅{drop_from_last*100:.2f}%，"
                            f"第{self._level+1}层加仓 {qty} 股"
                        ),
                    ))
                    # 更新金字塔状态
                    new_total = self._total_qty + qty
                    self._avg_price = (
                        (self._avg_price * self._total_qty + price * qty)
                        / new_total
                    )
                    self._total_qty = new_total
                    self._last_buy_price = price
                    self._level += 1

        return signals
