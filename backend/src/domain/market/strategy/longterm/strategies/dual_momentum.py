"""
双动量策略（Dual Momentum）
============================
Gary Antonacci 经典。在风险资产（股票）、避险资产（债券/黄金）、现金之间，
按过去一段时间的动量（收益率）择强持有。

两条规则：
  1. 绝对动量：风险资产过去 lookback 期收益 < 0 → 全仓避险资产（防御）
  2. 相对动量：风险资产收益 > 避险资产 → 持风险资产，否则持避险资产

合并决策：
  - 风险资产为正 且 强于避险 → 满仓风险资产
  - 否则持避险资产（避险资产为正）或现金（避险也为负）

适用：长期资产配置，牛市跟上、熊市躲开，回撤显著低于纯股票。
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..base import LongTermStrategy, ParamSpec
from ..models import RebalanceSignal
from ....sync.sync_provider import OHLCVBar


@dataclass
class DualMomentumStrategy(LongTermStrategy):
    """双动量（绝对动量 + 相对动量）。"""

    name: str = "dual_momentum"
    display_name: str = "双动量"
    one_liner: str = "比股票/债券/现金谁涨得多就持有谁，跌了就躲进现金"
    description: str = (
        "Gary Antonacci 经典资产配置法。"
        "看过去一段时间的动量（收益率）："
        "① 绝对动量——风险资产若亏损，全部转入避险资产防御；"
        "② 相对动量——风险资产若强于避险资产则持有风险，否则持有避险。"
    )
    market_fit: str = "长期资产配置，牛市跟上、熊市躲开"
    pros: list = field(default_factory=lambda: [
        "逻辑极简，不预测涨跌",
        "历史回撤显著低于纯股票",
        "趋势明确时切换，避免抄底接刀",
    ])
    risks: list = field(default_factory=lambda: [
        "震荡市频繁切换，来回损耗",
        "切换有滞后，趋势反转初期会受伤",
    ])
    family: str = "动量"
    rebalance_freq: str = "monthly"

    risk_symbol: str = "sh510300"        # 风险资产（沪深300 ETF）
    safe_symbol: str = "sh511010"        # 避险资产（国债 ETF）
    lookback: int = 252                  # 动量回看期（交易日，≈12个月）

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="risk_symbol", label="风险资产", type="select",
                default=self.risk_symbol,
                options=["sh000300", "sh510300", "sz159915"],
                help="股票类资产（指数/ETF），动量为正时持有",
            ),
            ParamSpec(
                key="safe_symbol", label="避险资产", type="select",
                default=self.safe_symbol,
                options=["sh511010", "sh511260", "sh518880"],
                help="债券/黄金类，风险资产亏损时躲入",
            ),
            ParamSpec(
                key="lookback", label="动量回看期", type="number",
                default=252, min=21, max=504, step=21, unit="日",
                help="看过去多少交易日的收益率，252≈12个月",
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
        risk_bars = bars_by_symbol.get(self.risk_symbol, [])
        safe_bars = bars_by_symbol.get(self.safe_symbol, [])

        risk_ret = self.returns(risk_bars, self.lookback)
        safe_ret = self.returns(safe_bars, self.lookback)

        # 数据不足：保持现金（保守）
        if risk_ret is None:
            return RebalanceSignal({}, reason="风险资产数据不足，空仓观望")

        # 避险资产数据不足：只用绝对动量
        safe_ret = safe_ret if safe_ret is not None else 0.0

        # 决策矩阵
        if risk_ret > 0 and risk_ret >= safe_ret:
            # 风险资产为正且强于避险 → 满仓风险
            weights = {self.risk_symbol: 1.0}
            reason = f"风险动量{risk_ret:.1f}% > 避险{safe_ret:.1f}%，满仓风险资产"
        elif safe_ret > 0:
            # 风险弱于避险，但避险为正 → 持避险
            weights = {self.safe_symbol: 1.0}
            reason = f"避险动量{safe_ret:.1f}% 更强，转入避险资产"
        else:
            # 两者皆负 → 空仓持现金
            weights = {}
            reason = f"风险{risk_ret:.1f}%/避险{safe_ret:.1f}% 双双为负，空仓持现金"

        return RebalanceSignal(weights, reason=reason)
