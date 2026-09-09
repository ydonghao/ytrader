"""最小方差（Minimum Variance）策略。

在约束下最小化组合方差。不预测收益，仅用协方差，
理论上给出给定约束下方差最低的权重 → 回撤最小的纯防御型配置。
"""
from dataclasses import dataclass, field

import numpy as np

from . import solvers
from .base_optimizer import OptimizationStrategyBase


@dataclass
class MinVarianceStrategy(OptimizationStrategyBase):
    name: str = "min_variance"
    display_name: str = "最小方差"
    one_liner: str = "数学上波动最低的权重，纯防御、不预测收益"
    description: str = (
        "最小方差组合。在单标的上限、做多、现金缓冲约束下，"
        "求使组合方差最小的权重。不预测收益，仅用协方差，"
        "是给定约束下方差最低的配置——回撤最小的防御型策略。"
    )
    market_fit: str = "极度厌恶波动、追求最低回撤的防御型资金"
    pros: list = field(default_factory=lambda: [
        "历史回撤通常最低",
        "不依赖收益预测，稳健",
        "低波动资产自动获得更高权重",
    ])
    risks: list = field(default_factory=lambda: [
        "牛市大幅跑输",
        "可能高度集中于低波动资产（受 max_weight 约束缓解）",
    ])

    def solve_weights(self, rets, cov_ann, mu_ann) -> np.ndarray:
        return solvers.solve_min_variance(
            cov_ann, max_weight=self.max_weight, cash_buffer=self.cash_buffer
        )

    def _reason(self) -> str:
        return "最小方差：约束下方差最低配置"
