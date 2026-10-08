# backend/src/domain/market/industry_analysis/prosperity.py
"""行业景气分(纯函数):盈利/估值/动量/资金四分项截面分位加权(规格§4 F2)。

估值分位窗口固定取 config(默认8年)——评分口径恒定;热力图展示列的
5/8/10年切换只影响展示,不影响本模块(窗口由 inputs 装配方决定)。
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Optional

from src.domain.market.industry_analysis.stats import percentile_rank

DEFAULT_WEIGHTS = {"profit": 0.35, "valuation": 0.25,
                   "momentum": 0.25, "flow": 0.15}


@dataclass
class IndustryInputs:
    sw_code: str
    name: str = ""
    revenue_yoy: Optional[float] = None      # %,cross_section 最新报告期
    net_profit_yoy: Optional[float] = None   # %,net_profit_sum 跨期自算
    pb: Optional[float] = None
    pb_pct: Optional[float] = None           # 历史分位 0-100
    pe_ttm: Optional[float] = None
    pe_pct: Optional[float] = None           # 历史分位 0-100
    rs60: Optional[float] = None             # 60日收益 − 沪深300同窗收益
    flow20: Optional[float] = None           # 映射后20日主力净流入合计(元)


@dataclass
class ProsperityScore:
    sw_code: str
    score: Optional[float]
    score_profit: Optional[float]
    score_valuation: Optional[float]
    score_momentum: Optional[float]
    score_flow: Optional[float]
    inputs: dict = field(default_factory=dict)


def net_profit_yoy(cur: Optional[float],
                   prev: Optional[float]) -> Optional[float]:
    """净利同比%:缺失或 prev==0 → None(宁缺毋滥)。

    (行为按参考实现:仅 prev==0 或任一缺失返回 None;负 prev 参与计算,
    分母取 |prev|——扭亏为盈记正,方向随变化不翻转。)
    """
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100.0


def _snapshot(x: IndustryInputs) -> dict:
    return {f.name: getattr(x, f.name) for f in fields(x)
            if f.name not in ("sw_code", "name")}


def _raw_components(x: IndustryInputs) -> dict[str, Optional[float]]:
    """四分项的原始值(估值=分位取反;盈利=两同比均值)。"""
    profit_vals = [v for v in (x.revenue_yoy, x.net_profit_yoy)
                   if v is not None]
    profit = sum(profit_vals) / len(profit_vals) if profit_vals else None
    val_vals = [100.0 - p for p in (x.pb_pct, x.pe_pct) if p is not None]
    valuation = sum(val_vals) / len(val_vals) if val_vals else None
    return {"profit": profit, "valuation": valuation,
            "momentum": x.rs60, "flow": x.flow20}


def compute_prosperity(inputs: dict[str, IndustryInputs],
                       weights: Optional[dict] = None) -> dict[str, ProsperityScore]:
    w = dict(weights or DEFAULT_WEIGHTS)
    raw = {code: _raw_components(x) for code, x in inputs.items()}
    cross = {k: [raw[c][k] for c in raw if raw[c][k] is not None]
             for k in w}
    out: dict[str, ProsperityScore] = {}
    for code, x in inputs.items():
        subs: dict[str, Optional[float]] = {}
        for k, weight in w.items():
            v = raw[code][k]
            subs[k] = percentile_rank(v, cross[k]) if v is not None else None
        avail = [(w[k], s) for k, s in subs.items() if s is not None]
        total_w = sum(wi for wi, _ in avail)
        score = (sum(wi * s for wi, s in avail) / total_w
                 if total_w > 0 else None)
        out[code] = ProsperityScore(
            sw_code=code, score=score,
            score_profit=subs["profit"], score_valuation=subs["valuation"],
            score_momentum=subs["momentum"], score_flow=subs["flow"],
            inputs=_snapshot(x) if score is not None else {},
        )
    return out
