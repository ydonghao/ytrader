# backend/src/api/router/industry_router.py
"""行业分析 API(规格 2026-09-20 §5)。"""
import datetime as dt
import logging

from fastapi import APIRouter, HTTPException

from src.domain.market.industry_analysis.flow_map import summarize_flow
from src.domain.market.industry_analysis.knowledge import (
    SW_L1_CODES, TIER_LABELS, load_knowledge,
)
from src.domain.market.industry_analysis.stats import histogram, percentile_rank
from src.infra.database.market.industry_analysis import (
    create_industry_analysis_repository,
)

log = logging.getLogger("industry_analysis")
router = APIRouter(prefix="/industry", tags=["industry"])

PB_BREAK_THRESHOLD = 0.10       # 规格笔记:>10% 阶段性底部参考区


def _ok(data):
    return {"code": 0, "msg": "ok", "data": data}


def _repo():
    return create_industry_analysis_repository()


def rs_series(industry_closes, bench_closes):
    """RS 线 = 标的/基准双 rebase 商(首点 1.0);按日期对齐,任一侧缺日跳过。"""
    bench = dict(bench_closes)
    pts = [(d, p, bench[d]) for (d, p) in industry_closes if d in bench]
    if not pts:
        return []
    p0, b0 = pts[0][1], pts[0][2]
    if not p0 or not b0:
        return []
    return [{"date": d.isoformat(), "rs": round((p / p0) / (b / b0), 6)}
            for (d, p, b) in pts]


def _overview_data(window: int) -> dict:
    """最新评分快照 + 展示口径分位(可切5/8/10年)+知识层 → 热力图行。"""
    repo = _repo()
    d = repo.get_prosperity_latest_date()
    if d is None:
        return {"trade_date": None, "rows": []}
    rows_by_code = {r["sw_code"]: r for r in repo.get_prosperity(d)}
    w_start = d - dt.timedelta(days=int(window * 365.25))
    valuations = repo.get_sw_valuation_window(list(SW_L1_CODES), w_start, d)
    know = load_knowledge()
    rows = []
    for code in SW_L1_CODES:
        k, p = know[code], rows_by_code.get(code, {})
        inputs = p.get("inputs") or {}
        series = valuations.get(code) or []
        last = series[-1] if series else {}
        rows.append({
            "sw_code": code, "name": k.name, "tier": k.tier,
            "tier_label": TIER_LABELS[k.tier],
            "retail_suitable": k.retail_suitable,
            "revenue_yoy": inputs.get("revenue_yoy"),
            "net_profit_yoy": inputs.get("net_profit_yoy"),
            "pe_ttm": last.get("pe_ttm"),
            "pe_pct": percentile_rank(last.get("pe_ttm"),
                                      [r["pe_ttm"] for r in series]),
            "pb": last.get("pb"),
            "pb_pct": percentile_rank(last.get("pb"),
                                      [r["pb"] for r in series]),
            "rs60": inputs.get("rs60"), "flow20": inputs.get("flow20"),
            "score": p.get("score"), "score_profit": p.get("score_profit"),
            "score_valuation": p.get("score_valuation"),
            "score_momentum": p.get("score_momentum"),
            "score_flow": p.get("score_flow"),
            "hist_start": series[0]["trade_date"].isoformat()
            if series else None,
        })
    return {"trade_date": d.isoformat(), "window": window, "rows": rows}


def _pb_break_data(scope: str, scope_code: str | None,
                   years: int) -> dict:
    repo = _repo()
    end = dt.date.today()
    start = end - dt.timedelta(days=int(years * 365.25))
    code = scope_code or ("ALL" if scope == "market" else None)
    if scope == "industry" and code not in SW_L1_CODES:
        raise ValueError("scope_code 须为申万一级行业码")
    series = repo.get_pb_break_series(scope, code, start, end)
    rates = [r["break_rate"] for r in series
             if r["break_rate"] is not None]
    current = series[-1] if series else None
    return {
        "scope": scope, "scope_code": code,
        "threshold": PB_BREAK_THRESHOLD,
        "series": [dict(r, trade_date=r["trade_date"].isoformat())
                   for r in series],
        "current": dict(current,
                        trade_date=current["trade_date"].isoformat())
        if current else None,
        "current_percentile": percentile_rank(
            current.get("break_rate") if current else None, rates),
        "over_threshold_now": bool(
            current and current.get("break_rate", 0) > PB_BREAK_THRESHOLD),
    }


def _flow_data() -> dict:
    repo = _repo()
    latest = repo.get_flow_latest_date()
    if latest is None:
        return {"snapshot": None, "rows": []}
    rows = repo.get_flow_rows(latest - dt.timedelta(days=30))
    return {"snapshot": latest.isoformat(),
            "rows": summarize_flow(rows)}


@router.get("/overview")
def overview(window: int = 8):
    if window not in (5, 8, 10):
        raise HTTPException(400, "window 须为 5/8/10")
    return _ok(_overview_data(window))


@router.get("/pb-break")
def pb_break(scope: str = "market", scope_code: str = None,
             years: int = 35):
    if scope not in ("market", "industry"):
        raise HTTPException(400, "scope 须为 market/industry")
    try:
        return _ok(_pb_break_data(scope=scope, scope_code=scope_code,
                                  years=years))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/flow")
def flow():
    return _ok(_flow_data())


def _detail_data(sw_code: str) -> dict:
    if sw_code not in SW_L1_CODES:
        raise LookupError(sw_code)
    repo = _repo()
    know = load_knowledge()
    k = know[sw_code]
    p_date = repo.get_prosperity_latest_date()
    prosper = next((r for r in (repo.get_prosperity(p_date)
                                if p_date else [])
                    if r["sw_code"] == sw_code), None)
    conc = repo.get_concentration(sw_code)
    # 成分估值:最新估值交易日截面(15*3 容差,估值同步可能滞后数周,
    # 同 industry_pb_break_sync 的 days*3 口径)
    today = dt.date.today()
    v_dates = repo.get_stock_valuation_dates(
        today - dt.timedelta(days=45), today)
    members = (repo.get_member_valuations(v_dates[-1])
               if v_dates else [])
    mine = [m for m in members if m["sw_code_l1"] == sw_code]
    pb_hist = histogram([m["pb"] for m in mine], bins=20)
    pe_hist = histogram([m["pe_ttm"] for m in mine], bins=20,
                        lo=0, hi=200)      # 负PE剔除展示
    top = sorted(mine, key=lambda m: m["total_mv"] or 0,
                 reverse=True)[:20]
    return {
        "sw_code": sw_code, "name": k.name, "knowledge": {
            "tier": k.tier, "tier_label": TIER_LABELS[k.tier],
            "retail_suitable": k.retail_suitable, "approach": k.approach,
            "upstream": list(k.upstream), "downstream": list(k.downstream),
            "note": k.note},
        "prosperity": prosper,
        "valuation_date": v_dates[-1].isoformat() if v_dates else None,
        "member_count": len(mine),
        "pb_histogram": pb_hist, "pe_histogram": pe_hist,
        "members": top,
        "concentration": conc,
    }


def _strength_data(sw_code: str, compare: list[str]) -> dict:
    if sw_code not in SW_L1_CODES:
        raise LookupError(sw_code)
    repo = _repo()
    end = dt.date.today()
    start = end - dt.timedelta(days=365)
    codes = [sw_code] + [c for c in compare if c in SW_L1_CODES][:4]
    closes = repo.get_index_closes(
        [f"sw{c}" for c in codes] + ["sh000300"], start, end)
    bench = closes.get("sh000300", [])
    b0 = bench[0][1] if bench else 1.0
    lines = {}
    for c in codes:
        cl = closes.get(f"sw{c}", [])
        if not cl or not bench:
            continue
        lines[c] = rs_series(cl, bench)
    know = load_knowledge()
    return {
        "sw_code": sw_code,
        "benchmark": [{"date": d.isoformat(), "close": round(p / b0, 6)}
                      for (d, p) in bench],
        "lines": lines,
        "names": {c: know[c].name for c in codes},
    }


@router.get("/{sw_code}")
def detail(sw_code: str):
    try:
        return _ok(_detail_data(sw_code))
    except LookupError:
        raise HTTPException(404, f"未知申万一级行业: {sw_code}")


@router.get("/{sw_code}/strength")
def strength(sw_code: str, compare: str = ""):
    try:
        return _ok(_strength_data(
            sw_code, [c for c in compare.split(",") if c]))
    except LookupError:
        raise HTTPException(404, f"未知申万一级行业: {sw_code}")


@router.post("/{sw_code}/interpret")
async def interpret_route(sw_code: str):
    if sw_code not in SW_L1_CODES:
        raise HTTPException(404, f"未知申万一级行业: {sw_code}")
    repo = _repo()
    d = repo.get_prosperity_latest_date()
    if d is None:
        raise HTTPException(404, "暂无景气分数据,请先跑回填/等待job")
    from src.domain.market.industry_analysis import llm_analyst
    try:
        result = await llm_analyst.interpret(sw_code, d.isoformat())
    except llm_analyst.LLMNotConfigured as e:   # provider 未配置
        raise HTTPException(503, str(e))
    except Exception as e:         # noqa: BLE001
        log.error("[INDUSTRY_INTERPRET] %s failed: %s", sw_code, e)
        raise HTTPException(502, f"LLM 调用失败: {e}")
    return _ok({"sw_code": sw_code, "date": d.isoformat(), **result})
