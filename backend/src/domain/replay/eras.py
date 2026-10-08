"""基准指数历史 → 牛顶/熊底/震荡三时代池(v3 盲盒开局)。"""

from __future__ import annotations

from datetime import date

LOOKBACK = 250    # 前250日涨幅分位
FORWARD = 120     # 后120日走势判定
MIN_GAP = 60      # 池内日期最小间隔(自然日近似交易日)
MIN_HISTORY = 300  # 起点前至少300交易日(K线上下文,由 handler 用)


def pools(bars: list[tuple]) -> dict[str, list[date]]:
    """bars = [(trade_date, close)] 升序 → 三池日期列表。"""
    n = len(bars)
    if n <= max(LOOKBACK, MIN_HISTORY) + FORWARD:
        return {"bull_top": [], "bear_bottom": [], "range": []}
    cands: list[tuple] = []  # (date, trail, fwd_dd, fwd_ret)
    for i in range(LOOKBACK, n - FORWARD):
        base = bars[i - LOOKBACK][1]
        cur = bars[i][1]
        if not base or not cur:
            continue
        trail = cur / base - 1
        window = [b[1] for b in bars[i:i + FORWARD + 1]]
        fwd_dd = 1 - min(window) / cur
        fwd_ret = bars[i + FORWARD][1] / cur - 1
        cands.append((bars[i][0], trail, fwd_dd, fwd_ret))
    if not cands:
        return {"bull_top": [], "bear_bottom": [], "range": []}
    trails = sorted(c[1] for c in cands)
    q90 = trails[int(len(trails) * 0.9)]
    q10 = trails[int(len(trails) * 0.1)]
    bull = thin([c[0] for c in cands if c[1] >= q90 and c[2] > 0.20])
    bear = thin([c[0] for c in cands if c[1] <= q10 and c[3] > 0.15])
    used = set(bull) | set(bear)
    rng = thin([c[0] for c in cands if c[0] not in used])
    return {"bull_top": bull, "bear_bottom": bear, "range": rng}


def thin(dates: list[date], gap: int = MIN_GAP) -> list[date]:
    """贪心抽稀:顺序保留,与前一个保留点间隔 <gap 自然日的丢弃。"""
    out: list[date] = []
    for d in dates:
        if not out or (d - out[-1]).days >= gap:
            out.append(d)
    return out
