"""永久投资组合 API — 多组合管理 + 净值监控 + 再平衡建议 + 回测。

GET    /perm-portfolio/instruments                  标的池列表
POST   /perm-portfolio/instruments                  新增标的
PUT    /perm-portfolio/instruments/{id}             编辑标的
DELETE /perm-portfolio/instruments/{id}             删除标的
GET    /perm-portfolio/portfolios                   组合列表(含最新净值)
POST   /perm-portfolio/portfolios                   新建组合
GET    /perm-portfolio/portfolios/{id}              组合详情
PUT    /perm-portfolio/portfolios/{id}              编辑组合
DELETE /perm-portfolio/portfolios/{id}              删除组合
GET    /perm-portfolio/portfolios/{id}/nav          净值历史
GET    /perm-portfolio/portfolios/{id}/rebalance    再平衡建议
POST   /perm-portfolio/portfolios/{id}/rebalance/apply  应用再平衡
POST   /perm-portfolio/portfolios/{id}/backtest     组合回测
"""
from typing import Optional

from fastapi import APIRouter, Query

from src.api.handler.perm_portfolio_handler import (
    apply_rebalance,
    backtest_portfolio,
    create_instrument,
    create_portfolio,
    delete_instrument,
    delete_portfolio,
    get_nav_history,
    get_portfolio,
    get_rebalance_suggestion,
    list_instruments,
    list_portfolios,
    rolling_backtest_portfolio,
    update_instrument,
    update_portfolio,
)

router = APIRouter(
    prefix="/perm-portfolio", tags=["perm-portfolio"]
)


# ═══════════════════════════════════════════════════════════════
# 标的池
# ═══════════════════════════════════════════════════════════════

@router.get("/instruments")
def _list_instruments(
    market: Optional[str] = Query(None),
    asset_class: Optional[str] = Query(None),
    enabled_only: bool = Query(False),
):
    return list_instruments(market, asset_class, enabled_only)


@router.post("/instruments")
def _create_instrument(body: dict):
    return create_instrument(body)


@router.put("/instruments/{instrument_id}")
def _update_instrument(instrument_id: int, body: dict):
    return update_instrument(instrument_id, body)


@router.delete("/instruments/{instrument_id}")
def _delete_instrument(instrument_id: int):
    return delete_instrument(instrument_id)


# ═══════════════════════════════════════════════════════════════
# 组合
# ═══════════════════════════════════════════════════════════════

@router.get("/portfolios")
def _list_portfolios(
    active_only: bool = Query(True),
):
    return list_portfolios(active_only=active_only)


@router.post("/portfolios")
def _create_portfolio(body: dict):
    return create_portfolio(body)


@router.get("/portfolios/{portfolio_id}")
def _get_portfolio(portfolio_id: int):
    return get_portfolio(portfolio_id)


@router.put("/portfolios/{portfolio_id}")
def _update_portfolio(portfolio_id: int, body: dict):
    return update_portfolio(portfolio_id, body)


@router.delete("/portfolios/{portfolio_id}")
def _delete_portfolio(portfolio_id: int):
    return delete_portfolio(portfolio_id)


@router.get("/portfolios/{portfolio_id}/nav")
def _get_nav(
    portfolio_id: int,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    return get_nav_history(portfolio_id, start_date, end_date)


@router.get("/portfolios/{portfolio_id}/rebalance")
def _get_rebalance(portfolio_id: int):
    return get_rebalance_suggestion(portfolio_id)


@router.post("/portfolios/{portfolio_id}/rebalance/apply")
def _apply_rebalance(portfolio_id: int):
    return apply_rebalance(portfolio_id)


@router.post("/portfolios/{portfolio_id}/backtest")
def _backtest(portfolio_id: int, body: dict = None):
    return backtest_portfolio(portfolio_id, body or {})


@router.post("/portfolios/{portfolio_id}/rolling-backtest")
def _rolling_backtest(portfolio_id: int, body: dict = None):
    return rolling_backtest_portfolio(portfolio_id, body or {})
