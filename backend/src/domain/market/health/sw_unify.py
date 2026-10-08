"""sw 估值双源统一（数据治理 1.2）：诊断与日度化 computed。

诊断：akshare 日度 vs computed 最近一期（|Δt|≤10 日）的相对偏差，
中位 ≤5% 才允许读侧统一 computed，否则先披露口径差异。
"""
import datetime as dt
import statistics
from typing import Optional


def nearest_neighbor_deviation(
    akshare_rows: list, computed_rows: list, metric: str = "pe_ttm",
    max_gap_days: int = 10,
) -> dict:
    """rows: [(sw_code, date_iso, value)]; 返回逐行业与总体中位偏差%。

    每个 akshare 点取 |Δt|≤max_gap_days 内最近的 computed 点；
    偏差 = |akshare−computed|/computed×100。
    """
    comp_by: dict = {}
    for code, d, v in computed_rows:
        if v is None:
            continue
        comp_by.setdefault(code, []).append((dt.date.fromisoformat(d), v))
    for code in comp_by:
        comp_by[code].sort()

    def _nearest(code: str, d: dt.date):
        best = None
        for cd, cv in comp_by.get(code, []):
            gap = abs((cd - d).days)
            if gap <= max_gap_days and (best is None
                                        or gap < best[0]):
                best = (gap, cv)
        return best[1] if best else None

    devs: list = []
    by_industry: dict = {}
    for code, d, v in akshare_rows:
        if v is None:
            continue
        dd = dt.date.fromisoformat(d)
        cv = _nearest(code, dd)
        if cv is None or cv == 0:
            continue
        dev = abs(v - cv) / abs(cv) * 100
        devs.append(dev)
        slot = by_industry.setdefault(code, {"devs": [], "dev_pct": None})
        slot["devs"].append(dev)
    for slot in by_industry.values():
        slot["dev_pct"] = round(statistics.median(slot["devs"]), 2)
        del slot["devs"]
    return {
        "metric": metric,
        "pairs": len(devs),
        "median_dev_pct": round(statistics.median(devs), 2)
        if devs else None,
        "by_industry": by_industry,
        "unify_ok": bool(devs) and statistics.median(devs) <= 5,
    }


def compute_sw_valuation_daily(
    members: list, valuations: list, trade_date: dt.date,
) -> list:
    """整体法（调和加权）日度 computed：复用 index_valuation_backfill 口径。

    members: [{sw_code, symbol}]; valuations: [{symbol, trade_date,
    pe_ttm, pb, total_mv}]（取 as-of 最近值）。
    返回 [{sw_code, pe_ttm, pb, sample_count}]。
    """
    val_by_sym: dict = {}
    for v in valuations:
        val_by_sym.setdefault(v["symbol"], []).append(v)
    by_ind: dict = {}
    for m in members:
        code, sym = m["sw_code"], m["symbol"]
        rows = val_by_sym.get(sym) or []
        asof = [r for r in rows
                if r.get("trade_date") and r["trade_date"] <= trade_date]
        if not asof:
            continue
        r = max(asof, key=lambda x: x["trade_date"])
        if not r.get("total_mv") or r["total_mv"] <= 0:
            continue
        g = by_ind.setdefault(code, {
            "mv": 0.0, "pe_h": 0.0, "pb_h": 0.0, "n": 0,
            "pe_n": 0, "pb_n": 0,
        })
        g["mv"] += r["total_mv"]
        g["n"] += 1
        if r.get("pe_ttm") and r["pe_ttm"] > 0:
            g["pe_h"] += r["total_mv"] / r["pe_ttm"]
            g["pe_n"] += 1
        if r.get("pb") and r["pb"] > 0:
            g["pb_h"] += r["total_mv"] / r["pb"]
            g["pb_n"] += 1
    out = []
    for code, g in by_ind.items():
        out.append({
            "sw_code": code,
            "pe_ttm": round(g["mv"] / g["pe_h"], 4)
            if g["pe_h"] > 0 else None,
            "pb": round(g["mv"] / g["pb_h"], 4)
            if g["pb_h"] > 0 else None,
            "sample_count": g["n"],
        })
    return out


def merge_sw_series(computed: list, akshare: list) -> list:
    """拼接口径：computed 优先，akshare 仅补 computed 缺失的日期。

    输入行需含 trade_date（date 或 iso）；返回按日期升序的合并列表
    （元素为 computed 优先的同结构 dict/对象，日期重叠取 computed）。
    """
    def _d(r):
        v = r["trade_date"] if isinstance(r, dict) else r.trade_date
        return v if not isinstance(v, str) else dt.date.fromisoformat(v)

    comp_by_date = {_d(r): r for r in computed}
    out = dict(comp_by_date)
    for r in akshare:
        k = _d(r)
        if k not in out:
            out[k] = r
    return [out[k] for k in sorted(out)]
