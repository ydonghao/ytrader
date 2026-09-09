"""安全边际驱动的仓位 sizing(纯领域函数)。

设计目标:
    - 纯函数, 无 DB / IO 依赖, 易于单测;
    - 不依赖 DCF 模块, 只接收 ``margin_of_safety`` 数值(0~1),
      由调用方决定如何估算(DCF 内在价值 vs 现价, 或估值分位推断);
    - 给出三类能力:
        1. :func:`size_by_margin`   — 单次目标仓位 sizing;
        2. :func:`plan_laddering`   — 分批(越跌越买)建仓计划;
        3. :func:`apply_buy_fill` /
           :func:`apply_sell_fill` — 成交回写到单标的持仓的纯算术
           (加权平均成本 / 已实现盈亏), 供 infra 层回写 positions 表复用。

口径约定:
    - ``margin_of_safety`` ∈ [0, 1], 越大 = 越便宜 = 仓位越大;
    - ``max_weight`` 为单标的的总权重上限(含已持仓);
    - 资金按 ``lot_size``(默认 100 股)向下取整, 不足一手则不建仓;
    - 波动率缩放: 高波动降仓, 下限 ``vol_floor``(避免清零)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── 结果数据结构 ───────────────────────────────────────────────────────────────


@dataclass
class SizingResult:
    """ :func:`size_by_margin` 的返回。"""

    target_value: float          # 目标投入资金(元)
    quantity: int                # 取整到 lot_size 倍数的股数
    weight: float                # target_value / total_capital
    margin_of_safety: float      # 透传输入(诊断用)
    vol_scale: float             # 波动率缩放系数(1.0=未缩放)
    skipped: bool                # 是否不建仓
    reason: str = ""             # skipped/截断原因

    def __bool__(self) -> bool:  # noqa: D401 - 语义: 是否产生了仓位
        """True 表示应建仓(quantity > 0)。"""
        return (not self.skipped) and self.quantity > 0


@dataclass
class LadderRung:
    """分批建仓的单档。"""

    price_level: float           # 触发价(元)
    drop_pct: float              # 相对初始价的跌幅(正数, 0=初始档)
    add_quantity: int            # 该档加仓股数(lot 倍数)
    add_value: float             # 该档加仓金额(元)
    cumulative_quantity: int     # 截至该档的累计股数
    cumulative_value: float      # 截至该档的累计投入(元)


# ── 内部工具 ───────────────────────────────────────────────────────────────────


def _clamp(value: float, lo: float, hi: float) -> float:
    """将 value 限制到 [lo, hi]。"""
    return max(lo, min(hi, value))


def _round_to_lot(value: float, price: float, lot_size: int) -> int:
    """把目标金额按 price 折算成股数并向下取整到 lot_size 倍数。"""
    if price is None or price <= 0 or lot_size <= 0:
        return 0
    lots = int(value // price // lot_size)
    return lots * lot_size


# ── 核心: 安全边际 sizing ─────────────────────────────────────────────────────


def size_by_margin(
    margin_of_safety: float,
    total_capital: float,
    current_position: float = 0.0,
    price: Optional[float] = None,
    volatility: Optional[float] = None,
    max_weight: float = 0.25,
    min_margin: float = 0.10,
    vol_reference: float = 0.25,
    vol_floor: float = 0.25,
    lot_size: int = 100,
) -> SizingResult:
    """根据安全边际计算目标仓位。

    规则:
        1. ``margin_of_safety < min_margin``  → 不建仓(安全边际不足);
        2. margin ∈ [min_margin, 1] 线性映射到权重 [0, max_weight];
        3. 叠加单标的总权重上限: 含已持仓不超过 ``max_weight``,
           若已到/超上限 → 不建仓;
        4. 可选波动率缩放: ``vol_scale = vol_reference / volatility``,
           截断到 [vol_floor, 1.0], 高波动降仓但不清零;
        5. 资金按 ``lot_size`` 向下取整, 不足一手则 quantity=0。

    Args:
        margin_of_safety: 安全边际(0~1), 调用方提供。
        total_capital: 总资金(元)。
        current_position: 当前已持仓股数(用于单标的权重上限核算)。
        price: 当前价; 传入才能把资金折算成股数。
        volatility: 年化波动率(如 0.30); None 表示不缩放。
        max_weight: 单标的总权重上限, 默认 0.25。
        min_margin: 建仓所需的最小安全边际, 默认 0.10。
        vol_reference: 基准波动率(等于该值时缩放系数=1.0)。
        vol_floor: 波动率缩放下限(避免高波动清零)。
        lot_size: 最小交易手数对应的股数, 默认 100。

    Returns:
        :class:`SizingResult`。
    """
    base = SizingResult(
        target_value=0.0,
        quantity=0,
        weight=0.0,
        margin_of_safety=margin_of_safety,
        vol_scale=1.0,
        skipped=True,
    )

    if total_capital <= 0:
        base.reason = "total_capital <= 0"
        return base

    if margin_of_safety < min_margin:
        base.reason = (
            f"margin_of_safety {margin_of_safety:.3f} < "
            f"min_margin {min_margin:.3f}"
        )
        return base

    # 1) margin → 原始权重(线性映射到 [0, max_weight])
    span = max(1e-9, 1.0 - min_margin)
    raw = _clamp((margin_of_safety - min_margin) / span, 0.0, 1.0)
    weight = raw * max_weight

    # 2) 单标的总权重上限(扣减已持仓)
    held_weight = 0.0
    if price and price > 0 and current_position > 0:
        held_weight = (current_position * price) / total_capital
    allowed = max_weight - held_weight
    if allowed <= 0:
        base.reason = (
            f"already at max_weight {max_weight:.3f} "
            f"(held {held_weight:.3f})"
        )
        return base
    weight = min(weight, allowed)

    # 3) 波动率缩放(高波动降仓)
    vol_scale = 1.0
    if volatility is not None and volatility > 0:
        vol_scale = _clamp(vol_reference / volatility, vol_floor, 1.0)
    weight *= vol_scale

    target_value = weight * total_capital
    quantity = _round_to_lot(target_value, price or 0.0, lot_size)

    return SizingResult(
        target_value=target_value,
        quantity=quantity,
        weight=weight,
        margin_of_safety=margin_of_safety,
        vol_scale=vol_scale,
        skipped=quantity <= 0,
        reason=("" if quantity > 0 else "below one lot"),
    )


# ── 分批建仓(越跌越买)─────────────────────────────────────────────────────────


def plan_laddering(
    margin_of_safety: float,
    price: float,
    total_capital: float,
    current_position: int = 0,
    volatility: Optional[float] = None,
    max_weight: float = 0.25,
    min_margin: float = 0.10,
    steps: int = 3,
    step_drop: float = 0.05,
    lot_size: int = 100,
) -> list[LadderRung]:
    """生成"初始仓位 + 越跌越买"的分批建仓计划。

    由当前 ``(margin_of_safety, price)`` 反推隐含内在价值
    ``iv = price / (1 - margin_of_safety)``; 之后每下跌 ``step_drop``
    触发一档, 该档的 margin 随价格下行而升高, 从而 :func:`size_by_margin`
    给出更大的加仓量(越跌越买)。

    每档独立对 ``total_capital`` 做 sizing(视为"价格跌到该档时买入多少"
    的条件单), ``cumulative_*`` 汇总为满仓后的潜在总暴露。

    Args:
        margin_of_safety: 当前价对应的安全边际(0~1)。
        price: 当前价(元)。
        total_capital: 总资金(元)。
        current_position: 已持仓股数(计入初始档累计)。
        volatility: 年化波动率; None 不缩放。
        max_weight / min_margin / lot_size: 透传给 :func:`size_by_margin`。
        steps: 额外的下跌加仓档数(不含初始档)。
        step_drop: 每档相对上一档的跌幅, 默认 5%。

    Returns:
        ``list[LadderRung]``; 输入非法(margin < min_margin / 价格无效)
        时返回空列表。
    """
    if (
        margin_of_safety < min_margin
        or price is None
        or price <= 0
        or total_capital <= 0
    ):
        return []

    # 反推隐含内在价值(clamp margin 防止除零/负价)
    m_for_iv = min(max(margin_of_safety, 1e-6), 0.999)
    iv = price / (1.0 - m_for_iv)

    rungs: list[LadderRung] = []
    cum_qty = int(current_position)
    cum_val = cum_qty * price

    for i in range(steps + 1):
        if i == 0:
            level_price = price
            level_margin = margin_of_safety
        else:
            level_price = price * ((1.0 - step_drop) ** i)
            level_margin = _clamp(1.0 - level_price / iv, 0.0, 0.99)

        sizing = size_by_margin(
            level_margin,
            total_capital,
            current_position=0,
            price=level_price,
            volatility=volatility,
            max_weight=max_weight,
            min_margin=min_margin,
            lot_size=lot_size,
        )
        add_qty = sizing.quantity
        cum_qty += add_qty
        cum_val += add_qty * level_price

        rungs.append(
            LadderRung(
                price_level=level_price,
                drop_pct=1.0 - level_price / price,
                add_quantity=add_qty,
                add_value=add_qty * level_price,
                cumulative_quantity=cum_qty,
                cumulative_value=cum_val,
            )
        )

    return rungs


# ── 成交回写算术(供 infra 层回写 positions 表)─────────────────────────────────


def apply_buy_fill(
    quantity: int,
    avg_price: float,
    fill_qty: int,
    fill_price: float,
) -> tuple[int, float]:
    """买入成交后更新持仓(加权平均成本)。

    Args:
        quantity: 原持仓股数。
        avg_price: 原持仓均价。
        fill_qty: 本次买入股数。
        fill_price: 本次成交价。

    Returns:
        (new_quantity, new_avg_price)。
    """
    fill_qty = max(0, fill_qty)
    new_qty = int(quantity) + fill_qty
    if new_qty <= 0 or fill_price <= 0:
        # 无有效成交: 维持原状(或空仓)
        if new_qty <= 0:
            return 0, 0.0
        return int(quantity), float(avg_price or 0.0)

    old_cost = int(quantity) * float(avg_price or 0.0)
    new_avg = (old_cost + fill_qty * fill_price) / new_qty
    return new_qty, new_avg


def apply_sell_fill(
    quantity: int,
    avg_price: float,
    fill_qty: int,
    fill_price: float,
) -> tuple[int, float, float]:
    """卖出成交后更新持仓。

    Args:
        quantity: 原持仓股数。
        avg_price: 原持仓均价。
        fill_qty: 本次卖出股数(超过持仓时只平掉持仓)。
        fill_price: 本次成交价。

    Returns:
        (new_quantity, new_avg_price, realized_pnl)。
        清仓后 new_avg_price 归零; realized_pnl 为本次已实现盈亏。
    """
    qty = max(0, int(quantity))
    sell_qty = min(max(0, fill_qty), qty)
    realized = (fill_price - float(avg_price or 0.0)) * sell_qty
    new_qty = qty - sell_qty
    new_avg = float(avg_price or 0.0) if new_qty > 0 else 0.0
    return new_qty, new_avg, realized


__all__ = [
    "SizingResult",
    "LadderRung",
    "size_by_margin",
    "plan_laddering",
    "apply_buy_fill",
    "apply_sell_fill",
]
