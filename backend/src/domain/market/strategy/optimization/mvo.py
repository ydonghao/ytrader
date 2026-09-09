"""均值-方差优化（MVO / 最大夏普）策略 + 有效前沿工具。

最大夏普（切线）组合：在约束下最大化风险调整后收益。
同时提供 efficient_frontier_compute() 供资产配置工具端点绘制前沿。
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ...sync.sync_provider import OHLCVBar
from ..longterm.base import ParamSpec
from . import covariance as cov_mod
from . import solvers
from .base_optimizer import OptimizationStrategyBase


@dataclass
class MVOStrategy(OptimizationStrategyBase):
    name: str = "mvo"
    display_name: str = "均值-方差(最大夏普)"
    one_liner: str = "用历史收益+波动求风险调整后收益最高的权重"
    description: str = (
        "均值-方差优化（最大夏普/切线组合）。用历史均值估预期收益、"
        "用协方差估风险，求夏普比率最高的权重。理论上每单位风险回报最高，"
        "但对收益估计敏感，易过拟合——需配合 max_weight 约束与较短回看窗口。"
    )
    market_fit: str = "相信历史动量延续、能承受估计误差的积极配置者"
    pros: list = field(default_factory=lambda: [
        "理论上每单位风险收益最高",
        "同时考虑收益与风险",
    ])
    risks: list = field(default_factory=lambda: [
        "对收益估计极敏感，易过拟合",
        "历史均值未必预示未来",
        "需 max_weight 约束防集中",
    ])

    risk_free_rate: float = 0.0

    def get_param_specs(self):
        specs = super().get_param_specs()
        specs.append(
            ParamSpec(
                "risk_free_rate", "无风险利率", "number",
                default=self.risk_free_rate, min=0.0, max=0.1, step=0.005,
                help="年化无风险利率，用于计算夏普",
            )
        )
        return specs

    def get_params(self) -> dict:
        p = super().get_params()
        p["risk_free_rate"] = self.risk_free_rate
        return p

    def solve_weights(self, rets, cov_ann, mu_ann) -> np.ndarray:
        return solvers.solve_max_sharpe(
            mu_ann, cov_ann, rf=self.risk_free_rate,
            max_weight=self.max_weight, cash_buffer=self.cash_buffer,
        )

    def _reason(self) -> str:
        return "均值-方差：最大夏普切线组合"


def efficient_frontier_compute(
    bars_by_symbol: dict[str, list[OHLCVBar]],
    lookback: int = 120,
    max_weight: float = 0.4,
    cash_buffer: float = 0.05,
    n_points: int = 25,
    risk_free_rate: float = 0.0,
) -> dict:
    """计算有效前沿，供资产配置工具端点使用。

    返回 {symbols, frontier:[{ret,risk,sharpe,weights}],
          min_variance, max_sharpe}。
    """
    symbols, prices = cov_mod.price_matrix(bars_by_symbol, lookback=lookback)
    if len(symbols) < 2:
        return {
            "symbols": list(bars_by_symbol.keys()),
            "frontier": [],
            "min_variance": None,
            "max_sharpe": None,
            "warning": "可用标的不足(<2)，无法计算前沿",
        }
    rets = cov_mod.daily_returns(prices)
    if rets.shape[0] < 2:
        return {
            "symbols": symbols,
            "frontier": [],
            "min_variance": None,
            "max_sharpe": None,
            "warning": "历史数据不足",
        }
    cov_ann = cov_mod.annualize_cov(cov_mod.covariance_matrix(rets))
    mu_ann = cov_mod.annualize_returns(rets.mean(axis=0))

    pts = solvers.efficient_frontier(
        mu_ann, cov_ann, n_points=n_points,
        max_weight=max_weight, cash_buffer=cash_buffer, rf=risk_free_rate,
    )
    if not pts:
        return {
            "symbols": symbols, "frontier": [],
            "min_variance": None, "max_sharpe": None,
            "warning": "前沿计算失败",
        }
    min_var = min(pts, key=lambda p: p.risk)
    max_sh = max(pts, key=lambda p: p.sharpe)
    return {
        "symbols": symbols,
        "frontier": [p.to_dict(symbols) for p in pts],
        "min_variance": min_var.to_dict(symbols),
        "max_sharpe": max_sh.to_dict(symbols),
    }
