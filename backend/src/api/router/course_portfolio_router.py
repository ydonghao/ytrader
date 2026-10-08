"""课程组合(自动建组合)router: /api/v1/course-portfolio。

- generate: 市场快照 → course_builder 纯函数生成草稿(不落库);
- save:     服务端重算估值带+档位后落库(前端仅传 symbol/category/配额);
- review:   现算周检视建议(不落库);
- fills:    回写档位成交(整手折算, 状态推进 planned→building→complete)。

供测试猴补的接缝: _course_repo / _csi300_members / _load_pe_series /
fetch_*(router 命名空间内)。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.domain.market.portfolio.course_allocation import risk_profile_weights
from src.domain.market.portfolio.course_builder import (
    CandidateRow,
    allocate_slots,
    assemble_plan,
    classify_candidates,
    plan_ladder,
    plan_pe_band,
    select_pools,
)
from src.domain.market.portfolio.course_review import (
    LegReviewInput,
    review_portfolio,
)
from src.domain.market.strategy.longterm.data_loader import (
    fetch_annual_revenues,
    fetch_latest_financials,
    fetch_latest_valuations,
    fetch_symbol_names,
    fetch_universe_symbols,
)
from src.infra.database.market.index_constituent import (
    create_index_constituent_repository,
)
from src.infra.database.market.valuation import (
    create_stock_valuation_repository,
)
from src.infra.database.portfolio.course_models import (
    CoursePortfolio,
    CoursePortfolioLeg,
)
from src.infra.database.portfolio.course_portfolio_repository import (
    create_course_portfolio_repository,
)
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.database.sql_engine.engine import create_db_connection

router = APIRouter(prefix="/course-portfolio", tags=["course-portfolio"])

PE_HISTORY_YEARS = 5
CASH_RESERVE_PCT = 0.10
VALID_CATEGORIES = ("dividend", "bluechip", "growth")

# 全市场快照进程内缓存: generate 每次要拉 6780 只的估值/ROE/年报快照,
# 结果一天内不变(交易数据日频), TTL 10 分钟足够新鲜且明显提速。
_SNAPSHOT_TTL_SECONDS = 600
_snapshot_cache: dict = {"key": None, "at": 0.0, "vals": {}, "fins": {}, "revs": {}}


# ── 接缝(测试猴补点) ──────────────────────────────────────────────────
def _course_repo():
    return create_course_portfolio_repository()


def _csi300_members() -> list[str]:
    return create_index_constituent_repository().get_members("000300")


def _load_pe_series(
    symbols: list[str], as_of: Optional[date] = None
) -> dict[str, list[float]]:
    """批量取每股近5年"每月末 pe_ttm"序列(供 μ±1σ, SQL侧降采样)。

    as_of: 窗口右端, 缺省今天。时光机 generate 必须传请求的 as_of,
    否则历史日的 PE 带会掺入未来数据(状态判错)。
    """
    if not symbols:
        return {}
    repo = create_stock_valuation_repository()
    end = as_of or date.today()
    start = end - dt.timedelta(days=int(PE_HISTORY_YEARS * 365.25))
    try:
        return repo.get_monthly_pe_ttm_batch(symbols, start, end)
    except Exception:
        return {s: [] for s in symbols}


# ── 请求模型 ──────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    total_capital: float = Field(gt=0)
    risk_profile: str
    stock_count: int = Field(default=8, ge=5, le=8)
    as_of: Optional[str] = None


class LegIn(BaseModel):
    symbol: str
    category: str
    target_weight: float = Field(gt=0, le=1)
    target_amount: float = Field(gt=0)


class SaveRequest(BaseModel):
    name: str = ""
    total_capital: float = Field(gt=0)
    risk_profile: str
    stock_count: int = Field(default=8, ge=5, le=8)
    legs: list[LegIn]


class FillRequest(BaseModel):
    rung_index: int = Field(ge=0)
    fill_price: Optional[float] = None
    fill_shares: Optional[int] = None


# ── 内部组装 ──────────────────────────────────────────────────────────
def _latest_valuations_all(as_of: date) -> dict[str, dict]:
    """全市场估值快照(不带 symbol 过滤, 输出形状同 fetch_latest_valuations)。

    实测: DISTINCT ON (symbol) 的 SkipScan 不带 ANY 列表 28ms; 带 6780 只
    的 ANY 列表会退化为 ~4s(planner 对数组逐项判定, 跳跃优化失效)。
    多返回的非 universe symbol 由调用方 dict 取值时自然忽略。
    """
    try:
        db = create_db_connection(get_dsn())
    except Exception:
        return {}
    out: dict[str, dict] = {}
    try:
        with db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT DISTINCT ON (symbol) symbol, trade_date, pe, pe_ttm,"
                    " pb, ps, ps_ttm, dv_ratio, dv_ttm, total_mv"
                    " FROM stock_valuation WHERE trade_date <= :d"
                    " ORDER BY symbol, trade_date DESC"
                ),
                {"d": as_of},
            ).fetchall()
            for (sym, td, pe, pe_ttm, pb, ps, ps_ttm,
                 dv_ratio, dv_ttm, total_mv) in rows:
                out[sym] = {
                    "trade_date": td.date() if hasattr(td, "date") else td,
                    "pe": pe, "pe_ttm": pe_ttm, "pb": pb,
                    "ps": ps, "ps_ttm": ps_ttm,
                    "dv_ratio": dv_ratio, "dv_ttm": dv_ttm,
                    "total_mv": total_mv,
                }
    except Exception:
        return {}
    return out


def _load_universe_rows(
    symbols: list[str], csi300: set, as_of: date
) -> tuple[list[CandidateRow], dict[str, Optional[float]]]:
    """universe → 分类输入快照;同时返回 {symbol: 当前pe_ttm}。

    三个全市场快照查询走 10 分钟进程内缓存(结果日频, 不影响口径);
    缓存按 as_of 日期 + symbols 指纹作 key, 只缓存"全市场"规模调用。
    """
    import time as _time

    key = f"{as_of.isoformat()}|{len(symbols)}"
    now = _time.monotonic()
    use_cache = len(symbols) > 1000
    if use_cache and _snapshot_cache["key"] == key and \
            now - _snapshot_cache["at"] < _SNAPSHOT_TTL_SECONDS:
        vals = _snapshot_cache["vals"]
        fins = _snapshot_cache["fins"]
        revs = _snapshot_cache["revs"]
    else:
        # 全市场: 不带 ANY 过滤走 SkipScan 快路径; 小列表走共享 data_loader
        vals = (_latest_valuations_all(as_of) if use_cache
                else fetch_latest_valuations(symbols, as_of))
        fins = fetch_latest_financials(symbols, as_of)
        revs = fetch_annual_revenues(symbols, as_of)
        if use_cache:
            _snapshot_cache.update(
                key=key, at=now, vals=vals, fins=fins, revs=revs
            )

    rows: list[CandidateRow] = []
    current_pes: dict[str, Optional[float]] = {}
    for sym in symbols:
        v = vals.get(sym)
        if not v:
            continue
        pe = v.get("pe_ttm")
        current_pes[sym] = pe
        if not pe or pe <= 0:
            continue
        annual = [x["revenue"] for x in revs.get(sym, [])[:2] if x.get("revenue")]
        rows.append(CandidateRow(
            symbol=sym,
            dv_ttm=v.get("dv_ttm"),
            pe_ttm=pe,
            total_mv=v.get("total_mv"),
            roe_pct=(fins.get(sym) or {}).get("roe_weighted"),
            annual_revenues=annual,
            in_csi300=sym in csi300,
        ))
    return rows, current_pes


def _close_prices(repo, symbols: list[str], as_of: date) -> dict[str, float]:
    """批量收盘价(超表分块规划只摊销一次)。"""
    try:
        return repo.get_close_prices_batch(symbols, as_of)
    except AttributeError:
        # 兼容仅有单只接口的仓储实现(如测试 FakeRepo)
        out = {}
        for s in dict.fromkeys(symbols):
            p = repo.get_close_price(s, as_of)
            if p is not None:
                out[s] = p
        return out


# ── 端点 ──────────────────────────────────────────────────────────────
@router.post("/generate")
def generate_portfolio(req: GenerateRequest):
    """生成组合草稿(不落库)。

    注: bluechip 分类按当前沪深300成分近似(无历史成分数据),
    as_of 仅作用于价格/估值系列。
    """
    weights = risk_profile_weights(req.risk_profile)
    if weights is None:
        raise HTTPException(status_code=400,
                            detail=f"未知风险偏好: {req.risk_profile}")
    as_of = date.fromisoformat(req.as_of) if req.as_of else date.today()
    symbols = fetch_universe_symbols("A", exclude_st=True)
    if not symbols:
        raise HTTPException(status_code=503,
                            detail="标的池不可用(stock_info 为空)")
    rows, current_pes = _load_universe_rows(
        symbols, set(_csi300_members()), as_of)
    classified = classify_candidates(rows)
    slots = allocate_slots(req.stock_count, weights)
    pools = select_pools(classified, slots)
    pool_syms = sorted({c.symbol for pl in pools.values() for c in pl})
    names = fetch_symbol_names(pool_syms)
    prices = _close_prices(_course_repo(), pool_syms, as_of)
    pe_series = _load_pe_series(pool_syms, as_of)  # 时光机: PE带窗口截至 as_of
    draft = assemble_plan(
        pools=pools, slots=slots, weights=weights,
        total_capital=req.total_capital, cash_reserve_pct=CASH_RESERVE_PCT,
        names=names, prices=prices, pe_series=pe_series,
        current_pes=current_pes,
    )
    draft.risk_profile = req.risk_profile
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "risk_profile": req.risk_profile,
            "profile_weights": weights,
            "total_capital": req.total_capital,
            "investable_capital": draft.investable_capital,
            "slots": draft.slots,
            "legs": [asdict(l) for l in draft.legs],
            "warnings": draft.warnings,
            "candidates": draft.candidates,
        },
    }


@router.post("")
def save_portfolio(req: SaveRequest):
    weights = risk_profile_weights(req.risk_profile)
    if weights is None:
        raise HTTPException(status_code=400,
                            detail=f"未知风险偏好: {req.risk_profile}")
    if not req.legs:
        raise HTTPException(status_code=400, detail="legs 为空")
    seen: set[str] = set()
    for l in req.legs:
        if l.category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"非法类别: {l.category}")
        if l.symbol in seen:
            raise HTTPException(status_code=400, detail=f"重复标的: {l.symbol}")
        seen.add(l.symbol)

    as_of = date.today()
    repo = _course_repo()
    syms = [l.symbol for l in req.legs]
    vals = fetch_latest_valuations(syms, as_of)
    names = fetch_symbol_names(syms)
    prices = _close_prices(repo, syms, as_of)
    pe_series = _load_pe_series(syms)

    leg_models: list[CoursePortfolioLeg] = []
    for l in req.legs:
        pe = (vals.get(l.symbol) or {}).get("pe_ttm")
        band = plan_pe_band(pe_series.get(l.symbol, []), pe)
        price = prices.get(l.symbol)
        rungs = plan_ladder(band, price, l.target_amount) if price else []
        leg_models.append(CoursePortfolioLeg(
            symbol=l.symbol,
            name=names.get(l.symbol, l.symbol),
            category=l.category,
            target_weight=l.target_weight,
            target_amount=l.target_amount,
            pe_band=band,
            entry_plan=[r.to_dict() for r in rungs],
        ))
    portfolio = CoursePortfolio(
        name=req.name or f"{req.risk_profile}-课程组合",
        risk_profile=req.risk_profile,
        total_capital=req.total_capital,
        cash_reserve_pct=CASH_RESERVE_PCT,
        target_stock_count=req.stock_count,
        status="planned",
    )
    pid = repo.create_plan(portfolio, leg_models)
    return {"code": 0, "msg": "ok", "data": {"id": pid}}


@router.get("")
def list_portfolios():
    return {"code": 0, "msg": "ok", "data": _course_repo().list_plans()}


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: int):
    plan = _course_repo().get_plan(portfolio_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="组合不存在")
    p, legs = plan["portfolio"], plan["legs"]
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "id": p.id,
            "name": p.name,
            "risk_profile": p.risk_profile,
            "total_capital": p.total_capital,
            "cash_reserve_pct": p.cash_reserve_pct,
            "target_stock_count": p.target_stock_count,
            "status": p.status,
            "notes": p.notes,
            "legs": [
                {
                    "id": l.id,
                    "symbol": l.symbol,
                    "name": l.name,
                    "category": l.category,
                    "target_weight": l.target_weight,
                    "target_amount": l.target_amount,
                    "pe_band": l.pe_band,
                    "entry_plan": l.entry_plan or [],
                    "shares": l.shares,
                    "invested_amount": l.invested_amount,
                    "avg_cost": l.avg_cost,
                }
                for l in legs
            ],
        },
    }


@router.delete("/{portfolio_id}")
def delete_portfolio(portfolio_id: int):
    if not _course_repo().delete_plan(portfolio_id):
        raise HTTPException(status_code=404, detail="组合不存在")
    return {"code": 0, "msg": "ok", "data": {"deleted": portfolio_id}}


@router.get("/{portfolio_id}/review")
def review(portfolio_id: int):
    repo = _course_repo()
    plan = repo.get_plan(portfolio_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="组合不存在")
    p, legs = plan["portfolio"], plan["legs"]
    as_of = date.today()
    syms = [l.symbol for l in legs]
    vals = fetch_latest_valuations(syms, as_of)
    pe_series = _load_pe_series(syms)
    closes = _close_prices(repo, syms, as_of)
    inputs: list[LegReviewInput] = []
    for l in legs:
        price = closes.get(l.symbol)
        band = plan_pe_band(
            pe_series.get(l.symbol, []),
            (vals.get(l.symbol) or {}).get("pe_ttm"),
        )
        v = vals.get(l.symbol) or {}
        inputs.append(LegReviewInput(
            symbol=l.symbol, name=l.name, category=l.category,
            target_weight=l.target_weight, entry_plan=l.entry_plan or [],
            shares=l.shares, invested_amount=l.invested_amount,
            current_price=price, dv_ttm=v.get("dv_ttm"),
            pe_state=(band or {}).get("state"),
        ))
    rev = review_portfolio(inputs, p.total_capital, p.cash_reserve_pct)
    return {"code": 0, "msg": "ok", "data": asdict(rev)}


@router.post("/{portfolio_id}/legs/{leg_id}/fills")
def record_fill(portfolio_id: int, leg_id: int, req: FillRequest):
    repo = _course_repo()
    plan = repo.get_plan(portfolio_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="组合不存在")
    leg = next((l for l in plan["legs"] if l.id == leg_id), None)
    if leg is None:
        raise HTTPException(status_code=404, detail="腿不存在")
    entry = [dict(r) for r in (leg.entry_plan or [])]
    target = next(
        (r for r in entry if r.get("rung_index") == req.rung_index), None)
    if target is None:
        raise HTTPException(status_code=400,
                            detail=f"档位不存在: {req.rung_index}")
    if target.get("executed"):
        raise HTTPException(status_code=400, detail="该档已执行")

    price = req.fill_price or repo.get_close_price(leg.symbol, date.today())
    if not price or price <= 0:
        raise HTTPException(status_code=400,
                            detail="无可用成交价(停牌?), 请手动传入 fill_price")
    shares = req.fill_shares or int(target["amount"] / price // 100) * 100
    if shares <= 0:
        raise HTTPException(status_code=400, detail="金额不足一手, 无法成交")

    target["executed"] = True
    target["executed_at"] = datetime.now().isoformat(timespec="seconds")
    target["fill_price"] = price
    target["fill_shares"] = shares

    def _done(l, entry_override):
        e = entry_override if l.id == leg_id else (l.entry_plan or [])
        return bool(e) and all(r.get("executed") for r in e)

    if all(_done(l, entry) for l in plan["legs"]):
        status = "complete"
    elif plan["portfolio"].status == "planned":
        status = "building"
    else:
        status = None
    repo.save_leg_fill(leg_id, entry, shares, price, shares * price, status)
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "fill_price": price,
            "fill_shares": shares,
            "status": status or plan["portfolio"].status,
        },
    }
