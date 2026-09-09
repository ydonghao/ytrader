"""perm-portfolio 真实持仓 → 风险/归因 positions 桥接(纯领域逻辑)。

背景(P0 止血):
    risk_router / portfolio_router 原先读 positions 表, 但全仓库
    没有任何代码写入该表; 空表时仪表盘退化为 random 模拟收益 /
    DEMO_POSITIONS 假数据。本模块把 perm-portfolio 的真实持仓
    (PortfolioHolding) 折算成两套 router 期望的 positions 口径。

字段口径:
    quantity      = holding.shares
    avg_price     = holding.cost_price
    current_price = price_fetcher 返回的最新收盘价(通常查
                    stock_ohlcv); 取不到时兜底为 avg_price,
                    保证仓位可估值; 若 avg_price 也无效(<=0),
                    视为无法估值, 直接跳过该仓位。
                    (未走 stock_valuation total_mv/股本 估值路线,
                    简化取价直接用收盘价。)
    market_value  = quantity × current_price
    ccy           = 标的币种(A 股 CNY 直接用, 记录原币种)

分层约定:
    本模块是 domain 层纯函数, 不 import infra/api/conf。
    DB 读取由调用方(api 层)通过 infra repo 完成后, 以
    HoldingInput 列表传入; 取价通过 price_fetcher 回调注入
    (依赖倒置), 便于单测与替换数据源。
"""
from dataclasses import dataclass
from typing import Callable, Optional

# 取价回调: symbol -> 最新收盘价(原币种); 取不到返回 None。
PriceFetcher = Callable[[str], Optional[float]]


@dataclass
class HoldingInput:
    """perm-portfolio 单持仓输入(由 api 层从 repo 折算而来)。"""

    symbol: str
    shares: int
    cost_price: float = 0.0
    name: str = ""
    ccy: str = "CNY"


def build_positions(
    holdings: list[HoldingInput],
    price_fetcher: Optional[PriceFetcher] = None,
) -> list[dict]:
    """把 perm-portfolio 持仓转成风险/归因模块的 positions 口径。

    Args:
        holdings: 持仓列表; shares<=0 或 symbol 为空的空仓直接忽略。
        price_fetcher: symbol -> 最新收盘价 回调; 传 None 表示完全
            无行情(current_price 全部兜底为 avg_price)。

    Returns:
        list[dict], 每项含 {symbol, name, quantity, avg_price,
        current_price, market_value, ccy}; 无法估值的仓位被跳过。
    """
    positions: list[dict] = []
    for h in holdings:
        if h.shares <= 0 or not h.symbol:
            continue

        current_price: Optional[float] = None
        if price_fetcher is not None:
            try:
                fetched = price_fetcher(h.symbol)
            except Exception:  # 单标的取价失败不阻断整体桥接
                fetched = None
            if fetched is not None and fetched > 0:
                current_price = float(fetched)

        avg_price = float(h.cost_price or 0.0)
        if current_price is None:
            # 无行情: 兜底用成本价(avg_price)估值;
            # 成本价也无效则跳过(下游无法估值该仓位)。
            if avg_price <= 0:
                continue
            current_price = avg_price

        positions.append(
            {
                "symbol": h.symbol,
                "name": h.name or h.symbol,
                "quantity": int(h.shares),
                "avg_price": avg_price,
                "current_price": current_price,
                "market_value": int(h.shares) * current_price,
                "ccy": h.ccy,
            }
        )
    return positions
