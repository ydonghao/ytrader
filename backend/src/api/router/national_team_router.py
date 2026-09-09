"""国家队板块 API — 每日 ETF 信号 + 历年季报持仓 + 实时全景。

GET  /national-team/daily-signals            当日 ETF 护盘信号(成交量口径)
GET  /national-team/holdings/summary         总市值趋势(季度×主体)
GET  /national-team/holdings/changes         季度环比变动明细
GET  /national-team/holdings/sector-distribution  行业分布时间序列
GET  /national-team/holdings/top             个股 Top 榜
GET  /national-team/holdings/symbol/{symbol} 单股持仓历史(下钻)
GET  /national-team/coverage                 回填进度
# ── 实时全景(新增,纯增量)──
GET  /national-team/live/snapshot            持仓+实时行情+汇总+矩阵+洞察
GET  /national-team/live/entities            6 大主体元数据
GET  /national-team/live/kline               个股/ETF 前复权日K
GET  /national-team/etf/snapshot             ETF 实时 + 份额变动信号
GET  /national-team/etf/history              ETF 份额历史序列
GET  /national-team/etf/signals              份额级异常申赎信号
"""
from typing import Optional

from fastapi import APIRouter, Query

from src.api.handler.national_team_handler import (
    coverage,
    daily_signals,
    holdings_changes,
    holdings_search,
    holdings_sector_distribution,
    holdings_summary,
    holdings_symbol_history,
    holdings_top,
    sector_flow,
    sector_stocks,
)
from src.api.handler.national_team_live_handler import (
    etf_history,
    etf_signals,
    etf_snapshot,
    live_entities,
    live_kline,
    live_snapshot,
)

router = APIRouter(prefix="/national-team", tags=["national-team"])


@router.get("/daily-signals")
def _daily_signals(
    days: int = Query(20, description="热力图交易日窗口(20/60/120/...)"),
):
    return daily_signals(days=days)


@router.get("/holdings/summary")
def _summary(
    category: Optional[str] = Query(None, description="huijin/zhengjin/safe/social_security"),
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    return holdings_summary(category=category, from_date=from_date)


@router.get("/holdings/changes")
def _changes(
    period: str = Query(..., description="当期 YYYY-MM-DD"),
    vs_period: str = Query(..., description="对比期 YYYY-MM-DD"),
    category: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None, description="new/increase/decrease/exit"),
):
    return holdings_changes(period=period, vs_period=vs_period,
                            category=category, change_type=change_type)


@router.get("/holdings/sector-distribution")
def _sector(from_date: Optional[str] = Query(None)):
    return holdings_sector_distribution(from_date=from_date)


@router.get("/holdings/top")
def _top(
    period: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
):
    return holdings_top(period=period, limit=limit, offset=offset)


@router.get("/holdings/symbol/{symbol}")
def _symbol(symbol: str):
    return holdings_symbol_history(symbol=symbol)


@router.get("/holdings/search")
def _search(
    q: str = Query(..., description="代码或名称关键词"),
    limit: int = Query(20),
):
    return holdings_search(q=q, limit=limit)


@router.get("/holdings/sector-flow")
def _sector_flow():
    return sector_flow()


@router.get("/holdings/sector-stocks")
def _sector_stocks(
    sector: str = Query(..., description="行业名"),
    period: Optional[str] = Query(None, description="YYYY-MM-DD, 默认最新"),
):
    return sector_stocks(sector=sector, period=period)


@router.get("/coverage")
def _coverage():
    return coverage()


# ── 实时全景(新增,纯增量;既有端点不动)──────────────────────────
@router.get("/live/snapshot")
def _live_snapshot():
    return live_snapshot()


@router.get("/live/entities")
def _live_entities():
    return live_entities()


@router.get("/live/kline")
def _live_kline(
    symbol: str = Query(..., description="6 位股票/ETF 代码"),
    days: int = Query(30, description="K 线天数(5-250)"),
):
    return live_kline(symbol=symbol, days=days)


@router.get("/etf/snapshot")
def _etf_snapshot():
    return etf_snapshot()


@router.get("/etf/history")
def _etf_history(
    etf_code: Optional[str] = Query(None, description="留空返回全部 ETF 热力结构"),
    days: int = Query(90, description="历史天数"),
):
    return etf_history(etf_code=etf_code, days=days)


@router.get("/etf/signals")
def _etf_signals():
    return etf_signals()
