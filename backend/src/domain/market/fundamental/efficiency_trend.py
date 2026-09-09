"""股票投资课程——经营效率趋势（docs 08/13/19）纯函数。

簇 1 的杜邦分解把 ROE 拆成"净利率 × 总资产周转率 × 权益乘数"，但只看了单期。
本模块从**时序趋势**视角量化经营效率——课程 doc 19 强调：好公司的周转率
应随规模稳定甚至提升（轻资产化/管理改善），而周转率持续下滑是竞争力
衰退的早期信号。

    turnover_ratio           通用周转率 = 流量 / 平均存量
    receivable/inventory/asset_turnover   三大周转率（封装）
    compute_turnovers        单期三大周转率（从相邻两期快照算平均存量）
    turnover_trend           多期周转率趋势（改善/恶化）

输入为财报快照 dict（含 revenue/operating_cost/accounts_receivable/inventory/
total_assets）。全部纯函数。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def turnover_ratio(flow: Optional[float], avg_stock: Optional[float]) -> Optional[float]:
    """通用周转率 = 流量 / 平均存量。

    Args:
        flow:      期间流量（营收/营业成本）。
        avg_stock: 平均存量（(期初+期末)/2）。

    Returns:
        周转率；流量/存量非法返回 None。
    """
    if flow is None or avg_stock is None or avg_stock <= 0:
        return None
    return flow / avg_stock


def receivable_turnover(
    revenue: Optional[float], ar_begin: Optional[float], ar_end: Optional[float]
) -> Optional[float]:
    """应收账款周转率 = 营收 / 平均应收（次/年）。越高 = 收现越快。"""
    if ar_begin is None or ar_end is None:
        return None
    return turnover_ratio(revenue, (ar_begin + ar_end) / 2.0)


def inventory_turnover(
    operating_cost: Optional[float], inv_begin: Optional[float], inv_end: Optional[float]
) -> Optional[float]:
    """存货周转率 = 营业成本 / 平均存货（次/年）。越高 = 周转越快、不积压。"""
    if inv_begin is None or inv_end is None:
        return None
    return turnover_ratio(operating_cost, (inv_begin + inv_end) / 2.0)


def asset_turnover(
    revenue: Optional[float], assets_begin: Optional[float], assets_end: Optional[float]
) -> Optional[float]:
    """总资产周转率 = 营收 / 平均总资产（次/年）。越高 = 资产越轻/效率越高。"""
    if assets_begin is None or assets_end is None:
        return None
    return turnover_ratio(revenue, (assets_begin + assets_end) / 2.0)


def compute_turnovers(curr: dict, prev: dict) -> dict:
    """从相邻两期快照算单期三大周转率。

    Args:
        curr: 本期快照（提供流量 + 期末存量）。
        prev: 上期快照（提供期初存量）。

    Returns:
        {receivable, inventory, asset}（缺失项为 None）。
    """
    return {
        "receivable": receivable_turnover(
            curr.get("revenue"),
            prev.get("accounts_receivable"), curr.get("accounts_receivable"),
        ),
        "inventory": inventory_turnover(
            curr.get("operating_cost"),
            prev.get("inventory"), curr.get("inventory"),
        ),
        "asset": asset_turnover(
            curr.get("revenue"),
            prev.get("total_assets"), curr.get("total_assets"),
        ),
    }


# ── 多期趋势 ────────────────────────────────────────────────────────────────

@dataclass
class RatioTrend:
    name: str
    values: list[float]
    slope: Optional[float]     # 每期变动
    improving: Optional[bool]  # 周转率上升 = 改善
    latest: Optional[float]


@dataclass
class EfficiencyTrend:
    receivable: Optional[RatioTrend]
    inventory: Optional[RatioTrend]
    asset: Optional[RatioTrend]
    overall: str               # improving / stable / deteriorating


def _ratio_trend(name: str, values: list[float]) -> Optional[RatioTrend]:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return None
    n = len(vals)
    if n < 2:
        return RatioTrend(name, vals, None, None, vals[-1])
    xs = list(range(n))
    xm = sum(xs) / n
    ym = sum(vals) / n
    num = sum((x - xm) * (y - ym) for x, y in zip(xs, vals))
    den = sum((x - xm) ** 2 for x in xs)
    slope = num / den if den else 0.0
    return RatioTrend(name, vals, slope, slope > 0, vals[-1])


def turnover_trend(periods: list[dict]) -> EfficiencyTrend:
    """多期周转率趋势（doc 19）。

    Args:
        periods: 升序财报快照列表（至少 2 期，建议 4+）。
                 每相邻两期算一组周转率，串联成趋势。

    Returns:
        EfficiencyTrend（三大周转率趋势 + overall 改善/稳定/恶化）。
    """
    rec_vals: list[float] = []
    inv_vals: list[float] = []
    ast_vals: list[float] = []
    for i in range(1, len(periods)):
        t = compute_turnovers(periods[i], periods[i - 1])
        if t["receivable"] is not None:
            rec_vals.append(t["receivable"])
        if t["inventory"] is not None:
            inv_vals.append(t["inventory"])
        if t["asset"] is not None:
            ast_vals.append(t["asset"])

    rec = _ratio_trend("receivable", rec_vals)
    inv = _ratio_trend("inventory", inv_vals)
    ast = _ratio_trend("asset", ast_vals)

    # overall：统计改善/恶化的项数
    votes = [r.improving for r in (rec, inv, ast) if r and r.improving is not None]
    if not votes:
        overall = "stable"
    elif sum(votes) >= 2:
        overall = "improving"
    elif sum(votes) == 0:
        overall = "deteriorating"
    else:
        overall = "stable"
    return EfficiencyTrend(receivable=rec, inventory=inv, asset=ast, overall=overall)
