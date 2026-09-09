"""
全天候资产配置（All Weather）
==============================
Ray Dalio 全天候组合简化版。不选股、不择时，靠多资产分散 + 定期再平衡
赚取"再平衡溢价"——某类资产涨多了就卖一点、跌多了就买一点，纪律性调仓。

经典权重（可调）：
  - 股票 30%（进攻）
  - 长期债券 40%（防御，股债负相关）
  - 中期债券 15%
  - 黄金 7.5%（通胀对冲）
  - 商品 7.5%（通胀对冲）

适用：求稳的长期资金，目标低回撤（< 10%）、稳定复利。
核心价值：纪律性的再平衡，而非选股择时。
"""
from dataclasses import dataclass, field
from datetime import date

from ..base import LongTermStrategy, ParamSpec
from ..models import RebalanceSignal
from ....sync.sync_provider import OHLCVBar


@dataclass
class AllWeatherStrategy(LongTermStrategy):
    """全天候资产配置（固定权重 + 定期再平衡）。"""

    name: str = "all_weather"
    display_name: str = "全天候资产配置"
    one_liner: str = "股债金分散持有，涨多了卖跌多了买，靠再平衡赚溢价"
    description: str = (
        "Ray Dalio 全天候组合简化版。不选股不择时，靠多资产分散 + 定期再平衡："
        "某类资产涨多了就卖一点、跌多了就买一点。"
        "股债负相关 + 黄金抗通胀，追求低回撤稳定复利。"
    )
    market_fit: str = "求稳的长期资金，目标低回撤、稳定复利"
    pros: list = field(default_factory=lambda: [
        "回撤显著低于纯股票（历史<10%）",
        "不择时、不选股，省心",
        "再平衡纪律性带来稳定 alpha",
    ])
    risks: list = field(default_factory=lambda: [
        "牛市明显跑输纯股票",
        "依赖股债负相关，极端时可能同跌",
    ])
    family: str = "资产配置"
    rebalance_freq: str = "quarterly"

    # 默认权重（标的代码: 权重）。可由 params 覆盖。
    # 实盘需开通对应 ETF；回测也可用指数代理。
    weights: dict = field(default_factory=lambda: {
        "sh510300": 0.30,    # 沪深300 ETF（股票）
        "sh511010": 0.40,    # 国债 ETF（长期债券）
        "sh511260": 0.15,    # 国债指数 ETF（中期债券）
        "sh518880": 0.075,   # 黄金 ETF
        "sh510980": 0.075,   # 商品 ETF（近似）
    })

    def get_param_specs(self) -> list[ParamSpec]:
        return [
            ParamSpec(
                key="rebalance_freq", label="再平衡频率", type="select",
                default=self.rebalance_freq,
                options=["monthly", "quarterly", "yearly"],
                help="多久把组合拉回目标权重一次",
            ),
        ]

    def get_params(self) -> dict:
        return {"weights": self.weights, "rebalance_freq": self.rebalance_freq}

    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol=None,
        financials_by_symbol=None,
        state=None,
    ) -> RebalanceSignal:
        # 全天候永远回到固定目标权重，不管市场涨跌。
        # 只纳入有数据的标的（回测时某 ETF 可能缺数据）。
        valid = {
            sym: w for sym, w in self.weights.items()
            if sym in bars_by_symbol and len(bars_by_symbol[sym]) > 0
        }
        if not valid:
            return RebalanceSignal({}, reason="无可用资产数据")
        return RebalanceSignal(valid, reason="回到全天候目标权重")
