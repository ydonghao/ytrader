"""Price alert repository implementation."""
import threading
from datetime import date, datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlmodel import select

from src.infra.database.alert.entity import PriceAlertTable, MetricAlertTable
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn


# ═══════════════════════════════════════════
# Repository
# ═══════════════════════════════════════════

class AlertRepository:
    """Price alert CRUD operations using SQLModel."""

    def __init__(self, db_connection: DBConnection):
        self._db = db_connection

    # ── Read ──────────────────────────────────────────────────────

    def list_alerts(
        self,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[PriceAlertTable]:
        """列出价格提醒（默认上限 200，避免持续增长的表全量返回）。"""
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self._db.session_scope() as session:
            stmt = select(PriceAlertTable).order_by(
                PriceAlertTable.created_at.desc()
            )
            if status:
                stmt = stmt.where(PriceAlertTable.status == status)
            stmt = stmt.offset(offset).limit(limit)
            return list(session.exec(stmt).all())

    def get_by_id(self, alert_id: int) -> Optional[PriceAlertTable]:
        with self._db.session_scope() as session:
            return session.exec(
                select(PriceAlertTable).where(
                    PriceAlertTable.id == alert_id
                )
            ).first()

    def get_active_alerts(self) -> list[PriceAlertTable]:
        with self._db.session_scope() as session:
            return list(
                session.exec(
                    select(PriceAlertTable).where(
                        PriceAlertTable.status == "active"
                    )
                ).all()
            )

    def get_active_by_symbol(
        self, symbol: str
    ) -> list[PriceAlertTable]:
        with self._db.session_scope() as session:
            return list(
                session.exec(
                    select(PriceAlertTable).where(
                        PriceAlertTable.symbol == symbol,
                        PriceAlertTable.status == "active",
                    )
                ).all()
            )

    # ── Write ─────────────────────────────────────────────────────

    def create_alert(
        self,
        symbol: str,
        target_price: float,
        direction: str,
        message: Optional[str] = None,
    ) -> PriceAlertTable:
        alert = PriceAlertTable(
            symbol=symbol,
            target_price=target_price,
            direction=direction,
            message=message,
        )
        with self._db.session_scope() as session:
            session.add(alert)
            session.refresh(alert)
            return alert

    def cancel_alert(self, alert_id: int) -> Optional[PriceAlertTable]:
        with self._db.session_scope() as session:
            alert = session.exec(
                select(PriceAlertTable).where(
                    PriceAlertTable.id == alert_id
                )
            ).first()
            if not alert:
                return None
            alert.status = "cancelled"
            session.add(alert)
            session.refresh(alert)
            return alert

    def trigger_alert(self, alert_id: int) -> Optional[PriceAlertTable]:
        with self._db.session_scope() as session:
            alert = session.exec(
                select(PriceAlertTable).where(
                    PriceAlertTable.id == alert_id
                )
            ).first()
            if not alert:
                return None
            alert.status = "triggered"
            alert.triggered_at = datetime.now(timezone.utc)
            session.add(alert)
            session.refresh(alert)
            return alert

    # ── Metrics ───────────────────────────────────────────────────

    def get_alert_metrics(self, end_date: date) -> dict:
        active = 0
        triggered_today = 0
        try:
            with self._db.session_scope() as session:
                row = session.exec(
                    text(
                        "SELECT COUNT(*) AS cnt FROM price_alerts "
                        "WHERE status = 'active'"
                    )
                ).first()
                active = row[0] if row else 0

                row = session.exec(
                    text(
                        "SELECT COUNT(*) AS cnt FROM price_alerts "
                        "WHERE status = 'triggered' "
                        "AND DATE(triggered_at) = :end_date"
                    ),
                    params={"end_date": end_date.isoformat()},
                ).first()
                triggered_today = row[0] if row else 0
        except Exception as e:
            logger.warning("[alert_db] get_alert_metrics error: {}", e)
        return {"active_count": active, "triggered_today": triggered_today}

    # ── stock_ohlcv (no SQLModel table — raw SQL) ─────────────────

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get latest close_ from stock_ohlcv for the given symbol."""
        with self._db.session_scope() as session:
            row = session.exec(
                text(
                    "SELECT close_ FROM stock_ohlcv "
                    "WHERE symbol = :symbol "
                    "ORDER BY trade_date DESC LIMIT 1"
                ),
                params={"symbol": symbol},
            ).first()
            return float(row[0]) if row else None

    # ═══════════════════════════════════════════
    # P1b 指标级告警（metric_alerts 表）
    # ═══════════════════════════════════════════

    def list_metric_alerts(
        self,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[MetricAlertTable]:
        """列指标告警（默认上限 200）。"""
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self._db.session_scope() as session:
            stmt = select(MetricAlertTable).order_by(
                MetricAlertTable.created_at.desc()
            )
            if status:
                stmt = stmt.where(MetricAlertTable.status == status)
            stmt = stmt.offset(offset).limit(limit)
            rows = list(session.exec(stmt).all())
            for r in rows:
                session.expunge(r)
            return rows

    def get_metric_by_id(self, alert_id: int) -> Optional[MetricAlertTable]:
        with self._db.session_scope() as session:
            row = session.exec(
                select(MetricAlertTable).where(
                    MetricAlertTable.id == alert_id
                )
            ).first()
            if row:
                session.expunge(row)
            return row

    def get_active_metric_alerts(self) -> list[MetricAlertTable]:
        with self._db.session_scope() as session:
            rows = list(
                session.exec(
                    select(MetricAlertTable).where(
                        MetricAlertTable.status == "active"
                    )
                ).all()
            )
            for r in rows:
                session.expunge(r)
            return rows

    def create_metric_alert(
        self,
        symbol: str,
        metric_kind: str,
        threshold: float,
        direction: str,
        message: Optional[str] = None,
    ) -> MetricAlertTable:
        alert = MetricAlertTable(
            symbol=symbol,
            metric_kind=metric_kind,
            threshold=threshold,
            direction=direction,
            message=message,
        )
        with self._db.session_scope() as session:
            session.add(alert)
            session.flush()           # 让 DB 生成 id / created_at
            session.refresh(alert)    # 回读 DB 生成的值
            session.expunge(alert)    # 脱离 session，避免返回后 detached 报错
            return alert

    def cancel_metric_alert(self, alert_id: int) -> Optional[MetricAlertTable]:
        with self._db.session_scope() as session:
            alert = session.exec(
                select(MetricAlertTable).where(
                    MetricAlertTable.id == alert_id
                )
            ).first()
            if not alert:
                return None
            alert.status = "cancelled"
            session.add(alert)
            session.flush()
            session.refresh(alert)
            session.expunge(alert)
            return alert

    def trigger_metric_alert(self, alert_id: int) -> Optional[MetricAlertTable]:
        with self._db.session_scope() as session:
            alert = session.exec(
                select(MetricAlertTable).where(
                    MetricAlertTable.id == alert_id
                )
            ).first()
            if not alert:
                return None
            alert.status = "triggered"
            alert.triggered_at = datetime.now(timezone.utc)
            session.add(alert)
            session.flush()
            session.refresh(alert)
            session.expunge(alert)
            return alert

    def get_latest_metric_value(
        self, symbol: str, metric_kind: str
    ) -> Optional[float]:
        """取个股最新指标值。

        pe_ttm/pb/ps_ttm/dv_ttm 取自 stock_valuation 最新一行；
        roe 取自 stock_financials 最新一行。
        """
        col_map = {
            "pe_ttm": "pe_ttm", "pb": "pb",
            "ps_ttm": "ps_ttm", "dv_ttm": "dv_ttm",
        }
        with self._db.session_scope() as session:
            if metric_kind in col_map:
                row = session.execute(
                    text(
                        f"SELECT {col_map[metric_kind]} FROM stock_valuation "
                        "WHERE symbol = :symbol "
                        "ORDER BY trade_date DESC LIMIT 1"
                    ),
                    {"symbol": symbol},
                ).first()
                return float(row[0]) if row and row[0] is not None else None
            elif metric_kind == "roe":
                row = session.execute(
                    text(
                        "SELECT roe_weighted FROM stock_financials "
                        "WHERE symbol = :symbol "
                        "ORDER BY report_date DESC LIMIT 1"
                    ),
                    {"symbol": symbol},
                ).first()
                return float(row[0]) if row and row[0] is not None else None
        return None


# ═══════════════════════════════════════════
# Singleton + Factory
# ═══════════════════════════════════════════

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_alert_repository(
    db_connection: DBConnection | None = None,
) -> AlertRepository:
    return AlertRepository(db_connection or _get_db_connection())
