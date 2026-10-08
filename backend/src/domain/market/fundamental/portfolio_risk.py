"""组合层风险管理纯函数（价值投资二期 F1）。

集中度/相关性/加权估值——输入由 handler 注入（持仓×行情×行业）。
权重口径：个股市值 / 持仓总市值（不含现金，输出中注明）。
"""
import math
from typing import Optional


def industry_concentration(positions: list) -> dict:
    """按行业分组权重；单行业>40% → flag。"""
    total = sum(p.get("value") or 0 for p in positions)
    if total <= 0:
        return {"groups": [], "flags": ["持仓市值为 0"]}
    acc: dict = {}
    for p in positions:
        ind = p.get("industry") or "未知"
        g = acc.setdefault(ind, {"industry": ind, "value": 0.0,
                                 "count": 0})
        g["value"] += p.get("value") or 0
        g["count"] += 1
    groups = sorted(acc.values(), key=lambda g: -g["value"])
    for g in groups:
        g["weight_pct"] = round(g["value"] / total * 100, 1)
    flags = [
        f"行业集中度偏高：{g['industry']} {g['weight_pct']}%（>40%）"
        for g in groups if g["weight_pct"] > 40
    ]
    if len(groups) == 1:
        flags.append("单一行业持仓：无分散")
    return {"groups": groups, "flags": flags}


def _pearson(xs, ys) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    xs, ys = xs[:n], ys[:n]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy)


def correlation_matrix(returns: dict, weights: dict) -> dict:
    """日收益 pearson 两两矩阵 + 有效独立仓位数。

    N_eff = (Σw)² / Σᵢⱼ wᵢwⱼρᵢⱼ（ρᵢᵢ=1）；缺序列的对不参与。
    """
    syms = sorted(returns)
    matrix: dict = {}
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            rho = _pearson(returns[a], returns[b])
            if rho is not None:
                matrix[(a, b)] = round(rho, 4)

    def _rho(a, b):
        if a == b:
            return 1.0
        return matrix.get((a, b), matrix.get((b, a), 0.0))

    eff = None
    wsum = sum(weights.get(s, 0) for s in syms)
    if wsum > 0 and len(syms) >= 2:
        var = sum(
            weights.get(a, 0) * weights.get(b, 0) * _rho(a, b)
            for a in syms for b in syms
        )
        if var > 0:
            eff = round(wsum * wsum / var, 2)
    return {
        "symbols": syms, "matrix": matrix,
        "effective_positions": eff,
    }


def portfolio_valuation(positions: list) -> dict:
    """市值加权 PE/PB（缺指标的持仓按市值剔除口径，输出计入口径）。"""
    out = {}
    for key in ("pe_ttm", "pb"):
        num = den = 0.0
        for p in positions:
            v, m = p.get("value") or 0, p.get(key)
            if v > 0 and m and m > 0:
                num += v
                den += v * m
        out[key] = round(den / num, 2) if num > 0 else None
    return out


def fair_value_range(upside_dict: dict) -> dict:
    """五法 upside → 公允/现价比区间（二期 F3b）。

    ratio=1+upside；取中位数为锚、min/max 为区间；现价恒为 1.0：
    <low 低估 / 区间内 合理 / >high 高估。缺 ≥3 法 → 数据不足。
    """
    ratios = sorted(
        1.0 + v for v in upside_dict.values()
        if v is not None and v > -1
    )
    if len(ratios) < 3:
        return {"median_ratio": None, "low_ratio": None,
                "high_ratio": None, "verdict": "unknown",
                "methods_used": len(ratios)}
    n = len(ratios)
    median = (ratios[n // 2] if n % 2
              else (ratios[n // 2 - 1] + ratios[n // 2]) / 2)
    low, high = ratios[0], ratios[-1]
    if 1.0 < low:
        verdict = "undervalued"
    elif 1.0 > high:
        verdict = "overvalued"
    else:
        verdict = "fair"
    return {
        "median_ratio": round(median, 3),
        "low_ratio": round(low, 3),
        "high_ratio": round(high, 3),
        "verdict": verdict,
        "methods_used": n,
        "note": "ratio=公允/现价；现价恒为1.0。区间为可得方法的"
                "min~max，中位数为锚。",
    }


def stress_test(positions: list, scenarios: list,
                history: dict) -> dict:
    """组合压力测试（三期G4）。

    positions: [{symbol, weight}]; scenarios: [{name, index_drop_pct}];
    history: {场景名: {symbol: 自身窗内% 或 None}}。缺自身历史 →
    指数跌幅×1.0（标注 imputed）。
    """
    out_scenes = []
    for sc in scenarios:
        name = sc["name"]
        hist = history.get(name) or {}
        port = 0.0
        worst, worst_v = None, 0.0
        imputed = []
        for p in positions:
            sym, w = p["symbol"], p.get("weight") or 0
            own = hist.get(sym)
            if own is None:
                own = sc.get("index_drop_pct") or 0.0
                imputed.append((sym, "指数×1.0"))
            port += w * own
            if own < worst_v:
                worst, worst_v = sym, own
        out_scenes.append({
            **sc,
            "portfolio_pct": round(port, 1),
            "worst_symbol": worst,
            "worst_pct": worst_v,
            "imputed": imputed,
        })
    return {"scenarios": out_scenes,
            "note": "各持仓用场景窗内自身跌幅(缺历史用指数×1.0并标注)；"
                    "组合跌幅=权重加权。"}
