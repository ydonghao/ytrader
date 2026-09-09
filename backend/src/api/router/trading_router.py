"""
交易路由
=========
GET  /trade/account          → 账户信息（模拟）
GET  /trade/positions        → 当前持仓
GET  /trade/orders           → 订单列表
POST /trade/orders           → 下单（模拟写入，返回订单ID）
DELETE /trade/orders/{id}    → 撤单
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/trade", tags=["trading"])

from src.infra.database.sql_engine.dsn import get_dsn


# ── 请求/响应模型 ────────────────────────────────────────────────────────────
class AccountInfo(BaseModel):
    account_id: str
    total_assets: float
    cash: float
    positions_value: float
    total_profit: float
    total_profit_pct: float
    frozen_cash: float
    margin_used: float
    status: str  # active / frozen


class PositionItem(BaseModel):
    id: int
    symbol: str
    quantity: int
    avg_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    updated_at: str


class OrderItem(BaseModel):
    id: int
    order_no: str
    symbol: str
    side: str       # buy / sell
    order_type: str  # limit / market
    price: float
    quantity: int
    filled_qty: int
    status: str      # pending / filled / cancelled / rejected
    strategy_id: Optional[int] = None
    created_at: str


class OrderCreateRequest(BaseModel):
    symbol: str
    side: str          # buy / sell
    order_type: str    # limit / market
    price: float
    quantity: int
    strategy_id: Optional[int] = None


# ── DB helpers ───────────────────────────────────────────────────────────────
def _get_conn():
    return psycopg2.connect(get_dsn())


# ── API 端点 ─────────────────────────────────────────────────────────────────

@router.get("/account", response_model=dict)
def get_account():
    """获取账户信息（模拟）"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 从 positions 表汇总持仓
                cur.execute("""
                    SELECT COALESCE(SUM(quantity * avg_price), 0) as positions_value,
                           COALESCE(SUM(unrealized_pnl), 0) as unrealized_pnl,
                           COALESCE(SUM(realized_pnl), 0) as realized_pnl
                    FROM positions
                """)
                row = dict(cur.fetchone())

                total_profit = round(row["realized_pnl"] + row["unrealized_pnl"], 2)
                positions_value = round(float(row["positions_value"]), 2)
                # 模拟账户：初始资金 1,000,000 + 已实现盈亏
                initial_capital = 1_000_000.0
                cash = round(initial_capital + row["realized_pnl"], 2)
                total_assets = round(cash + positions_value, 2)
                total_profit_pct = round(total_profit / initial_capital * 100, 4) if initial_capital else 0.0

                data = AccountInfo(
                    account_id="ACC_SIM_001",
                    total_assets=total_assets,
                    cash=cash,
                    positions_value=positions_value,
                    total_profit=total_profit,
                    total_profit_pct=total_profit_pct,
                    frozen_cash=0.0,
                    margin_used=0.0,
                    status="active",
                )
                return {"code": 0, "msg": "ok", "data": data}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions", response_model=dict)
def get_positions():
    """获取当前持仓"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, symbol, quantity, avg_price, current_price,
                           unrealized_pnl, realized_pnl, updated_at
                    FROM positions
                    WHERE quantity > 0
                    ORDER BY unrealized_pnl DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                items = [
                    PositionItem(
                        id=r["id"],
                        symbol=r["symbol"],
                        quantity=r["quantity"],
                        avg_price=round(float(r["avg_price"]), 4),
                        current_price=round(float(r["current_price"]), 4),
                        unrealized_pnl=round(float(r["unrealized_pnl"]), 2),
                        realized_pnl=round(float(r["realized_pnl"]), 2),
                        updated_at=str(r["updated_at"]),
                    )
                    for r in rows
                ]
                return {"code": 0, "msg": "ok", "data": items, "total": len(items)}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders", response_model=dict)
def get_orders(
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """获取订单列表"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sql = """
                    SELECT id, order_no, symbol, side, order_type, price,
                           quantity, filled_qty, status, strategy_id, created_at
                    FROM orders
                    WHERE 1=1
                """
                params: list = []
                if symbol:
                    sql += " AND symbol = %s"
                    params.append(symbol)
                if status:
                    sql += " AND status = %s"
                    params.append(status)
                sql += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                items = [
                    OrderItem(
                        id=r["id"],
                        order_no=r["order_no"],
                        symbol=r["symbol"],
                        side=r["side"],
                        order_type=r["order_type"],
                        price=round(float(r["price"]), 4),
                        quantity=r["quantity"],
                        filled_qty=r["filled_qty"],
                        status=r["status"],
                        strategy_id=r["strategy_id"],
                        created_at=str(r["created_at"]),
                    )
                    for r in rows
                ]
                return {"code": 0, "msg": "ok", "data": items, "total": len(items)}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orders", response_model=dict)
def create_order(req: OrderCreateRequest):
    """下单（模拟写入）"""
    try:
        if req.quantity <= 0:
            raise HTTPException(status_code=422, detail="quantity must be > 0")
        if req.price <= 0:
            raise HTTPException(status_code=422, detail="price must be > 0")
        if req.side not in ("buy", "sell"):
            raise HTTPException(status_code=422, detail="side must be 'buy' or 'sell'")
        if req.order_type not in ("limit", "market"):
            raise HTTPException(status_code=422, detail="order_type must be 'limit' or 'market'")

        order_no = f"ORD{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO orders (order_no, symbol, side, order_type, price, quantity, status, strategy_id)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
                    RETURNING id, order_no, symbol, side, order_type, price, quantity, filled_qty, status, strategy_id, created_at
                    """,
                    (order_no, req.symbol, req.side, req.order_type, req.price, req.quantity, req.strategy_id),
                )
                row = dict(cur.fetchone())
                conn.commit()
                item = OrderItem(
                    id=row["id"],
                    order_no=row["order_no"],
                    symbol=row["symbol"],
                    side=row["side"],
                    order_type=row["order_type"],
                    price=round(float(row["price"]), 4),
                    quantity=row["quantity"],
                    filled_qty=row["filled_qty"],
                    status=row["status"],
                    strategy_id=row["strategy_id"],
                    created_at=str(row["created_at"]),
                )
                return {"code": 0, "msg": "ok", "data": item}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orders/{order_id}", response_model=dict)
def cancel_order(order_id: int):
    """撤单"""
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 只允许撤 pending 状态的订单
                cur.execute(
                    "UPDATE orders SET status = 'cancelled', updated_at = NOW() "
                    "WHERE id = %s AND status = 'pending' RETURNING id, status",
                    (order_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Order {order_id} not found or not cancellable")
                conn.commit()
                return {"code": 0, "msg": "ok", "data": {"id": row["id"], "status": row["status"]}}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
