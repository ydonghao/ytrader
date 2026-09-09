"""
Market Data API Router
====================
从 TimescaleDB 读取真实 K 线数据
"""
import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/market", tags=["market"])

from src.infra.database.sql_engine.dsn import get_dsn


# ── 请求/响应模型 ───────────────────────────────────────────────────
class KLineBar(BaseModel):
    symbol: str
    trade_date: str
    open_: float
    close_: float
    high_: float
    low_: float
    volume: float
    amount: float


class KLineResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    interval: str
    total: int
    bars: list[KLineBar]


# ── DB 读取 ────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(get_dsn())


def _resolve_kline_table(symbol: str, interval: str) -> tuple[str, str, bool]:
    """按 symbol 格式 + interval 决定查哪张表。
    返回 (table, time_col, has_interval_col)。日线按 symbol 分派到对应资产表。"""
    s = symbol.upper() if isinstance(symbol, str) else ""
    if interval != "1d":
        return ("stock_ohlcv_minute", "trade_time", True)
    # 日线: 按 symbol 格式分派资产表
    if s.startswith("SW"):
        return ("index_ohlcv", "trade_date", False)
    if s.startswith(("SH000", "SZ399", "SH899")):
        return ("index_ohlcv", "trade_date", False)
    if s in {"XAU", "XAG", "XPT", "XPD", "GC", "SI", "OIL", "CL", "NG"}:
        return ("commodity_ohlcv", "trade_date", False)
    if len(s) == 6 and s.isalpha():
        return ("fx_rate", "date", False)
    return ("stock_ohlcv", "trade_date", False)


def fetch_kline(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interval: str = "1d",
    limit: int = 3000,
) -> list[dict]:
    """从 TimescaleDB 读取 K 线。按 symbol 格式自动分派到
    stock_ohlcv / stock_ohlcv_minute / index_ohlcv / commodity_ohlcv / fx_rate。"""
    table, time_col, has_interval_col = _resolve_kline_table(symbol, interval)

    conn = get_conn()
    is_daily = interval == "1d"
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if start_date and end_date:
                if has_interval_col:
                    cur.execute(
                        f"""
                        SELECT symbol,
                               {time_col}::date as trade_date,
                               open_, close_, high_, low_, volume, amount
                        FROM "{table}"
                        WHERE symbol = %s
                          AND {time_col}::date >= %s
                          AND {time_col}::date <= %s
                          AND interval = %s
                        ORDER BY {time_col} ASC
                        LIMIT %s
                        """,
                        (symbol, start_date, end_date, interval, limit),
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT symbol,
                               {time_col}::date as trade_date,
                               open_, close_, high_, low_, volume, amount
                        FROM "{table}"
                        WHERE symbol = %s
                          AND {time_col}::date >= %s
                          AND {time_col}::date <= %s
                        ORDER BY {time_col} ASC
                        LIMIT %s
                        """,
                        (symbol, start_date, end_date, limit),
                    )
            elif start_date:
                if has_interval_col:
                    cur.execute(
                        f"""
                        SELECT symbol,
                               {time_col}::date as trade_date,
                               open_, close_, high_, low_, volume, amount
                        FROM "{table}"
                        WHERE symbol = %s
                          AND {time_col}::date >= %s
                          AND interval = %s
                        ORDER BY {time_col} ASC
                        LIMIT %s
                        """,
                        (symbol, start_date, interval, limit),
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT symbol,
                               {time_col}::date as trade_date,
                               open_, close_, high_, low_, volume, amount
                        FROM "{table}"
                        WHERE symbol = %s
                          AND {time_col}::date >= %s
                        ORDER BY {time_col} ASC
                        LIMIT %s
                        """,
                        (symbol, start_date, limit),
                    )
            elif end_date:
                if has_interval_col:
                    cur.execute(
                        f"""
                        SELECT symbol,
                               {time_col}::date as trade_date,
                               open_, close_, high_, low_, volume, amount
                        FROM "{table}"
                        WHERE symbol = %s
                          AND {time_col}::date <= %s
                          AND interval = %s
                        ORDER BY {time_col} DESC
                        LIMIT %s
                        """,
                        (symbol, end_date, interval, limit),
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT symbol,
                               {time_col}::date as trade_date,
                               open_, close_, high_, low_, volume, amount
                        FROM "{table}"
                        WHERE symbol = %s
                          AND {time_col}::date <= %s
                        ORDER BY {time_col} DESC
                        LIMIT %s
                        """,
                        (symbol, end_date, limit),
                    )
            else:
                if has_interval_col:
                    cur.execute(
                        f"""
                        SELECT symbol,
                               {time_col}::date as trade_date,
                               open_, close_, high_, low_, volume, amount
                        FROM "{table}"
                        WHERE symbol = %s AND interval = %s
                        ORDER BY {time_col} DESC
                        LIMIT %s
                        """,
                        (symbol, interval, limit),
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT symbol,
                               {time_col}::date as trade_date,
                               open_, close_, high_, low_, volume, amount
                        FROM "{table}"
                        WHERE symbol = %s
                        ORDER BY {time_col} DESC
                        LIMIT %s
                        """,
                        (symbol, limit),
                    )
            rows = cur.fetchall()
            # 升序返回
            rows.reverse()
            return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 指数搜索维度（并入 /market/search）──────────────────────────────
# stock_info 只有股票/ETF；指数并入搜索可见范围，否则中证500/1000 等
# 指数本身搜不到（只能搜到跟踪它的 ETF）。清单取 conf quant_universe.indices
# （与指数PE/成分配置同源），且只暴露 index_ohlcv 实际有行情的 symbol，
# 避免搜到无 K 线数据的空指数（如中证800/中证2000 未同步行情）。
_INDEX_SEARCH_CACHE: dict = {"ts": 0.0, "items": []}
_INDEX_SEARCH_TTL = 600  # 秒；指数清单基本静态，进程内缓存即可

# 同花顺/通达信风格指数代码 → 站内代码（1=沪市 1A=上证系列 1B=中证系列，
# 规则 1B+站内代码后4位）。外部行情软件复制的代码可直接命中。
_INDEX_CODE_ALIASES: dict[str, str] = {
    "1a0001": "sh000001",
    "1b0300": "sh000300",
    "1b0016": "sh000016",
    "1b0905": "sh000905",
    "1b0852": "sh000852",
    "1b0903": "sh000903",
    "1b0010": "sh000010",
    "1b0015": "sh000015",
    "1b0688": "sh000688",
    "1b0985": "sh000985",
}


def _load_index_search_items(cur) -> list[dict]:
    """[{symbol, name}] — 配置指数 ∩ index_ohlcv 有数据（TTL 缓存）。"""
    now = time.time()
    if (_INDEX_SEARCH_CACHE["items"]
            and now - _INDEX_SEARCH_CACHE["ts"] < _INDEX_SEARCH_TTL):
        return _INDEX_SEARCH_CACHE["items"]
    from conf import app_config  # 局部导入，避免模块加载次序依赖

    configured = [
        {"symbol": it.symbol.lower(), "name": it.name}
        for it in app_config.quant_universe.indices
    ]
    cur.execute(
        "SELECT DISTINCT symbol FROM index_ohlcv WHERE symbol = ANY(%s)",
        ([it["symbol"] for it in configured],),
    )
    with_data = {r["symbol"].lower() for r in cur.fetchall()}
    items = [it for it in configured if it["symbol"] in with_data]
    _INDEX_SEARCH_CACHE["ts"] = now
    _INDEX_SEARCH_CACHE["items"] = items
    return items


def _match_index_items(q_lower: str, items: list[dict]) -> list[dict]:
    """按与股票一致的优先级匹配指数：0=别名命中/代码前缀，1=代码包含，2=名称包含。"""
    alias_symbol = _INDEX_CODE_ALIASES.get(q_lower)
    hits = []
    for it in items:
        sym = it["symbol"]
        if sym == alias_symbol or sym.startswith(q_lower):
            priority = 0
        elif q_lower in sym:
            priority = 1
        elif q_lower in it["name"].lower():
            priority = 2
        else:
            continue
        hits.append({
            "symbol": sym, "name": it["name"], "market": "A",
            "list_date": None, "priority": priority,
        })
    return hits


def search_symbols(q: str, market: str = None, limit: int = 20) -> list[dict]:
    """
    搜索股票/ETF/指数 — 股票与 ETF 查 stock_info 维度表（~1 万行，毫秒级），
    指数并入 conf quant_universe.indices ∩ index_ohlcv 有行情的清单
    （stock_info 无指数行；此前中证500/1000 等指数本身搜不到）。

    历史实现直接扫 stock_ohlcv 事实表（~1750 万行）做 GROUP BY + COUNT(*)，
    单次搜索 ~4s，且每个击键触发一次（前端 debounce 200ms），导致搜索框
    严重卡顿。排序优先级：代码精确前缀/别名 > 代码包含 > 名称包含；
    同优先级按 symbol 排序（sh000905 中证500 排在 sz000905 厦门港务、
    sh510500 系列 ETF 之前）。
    bars 字段为兼容旧响应结构保留，固定为 0。
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            q_stripped = q.strip()
            q_lower = q_stripped.lower()
            like_pattern = f"%{q_lower}%"
            exact_pattern = f"{q_lower}%"

            base_sql = """
                SELECT symbol, market, list_date, COALESCE(name, '') AS name,
                       CASE WHEN lower(symbol) LIKE %(exact)s THEN 0
                            WHEN lower(symbol) LIKE %(like)s THEN 1
                            ELSE 2
                       END AS priority
                FROM stock_info
                WHERE (lower(symbol) LIKE %(like)s OR name LIKE %(like)s)
            """
            params: dict = {"exact": exact_pattern, "like": like_pattern, "limit": limit}
            if market in ("A", "HK"):
                base_sql += " AND market = %(market)s"
                params["market"] = market
            base_sql += " ORDER BY priority, symbol LIMIT %(limit)s"

            cur.execute(base_sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            # 指数维度并入（A 股指数仅在 market=A/不限时可见），排序键与股票一致；
            # 指数清单加载失败时降级为纯股票结果，不影响搜索主链路
            if market in (None, "A"):
                try:
                    idx_hits = _match_index_items(
                        q_lower, _load_index_search_items(cur))
                    rows = sorted(rows + idx_hits,
                                  key=lambda r: (r["priority"], r["symbol"]))
                except Exception:
                    pass
            rows = rows[:limit]
            for r in rows:
                r["bars"] = 0  # 兼容旧响应；逐 symbol 的 bar 统计见 kline/overview 接口
            return rows
    finally:
        conn.close()


def get_overview() -> dict:
    """市场概览（使用预计算表，毫秒级响应）"""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 读预计算的市场统计（由 refresh_market_stats() 更新）
            cur.execute("SELECT market, stocks, bars, earliest, latest FROM market_stats ORDER BY market")
            rows = [dict(r) for r in cur.fetchall()]

            # 分钟线统计（使用预计算表）
            cur.execute("SELECT interval, stocks, bars FROM minute_stats ORDER BY interval")
            minute_stats = [dict(r) for r in cur.fetchall()]

            return {"markets": rows, "minute": minute_stats}
    finally:
        conn.close()


def refresh_market_stats():
    """刷新 market_stats 表（每日一次，由 backfill job 调用）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market_stats (market, stocks, bars, earliest, latest, updated_at)
                SELECT
                    market,
                    COUNT(DISTINCT symbol)::INT,
                    COUNT(*)::BIGINT,
                    MIN(trade_date)::DATE,
                    MAX(trade_date)::DATE,
                    NOW()
                FROM stock_ohlcv
                GROUP BY market
                ON CONFLICT (market) DO UPDATE SET
                    stocks = EXCLUDED.stocks,
                    bars = EXCLUDED.bars,
                    earliest = EXCLUDED.earliest,
                    latest = EXCLUDED.latest,
                    updated_at = EXCLUDED.updated_at
            """)
            # 同时刷新分钟线统计
            cur.execute("""
                INSERT INTO minute_stats (interval, stocks, bars, updated_at)
                SELECT interval, COUNT(DISTINCT symbol)::INT, COUNT(*)::BIGINT, NOW()
                FROM stock_ohlcv_minute
                GROUP BY interval
                ON CONFLICT (interval) DO UPDATE SET
                    stocks = EXCLUDED.stocks,
                    bars = EXCLUDED.bars,
                    updated_at = EXCLUDED.updated_at
            """)
        conn.commit()
    finally:
        conn.close()


# ── API 端点 ─────────────────────────────────────────────────────

@router.get("/overview")
def market_overview():
    """市场概览"""
    try:
        data = get_overview()
        return {"code": 0, "msg": "ok", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh-stats")
def refresh_stats():
    """手动刷新 market_stats 预计算表（日常由 backfill job 自动调用）"""
    try:
        refresh_market_stats()
        return {"code": 0, "msg": "ok", "data": {"updated_at": "just now"}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kline/{symbol}")
def kline(
    symbol: str,
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    interval: str = Query("1d", description="K线周期：1d/5m/15m/30m/60m"),
    limit: int = Query(3000, description="最大bar数量"),
):
    """
    获取 K 线数据（从 TimescaleDB）

    支持日线和分钟级（分钟级需先完成回填）
    """
    try:
        bars = fetch_kline(symbol, start, end, interval, limit)
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "symbol": symbol,
                "interval": interval,
                "total": len(bars),
                "bars": [
                    {
                        "trade_date": str(b["trade_date"]),
                        "open": b["open_"],
                        "close": b["close_"],
                        "high": b["high_"],
                        "low": b["low_"],
                        "volume": b["volume"],
                        "amount": b.get("amount", 0),
                    }
                    for b in bars
                ],
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 分时成交缓存 ─────────────────────────────────────────────────
# AkShare 外部拉取 ~2.5s 且每次切换 symbol 都触发；60s TTL 内存缓存
# 让重复查看/切回同一标的时瞬时返回。分钟级数据 60s 延迟可接受。
_TRADES_CACHE_TTL = 60
_trades_cache: dict = {}


@router.get("/trades/{symbol}")
def trades(
    symbol: str,
    limit: int = Query(500, description="最大成交数"),
):
    """
    分时成交 — 从 AkShare 获取 1 分钟 K 线数据，转换为逐笔成交展示。

    每根 1 分钟 K 线被转换为一个合成成交记录（close=成交价，volume=成交量）。
    AkShare 返回所有可用历史数据（最近 ~40 个交易日）。
    要看真实逐笔成交需要 Level2 行情数据（付费）。
    """
    import time as _time

    cache_key = (symbol, limit)
    cached = _trades_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _TRADES_CACHE_TTL:
        return cached["payload"]

    import akshare as ak
    import pandas as pd

    try:
        df = ak.stock_zh_a_minute(
            symbol=symbol,
            period="1",
            adjust="qfq",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AkShare fetch failed: {e}")

    if df is None or df.empty:
        return {
            "code": 0,
            "msg": "ok",
            "data": {"symbol": symbol, "trades": []},
        }

    df = df.sort_values("day", ascending=True).tail(limit)
    # AkShare 返回的数据可能含 NaN 行（未成交时段/脏数据），直接丢弃，
    # 否则 int(float(NaN)) 会抛 ValueError 导致整个接口 500
    df = df.dropna(subset=["close", "volume"])

    trades_list = []
    for _, row in df.iterrows():
        ts = int(pd.Timestamp(row["day"], tz="Asia/Shanghai").timestamp() * 1000)
        trades_list.append({
            "id": f"{symbol}-{ts}-{int(float(row['close']) * 100)}",
            "symbol": symbol,
            "side": "BUY",
            "price": float(row["close"]),
            "quantity": float(row["volume"]),
            "timestamp": ts,
            "isBuyerMaker": False,
        })

    payload = {
        "code": 0,
        "msg": "ok",
        "data": {
            "symbol": symbol,
            "total": len(trades_list),
            "trades": trades_list,
        },
    }
    import time as _time

    _trades_cache[cache_key] = {"ts": _time.time(), "payload": payload}
    # 防止缓存无限增长：超过 200 个键时清空（标的数量有限，简单重建即可）
    if len(_trades_cache) > 200:
        _trades_cache.clear()
        _trades_cache[cache_key] = {"ts": _time.time(), "payload": payload}
    return payload

@router.get("/search")
def search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    market: Optional[str] = Query(None, description="市场：A/HK"),
    limit: int = Query(20),
):
    """搜索股票/ETF/指数代码（指数并入 quant_universe.indices 清单）"""
    try:
        results = search_symbols(q, market, limit)
        return {
            "code": 0,
            "msg": "ok",
            "data": [
                {
                    "symbol": r["symbol"],
                    "name": r.get("name") or "",
                    "market": r["market"],
                    "list_date": str(r["list_date"]) if r.get("list_date") else "",
                    "bars": r["bars"],
                }
                for r in results
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/symbols")
def symbol_list(
    market: str = Query("A", description="市场：A/HK"),
    limit: int = Query(100, le=5000),
):
    """获取股票列表"""
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT symbol, market,
                       MIN(trade_date::date) as first_date,
                       MAX(trade_date::date) as last_date,
                       COUNT(*) as bars
                FROM stock_ohlcv
                WHERE market = %s
                GROUP BY symbol, market
                ORDER BY symbol
                LIMIT %s
                """,
                (market, limit),
            )
            rows = [
                {
                    "symbol": r["symbol"],
                    "market": r["market"],
                    "first_date": str(r["first_date"]),
                    "last_date": str(r["last_date"]),
                    "bars": r["bars"],
                }
                for r in cur.fetchall()
            ]
            conn.close()
            return {"code": 0, "msg": "ok", "data": rows, "total": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 批量报价(自选股等复用) ───────────────────────────────────────

_QUOTES_OHLCV_SQL = """
    WITH ranked AS (
        SELECT symbol, close_, trade_date,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn
        FROM stock_ohlcv
        WHERE symbol = ANY(%s) AND trade_date >= current_date - interval '40 days'
    )
    SELECT t.symbol, t.close_, p.close_ AS prev,
           COALESCE(i.name, t.symbol) AS name
    FROM ranked t
    LEFT JOIN ranked p ON p.symbol = t.symbol AND p.rn = 2
    LEFT JOIN stock_info i ON i.symbol = t.symbol
    WHERE t.rn = 1
"""

_QUOTES_VAL_SQL = """
    WITH ranked AS (
        SELECT symbol, pe, pe_ttm, pb, dv_ratio, dv_ttm, total_mv,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn
        FROM stock_valuation
        WHERE symbol = ANY(%s)
    )
    SELECT symbol, pe, pe_ttm, pb, dv_ratio, dv_ttm, total_mv
    FROM ranked WHERE rn = 1
"""


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


@router.post("/quotes")
def batch_quotes(body: dict):
    """批量查询多个 symbol 的最新行情 + 估值。

    body: {"symbols": ["sh600519", ...]}
    缺失数据返回 null; 无行情的 symbol 从结果略过。
    """
    symbols = body.get("symbols") or []
    if not isinstance(symbols, list) or not symbols:
        return {"code": 0, "msg": "ok", "data": []}
    # 去重保序
    seen = set()
    uniq = []
    for s in symbols:
        s = str(s)
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    try:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(_QUOTES_OHLCV_SQL, (uniq,))
                ohlcv = {r["symbol"]: dict(r) for r in cur.fetchall()}
                cur.execute(_QUOTES_VAL_SQL, (uniq,))
                val = {r["symbol"]: dict(r) for r in cur.fetchall()}
            data = []
            for s in uniq:
                o = ohlcv.get(s)
                if not o:
                    continue  # 无行情略过
                close = float(o.get("close_") or 0)
                prev = o.get("prev")
                prev = float(prev) if prev is not None else None
                change = round(close - prev, 4) if prev is not None else None
                # 无前日收盘(如窗口内仅一根K线)时 change_pct 也为 null,
                # 与 change 保持一致, 避免出现"涨跌额—但涨跌幅0.00%"
                change_pct = (
                    round((close / prev - 1) * 100, 2) if prev else None
                )
                v = val.get(s, {})
                data.append(
                    {
                        "symbol": s,
                        "name": o.get("name") or s,
                        "price": close,
                        "change": change,
                        "change_pct": change_pct,
                        "pe": _to_float(v.get("pe")),
                        "pe_ttm": _to_float(v.get("pe_ttm")),
                        "pb": _to_float(v.get("pb")),
                        "dv_ratio": _to_float(v.get("dv_ratio")),
                        "dv_ttm": _to_float(v.get("dv_ttm")),
                        "total_mv": _to_float(v.get("total_mv")),
                    }
                )
            return {"code": 0, "msg": "ok", "data": data}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Market Categories (6 类 Tab 数据源) ──────────────────────────────────────

_INDEX_COMMO_NAME = {
    "XAU": "伦敦金", "XAG": "伦敦银", "XPT": "伦敦铂", "XPD": "伦敦钯",
    "GC": "COMEX黄金", "SI": "COMEX白银", "OIL": "布伦特原油", "CL": "WTI原油", "NG": "NYMEX天然气",
    "USDCNY": "美元/人民币", "EURCNY": "欧元/人民币", "JPYCNY": "日元/人民币",
    "GBPCNY": "英镑/人民币", "HKDCNY": "港币/人民币",
}


def _latest_sql(table, time_col, where="", join_name=None, order=None, limit=None, recent_days=None):
    """每个 symbol 最新 close + 上一交易日 close(prev), 用两次 ROW_NUMBER 自连接。

    recent_days: 只在近 N 天内做窗口排序，避免对全历史排序——仅对大表(如
    stock_ohlcv 1740万行)的调用方按需传入(如 30)；默认 None 不裁剪(向后兼容，
    小表如 index/commodity/fx 全历史也仅几十 ms)。
    """
    name_sel = ", COALESCE(i.name, t.symbol) AS name" if join_name else ""
    name_join = "LEFT JOIN {} i ON i.symbol = t.symbol".format(join_name) if join_name else ""
    order_sql = "ORDER BY {}".format(order) if order else "ORDER BY t.symbol"
    limit_sql = "LIMIT {}".format(limit) if limit else ""
    # 日期下界：只对近期数据做窗口排序，避免对整张历史表（如 stock_ohlcv 1740万行）全表扫描排序
    date_pred = f"{time_col} >= current_date - interval '{recent_days} days'" if recent_days else ""
    if not where.strip():
        wh_final = f"WHERE {date_pred}" if date_pred else ""
    else:
        wh_final = f"{where} AND {date_pred}" if date_pred else where
    return """
        WITH ranked AS (
            SELECT symbol, close_, {tc},
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY {tc} DESC) AS rn
            FROM {tbl} {wh}
        )
        SELECT t.symbol, t.close_, p.close_ AS prev{ns}
        FROM ranked t
        LEFT JOIN ranked p ON p.symbol = t.symbol AND p.rn = 2
        {nj}
        WHERE t.rn = 1
        {ord} {lim}
    """.format(tc=time_col, tbl=table, wh=wh_final, ns=name_sel, nj=name_join, ord=order_sql, lim=limit_sql)


def _range_sql(table, time_col, start, end, where=""):
    """区间涨跌幅 SQL：close = ≤end 最新一条，prev = <start 最新一条。

    与 _latest_sql 同风格（ROW_NUMBER 窗口），区别在端点取值：
    - close 端点：trade_date <= end（end 缺省时不约束 = 取最新）
    - prev  端点：trade_date <  start（start 缺省时取最早一条作为基准）

    日期用 psycopg 参数化（%s），绝不字符串拼接用户输入。
    返回 (sql, params) 二元组：sql 用 %s 占位，params 按出现顺序排列。
    where 形如 "market='INDEX'"，可带或不带前导 "WHERE"（本函数负责剥离并重新拼接）。
    """
    where = where.strip()
    # 调用方可能传 "WHERE market='INDEX'" 或 "market='INDEX'"，统一剥掉前导 WHERE
    if where.upper().startswith("WHERE "):
        where = where[6:].strip()

    # ── close 端点子查询 ──
    close_conds = [where] if where else []
    close_params = []
    if end:
        close_conds.append(f"{time_col} <= %s")
        close_params.append(end)
    close_where = (" WHERE " + " AND ".join(c for c in close_conds if c)) if close_conds else ""
    close_sub = (
        f"SELECT symbol, close_, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY {time_col} DESC) AS rn "
        f"FROM {table}{close_where}"
    )

    # ── prev 端点子查询 ──
    prev_conds = [where] if where else []
    prev_params = []
    if start:
        prev_conds.append(f"{time_col} < %s")
        prev_params.append(start)
    prev_where = (" WHERE " + " AND ".join(c for c in prev_conds if c)) if prev_conds else ""
    # start 缺省时取最早一条（rn 按 ASC，取 rn=1）；有 start 时取 <start 的最新（DESC，取 rn=1）
    prev_order = "ASC" if not start else "DESC"
    prev_sub = (
        f"SELECT symbol, close_, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY {time_col} {prev_order}) AS rn "
        f"FROM {table}{prev_where}"
    )

    sql = f"""
        WITH close_end AS ({close_sub}),
             prev_base AS ({prev_sub})
        SELECT c.symbol, c.close_, p.close_ AS prev
        FROM close_end c
        LEFT JOIN prev_base p ON p.symbol = c.symbol AND p.rn = 1
        WHERE c.rn = 1
        ORDER BY c.symbol
    """
    params = close_params + prev_params
    return sql, params


def _pack_row(d, name):
    close = float(d.get("close_") or 0)
    prev = d.get("prev")
    prev = float(prev) if prev is not None else None
    return {
        "symbol": d.get("symbol"),
        "name": name or d.get("symbol"),
        "close": close,
        "change_pct": round((close / prev - 1) * 100, 2) if prev else 0.0,
    }


# ── 分类行情（按分类 TTL 缓存 + 按 Tab 懒加载）─────────────────────────────────

# 分类 key 清单（stock 走前端搜索，不在此预取数据）
_CATEGORY_KEYS = ["market_index", "sw_index", "etf", "hk", "commodity_fx"]

# 按分类 TTL 缓存：行情分类数据日级更新，120s 内复用，重复请求 <10ms。
_CAT_CACHE: dict[str, tuple[list, float]] = {}
_CAT_TTL = 120  # 秒


def _compute_category(cat: str) -> list:
    """取单个分类的最新收盘 + 日涨跌幅列表。

    复用 _latest_sql（自带近14天日期裁剪，避免对全历史窗口排序）。
    """
    from conf import app_config
    qu = app_config.quant_universe
    idx_names = {i.symbol: i.name for i in qu.indices}
    sw_names = {i.symbol: i.name for i in qu.sw_industries}

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if cat == "market_index":
                cur.execute(_latest_sql("index_ohlcv", "trade_date", "WHERE market='INDEX'"))
                return [_pack_row(dict(r), idx_names.get(dict(r)["symbol"], dict(r)["symbol"])) for r in cur.fetchall()]

            if cat == "sw_index":
                cur.execute(_latest_sql("index_ohlcv", "trade_date", "WHERE market='SW'"))
                out = []
                for r in cur.fetchall():
                    d = dict(r); sym = d["symbol"]
                    key = sym[2:] if sym.lower().startswith("sw") else sym
                    out.append(_pack_row(d, sw_names.get(key, sym)))
                return out

            if cat == "etf":
                # stock_ohlcv 1740万行：裁剪到近30天，避免全历史窗口排序（4376ms→~190ms）
                cur.execute(_latest_sql("stock_ohlcv", "trade_date",
                                        "WHERE market='A' AND symbol ~ '^(sh5|sz159)'", "stock_info",
                                        recent_days=30))
                return [_pack_row(dict(r), dict(r).get("name")) for r in cur.fetchall()]

            if cat == "hk":
                # 港股按收盘价取前 200（stock_ohlcv 裁剪到近30天，6701ms→~110ms）
                cur.execute(_latest_sql("stock_ohlcv", "trade_date",
                                        "WHERE market='HK'", "stock_info",
                                        order="t.close_ DESC", limit=200, recent_days=30))
                return [_pack_row(dict(r), dict(r).get("name")) for r in cur.fetchall()]

            if cat == "commodity_fx":
                # 商品
                cur.execute(_latest_sql("commodity_ohlcv", "trade_date"))
                rows = [_pack_row(dict(r), _INDEX_COMMO_NAME.get(dict(r)["symbol"], dict(r)["symbol"])) for r in cur.fetchall()]
                # 货币 (fx_rate: pair/rate/date 列名不同, 单独查；表小不裁剪)
                cur.execute("""
                    WITH ranked AS (
                        SELECT pair, rate, ROW_NUMBER() OVER (PARTITION BY pair ORDER BY date DESC) AS rn
                        FROM fx_rate
                    )
                    SELECT t.pair AS symbol, t.rate AS close_, p.rate AS prev
                    FROM ranked t LEFT JOIN ranked p ON p.pair=t.pair AND p.rn=2
                    WHERE t.rn = 1
                """)
                rows += [_pack_row(dict(r), _INDEX_COMMO_NAME.get(dict(r)["symbol"], dict(r)["symbol"])) for r in cur.fetchall()]
                return rows

            return []  # stock 等无预置列表的分类
    finally:
        conn.close()


def _get_category(cat: str) -> list:
    """带 TTL 缓存的分类读取。命中缓存直接返回，否则计算并缓存。

    线程安全：CPython GIL 下 dict 赋值原子，最坏并发各算一次（结果相同）。
    """
    ent = _CAT_CACHE.get(cat)
    if ent and time.time() < ent[1]:
        return ent[0]
    data = _compute_category(cat)
    _CAT_CACHE[cat] = (data, time.time() + _CAT_TTL)
    return data


@router.get("/categories", response_model=dict)
def market_categories(cat: Optional[str] = Query(None, description="只取单个分类，如 market_index/etf/hk 等；为空返回全部")):
    """6 类标的 symbol+name 列表 (含最新收盘+日涨跌幅), 供 Market 页 Tab 渲染。
    分类: market_index / sw_index / etf / stock / hk / commodity_fx。
    ?cat=<key> 只返回该分类（前端按 Tab 懒加载用）；不传返回全部分类。"""
    try:
        if cat:
            return {"code": 0, "msg": "ok", "data": {cat: _get_category(cat)}}
        data = {k: _get_category(k) for k in _CATEGORY_KEYS}
        data["stock"] = []  # 个股走前端搜索，无预置列表
        return {"code": 0, "msg": "ok", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Indices（A 股宽基 + 申万行业，轻量列表端点）─────────────────────────────────

# 今日快照缓存：无参请求（=最新交易日收盘 + 当日涨跌）日级更新，30s 内复用。
# 带 start/end 的区间请求不缓存（键维度爆炸，命中率低）。
_INDICES_TODAY_CACHE: dict[str, tuple[dict, float]] = {}
_INDICES_TODAY_TTL = 30  # 秒


def _compute_indices_today() -> dict:
    """无参路径：最新收盘 + 当日涨跌幅。recent_days=14 裁剪窗口排序范围
    （只需最近 2 个交易日即可取 latest+prev，给两周余量应对节假日停牌）。
    """
    from conf import app_config
    qu = app_config.quant_universe
    idx_names = {i.symbol: i.name for i in qu.indices}
    sw_names = {i.symbol: i.name for i in qu.sw_industries}

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 宽基指数（market='INDEX'）— recent_days=14 避免对 137 万行全历史排序
            cur.execute(_latest_sql("index_ohlcv", "trade_date",
                                    "WHERE market='INDEX'", recent_days=14))
            market_idx = [_pack_row(dict(r), idx_names.get(dict(r)["symbol"], dict(r)["symbol"]))
                          for r in cur.fetchall()]
            # 申万行业指数（symbol sw801010，去前缀查名）
            cur.execute(_latest_sql("index_ohlcv", "trade_date",
                                    "WHERE market='SW'", recent_days=14))
            sw_idx = []
            for r in cur.fetchall():
                d = dict(r); sym = d["symbol"]
                key = sym[2:] if sym.lower().startswith("sw") else sym
                sw_idx.append(_pack_row(d, sw_names.get(key, sym)))
    finally:
        conn.close()

    return {"market_index": market_idx, "sw_index": sw_idx}


@router.get("/indices", response_model=dict)
def list_indices(
    start: Optional[date] = Query(None, description="开始日期 YYYY-MM-DD；不传=从历史最早算"),
    end:   Optional[date] = Query(None, description="结束日期 YYYY-MM-DD；不传=最新交易日"),
):
    """所有指数的最新收盘 + 涨跌幅（market='INDEX' 宽基 + market='SW' 申万行业）。

    轻量端点：只查 index_ohlcv 一张表，供 Indices 页首屏。
    K 线走通用 /market/kline/{symbol}（_resolve_kline_table 路由到 index_ohlcv）。

    时间筛选（方案 A 统一范围）：
    - 无参：最新交易日 close + 前一日 close（当日涨跌，现状行为）。走 30s 缓存。
    - 有 start/end：close = ≤end 最新一条，prev = <start 最新一条（区间累计涨跌）。
    日期参数来自 URL，_range_sql 内用 psycopg %s 参数化，绝不字符串拼接。
    """
    # start > end 非法
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start 不能晚于 end")

    try:
        # 日期 → 'YYYY-MM-DD' 字符串（_range_sql 接收字符串）
        s = start.isoformat() if start else None
        e = end.isoformat() if end else None
        use_range = s is not None or e is not None

        # 无参路径：走缓存（今日快照，30s TTL）
        if not use_range:
            ent = _INDICES_TODAY_CACHE.get("today")
            if ent and time.time() < ent[1]:
                return {"code": 0, "msg": "ok", "data": ent[0]}
            data = _compute_indices_today()
            _INDICES_TODAY_CACHE["today"] = (data, time.time() + _INDICES_TODAY_TTL)
            return {"code": 0, "msg": "ok", "data": data}

        # 区间路径：不缓存
        from conf import app_config
        qu = app_config.quant_universe
        idx_names = {i.symbol: i.name for i in qu.indices}
        sw_names = {i.symbol: i.name for i in qu.sw_industries}

        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 宽基指数（market='INDEX'）
                sql, params = _range_sql("index_ohlcv", "trade_date", s, e,
                                         where="WHERE market='INDEX'")
                cur.execute(sql, params)
                market_idx = [_pack_row(dict(r), idx_names.get(dict(r)["symbol"], dict(r)["symbol"]))
                              for r in cur.fetchall()]

                # 申万行业指数（symbol sw801010，去前缀查名）
                sql, params = _range_sql("index_ohlcv", "trade_date", s, e,
                                         where="WHERE market='SW'")
                cur.execute(sql, params)
                sw_idx = []
                for r in cur.fetchall():
                    d = dict(r); sym = d["symbol"]
                    key = sym[2:] if sym.lower().startswith("sw") else sym
                    sw_idx.append(_pack_row(d, sw_names.get(key, sym)))
        finally:
            conn.close()

        return {"code": 0, "msg": "ok", "data": {
            "market_index": market_idx,
            "sw_index": sw_idx,
        }}
    except HTTPException:
        raise  # 校验错误原样抛出
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Market Heatmap ─────────────────────────────────────────────────────────────────

# 热力图 60s TTL 缓存：全市场聚合 + 日级数据，重复请求无需重扫 stock_ohlcv
_HEATMAP_CACHE: dict[int, tuple[dict, float]] = {}
_HEATMAP_TTL = 60  # 秒


@router.get("/heatmap", response_model=dict)
def get_market_heatmap(limit: int = 50):
    """
    市场热力图 — 最新交易日涨跌幅排行
    返回: top_gainers, top_losers, market_breadth (上涨/下跌/平盘家数)
    """
    cached = _HEATMAP_CACHE.get(limit)
    if cached and time.time() - cached[1] < _HEATMAP_TTL:
        return cached[0]
    try:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 取最新有大量数据的交易日（只在近10天内探测：覆盖长假，
                # 且避免对全历史 GROUP BY 全表扫描；同窗内 cnt 最大者=最完整的近端交易日）
                cur.execute("""
                    SELECT trade_date::date as dt, COUNT(DISTINCT symbol) as cnt
                    FROM stock_ohlcv
                    WHERE market = 'A' AND open_ > 0
                      AND trade_date >= current_date - interval '10 days'
                    GROUP BY dt
                    ORDER BY cnt DESC
                    LIMIT 1
                """)
                row = cur.fetchone()
                if not row or not row["dt"]:
                    return {"code": 0, "msg": "ok", "data": None}
                latest_date = str(row["dt"])

                # 取该日全部数据，算涨跌幅 (close vs open)
                cur.execute(f"""
                    SELECT
                        o.symbol,
                        si.name,
                        o.open_,
                        o.close_,
                        o.high_,
                        o.low_,
                        o.volume,
                        ROUND(((o.close_ - o.open_) / NULLIF(o.open_, 0) * 100)::numeric, 2) AS change_pct,
                        ROUND(((o.close_ - o.open_) / NULLIF(o.open_, 0))::numeric, 4) AS change_ratio
                    FROM stock_ohlcv o
                    LEFT JOIN stock_info si ON si.symbol = o.symbol
                    WHERE o.market = 'A'
                      AND o.trade_date::date = %s
                      AND o.open_ > 0
                    ORDER BY change_pct DESC
                """, (latest_date,))
                all_rows = [dict(r) for r in cur.fetchall()]

                # 市场宽度（基于全部数据）
                gainers = [r for r in all_rows if r["change_pct"] and r["change_pct"] > 0]
                losers = [r for r in all_rows if r["change_pct"] and r["change_pct"] < 0]
                flat = [r for r in all_rows if not r["change_pct"] or r["change_pct"] == 0]

                # Top gainers / losers
                sorted_by_pct = sorted(all_rows, key=lambda x: float(x["change_pct"] or 0), reverse=True)
                top_gainers = sorted_by_pct[:limit]
                top_losers = list(reversed(sorted_by_pct))[:limit]

                def serialize_stock(r):
                    return {
                        "symbol": r["symbol"],
                        "name": r["name"] or r["symbol"],
                        "change_pct": float(r["change_pct"]) if r["change_pct"] is not None else 0.0,
                        "close": float(r["close_"]),
                        "volume": float(r["volume"]) if r["volume"] else 0.0,
                    }

                resp = {
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "date": latest_date,
                        "total_stocks": len(all_rows),
                        "gainers": len(gainers),
                        "losers": len(losers),
                        "flat": len(flat),
                        "breadth_pct": round(len(gainers) / max(len(all_rows), 1) * 100, 2),
                        "top_gainers": [serialize_stock(r) for r in top_gainers],
                        "top_losers": [serialize_stock(r) for r in top_losers],
                    },
                }
                _HEATMAP_CACHE[limit] = (resp, time.time())
                return resp
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monthly-heatmap", response_model=dict)
def get_monthly_heatmap(months: int = Query(24, description="Number of months to return")):
    """
    月度市场收益热力图
    ====================
    计算最近 N 个月的市场宽度数据：
    - 每月平均日收益（所有标的的均值）
    - 上涨家数比例（市场宽度）
    - 用于渲染月度热力图
    """
    try:
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        DATE_TRUNC('month', trade_date)::date AS month_start,
                        COUNT(DISTINCT symbol) AS stock_count,
                        AVG(daily_return) AS avg_return_pct,
                        SUM(CASE WHEN daily_return > 0 THEN 1 ELSE 0 END)::float
                            / NULLIF(SUM(CASE WHEN daily_return IS NOT NULL THEN 1 ELSE 0 END), 0) * 100
                            AS gainer_pct
                    FROM (
                        SELECT
                            symbol,
                            trade_date,
                            (close_ - LAG(close_, 1) OVER (PARTITION BY symbol ORDER BY trade_date))
                                / NULLIF(LAG(close_, 1) OVER (PARTITION BY symbol ORDER BY trade_date), 0) * 100
                                AS daily_return
                        FROM stock_ohlcv
                        WHERE trade_date >= CURRENT_DATE - (INTERVAL '1 month' * %s)
                    ) sub
                    WHERE daily_return IS NOT NULL
                    GROUP BY 1
                    ORDER BY 1 ASC
                """, (months,))
                rows = cur.fetchall()

                heatmap_data = []
                for r in rows:
                    month_start = r["month_start"]
                    year = month_start.year
                    month = month_start.month
                    heatmap_data.append({
                        "year": year,
                        "month": month,
                        "month_label": f"{year}-{month:02d}",
                        "avg_return_pct": round(float(r["avg_return_pct"] or 0), 3),
                        "gainer_pct": round(float(r["gainer_pct"] or 50), 1),
                        "stock_count": int(r["stock_count"]),
                    })

                # 补充未来月份（最近 N 个月无数据的月份用 null）
                from datetime import datetime, timezone
                from dateutil.relativedelta import relativedelta
                now = datetime.now(timezone.utc)
                end_month = date(now.year, now.month, 1)
                start_month = date(end_month.year, end_month.month, 1) - relativedelta(months=months - 1)

                complete_months = []
                cur_month = start_month
                while cur_month <= end_month:
                    complete_months.append(cur_month)
                    cur_month += relativedelta(months=1)

                data_by_ym = {(r['year'], r['month']): r for r in heatmap_data}
                full_data = []
                for m in complete_months:
                    key = (m.year, m.month)
                    if key in data_by_ym:
                        full_data.append(data_by_ym[key])
                    else:
                        full_data.append({
                            "year": m.year,
                            "month": m.month,
                            "month_label": f"{m.year}-{m.month:02d}",
                            "avg_return_pct": None,
                            "gainer_pct": None,
                            "stock_count": 0,
                        })

                return {"code": 0, "msg": "ok", "data": full_data}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Sector Scan（行业挖掘：横向对比 31 个申万一级行业的动量/RS/回撤）──────────────

_SECTOR_PERIOD_DAYS = {"1m": 30, "6m": 183, "1y": 365, "3y": 1095}
_SECTOR_BENCHMARK = "sh000300"

# 申万行业名称缓存（level → (name_map, 过期时间)）。行业清单极少变化，
# level=2/3 走 akshare 远程取名（~1.5s），10 分钟缓存避免每次请求都调远程。
_SW_NAME_CACHE: dict[int, tuple[dict, float]] = {}
_SW_NAME_TTL = 600  # 10 分钟


def _get_sw_names(level: int) -> dict[str, str]:
    """取申万行业 symbol→name 映射。

    level=1：本地 config 即有 32 个一级名称，毫秒级，不缓存。
    level=2/3：akshare 远程取名（~1.5s），10 分钟缓存。
    返回 {symbol: name}，symbol 形如 'sw801010'（带 sw 前缀，与 DB 一致）。
    """
    # level=1：本地 config，零延迟
    if level == 1:
        from conf import app_config
        qu = app_config.quant_universe
        return {f"sw{i.symbol}": i.name for i in qu.sw_industries}

    # level=2/3：缓存优先
    ent = _SW_NAME_CACHE.get(level)
    if ent and time.time() < ent[1]:
        return ent[0]

    # akshare 远程取名
    import akshare as ak
    name_map: dict[str, str] = {}
    try:
        info_fn = {2: ak.sw_index_second_info,
                   3: ak.sw_index_third_info}[level]
        info_df = info_fn()
        for _, r in info_df.iterrows():
            code = str(r["行业代码"]).replace(".SI", "")
            nm = str(r["行业名称"]).strip()
            parent = str(r.get("上级行业", "")).strip()
            name_map[f"sw{code}"] = f"{parent}·{nm}" if parent else nm
    except Exception:
        pass  # 取名失败降级用 symbol
    _SW_NAME_CACHE[level] = (name_map, time.time() + _SW_NAME_TTL)
    return name_map


@router.get("/sector-scan", response_model=dict)
def sector_scan(
    period: str = Query("1y", description="统计周期：1m/6m/1y/3y"),
    level: int = Query(1, description="申万行业级别：1/2/3"),
):
    """行业挖掘：对申万行业指数计算近 N 期的区间涨幅、相对强度(RS)、
    动量(60日均线偏离)、最大回撤，并返回归一化收盘序列供前端画对比曲线。

    level=1 一级(31个) / 2 二级(~131个) / 3 三级(~335个)。
    RS 基准为沪深300(sh000300)。动量取末日 close 相对 MA60 的偏离百分比。
    归一化序列把每个行业和基准的 close 折算成"起点=100"，便于横向比较。
    """
    days = _SECTOR_PERIOD_DAYS.get(period)
    if not days:
        raise HTTPException(status_code=400, detail=f"period 仅支持 {list(_SECTOR_PERIOD_DAYS)}")
    if level not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="level 仅支持 1/2/3")

    # 各级别对应的 market 列标记（见 sw_index_backfill_all.py）
    market_mark = {1: "SW", 2: "SW2", 3: "SW3"}[level]

    try:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 从数据库动态取该级别的行业清单（symbol + 名称无 config 依赖）
                # 名称通过 sw_index_*_info 接口拿到，这里直接用 symbol
                cur.execute(
                    "SELECT DISTINCT symbol FROM index_ohlcv WHERE market = %s ORDER BY symbol",
                    (market_mark,),
                )
                sw_symbols = [r["symbol"] for r in cur.fetchall()]
                if not sw_symbols:
                    raise HTTPException(status_code=404,
                                        detail=f"无 level={level} 行业数据，请先回填")

                # 取区间内所有行业 + 基准的日线 close
                # start 向前多取 90 天，确保动量 MA60 有完整窗口
                cur.execute(
                    f"""
                    SELECT symbol, trade_date, close_
                    FROM index_ohlcv
                    WHERE symbol = ANY(%s)
                      AND trade_date >= (%s::date - %s::int)
                    ORDER BY symbol, trade_date
                    """,
                    (sw_symbols + [_SECTOR_BENCHMARK], date.today(), days + 90),
                )
                raw = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        # 取该级别的行业名称：level=1 走本地 config（毫秒级），level=2/3 走 akshare（10min 缓存）
        name_map = _get_sw_names(level)

        # 按 symbol 分组
        from collections import defaultdict
        by_sym = defaultdict(list)
        for r in raw:
            by_sym[r["symbol"]].append((r["trade_date"], float(r["close_"])))

        bench_series = by_sym.get(_SECTOR_BENCHMARK, [])
        if not bench_series:
            raise HTTPException(status_code=500, detail="基准沪深300 无数据")

        # 基准在统计区间(start..end)内的涨幅
        # end = 基准最新交易日
        bench_end = bench_series[-1][0]
        bench_start_target = bench_end  # 用 end 反推 start
        from datetime import timedelta
        start_cutoff = bench_end - timedelta(days=days)
        # 基准区间内数据
        bench_in = [(d, c) for d, c in bench_series if d >= start_cutoff]
        if len(bench_in) < 2:
            raise HTTPException(status_code=500, detail="基准区间数据不足")
        bench_return = (bench_in[-1][1] / bench_in[0][1] - 1) * 100
        # 基准归一化序列（起点=100）
        bench_base = bench_in[0][1]
        bench_norm = [{"date": d.isoformat(), "value": round(c / bench_base * 100, 2)}
                      for d, c in bench_in]

        rows = []
        for sym in sw_symbols:
            series = by_sym.get(sym, [])
            if len(series) < 2:
                continue
            # 区间内数据
            in_range = [(d, c) for d, c in series if d >= start_cutoff]
            if len(in_range) < 2:
                continue
            close_start = in_range[0][1]
            close_end = in_range[-1][1]
            closes = [c for _, c in in_range]

            # 1) 区间涨幅
            return_pct = (close_end / close_start - 1) * 100
            # 2) 相对强度 RS
            rs_pct = return_pct - bench_return
            # 3) 动量：末日 close 相对 MA60 偏离（MA60 用区间内最后 60 个 close）
            ma_window = closes[-60:] if len(closes) >= 60 else closes
            ma60 = sum(ma_window) / len(ma_window) if ma_window else close_end
            momentum = (close_end / ma60 - 1) * 100 if ma60 else 0.0
            # 4) 最大回撤：区间内 (close / 前高 - 1) 的最小值
            peak = closes[0]
            max_dd = 0.0
            for c in closes:
                if c > peak:
                    peak = c
                dd = (c / peak - 1) * 100
                if dd < max_dd:
                    max_dd = dd

            # 归一化序列（起点=100）
            norm = [{"date": d.isoformat(), "value": round(c / close_start * 100, 2)}
                    for d, c in in_range]

            name = name_map.get(sym, sym)
            rows.append({
                "symbol": sym,
                "name": name,
                "close": round(close_end, 2),
                "return_pct": round(return_pct, 2),
                "rs_pct": round(rs_pct, 2),
                "momentum": round(momentum, 2),
                "max_drawdown": round(max_dd, 2),
                "series": norm,
            })

        # 默认按涨幅降序
        rows.sort(key=lambda x: x["return_pct"], reverse=True)

        return {"code": 0, "msg": "ok", "data": {
            "period": period,
            "benchmark": _SECTOR_BENCHMARK,
            "start": start_cutoff.isoformat(),
            "end": bench_end.isoformat(),
            "bench_return": round(bench_return, 2),
            "bench_series": bench_norm,
            "rows": rows,
        }}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Fund Flow（行业资金流：主力净流入排行）──────────────────────────────────────

_FUND_FLOW_CACHE: dict = {"data": None, "ts": 0}
_FUND_FLOW_TTL = 300  # 5 分钟缓存


@router.get("/fund-flow", response_model=dict)
def fund_flow():
    """行业资金流向：90 个东财二级行业的主力资金净流入（亿元）。

    数据源：akshare stock_fund_flow_industry（东财即时）。返回每个行业的
    流入/流出/净额/涨跌幅/领涨股。净额为正=资金涌入，为负=资金撤离。
    5 分钟缓存，避免频繁请求东财。
    """
    now = time.time()
    if _FUND_FLOW_CACHE["data"] and now - _FUND_FLOW_CACHE["ts"] < _FUND_FLOW_TTL:
        return {"code": 0, "msg": "ok", "data": _FUND_FLOW_CACHE["data"]}

    try:
        import akshare as ak
        df = ak.stock_fund_flow_industry(symbol="即时")
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "name": str(r.get("行业", "")).strip(),
                "index_value": float(r.get("行业指数", 0) or 0),
                "change_pct": float(r.get("行业-涨跌幅", 0) or 0),
                "inflow": float(r.get("流入资金", 0) or 0),
                "outflow": float(r.get("流出资金", 0) or 0),
                "net_flow": float(r.get("净额", 0) or 0),
                "company_count": int(r.get("公司家数", 0) or 0),
                "leading_stock": str(r.get("领涨股", "")).strip(),
                "leading_change_pct": float(r.get("领涨股-涨跌幅", 0) or 0),
            })
        # 按净额降序
        rows.sort(key=lambda x: x["net_flow"], reverse=True)
        data = {
            "snapshot": date.today().isoformat(),
            "total_inflow": round(sum(r["inflow"] for r in rows), 2),
            "total_outflow": round(sum(r["outflow"] for r in rows), 2),
            "total_net": round(sum(r["net_flow"] for r in rows), 2),
            "sector_count": len(rows),
            "rows": rows,
        }
        _FUND_FLOW_CACHE["data"] = data
        _FUND_FLOW_CACHE["ts"] = now
        return {"code": 0, "msg": "ok", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



