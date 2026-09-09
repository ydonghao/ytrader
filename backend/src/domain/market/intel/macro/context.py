"""宏观分析师输入收集器：聚合宏观指标 + 财经新闻 + 指数走势，喂给 LLM。

三类输入：
  1. 宏观指标读数（最新值 + 近 6 期趋势）— 来自 macro_indicator
  2. 近期财经新闻（按重要性）— 来自 intel_news
  3. 近期指数/汇率/商品走势（近 1 月收益）— 来自 index_ohlcv / fx_rate / commodity_ohlcv
"""
from datetime import date, timedelta
from typing import Any

from loguru import logger


def collect_macro_readings(indicator_codes: list[str], lookback: int = 6) -> dict[str, Any]:
    """收集每个宏观指标的最新值 + 近 N 期趋势。

    返回 {code: {name, unit, latest_value, latest_date, trend: [..], direction: up/down/flat, pct_change}}
    """
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )

    repo = create_macro_indicator_repository()
    meta_map = {m["code"]: m for m in repo.list_meta()}
    out: dict[str, Any] = {}
    for code in indicator_codes:
        series = repo.get_series(code, limit=lookback)
        if not series:
            continue
        meta = meta_map.get(code, {})
        latest = series[-1]
        prev = series[0] if len(series) > 1 else None
        # 趋势方向（首末对比）
        direction = "flat"
        pct = None
        if prev and prev["value"] and latest["value"] and prev["value"] != 0:
            pct = round((latest["value"] - prev["value"]) / abs(prev["value"]) * 100, 2)
            if abs(pct) < 1.0:
                direction = "flat"
            else:
                direction = "up" if pct > 0 else "down"
        out[code] = {
            "name": meta.get("name", code),
            "unit": meta.get("unit", ""),
            "group": meta.get("group", ""),
            "latest_value": latest["value"],
            "latest_date": latest["report_date"],
            "trend": [round(s["value"], 3) for s in series],
            "direction": direction,
            "pct_change_over_window": pct,
            "threshold_high": meta.get("threshold_high"),
            "threshold_low": meta.get("threshold_low"),
        }
    return out


def collect_recent_news(hours: int = 72, limit: int = 25) -> list[dict]:
    """收集近期财经新闻（按重要性排序）。"""
    try:
        from src.infra.database.intel.repository import create_intel_repository
        repo = create_intel_repository()
        news = repo.find_trending(hours=hours, limit=limit)
        # 过滤财经类优先（finance / policy）
        finance = [n for n in news if n.get("category") in ("finance", "cctv_news")]
        return (finance + [n for n in news if n not in finance])[:limit]
    except Exception as e:
        logger.warning(f"[macro] collect_recent_news 失败: {e}")
        return []


def _query_ohlcv_return(symbol: str, days: int) -> dict | None:
    """查询单个标的近 days 天的收益率。

    分派：US.*/HK.* → index_ohlcv；FX 对 → fx_rate；商品 → commodity_ohlcv。
    返回 {symbol, close, return_pct, direction} 或 None。
    """
    import psycopg2
    from src.domain.market.sync.jobs.macro_sync import _get_dsn

    is_fx = symbol.isalpha() and len(symbol) == 6  # USDCNY
    is_commodity = symbol in {"XAU", "XAG", "XPT", "XPD", "GC", "SI", "OIL", "CL", "NG"}
    is_global_idx = symbol.startswith(("US.", "HK."))

    if is_fx:
        sql = ("SELECT rate AS close FROM fx_rate WHERE pair = %s "
               "ORDER BY date DESC LIMIT %s")
        col, table_where = "rate", ("pair", symbol)
    elif is_commodity:
        sql = ("SELECT close_ AS close FROM commodity_ohlcv WHERE symbol = %s "
               "ORDER BY trade_date DESC LIMIT %s")
    else:  # index / global index
        sql = ("SELECT close_ AS close FROM index_ohlcv WHERE symbol = %s "
               "ORDER BY trade_date DESC LIMIT %s")

    try:
        with psycopg2.connect(_get_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (symbol, days + 5))  # 多取几日兜底节假日
                rows = cur.fetchall()
        if len(rows) < 2:
            return None
        latest_close = float(rows[0][0])
        base_close = float(rows[-1][0])
        if base_close == 0:
            return None
        ret = round((latest_close - base_close) / base_close * 100, 2)
        direction = "up" if ret > 0.5 else ("down" if ret < -0.5 else "flat")
        return {"symbol": symbol, "close": latest_close, "return_pct": ret, "direction": direction}
    except Exception as e:
        logger.debug(f"[macro] _query_ohlcv_return({symbol}) 失败: {e}")
        return None


def collect_market_context(targets: list[dict], days: int = 30) -> list[dict]:
    """收集预测标的近期走势（近 days 天收益）。

    targets: [{symbol, name, asset_class}, ...]
    返回 [{symbol, name, asset_class, recent_return_pct, recent_direction, close}]
    """
    out = []
    for t in targets:
        sym = t["symbol"]
        r = _query_ohlcv_return(sym, days)
        if r:
            out.append({
                "symbol": sym, "name": t.get("name", sym),
                "asset_class": t.get("asset_class", "index"),
                "recent_return_pct": r["return_pct"],
                "recent_direction": r["direction"],
                "close": r["close"],
            })
        else:
            out.append({
                "symbol": sym, "name": t.get("name", sym),
                "asset_class": t.get("asset_class", "index"),
                "recent_return_pct": None, "recent_direction": None, "close": None,
            })
    return out


def format_context_for_prompt(
    readings: dict, news: list[dict], market: list[dict], targets: list[dict],
) -> str:
    """把三类输入格式化为 LLM 可读的上下文文本。"""
    lines: list[str] = []

    lines.append("【一、宏观经济指标读数】（最新值 + 近 6 期趋势）")
    for code, r in readings.items():
        th = ""
        if r.get("threshold_high") is not None:
            th = f"（阈值线 {r['threshold_high']}）"
        trend_str = " → ".join(str(x) for x in r["trend"])
        lines.append(
            f"- {r['name']}({code})：{r['latest_value']}{r['unit']} "
            f"@ {r['latest_date']}{th} | 趋势 {r['direction']}({r['pct_change_over_window']}%) "
            f"| 近期 {trend_str}"
        )

    lines.append("\n【二、近期财经新闻】（按重要性）")
    if news:
        for n in news[:20]:
            title = (n.get("title") or "").strip()
            imp = n.get("importance")
            sent = n.get("sentiment") or ""
            imp_str = f"[重要度 {imp}]" if imp else ""
            lines.append(f"- {imp_str}({sent}) {title}")
    else:
        lines.append("- （无近期新闻）")

    lines.append("\n【三、近期市场走势】（近 30 日收益）")
    for m in market:
        if m.get("recent_return_pct") is not None:
            lines.append(
                f"- {m['name']}({m['symbol']})：{m['close']} | 近30日 {m['recent_return_pct']}% "
                f"({m['recent_direction']})"
            )

    lines.append("\n【四、需逐个预测方向的标的清单】")
    for t in targets:
        lines.append(f"- {t['symbol']} | {t.get('name', '')} | {t.get('asset_class', 'index')}")

    return "\n".join(lines)
