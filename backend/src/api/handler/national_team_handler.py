"""国家队板块 API handler — 每日 ETF 信号 + 历年季报持仓。

遵循 router → handler → repository 分层，统一 src.pkg.responses 返回。
"""
import datetime as dt
import time
from typing import Any, Optional

from src.pkg import responses


# ── 个股收盘价:从本地 stock_ohlcv 表读(零网络依赖) ─────────────


def _fetch_close_prices(symbol: str, report_dates: list[str]) -> dict[str, float]:
    """为给定的 report_dates 取该股报告期收盘价。
    从本地 stock_ohlcv 表读(项目已回填的个股日线),零网络依赖。
    一次查该股全部日线(走 idx_ohlcv_sym_date 索引),内存二分匹配每个报告期,
    避免逐条查询(N 条报告期 = N 次 SQL 的性能陷阱)。
    返回 {report_date: close}。无数据返回部分或 {}(前端降级)。"""
    if not report_dates or not symbol:
        return {}
    from bisect import bisect_right
    from sqlalchemy import text
    from src.infra.database.sql_engine.engine import create_db_connection
    from src.infra.database.sql_engine.dsn import get_dsn

    prefixed = symbol if symbol[:2] in ("sh", "sz") else (
        f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"
    )
    out: dict[str, float] = {}
    try:
        db = create_db_connection(get_dsn())
        with db.session_scope() as s:
            # 一次取该股全部 (date, close),升序
            rows = s.execute(text(
                "SELECT trade_date, close_ FROM stock_ohlcv "
                "WHERE symbol = :sym AND close_ IS NOT NULL "
                "ORDER BY trade_date"
            ), {"sym": prefixed}).all()
        if not rows:
            return out
        dates = [r[0].date() if hasattr(r[0], "date") else r[0] for r in rows]
        closes = [float(r[1]) for r in rows]
        for rd in report_dates:
            try:
                rd_date = dt.date.fromisoformat(rd[:10])
            except Exception:
                continue
            idx = bisect_right(dates, rd_date) - 1  # <= report_date 的最后交易日
            if idx >= 0:
                out[rd] = round(closes[idx], 2)
        return out
    except Exception:
        return out


# ── 每日 ETF 信号（TTL 内存缓存，按 days 分桶）─────────────────
# 不同 days(20/60/120/...) 各自独立缓存,避免互相污染。
_DAILY_CACHE: dict[int, dict] = {}
_DAILY_TTL = 300  # 5 分钟


def daily_signals(days: int = 20) -> Any:
    """当日核心宽基 ETF 护盘信号 + 近 `days` 日热力。
    days: 热力图交易日窗口(20/60/120/...)。返回
    {as_of, days, summary:{strong,suspect,none}, signals:[...], heatmap:{dates, cells}}。"""
    now = time.time()
    bucket = _DAILY_CACHE.get(days)
    if bucket and bucket["data"] and now - bucket["ts"] < _DAILY_TTL:
        return responses.success(bucket["data"])

    try:
        from src.domain.market.sync.providers.akshare_provider import AkshareProvider
        from src.domain.market.sync.providers.national_team_config import get_watch_etfs

        provider = AkshareProvider()
        etfs = get_watch_etfs()
        signals = []
        # 近 days 日热力:对每只 ETF 取过去 days 个交易日的 strength 序列
        # 统一成 {dates:[...], cells:{etf_code:{date: strength}}} 结构。
        heatmap_dates: list[str] = []
        heatmap_cells: dict[str, dict[str, str]] = {}
        for e in etfs:
            sig = provider.fetch_etf_daily_signal(e["etf_code"], e["index_code"])
            sig["etf_name"] = e["etf_name"]
            signals.append(sig)
            hist = provider.fetch_etf_signal_history(
                e["etf_code"], e["index_code"], days=days
            )
            cell_map = {h["date"]: h["strength"] for h in hist}
            heatmap_cells[e["etf_code"]] = cell_map
            if hist and len(hist) > len(heatmap_dates):
                # 以最近一次拿到的完整日期序列为准(各 ETF 交易日一致)
                heatmap_dates = [h["date"] for h in hist]
        as_of = signals[0].get("as_of_date") if signals else None
        summary = {
            "strong": sum(1 for s in signals if s.get("strength") == "strong"),
            "suspect": sum(1 for s in signals if s.get("strength") == "suspect"),
            "none": sum(1 for s in signals if s.get("strength") == "none"),
            "error": sum(1 for s in signals if s.get("strength") == "error"),
        }
        data = {
            "as_of": as_of,
            "days": days,
            "summary": summary,
            "signals": signals,
            "heatmap_20d": {"dates": heatmap_dates, "cells": heatmap_cells},
        }
        _DAILY_CACHE[days] = {"data": data, "ts": now}
        return responses.success(data)
    except Exception as e:
        # 降级:akshare 取数失败时,若内存里仍有(可能已过期的)该 days 缓存值,
        # 优先返回旧值而非直接报错,保证盘后展示连续性。
        if bucket and bucket.get("data"):
            return responses.success(bucket["data"])
        return responses.fail(f"获取每日信号失败: {e}")


# ── 历年持仓 ──────────────────────────────────────────────────
def _parse_date(s: Optional[str]) -> Optional[dt.date]:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def _parse_categories(category: Optional[str]) -> Optional[list[str]]:
    """category 支持逗号分隔多选(如 'huijin,zhengjin');空/无 → None(不过滤)。
    单个值也兼容,等价于旧的单选 contract。"""
    if not category:
        return None
    cats = [c.strip() for c in category.split(",") if c.strip()]
    return cats or None


def holdings_summary(
    category: Optional[str] = None, from_date: Optional[str] = None,
) -> Any:
    """总市值趋势（按 report_date × holder_category 聚合）。
    category 支持逗号分隔多选(向后兼容单值)。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    series = repo.get_summary_series(
        categories=_parse_categories(category), from_date=_parse_date(from_date)
    )
    return responses.success({"series": series})


def holdings_changes(
    period: str, vs_period: str,
    category: Optional[str] = None, change_type: Optional[str] = None,
) -> Any:
    """季度环比变动明细。period=当期, vs_period=对比期(YYYY-MM-DD)。
    category 支持逗号分隔多选(向后兼容单值)。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    p = _parse_date(period)
    vp = _parse_date(vs_period)
    if not p or not vp:
        return responses.fail("period / vs_period 需为 YYYY-MM-DD")
    repo = create_national_team_repository()
    changes = repo.get_changes(
        period=p, vs_period=vp,
        categories=_parse_categories(category), change_type=change_type,
    )
    return responses.success({"changes": changes, "period": period, "vs_period": vs_period})


def holdings_sector_distribution(from_date: Optional[str] = None) -> Any:
    """行业分布时间序列。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    series = repo.get_sector_distribution(from_date=_parse_date(from_date))
    return responses.success({"series": series})


def holdings_top(period: Optional[str] = None, limit: int = 50, offset: int = 0) -> Any:
    """个股 Top 榜（period=None 取最新报告期），支持分页。返回 rows + total。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    rows = repo.get_top_holdings(period=_parse_date(period), limit=limit, offset=offset)
    total = rows[0].get("_total") if rows else 0
    for r in rows:
        r.pop("_total", None)
    return responses.success({"rows": rows, "period": period, "total": total, "offset": offset})


def holdings_symbol_history(symbol: str) -> Any:
    """单股国家队持仓历史（下钻）+ 叠加该股报告期收盘价。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    rows = repo.get_symbol_history(symbol=symbol)

    # 拉该股前复权日线,为每个 report_date 匹配最近收盘价。
    # 用东方财富 K线裸接口(快),带 8s 超时 + 进程级缓存(同一股二次下钻秒出)。
    # 失败则 close_price 留空,前端降级(只画持仓双线,不画股价线)。
    price_map: dict[str, float] = {}
    if rows:
        price_map = _fetch_close_prices(symbol, [r.get("report_date") for r in rows if r.get("report_date")])

    for r in rows:
        r["close_price"] = price_map.get(r.get("report_date"))
    return responses.success({"symbol": symbol, "history": rows})


def coverage() -> Any:
    """回填进度（前端展示数据覆盖度）。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    return responses.success(repo.get_coverage())


def holdings_search(q: str, limit: int = 20) -> Any:
    """按代码或名称搜索国家队持仓个股(用于下拉联想)。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    rows = repo.search_symbols(q=q, limit=limit)
    return responses.success({"q": q, "rows": rows})


def sector_flow() -> Any:
    """行业资金流向原始数据(行业×季度的持股数+市值),供前端算增减/占比/排行。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    return responses.success(repo.get_sector_flow())


def sector_stocks(sector: str, period: Optional[str] = None) -> Any:
    """某行业在某报告期的国家队持仓个股(供行业下钻)。period=None 取最新。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    rows = repo.get_sector_stocks(sector=sector, period=_parse_date(period))
    return responses.success({"sector": sector, "period": period, "rows": rows})
