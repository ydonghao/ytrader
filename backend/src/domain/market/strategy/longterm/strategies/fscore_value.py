"""
Piotroski F-Score 价值策略
============================
Joseph Piotroski 2000 年经典论文。核心洞察：
**便宜的股票里，多数是"价值陷阱"（便宜有便宜的道理）。**
用 9 项财务质量打分（F-Score 0~9）筛掉质量差的，只买"便宜且质量在改善"的。

F-Score 9 项（盈利/杠杆/效率三组）：
  盈利：
    1. ROA 为正
    2. ROA 同比上升
    3. 经营现金流为正
    4. 现金流 ROA > 会计 ROA（质量高）
  杠杆：
    5. 资产负债率下降
    6. 流动比率上升
    7. 不增发新股
  效率：
    8. 毛利率上升
    9. 资产周转率上升

简化（本实现，受限于财务表字段）：用 ROE/毛利率/负债率/净利率的变化打分，
得到 0~5 的简化 F-Score。配合低 PB 筛选，选高 F-Score + 低 PB 的前 N 只。

适用：长期价值，深度防御型，回撤低、胜率高。
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
class FScoreValueStrategy(LongTermStrategy):
    """Piotroski F-Score 价值策略（简化版 + 低 PB）。"""

    name: str = "fscore_value"
    display_name: str = "F-Score 价值"
    one_liner: str = "挑便宜的股票里质量最好的，避开价值陷阱"
    description: str = (
        "Piotroski 经典。便宜的股票里多是价值陷阱，"
        "用 9 项财务质量打分（简化为 ROE/毛利率/负债率/净利率改善度）筛掉差的，"
        "只买【便宜且质量在改善】的。配低 PB 筛选，深度防御型。"
    )
    market_fit: str = "长期价值投资，防御型，胜率高回撤低"
    pros: list = field(default_factory=lambda: [
        "有效避开价值陷阱",
        "高 F-Score 公司基本面扎实",
        "回撤低、胜率高",
    ])
    risks: list = field(default_factory=lambda: [
        "牛市弹性弱",
        "需要财务历史数据",
    ])
    family: str = "价值"
    rebalance_freq: str = "quarterly"
    needs_fundamentals: bool = True

    top_n: int = 10
    max_pb: float = 3.0          # PB 上限，只看便宜股
    min_fscore: int = 3          # F-Score 下限（简化版 0~5）

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="top_n", label="持仓数", type="number",
                default=10, min=3, max=30, step=1, unit="只",
            ),
            ParamSpec(
                key="max_pb", label="PB 上限", type="number",
                default=3.0, min=1, max=10, step=0.5, unit="",
                help="只考虑 PB 低于此值的便宜股",
            ),
            ParamSpec(
                key="min_fscore", label="F-Score 下限", type="number",
                default=3, min=0, max=5, step=1, unit="分",
                help="简化版 0~5，剔除质量差的",
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

        # 1. 低 PB 筛选 + F-Score 计算
        scores: dict[str, float] = {}
        pb_map: dict[str, float] = {}
        for sym in bars_by_symbol:
            val = latest_valuation(valuation_by_symbol.get(sym), today)
            if val is None:
                continue
            pb = val.get("pb")
            if pb is None or pb <= 0 or pb > self.max_pb:
                continue
            # F-Score 需要最近两期财务
            fin_rows = financials_by_symbol.get(sym, [])
            fscore = self._fscore(fin_rows, today)
            if fscore is None or fscore < self.min_fscore:
                continue
            scores[sym] = float(fscore)
            pb_map[sym] = pb

        if len(scores) < self.top_n:
            return RebalanceSignal(
                {},
                reason=f"达标候选仅 {len(scores)} 只，跳过",
            )

        # 2. F-Score 高 + PB 低（PB 反向排名）
        fscore_rank = rank_cross_section(scores, descending=True)
        pb_rank = rank_cross_section(pb_map, descending=False)  # 低 PB 高分位
        combined = {
            sym: fscore_rank[sym] + pb_rank.get(sym, 0)
            for sym in scores
        }

        # 3. 取前 N 等权
        selected = top_n_by_score(combined, self.top_n)
        weights = equal_weights(selected)
        return RebalanceSignal(
            weights,
            reason=f"F-Score+低PB前{self.top_n}等权（候选{len(scores)}只）",
        )

    @staticmethod
    def _fscore(
        fin_rows: list[dict],
        today: date,
    ) -> Optional[int]:
        """
        简化 F-Score（0~5）。需要至少最近两期财报。
        打分项：
          1. ROE 为正              +1
          2. ROE 同比上升          +1
          3. 净利率为正            +1
          4. 净利率上升            +1
          5. 资产负债率下降        +1
        """
        from .value_utils import latest_financials

        cur = latest_financials(fin_rows, today)
        if cur is None:
            return None
        # 找上一期：report_date < cur 的最新
        from datetime import timedelta
        from .value_utils import _as_date, FINANCIAL_LAG_DAYS

        cur_date = _as_date(cur.get("report_date"))
        if cur_date is None:
            return None
        prev = None
        prev_date = None
        cutoff = today - timedelta(days=FINANCIAL_LAG_DAYS)
        for r in fin_rows:
            d = _as_date(r.get("report_date"))
            if d is None or d > cutoff or d >= cur_date:
                continue
            if prev_date is None or d > prev_date:
                prev_date = d
                prev = r
        if prev is None:
            return None

        score = 0
        roe_cur = cur.get("roe_weighted") or cur.get("roe_diluted")
        roe_prev = prev.get("roe_weighted") or prev.get("roe_diluted")
        nm_cur = cur.get("net_margin")
        nm_prev = prev.get("net_margin")
        dr_cur = cur.get("debt_ratio")
        dr_prev = prev.get("debt_ratio")

        if roe_cur is not None and roe_cur > 0:
            score += 1
        if roe_cur is not None and roe_prev is not None and roe_cur > roe_prev:
            score += 1
        if nm_cur is not None and nm_cur > 0:
            score += 1
        if nm_cur is not None and nm_prev is not None and nm_cur > nm_prev:
            score += 1
        if dr_cur is not None and dr_prev is not None and dr_cur < dr_prev:
            score += 1
        return score
