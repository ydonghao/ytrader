"""时光机 handler：会话 CRUD + 成交存档 + as-of 行情切片。

状态权威在前端引擎（设计文档 §3/§5），后端只做数据截断供给与存档。
"""

from datetime import date, timedelta
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

import random as _random

from src.domain.replay import engine as _engine
from src.domain.replay.eras import pools as _era_pools
from src.domain.replay.scoring import score as _score
from src.domain.replay.synthetic import SEG_COUNT, segments as _segments
from src.infra.database.replay.models import ReplaySession, ReplayTrade
from src.infra.database.sql_engine.dsn import get_dsn
from src.pkg import responses

CALENDAR_SYMBOL = "sh000001"  # 上证指数日线 = 交易日历

# 四指数为默认指数带;sz399006 自2010-06-01 起有数据,更早窗口由 _day_bars
# 自然缺省（视图/前端按存在渲染;sh932000 无数据已剔除）
INDEX_SYMBOLS = ("sh000001", "sz399001", "sz399006", "sh000300")


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
    mode = s.mode or "free"
    blind = mode == "exam" and s.status == "active"
    st = s.state or {}
    out = {
        "id": s.id,
        "name": s.name,
        "status": s.status,
        "mode": mode,
        # 拟真+航行中:真实日期脱敏(F12 不设防,spec §6)
        "start_date": None if blind else s.start_date.isoformat(),
        "current_date": None if blind else s.current_date.isoformat(),
        "day_ordinal": st.get("day_ordinal") if blind else None,
        "length_days": st.get("length_days") if blind else None,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "initial_capital": s.initial_capital,
        "cash": s.cash,
        "benchmark_symbol": s.benchmark_symbol,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }
    if with_state:
        state_out = dict(st or {"pool": [], "positions": [], "nav": []})
        if blind:
            state_out.pop("nav", None)  # nav 含真实日期,盲盒期由 /view 供给
        out["state"] = state_out
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
        "confidence": getattr(t, "confidence", None),
        "order_type": t.order_type or "market",
    }


# ── 会话 CRUD ──


def create_session(body: dict):
    mode = body.get("mode") or "free"
    if mode not in ("free", "exam"):
        return responses.fail("mode 应为 free|exam")
    try:
        capital = float(body.get("initial_capital"))
    except (TypeError, ValueError):
        return responses.fail("initial_capital 应为正数")
    if capital <= 0:
        return responses.fail("initial_capital 应为正数")
    if mode == "exam":
        length_days = body.get("length_days")
        if length_days not in (120, 250, 500):
            return responses.fail("length_days 应为 120|250|500")
        era_pref = body.get("era_pref") or "random"
        if era_pref not in ("random", "bull_top", "bear_bottom", "range"):
            return responses.fail(
                "era_pref 应为 random|bull_top|bear_bottom|range")
        benchmark = body.get("benchmark_symbol") or "sh000300"
        try:
            start = _pick_exam_start(benchmark, length_days, era_pref)
        except ValueError as e:
            return responses.fail(str(e))
        s = ReplaySession(
            name=(body.get("name") or "").strip() or "盲盒旅程",
            start_date=start, current_date=start, end_date=None,
            initial_capital=capital, cash=capital,
            benchmark_symbol=benchmark, mode="exam",
            state={
                "pool": [], "positions": [], "nav": [], "names": {},
                "industries": {}, "seg_idx": 0, "day_ordinal": 1,
                "length_days": length_days, "skipped_days": 0,
                "pending_orders": [], "frozen_cash": 0.0,
                # 引擎 state 约定键含 cash(plan §挂单簿):Task 8 建档漏了,
                # Task 9 撮合/记账/视图全按 state["cash"] 走,此处补齐
                "cash": capital,
                "dividends_received": [], "era_pref": era_pref,
            })
        return responses.success(_session_dict(_repo().create(s)))
    # ↓ free:原逻辑不动
    name = (body.get("name") or "").strip()
    d, err = _parse_day(body.get("start_date"), "start_date")
    if err:
        return err
    if not name:
        return responses.fail("name 必填")
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
        name=name, start_date=first, current_date=first, end_date=end_d,
        initial_capital=capital, cash=capital,
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
    s = _repo().get(session_id)
    if s is not None and (s.mode or "free") == "exam":
        return responses.fail("拟真会话由服务端记账，禁止外部存档")
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
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    out = {"id": session_id, "status": "revealed"}
    if (s.mode or "free") == "exam":
        state = s.state
        if not state.get("score"):
            nav = state.get("nav") or []
            if len(nav) < 2:
                return responses.fail("评分失败：还没有走过完整的交易日")
            trades = [_trade_dict(t) for t in _repo().list_trades(session_id)]
            with _conn() as conn, conn.cursor(
                    cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT {_BAR_COLS} FROM index_ohlcv "
                    "WHERE symbol = %s AND trade_date::date >= %s "
                    "AND trade_date::date <= %s ORDER BY trade_date",
                    (s.benchmark_symbol.lower(), nav[0]["date"],
                     nav[-1]["date"]),
                )
                bench = [_bar(r) for r in cur.fetchall()]
            try:
                state["score"] = _score(nav, bench, trades,
                                        s.initial_capital)
            except ValueError as e:
                return responses.fail(f"评分失败：{e}")
            _repo().save_state(session_id, s.current_date, state["cash"],
                               state)
        out["score"] = state["score"]
    if not _repo().set_status(session_id, "revealed"):
        return responses.fail("会话不存在")
    return responses.success(out)


def delete_session(session_id: int):
    _repo().delete(session_id)
    return responses.success({"id": session_id})


# ── 成交存档 ──


def add_trade(session_id: int, body: dict):
    repo = _repo()
    s = repo.get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") == "exam":
        # 拟真会话由服务端 place_order 撮合计账,外部直记成交会
        # 绕过资金/持仓校验污染成交清单(评分读 state 不受影响)
        return responses.fail("拟真会话由服务端记账，禁止外部记成交")
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


def advance(session_id: int, days: int = 1, step: str | None = None):
    """油门端点：free=days 日推进(原语义)；exam=step=seg|day 段级推进。"""
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") == "exam":
        if step not in ("seg", "day"):
            return responses.fail("拟真会话请用 step=seg|day 推进")
        return _advance_exam(s, step)
    if step is not None:
        return responses.fail("step 仅拟真会话可用")
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
                {"dates": [], "bars": {}, "benchmark": [], "indices": {}})
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
        cur.execute(
            f"SELECT symbol, {_BAR_COLS} FROM index_ohlcv "
            "WHERE symbol = ANY(%s) "
            "AND trade_date::date >= %s AND trade_date::date <= %s "
            "ORDER BY symbol, trade_date",
            (list(INDEX_SYMBOLS), d0, d1),
        )
        indices: dict[str, list] = {}
        for r in cur.fetchall():
            sym = r.pop("symbol")
            indices.setdefault(sym, []).append(_bar(r))
    # 服务端游标随请求自洽推进（终审 C1：防抖存档窗口期连点/播放不再重复推进）
    _repo().bump_current_date(session_id, dates[-1])
    return responses.success({
        "dates": [d.isoformat() for d in dates],
        "bars": bars,
        "benchmark": bench,
        "indices": indices,
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
            names = {r["symbol"]: _display_name(r["name"])
                     for r in cur.fetchall()}
    data = [{
        "symbol": r["symbol"],
        "name": names.get(r["symbol"], ""),
        "close": float(r["close"]),
        "pct_chg": round(float(r["pct"] or 0), 2),
        "amount": float(r["amount"] or 0),
    } for r in rows]
    return responses.success(data)


# ── 标的信息 / as-of 新闻（Task 3, v2） ──

import re as _re

_EXCHANGE_PREFIX_RE = _re.compile(r"^(XD|XR|DR)")


def _display_name(name: str) -> str:
    """剥离交易所除权日前缀(XD/XR/DR)——外部行情源常带此标记且伴随截断。"""
    return _EXCHANGE_PREFIX_RE.sub("", name)


def instrument(symbol: str):
    """标的名称+申万一级行业(当前快照口径,无历史维度,如实标注)。"""
    sym = symbol.lower()
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT si.name AS name, m.sw_name_l1 AS industry "
            "FROM (SELECT %s AS s) q "
            "LEFT JOIN stock_info si ON si.symbol = q.s "
            "LEFT JOIN sw_industry_member m ON m.symbol = q.s",
            (sym,),
        )
        row = cur.fetchone()
    if row is None or not row["name"]:
        return responses.fail("未找到该标的")
    return responses.success({
        "symbol": sym,
        "name": _display_name(row["name"]),
        "industry": row["industry"],
    })


def news(asof: str, days: int = 3, limit: int = 20):
    """as-of 新闻头条: intel_news 里 published_at <= asof 的近 N 天。

    覆盖密度受回填进度限制(2026 年密度高,更早年份稀疏)。
    """
    d, err = _parse_day(asof, "asof")
    if err:
        return err
    if d > date.today():
        return responses.fail("asof 不能晚于今天")
    days = max(1, min(days, 14))
    limit = max(1, min(limit, 50))
    start = d - timedelta(days=days)
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT title, source, published_at, importance, url "
            "FROM intel_news "
            "WHERE (published_at AT TIME ZONE 'Asia/Shanghai')::date <= %s "
            "AND (published_at AT TIME ZONE 'Asia/Shanghai')::date >= %s "
            "AND category = ANY(%s) "
            "ORDER BY importance DESC NULLS LAST, "
            "published_at DESC LIMIT %s",
            (d, start, ["finance", "cctv_news"], limit),
        )
        rows = cur.fetchall()
    return responses.success([{
        "title": r["title"],
        "source": r["source"],
        "published_at": r["published_at"].isoformat(),
        "importance": r["importance"],
        "url": r["url"],
    } for r in rows])


# ── v3 拟真考核 ──


def _benchmark_series(symbol: str) -> list[tuple]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date::date, close_ FROM index_ohlcv "
            "WHERE symbol = %s ORDER BY trade_date",
            (symbol.lower(),),
        )
        return cur.fetchall()


def _pick_exam_start(benchmark: str, length_days: int,
                     era_pref: str) -> date:
    """时代池抽起点:偏好池优先,约束前≥300/后≥length_days 交易日;空则回退。

    无任何数据 raise ValueError。
    """
    series = _benchmark_series(benchmark)
    if not series:
        raise ValueError("基准指数无数据")
    dates = [r[0] for r in series]
    idx = {d: i for i, d in enumerate(dates)}

    def usable(d) -> bool:
        i = idx.get(d)
        return i is not None and i >= 300 and i + length_days < len(dates)

    cands: list = []
    if era_pref != "random":
        cands = [d for d in _era_pools(series).get(era_pref, []) if usable(d)]
    if not cands:
        cands = [d for d in dates if usable(d)]
    if not cands:
        cands = dates[300:] or dates  # 数据不足兜底(测试库短历史)
    return _random.choice(cands)


# ── v3 段级推进(信息门:响应只含截至当前段的行情) ──


def _split_symbols(symbols: list[str]) -> tuple[list[str], list[str]]:
    syms = [s.lower() for s in symbols]
    idx = [s for s in syms if s.startswith(("sh000", "sz399"))]
    stk = [s for s in syms if not s.startswith(("sh000", "sz399"))]
    return stk, idx


def _day_bars(symbols: list[str], day: date) -> dict[str, dict]:
    """池内股票+指数的当日 bar(停牌无行)。"""
    out: dict[str, dict] = {}
    stk, idx = _split_symbols(symbols)
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        for table, keys in (("stock_ohlcv", stk), ("index_ohlcv", idx)):
            if not keys:
                continue
            cur.execute(
                f'SELECT symbol, {_BAR_COLS} FROM "{table}" '
                "WHERE symbol = ANY(%s) AND trade_date::date = %s",
                (keys, day),
            )
            for r in cur.fetchall():
                out[r.pop("symbol")] = _bar(r)
    return out


def _prev_closes(symbols: list[str], day: date) -> dict[str, float]:
    """每符号 < day 的最后收盘价(限价区间/停牌估值)。"""
    out: dict[str, float] = {}
    stk, idx = _split_symbols(symbols)
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        for table, keys in (("stock_ohlcv", stk), ("index_ohlcv", idx)):
            if not keys:
                continue
            cur.execute(
                f'SELECT DISTINCT ON (symbol) symbol, close_ AS close '
                f'FROM "{table}" WHERE symbol = ANY(%s) '
                "AND trade_date::date < %s ORDER BY symbol, trade_date DESC",
                (keys, day),
            )
            for r in cur.fetchall():
                out[r["symbol"]] = float(r["close"])
    return out


def _dividends_for(pool: list[str], day: date) -> list[dict]:
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT symbol, div_per_share, stock_div, convert "
            "FROM stock_dividend "
            "WHERE symbol = ANY(%s) AND ex_date = %s",
            ([s.lower() for s in pool], day),
        )
        return [dict(r) for r in cur.fetchall()]


def _segs_of(session_id: int, bars: dict[str, dict],
             day_str: str) -> dict[str, list[dict]]:
    return {sym: _segments(sym, day_str, bar, seed=str(session_id))
            for sym, bar in bars.items()}


def _partial_bar(bar: dict, segs: list[dict]) -> dict:
    n = len(segs)
    return {
        "trade_date": bar["trade_date"],
        "open": segs[0]["open"],
        "high": max(s["high"] for s in segs),
        "low": min(s["low"] for s in segs),
        "close": segs[-1]["close"],
        "volume": int(bar["volume"] * n / SEG_COUNT),
        "amount": round(bar["amount"] * n / SEG_COUNT, 2),
    }


def _trade_model(session_id: int, t: dict) -> ReplayTrade:
    return ReplayTrade(
        session_id=session_id,
        trade_date=date.fromisoformat(t["trade_date"]),
        symbol=t["symbol"], side=t["side"], price=t["price"],
        shares=t["shares"], fee=t["fee"], tax=t["tax"],
        note=t.get("note"), confidence=t.get("confidence"),
        order_type=t.get("order_type", "market"))


def _exam_view(s: ReplaySession, fills=None, events=None) -> dict:
    state = s.state
    day_str = s.current_date.isoformat()
    seed = str(s.id)
    pool = state.get("pool") or []
    bars = _day_bars(pool + list(INDEX_SYMBOLS), s.current_date)
    seg_idx = state.get("seg_idx", 0)
    all_segs = _segs_of(s.id, bars, day_str)
    stock_segs = {sym: all_segs[sym][:seg_idx + 1] for sym in pool
                  if sym in all_segs}
    idx_segs = {sym: all_segs[sym][:seg_idx + 1]
                for sym in INDEX_SYMBOLS if sym in all_segs}
    suspended = [sym for sym in pool if sym not in bars]
    ev = list(events or [])
    ev += [{"type": "suspended", "symbol": sym, "msg": "停牌/无行情"}
           for sym in suspended]
    out = {
        "mode": "exam",
        "day_ordinal": state.get("day_ordinal", 1),
        "seg_idx": seg_idx,
        "seg_count": SEG_COUNT,
        "date": day_str,
        "travel_complete": bool(state.get("travel_complete")),
        "segments": stock_segs,
        "partial_bars": {sym: _partial_bar(bars[sym], stock_segs[sym])
                         for sym in stock_segs},
        "indices_segments": idx_segs,
        "indices_partial": {sym: _partial_bar(bars[sym], idx_segs[sym])
                            for sym in idx_segs},
        "cash": state["cash"],
        "positions": state.get("positions") or [],
        "nav": state.get("nav") or [],
        "pending": state.get("pending_orders") or [],
        "frozen_cash": state.get("frozen_cash", 0.0),
        "events": ev,
        "pool": pool,
        "names": state.get("names") or {},
        "industries": state.get("industries") or {},
    }
    if fills is not None:
        out["fills"] = fills
    return out


def view(session_id: int):
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") != "exam":
        return responses.fail("仅拟真会话有视图端点")
    return responses.success(_exam_view(s))


def add_pool(session_id: int, body: dict):
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") != "exam":
        return responses.fail("仅拟真会话使用池端点")
    if s.status != "active":
        return responses.fail("会话已揭晓")
    syms = body.get("symbols")
    if not isinstance(syms, list) or not syms:
        return responses.fail("symbols 应为非空数组")
    state = s.state
    pool = state.setdefault("pool", [])
    failed: list[str] = []
    for raw in syms:
        sym = str(raw).lower()
        if sym in pool:
            continue
        with _conn() as conn, conn.cursor(
                cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT 1 FROM stock_ohlcv WHERE symbol = %s "
                "AND trade_date::date <= %s LIMIT 1",
                (sym, s.current_date),
            )
            if cur.fetchone() is None:
                failed.append(sym)
                continue
            cur.execute(
                "SELECT si.name AS name, m.sw_name_l1 AS industry "
                "FROM (SELECT %s AS s) q "
                "LEFT JOIN stock_info si ON si.symbol = q.s "
                "LEFT JOIN sw_industry_member m ON m.symbol = q.s",
                (sym,),
            )
            row = cur.fetchone()
        pool.append(sym)
        if row and row["name"]:
            state.setdefault("names", {})[sym] = _display_name(row["name"])
        if row and row["industry"]:
            state.setdefault("industries", {})[sym] = row["industry"]
    _repo().save_state(session_id, s.current_date, state["cash"], state)
    out = _exam_view(s)
    out["failed"] = failed
    return responses.success(out)


def _advance_exam(s: ReplaySession, step: str):
    if s.status != "active":
        return responses.fail("会话已揭晓")
    state = s.state
    if state.get("travel_complete"):
        return responses.fail("旅程已走完，请揭晓复盘")
    day = s.current_date
    day_str = day.isoformat()
    seed = str(s.id)
    pool = state.get("pool") or []
    bars = _day_bars(pool + list(INDEX_SYMBOLS), day)
    segs_all = _segs_of(s.id,
                        {sym: b for sym, b in bars.items() if sym in pool},
                        day_str)
    prev_closes = _prev_closes(pool, day)
    names = state.get("names") or {}
    fills: list[dict] = []
    events: list[dict] = []

    segs_left = SEG_COUNT - 1 - state.get("seg_idx", 0)
    walk = segs_left if step == "day" else min(1, segs_left)
    for _k in range(walk):
        state["seg_idx"] = state["seg_idx"] + 1
        seg_now = {sym: segs_all[sym][state["seg_idx"]]
                   for sym in segs_all}
        t, ev = _engine.check_pending(state, seg_now, prev_closes, names,
                                      day_str)
        fills += t
        events += ev

    if (step == "day") or segs_left == 0:  # 日切(尾盘后按段=收摊走人)
        events += _engine.cancel_day_pending(state)
        close_map = {sym: bars[sym]["close"]
                     for sym in pool if sym in bars}
        for sym in pool:  # 停牌用最近收盘价
            if sym not in close_map and sym in prev_closes:
                close_map[sym] = prev_closes[sym]
        _engine.day_close_nav(state, day_str, close_map)
        if step == "day":
            state["skipped_days"] = state.get("skipped_days", 0) + 1
        if state.get("day_ordinal", 1) >= state.get("length_days", 1):
            state["travel_complete"] = True
        else:
            nxt = _next_trading_day(day + timedelta(days=1))
            if nxt is None:
                state["travel_complete"] = True
            else:
                divs = _dividends_for(pool, nxt)
                events += _engine.apply_dividends(state, divs,
                                                  nxt.isoformat())
                day = nxt
                state["seg_idx"] = 0
                state["day_ordinal"] = state.get("day_ordinal", 1) + 1
    # v3 单事务落库(spec §6):fills 与 state 同一事务写入,拆两笔时
    # 中途崩溃会错账(状态推进了但成交丢失,或反之)
    _repo().save_state_with_trades(
        s.id, day, state["cash"], state,
        [_trade_model(s.id, t) for t in fills])
    s.current_date = day  # 内存对象同步(_exam_view 用)
    return responses.success(_exam_view(s, fills=fills, events=events))


def place_order(session_id: int, body: dict):
    """下单端点:市价按当前段价±滑点即时成交,限价入挂单簿冻结。

    下单理由(note)必填 1~140 字——拟真考核的强制复盘纪律,服务端校验。
    """
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") != "exam":
        return responses.fail("仅拟真会话使用下单端点")
    if s.status != "active":
        return responses.fail("会话已揭晓，不能交易")
    state = s.state
    if state.get("travel_complete"):
        return responses.fail("旅程已走完，请揭晓复盘")
    symbol = str(body.get("symbol") or "").lower()
    if symbol not in (state.get("pool") or []):
        return responses.fail("标的不在池内")
    side = body.get("side")
    if side not in ("buy", "sell"):
        return responses.fail("side 应为 buy|sell")
    order_type = body.get("order_type") or "market"
    if order_type not in ("market", "limit"):
        return responses.fail("order_type 应为 market|limit")
    shares = body.get("shares")
    if not isinstance(shares, int) or shares <= 0:
        return responses.fail("shares 应为正整数")
    note = (body.get("note") or "").strip()
    if not (1 <= len(note) <= 140):
        return responses.fail("下单理由必填（1~140 字）")
    confidence = body.get("confidence")
    if confidence is not None and confidence not in (1, 2, 3, 4, 5):
        return responses.fail("confidence 应为 1~5")
    day = s.current_date
    day_str = day.isoformat()
    bars = _day_bars([symbol], day)
    if symbol not in bars:
        return responses.fail("当日停牌，无法交易")
    prev = _prev_closes([symbol], day).get(symbol)
    if prev is None:
        return responses.fail("缺前收盘数据")
    names = state.get("names") or {}
    order = {"symbol": symbol, "side": side, "shares": shares,
             "note": note, "confidence": confidence,
             "order_type": order_type}
    if order_type == "market":
        # 市卖先校验可卖股数(持仓−挂单冻结),再谈成交
        if side == "sell" and shares > _engine.sellable_shares(
                state, symbol, day_str):
            return responses.fail("持仓不足（含挂单冻结）")
        segs = _segments(symbol, day_str, bars[symbol], seed=str(s.id))
        seg_price = segs[state.get("seg_idx", 0)]["close"]
        slip = _engine.slippage(
            f"{s.id}:{symbol}:{day_str}:{state.get('seg_idx', 0)}:{side}")
        px = seg_price * (1 + slip if side == "buy" else 1 - slip)
        # 有效现金 = 现金 − 挂单冻结(买单不能动用挂单冻结额)
        cash_avail = state["cash"] - state.get("frozen_cash", 0.0)
        r = _engine.try_fill_market(cash_avail, state.get("positions") or [],
                                    order, px, prev, names.get(symbol),
                                    day_str)
        if not r["ok"]:
            return responses.fail(r["error"])
        state["cash"] = r["cash"]
        state["positions"] = r["positions"]
        # 单事务落库(spec §6):成交与 state 同事务,防崩错账
        _repo().save_state_with_trades(s.id, day, state["cash"], state,
                                       [_trade_model(s.id, r["trade"])])
        return responses.success({
            "status": "filled", "trade": r["trade"],
            "cash": state["cash"], "positions": state["positions"],
            "pending": state.get("pending_orders") or [],
            "frozen_cash": state.get("frozen_cash", 0.0)})
    # 限价单:校验区间/资金/可卖后入挂单簿,冻结额走引擎统一公式
    order["limit_price"] = body.get("limit_price")
    r = _engine.try_place_limit(state, order, prev, names.get(symbol),
                                day_str)
    if not r["ok"]:
        return responses.fail(r["error"])
    _repo().save_state(s.id, day, state["cash"], state)
    return responses.success({
        "status": "pending", "order": r["order"],
        "cash": state["cash"], "positions": state.get("positions") or [],
        "pending": state.get("pending_orders") or [],
        "frozen_cash": state.get("frozen_cash", 0.0)})


# ── v3 揭晓评分 / 拟真榜（Task 11） ──


def leaderboard():
    rows = []
    for s in _repo().list():
        if (s.mode or "free") != "exam" or s.status != "revealed":
            continue
        sc = (s.state or {}).get("score")
        if not sc:
            continue
        nav = (s.state or {}).get("nav") or []
        rows.append({
            "id": s.id, "name": s.name, "score": sc.get("total"),
            "excess_score": sc.get("excess_score"),
            "turnover_score": sc.get("turnover_score"),
            "annual_excess_pct": sc.get("annual_excess_pct"),
            "annual_turnover": sc.get("annual_turnover"),
            "days": len(nav), "initial_capital": s.initial_capital,
            "final": nav[-1]["value"] if nav else None,
        })
    rows.sort(key=lambda r: r["score"] or 0, reverse=True)
    return responses.success(rows[:50])


def training_log():
    """拟真训练册：全部已揭晓 exam 旅程的成交（含强制理由+信心度）。

    下单理由此前只在单旅程复盘页可见、随会话删除即散——此端点把
    跨旅程的理由沉淀成可翻阅的训练记录,是判断训练复利的原料。
    """
    repo = _repo()
    sessions = []
    trades = []
    for s in repo.list():
        if (s.mode or "free") != "exam" or s.status != "revealed":
            continue
        sc = (s.state or {}).get("score") or {}
        nav = (s.state or {}).get("nav") or []
        sessions.append({
            "id": s.id, "name": s.name,
            "score": sc.get("total"),
            "annual_excess_pct": sc.get("annual_excess_pct"),
            "days": len(nav),
            "final": nav[-1]["value"] if nav else None,
            "trade_count": 0,
        })
        for t in repo.list_trades(s.id):
            row = _trade_dict(t)
            row["session_name"] = s.name
            trades.append(row)
    count_by_id = {}
    for t in trades:
        count_by_id[t["session_id"]] = (
            count_by_id.get(t["session_id"], 0) + 1)
    for sess in sessions:
        sess["trade_count"] = count_by_id.get(sess["id"], 0)
    trades.sort(key=lambda t: (t["session_id"], t["trade_date"], t["id"]),
                reverse=True)
    return responses.success({"sessions": sessions, "trades": trades})
