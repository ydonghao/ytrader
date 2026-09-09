"""
网格做T（Grid）
================
最经典、最易懂的做T算法。

原理：以当日开盘价为基准，把 [基准*(1-band), 基准*(1+band)] 区间
均分成 grids 格。价格每下穿一条网格线买入一份，每上穿一条卖出一份。

大白话："把价格切成像棋盘一样的格子，跌一格买一手、涨一格卖一手，
来回震荡就不断赚差价。"

适用：震荡行情（不适合单边大涨大跌）。
"""
from dataclasses import dataclass, field

from ....sync.sync_provider import OHLCVBar
from ..models import TSignal, TStrategyState
from .base import ParamSpec, TStrategy


@dataclass
class GridStrategy(TStrategy):
    """
    网格做T

    Args:
        band_pct:   网格总半宽（如 0.10 表示 ±10%）
        grids:      网格数（区间被分成 grids 格）
        qty_per_grid: 每格交易股数（0 = 自动按底仓/grids 算）
    """
    name: str = "grid"
    display_name: str = "网格做T"
    one_liner: str = "把价格切成格子，跌一格买、涨一格卖，震荡就赚钱"
    description: str = (
        "以开盘价为基准价，上下各 band_pct% 形成价格区间，"
        "再均分成 grids 个网格。价格每向下跌破一条网格线，就买入一份；"
        "每向上涨破一条网格线，就卖出一份。只要价格在区间内来回波动，"
        "就能不断低买高卖赚取差价。"
    )
    market_fit: str = "震荡行情（横盘整理）"
    pros: list = field(default_factory=lambda: [
        "逻辑简单，不预测涨跌",
        "震荡市稳定赚取差价",
        "参数少，易于理解",
    ])
    risks: list = field(default_factory=lambda: [
        "单边大涨：早早卖飞，错过行情",
        "单边大跌：一路买入被套，资金耗尽",
    ])

    band_pct: float = 0.08
    grids: int = 6
    qty_per_grid: int = 0

    def __post_init__(self):
        self._base = 0.0
        self._lines: list[float] = []
        self._level = 0   # 当前所处网格层级（0 = 基准）

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="band_pct", label="网格半宽", type="number",
                default=0.08, min=0.02, max=0.30, step=0.01, unit="",
                help="上下各多少比例形成网格区间，0.08 = ±8%",
            ),
            ParamSpec(
                key="grids", label="网格数", type="number",
                default=6, min=2, max=20, step=1, unit="格",
                help="区间被分成多少格，越多越频繁、每格差价越小",
            ),
            ParamSpec(
                key="qty_per_grid", label="每格股数", type="number",
                default=0, min=0, max=10000, step=100, unit="股",
                help="每触发一格买卖多少股；填0自动按 底仓÷网格数 计算",
            ),
        ]

    def get_params(self) -> dict:
        return {
            "band_pct": self.band_pct,
            "grids": self.grids,
            "qty_per_grid": self.qty_per_grid,
        }

    def on_day_start(self, day_open: float, prev_close: float) -> None:
        self._base = day_open
        lo = day_open * (1 - self.band_pct)
        hi = day_open * (1 + self.band_pct)
        step = (hi - lo) / self.grids
        self._lines = [lo + step * i for i in range(self.grids + 1)]
        self._level = self.grids // 2   # 起点在中线

    def _qty(self, state: TStrategyState) -> int:
        if self.qty_per_grid > 0:
            return self.qty_per_grid
        # 自动：底仓均分到每个方向
        return max(state.base_shares // self.grids, 100)

    def on_bar(
        self, bar: OHLCVBar, state: TStrategyState
    ) -> list[TSignal]:
        if not self._lines:
            return []
        price = bar.close_
        qty = self._qty(state)

        # 找当前价格对应的网格层级
        new_level = 0
        for i, line in enumerate(self._lines):
            if price >= line:
                new_level = i

        signals: list[TSignal] = []
        # 价格下移 → 买入
        if new_level < self._level:
            steps = self._level - new_level
            signals.append(TSignal(
                action="BUY",
                quantity=qty * steps,
                reason=f"价格下穿网格 {self._level}→{new_level}",
            ))
        # 价格上移 → 卖出
        elif new_level > self._level:
            steps = new_level - self._level
            signals.append(TSignal(
                action="SELL",
                quantity=qty * steps,
                reason=f"价格上穿网格 {self._level}→{new_level}",
            ))
        self._level = new_level
        return signals
