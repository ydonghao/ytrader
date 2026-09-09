"""优化类策略公共基类。

把"从 K 线估计协方差/收益 → 求解权重 → 产出 RebalanceSignal"的通用流程
封装在此；子类只需实现 solve_weights() 选择具体优化目标。
"""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np

from ..longterm.base import LongTermStrategy, ParamSpec
from ..longterm.models import RebalanceSignal
from ...sync.sync_provider import OHLCVBar
from . import covariance as cov_mod


@dataclass
class OptimizationStrategyBase(LongTermStrategy):
    """现代组合构建策略基类（协方差驱动）。"""

    family: str = "资产配置"
    rebalance_freq: str = "quarterly"
    needs_fundamentals: bool = False

    # 优化通用参数
    lookback: int = 120
    max_weight: float = 0.4
    cash_buffer: float = 0.05

    @abstractmethod
    def solve_weights(
        self, rets: np.ndarray, cov_ann: np.ndarray, mu_ann: np.ndarray
    ) -> np.ndarray:
        """子类实现：给定日收益矩阵/年化协方差/年化预期收益，返回权重向量。"""
        ...

    # ── 参数规格 / 记录 ──────────────────────────────────────────────────
    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                "lookback", "回看窗口", "number", default=self.lookback,
                min=20, max=500, step=10, unit="日",
                help="用最近多少个交易日的收益率估计协方差",
            ),
            ParamSpec(
                "max_weight", "单标的上限", "number", default=self.max_weight,
                min=0.1, max=1.0, step=0.05,
                help="单个标的最大权重，避免过度集中",
            ),
            ParamSpec(
                "cash_buffer", "现金缓冲", "number", default=self.cash_buffer,
                min=0.0, max=0.5, step=0.05,
                help="保留为现金的比例",
            ),
            ParamSpec(
                "rebalance_freq", "再平衡频率", "select",
                default=self.rebalance_freq,
                options=["monthly", "quarterly", "yearly"],
            ),
        ]

    def get_params(self) -> dict:
        return {
            "lookback": self.lookback,
            "max_weight": self.max_weight,
            "cash_buffer": self.cash_buffer,
            "rebalance_freq": self.rebalance_freq,
        }

    # ── 调仓决策 ─────────────────────────────────────────────────────────
    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol: Optional[dict[str, list[dict]]] = None,
        financials_by_symbol: Optional[dict[str, list[dict]]] = None,
        state: Optional[object] = None,
    ) -> RebalanceSignal:
        symbols, prices = cov_mod.price_matrix(
            bars_by_symbol, lookback=self.lookback
        )
        if len(symbols) < 2:
            return RebalanceSignal(
                {}, reason=f"{self.name}: 可用标的不足(<2)，无法优化"
            )
        rets = cov_mod.daily_returns(prices)
        if rets.shape[0] < 2:
            return RebalanceSignal(
                {}, reason=f"{self.name}: 历史数据不足，无法估计协方差"
            )
        cov_ann = cov_mod.annualize_cov(cov_mod.covariance_matrix(rets))
        mu_ann = cov_mod.annualize_returns(rets.mean(axis=0))

        try:
            weights = self.solve_weights(rets, cov_ann, mu_ann)
        except Exception:
            # 求解失败 → 降级等权
            n = len(symbols)
            weights = np.full(n, (1.0 - self.cash_buffer) / n)

        target = {
            s: float(wi)
            for s, wi in zip(symbols, weights)
            if wi > 1e-4
        }
        if not target:
            n = len(symbols)
            target = {s: (1.0 - self.cash_buffer) / n for s in symbols}
        return RebalanceSignal(target, reason=self._reason())
