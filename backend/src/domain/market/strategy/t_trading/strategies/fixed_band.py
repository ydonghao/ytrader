"""
固定价差区间做T（Fixed Band）
================================
原理：以当日开盘价（昨收）为基准，价格偏离 ±k% 触发买卖。
每跌破一档买入一份，每涨破一档卖出一份。

大白话："和网格类似，但用固定的百分比档位（如 1%、2%、3%），
跌到 -1% 买一手、-2% 再买一手；涨到 +1% 卖一手、+2% 再卖一手。"

适用：震荡行情，档位比网格更直观。
"""
from dataclasses import dataclass, field

from ....sync.sync_provider import OHLCVBar
from ..models import TSignal, TStrategyState
from .base import ParamSpec, TStrategy


@dataclass
class FixedBandStrategy(TStrategy):
    """
    固定价差区间做T

    Args:
        steps:    偏离档位列表（小数，如 [0.01,0.02,0.03] 表示 1/2/3%）
        qty:      每档交易股数
    """
    name: str = "fixed_band"
    display_name: str = "固定价差"
    one_liner: str = "按固定百分比档位（1%/2%/3%）低买高卖"
    description: str = (
        "以开盘价为基准，预设几档偏离百分比。价格相对基准每下跌一档"
        "（如 -1%、-2%、-3%）就买入一份；每上涨一档（+1%、+2%、+3%）"
        "就卖出一份。比网格更直观——你能直接看到「跌了1%就买」。"
    )
    market_fit: str = "震荡行情（温和波动）"
    pros: list = field(default_factory=lambda: [
        "档位直观，一眼看懂触发条件",
        "参数最少，小白最易理解原理",
    ])
    risks: list = field(default_factory=lambda: [
        "档位太密：手续费吃掉差价",
        "单边行情：和网格一样会被套或卖飞",
    ])

    steps: list = field(default_factory=lambda: [0.01, 0.02, 0.03])
    qty: int = 200

    def __post_init__(self):
        self._base = 0.0
        self._buy_level = 0   # 已触发到第几个买入档
        self._sell_level = 0  # 已触发到第几个卖出档

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="step_pct", label="档位步长", type="number",
                default=1.0, min=0.2, max=5.0, step=0.1, unit="%",
                help="每隔多少百分比设一档，如 1% 则档位为 ±1%/±2%/±3%",
            ),
            ParamSpec(
                key="levels", label="档位数量", type="number",
                default=3, min=1, max=8, step=1, unit="档",
                help="每个方向设几档（上下对称）",
            ),
            ParamSpec(
                key="qty", label="每档股数", type="number",
                default=200, min=100, max=10000, step=100, unit="股",
                help="每触发一档买卖多少股",
            ),
        ]

    def get_params(self) -> dict:
        return {"steps": self.steps, "qty": self.qty}

    def on_day_start(self, day_open: float, prev_close: float) -> None:
        self._base = day_open
        self._buy_level = 0
        self._sell_level = 0

    def on_bar(
        self, bar: OHLCVBar, state: TStrategyState
    ) -> list[TSignal]:
        if not self._base:
            return []
        price = bar.close_
        dev = (price - self._base) / self._base  # 偏离比例

        signals: list[TSignal] = []

        # 下跌：每跌破一个档位买入一份
        for i, step in enumerate(self.steps, start=1):
            if dev <= -step and self._buy_level < i:
                signals.append(TSignal(
                    action="BUY",
                    quantity=self.qty,
                    reason=f"跌幅达 -{step*100:.1f}%（第{i}档买入）",
                ))
                self._buy_level = i
                break

        # 上涨：每涨破一个档位卖出一份
        for i, step in enumerate(self.steps, start=1):
            if dev >= step and self._sell_level < i:
                signals.append(TSignal(
                    action="SELL",
                    quantity=self.qty,
                    reason=f"涨幅达 +{step*100:.1f}%（第{i}档卖出）",
                ))
                self._sell_level = i
                break

        return signals
