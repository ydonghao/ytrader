"""等权（Equal Weight）策略 —— 优化类策略的基线对照。

每个标的等权重，无需优化。研究表明等权长期常优于市值加权，
是最简单稳健的分散配置。作为风险平价/最小方差/MVO 的对照基准。
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np

from ..longterm.base import LongTermStrategy, ParamSpec
from ..longterm.models import RebalanceSignal
from ...sync.sync_provider import OHLCVBar


@dataclass
class EqualWeightStrategy(LongTermStrategy):
    name: str = "equal_weight"
    display_name: str = "等权配置"
    one_liner: str = "每标的等权重，最简单的稳健分散基线"
    description: str = (
        "等权配置。每个标的分配相同权重（扣除现金缓冲后均分）。"
        "无需优化、不依赖任何估计，是风险平价/最小方差/MVO 的天然对照基准。"
        "研究显示等权长期常优于市值加权，自带再平衡溢价。"
    )
    market_fit: str = "所有优化策略的对照基准；追求简单透明的分散配置"
    family: str = "资产配置"
    rebalance_freq: str = "quarterly"
    needs_fundamentals: bool = False

    cash_buffer: float = 0.0

    pros: list = field(default_factory=lambda: [
        "零估计误差，最稳健",
        "自带再平衡溢价",
        "天然分散",
    ])
    risks: list = field(default_factory=lambda: [
        "不看波动，高波动资产拖累",
    ])

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                "cash_buffer", "现金缓冲", "number", default=self.cash_buffer,
                min=0.0, max=0.5, step=0.05,
            ),
            ParamSpec(
                "rebalance_freq", "再平衡频率", "select",
                default=self.rebalance_freq,
                options=["monthly", "quarterly", "yearly"],
            ),
        ]

    def get_params(self) -> dict:
        return {"cash_buffer": self.cash_buffer,
                "rebalance_freq": self.rebalance_freq}

    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol: Optional[dict[str, list[dict]]] = None,
        financials_by_symbol: Optional[dict[str, list[dict]]] = None,
        state: Optional[object] = None,
    ) -> RebalanceSignal:
        valid = [
            s for s, bs in bars_by_symbol.items() if bs and len(bs) > 0
        ]
        if not valid:
            return RebalanceSignal({}, reason="等权：无可用标的")
        w = (1.0 - self.cash_buffer) / len(valid)
        target = {s: w for s in valid}
        return RebalanceSignal(target, reason="等权配置")
