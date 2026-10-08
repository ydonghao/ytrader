"""课程组合周检视(课程24第九节量化, 纯函数)。

单腿四态建议(优先级从高到低):
- BREAKDOWN: 现价 < 最低档价格 → 破位, 先复查基本面勿急于补仓
- BUY_RUNG:  现价 ≤ 下一未执行档价格 → 建议按档买入
- TRIM:      实际权重 − 目标权重 > 阈值(上涨被动超配) → 建议减仓至目标
- HOLD:      其他(含距下一档距离/建仓完成权重正常/无档位观察/停牌跳过)

组合层: 建仓进度、现金余额、类别实际市值 vs 目标权重、加权股息率。
当前估值状态与收盘价由调用方注入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

TRIM_WEIGHT_DRIFT = 0.03   # 超配阈值(3pct)


@dataclass
class LegReviewInput:
    """单腿检视输入。"""

    symbol: str
    name: str
    category: str
    target_weight: float
    entry_plan: list[dict]
    shares: int
    invested_amount: float
    current_price: Optional[float]
    dv_ttm: Optional[float]
    pe_state: Optional[str]


@dataclass
class LegAdvice:
    """单腿建议。"""

    symbol: str
    code: str          # BUY_RUNG | TRIM | BREAKDOWN | HOLD
    message: str
    amount: Optional[float] = None
    shares: Optional[int] = None


@dataclass
class PortfolioReview:
    """组合层检视结果。"""

    advices: list[LegAdvice] = field(default_factory=list)
    progress_invested: float = 0.0
    progress_target: float = 0.0
    cash_remaining: float = 0.0
    category_actual: dict[str, float] = field(default_factory=dict)
    category_target: dict[str, float] = field(default_factory=dict)
    dividend_yield_weighted: Optional[float] = None


def review_leg(
    inp: LegReviewInput,
    total_capital: float,
    drift_threshold: float = TRIM_WEIGHT_DRIFT,
) -> LegAdvice:
    """单腿检视(优先级 破位 > 买入触发 > 超配 > 持有)。"""
    plan = inp.entry_plan or []
    price = inp.current_price
    if not plan:
        return LegAdvice(inp.symbol, "HOLD", "该腿无建仓档位(估值数据不足或虚高), 持续观察")
    if price is None or price <= 0:
        return LegAdvice(inp.symbol, "HOLD", "无最新收盘价(可能停牌), 跳过检视")

    lowest = min(r["price_level"] for r in plan)
    if lowest > 0 and price < lowest:
        return LegAdvice(inp.symbol, "BREAKDOWN",
                         "现价跌破最低建仓档: 先复查基本面逻辑是否变化, 勿急于补仓")

    pending = [r for r in plan if not r.get("executed")]
    if pending:
        # 价格下跌时最先触发的是价格最高的未执行档
        nxt = max(pending, key=lambda r: r["price_level"])
        if price <= nxt["price_level"]:
            shares = int(nxt["amount"] / price // 100) * 100
            return LegAdvice(inp.symbol, "BUY_RUNG",
                             f"触发第 {nxt['rung_index'] + 1} 档买点"
                             f"(≤{nxt['price_level']:.2f}), 建议买入约 {nxt['amount']:.0f} 元",
                             amount=nxt["amount"], shares=shares)
        # 未触发买入 → 检查中途超配
        pv = inp.shares * price
        actual_w = pv / total_capital if total_capital > 0 else 0.0
        if inp.shares > 0 and actual_w - inp.target_weight > drift_threshold:
            return LegAdvice(inp.symbol, "TRIM",
                             f"被动超配(实际 {actual_w:.1%} vs 目标 "
                             f"{inp.target_weight:.1%}), 建议适度减仓至目标")
        dist = (price / nxt["price_level"] - 1) * 100
        return LegAdvice(inp.symbol, "HOLD",
                         f"距下一档({nxt['price_level']:.2f})还有 {dist:.1f}%")

    # 档位全部执行 → 权重检查
    pv = inp.shares * price
    actual_w = pv / total_capital if total_capital > 0 else 0.0
    if actual_w - inp.target_weight > drift_threshold:
        return LegAdvice(inp.symbol, "TRIM",
                         f"被动超配(实际 {actual_w:.1%} vs 目标 "
                         f"{inp.target_weight:.1%}), 建议适度减仓至目标")
    return LegAdvice(inp.symbol, "HOLD", "建仓完成, 权重正常")


def review_portfolio(
    legs: list[LegReviewInput],
    total_capital: float,
    cash_reserve_pct: float,
    drift_threshold: float = TRIM_WEIGHT_DRIFT,
) -> PortfolioReview:
    """组合层检视: 单腿建议 + 进度/现金/类别结构/加权股息率。"""
    advices = [review_leg(l, total_capital, drift_threshold) for l in legs]
    invested = sum(l.invested_amount or 0.0 for l in legs)
    target_total = 0.0
    cat_actual: dict[str, float] = {}
    cat_target: dict[str, float] = {}
    wsum = 0.0
    wdv = 0.0
    for l in legs:
        target_total += sum((r.get("amount", 0.0) for r in (l.entry_plan or [])), 0.0)
        pv = (l.shares or 0) * l.current_price if l.current_price else 0.0
        cat_actual[l.category] = cat_actual.get(l.category, 0.0) + pv
        cat_target[l.category] = cat_target.get(l.category, 0.0) + l.target_weight
        if l.dv_ttm is not None and pv > 0:
            wsum += pv
            wdv += l.dv_ttm * pv
    investable = total_capital * (1 - cash_reserve_pct)
    return PortfolioReview(
        advices=advices,
        progress_invested=invested,
        progress_target=target_total,
        cash_remaining=investable - invested,
        category_actual=cat_actual,
        category_target=cat_target,
        dividend_yield_weighted=(wdv / wsum) if wsum > 0 else None,
    )
