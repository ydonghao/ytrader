"""
Price Alerts Router
====================
GET  /alerts              → list all alerts (optional ?status=active filter)
POST /alerts              → create alert {symbol, target_price, direction, message?}
DELETE /alerts/{id}       → cancel/delete an alert
GET  /alerts/check/{symbol} → check current price and trigger active alerts
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from src.infra.database.alert.repository import create_alert_repository

router = APIRouter(prefix="/alerts", tags=["alerts"])
log = logging.getLogger(__name__)


# ── Pydantic Models ─────────────────────────────────────────────────────────
class AlertCreate(BaseModel):
    symbol: str
    target_price: float
    direction: str
    message: Optional[str] = None

    @field_validator("symbol")
    @classmethod
    def symbol_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("symbol cannot be empty")
        return v.strip()

    @field_validator("target_price")
    @classmethod
    def target_price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("target_price must be greater than 0")
        return v

    @field_validator("direction")
    @classmethod
    def direction_valid(cls, v: str) -> str:
        if v not in ("above", "below"):
            raise ValueError("direction must be 'above' or 'below'")
        return v


class AlertItem(BaseModel):
    id: int
    symbol: str
    target_price: float
    direction: str
    status: str
    message: Optional[str]
    triggered_at: Optional[str]
    created_at: str


class AlertCheckResult(BaseModel):
    triggered_alerts: list[AlertItem]
    current_price: Optional[float]
    symbol: str


# ── Helpers ────────────────────────────────────────────────────────────────

def _to_dict(alert) -> dict:
    """Convert a PriceAlertTable instance to API response dict."""
    return {
        "id": alert.id,
        "symbol": alert.symbol,
        "target_price": alert.target_price,
        "direction": alert.direction,
        "status": alert.status,
        "message": alert.message,
        "triggered_at": str(alert.triggered_at) if alert.triggered_at else None,
        "created_at": str(alert.created_at),
    }


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.get("")
def list_alerts(
    status: Optional[str] = Query(None, description="Filter by status: active, triggered, cancelled"),
    limit: int = Query(200, ge=1, le=500, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="分页偏移"),
):
    """List alerts, optionally filtered by status (分页)."""
    try:
        repo = create_alert_repository()
        alerts = repo.list_alerts(status=status, limit=limit, offset=offset)
        return {
            "code": 0,
            "msg": "ok",
            "data": [_to_dict(a) for a in alerts],
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        log.error("list_alerts error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
def create_alert(body: AlertCreate):
    """Create a new price alert."""
    try:
        repo = create_alert_repository()
        alert = repo.create_alert(
            symbol=body.symbol,
            target_price=body.target_price,
            direction=body.direction,
            message=body.message,
        )
        return {"code": 0, "msg": "ok", "data": _to_dict(alert)}
    except Exception as e:
        log.error("create_alert error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{alert_id}")
def delete_alert(alert_id: int):
    """Cancel/delete an alert."""
    try:
        repo = create_alert_repository()
        alert = repo.cancel_alert(alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
        return {"code": 0, "msg": "ok", "data": {"id": alert_id, "status": "cancelled"}}
    except HTTPException:
        raise
    except Exception as e:
        log.error("delete_alert error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check/{symbol}")
def check_alerts(symbol: str):
    """
    Check active alerts for a symbol against the latest close price.
    Triggers any alerts whose condition is met, returns the triggered list.
    """
    try:
        repo = create_alert_repository()

        # 1. Get latest close price from stock_ohlcv
        current_price = repo.get_latest_price(symbol)

        if current_price is None:
            return {"code": 0, "msg": "ok", "data": {
                "symbol": symbol,
                "current_price": None,
                "triggered_alerts": [],
            }}

        # 2. Find all active alerts for this symbol
        active_alerts = repo.get_active_by_symbol(symbol)

        triggered = []
        for alert in active_alerts:
            should_trigger = False
            if alert.direction == "above" and current_price >= alert.target_price:
                should_trigger = True
            elif alert.direction == "below" and current_price <= alert.target_price:
                should_trigger = True

            if should_trigger:
                updated = repo.trigger_alert(alert.id)
                triggered.append(_to_dict(updated))
                log.warning(
                    "[PRICE_ALERT_TRIGGERED] symbol=%s target=%.2f direction=%s current=%.2f",
                    symbol, alert.target_price, alert.direction, current_price,
                )

        return {"code": 0, "msg": "ok", "data": {
            "symbol": symbol,
            "current_price": current_price,
            "triggered_alerts": triggered,
        }}
    except Exception as e:
        log.error("check_alerts error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
#  P1b 指标级告警（metric_alerts）
#  支持 PE_TTM/PB/PS_TTM/股息率/ROE 跨阈值触发。
# ════════════════════════════════════════════════════════════════════════════

from src.infra.database.alert.entity import METRIC_ALERT_KINDS


class MetricAlertCreate(BaseModel):
    """创建指标告警请求。"""
    symbol: str
    metric_kind: str          # pe_ttm / pb / ps_ttm / dv_ttm / roe
    threshold: float          # 阈值
    direction: str            # above | below
    message: Optional[str] = None

    @field_validator("direction")
    @classmethod
    def direction_valid(cls, v: str) -> str:
        if v not in ("above", "below"):
            raise ValueError("direction 必须是 above 或 below")
        return v

    @field_validator("metric_kind")
    @classmethod
    def metric_kind_valid(cls, v: str) -> str:
        if v not in METRIC_ALERT_KINDS:
            raise ValueError(f"metric_kind 必须是 {list(METRIC_ALERT_KINDS)} 之一")
        return v


def _to_metric_dict(alert) -> dict:
    """MetricAlertTable → API dict。"""
    return {
        "id": alert.id,
        "symbol": alert.symbol,
        "metric_kind": alert.metric_kind,
        "threshold": alert.threshold,
        "direction": alert.direction,
        "status": alert.status,
        "message": alert.message,
        "triggered_at": str(alert.triggered_at) if alert.triggered_at else None,
        "created_at": str(alert.created_at),
    }


@router.get("/metrics")
def list_metric_alerts(
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """列出指标告警。"""
    try:
        repo = create_alert_repository()
        alerts = repo.list_metric_alerts(status=status, limit=limit, offset=offset)
        return {
            "code": 0, "msg": "ok",
            "data": [_to_metric_dict(a) for a in alerts],
            "limit": limit, "offset": offset,
        }
    except Exception as e:
        log.error("list_metric_alerts error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/metrics")
def create_metric_alert(body: MetricAlertCreate):
    """创建指标告警。"""
    try:
        repo = create_alert_repository()
        alert = repo.create_metric_alert(
            symbol=body.symbol,
            metric_kind=body.metric_kind,
            threshold=body.threshold,
            direction=body.direction,
            message=body.message,
        )
        return {"code": 0, "msg": "ok", "data": _to_metric_dict(alert)}
    except Exception as e:
        log.error("create_metric_alert error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/metrics/{alert_id}")
def delete_metric_alert(alert_id: int):
    """取消指标告警。"""
    try:
        repo = create_alert_repository()
        alert = repo.cancel_metric_alert(alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail=f"指标告警 {alert_id} 不存在")
        return {"code": 0, "msg": "ok", "data": {"id": alert_id, "status": "cancelled"}}
    except HTTPException:
        raise
    except Exception as e:
        log.error("delete_metric_alert error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/check/{symbol}")
def check_metric_alerts(symbol: str):
    """检查某股的所有 active 指标告警，触发命中条件的。"""
    try:
        repo = create_alert_repository()
        active = [a for a in repo.get_active_metric_alerts() if a.symbol == symbol]
        if not active:
            return {"code": 0, "msg": "ok", "data": {
                "symbol": symbol, "triggered_alerts": [], "current_values": {},
            }}

        # 取每个 metric_kind 的最新值（去重避免重复查询）
        triggered = []
        current_values: dict = {}
        for alert in active:
            mk = alert.metric_kind
            if mk not in current_values:
                current_values[mk] = repo.get_latest_metric_value(symbol, mk)
            cur = current_values[mk]
            if cur is None:
                continue
            hit = False
            if alert.direction == "above" and cur >= alert.threshold:
                hit = True
            elif alert.direction == "below" and cur <= alert.threshold:
                hit = True
            if hit:
                updated = repo.trigger_metric_alert(alert.id)
                triggered.append(_to_metric_dict(updated))
                log.warning(
                    "[METRIC_ALERT_TRIGGERED] %s %s %s %.2f current=%.2f",
                    symbol, mk, alert.direction, alert.threshold, cur,
                )

        return {"code": 0, "msg": "ok", "data": {
            "symbol": symbol,
            "triggered_alerts": triggered,
            "current_values": current_values,
        }}
    except Exception as e:
        log.error("check_metric_alerts error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
