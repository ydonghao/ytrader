"""
WebSocket router for real-time market data streaming
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set
import asyncio
from datetime import datetime

from src.infra.database.sql_engine.dsn import get_dsn
import psycopg2
from psycopg2.extras import RealDictCursor

router = APIRouter(tags=["websocket"])

# Connection manager
class ConnectionManager:
    def __init__(self):
        # symbol -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, symbol: str):
        await websocket.accept()
        if symbol not in self.active_connections:
            self.active_connections[symbol] = set()
        self.active_connections[symbol].add(websocket)

    def disconnect(self, websocket: WebSocket, symbol: str):
        if symbol in self.active_connections:
            self.active_connections[symbol].discard(websocket)
            if not self.active_connections[symbol]:
                del self.active_connections[symbol]

    async def broadcast_to_symbol(self, symbol: str, data: dict):
        if symbol in self.active_connections:
            dead = set()
            for connection in self.active_connections[symbol]:
                try:
                    await connection.send_json(data)
                except Exception:
                    dead.add(connection)
            for conn in dead:
                self.active_connections[symbol].discard(conn)


manager = ConnectionManager()


def _sync_get_latest_ticks(symbols: list[str]) -> dict[str, dict]:
    """单连接单查询取多 symbol 最新 tick。

    广播循环每 5s 调一次：N 个关注 symbol 原本是 N 次 TCP connect + N 条 SQL，
    现在合并为 DISTINCT ON 批量查询。
    """
    if not symbols:
        return {}
    try:
        conn = psycopg2.connect(get_dsn(), connect_timeout=3)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT DISTINCT ON (symbol)
                        symbol, trade_date, open_, close_, high_, low_, volume
                    FROM stock_ohlcv
                    WHERE symbol = ANY(%s)
                    ORDER BY symbol, trade_date DESC
                """, (symbols,))
                return {row["symbol"]: dict(row) for row in cur.fetchall()}
        finally:
            conn.close()
    except Exception:
        return {}


async def get_latest_ticks(symbols: list[str]) -> dict[str, dict]:
    """Async wrapper — runs sync DB call in thread pool to avoid blocking event loop"""
    return await asyncio.to_thread(_sync_get_latest_ticks, symbols)


async def get_latest_tick(symbol: str) -> dict | None:
    """单个 symbol 的最新 tick（连接建立时首推用）"""
    return (await get_latest_ticks([symbol])).get(symbol)


def _tick_to_payload(symbol: str, tick: dict) -> dict:
    return {
        "type": "tick",
        "symbol": symbol,
        "data": {
            "trade_date": str(tick["trade_date"]),
            "open": float(tick["open_"]),
            "close": float(tick["close_"]),
            "high": float(tick["high_"]),
            "low": float(tick["low_"]),
            "volume": float(tick["volume"]),
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


async def tick_broadcaster():
    """Background task: every 5 seconds, broadcast latest tick for each watched symbol"""
    while True:
        await asyncio.sleep(5)
        symbols = list(manager.active_connections.keys())
        if not symbols:
            continue
        ticks = await get_latest_ticks(symbols)
        for symbol, tick in ticks.items():
            await manager.broadcast_to_symbol(symbol, _tick_to_payload(symbol, tick))


@router.websocket("/ws/market/tick/{symbol}")
async def websocket_tick(websocket: WebSocket, symbol: str):
    """Real-time tick stream for a symbol. Sends latest OHLCV every 5 seconds."""
    symbol = symbol.strip().lower()
    await manager.connect(websocket, symbol)
    try:
        tick = await get_latest_tick(symbol)
        if tick:
            await websocket.send_json(_tick_to_payload(symbol, tick))
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat", "timestamp": datetime.utcnow().isoformat()})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, symbol)
