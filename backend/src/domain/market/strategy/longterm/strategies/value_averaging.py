"""
价值平均定投（Value Averaging）
================================
Michael Edleson 经典。比普通定投更聪明：用估值（PE 分位）调节买入力度，
低估多买、高估少买或暂停。

规则：
  - 每期设定一个"目标市值增长"（如每月 +X 元）
  - 实际市值 < 目标 → 补足差额（买入）
  - 实际市值 > 目标 → 卖出超出（罕见于定投，但机制完整）
  - 叠加估值调节：当前 PE 处于历史低分位 → 加大买入；高分位 → 减少买入

简化版（本实现）：根据 PE 历史分位决定买入力度
  - PE 分位 < 30%（低估）：买 2 倍基础额
  - PE 分位 30%~70%（合理）：买 1 倍基础额
  - PE 分位 > 70%（高估）：暂停买入
  - PE 分位 > 90%（极度高估）：卖出（止盈）

适用：长期定投指数/ETF，用估值提升定投效率，门槛极低。
注意：需估值数据；无估值数据时退化为普通定投。
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..base import LongTermStrategy, ParamSpec
from ..models import RebalanceSignal
from ....sync.sync_provider import OHLCVBar


@dataclass
class ValueAveragingStrategy(LongTermStrategy):
    """估值定投（PE 分位调节买入力度）。"""

    name: str = "value_averaging"
    display_name: str = "价值平均定投"
    one_liner: str = "估值低就多买、高就停买，比无脑定投更划算"
    description: str = (
        "Michael Edleson 经典定投升级版。用估值（PE 历史分位）调节买入力度："
        "低估时加倍买入、合理估值正常定投、高估暂停、极度高估止盈。"
        "长期收益显著高于无脑定投。"
    )
    market_fit: str = "长期定投指数/ETF，门槛最低"
    pros: list = field(default_factory=lambda: [
        "门槛极低，适合个人长期投资",
        "估值低多买、高少买，自动低位加仓",
        "不择时、不选股，省心",
    ])
    risks: list = field(default_factory=lambda: [
        "需要估值历史数据",
        "牛市后期买入暂停，可能错过泡沫段",
    ])
    family: str = "定投"
    rebalance_freq: str = "monthly"
    needs_fundamentals: bool = True      # 用 PE 估值数据

    symbol: str = "sh510300"
    monthly_amount: float = 10_000.0     # 基础月定投额
    max_position_pct: float = 1.0        # 单标的最大占总权益比例

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="symbol", label="定投标的", type="select",
                default=self.symbol,
                options=["sh000300", "sh510300", "sz159915"],
                help="定投的指数/ETF",
            ),
            ParamSpec(
                key="monthly_amount", label="基础月定投额", type="number",
                default=10_000, min=100, max=1_000_000, step=1000, unit="元",
                help="合理估值区间的每月买入金额",
            ),
        ]

    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol: Optional[dict[str, list[dict]]] = None,
        financials_by_symbol=None,
        state=None,
    ) -> RebalanceSignal:
        # 无估值数据 → 退化为普通定投（满仓或保持）
        pe_pct = self._pe_percentile(self.symbol, valuation_by_symbol)

        # 算买入倍率
        if pe_pct is None:
            mult = 1.0
            zone = "无估值数据，按基础额定投"
        elif pe_pct < 0.30:
            mult = 2.0
            zone = f"PE 分位{pe_pct*100:.0f}%（低估），加倍买入"
        elif pe_pct < 0.70:
            mult = 1.0
            zone = f"PE 分位{pe_pct*100:.0f}%（合理），正常定投"
        elif pe_pct < 0.90:
            mult = 0.0
            zone = f"PE 分位{pe_pct*100:.0f}%（高估），暂停买入"
        else:
            # 极度高估 → 止盈清仓
            return RebalanceSignal(
                {}, reason=f"PE 分位{pe_pct*100:.0f}%（极度高估），止盈清仓"
            )

        # 把月定投额转成目标权重：
        # 简化处理——若总权益足够，目标仓位 = 当前仓位 + 月定投额*倍率/总权益
        # 但权重策略下，更稳健的做法是：低估满仓、合理半仓、暂停/止盈空仓
        # 这里用一个映射：低估满仓、合理 50%、暂停保持、止盈空仓
        if state is None:
            target_w = {self.symbol: min(0.5 * mult, self.max_position_pct)}
        else:
            # 渐进加仓：每次调仓把目标仓位往上调一档
            cur_w = self._current_weight(state, self.symbol)
            step = (self.monthly_amount * mult) / max(state.total_equity, 1)
            target_w_val = min(cur_w + step, self.max_position_pct)
            target_w = {self.symbol: target_w_val}

        return RebalanceSignal(target_w, reason=zone)

    def _current_weight(self, state, symbol: str) -> float:
        """当前某标的占总权益比例。"""
        if state.total_equity <= 0:
            return 0.0
        pos = state.holdings.get(symbol)
        if pos is None or pos.shares <= 0:
            return 0.0
        return pos.market_value / state.total_equity

    @staticmethod
    def _pe_percentile(
        symbol: str,
        valuation_by_symbol: Optional[dict[str, list[dict]]],
    ) -> Optional[float]:
        """
        当前 PE 在历史中的分位（0~1）。
        无估值数据返回 None。
        """
        if not valuation_by_symbol:
            return None
        rows = valuation_by_symbol.get(symbol)
        if not rows:
            return None
        pe_ttm_vals = [
            r.get("pe_ttm") or r.get("pe")
            for r in rows
            if (r.get("pe_ttm") or r.get("pe")) is not None
        ]
        if len(pe_ttm_vals) < 30:  # 样本不足
            return None
        cur = pe_ttm_vals[-1]
        rank = sum(1 for v in pe_ttm_vals if v <= cur)
        return rank / len(pe_ttm_vals)
