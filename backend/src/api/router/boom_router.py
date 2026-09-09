# backend/src/api/router/boom_router.py
"""财报季景气雷达 API。"""
import datetime as dt
import logging

from fastapi import APIRouter, HTTPException

from src.api.handler import watchlist_handler
from src.domain.market.boom.keywords import CATEGORY_LABELS
from src.domain.market.boom.season import announce_window
from src.domain.market.boom.service import (
    build_default_service, filter_window_hits, to_prefixed,
)
from src.infra.database.market.boom import create_boom_repository

log = logging.getLogger("boom_radar")
router = APIRouter(prefix="/boom", tags=["boom"])

WATCHLIST_GROUP = "财报季雷达"


def _ok(data):
    return {"code": 0, "msg": "ok", "data": data}


def _parse_date(s):
    return dt.date.fromisoformat(s) if s else None


def _parse_date_or_400(s):
    try:
        return _parse_date(s)
    except (TypeError, ValueError):
        raise HTTPException(400, "report_date 必须是 YYYY-MM-DD")


def _handler_json(resp):
    """watchlist handler 返回 JSONResponse,解包为 dict;已是 dict 则原样。"""
    import json as _json
    if isinstance(resp, dict):
        return resp
    body = getattr(resp, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return _json.loads(body)
    return {}


def _candidate_dict(c, hits, preview=5):
    d = {k: getattr(c, k, None) for k in (
        "symbol", "report_date", "forecast_type", "company_name",
        "announce_date", "change_pct", "forecast_type_label", "categories",
        "keyword_count", "news_hit_count", "llm_score", "llm_verdict",
        "llm_summary", "status")}
    d["category_labels"] = [CATEGORY_LABELS.get(x, x) for x in (c.categories or [])]
    shown = hits if preview is None else hits[:preview]  # 下钻全量,列表截断
    d["hits_preview"] = [
        {"keyword": h.keyword, "category": h.category,
         "category_label": CATEGORY_LABELS.get(h.category, h.category),
         "source_type": h.source_type, "source_date": h.source_date,
         "snippet": h.snippet}
        for h in shown
    ]
    return d


def _radar_data(report_date, min_change_pct, categories):
    repo = create_boom_repository()
    season = announce_window(dt.date.today())
    rows = repo.get_candidates(report_date=report_date)
    if categories:
        cats = set(categories.split(","))
        rows = [r for r in rows if cats & set(r.categories or [])]
    if min_change_pct is not None:
        rows = [r for r in rows
                if (r.change_pct or 0) >= min_change_pct]
    report_dates = [str(d) for d in repo.get_report_dates(8)]
    with_hits = sum(1 for r in rows if r.keyword_count > 0)

    def _hits_of(c, rd):
        return filter_window_hits(repo.get_hits(c.symbol, rd), rd)

    return {
        "season": {
            "in_season": season.in_season, "window_name": season.window_name,
            "window_start": season.window_start,
            "window_end": season.window_end,
            "next_window_start": season.next_window_start,
        },
        "report_dates": report_dates,
        "candidates": [
            _candidate_dict(r, _hits_of(r, r.report_date)) for r in rows
        ],
        "summary": {"pool": len(rows), "with_hits": with_hits},
    }


@router.get("/radar")
def radar(report_date: str = None, min_change_pct: float = None,
          categories: str = None):
    try:
        return _ok(_radar_data(_parse_date(report_date), min_change_pct,
                               categories))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/radar/{symbol}")
def radar_detail(symbol: str, report_date: str = None):
    rd = _parse_date_or_400(report_date)
    repo = create_boom_repository()
    c = None
    if rd is not None:
        c = repo.get_candidate(symbol, rd)
    else:
        # 未指明报告期:按报告期从新到旧找第一个命中的期
        for d in repo.get_report_dates(20):
            c = repo.get_candidate(symbol, d)
            if c:
                rd = d
                break
    if c is None:
        raise HTTPException(404, "candidate not found")
    hits = filter_window_hits(repo.get_hits(symbol, rd), rd)
    data = _candidate_dict(c, hits, preview=None)
    data["hits"] = data.pop("hits_preview")
    return _ok(data)


def _ensure_watchlist_group() -> int:
    groups = (_handler_json(watchlist_handler.list_groups()) or {}).get("data") or []
    for g in groups:
        if g.get("name") == WATCHLIST_GROUP:
            return g["id"]
    g = (_handler_json(watchlist_handler.create_group(
        {"name": WATCHLIST_GROUP})) or {}).get("data") or {}
    return g["id"]


@router.post("/radar/{symbol}/watchlist")
def add_to_watchlist(symbol: str, body: dict):
    rd = _parse_date_or_400(body.get("report_date"))
    repo = create_boom_repository()
    c = repo.get_candidate(symbol, rd) if rd else None
    if c is None:
        raise HTTPException(404, "candidate not found")
    gid = _ensure_watchlist_group()
    resp = _handler_json(watchlist_handler.add_item(
        gid, {"symbol": to_prefixed(symbol)}))
    if resp.get("code") != 0:
        raise HTTPException(400, resp.get("msg") or "add item failed")
    repo.set_status(symbol, rd, "added_watchlist")
    return _ok({"group": WATCHLIST_GROUP, "item": resp.get("data")})


@router.post("/scan/run")
def scan_run(body: dict):
    svc = build_default_service()
    today = _parse_date(body.get("date")) if body and body.get("date") else None
    return _ok(svc.run_daily(today=today))


@router.get("/keywords")
def keywords_list():
    repo = create_boom_repository()
    return _ok([
        {"id": k.id, "category": k.category,
         "category_label": CATEGORY_LABELS.get(k.category, k.category),
         "keyword": k.keyword, "weight": k.weight, "enabled": k.enabled}
        for k in repo.list_keywords(enabled_only=False)
    ])


@router.post("/keywords")
def keywords_create(body: dict):
    if body.get("category") not in CATEGORY_LABELS:
        raise HTTPException(400, f"category must be one of {list(CATEGORY_LABELS)}")
    repo = create_boom_repository()
    row = repo.create_keyword(body["category"], body["keyword"],
                              int(body.get("weight", 1)))
    return _ok({"id": row.id})


@router.put("/keywords/{kid}")
def keywords_update(kid: int, body: dict):
    if "category" in body and body["category"] not in CATEGORY_LABELS:
        raise HTTPException(400, f"category must be one of {list(CATEGORY_LABELS)}")
    repo = create_boom_repository()
    row = repo.update_keyword(kid, **{k: v for k, v in body.items()
                                      if k in ("category", "keyword", "weight", "enabled")})
    if row is None:
        raise HTTPException(404, "keyword not found")
    return _ok({"id": kid})


@router.delete("/keywords/{kid}")
def keywords_delete(kid: int):
    repo = create_boom_repository()
    if not repo.delete_keyword(kid):
        raise HTTPException(404, "keyword not found")
    return _ok({"id": kid})


@router.post("/analyze/{symbol}")
def analyze_symbol(symbol: str, body: dict):
    rd = _parse_date_or_400(body.get("report_date"))
    return _ok(_run_analyze(symbol, rd))


def _run_analyze(symbol: str, report_date):
    import asyncio

    repo = create_boom_repository()
    c = repo.get_candidate(symbol, report_date) if report_date else None
    if c is None:
        raise HTTPException(404, "candidate not found")
    from src.domain.market.boom.llm_analyst import analyze_candidate
    from src.domain.market.boom.keywords import CATEGORY_LABELS

    hits = [{"keyword": h.keyword,
             "category_label": CATEGORY_LABELS.get(h.category, h.category),
             "source_type": h.source_type, "snippet": h.snippet}
            for h in filter_window_hits(repo.get_hits(symbol, report_date),
                                        report_date)]
    cand = {"symbol": c.symbol, "company_name": c.company_name,
            "change_pct": c.change_pct,
            "forecast_type_label": c.forecast_type_label}
    try:
        out = asyncio.run(analyze_candidate(cand, hits))
    except Exception as e:
        raise HTTPException(503, f"LLM 调用失败: {e}")
    if out["verdict"] != "parse_error":
        repo.mark_llm(symbol, report_date, out["boom_score"], out["verdict"],
                      out["summary"])
    return out


@router.post("/backtest")
def backtest_run(body: dict):
    from src.domain.market.boom.backtest import run_full_backtest

    start_year = int(body.get("start_year", dt.date.today().year - 3))
    end_year = int(body.get("end_year", dt.date.today().year - 1))
    if end_year - start_year > 10:
        raise HTTPException(400, "时间跨度不能超过 10 年")
    if end_year < start_year:
        raise HTTPException(400, "end_year 必须 >= start_year")
    return _ok(run_full_backtest(
        start_year=start_year, end_year=end_year,
        min_change_pct=float(body.get("min_change_pct", 50.0)),
        hold_months=int(body.get("hold_months", 3)),
        with_text=bool(body.get("with_text", False)),
        benchmark=str(body.get("benchmark", "sh000300")),
    ))
