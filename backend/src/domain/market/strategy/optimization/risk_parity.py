"""风险平价（Risk Parity / ERC）策略。

各资产对组合总风险的贡献相等。低波动资产获得更高权重，
使每类资产承担相同风险 → 天然分散，不依赖收益预测。
"""
from dataclasses import dataclass, field

import numpy as np

from . import solvers
from .base_optimizer import OptimizationStrategyBase


@dataclass
class RiskParityStrategy(OptimizationStrategyBase):
    name: str = "risk_parity"
    display_name: str = "风险平价"
    one_liner: str = "让每类资产承担相同风险，低波动多配、高波动少配"
    description: str = (
        "风险平价（Equal Risk Contribution）。不预测收益，"
        "只根据波动率与相关性分配权重，使各资产对组合总风险的边际贡献相等。"
        "低波动资产权重更高，天然实现风险分散，回撤通常低于集中组合。"
    )
    market_fit: str = "追求均衡风险暴露、稳定回撤的长期资金"
    pros: list = field(default_factory=lambda: [
        "不依赖收益预测，仅用波动率/相关性",
        "天然分散，回撤通常较低",
        "各资产风险贡献相等，无单一风险源主导",
    ])
    risks: list = field(default_factory=lambda: [
        "牛市跑输集中持股",
        "低波动资产（如债券）占比可能偏高",
    ])

    def solve_weights(self, rets, cov_ann, mu_ann) -> np.ndarray:
        return solvers.solve_risk_parity(
            cov_ann, max_weight=self.max_weight, cash_buffer=self.cash_buffer
        )

    def _reason(self) -> str:
        return "风险平价：各资产等风险贡献"
