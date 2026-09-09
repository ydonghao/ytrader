"""
策略路由
=========
GET  /strategy/strategies          → 策略列表
GET  /strategy/strategies/{id}     → 单个策略详情
POST /strategy/strategies          → 创建策略
PUT  /strategy/strategies/{id}     → 更新策略
DELETE /strategy/strategies/{id}   → 删除策略
GET  /strategy/backtest/{id}       → 回测结果（从 backtest_results 表读）
POST /strategy/backtest            → 发起回测（异步）
"""
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/strategy", tags=["strategy"])

from src.infra.database.sql_engine.dsn import get_dsn
log = logging.getLogger(__name__)

# ── backtest_results 表不存在则自动创建 ─────────────────────────────────────
_BACKTEST_RESULTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS backtest_results (
    id              SERIAL PRIMARY KEY,
    strategy_id     INTEGER REFERENCES strategies(id) ON DELETE SET NULL,
    strategy_name   TEXT NOT NULL,
    symbols         TEXT[] NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    initial_capital REAL NOT NULL DEFAULT 1000000,
    final_equity    REAL NOT NULL DEFAULT 0,
    total_return    REAL NOT NULL DEFAULT 0,
    sharpe_ratio    REAL NOT NULL DEFAULT 0,
    max_drawdown    REAL NOT NULL DEFAULT 0,
    max_drawdown_duration_days INTEGER NOT NULL DEFAULT 0,
    win_rate        REAL NOT NULL DEFAULT 0,
    profit_factor   REAL NOT NULL DEFAULT 0,
    total_trades    INTEGER NOT NULL DEFAULT 0,
    winning_trades  INTEGER NOT NULL DEFAULT 0,
    losing_trades   INTEGER NOT NULL DEFAULT 0,
    avg_trade_return REAL NOT NULL DEFAULT 0,
    avg_holding_days REAL NOT NULL DEFAULT 0,
    equity_curve    JSONB DEFAULT '[]'::jsonb,
    trades          JSONB DEFAULT '[]'::jsonb,
    errors          TEXT[] DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'running',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _ensure_backtest_results_table() -> None:
    """确保 backtest_results 表存在（每进程首个用到该表的请求执行一次）"""
    global _BACKTEST_TABLE_READY
    if _BACKTEST_TABLE_READY:
        return
    with _BACKTEST_TABLE_LOCK:
        if _BACKTEST_TABLE_READY:
            return
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(_BACKTEST_RESULTS_TABLE_SQL)
            conn.commit()
        finally:
            conn.close()
        _BACKTEST_TABLE_READY = True


# 原来在模块导入时直接建表（经 src/api/router/__init__ 链路，任何 import
# 该包的测试/工具都会触库，DB 不可用时应用起不来）；改为懒执行。
_BACKTEST_TABLE_READY = False
_BACKTEST_TABLE_LOCK = threading.Lock()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────
class StrategyItem(BaseModel):
    id: int
    name: str
    type: str
    config: dict
    description: Optional[str]
    status: str
    created_by: Optional[int]
    created_at: str
    updated_at: str


class StrategyCreateRequest(BaseModel):
    name: str
    type: str
    config: dict = {}
    description: Optional[str] = None
    status: str = "active"
    created_by: Optional[int] = None


class StrategyUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    config: Optional[dict] = None
    description: Optional[str] = None
    status: Optional[str] = None


class BacktestResultItem(BaseModel):
    id: int
    strategy_id: Optional[int]
    strategy_name: str
    symbols: list[str]
    start_date: str
    end_date: str
    initial_capital: float
    final_equity: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_duration_days: int
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_trade_return: float
    avg_holding_days: float
    equity_curve: list
    trades: list
    errors: list[str]
    status: str
    created_at: str


class BacktestCreateRequest(BaseModel):
    strategy_id: Optional[int] = None  # None = create temp strategy from strategy_type
    symbols: Optional[list[str]] = None  # backend internal format
    symbol: Optional[str] = None  # frontend format (single symbol string)
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    slippage: float = 0.0001
    strategy_type: Optional[str] = None  # frontend strategy type (e.g. "SMA_CROSS")
    interval: Optional[str] = "1d"  # accepted but ignored (daily only for now)

    def resolved_symbols(self) -> list[str]:
        if self.symbol:
            return [self.symbol]
        return self.symbols or []

    def resolved_strategy_type(self) -> str:
        # Map frontend strategy_type names to backend strategy names
        mapping = {
            "SMA_CROSS": "sma_cross",
            "RSI": "rsi",
            "MACD": "macd",
            "BOLLINGER": "bollinger",
            "GRID": "sma_cross",
            "MOMENTUM": "macd",
            "MEAN_REVERSION": "rsi",
        }
        if self.strategy_type:
            return mapping.get(self.strategy_type.upper().replace("-", "_"), "sma_cross")
        return "sma_cross"


# ── DB helpers ────────────────────────────────────────────────────────────────
def _get_conn():
    return psycopg2.connect(get_dsn())


# ── 策略 CRUD ───────────────────────────────────────────────────────────────

@router.get("/strategies", response_model=dict)
def list_strategies(
    status: Optional[str] = None,
    limit: int = 100,
):
    """策略列表"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sql = """
                    SELECT id, name, type, config, description, status,
                           created_by, created_at, updated_at
                    FROM strategies
                    WHERE 1=1
                """
                params: list = []
                if status:
                    sql += " AND status = %s"
                    params.append(status)
                sql += " ORDER BY updated_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                items = [
                    StrategyItem(
                        id=r["id"],
                        name=r["name"],
                        type=r["type"],
                        config=r["config"] or {},
                        description=r["description"],
                        status=r["status"],
                        created_by=r["created_by"],
                        created_at=str(r["created_at"]),
                        updated_at=str(r["updated_at"]),
                    )
                    for r in rows
                ]
                return {"code": 0, "msg": "ok", "data": items, "total": len(items)}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies/{strategy_id}", response_model=dict)
def get_strategy(strategy_id: int):
    """单个策略详情"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, name, type, config, description, status,
                           created_by, created_at, updated_at
                    FROM strategies
                    WHERE id = %s
                    """,
                    (strategy_id,),
                )
                r = cur.fetchone()
                if not r:
                    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
                item = StrategyItem(
                    id=r["id"],
                    name=r["name"],
                    type=r["type"],
                    config=r["config"] or {},
                    description=r["description"],
                    status=r["status"],
                    created_by=r["created_by"],
                    created_at=str(r["created_at"]),
                    updated_at=str(r["updated_at"]),
                )
                return {"code": 0, "msg": "ok", "data": item}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategies", response_model=dict)
def create_strategy(req: StrategyCreateRequest):
    """创建策略"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO strategies (name, type, config, description, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, name, type, config, description, status,
                              created_by, created_at, updated_at
                    """,
                    (req.name, req.type, json.dumps(req.config), req.description, req.status, req.created_by),
                )
                r = dict(cur.fetchone())
                conn.commit()
                item = StrategyItem(
                    id=r["id"],
                    name=r["name"],
                    type=r["type"],
                    config=r["config"] or {},
                    description=r["description"],
                    status=r["status"],
                    created_by=r["created_by"],
                    created_at=str(r["created_at"]),
                    updated_at=str(r["updated_at"]),
                )
                return {"code": 0, "msg": "ok", "data": item}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/strategies/{strategy_id}", response_model=dict)
def update_strategy(strategy_id: int, req: StrategyUpdateRequest):
    """更新策略"""
    try:
        # 先检查存在
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM strategies WHERE id = %s", (strategy_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

            # 构建动态更新
            fields, params = [], []
            if req.name is not None:
                fields.append("name = %s")
                params.append(req.name)
            if req.type is not None:
                fields.append("type = %s")
                params.append(req.type)
            if req.config is not None:
                fields.append("config = %s")
                params.append(json.dumps(req.config))
            if req.description is not None:
                fields.append("description = %s")
                params.append(req.description)
            if req.status is not None:
                fields.append("status = %s")
                params.append(req.status)
            fields.append("updated_at = NOW()")
            params.append(strategy_id)

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    UPDATE strategies SET {', '.join(fields)}
                    WHERE id = %s
                    RETURNING id, name, type, config, description, status,
                              created_by, created_at, updated_at
                    """,
                    params,
                )
                r = dict(cur.fetchone())
                conn.commit()
                item = StrategyItem(
                    id=r["id"],
                    name=r["name"],
                    type=r["type"],
                    config=r["config"] or {},
                    description=r["description"],
                    status=r["status"],
                    created_by=r["created_by"],
                    created_at=str(r["created_at"]),
                    updated_at=str(r["updated_at"]),
                )
                return {"code": 0, "msg": "ok", "data": item}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/strategies/{strategy_id}", response_model=dict)
def delete_strategy(strategy_id: int):
    """删除策略"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM strategies WHERE id = %s RETURNING id",
                    (strategy_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
                conn.commit()
                return {"code": 0, "msg": "ok", "data": {"id": strategy_id}}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 回测结果 ───────────────────────────────────────────────────────────────

@router.get("/backtest_results", response_model=dict)
def list_backtest_results(limit: int = 20, status: Optional[str] = None):
    _ensure_backtest_results_table()
    """列出回测结果历史"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sql = """
                    SELECT id, strategy_id, strategy_name, symbols, start_date, end_date,
                           initial_capital, final_equity, total_return, sharpe_ratio,
                           max_drawdown, max_drawdown_duration_days, win_rate, profit_factor,
                           total_trades, winning_trades, losing_trades,
                           avg_trade_return, avg_holding_days,
                           equity_curve, trades, errors, status, created_at
                    FROM backtest_results
                    WHERE 1=1
                """
                params: list = []
                if status:
                    sql += " AND status = %s"
                    params.append(status)
                sql += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                items = []
                for r in rows:
                    initial = float(r["initial_capital"] or 1)
                    final = float(r["final_equity"] or initial)
                    total_return_raw = float(r["total_return"] or 0)
                    items.append({
                        "id": r["id"],
                        "strategy_id": str(r["strategy_id"]) if r["strategy_id"] else None,
                        "strategy_name": r["strategy_name"],
                        "status": r["status"] or "UNKNOWN",
                        "initial_capital": initial,
                        "final_capital": final,
                        "total_return": total_return_raw,
                        "sharpe_ratio": float(r["sharpe_ratio"] or 0),
                        "max_drawdown": float(r["max_drawdown"] or 0),
                        "win_rate": float(r["win_rate"] or 0),
                        "total_trades": r["total_trades"] or 0,
                        "equity_curve": r["equity_curve"] or [],
                        "trades": r["trades"] or [],
                        "errors": r["errors"] or [],
                        "created_at": str(r["created_at"]),
                    })
                return {"code": 0, "msg": "ok", "data": items, "total": len(items)}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backtest/{result_id}", response_model=dict)
def get_backtest_result(result_id: int):
    """获取回测结果"""
    _ensure_backtest_results_table()
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, strategy_id, strategy_name, symbols, start_date, end_date,
                           initial_capital, final_equity, total_return, sharpe_ratio,
                           max_drawdown, max_drawdown_duration_days, win_rate, profit_factor,
                           total_trades, winning_trades, losing_trades,
                           avg_trade_return, avg_holding_days,
                           equity_curve, trades, errors, status, created_at
                    FROM backtest_results
                    WHERE id = %s
                    """,
                    (result_id,),
                )
                r = cur.fetchone()
                if not r:
                    raise HTTPException(status_code=404, detail=f"Backtest result {result_id} not found")
                # Normalize to match frontend BacktestPanelResultData
                equity_raw = r["equity_curve"] or []
                equity_curve_normalized = [
                    {"timestamp": int(str(v[0]).replace("-", "").replace(":", "").replace(" ", "")[:14]) if isinstance(v, (list, tuple)) else 0,
                     "value": float(v[1]) if isinstance(v, (list, tuple)) else float(v)}
                    for v in equity_raw
                ]

                trades_raw = r["trades"] or []
                trades_normalized = []
                for i, t in enumerate(trades_raw):
                    side = "BUY" if str(t.get("action", "")).upper() in ("BUY", "LONG", "BUY_TO_OPEN") else "SELL"
                    ts_str = str(t.get("timestamp", ""))
                    ts_int = int(ts_str.replace("-", "").replace(":", "").replace(" ", "")[:14]) if ts_str else 0
                    trades_normalized.append({
                        "id": f"trade-{i}",
                        "timestamp": ts_int,
                        "side": side,
                        "price": float(t.get("price", 0)),
                        "quantity": float(t.get("quantity", 0)),
                        "pnl": float(t.get("pnl", 0) or 0),
                    })

                initial = float(r["initial_capital"] or 1)
                final = float(r["final_equity"] or initial)
                total_return_raw = float(r["total_return"] or 0)
                # If total_return looks like a ratio (0.05 = 5%), convert to percent
                total_return_percent = total_return_raw * 100 if abs(total_return_raw) < 100 else total_return_raw

                item = {
                    "id": r["id"],
                    "strategy_id": str(r["strategy_id"]) if r["strategy_id"] else None,
                    "status": r["status"] or "UNKNOWN",
                    "initial_capital": initial,
                    "final_capital": final,
                    "total_return": total_return_raw,
                    "total_return_percent": total_return_percent,
                    "sharpe_ratio": float(r["sharpe_ratio"] or 0),
                    "max_drawdown": float(r["max_drawdown"] or 0),
                    "win_rate": float(r["win_rate"] or 0),
                    "total_trades": r["total_trades"] or 0,
                    "equity_curve": equity_curve_normalized,
                    "trades": trades_normalized,
                }
                return {"code": 0, "msg": "ok", "data": item}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backtest", response_model=dict)
def submit_backtest(req: BacktestCreateRequest):
    """
    发起回测（异步）

    返回回测任务 ID（backtest_result.id），status='running'
    后台线程执行 Backtester.run_multi，完成后更新 status='completed'
    """
    # 1. 校验策略或创建临时策略
    _ensure_backtest_results_table()
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if req.strategy_id is not None:
                    cur.execute(
                        "SELECT id, name, type, config FROM strategies WHERE id = %s",
                        (req.strategy_id,),
                    )
                    strat_row = cur.fetchone()
                    if not strat_row:
                        raise HTTPException(status_code=404, detail=f"Strategy {req.strategy_id} not found")
                else:
                    # 创建临时策略（使用前端指定的 strategy_type 或默认 sma_cross）
                    strat_type = req.resolved_strategy_type()
                    cur.execute(
                        """INSERT INTO strategies (name, type, config, status)
                           VALUES (%s, %s, %s, 'active')
                           RETURNING id, name, type, config""",
                        (f"_temp_{strat_type}", strat_type,
                         json.dumps({"fast_period": 5, "slow_period": 20})),
                    )
                    strat_row = cur.fetchone()
        finally:
            conn.close()
    except HTTPException:
        raise

    # 2. 创建回测记录（running）
    try:
        conn = _get_conn()
        run_id: int = 0
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO backtest_results
                        (strategy_id, strategy_name, symbols, start_date, end_date,
                         initial_capital, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'running')
                    RETURNING id
                    """,
                    (
                        req.strategy_id,
                        strat_row["name"],
                        req.resolved_symbols(),
                        req.start_date,
                        req.end_date,
                        req.initial_capital,
                    ),
                )
                run_id = cur.fetchone()["id"]
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 3. 后台线程执行回测
    def _run_backtest_async(run_id: int, req: BacktestCreateRequest, strat_row: dict) -> None:
        """后台回测线程"""
        try:
            from src.domain.market.strategy.backtester import Backtester
            from src.domain.market.strategy.strategies import get_strategy
            from src.api.router.market_router import fetch_kline

            # 构建策略实例
            # strat_row["type"] is the strategy class key (e.g. "sma_cross")
            # strat_row["name"] is the display name
            # strat_row["config"] is the jsonb config (fast_period, slow_period, etc.)
            # Pass type as positional arg (strategy class name), name separately,
            # and config kwargs but exclude 'name' to avoid double-pass error.
            # get_strategy(class_name: str, **config_kwargs) — class_name is positional,
            # all config fields (fast_period, slow_period, etc.) as keyword args.
            # NOTE: strategy classes do NOT accept a "name" kwarg, so don't pass it.
            strat_config = dict(strat_row["config"] or {})
            # Remove 'name' key from config (classes don't accept it; it's a class attr)
            strat_config.pop("name", None)
            strategy = get_strategy(
                strat_row["type"],  # e.g. "sma_cross"
                **strat_config,
            )

            # 拉取各标的 K 线
            all_bars: list = []
            for sym in req.resolved_symbols():
                bars = fetch_kline(sym, start_date=req.start_date, end_date=req.end_date, interval="1d")
                for b in bars:
                    from src.domain.market.sync.sync_provider import OHLCVBar
                    bar = OHLCVBar(
                        symbol=sym,
                        trade_time=str(b["trade_date"]) + " 15:00:00",
                        open_=float(b["open_"]),
                        close_=float(b["close_"]),
                        high_=float(b["high_"]),
                        low_=float(b["low_"]),
                        volume=float(b["volume"]),
                        amount=float(b.get("amount", 0)),
                    )
                    all_bars.append(bar)

            if not all_bars:
                raise RuntimeError(f"No bars fetched for symbols: {req.resolved_symbols()}")

            # 按 symbol 分组
            from collections import defaultdict
            bars_by_symbol: dict = defaultdict(list)
            for b in all_bars:
                bars_by_symbol[b.symbol].append(b)

            # 运行回测
            bt = Backtester(
                initial_capital=req.initial_capital,
                commission_rate=req.commission_rate,
                slippage=req.slippage,
            )
            result = bt.run_multi(
                strategy=strategy,
                bars_by_symbol=dict(bars_by_symbol),
                start_date=req.start_date,
                end_date=req.end_date,
            )

            # 序列化 equity_curve 和 trades
            equity_curve_serializable = [
                [str(ts), float(val)] for ts, val in (result.equity_curve or [])
            ]
            trades_serializable = [
                {
                    "symbol": t.symbol,
                    "action": t.action.value if hasattr(t.action, "value") else str(t.action),
                    "price": float(t.price),
                    "quantity": t.quantity,
                    "timestamp": str(t.timestamp),
                    "pnl": float(t.pnl) if t.pnl else 0.0,
                }
                for t in (result.trades or [])
            ]

            conn2 = psycopg2.connect(get_dsn())
            try:
                with conn2.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE backtest_results SET
                            final_equity = %s,
                            total_return = %s,
                            sharpe_ratio = %s,
                            max_drawdown = %s,
                            max_drawdown_duration_days = %s,
                            win_rate = %s,
                            profit_factor = %s,
                            total_trades = %s,
                            winning_trades = %s,
                            losing_trades = %s,
                            avg_trade_return = %s,
                            avg_holding_days = %s,
                            equity_curve = %s,
                            trades = %s,
                            errors = %s,
                            status = 'completed'
                        WHERE id = %s
                        """,
                        (
                            result.final_equity,
                            result.total_return,
                            result.sharpe_ratio,
                            result.max_drawdown,
                            result.max_drawdown_duration_days,
                            result.win_rate,
                            result.profit_factor,
                            result.total_trades,
                            result.winning_trades,
                            result.losing_trades,
                            result.avg_trade_return,
                            result.avg_holding_days,
                            json.dumps(equity_curve_serializable),
                            json.dumps(trades_serializable),
                            result.errors or [],
                            run_id,
                        ),
                    )
                conn2.commit()
            finally:
                conn2.close()

            log.info(f"[Backtest] completed run_id={run_id} strategy={strat_row['name']}")

        except Exception as exc:
            log.error(f"[Backtest] failed run_id={run_id}: {exc}", exc_info=True)
            try:
                conn3 = psycopg2.connect(get_dsn())
                try:
                    with conn3.cursor() as cur:
                        cur.execute(
                            "UPDATE backtest_results SET errors = errors || %s, status = 'failed' WHERE id = %s",
                            ([str(exc)], run_id),
                        )
                    conn3.commit()
                finally:
                    conn3.close()
            except Exception:
                pass

    t = threading.Thread(target=_run_backtest_async, args=(run_id, req, dict(strat_row)), daemon=True)
    t.start()

    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "id": run_id,
            "status": "running",
            "message": "Backtest task submitted. Poll GET /strategy/backtest/{id} for results.",
        },
    }
