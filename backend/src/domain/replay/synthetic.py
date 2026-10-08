"""日 OHLC → 8 段盘中合成路径(v3 拟真考核)。

确定性:random.Random(str) 对字符串 seed 走 sha512 派生,跨进程稳定,
同一 (seed, symbol, day) 永远同一路径,服务端可随时重算无需落库。
"""

from __future__ import annotations

import math
import random

SEG_COUNT = 8


def _round2(v: float) -> float:
    return round(v * 100) / 100


def _flat(c: float) -> list[dict]:
    v = _round2(c)
    return [{"open": v, "high": v, "low": v, "close": v}
            for _ in range(SEG_COUNT)]


def segments(symbol: str, day: str, bar: dict, seed: str = "") -> list[dict]:
    """日 bar → SEG_COUNT 段连续 OHLC。

    性质(见测试):端点对齐 open/close、路径必经 high/low、全程有界、
    段间连续(seg[k+1].open == seg[k].close)。坏数据退化为 8 段平坦收盘价。
    """
    try:
        o = float(bar["open"]); h = float(bar["high"])
        l = float(bar["low"]); c = float(bar["close"])
    except (KeyError, TypeError, ValueError):
        # 字段坏但仍可取到 close:退化为平坦收盘价(与测试语义一致)
        try:
            c = float(bar.get("close") or 0)
        except (TypeError, ValueError, AttributeError):
            c = 0.0
        return _flat(c)
    if not all(map(math.isfinite, (o, h, l, c))):
        return _flat(c)
    if l > h or o < l or o > h or c < l or c > h:
        return _flat(c)
    if h == l:  # 一字板
        return _flat(c)

    rng = random.Random(f"{seed}:{symbol}:{day}")
    hi_i = rng.randrange(1, SEG_COUNT)
    lo_i = rng.randrange(1, SEG_COUNT)
    while lo_i == hi_i:
        lo_i = rng.randrange(1, SEG_COUNT)

    pts = [o]
    for k in range(1, SEG_COUNT):
        if k == hi_i:
            pts.append(h)
        elif k == lo_i:
            pts.append(l)
        else:
            # 朝收盘价方向抖动插值,clamp 在 [l, h]
            drift = pts[-1] + (c - pts[-1]) * rng.random() * 0.6
            pts.append(min(h, max(l, drift)))
    pts.append(c)

    segs: list[dict] = []
    wick = (h - l) * 0.05
    for k in range(SEG_COUNT):
        so, sc = pts[k], pts[k + 1]
        sh = min(h, max(l, max(so, sc) + wick * rng.random()))
        sl = min(h, max(l, min(so, sc) - wick * rng.random()))
        segs.append({"open": _round2(so), "high": _round2(sh),
                     "low": _round2(sl), "close": _round2(sc)})
    return segs
