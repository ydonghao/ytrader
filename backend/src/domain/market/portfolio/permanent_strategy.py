"""固定权重回测策略适配器。

把永久组合/全天候等"目标权重不变"的组合策略适配到现有的
PortfolioBacktester 回测引擎: 每次调仓日都返回相同的目标权重。

复用 longterm 模块的 LongTermStrategy / RebalanceSignal / OHLCVBar,
零新建回测代码。
"""
from datetime import date
from typing import Optional

from src.domain.market.sync.sync_provider import OHLCVBar
from src.domain.market.strategy.longterm.base import LongTermStrategy
from src.domain.market.strategy.longterm.models import (
    RebalanceSignal,
    PortfolioState,
)


class FixedWeightStrategy(LongTermStrategy):
    """始终返回固定目标权重的策略。

    用于组合回测: 永久组合每次调仓都回归原始目标权重(25/25/25/25)。
    """

    name: str = "FixedWeight"
    display_name: str = "固定权重组合"
    one_liner: str = "始终维持目标权重不变的资产配置策略"
    description: str = (
        "适用于永久组合/全天候/黄金蝴蝶等固定配置型策略。"
        "每次调仓日都把组合拉回初始目标权重。"
    )
    family: str = "资产配置"

    def __init__(
        self, display_name: str, target_weights: dict[str, float]
    ):
        self.display_name = display_name
        self._target_weights = target_weights

    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol: Optional[dict[str, list[dict]]] = None,
        financials_by_symbol: Optional[dict[str, list[dict]]] = None,
        state: Optional[PortfolioState] = None,
    ) -> RebalanceSignal:
        # 永久组合: 每次调仓都回归原始目标权重
        return RebalanceSignal(
            target_weights=dict(self._target_weights),
            reason=f"{self.display_name} 固定权重再平衡",
        )

    def get_param_specs(self) -> dict:
        return {
            "target_weights": {
                "type": "dict",
                "default": self._target_weights,
                "description": "各标的目标权重 {symbol: 0~1}",
            }
        }
