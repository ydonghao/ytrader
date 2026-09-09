"""组合净值计算引擎（纯函数，无 DB 依赖）。

核算口径: 持仓制
    组合净值 = Σ(持仓股数 × 当日收盘价 × 汇率→CNY)
    nav_cny  = total_value_cny / initial_capital  (归一化, 初始日=1.0)

权重约定:
    holding.target_weight 是单标的目标权重。
    再平衡判断按资产类(equity/bond/gold/cash)聚合:
      某资产类有多只标的时, 各 target_weight 之和 = 该类目标权重。
    单标的的 drift 字段记录它对所在资产类偏离的贡献;
    触发再平衡的 max_drift 是资产类层面的偏离绝对值。
"""
from dataclasses import dataclass, field
from typing import Optional


# 四类标准资产（永久组合核心）。资产类聚合时按此枚举。
ASSET_CLASSES = ("equity", "bond", "gold", "cash")


@dataclass
class NavItemInput:
    """单标的净值计算输入。"""

    instrument_id: int
    symbol: str
    asset_class: str       # equity | bond | gold | cash
    target_weight: float   # 单标的的目标权重(0~1)
    shares: int            # 持仓股数
    price: float           # 当日收盘价(原币种)
    fx_rate: float = 1.0   # 折算 CNY 汇率(CNY 标的=1.0)


@dataclass
class NavItemOutput:
    """单标的净值计算输出。"""

    instrument_id: int
    symbol: str
    asset_class: str
    shares: int
    price: float
    fx_rate: float
    price_cny: float       # = price * fx_rate
    value_cny: float       # = shares * price_cny
    target_weight: float
    actual_weight: float   # = value_cny / total_value_cny
    drift: float           # = actual_weight - target_weight (单标的层面)


@dataclass
class AssetClassBreakdown:
    """某资产类的聚合偏离。"""

    asset_class: str
    target_weight: float   # 该类所有标的 target_weight 之和
    actual_weight: float   # 该类所有标的 actual_weight 之和
    drift: float           # = actual_weight - target_weight


@dataclass
class NavResult:
    """组合净值计算结果。"""

    total_value_cny: float
    nav_cny: float
    prev_nav_cny: Optional[float]
    daily_return: Optional[float]
    items: list[NavItemOutput] = field(default_factory=list)
    breakdowns: list[AssetClassBreakdown] = field(default_factory=list)
    max_drift: float = 0.0
    rebalance_suggested: bool = False


def calc_portfolio_nav(
    initial_capital: float,
    threshold: float,
    items_in: list[NavItemInput],
    prev_nav_cny: Optional[float] = None,
) -> NavResult:
    """计算组合单日净值、各资产实际权重与偏离度。

    Args:
        initial_capital: 初始资金(人民币), 作为净值归一化基准。
        threshold:       触发再平衡的资产类偏离阈值(绝对值, 0~1)。
        items_in:        各标的当日输入(含收盘价/汇率/持仓)。
        prev_nav_cny:    上一交易日净值, 用于算日收益率。

    Returns:
        NavResult: 含净值、各标的明细、资产类聚合偏离、最大偏离、
                   是否建议再平衡。
    """
    # 1. 每标的折算人民币市值
    items: list[NavItemOutput] = []
    for it in items_in:
        price_cny = it.price * it.fx_rate
        value_cny = it.shares * price_cny
        items.append(
            NavItemOutput(
                instrument_id=it.instrument_id,
                symbol=it.symbol,
                asset_class=it.asset_class,
                shares=it.shares,
                price=it.price,
                fx_rate=it.fx_rate,
                price_cny=price_cny,
                value_cny=value_cny,
                target_weight=it.target_weight,
                actual_weight=0.0,   # 占位, 下一步填
                drift=0.0,
            )
        )

    # 2. 总市值
    total_value_cny = sum(it.value_cny for it in items)

    # 3. 单标的实际权重
    for it in items:
        it.actual_weight = (
            it.value_cny / total_value_cny if total_value_cny > 0 else 0.0
        )
        it.drift = it.actual_weight - it.target_weight

    # 4. 资产类聚合偏离
    breakdowns: list[AssetClassBreakdown] = []
    for ac in ASSET_CLASSES:
        tgt = sum(
            it.target_weight for it in items if it.asset_class == ac
        )
        act = sum(
            it.actual_weight for it in items if it.asset_class == ac
        )
        if tgt == 0.0 and act == 0.0:
            continue  # 该资产类无标的, 跳过
        breakdowns.append(
            AssetClassBreakdown(
                asset_class=ac,
                target_weight=tgt,
                actual_weight=act,
                drift=act - tgt,
            )
        )

    # 5. 最大资产类偏离(绝对值)
    max_drift = max((abs(b.drift) for b in breakdowns), default=0.0)

    # 6. 归一化净值
    nav_cny = (
        total_value_cny / initial_capital
        if initial_capital > 0
        else 0.0
    )
    daily_return = (
        (nav_cny - prev_nav_cny) / prev_nav_cny
        if prev_nav_cny and prev_nav_cny != 0
        else None
    )

    return NavResult(
        total_value_cny=total_value_cny,
        nav_cny=nav_cny,
        prev_nav_cny=prev_nav_cny,
        daily_return=daily_return,
        items=items,
        breakdowns=breakdowns,
        max_drift=max_drift,
        rebalance_suggested=max_drift > threshold,
    )
