"""回测收益归因分析（纯函数）。

对一次组合回测结果做收益分解：
  - 逐标的贡献：contribution(symbol) = 时间加权平均权重 × 区间收益
  - 行业聚合：按 symbol 前缀启发式分类汇总
  - 配置效应：策略相对等权基准的超额（来自权重配置）

基于 rebalance target_weights（分段常数近似），不重建逐日漂移持仓。
对季度再平衡是合理近似；UI/文档明确标注"基于调仓目标权重"。
"""
from __future__ import annotations

from typing import Any

from ...sync.sync_provider import OHLCVBar


def classify_sector(symbol: str) -> str:
    """symbol 前缀启发式行业分类（A/HK 股票）。

    与 portfolio_router.classify_sector 同逻辑，放 domain 层供归因复用。
    """
    s = symbol.lower()
    if s.startswith("sh688"):
        return "💻 科技创新"
    if s.startswith(("sh600", "sh601")):
        return "🏦 金融"
    if s.startswith("sh603"):
        return "🏭 制造"
    if s.startswith(("sz000", "sz001")):
        return "🏭 材料工业"
    if s.startswith("sz002"):
        return "💻 科技"
    if s.startswith("sz300"):
        return "💊 医药"
    if s.startswith("sh510") or s.startswith("sh511") or s.startswith("sh512"):
        return " ETF/指数"
    if s.startswith("sh518"):
        return "🥇 黄金"
    if s.startswith("sh000") or s.startswith("sz399") or s.startswith("sh899"):
        return "📊 指数"
    if s.startswith(("hk", "0")):
        return "🏦 港股金融"
    return "📊 其他"


def _period_return(bars: list[OHLCVBar]) -> float | None:
    """标的区间收益率（%，首末收盘价）。数据不足返回 None。"""
    closes = [b.close_ for b in bars if b.close_ and b.close_ > 0]
    if len(closes) < 2:
        return None
    first, last = closes[0], closes[-1]
    if first <= 0:
        return None
    return (last / first - 1.0) * 100.0


def _parse_rebalances(result: dict) -> list[dict[str, Any]]:
    """从结果字典提取 [{date, weights}]（按日期升序）。"""
    out = []
    for r in result.get("rebalances") or []:
        if not isinstance(r, dict):
            continue
        tw = r.get("target_weights") or {}
        if tw:
            out.append({"date": r.get("date", ""), "weights": tw})
    out.sort(key=lambda x: x["date"])
    return out


def _time_weighted_avg_weights(
    rebalances: list[dict[str, Any]],
) -> dict[str, float]:
    """各标的的时间加权平均权重。

    每个 rebalance 段的权重 = 该次 target_weights，持续到下一次 rebalance。
    时间加权：avg(sym) = Σ(w_i × 段长_i) / Σ(段长_i)。
    段长用日期字符串字典序差近似（同格式 YYYY-MM-DD 字典序=时间序）。
    """
    if not rebalances:
        return {}
    # 段长：用相邻日期的"距离"。无显式日期时退化为等权计数。
    durations: list[float] = []
    for i in range(len(rebalances)):
        if i + 1 < len(rebalances):
            d_cur = rebalances[i]["date"]
            d_next = rebalances[i + 1]["date"]
            # 字典序差作为粗略时长（同格式可比）；最小 1
            dur = max(1.0, float(_date_ordinal_diff(d_cur, d_next)))
        else:
            # 末段：用前一段时长，无则 1
            dur = durations[-1] if durations else 1.0
        durations.append(dur)

    total_dur = sum(durations) or 1.0
    symbols = set()
    for r in rebalances:
        symbols.update(r["weights"].keys())

    avg: dict[str, float] = {}
    for sym in symbols:
        weighted = sum(
            r["weights"].get(sym, 0.0) * durations[i]
            for i, r in enumerate(rebalances)
        )
        avg[sym] = weighted / total_dur
    return avg


def _date_ordinal_diff(d1: str, d2: str) -> int:
    """两个 YYYY-MM-DD 字符串的天数差（正）。解析失败返回 0。"""
    try:
        from datetime import date as _d
        a = _d.fromisoformat(str(d1)[:10])
        b = _d.fromisoformat(str(d2)[:10])
        return max(1, (b - a).days)
    except Exception:
        return 0


def compute_attribution(
    result: dict, bars_by_symbol: dict[str, list[OHLCVBar]]
) -> dict:
    """计算回测收益归因。

    Args:
        result: 回测结果字典（含 rebalances / total_return_pct / equity_curve）。
        bars_by_symbol: 各标的日线 {symbol: [OHLCVBar]}（用于算区间收益）。

    Returns:
        {total_return_pct, total_attributed, residual, by_symbol, by_sector,
         vs_equal_weight}
    """
    rebalances = _parse_rebalances(result)
    avg_weights = _time_weighted_avg_weights(rebalances)
    total_return = float(result.get("total_return_pct", 0.0) or 0.0)

    # 逐标的贡献
    by_symbol: list[dict] = []
    attributed = 0.0
    for sym, w in avg_weights.items():
        bars = bars_by_symbol.get(sym, [])
        ret = _period_return(bars)
        if ret is None:
            # 无价格数据：跳过贡献但保留权重信息
            by_symbol.append({
                "symbol": sym, "sector": classify_sector(sym),
                "avg_weight": round(w, 4), "period_return_pct": None,
                "contribution_pct": 0.0, "note": "无价格数据",
            })
            continue
        contrib = w * ret
        attributed += contrib
        by_symbol.append({
            "symbol": sym, "sector": classify_sector(sym),
            "avg_weight": round(w, 4),
            "period_return_pct": round(ret, 2),
            "contribution_pct": round(contrib, 4),
        })
    by_symbol.sort(key=lambda x: x["contribution_pct"], reverse=True)

    # 行业聚合
    sector_map: dict[str, dict] = {}
    for s in by_symbol:
        sec = s["sector"]
        d = sector_map.setdefault(sec, {
            "sector": sec, "avg_weight": 0.0,
            "contribution_pct": 0.0, "count": 0,
        })
        d["avg_weight"] += s["avg_weight"]
        d["contribution_pct"] += s["contribution_pct"]
        d["count"] += 1
    by_sector = sorted(
        sector_map.values(), key=lambda x: x["contribution_pct"], reverse=True
    )
    for d in by_sector:
        d["avg_weight"] = round(d["avg_weight"], 4)
        d["contribution_pct"] = round(d["contribution_pct"], 4)

    # vs 等权基准
    period_returns = [
        s["period_return_pct"] for s in by_symbol
        if s["period_return_pct"] is not None
    ]
    n = len(period_returns)
    eq_return = sum(period_returns) / n if n else 0.0
    excess = attributed - eq_return
    # 配置效应：Σ (w_i - 1/n) × r_i
    allocation_effect = 0.0
    if n:
        w_eq = 1.0 / n
        for s in by_symbol:
            if s["period_return_pct"] is not None:
                allocation_effect += (s["avg_weight"] - w_eq) * s["period_return_pct"]

    return {
        "total_return_pct": round(total_return, 2),
        "total_attributed_pct": round(attributed, 2),
        "residual_pct": round(total_return - attributed, 2),
        "residual_note": (
            "残差来自权重漂移/再平衡交易/成本/现金，"
            "归因基于调仓目标权重(分段常数近似)"
        ),
        "by_symbol": by_symbol,
        "by_sector": by_sector,
        "vs_equal_weight": {
            "equal_weight_return_pct": round(eq_return, 2),
            "strategy_attributed_pct": round(attributed, 2),
            "excess_pct": round(excess, 2),
            "allocation_effect_pct": round(allocation_effect, 2),
            "allocation_note": (
                "配置效应 = 策略权重相对等权的偏离带来的超额"
                "（正=优于等权配置，负=劣于等权）"
            ),
        },
    }
