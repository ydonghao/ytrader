"""
Price alert & metric alert SQLModel table definitions.

metric_alerts（P1b）：指标级告警，支持 PE_TTM/PB/PS_TTM/股息率/ROE 等指标
跨过阈值时触发。与 price_alerts 分离，避免迁移现有价格告警表。
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Index, func
from sqlmodel import SQLModel, Field


class PriceAlertTable(SQLModel, table=True):
    __tablename__ = "price_alerts"
    __table_args__ = (
        # 覆盖 list_alerts(status=?) ORDER BY created_at DESC 的常见查询
        Index("idx_price_alerts_status_created", "status", "created_at"),
        # 覆盖 get_active_alerts 按 symbol 过滤
        Index("idx_price_alerts_symbol_status", "symbol", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str
    target_price: float
    direction: str  # 'above' or 'below'
    status: str = Field(default="active")  # active / triggered / cancelled
    message: Optional[str] = Field(default=None)
    triggered_at: Optional[datetime] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── P1b 指标告警支持的指标（值取自 stock_valuation / stock_financials） ──
METRIC_ALERT_KINDS = ("pe_ttm", "pb", "ps_ttm", "dv_ttm", "roe")


class MetricAlertTable(SQLModel, table=True):
    """指标级告警：当某股的指定指标跨过阈值时触发。

    与 PriceAlertTable 分离：metric_kind 标识指标类型，
    threshold 是阈值，direction 标识穿越方向（above=向上突破/below=向下跌破）。
    """
    __tablename__ = "metric_alerts"
    __table_args__ = (
        Index("idx_metric_alerts_status_created", "status", "created_at"),
        Index("idx_metric_alerts_symbol_status", "symbol", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str
    metric_kind: str        # pe_ttm / pb / ps_ttm / dv_ttm / roe
    threshold: float        # 阈值
    direction: str          # 'above'（指标 >= 阈值触发）| 'below'（<= 阈值触发）
    status: str = Field(default="active")  # active / triggered / cancelled
    message: Optional[str] = Field(default=None)
    triggered_at: Optional[datetime] = None
    created_at: datetime = Field(
        sa_column=Column(DateTime, server_default=func.now(), nullable=False)
    )
