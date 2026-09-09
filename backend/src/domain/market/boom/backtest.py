# backend/src/domain/market/boom/backtest.py
"""策略回测:重放「业绩大增(+文本命中)→ T+1 买入持有N月」。

前视守卫:文本信号只取 source_date ≤ announce_date 的命中。
"""
import datetime as dt
from dataclasses import dataclass

from src.domain.market.boom.service import growth_filter


@dataclass(frozen=True)
class SampleEvent:
    symbol: str
    report_date: dt.date
    announce_date: dt.date
    change_pct: float
    # 注:brief 测试断言为 list,故此处存 list(与 Task 14 引擎兼容)
    categories: list[str]
    forecast_type: str


def build_samples(boom_repo, forecast_repo, start_year: int, end_year: int,
                  min_change_pct: float) -> list[SampleEvent]:
    events: list[SampleEvent] = []
    for year in range(start_year, end_year + 1):
        for m in (1, 4, 7, 10):                     # 四个预告窗
            w_start = dt.date(year, m, 1)
            w_end = (dt.date(year, m + 1, 1) - dt.timedelta(days=1)
                     if m < 12 else dt.date(year, 12, 31))
            rows = forecast_repo.get_by_announce_date_range(w_start, w_end)
            pool = growth_filter(rows, min_change_pct)
            if not pool:
                continue
            # 前视守卫:窗口内命中的文本,只承认 source_date ≤ 该股公告日的
            hits = boom_repo.get_hits_as_of([f.symbol for f in pool], w_end)
            by_sym: dict = {}
            for h in hits:
                by_sym.setdefault(h.symbol, []).append(h)
            for f in pool:
                cats = sorted({h.category for h in by_sym.get(f.symbol, [])
                               if h.source_date is not None
                               and h.source_date <= f.announce_date})
                events.append(SampleEvent(
                    f.symbol, f.report_date, f.announce_date,
                    float(f.change_pct or 0), cats, f.forecast_type,
                ))
    return events


def with_text_only(events: list[SampleEvent]) -> list[SampleEvent]:
    return [e for e in events if e.categories]


# ---- Task 14: 回测引擎(可注入价格函数) ----
LIMIT_UP_PCT = 9.7      # 入场开盘较 T 收盘涨幅阈值(近似一字/开盘涨停)


def _months_after(d: dt.date, months: int) -> dt.date:
    y, m = d.year + (d.month - 1 + months) // 12, (d.month - 1 + months) % 12 + 1
    day = min(d.day, [31, 29 if _leap(y) else 28, 31, 30, 31, 30,
                      31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day)


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def run_backtest(events, price_fn, bench_fn, hold_months: int = 3,
                 skip_limit_up: bool = True) -> dict:
    trades: list[dict] = []
    n_skipped = n_no_data = 0
    for e in events:
        bars = price_fn(e.symbol, e.announce_date,
                        _months_after(e.announce_date, hold_months) +
                        dt.timedelta(days=15))        # 出场月多给半月找交易日
        # T 日收盘:取 ≤ T 的最后一根 K 线;无 T 日(及之前)数据则视为无数据
        t_bar = None
        for b in bars:
            if b[0] <= e.announce_date:
                t_bar = b
            else:
                break
        entry = next((b for b in bars if b[0] > e.announce_date), None)
        if t_bar is None or entry is None:
            n_no_data += 1
            continue
        t_close = t_bar[2]
        if skip_limit_up and _pct(entry[1], t_close) >= LIMIT_UP_PCT:
            n_skipped += 1
            continue
        target = _months_after(entry[0], hold_months)
        exits = [b for b in bars if b[0] >= target]
        exit_bar = exits[0] if exits else bars[-1]
        mret = _pct(exit_bar[2], entry[1])
        bbars = bench_fn(entry[0], exit_bar[0])
        bret = _pct(bbars[-1][1], bbars[0][1]) if len(bbars) >= 2 else 0.0
        trades.append({"symbol": e.symbol, "year": entry[0].year,
                       "entry": entry[0], "exit": exit_bar[0],
                       "ret": mret, "bret": bret, "excess": mret - bret,
                       "categories": e.categories})

    def _agg(rows):
        if not rows:
            return {"n": 0, "avg_ret": 0.0, "avg_bench_ret": 0.0,
                    "avg_excess": 0.0, "hit_rate": 0.0}
        return {"n": len(rows),
                "avg_ret": sum(r["ret"] for r in rows) / len(rows),
                "avg_bench_ret": sum(r["bret"] for r in rows) / len(rows),
                "avg_excess": sum(r["excess"] for r in rows) / len(rows),
                "hit_rate": sum(1 for r in rows if r["ret"] > 0) / len(rows)}

    by_year = []
    for y in sorted({t["year"] for t in trades}):
        a = _agg([t for t in trades if t["year"] == y])
        by_year.append({"year": y, **a})
    all_cats = sorted({c for t in trades for c in t["categories"]})
    by_category = []
    for c in all_cats:
        rows = [t for t in trades if c in t["categories"]]
        by_category.append({"category": c, "n": len(rows),
                            "avg_ret": sum(r["ret"] for r in rows) / len(rows),
                            "avg_excess": sum(r["excess"] for r in rows) / len(rows)})
    overall = _agg(trades)
    return {"n_events": len(events), "n_traded": len(trades),
            "n_skipped_limitup": n_skipped, "n_no_data": n_no_data,
            "avg_ret": overall["avg_ret"], "avg_bench_ret": overall["avg_bench_ret"],
            "avg_excess": overall["avg_excess"], "hit_rate": overall["hit_rate"],
            "by_year": by_year, "by_category": by_category}


# ---- Task 15: DB 价格适配器 + 一键回测 ----
def _pg_query(sql: str, params: tuple) -> list[tuple]:
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn

    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def _as_date(v) -> dt.date:
    """DB 驱动可能返回 datetime,统一归一为 date。"""
    return v.date() if isinstance(v, dt.datetime) else v


def make_db_price_fn():
    """stock_ohlcv 适配器:返回 [(trade_date, open, close)] 升序(symbol 带前缀)。"""
    from src.domain.market.boom.service import to_prefixed

    def price_fn(symbol: str, start: dt.date, end: dt.date):
        rows = _pg_query(
            "SELECT trade_date, open_, close_ FROM stock_ohlcv "
            "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
            "ORDER BY trade_date ASC",
            (to_prefixed(symbol), start, end),
        )
        return [(_as_date(r[0]), float(r[1]), float(r[2]))
                for r in rows if r[1] and r[2]]
    return price_fn


def make_db_bench_fn(benchmark: str = "sh000300"):
    """index_ohlcv 适配器:返回 [(date, close)] 升序。"""
    def bench_fn(start: dt.date, end: dt.date):
        rows = _pg_query(
            "SELECT trade_date, close_ FROM index_ohlcv "
            "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
            "ORDER BY trade_date ASC",
            (benchmark, start, end),
        )
        return [(_as_date(r[0]), float(r[1])) for r in rows if r[1]]
    return bench_fn


META_NOTES = {
    "text_leg": "文本腿受 news_articles 历史深度限制,早年样本 categories 可能为空",
    "disclosure_bias": "业绩预告有强制披露门槛(±50%/亏损/扭亏),创业板不强制,样本存在覆盖偏差",
    "survivorship": "退市股无行情时计入 n_no_data 剔除",
}


def run_full_backtest(start_year: int, end_year: int,
                      min_change_pct: float = 50.0, hold_months: int = 3,
                      with_text: bool = False,
                      benchmark: str = "sh000300") -> dict:
    from src.infra.database.market.boom import create_boom_repository
    from src.infra.database.market.financial_full import (
        create_earnings_forecast_repository,
    )

    all_events = build_samples(create_boom_repository(),
                               create_earnings_forecast_repository(),
                               start_year, end_year, min_change_pct)
    events = with_text_only(all_events) if with_text else all_events
    report = run_backtest(events, make_db_price_fn(),
                          make_db_bench_fn(benchmark), hold_months=hold_months)
    report["meta"] = {
        **META_NOTES,
        "start_year": start_year, "end_year": end_year,
        "min_change_pct": min_change_pct, "hold_months": hold_months,
        "with_text": with_text, "benchmark": benchmark,
        "events_dropped_no_text": len(all_events) - len(events),
    }
    return report
