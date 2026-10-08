"""全市场温度计（价值投资闭环第 7 期）。

股债性价比（ERP = 沪深300 E/P − 10Y 国债）为主锚、巴菲特指标为参考，
映射五档温度与整体仓位水位。经验阈值注释：A股 2014/2018/2024 大底
ERP ≈ 5.5%+，2015/2021 泡沫 < 2.5%。纯函数，输入缺失对应项置 None。
"""
from typing import Optional

_LEVELS = [
    # (erp下限, level, 中文, 水位区间%)
    (5.5, "deep_cold", "极冷（历史大底区）", 80, 90),
    (4.5, "cold", "偏冷", 70, 80),
    (3.5, "neutral", "中性", 50, 60),
    (2.5, "warm", "偏热", 30, 40),
    (None, "hot", "过热（泡沫区）", 20, 30),
]

_BUFFETT_BANDS = [
    (110.0, "bubble", "泡沫"),
    (90.0, "elevated", "偏高"),
    (70.0, "fair", "合理"),
    (None, "undervalued", "低估"),
]


def market_thermometer(
    pe_ttm: Optional[float],
    bond_yield_pct: Optional[float],
    total_mv_sum: Optional[float] = None,
    gdp: Optional[float] = None,
    erp_history: Optional[list] = None,
    erp_history_approx: bool = False,
) -> dict:
    """市场温度：ERP 五档 + 历史分位 + 巴菲特指标参考 + 仓位水位。"""
    ep_pct = (100.0 / pe_ttm) if pe_ttm and pe_ttm > 0 else None
    erp_pct = (
        ep_pct - bond_yield_pct
        if ep_pct is not None and bond_yield_pct is not None else None
    )

    level, label, band = "unknown", "数据不足", None
    if erp_pct is not None:
        erp_banded = round(erp_pct, 4)   # 边界浮点误差先取整
        for floor, lv, lb, lo, hi in _LEVELS:
            if floor is None or erp_banded >= floor:
                level, label = lv, lb
                band = {"low": lo, "high": hi}
                break

    percentile = None
    if erp_pct is not None and erp_history:
        below = sum(1 for h in erp_history if h <= erp_pct)
        percentile = round(below / len(erp_history) * 100.0, 1)

    buffett_pct = (
        total_mv_sum / gdp * 100.0
        if total_mv_sum and gdp else None
    )
    buffett_level, buffett_label = None, None
    if buffett_pct is not None:
        for floor, lv, lb in _BUFFETT_BANDS:
            if floor is None or buffett_pct >= floor:
                buffett_level, buffett_label = lv, lb
                break

    return {
        "ep_pct": round(ep_pct, 2) if ep_pct is not None else None,
        "erp_pct": round(erp_pct, 2) if erp_pct is not None else None,
        "level": level,
        "level_label": label,
        "position_band": band,
        "erp_percentile": percentile,
        "history_sample_count": len(erp_history or []),
        "erp_history_approx": erp_history_approx,
        "buffett_pct": round(buffett_pct, 1)
        if buffett_pct is not None else None,
        "buffett_level": buffett_level,
        "buffett_label": buffett_label,
        "note": "ERP=沪深300 E/P−10Y国债（%）；历史分位用"
                "历史E/P−当前国债近似（PE周期主导）。"
                "水位为整体仓位参考，非指令。",
    }


def erp_to_level(erp_pct):
    """ERP → (level, label, {low, high})，供回填复用。"""
    if erp_pct is None:
        return "unknown", "数据不足", None
    erp_banded = round(erp_pct, 4)
    for floor, lv, lb, lo, hi in _LEVELS:
        if floor is None or erp_banded >= floor:
            return lv, lb, {"low": lo, "high": hi}
    return "unknown", "数据不足", None


def build_erp_series(pe_series, bond_series, current_bond):
    """[(date_iso, erp)] 逐日对齐版（含日期），近似时 approx=True。"""
    import bisect

    if not pe_series:
        return [], False
    bonds = sorted(
        (b for b in bond_series if b[0] and b[1] is not None),
        key=lambda b: b[0],
    )
    if not bonds and current_bond is None:
        return [], False
    dates = [b[0] for b in bonds]
    out = []
    for d, pe in pe_series:
        if not pe or pe <= 0:
            continue
        if bonds:
            i = bisect.bisect_right(dates, d) - 1
            if i < 0:
                continue
            bond = bonds[i][1]
        else:
            bond = current_bond
        out.append((d, 100.0 / pe - bond))
    return out, not bonds


def build_erp_history(pe_series, bond_series, current_bond):
    """[(date_iso, pe)] × [(date_iso, yield%)] → (erp_list, approx)。

    逐点取该日或之前最近的债券值（carry-forward）；早于债券历史首日
    的点跳过；债券历史为空时退化为 current_bond 平移近似（approx=True）。
    """
    series, approx = build_erp_series(
        pe_series, bond_series, current_bond
    )
    return [v for _, v in series], approx


_LEVEL_WEIGHT = {   # 档位 → 目标权益仓位(带内中值)
    "deep_cold": 0.85, "cold": 0.75, "neutral": 0.55,
    "warm": 0.35, "hot": 0.25,
}


def allocation_backtest(thermo_rows: list, index_rows: list,
                         rebalance_days: int = 21,
                         cash_annual: float = 0.02) -> dict:
    """温度计水位策略回测（三期G3）——检验"建议水位"本身。

    exposure 模型：每期组合 = 上期 × (w×指数收益 + (1−w)×现金收益)；
    每 rebalance_days 个交易日按当日档位调 w（档位带内中值）；
    缺温度日沿用上一档。对比买入持有（CAGR/最大回撤）。
    """
    def _stats(curve):
        if not curve or curve[0] <= 0:
            return {"cagr_pct": None, "max_drawdown_pct": None}
        years = max(len(curve) / 244, 1 / 244)
        cagr = (curve[-1] / curve[0]) ** (1 / years) - 1
        pk, dd = curve[0], 0.0
        for v in curve:
            pk = max(pk, v)
            dd = max(dd, (pk - v) / pk * 100)
        return {"cagr_pct": round(cagr * 100, 2),
                "max_drawdown_pct": round(dd, 2)}

    if not thermo_rows or not index_rows:
        return {"start": None, "end": None,
                "rebalance_days": rebalance_days,
                "strategy": {"cagr_pct": None,
                             "max_drawdown_pct": None,
                             "rebalances": 0},
                "buy_hold": {"cagr_pct": None,
                             "max_drawdown_pct": None},
                "note": "数据不足。"}

    level_by_date = {r["trade_date"]: r.get("level")
                     for r in thermo_rows}
    dates = [r["trade_date"] for r in index_rows]
    closes = [float(r["close"]) for r in index_rows]
    daily_cash = (1 + cash_annual) ** (1 / 244) - 1

    strat_curve = [1.0]
    weight = 1.0
    rebalances = 0
    last_rebal_i = -10**9
    last_level = None
    for i in range(1, len(dates)):
        lvl = level_by_date.get(dates[i - 1]) or last_level
        if lvl:
            last_level = lvl
        if (last_level in _LEVEL_WEIGHT
                and (i - 1) - last_rebal_i >= rebalance_days):
            weight = _LEVEL_WEIGHT[last_level]
            rebalances += 1
            last_rebal_i = i - 1
        ret = closes[i] / closes[i - 1] - 1
        total = strat_curve[-1] * (
            weight * (1 + ret) + (1 - weight) * (1 + daily_cash)
        )
        strat_curve.append(total)

    bh_curve = [c / closes[0] for c in closes]
    return {
        "start": dates[0], "end": dates[-1],
        "rebalance_days": rebalance_days,
        "strategy": {**_stats(strat_curve), "rebalances": rebalances},
        "buy_hold": _stats(bh_curve),
        "note": "exposure 模型: 组合=上期×(w×指数+(1−w)×现金2%); "
                "w=档位带内中值(极冷85/偏冷75/中性55/偏热35/过热25)。",
    }
