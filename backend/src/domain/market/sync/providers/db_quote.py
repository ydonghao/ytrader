"""DB 驱动的个股/ETF 行情+估值 provider(替换 tencent_quote 的逐请求实时拉取)。

设计:国家队「持仓全景」改为「最新交易日时点快照」,数据全部来自已同步的 DB:
  - 价格/K线/52周/动量/换手/振幅 ← stock_ohlcv(全市场日线,每日同步)
  - PE/PB/市值/股息率 ← stock_valuation(每日同步)
  - ETF 份额 ← national_team_etf_shares(每日 cron 用腾讯种子累积)

逐请求零外部依赖,稳;数据随每日同步更新。symbol 用 sh/sz 前缀(两表一致),
国家队表是裸 6 位代码,本模块负责映射。

性能:680 只持仓 → 3 条批量 SQL(估值最新行 / 52周高低 / 近30日序列),60s 缓存。
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any

_CACHE_TTL = 120.0  # 秒(纯 DB,可略长于腾讯)
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _prefixed(code: str) -> str:
    """裸 6 位代码 → sh/sz 前缀(与 ohlcv/valuation 一致)。"""
    code = str(code).strip()
    if code[:2] in ("sh", "sz"):
        return code
    if code.startswith(("5", "6", "9")):
        return f"sh{code}"
    if code.startswith(("0", "1", "3")):
        return f"sz{code}"
    return f"sh{code}"


def _engine():
    from src.infra.database.sql_engine.engine import create_db_connection
    from src.infra.database.sql_engine.dsn import get_dsn
    return create_db_connection(get_dsn())


def _latest_trade_date() -> dt.date | None:
    from sqlalchemy import text
    db = _engine()
    with db.session_scope() as s:
        return s.execute(text("SELECT max(trade_date) FROM stock_ohlcv")).scalar()


def _num(v, default=0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def _batch_holdings_quote(bare_codes: list[str]) -> dict[str, dict]:
    """一批个股的时点行情+估值(最新交易日)。返回 {bare_code: fields}。"""
    if not bare_codes:
        return {}
    from sqlalchemy import text
    prefixed = [_prefixed(c) for c in bare_codes]
    code_by_pref = {_prefixed(c): c for c in bare_codes}
    db = _engine()
    latest = _latest_trade_date()
    if latest is None:
        return {}
    cutoff_30 = latest - dt.timedelta(days=45)   # 取近 ~30 个交易日(日历日放宽)
    cutoff_250 = latest - dt.timedelta(days=400)  # 52 周

    with db.session_scope() as s:
        # 1) 估值:每只最新一行
        val_rows = s.execute(text(
            "SELECT DISTINCT ON (symbol) symbol, pe_ttm, pb, total_mv "
            "FROM stock_valuation WHERE symbol = ANY(:syms) "
            "ORDER BY symbol, trade_date DESC"
        ), {"syms": prefixed}).all()
        val = {r[0]: {"pe_ttm": _num(r[1]), "pb": _num(r[2]), "mcap": _num(r[3])} for r in val_rows}

        # 2) 52 周高低
        w52_rows = s.execute(text(
            "SELECT symbol, max(high_), min(low_) FROM stock_ohlcv "
            "WHERE symbol = ANY(:syms) AND trade_date >= :c GROUP BY symbol"
        ), {"syms": prefixed, "c": cutoff_250}).all()
        w52 = {r[0]: (_num(r[1]), _num(r[2])) for r in w52_rows}

        # 3) 近 30 日序列(算 动量/回撤/K线 + 取最新 close/change/换手/成交额/振幅)
        recent = s.execute(text(
            "SELECT symbol, trade_date, close_, high_, low_, volume, amount, "
            "turnrate, amplitude, change_pct "
            "FROM stock_ohlcv WHERE symbol = ANY(:syms) AND trade_date >= :c "
            "ORDER BY symbol, trade_date"
        ), {"syms": prefixed, "c": cutoff_30}).all()

    # 按 symbol 聚合序列
    series: dict[str, list] = {}
    last_row: dict[str, Any] = {}
    for r in recent:
        sym, d, close_, hi, lo, vol, amt, turn, amp, chgpct = r
        series.setdefault(sym, []).append({
            "date": d, "close": _num(close_), "high": _num(hi), "low": _num(lo),
            "vol": _num(vol), "amount": _num(amt), "turn": _num(turn),
            "amplitude": _num(amp), "change_pct": _num(chgpct),
        })
        last_row[sym] = series[sym][-1]

    out: dict[str, dict] = {}
    for pref in prefixed:
        bare = code_by_pref[pref]
        ser = series.get(pref, [])
        if not ser:
            continue  # 该股无日线(停牌久/未覆盖)→ 跳过,前端降级
        last = ser[-1]
        closes = [p["close"] for p in ser]
        price = last["close"]
        h52, l52 = w52.get(pref, (0.0, 0.0))
        week_52_pos = (
            round((price - l52) / (h52 - l52) * 100, 1)
            if h52 > l52 and price > 0 else 50.0
        )
        # 动量:5日/20日(用序列末尾倒数,不足则用能算的)
        def _chg(days_back: int) -> float:
            if len(closes) > days_back and closes[-1 - days_back]:
                return round((closes[-1] - closes[-1 - days_back]) / closes[-1 - days_back] * 100, 2)
            return 0.0
        chg_5d = _chg(5)
        chg_20d = _chg(20)
        # 20 日最大回撤
        window = closes[-21:]
        max_dd = 0.0
        if len(window) >= 2:
            peak = window[0]
            for c in window:
                if c > peak:
                    peak = c
                if peak:
                    dd = (c - peak) / peak * 100
                    if dd < max_dd:
                        max_dd = dd
        # 量比:今日量 / 近5日均量
        vols = [p["vol"] for p in ser]
        avg5 = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else (sum(vols[:-1]) / max(len(vols) - 1, 1))
        vol_ratio = round(last["vol"] / avg5, 2) if avg5 else 0.0
        v = val.get(pref, {})
        out[bare] = {
            "code": bare,
            "name": "",  # 名字由持仓表给出
            "price": round(price, 3),
            "change_pct": round(last["change_pct"], 2),
            "pe_ttm": round(v.get("pe_ttm", 0), 2),
            "pb": round(v.get("pb", 0), 2),
            "mcap_yi": round(v.get("mcap", 0) / 1e8, 2),     # total_mv(元)→亿
            "float_mcap_yi": 0.0,                              # DB 无流通市值,留空
            "amount_wan": round(last["amount"] / 1e4, 1),     # 元→万
            "turnover_pct": round(last["turn"], 2),
            "volume_ratio": vol_ratio,
            "amplitude": round(last["amplitude"], 2),
            "high_52w": round(h52, 3),
            "low_52w": round(l52, 3),
            "week_52_position": week_52_pos,
            "chg_5d": chg_5d,
            "chg_20d": chg_20d,
            "max_drawdown_20d": round(max_dd, 2),
            "kline": [{"date": str(p["date"])[:10], "open": p["close"], "close": p["close"],
                        "high": p["high"], "low": p["low"]} for p in ser[-30:]],
            "_source": "DB(stock_ohlcv+stock_valuation,最新交易日)",
        }
    return out


def fetch_stock_quotes(bare_codes: list[str]) -> dict[str, dict]:
    """与 tencent_quote.fetch_stock_quotes 同名同构,供 nt_snapshot 无缝替换。
    带 120s 进程缓存。"""
    key = "st_" + ",".join(sorted(set(bare_codes)))
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    data = _batch_holdings_quote(bare_codes)
    with _CACHE_LOCK:
        _CACHE[key] = (now, data)
    return data


def fetch_etf_quotes(etf_codes: list[str]) -> dict[str, dict]:
    """ETF 行情:价/涨跌/换手/成交 ← ohlcv;份额/规模 ← national_team_etf_shares 最新行。"""
    if not etf_codes:
        return {}
    from sqlalchemy import text
    prefixed = [_prefixed(c) for c in etf_codes]
    code_by_pref = {_prefixed(c): c for c in etf_codes}
    db = _engine()
    latest = _latest_trade_date()
    if latest is None:
        return {}
    cutoff = latest - dt.timedelta(days=10)
    out: dict[str, dict] = {}
    with db.session_scope() as s:
        # ohlcv 最新一行(ETF 代码 5/1 开头,带前缀)
        rows = s.execute(text(
            "SELECT DISTINCT ON (symbol) symbol, close_, change_pct, amount, turnrate "
            "FROM stock_ohlcv WHERE symbol = ANY(:syms) ORDER BY symbol, trade_date DESC"
        ), {"syms": prefixed}).all()
        ohlcv = {r[0]: r for r in rows}
        # ETF 份额最新行
        from src.infra.database.market.national_team_etf_shares import (
            create_etf_shares_repository,
        )
        repo = create_etf_shares_repository()
    for pref in prefixed:
        bare = code_by_pref[pref]
        o = ohlcv.get(pref)
        if not o:
            continue
        price = _num(o[1])
        hist = repo.get_history(bare, 90)
        shares_yi = hist[-1]["shares"] / 1e8 if hist else 0.0
        out[bare] = {
            "code": bare,
            "name": "",
            "price": round(price, 3),
            "change_pct": round(_num(o[2]), 2),
            "amount_wan": round(_num(o[3]) / 1e4, 1),
            "turnover_pct": round(_num(o[4]), 2),
            "volume_ratio": 0.0,
            "high_52w": 0.0, "low_52w": 0.0,
            "shares": hist[-1]["shares"] if hist else 0,
            "shares_yi": round(shares_yi, 2),
            "total_value_yi": round(shares_yi * price, 2),
            "_source": "DB(ohlcv + etf_shares每日快照)",
        }
    return out


def fetch_one_kline(bare_code: str, days: int = 30) -> list[dict]:
    """前复权日 K(详情弹窗蜡烛图)——直接读 ohlcv,比 akshare 快且无外部依赖。
    注:ohlcv 是不复权价;国家队持仓历史看趋势,不复权可接受。"""
    from sqlalchemy import text
    pref = _prefixed(bare_code)
    db = _engine()
    cutoff = (_latest_trade_date() or dt.date.today()) - dt.timedelta(days=int(days * 1.6))
    with db.session_scope() as s:
        rows = s.execute(text(
            "SELECT trade_date, open_, close_, high_, low_ FROM stock_ohlcv "
            "WHERE symbol = :s AND trade_date >= :c ORDER BY trade_date"
        ), {"s": pref, "c": cutoff}).all()
    return [{"date": str(r[0])[:10], "open": _num(r[1]), "close": _num(r[2]),
             "high": _num(r[3]), "low": _num(r[4])} for r in rows[-days:]]
