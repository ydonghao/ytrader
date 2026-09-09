# tests/domain/test_market_schemas.py
"""Tests for market data schemas."""
from datetime import datetime
from src.domain.market.schemas import (
    MarketType,
    OHLCV,
    StockDaily,
    ETFDaily,
    IndexDaily,
)


class TestMarketType:
    """Test MarketType enum."""

    def test_market_type_has_stock(self):
        assert MarketType.STOCK.value == "stock"

    def test_market_type_has_etf(self):
        assert MarketType.ETF.value == "etf"

    def test_market_type_has_index(self):
        assert MarketType.INDEX.value == "index"

    def test_market_type_has_futures(self):
        assert MarketType.FUTURES.value == "futures"

    def test_market_type_has_options(self):
        assert MarketType.OPTIONS.value == "options"

    def test_market_type_has_crypto(self):
        assert MarketType.CRYPTO.value == "crypto"


class TestOHLCV:
    """Test OHLCV dataclass."""

    def test_ohlcv_can_be_created_with_required_fields(self):
        ohlcv = OHLCV(symbol="AAPL")
        assert ohlcv.symbol == "AAPL"
        assert ohlcv.name is None
        assert ohlcv.time is None
        assert ohlcv.open == 0.0
        assert ohlcv.high == 0.0
        assert ohlcv.low == 0.0
        assert ohlcv.close == 0.0
        assert ohlcv.volume == 0.0
        assert ohlcv.amount == 0.0
        assert ohlcv.interval == "1d"
        assert ohlcv.market is None

    def test_ohlcv_can_be_created_with_all_fields(self):
        now = datetime.now()
        ohlcv = OHLCV(
            symbol="AAPL",
            name="Apple Inc.",
            time=now,
            open=150.0,
            high=155.0,
            low=148.0,
            close=152.0,
            volume=1000000.0,
            amount=150000000.0,
            interval="1d",
            market=MarketType.STOCK,
        )
        assert ohlcv.symbol == "AAPL"
        assert ohlcv.name == "Apple Inc."
        assert ohlcv.time == now
        assert ohlcv.open == 150.0
        assert ohlcv.high == 155.0
        assert ohlcv.low == 148.0
        assert ohlcv.close == 152.0
        assert ohlcv.volume == 1000000.0
        assert ohlcv.amount == 150000000.0
        assert ohlcv.interval == "1d"
        assert ohlcv.market == MarketType.STOCK


class TestStockDaily:
    """Test StockDaily dataclass."""

    def test_stock_daily_has_turnrate(self):
        stock = StockDaily(symbol="AAPL", turnrate=5.5)
        assert stock.turnrate == 5.5

    def test_stock_daily_has_pre_close(self):
        stock = StockDaily(symbol="AAPL", pre_close=149.0)
        assert stock.pre_close == 149.0

    def test_stock_daily_inherits_ohlcv_fields(self):
        stock = StockDaily(
            symbol="AAPL",
            open=150.0,
            high=155.0,
            low=148.0,
            close=152.0,
            volume=1000000.0,
            turnrate=5.5,
            pre_close=149.0,
        )
        assert stock.symbol == "AAPL"
        assert stock.open == 150.0
        assert stock.close == 152.0
        assert stock.turnrate == 5.5
        assert stock.pre_close == 149.0


class TestETFDaily:
    """Test ETFDaily dataclass."""

    def test_etf_daily_has_nav(self):
        etf = ETFDaily(symbol="SPY", nav=450.0)
        assert etf.nav == 450.0

    def test_etf_daily_has_iopv(self):
        etf = ETFDaily(symbol="SPY", iopv=449.5)
        assert etf.iopv == 449.5

    def test_etf_daily_has_premium(self):
        etf = ETFDaily(symbol="SPY", premium=0.1)
        assert etf.premium == 0.1

    def test_etf_daily_inherits_ohlcv_fields(self):
        etf = ETFDaily(
            symbol="SPY",
            open=450.0,
            high=452.0,
            low=448.0,
            close=451.0,
            volume=500000.0,
            nav=451.0,
            iopv=449.5,
            premium=0.1,
        )
        assert etf.symbol == "SPY"
        assert etf.close == 451.0


class TestIndexDaily:
    """Test IndexDaily dataclass."""

    def test_index_daily_has_amplitude(self):
        index = IndexDaily(symbol="000001", amplitude=2.5)
        assert index.amplitude == 2.5

    def test_index_daily_has_change_pct(self):
        index = IndexDaily(symbol="000001", change_pct=1.5)
        assert index.change_pct == 1.5

    def test_index_daily_inherits_ohlcv_fields(self):
        index = IndexDaily(
            symbol="000001",
            open=3000.0,
            high=3050.0,
            low=2980.0,
            close=3030.0,
            volume=100000000.0,
            amplitude=2.5,
            change_pct=1.5,
        )
        assert index.symbol == "000001"
        assert index.close == 3030.0
