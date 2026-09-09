"""
系统路由
=========
GET /system/health   → {"status": "ok", "db": "up", "data": {...}}
GET /system/status   → 回补进度、数据库状态、Sina API 状态
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/system", tags=["system"])

from src.infra.database.sql_engine.dsn import get_dsn


# ── 响应模型 ────────────────────────────────────────────────────────────────
class DBHealth(BaseModel):
    connected: bool
    version: Optional[str] = None
    total_tables: int


class DataCoverage(BaseModel):
    market: str
    symbols: int
    bars: int
    earliest: Optional[str] = None
    latest: Optional[str] = None
    minute_intervals: list[str] = []


class BackfillProgress(BaseModel):
    last_backfill_time: Optional[str] = None
    symbols_covered: int
    total_symbols: int
    coverage_pct: float


class SystemHealth(BaseModel):
    status: str       # ok / degraded / error
    db: str           # up / down
    db_detail: DBHealth
    timestamp: str


class SystemStatus(BaseModel):
    db: DBHealth
    data: dict
    backfill: BackfillProgress
    timestamp: str


# ── DB helpers ───────────────────────────────────────────────────────────────
def _get_conn():
    return psycopg2.connect(get_dsn())


def _db_health() -> DBHealth:
    """检查数据库健康状态"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT version()")
                version = str(cur.fetchone()["version"])
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                total_tables = int(cur.fetchone()["cnt"])
                return DBHealth(connected=True, version=version, total_tables=total_tables)
        finally:
            conn.close()
    except Exception:
        return DBHealth(connected=False)


def _data_coverage() -> dict:
    """各市场数据覆盖情况"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT market,
                           COUNT(DISTINCT symbol) AS symbols,
                           COUNT(*) AS bars,
                           MIN(trade_date::date) AS earliest,
                           MAX(trade_date::date) AS latest
                    FROM stock_ohlcv
                    GROUP BY market
                    ORDER BY market
                    """
                )
                markets = [
                    {
                        "market": r["market"],
                        "symbols": r["symbols"],
                        "bars": r["bars"],
                        "earliest": str(r["earliest"]) if r["earliest"] else None,
                        "latest": str(r["latest"]) if r["latest"] else None,
                    }
                    for r in cur.fetchall()
                ]

                cur.execute(
                    "SELECT DISTINCT interval FROM stock_ohlcv_minute ORDER BY interval"
                )
                minute_intervals = [str(r["interval"]) for r in cur.fetchall()]

                return {"markets": markets, "minute_intervals": minute_intervals}
        finally:
            conn.close()
    except Exception as e:
        return {"error": str(e)}


def _backfill_progress() -> BackfillProgress:
    """回补进度估算"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT COUNT(DISTINCT symbol) as cnt FROM stock_ohlcv"
                )
                symbols_covered = int(cur.fetchone()["cnt"])

                # 估算 A 股总数（假设已覆盖的即为目标）
                # 用 covered 作为分母近似
                cur.execute(
                    "SELECT COUNT(DISTINCT symbol) as total FROM stock_ohlcv"
                )
                total = int(cur.fetchone()["cnt"])

                # 最近一条数据的时间
                cur.execute(
                    "SELECT MAX(trade_date::date) as last_dt FROM stock_ohlcv"
                )
                row = cur.fetchone()
                last_backfill_time = str(row["last_dt"]) if row and row["last_dt"] else None

                coverage_pct = round(symbols_covered / total * 100, 2) if total else 0.0

                return BackfillProgress(
                    last_backfill_time=last_backfill_time,
                    symbols_covered=symbols_covered,
                    total_symbols=total,
                    coverage_pct=coverage_pct,
                )
        finally:
            conn.close()
    except Exception:
        return BackfillProgress(
            last_backfill_time=None,
            symbols_covered=0,
            total_symbols=0,
            coverage_pct=0.0,
        )


# ── API 端点 ─────────────────────────────────────────────────────────────────

@router.get("/health", response_model=dict)
def health_check():
    """
    健康检查
    返回整体状态、数据库连接状态
    """
    db_detail = _db_health()
    status = "ok" if db_detail.connected else "error"
    db_status = "up" if db_detail.connected else "down"

    return {
        "code": 0,
        "msg": "ok",
        "data": SystemHealth(
            status=status,
            db=db_status,
            db_detail=db_detail,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    }


@router.get("/status", response_model=dict)
def system_status():
    """
    系统状态
    返回数据库详情、数据覆盖情况、回补进度
    """
    db_detail = _db_health()
    data = _data_coverage()
    backfill = _backfill_progress()

    return {
        "code": 0,
        "msg": "ok",
        "data": SystemStatus(
            db=db_detail,
            data=data,
            backfill=backfill,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    }


# ── Scheduler ──────────────────────────────────────────────────────────────────

@router.get("/scheduler", response_model=dict)
def get_scheduler_status():
    """定时任务调度器状态。"""
    from src.infra.scheduler import get_status
    return {"code": 0, "msg": "ok", "data": get_status()}
