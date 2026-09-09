"""
类比估值法（可比公司 Comparable Multiples，纯函数）
====================================================
《股票投资课程》15 集：相对估值法之一——「跟同类型公司比」。
核心思想：相似的资产应该具有相似的价格。取同行业可比公司的关键
乘数（PE/PB/PS/股息率）做截面统计（中位数/均值/四分位），把目标
公司当前乘数放进同行分布中定位，并用同行中位乘数反推隐含市值：

    implied_value = own_total_mv × peer_median / own_multiple
    upside        = peer_median / own_multiple − 1

剔除口径：PE/PB/PS 只用 > 0 的样本（亏损/资不抵债/负增长无估值
意义）；股息率缺失不参与。统计用标准库 statistics。

课程局限提醒：类比法只能判断相对高低，若参考同行整体高估/低估
则结论失效，须与绝对估值（DCF/DDM/净资产）交叉验证。

dict 进 dict 出，不读 DB、不发 HTTP、不抛异常（fundamental 惯例）。
"""
from __future__ import annotations

import statistics
from typing import Optional

#: 参与截面统计的乘数（stock_valuation 固定列名）
MULTIPLES = ("pe_ttm", "pb", "ps_ttm", "dv_ttm")

#: 股息率允许 = 0（不分红），其余乘数必须 > 0
_POSITIVE_ONLY = {"pe_ttm", "pb", "ps_ttm"}

_MIN_PEERS = 4  # 截面统计下限，防微小样本噪声


def _r4(v) -> Optional[float]:
    return round(v, 4) if v is not None else None


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def multiple_stats(values: list) -> Optional[dict]:
    """单乘数截面统计（调用方先剔 None，此处再防御）。

    Returns:
        {count, median, mean, p25, p75}；样本 < 2 → None。
        （quantiles 需 n>=2；p25/p75 需 n>=4，不足时为 None）
    """
    xs = sorted(v for v in (_num(x) for x in values) if v is not None)
    if len(xs) < 2:
        return None
    d = {
        "count": len(xs),
        "median": _r4(statistics.median(xs)),
        "mean": _r4(statistics.mean(xs)),
    }
    if len(xs) >= 4:
        q = statistics.quantiles(xs, n=4, method="inclusive")
        d["p25"], d["p75"] = _r4(q[0]), _r4(q[2])
    else:
        d["p25"] = d["p75"] = None
    return d


def comps_valuation(
    peers: list,
    target_symbol: str,
    min_peers: int = _MIN_PEERS,
) -> dict:
    """同行业可比公司截面估值。

    Args:
        peers: 同行 + 目标股的估值行，每行
            {symbol, name?, pe_ttm, pb, ps_ttm, dv_ttm, total_mv?}
            （乘数/市值可为 None）
        target_symbol: 目标股 symbol（须在 peers 内）。

    Returns:
        {target_found, sample_count, multiples: {m: {...} | None}}
        multiples[m] = {count, median, mean, p25, p75,
                        own, own_valid, rank_pct, implied_value, upside}
        own 无效（缺失/≤0）时 implied_value/upside/rank_pct 为 None。
    """
    target = next(
        (p for p in peers if p.get("symbol") == target_symbol), None
    )
    others = [p for p in peers if p.get("symbol") != target_symbol]
    out: dict = {
        "target_found": target is not None,
        "sample_count": len(others),
        "multiples": {},
    }
    if target is None:
        return out

    own_mv = _num(target.get("total_mv"))

    for m in MULTIPLES:
        raw = [p.get(m) for p in others]
        vals = []
        for v in raw:
            x = _num(v)
            if x is None:
                continue
            if m in _POSITIVE_ONLY and x <= 0:
                continue
            if m == "dv_ttm" and x < 0:
                continue
            vals.append(x)
        stats = multiple_stats(vals) if len(others) >= min_peers else None

        own = _num(target.get(m))
        own_valid = own is not None and (
            own > 0 if m in _POSITIVE_ONLY else own >= 0
        )

        entry: dict = {
            "count": stats["count"] if stats else len(vals),
            "median": stats["median"] if stats else None,
            "mean": stats["mean"] if stats else None,
            "p25": stats["p25"] if stats else None,
            "p75": stats["p75"] if stats else None,
            "own": _r4(own) if own_valid else None,
            "own_valid": own_valid,
            "implied_value": None,
            "upside": None,
            "rank_pct": None,
        }

        if stats and own and own > 0 and stats["median"]:
            implied = own_mv * stats["median"] / own if own_mv else None
            entry["implied_value"] = _r4(implied) if implied else None
            entry["upside"] = _r4(stats["median"] / own - 1)

        if own_valid and vals:
            rank_pct = sum(1 for v in vals if v <= own) / len(vals)
            entry["rank_pct"] = _r4(rank_pct)

        out["multiples"][m] = entry

    return out
