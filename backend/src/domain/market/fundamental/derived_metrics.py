"""
价值投资衍生指标（纯函数）
=========================
基于 stock_financial_detail（三大报表合并单期）+ stock_valuation 计算
价值投资核心衍生指标，替换"ROE 近似 ROIC、1/PE 近似收益率"的粗糙做法。

口径说明（务实近似，已在各函数注释标明假设）：
  - EBIT ≈ operating_profit（营业利润，息税前近似；含投资收益，不含营业外）
  - 有息负债 = short_loan（短期借款）+ long_loan（长期借款）
  - 投入资本 invested_capital = equity（股东权益）+ 有息负债
    （Greenblatt 口径；未扣超额现金，简化）
  - ROIC(%) = EBIT / 投入资本 × 100（用当期投入资本近似；理想用上期期初）
  - EV（企业价值）= total_mv + 有息负债 - monetary_funds
  - earnings_yield(%) = EBIT / EV × 100（Greenblatt 收益率，便宜程度）
  - fcf_yield(%) = free_cash_flow / EV × 100
  - ROA(%) = net_profit / total_assets × 100
"""
from __future__ import annotations

from typing import Optional


def _add(a, b) -> Optional[float]:
    """两者都为数值时相加；一数值一 None 返回该数值；均非数值返回 None。"""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a + b
    if isinstance(a, (int, float)):
        return a
    if isinstance(b, (int, float)):
        return b
    return None


def interest_bearing_debt(fin: dict) -> Optional[float]:
    """有息负债 = 短期借款 + 长期借款。"""
    return _add(fin.get("short_loan"), fin.get("long_loan"))


def invested_capital(fin: dict) -> Optional[float]:
    """投入资本 = 股东权益 + 有息负债（Greenblatt 口径，未扣超额现金）。"""
    return _add(fin.get("equity"), interest_bearing_debt(fin))


def ev(fin: dict, val: dict) -> Optional[float]:
    """企业价值 = 市值 + 有息负债 - 货币资金。"""
    mv = val.get("total_mv")
    debt = interest_bearing_debt(fin)
    cash = fin.get("monetary_funds")
    base = mv
    if debt is not None:
        base = (base or 0) + debt
    if cash is not None and base is not None:
        base = base - cash
    return base


def roic(fin: dict) -> Optional[float]:
    """ROIC(%) = EBIT / 投入资本 × 100。投入资本<=0 返回 None。"""
    ebit = fin.get("operating_profit")
    ic = invested_capital(fin)
    if (
        isinstance(ebit, (int, float))
        and isinstance(ic, (int, float))
        and ic > 0
    ):
        return round(ebit / ic * 100, 4)
    return None


def earnings_yield(fin: dict, val: dict) -> Optional[float]:
    """EBIT 收益率(%) = EBIT / EV × 100（Greenblatt 收益率）。"""
    ebit = fin.get("operating_profit")
    e = ev(fin, val)
    if (
        isinstance(ebit, (int, float))
        and isinstance(e, (int, float))
        and e > 0
    ):
        return round(ebit / e * 100, 4)
    return None


def fcf_yield(fin: dict, val: dict) -> Optional[float]:
    """FCF 收益率(%) = 自由现金流 / EV × 100。"""
    fcf = fin.get("free_cash_flow")
    e = ev(fin, val)
    if (
        isinstance(fcf, (int, float))
        and isinstance(e, (int, float))
        and e > 0
    ):
        return round(fcf / e * 100, 4)
    return None


def roa(fin: dict) -> Optional[float]:
    """ROA(%) = 净利润 / 总资产 × 100。"""
    net = fin.get("net_profit")
    assets = fin.get("total_assets")
    if (
        isinstance(net, (int, float))
        and isinstance(assets, (int, float))
        and assets > 0
    ):
        return round(net / assets * 100, 4)
    return None


def compute_value_metrics(fin: dict, val: dict) -> dict:
    """一次性算全部价值投资衍生指标（输入缺失则对应字段为 None）。"""
    return {
        "ebit": fin.get("operating_profit"),
        "invested_capital": invested_capital(fin),
        "roic": roic(fin),
        "ev": ev(fin, val),
        "earnings_yield": earnings_yield(fin, val),
        "fcf_yield": fcf_yield(fin, val),
        "roa": roa(fin),
    }
