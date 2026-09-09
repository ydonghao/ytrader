"""
神奇公式（Magic Formula）
==========================
Joel Greenblatt《股市稳赚》经典。两个指标简单粗暴：
  1. 资本回报率 ROIC = 息税前利润 / 投入资本（越高 = 公司越会赚钱）
  2. 收益率 = 息税前利润 / 企业价值 EBIT/EV（越高 = 越便宜）

规则：全市场分别按这两个指标排名，两排名相加，总分最小的（又好又便宜）
取前 N 只等权持有，定期（季/半年）调仓。

实现：优先用三大报表（stock_financial_detail）算真实 ROIC（EBIT/投入资本）
与 EBIT 收益率（EBIT/EV，企业价值口径），缺明细数据时降级用
roe_weighted 近似 ROIC、1/PE 近似收益率（与选股器同逻辑）。

适用：长期价值投资，长期年化显著跑赢大盘。
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
class MagicFormulaStrategy(LongTermStrategy):
    """神奇公式（ROIC + 收益率双排名，取前 N 等权）。"""

    name: str = "magic_formula"
    display_name: str = "神奇公式"
    one_liner: str = "挑赚钱效率高 + 价格便宜的公司，又好又便宜"
    description: str = (
        "Joel Greenblatt《股市稳赚》经典。两个指标："
        "资本回报率 ROIC（公司赚钱效率）和收益率 EBIT/EV（便宜程度），"
        "全市场分别排名后相加，总分最优的前 N 只等权持有。"
        "长期年化显著跑赢大盘。"
    )
    market_fit: str = "长期价值投资，季度/半年度调仓"
    pros: list = field(default_factory=lambda: [
        "规则极简（就两个指标），逻辑清晰",
        "A股长期回测有效，跑赢沪深300",
        "同时考虑质量(ROIC)和估值(收益率)",
    ])
    risks: list = field(default_factory=lambda: [
        "低估可能更深（价值陷阱）",
        "需要基本面历史数据",
    ])
    family: str = "价值"
    rebalance_freq: str = "quarterly"
    needs_fundamentals: bool = True

    top_n: int = 10               # 持仓数
    min_roe: float = 2.0          # ROE 下限（单季%，剔除亏损/极弱）
    max_pe: float = 50.0          # PE 上限，剔除亏损/泡沫
    min_pe: float = 3.0           # PE 下限，剔除异常（可能是陷阱）

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="top_n", label="持仓数", type="number",
                default=10, min=3, max=30, step=1, unit="只",
                help="选排名前 N 只等权持有",
            ),
            ParamSpec(
                key="min_roe", label="ROE 下限", type="number",
                default=8.0, min=0, max=30, step=1, unit="%",
                help="剔除 ROE 低于此值的公司",
            ),
            ParamSpec(
                key="max_pe", label="PE 上限", type="number",
                default=50.0, min=10, max=200, step=5, unit="",
                help="剔除 PE 过高的泡沫股",
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
        if not valuation_by_symbol or not financials_by_symbol:
            return RebalanceSignal({}, reason="无基本面数据，跳过")

        # 1. 筛候选：满足质量/估值门槛的标的
        # 优先取三大报表算真实 ROIC / EBIT 收益率（EV 口径），
        # 缺明细或字段缺失时降级 ROE + 1/PE（与原逻辑一致）。
        detail_map: dict[str, dict] = {}
        try:
            from ..data_loader import fetch_latest_financial_detail
            detail_map = fetch_latest_financial_detail(
                list(bars_by_symbol.keys()), today
            )
        except Exception:
            detail_map = {}

        roe_map: dict[str, float] = {}      # symbol -> ROIC（降级 ROE）
        earn_yield_map: dict[str, float] = {}  # symbol -> EBIT/EV（降级1/PE）
        for sym in bars_by_symbol:
            val = latest_valuation(valuation_by_symbol.get(sym), today)
            fin = latest_financials(financials_by_symbol.get(sym), today)
            if val is None or fin is None:
                continue

            pe = val.get("pe_ttm") or val.get("pe")
            roe = fin.get("roe_weighted") or fin.get("roe_diluted")
            if pe is None or roe is None:
                continue
            if pe <= self.min_pe or pe > self.max_pe:
                continue
            if roe < self.min_roe:
                continue

            detail = detail_map.get(sym)
            if detail:
                from src.domain.market.fundamental.derived_metrics import (
                    compute_value_metrics,
                )
                m = compute_value_metrics(detail, val)
                roic = m.get("roic")
                ey = m.get("earnings_yield")
                if roic is not None and ey is not None:
                    roe_map[sym] = roic
                    earn_yield_map[sym] = ey
                    continue
            # 降级：ROE + 1/PE
            roe_map[sym] = roe
            earn_yield_map[sym] = 1.0 / pe

        if len(roe_map) < self.top_n:
            return RebalanceSignal(
                {},
                reason=f"达标候选仅 {len(roe_map)} 只，不足 {self.top_n}，跳过",
            )

        # 2. 双排名 + 相加
        roe_rank = rank_cross_section(roe_map, descending=True)
        ey_rank = rank_cross_section(earn_yield_map, descending=True)
        combined: dict[str, float] = {}
        for sym in roe_rank:
            combined[sym] = roe_rank[sym] + ey_rank.get(sym, 0)

        # 3. 取前 N 等权
        selected = top_n_by_score(combined, self.top_n)
        weights = equal_weights(selected)
        return RebalanceSignal(
            weights,
            reason=f"双排名前{self.top_n}等权（候选池{len(roe_map)}只）",
        )
