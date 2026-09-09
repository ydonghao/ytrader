# backend/src/infra/database/timescale_client.py
import asyncpg
from typing import List, Optional
from datetime import datetime


class TimescaleDBClient:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    def is_connected(self) -> bool:
        return self.pool is not None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)

    async def disconnect(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def create_hypertable(self, table_name: str, time_column: str) -> bool:
        sql = f"SELECT create_hypertable('{table_name}', '{time_column}', if_not_exists => TRUE);"
        async with self.pool.acquire() as conn:
            await conn.execute(sql)
        return True

    async def insert_ohlcv(self, table_name: str, ohlcv_list: List) -> int:
        if not ohlcv_list:
            return 0
        values = [(o.symbol, o.time, o.open, o.high, o.low, o.close, o.volume, o.amount) for o in ohlcv_list]
        sql = f"INSERT INTO {table_name} (symbol, time, open, high, low, close, volume, amount) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)"
        async with self.pool.acquire() as conn:
            await conn.executemany(sql, values)
        return len(ohlcv_list)

    async def query_ohlcv(self, table_name: str, symbol: str, start_time: datetime, end_time: datetime) -> List:
        from backend.src.domain.market.schemas import OHLCV
        sql = f"SELECT symbol, time, open, high, low, close, volume, amount FROM {table_name} WHERE symbol = $1 AND time >= $2 AND time <= $3 ORDER BY time ASC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, symbol, start_time, end_time)
        return [OHLCV(symbol=r["symbol"], time=r["time"], open=float(r["open"]), high=float(r["high"]), low=float(r["low"]), close=float(r["close"]), volume=float(r["volume"]), amount=float(r["amount"])) for r in rows]
