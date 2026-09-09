"""再平衡建议引擎（纯函数，无 DB 依赖）。

当某资产类偏离目标权重超过阈值时, 给出具体买卖指令:
  - 超配类: 算需卖出的市值 = (actual - target) × total_value
            按该类内各标的当前市值比例分摊卖出股数
  - 低配类: 算需买入的市值 = (target - actual) × total_value
            按该类内各标的的目标权重比例分摊买入股数

输出为 RebalanceAction 列表, action="BUY"/"SELL", shares_delta
为正数绝对值(方向由 action 决定)。
"""
from dataclasses import dataclass

from .nav_calculator import NavItemOutput, AssetClassBreakdown


@dataclass
class RebalanceAction:
    """单标的再平衡指令。"""

    instrument_id: int
    symbol: str
    asset_class: str
    action: str            # "BUY" | "SELL"
    shares_delta: int      # 调仓股数(正数绝对值, 方向由 action 决定)
    value_cny: float       # 对应的人民币金额
    reason: str


def _round_lot(shares: float) -> int:
    """向下取整到整手(A股100股/港股/美股按1股)。

    保守取整: 不足1股的部分丢弃, 避免过度交易。
    """
    n = int(shares)
    return n if n > 0 else 0


def suggest_rebalance(
    items: list[NavItemOutput],
    breakdowns: list[AssetClassBreakdown],
    total_value_cny: float,
    threshold: float,
) -> list[RebalanceAction]:
    """根据当前持仓与偏离, 给出再平衡买卖指令。

    Args:
        items:           当前各标的明细(来自 NavResult.items)。
        breakdowns:      资产类聚合偏离(来自 NavResult.breakdowns)。
        total_value_cny: 当前组合总市值(人民币)。
        threshold:       偏离阈值, 超过则触发该类的再平衡。

    Returns:
        list[RebalanceAction]: 需要调仓的标的指令。无偏离时返回空列表。
    """
    if total_value_cny <= 0:
        return []

    actions: list[RebalanceAction] = []

    for b in breakdowns:
        if abs(b.drift) <= threshold:
            continue  # 该类未超阈值, 跳过

        # 该类所有标的
        class_items = [
            it for it in items if it.asset_class == b.asset_class
        ]
        if not class_items:
            continue

        if b.drift > 0:
            # 超配 → 卖出。按当前市值比例分摊
            class_value = sum(it.value_cny for it in class_items)
            if class_value <= 0:
                continue
            sell_value = b.drift * total_value_cny
            for it in class_items:
                proportion = it.value_cny / class_value
                target_sell_value = sell_value * proportion
                # 卖出股数 = 目标卖出市值 / 人民币单价
                shares = _round_lot(
                    target_sell_value / it.price_cny
                    if it.price_cny > 0
                    else 0
                )
                if shares <= 0:
                    continue
                actions.append(
                    RebalanceAction(
                        instrument_id=it.instrument_id,
                        symbol=it.symbol,
                        asset_class=it.asset_class,
                        action="SELL",
                        shares_delta=shares,
                        value_cny=round(shares * it.price_cny, 2),
                        reason=(
                            f"{b.asset_class}类超配 "
                            f"{b.drift*100:.1f}% (实际"
                            f"{b.actual_weight*100:.1f}% vs 目标"
                            f"{b.target_weight*100:.1f}%), 卖出回归"
                        ),
                    )
                )
        else:
            # 低配 → 买入。按目标权重比例分摊
            class_target_weight = sum(
                it.target_weight for it in class_items
            )
            if class_target_weight <= 0:
                continue
            buy_value = (-b.drift) * total_value_cny
            for it in class_items:
                proportion = (
                    it.target_weight / class_target_weight
                )
                target_buy_value = buy_value * proportion
                shares = _round_lot(
                    target_buy_value / it.price_cny
                    if it.price_cny > 0
                    else 0
                )
                if shares <= 0:
                    continue
                actions.append(
                    RebalanceAction(
                        instrument_id=it.instrument_id,
                        symbol=it.symbol,
                        asset_class=it.asset_class,
                        action="BUY",
                        shares_delta=shares,
                        value_cny=round(shares * it.price_cny, 2),
                        reason=(
                            f"{b.asset_class}类低配 "
                            f"{abs(b.drift)*100:.1f}% (实际"
                            f"{b.actual_weight*100:.1f}% vs 目标"
                            f"{b.target_weight*100:.1f}%), 买入补足"
                        ),
                    )
                )

    return actions
