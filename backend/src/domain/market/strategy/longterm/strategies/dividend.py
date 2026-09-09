"""
红利策略（Dividend）
====================
A股过去十年最稳的长线 alpha 之一。买高股息率 + 质量过得去的公司，
吃股息 + 享受"红利低波"效应（高股息股通常波动低、抗跌）。

规则：
  1. 质量过滤：ROE > 阈值、资产负债率 < 阈值（剔除分红不可持续的）
  2. 股息率排名：全市场按 dv_ttm（滚动股息率）从高到低
  3. 取前 N 等权持有，定期（季/半年）调仓

适用：长期稳健收益，熊市扛跌，适合追求现金流的长期资金。
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..base import LongTermStrategy, ParamSpec
from ..models import RebalanceSignal
from .value_utils import (
    equal_weights,
    latest_financials,
    latest_valuation,
    rank_cross_section,
    top_n_by_score,
)
from ....sync.sync_provider import OHLCVBar


@dataclass
class DividendStrategy(LongTermStrategy):
    """红利策略（高股息率 + 质量过滤）。"""

    name: str = "dividend"
    display_name: str = "红利策略"
    one_liner: str = "买高股息率的好公司，吃分红又抗跌"
    description: str = (
        "A股过去十年最稳的长线 alpha 之一。买高股息率 + 质量过得去的公司："
        "股息率排名前 N，剔除 ROE 低、负债高的（分红不可持续）。"
        "吃股息 + 享受红利低波效应（高股息股通常波动低、抗跌）。"
    )
    market_fit: str = "长期稳健收益，熊市扛跌，追求现金流"
    pros: list = field(default_factory=lambda: [
        "A股长期有效，年化跑赢沪深300",
        "高股息股波动低、回撤小",
        "现金流稳定（每年有分红）",
    ])
    risks: list = field(default_factory=lambda: [
        "牛市跑输成长股",
        "周期股高股息可能是【价值陷阱】（盈利下行周期）",
    ])
    family: str = "价值"
    rebalance_freq: str = "quarterly"
    needs_fundamentals: bool = True

    top_n: int = 15
    min_dividend_yield: float = 3.0   # 最低股息率（%）
    min_roe: float = 2.0              # ROE 下限（单季%，剔除亏损/极弱）
    max_debt_ratio: float = 95.0      # 资产负债率上限（银行/金融天然高杠杆，放宽）

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="top_n", label="持仓数", type="number",
                default=15, min=3, max=30, step=1, unit="只",
            ),
            ParamSpec(
                key="min_dividend_yield", label="最低股息率", type="number",
                default=3.0, min=0, max=10, step=0.5, unit="%",
                help="低于此股息率的剔除",
            ),
            ParamSpec(
                key="min_roe", label="ROE 下限", type="number",
                default=8.0, min=0, max=30, step=1, unit="%",
                help="剔除 ROE 低的（分红不可持续）",
            ),
            ParamSpec(
                key="max_debt_ratio", label="负债率上限", type="number",
                default=70.0, min=30, max=100, step=5, unit="%",
                help="剔除负债过高的",
            ),
        ]

    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol: Optional[dict[str, list[dict]]] = None,
        financials_by_symbol: Optional[dict[str, list[dict]]] = None,
        state=None,
    ) -> RebalanceSignal:
        if not valuation_by_symbol:
            return RebalanceSignal({}, reason="无估值数据，跳过")

        # 1. 质量 + 股息率筛选（无股息率时降级用低 PB 近似）
        dy_map: dict[str, float] = {}    # symbol -> 股息率（或 PB 倒数）
        use_pb_proxy = True  # 是否在缺股息率时降级
        has_any_dy = False
        for sym in bars_by_symbol:
            val = latest_valuation(valuation_by_symbol.get(sym), today)
            if val is None:
                continue
            dy = val.get("dv_ttm") or val.get("dv_ratio")
            if dy is not None:
                has_any_dy = True
            # 质量过滤（财务数据可用时）
            if financials_by_symbol:
                fin = latest_financials(financials_by_symbol.get(sym), today)
                if fin is not None:
                    roe = fin.get("roe_weighted") or fin.get("roe_diluted")
                    dr = fin.get("debt_ratio")
                    if roe is not None and roe < self.min_roe:
                        continue
                    if dr is not None and dr > self.max_debt_ratio:
                        continue
            if dy is not None and dy >= self.min_dividend_yield:
                dy_map[sym] = dy
            elif use_pb_proxy and dy is None:
                # 降级：用 PB 倒数近似（低 PB ≈ 高股息率，银行/公用事业股）
                pb = val.get("pb")
                if pb is not None and 0 < pb < 3.0:
                    dy_map[sym] = 1.0 / pb

        if len(dy_map) < self.top_n:
            return RebalanceSignal(
                {},
                reason=f"达标候选仅 {len(dy_map)} 只，跳过",
            )

        reason_suffix = "股息率" if has_any_dy else "低PB(股息率缺失，降级)"

        # 2. 股息率（或PB倒数）排名取前 N
        ranked = rank_cross_section(dy_map, descending=True)
        selected = top_n_by_score(ranked, self.top_n)
        weights = equal_weights(selected)
        return RebalanceSignal(
            weights,
            reason=f"高{reason_suffix}前{self.top_n}等权（候选{len(dy_map)}只）",
        )
