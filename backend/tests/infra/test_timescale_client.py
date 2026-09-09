# tests/infra/test_timescale_client.py
"""Tests for TimescaleDB client."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


class TestTimescaleDBClientInit:
    """Test TimescaleDBClient initialization."""

    def test_client_initializes_with_dsn(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient

        dsn = "postgresql://user:pass@localhost:5432/db"
        client = TimescaleDBClient(dsn)
        assert client.dsn == dsn
        assert client.pool is None

    def test_is_connected_returns_false_when_not_connected(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient

        client = TimescaleDBClient("postgresql://localhost/db")
        assert client.is_connected() is False

    def test_is_connected_returns_true_when_pool_exists(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient

        client = TimescaleDBClient("postgresql://localhost/db")
        client.pool = MagicMock()
        assert client.is_connected() is True


class TestTimescaleDBClientConnect:
    """Test TimescaleDBClient connection."""

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient

        dsn = "postgresql://user:pass@localhost:5432/db"
        client = TimescaleDBClient(dsn)

        mock_pool_instance = AsyncMock()
        with patch("src.infra.database.sql_engine.timescale_client.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool_instance) as mock_create:
            await client.connect()
            mock_create.assert_called_once_with(dsn, min_size=1, max_size=10)
            assert client.pool == mock_pool_instance

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient

        client = TimescaleDBClient("postgresql://localhost/db")
        mock_pool = AsyncMock()
        client.pool = mock_pool

        await client.disconnect()

        mock_pool.close.assert_called_once()
        assert client.pool is None


class TestTimescaleDBClientHypertable:
    """Test TimescaleDBClient hypertable creation."""

    @pytest.mark.asyncio
    async def test_create_hypertable_returns_true(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient

        client = TimescaleDBClient("postgresql://localhost/db")
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        client.pool = mock_pool

        result = await client.create_hypertable("stock_ohlcv", "time")

        assert result is True
        mock_conn.execute.assert_called_once()


class TestTimescaleDBClientInsert:
    """Test TimescaleDBClient insert operations."""

    @pytest.mark.asyncio
    async def test_insert_ohlcv_returns_zero_for_empty_list(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient

        client = TimescaleDBClient("postgresql://localhost/db")

        result = await client.insert_ohlcv("stock_ohlcv", [])

        assert result == 0

    @pytest.mark.asyncio
    async def test_insert_ohlcv_inserts_data(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient
        from src.domain.market.schemas import OHLCV

        client = TimescaleDBClient("postgresql://localhost/db")
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        client.pool = mock_pool

        ohlcv_list = [
            OHLCV(symbol="AAPL", time=datetime.now(), open=150.0, high=155.0, low=148.0, close=152.0, volume=1000000.0, amount=150000000.0),
        ]

        result = await client.insert_ohlcv("stock_ohlcv", ohlcv_list)

        assert result == 1
        mock_conn.executemany.assert_called_once()


class TestTimescaleDBClientQuery:
    """Test TimescaleDBClient query operations."""

    @pytest.mark.asyncio
    async def test_query_ohlcv_returns_list(self):
        from src.infra.database.sql_engine.timescale_client import TimescaleDBClient

        client = TimescaleDBClient("postgresql://localhost/db")
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        client.pool = mock_pool

        mock_conn.fetch.return_value = [
            {"symbol": "AAPL", "time": datetime.now(), "open": 150.0, "high": 155.0, "low": 148.0, "close": 152.0, "volume": 1000000.0, "amount": 150000000.0},
        ]

        result = await client.query_ohlcv("stock_ohlcv", "AAPL", datetime(2024, 1, 1), datetime(2024, 12, 31))

        assert len(result) == 1
        assert result[0].symbol == "AAPL"
