"""时光机 handler：会话 CRUD + 成交存档 + as-of 行情切片。

状态权威在前端引擎（设计文档 §3/§5），后端只做数据截断供给与存档。
"""

from datetime import date
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from src.infra.database.replay.models import ReplaySession, ReplayTrade
from src.infra.database.sql_engine.dsn import get_dsn
from src.pkg import responses

CALENDAR_SYMBOL = "sh000001"  # 上证指数日线 = 交易日历


def _conn():
    return psycopg2.connect(get_dsn())


def _repo():
    from src.infra.database.replay.repository import (
        create_replay_repository,
    )

    return create_replay_repository()


def _bar(r: dict) -> dict:
    """裸 SQL 行 → 前端 ReplayBar（date→iso，数值转原生类型）。"""
    return {
        "trade_date": r["trade_date"].isoformat(),
        "open": float(r["open"]),
        "close": float(r["close"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "volume": int(r["volume"] or 0),
        "amount": float(r["amount"] or 0),
    }


def _parse_day(s: Optional[str], field: str):
    if not s:
        return None, responses.fail(f"{field} 必填")
    try:
        return date.fromisoformat(s), None
    except ValueError:
        return None, responses.fail(f"{field} 格式应为 YYYY-MM-DD")


def _next_trading_day(d: date) -> Optional[date]:
    """>= d 的第一个交易日（以指数日线为历）。"""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(trade_date::date) FROM index_ohlcv "
            "WHERE symbol = %s AND trade_date::date >= %s",
            (CALENDAR_SYMBOL, d),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _session_dict(s: ReplaySession, with_state: bool = True) -> dict:
    out = {
        "id": s.id,
        "name": s.name,
        "status": s.status,
        "start_date": s.start_date.isoformat(),
        "current_date": s.current_date.isoformat(),
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "initial_capital": s.initial_capital,
        "cash": s.cash,
        "benchmark_symbol": s.benchmark_symbol,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }
    if with_state:
        out["state"] = s.state or {"pool": [], "positions": [], "nav": []}
    return out


def _trade_dict(t: ReplayTrade) -> dict:
    return {
        "id": t.id,
        "session_id": t.session_id,
        "trade_date": t.trade_date.isoformat(),
        "symbol": t.symbol,
        "side": t.side,
        "price": t.price,
        "shares": t.shares,
        "fee": t.fee,
        "tax": t.tax,
        "note": t.note,
    }


# ── 会话 CRUD ──


def create_session(body: dict):
    name = (body.get("name") or "").strip()
    capital = body.get("initial_capital")
    d, err = _parse_day(body.get("start_date"), "start_date")
    if err:
        return err
    if not name:
        return responses.fail("name 必填")
    try:
        capital = float(capital)
    except (TypeError, ValueError):
        return responses.fail("initial_capital 应为正数")
    if capital <= 0:
        return responses.fail("initial_capital 应为正数")
    if d >= date.today():
        return responses.fail("起始日期必须早于今天")
    first = _next_trading_day(d)
    if first is None:
        return responses.fail("起始日期之后没有交易日数据")
    end_d, err = (
        _parse_day(body.get("end_date"), "end_date")
        if body.get("end_date")
        else (None, None)
    )
    if err:
        return err
    if end_d is not None and end_d <= first:
        return responses.fail("end_date 必须晚于起始交易日")
    if end_d is not None and end_d > date.today():
        return responses.fail("end_date 不能晚于今天")
    s = ReplaySession(
        name=name,
        start_date=first,
        current_date=first,
        end_date=end_d,
        initial_capital=capital,
        cash=capital,
        benchmark_symbol=body.get("benchmark_symbol") or "sh000300",
        state={"pool": [], "positions": [], "nav": []},
    )
    return responses.success(_session_dict(_repo().create(s)))


def list_sessions():
    rows = _repo().list()
    return responses.success(
        [_session_dict(s, with_state=False) for s in rows]
    )


def get_session(session_id: int):
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    return responses.success(_session_dict(s))


def save_state(session_id: int, body: dict):
    d, err = _parse_day(body.get("current_date"), "current_date")
    if err:
        return err
    state = body.get("state")
    if not isinstance(state, dict):
        return responses.fail("state 应为对象")
    try:
        cash = float(body.get("cash"))
    except (TypeError, ValueError):
        return responses.fail("cash 应为数字")
    ok = _repo().save_state(session_id, d, cash, state)
    return (
        responses.success({"id": session_id})
        if ok
        else responses.fail("会话不存在")
    )


def reveal(session_id: int):
    ok = _repo().set_status(session_id, "revealed")
    return (
        responses.success({"id": session_id, "status": "revealed"})
        if ok
        else responses.fail("会话不存在")
    )


def delete_session(session_id: int):
    _repo().delete(session_id)
    return responses.success({"id": session_id})


# ── 成交存档 ──


def add_trade(session_id: int, body: dict):
    repo = _repo()
    s = repo.get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if s.status != "active":
        return responses.fail("会话已揭晓，不能再记成交")
    d, err = _parse_day(body.get("trade_date"), "trade_date")
    if err:
        return err
    side = body.get("side")
    if side not in ("buy", "sell"):
        return responses.fail("side 应为 buy|sell")
    try:
        t = ReplayTrade(
            session_id=session_id,
            trade_date=d,
            symbol=str(body["symbol"]),
            side=side,
            price=float(body["price"]),
            shares=int(body["shares"]),
            fee=float(body.get("fee") or 0),
            tax=float(body.get("tax") or 0),
            note=body.get("note") or None,
        )
    except (KeyError, TypeError, ValueError):
        return responses.fail("symbol/price/shares 必填且为数字")
    return responses.success(_trade_dict(repo.add_trade(t)))


def list_trades(session_id: int):
    rows = _repo().list_trades(session_id)
    return responses.success([_trade_dict(t) for t in rows])


# ── 行情切片（Task 3） ──

_BAR_COLS = (
    "trade_date::date AS trade_date, open_ AS open, close_ AS close, "
    "high_ AS high, low_ AS low, volume, amount"
)


def _table_for(symbol: str) -> str:
    """replay 只处理日线：指数走 index_ohlcv，其余走 stock_ohlcv。"""
    s = symbol.lower()  # 库内统一小写带前缀（sh000300/sh600519）
    if s.startswith(("sh000", "sz399", "sw")):
        return "index_ohlcv"
    return "stock_ohlcv"


def kline(symbol: str, asof: str, limit: int = 300):
    d, err = _parse_day(asof, "asof")
    if err:
        return err
    if d > date.today():
        return responses.fail("asof 不能晚于今天")
    limit = max(1, min(limit, 3000))
    table = _table_for(symbol)
    sym = symbol.lower()  # 库内统一小写
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f'SELECT {_BAR_COLS} FROM "{table}" '
            "WHERE symbol = %s AND trade_date::date <= %s "
            "ORDER BY trade_date DESC LIMIT %s",
            (sym, d, limit),
        )
        rows = [_bar(r) for r in reversed(cur.fetchall())]
    return responses.success({"symbol": symbol, "bars": rows})


def advance(session_id: int, days: int = 1):
    """油门端点：会话 current_date 之后 N 个交易日的池内 bar + 基准。"""
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    days = max(1, min(days, 60))
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT trade_date::date AS d FROM index_ohlcv "
            "WHERE symbol = %s AND trade_date::date > %s "
            "ORDER BY trade_date LIMIT %s",
            (CALENDAR_SYMBOL, s.current_date, days),
        )
        dates = [r["d"] for r in cur.fetchall()]
        if not dates:
            return responses.success(
                {"dates": [], "bars": {}, "benchmark": []})
        d0, d1 = dates[0], dates[-1]
        pool = (s.state or {}).get("pool") or []
        bars: dict[str, list] = {}
        if pool:
            cur.execute(
                f"SELECT symbol, {_BAR_COLS} FROM stock_ohlcv "
                "WHERE symbol = ANY(%s) "
                "AND trade_date::date >= %s AND trade_date::date <= %s "
                "ORDER BY symbol, trade_date",
                (pool, d0, d1),
            )
            for r in cur.fetchall():
                sym = r.pop("symbol")
                bars.setdefault(sym, []).append(_bar(r))
        cur.execute(
            f"SELECT {_BAR_COLS} FROM index_ohlcv "
            "WHERE symbol = %s "
            "AND trade_date::date >= %s AND trade_date::date <= %s "
            "ORDER BY trade_date",
            (s.benchmark_symbol, d0, d1),
        )
        bench = [_bar(r) for r in cur.fetchall()]
    # 服务端游标随请求自洽推进（终审 C1：防抖存档窗口期连点/播放不再重复推进）
    _repo().bump_current_date(session_id, dates[-1])
    return responses.success({
        "dates": [d.isoformat() for d in dates],
        "bars": bars,
        "benchmark": bench,
    })


# ── 估值分位 / 当日榜单（Task 4） ──

_SAMPLE_MIN = 30  # 与 fundamental/percentile.py 的 SAMPLE_MIN 一致


def valuation(symbol: str, asof: str):
    d, err = _parse_day(asof, "asof")
    if err:
        return err
    if d > date.today():
        return responses.fail("asof 不能晚于今天")
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT pe_ttm, pb FROM stock_valuation "
            "WHERE symbol = %s AND trade_date <= %s "
            "ORDER BY trade_date DESC LIMIT 1",
            (symbol, d),
        )
        row = cur.fetchone()
        if row is None:
            return responses.fail("该日期之前无估值数据")
        out = {"as_of": d.isoformat(), "pe_ttm": None, "pb": None}
        for key in ("pe_ttm", "pb"):
            curv = row[key]
            if curv is None or curv <= 0:
                continue
            cur.execute(
                f"SELECT COUNT(*) AS n, "
                f"COUNT(*) FILTER (WHERE {key} <= %s) AS le "
                "FROM stock_valuation "
                "WHERE symbol = %s AND trade_date <= %s "
                "AND trade_date > %s::date - INTERVAL '10 years' "
                f"AND {key} IS NOT NULL AND {key} > 0",
                (float(curv), symbol, d, d),
            )
            agg = cur.fetchone()
            pct = None
            if agg and agg["n"] and agg["n"] >= _SAMPLE_MIN:
                pct = round(agg["le"] / agg["n"], 4)
            out[key] = {
                "value": float(curv),
                "percentile": pct,
                "window": "10y",
            }
    return responses.success(out)


def board(asof: str, type: str = "gainers", limit: int = 50):
    d, err = _parse_day(asof, "asof")
    if err:
        return err
    if d > date.today():
        return responses.fail("asof 不能晚于今天")
    if type not in ("gainers", "amount"):
        return responses.fail("type 应为 gainers|amount")
    order = "pct DESC" if type == "gainers" else "a.amount DESC"
    limit = max(1, min(limit, 200))
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT MAX(trade_date::date) AS prev_day FROM index_ohlcv "
            "WHERE symbol = %s AND trade_date::date < %s",
            (CALENDAR_SYMBOL, d),
        )
        prev = cur.fetchone()["prev_day"]
        if prev is None:
            return responses.fail("asof 之前无交易日")
        cur.execute(
            "SELECT a.symbol, a.close_ AS close, "
            "(a.close_ / NULLIF(p.close_, 0) - 1) * 100 AS pct, "
            "a.amount "
            "FROM stock_ohlcv a "
            "JOIN stock_ohlcv p ON p.symbol = a.symbol "
            "AND p.trade_date::date = %s "
            "WHERE a.trade_date::date = %s "
            # 榜单只取 A 股（sh/sz/bj 前缀），stock_ohlcv 混有港股等脏数据
            "AND a.symbol ~ '^(sh|sz|bj)' "
            f"ORDER BY {order} LIMIT %s",
            (prev, d, limit),
        )
        rows = cur.fetchall()
        symbols = [r["symbol"] for r in rows]
        names: dict[str, str] = {}
        if symbols:
            cur.execute(
                "SELECT symbol, name FROM stock_info "
                "WHERE symbol = ANY(%s)",
                (symbols,),
            )
            names = {r["symbol"]: r["name"] for r in cur.fetchall()}
    data = [{
        "symbol": r["symbol"],
        "name": names.get(r["symbol"], ""),
        "close": float(r["close"]),
        "pct_chg": round(float(r["pct"] or 0), 2),
        "amount": float(r["amount"] or 0),
    } for r in rows]
    return responses.success(data)
