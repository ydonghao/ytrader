"""股票投资课程簇 8——杠杆与衍生品（doc 27）纯函数。

面向大资金（七位数以上）的杠杆/对冲工具计算器。课程 doc 27 强调：
杠杆是收益放大器也是风险放大器，必须先算清"杠杆倍数、保证金、成本、对冲手数"。
本模块实现 5 项：

    8.1 期货保证金/杠杆      杠杆=1/保证金率；收益率=合约盈亏/保证金
    8.2 股指期货合约估值      合约价值=指数点×乘数；保证金=价值×保证金率
    8.3 升贴水+交割日信号     basis=期货价−现货价；大升水→交割日卖压
    8.4 融资融券额度/成本     可融额=抵押物/维持担保比例；年化成本
    8.5 β 对冲               等值做空股指期货对冲组合 β，剥离 α

数据可得性
-----------
- 8.1/8.2/8.4/8.5 为纯计算（参数由调用方供给：保证金率/指数点/抵押物/β）；
- 8.3 的期货价/现货价需期货行情数据源（akshare ``futures_zh_daily_sina``，
  同步管道另建）；本模块以价格/交割日为入参。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    from datetime import date, timedelta
except ImportError:  # noqa: BLE001
    pass


# ── 8.1 期货保证金/杠杆 ─────────────────────────────────────────────────────

@dataclass
class FuturesLeverage:
    margin_rate: float         # 保证金率（小数）
    leverage: float            # = 1 / margin_rate
    contract_value: float      # 合约价值
    margin_required: float     # = contract_value × margin_rate


def futures_margin_leverage(
    contract_value: Optional[float],
    margin_rate: Optional[float],
) -> Optional[FuturesLeverage]:
    """杠杆=1/保证金率；保证金=合约价值×保证金率（doc 27）。

    Args:
        contract_value: 单张合约价值（元）。
        margin_rate:    保证金率（小数，如 0.14 = 14%）。

    Returns:
        FuturesLeverage；非法输入返回 None。
    课程：14% 保证金 ≈ 7.14 倍杠杆。
    """
    if (contract_value is None or margin_rate is None
            or contract_value <= 0 or margin_rate <= 0 or margin_rate >= 1):
        return None
    return FuturesLeverage(
        margin_rate=margin_rate,
        leverage=1.0 / margin_rate,
        contract_value=contract_value,
        margin_required=contract_value * margin_rate,
    )


def leveraged_return(
    price_change_pct: Optional[float],
    leverage: Optional[float],
) -> Optional[float]:
    """杠杆放大的收益率 = 价格变动 × 杠杆（doc 27）。

    Args:
        price_change_pct: 标的涨跌幅（小数，如 0.05 = 5%）。
        leverage:         杠杆倍数（=1/保证金率）。

    Returns:
        相对于保证金的收益率（小数）；可正可负（亏损也被放大）。
    """
    if price_change_pct is None or leverage is None or leverage <= 0:
        return None
    return price_change_pct * leverage


# ── 8.2 股指期货合约估值 ────────────────────────────────────────────────────

# 主流股指期货乘数（元/点）。doc 27：IF 沪深300 = 300 元/点。
INDEX_FUTURES_MULTIPLIERS = {
    "IF": 300.0,    # 沪深300
    "IH": 300.0,    # 上证50
    "IC": 200.0,    # 中证500
    "IM": 200.0,    # 中证1000
}


def index_futures_contract_value(
    index_point: Optional[float],
    multiplier: Optional[float] = None,
    *,
    code: Optional[str] = None,
) -> Optional[float]:
    """合约价值 = 指数点 × 乘数（doc 27）。

    Args:
        index_point: 指数点位（如 3800）。
        multiplier:  乘数（元/点）；若 None 则按 ``code`` 查表。
        code:        合约代码 IF/IH/IC/IM，仅在 multiplier 为 None 时用。

    Returns:
        合约价值（元）；非法返回 None。
    """
    if index_point is None or index_point <= 0:
        return None
    if multiplier is None:
        if code is None:
            return None
        multiplier = INDEX_FUTURES_MULTIPLIERS.get(code)
        if multiplier is None:
            return None
    return index_point * multiplier


def index_futures_margin(
    index_point: Optional[float],
    margin_rate: float,
    *,
    multiplier: Optional[float] = None,
    code: Optional[str] = None,
) -> Optional[float]:
    """股指期货保证金 = 合约价值 × 保证金率（doc 27）。"""
    cv = index_futures_contract_value(index_point, multiplier, code=code)
    if cv is None or margin_rate <= 0:
        return None
    return cv * margin_rate


# ── 8.3 升贴水 + 交割日信号 ─────────────────────────────────────────────────

@dataclass
class FuturesBasis:
    basis: float               # 期货价 − 现货价（正=升水，负=贴水）
    basis_pct: float           # basis / 现货价
    contango: bool             # 升水（期货 > 现货）
    delivery_sell_pressure: bool  # 大升水 → 交割日卖压


def futures_basis_signal(
    futures_price: Optional[float],
    spot_price: Optional[float],
    *,
    delivery_warning_pct: float = 0.02,
) -> Optional[FuturesBasis]:
    """升贴水与交割日卖压信号（doc 27）。

    课程：basis = 期货价 − 现货价；大幅升水（contango）意味着交割日
    临近时期货向现货收敛，多头有平仓/卖压（"交割日魔咒"）。

    Args:
        futures_price: 期货价。
        spot_price:    现货价（或指数点位）。
        delivery_warning_pct: 触发交割日卖压预警的升水阈值，默认 2%。

    Returns:
        FuturesBasis；价格非法返回 None。
    """
    if futures_price is None or spot_price is None or spot_price <= 0:
        return None
    basis = futures_price - spot_price
    basis_pct = basis / spot_price
    contango = basis > 0
    return FuturesBasis(
        basis=basis,
        basis_pct=basis_pct,
        contango=contango,
        delivery_sell_pressure=basis_pct >= delivery_warning_pct,
    )


def days_to_delivery(
    delivery_date,
    as_of=None,
) -> Optional[int]:
    """距交割日天数（doc 27 交割日魔咒的辅助）。

    Args:
        delivery_date: 交割日（date 或 ISO 字符串）。
        as_of:         起算日，默认今天。

    Returns:
        剩余天数（>=0）；已过或非法返回 None。
    """
    try:
        from datetime import date as _date, datetime as _dt
        if isinstance(delivery_date, str):
            delivery_date = _date.fromisoformat(delivery_date[:10])
        if as_of is None:
            as_of = _date.today()
        if isinstance(as_of, str):
            as_of = _date.fromisoformat(as_of[:10])
        delta = (delivery_date - as_of).days
    except Exception:  # noqa: BLE001
        return None
    return delta if delta >= 0 else None


# ── 8.4 融资融券额度 / 成本 ─────────────────────────────────────────────────

@dataclass
class MarginFinancing:
    collateral: float          # 抵押物市值
    maintain_ratio: float      # 维持担保比例（如 1.3 = 130%）
    max_financing: float       # 可融额度 = 抵押物 / 维持担保比例
    annual_cost: float         # 年化融资成本（元）
    leverage: float            # (自有+融资)/自有


def margin_financing_capacity(
    own_capital: Optional[float],
    collateral: Optional[float] = None,
    *,
    maintain_ratio: float = 1.3,
    annual_rate: float = 0.07,
) -> Optional[MarginFinancing]:
    """融资融券额度与成本（doc 27）。

    课程：可融额 ≈ 抵押物 / 维持担保比例（约 130%）；总仓位 = 自有 + 融资；
    年化成本 6~8%。

    Args:
        own_capital:    自有资金（元）。
        collateral:     抵押物市值；默认等于自有资金。
        maintain_ratio: 维持担保比例，默认 1.3（即 80% 折算）。
        annual_rate:    年化融资利率，默认 7%。

    Returns:
        MarginFinancing；自有资金<=0 返回 None。
    """
    if own_capital is None or own_capital <= 0:
        return None
    coll = collateral if collateral is not None else own_capital
    max_fin = coll / maintain_ratio
    total = own_capital + max_fin
    return MarginFinancing(
        collateral=coll,
        maintain_ratio=maintain_ratio,
        max_financing=max_fin,
        annual_cost=max_fin * annual_rate,
        leverage=total / own_capital,
    )


# ── 8.5 β 对冲 ──────────────────────────────────────────────────────────────

@dataclass
class BetaHedge:
    portfolio_value: float
    portfolio_beta: float
    contract_value: float      # 单张股指期货合约价值
    hedge_contracts: float     # 需做空的合约数（取整前）
    hedge_contracts_rounded: int  # 向下取整


def beta_hedge_contracts(
    portfolio_value: Optional[float],
    portfolio_beta: Optional[float],
    contract_value: Optional[float],
) -> Optional[BetaHedge]:
    """等值 β 对冲手数（doc 27）。

    课程：用股指期货做空对冲组合 β，剥离 α。对冲名义价值 =
    组合市值 × β；做空合约数 = 对冲名义 / 单张合约价值。

    Args:
        portfolio_value: 组合市值（元）。
        portfolio_beta:  组合相对股指的 β。
        contract_value:  单张股指期货合约价值（元）。

    Returns:
        BetaHedge；输入非法返回 None。
    """
    if (portfolio_value is None or portfolio_beta is None
            or contract_value is None or contract_value <= 0):
        return None
    hedge_notional = portfolio_value * portfolio_beta
    contracts = hedge_notional / contract_value
    return BetaHedge(
        portfolio_value=portfolio_value,
        portfolio_beta=portfolio_beta,
        contract_value=contract_value,
        hedge_contracts=contracts,
        hedge_contracts_rounded=int(contracts),
    )
