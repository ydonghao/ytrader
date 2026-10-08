"""揭晓评分(v3):总分 = 超额收益分(80) + 换手纪律分(20),spec §3.5。"""

from __future__ import annotations

TRADING_DAYS = 250


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _annual_pct(v0: float, v1: float, days: int) -> float:
    if v0 <= 0 or days <= 0:
        return 0.0
    return ((v1 / v0) ** (TRADING_DAYS / days) - 1) * 100


def _max_drawdown(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    peak = values[0]
    mdd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            mdd = max(mdd, 1 - v / peak)
    return mdd


def _closed_win_rate(trades: list[dict]) -> tuple[float | None, int]:
    """FIFO 平仓胜率:(win_rate|None, 平仓次数)。trades 须按时间升序。"""
    lots: dict[str, list[list]] = {}
    wins = 0
    trips = 0
    for t in trades:
        q = lots.setdefault(t["symbol"], [])
        if t["side"] == "buy":
            q.append([t["price"], t["shares"]])
            continue
        remain = t["shares"]
        pnl = 0.0
        while remain > 0 and q:
            lot = q[0]
            take = min(lot[1], remain)
            pnl += (t["price"] - lot[0]) * take
            remain -= take
            lot[1] -= take
            if lot[1] == 0:
                q.pop(0)
        if remain == 0:
            trips += 1
            wins += 1 if pnl > 0 else 0
    return (wins / trips if trips else None), trips


def score(nav: list[dict], benchmark_bars: list[dict],
          trades: list[dict], initial_capital: float) -> dict:
    if len(nav) < 2:
        raise ValueError("nav 不足2点，无法评分")
    days = len(nav)
    final = nav[-1]["value"]
    port_ann = _annual_pct(initial_capital, final, days)
    d0, d1 = nav[0]["date"], nav[-1]["date"]
    win = [b for b in benchmark_bars if d0 <= b["trade_date"] <= d1]
    bench_ann = (_annual_pct(win[0]["close"], win[-1]["close"], days)
                 if len(win) >= 2 else 0.0)
    excess_ann = port_ann - bench_ann
    excess_score = _clamp(40 + 8 * excess_ann, 0, 80)

    avg_nav = sum(p["value"] for p in nav) / days
    turnover_raw = (sum(t["price"] * t["shares"] for t in trades) / 2
                    / avg_nav) if avg_nav > 0 else 0.0
    turn_ann = turnover_raw * TRADING_DAYS / days
    turn_score = (20.0 if turn_ann <= 2
                  else _clamp(20 * (10 - turn_ann) / 8, 0, 20))

    nav_values = [p["value"] for p in nav]
    bench_values = [b["close"] for b in win] or [1.0]
    win_rate, trips = _closed_win_rate(trades)
    cash_ratio = None
    weight = None
    pts = [p for p in nav if p.get("cash") is not None]
    if pts:
        cash_ratio = sum(p["cash"] / p["value"] for p in pts) / len(pts)
        weights = [v / p["value"] for p in pts
                   for v in (p.get("pos") or {}).values()]
        weight = max(weights) if weights else None
    return {
        "total": round(excess_score + turn_score, 1),
        "excess_score": round(excess_score, 1),
        "turnover_score": round(turn_score, 1),
        "annual_excess_pct": round(excess_ann, 2),
        "annual_turnover": round(turn_ann, 2),
        "disclosures": {
            "max_drawdown": _max_drawdown(nav_values),
            "benchmark_max_drawdown": _max_drawdown(bench_values),
            "closed_win_rate": win_rate,
            "closed_trips": trips,
            "avg_cash_ratio": cash_ratio,
            "max_position_weight": weight,
        },
    }
