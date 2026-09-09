"""行业截面统计（纯函数）。

下游背景：波特五力行业分析（课程 14 集）的数据基础——集中度
（CR4/CR8/HHI）刻画"行业内竞争强度/进入壁垒"，盈利分布（毛利率/
净利率/ROE 的 mean/median/std/p25/p75）刻画"议价能力与行业盈利性"。

口径约定（spec: 2026-08-18-sw-industry-cross-section-design.md）：
- revenue 为 None 的行不进本期截面（调用方先剔除，此处再防御）；
- CR4/CR8/HHI 只用 revenue > 0 的行（份额非负才有意义）；
- revenue_sum/net_profit_sum 用全部非 None 行（净利可为负）；
- sample_count < 4 → 集中度与分布全 None（统计下限防微小样本噪声）；
- 分布用标准库 statistics：median / stdev（样本标准差，n≥2）/
  quantiles(n=4, method="inclusive") 取 p25/p75；
- 派生值只在最终赋值处 round 4 位；绝对额不 round。

dict 进 dict 出，不读 DB、不发 HTTP、不抛异常（fundamental 模块惯例）。
"""
import statistics

#: 参与分布统计的指标（固定列/派生列名，单位均为 %）
DIST_METRICS = ("gross_margin", "net_margin", "roe")

_MIN_SAMPLE = 4  # 集中度/分布统计下限


def _r4(v):
    return round(v, 4) if v is not None else None


def _dist(vals):
    """单指标分布；全 None → None。"""
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None
    d = {"mean": _r4(statistics.mean(xs)), "median": _r4(statistics.median(xs))}
    if len(xs) >= 2:
        q = statistics.quantiles(xs, n=4, method="inclusive")
        d["std"] = _r4(statistics.stdev(xs))
        d["p25"], d["p75"] = _r4(q[0]), _r4(q[2])
    else:
        d["std"] = d["p25"] = d["p75"] = None
    return d


def cross_section_metrics(peers: list) -> dict:
    """单期行业截面。

    Args:
        peers: [{symbol, revenue, net_profit, gross_margin, net_margin, roe}]
            （revenue None 的行内部剔除；净利/毛利率等可为 None）

    Returns:
        {sample_count, revenue_sum, net_profit_sum, cr4, cr8, hhi,
         distribution: {metric: {mean, median, std, p25, p75} | None}}
    """
    rows = [p for p in peers if p.get("revenue") is not None]
    n = len(rows)

    np_vals = [p["net_profit"] for p in rows if p.get("net_profit") is not None]
    out = {
        "sample_count": n,
        "revenue_sum": sum(p["revenue"] for p in rows) if rows else None,
        "net_profit_sum": sum(np_vals) if np_vals else None,
        "cr4": None, "cr8": None, "hhi": None,
        "distribution": {m: None for m in DIST_METRICS},
    }
    if n == 0:
        return out

    if n >= _MIN_SAMPLE:
        rev_total = out["revenue_sum"]
        pos = [p["revenue"] for p in rows if p["revenue"] > 0]
        if pos and rev_total and rev_total > 0:
            shares = sorted((v / rev_total for v in pos), reverse=True)
            out["cr4"] = _r4(sum(shares[:4]))
            out["cr8"] = _r4(sum(shares[:8]))
            out["hhi"] = _r4(sum(s * s for s in shares) * 10000)
        out["distribution"] = {
            m: _dist([p.get(m) for p in rows]) for m in DIST_METRICS
        }
    return out


def _year_ago(report_date) -> str:
    """去年同期 ISO 日期串（兼容 str/date/datetime）。"""
    if isinstance(report_date, str):
        y, m, d = report_date[:4], report_date[5:7], report_date[8:10]
    else:
        y, m, d = (
            f"{report_date.year:04d}",
            f"{report_date.month:02d}",
            f"{report_date.day:02d}",
        )
    return f"{int(y) - 1}-{m}-{d}"


def attach_yoy(sections: list) -> list:
    """按行业时序补 revenue_yoy（去年同期营收和同比-1）。

    Args:
        sections: 同一行业按 report_date 升序的指标行，
            行含 report_date 与 revenue_sum（就地修改并返回）。
    """
    by_date = {}
    for s in sections:
        key = s["report_date"]
        key = key if isinstance(key, str) else key.isoformat()
        by_date[key] = s
    for s in sections:
        prev = by_date.get(_year_ago(s["report_date"]))
        cur, base = s.get("revenue_sum"), prev.get("revenue_sum") if prev else None
        if cur is None or base is None or base <= 0:
            s["revenue_yoy"] = None
        else:
            s["revenue_yoy"] = _r4(cur / base - 1)
    return sections


def peer_ranks(peers: list, target_symbol: str) -> dict:
    """最新期同行明细排名 + 目标股相对位置。

    Args:
        peers: [{symbol, name?, revenue, gross_margin, roe}]（最新期明细）
        target_symbol: 目标股 symbol（如 sh600519）

    Returns:
        {"peers": [行 + rank_revenue/rank_gross_margin],
         "target": {percentile_revenue, percentile_gross_margin,
                    percentile_roe, revenue_share} | None}
        分位 = 值<=该股的样本数（含自身）/ 该指标有效样本数；
        rank 降序并列同名次；指标 None 不参与该指标排名/分位。
    """
    out = [dict(p) for p in peers]
    for key, rank_key in (("revenue", "rank_revenue"),
                          ("gross_margin", "rank_gross_margin")):
        vals = sorted(
            (p[key] for p in out if p.get(key) is not None), reverse=True,
        )
        for p in out:
            v = p.get(key)
            p[rank_key] = vals.index(v) + 1 if v is not None else None

    tp = next((p for p in out if p.get("symbol") == target_symbol), None)
    target = None
    if tp is not None:
        target = {}
        rev_total = sum(
            p["revenue"] for p in out if p.get("revenue") is not None
        )
        for m in ("revenue", "gross_margin", "roe"):
            xs = [p[m] for p in out if p.get(m) is not None]
            v = tp.get(m)
            target[f"percentile_{m}"] = (
                _r4(sum(1 for x in xs if x <= v) / len(xs))
                if v is not None and xs else None
            )
        target["revenue_share"] = (
            _r4(tp["revenue"] / rev_total)
            if tp.get("revenue") is not None and rev_total and rev_total > 0
            else None
        )
    return {"peers": out, "target": target}
