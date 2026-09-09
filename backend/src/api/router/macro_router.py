"""宏观板块 API — 宏观指标 + 判断快照 + 验证对照。

GET  /macro/dashboard             仪表盘（聚合视图）
GET  /macro/indicators/latest     指标最新值（含趋势/阈值）
GET  /macro/indicators/{code}     单指标历史时序
GET  /macro/views                 历史快照列表
GET  /macro/views/{id}            单快照详情
GET  /macro/views/{id}/track      预测期内指数 K 线（对照判断点）
GET  /macro/events                中国重大经济事件列表（图表标注）
POST /macro/views/generate        手动生成快照
"""
from typing import Optional

from fastapi import APIRouter, Query

from src.api.handler.macro_handler import (
    dashboard,
    generate_view,
    get_view,
    indicator_series,
    latest_indicators,
    list_events,
    list_views,
    record_view,
    track_view,
    cycle_signals,
    north_flow_signal_report,
    margin_sentiment_report,
    rate_differential_report,
    futures_basis_report,
)

router = APIRouter(prefix="/macro", tags=["macro"])


@router.get("/dashboard")
def _dashboard():
    return dashboard()


@router.get("/indicators/latest")
def _indicators_latest(
    category: Optional[str] = Query(None, description="cn/us/global"),
    group: Optional[str] = Query(
        None, description="growth/inflation/employment/monetary"
    ),
):
    return latest_indicators(category=category, group=group)


@router.get("/indicators/{code}")
def _indicator_series(
    code: str,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(500),
):
    return indicator_series(code, start, end, limit)


@router.get("/views")
def _views(
    status: Optional[str] = Query(None, description="pending/scored/partial"),
    limit: int = Query(50),
):
    return list_views(status=status, limit=limit)


@router.get("/views/{view_id}")
def _view_detail(view_id: int):
    return get_view(view_id)


@router.get("/views/{view_id}/track")
def _view_track(view_id: int):
    return track_view(view_id)


@router.post("/views/generate")
def _view_generate():
    return generate_view()


@router.post("/views/record")
def _view_record(body: dict):
    return record_view(body)


@router.get("/events")
def _events():
    return list_events()


@router.get("/cycle-signals")
def _cycle_signals():
    """宏观周期规则信号（PMI×PPI 周期定位 + 行业轮动 + M2/GDP + 三部门体检）。

    《股票投资课程》02/31 集：确定性规则驱动（非 LLM），可复现。
    """
    return cycle_signals()


@router.get("/north-flow-signal")
def _north_flow(limit: int = Query(60, ge=2, le=500)):
    """北向资金信号（外资情绪：持续净流入=看好）。

    《股票投资课程》31：需先同步 market_sentiment（north_flow_daily）。
    """
    return north_flow_signal_report(limit=limit)


@router.get("/margin-sentiment")
def _margin_sentiment(limit: int = Query(60, ge=2, le=500)):
    """融资融券杠杆情绪（余额上升=乐观加杠杆）。

    《股票投资课程》27：需先同步 market_sentiment（margin_balance_daily）。
    """
    return margin_sentiment_report(limit=limit)


@router.get("/rate-differential")
def _rate_differential():
    """中美 10Y 国债利差（倒挂=资本流出压力）。

    《股票投资课程》02/31：中国端由 market_sentiment 同步；美国端需 fred。
    """
    return rate_differential_report()


@router.get("/futures-basis")
def _futures_basis(
    code: str = Query("IF0", description="股指期货主力：IF0/IH0/IC0/IM0"),
):
    """股指期货升贴水（大升水→交割日卖压预警，交割日魔咒）。

    《股票投资课程》27：期货价取新浪主力连续，现货取对应宽基指数最新。
    """
    return futures_basis_report(code=code)
