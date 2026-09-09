"""
Tests for sync_provider — OHLCVBar dataclass and SyncProvider ABC
"""
import pytest
from datetime import datetime
from unittest.mock import Mock

from src.domain.market.sync.sync_provider import OHLCVBar, SyncProvider


class TestOHLCVBar:
    """OHLCVBar 值对象测试"""

    def test_default_values(self):
        bar = OHLCVBar(symbol="sh600000", trade_time=datetime(2026, 4, 3),
                       open_=10.0, close_=10.5, high_=11.0, low_=9.5, volume=1e6)
        assert bar.symbol == "sh600000"
        assert bar.interval == "1d"
        assert bar.market == "A"
        assert bar.amount == 0.0
        assert bar.provider == ""

    def test_full_values(self):
        bar = OHLCVBar(
            symbol="hk00700",
            trade_time=datetime(2026, 4, 3, 10, 30),
            open_=300.0, close_=305.0, high_=308.0, low_=298.0,
            volume=5e6, amount=1.5e9,
            interval="5m", market="HK", provider="tencent",
        )
        assert bar.interval == "5m"
        assert bar.market == "HK"
        assert bar.provider == "tencent"
        assert bar.amount == 1.5e9

    def test_to_dict(self):
        bar = OHLCVBar(
            symbol="sh600000",
            trade_time=datetime(2026, 4, 3),
            open_=10.0, close_=10.5, high_=11.0, low_=9.5,
            volume=1e6,
        )
        d = bar.__dict__
        assert d["symbol"] == "sh600000"
        assert d["close_"] == 10.5


class TestSyncProviderABC:
    """SyncProvider 抽象基类测试"""

    def test_cannot_instantiate_directly(self):
        """SyncProvider 是 ABC，不能直接实例化"""
        with pytest.raises(TypeError):
            SyncProvider()

    def test_concrete_implementation_passes(self):
        """继承 SyncProvider 并实现所有抽象方法后可实例化"""
        class ConcreteProvider(SyncProvider):
            name = "test"
            supports_minute = False

            def fetch_daily(self, symbol, start_date=None, end_date=None, datalen=1300):
                return []

            def fetch_minute(self, symbol, interval="5m", datalen=3000):
                return []

            def get_stock_list(self, market="A"):
                return []

            def validate_symbol(self, symbol):
                return True

        p = ConcreteProvider()
        assert p.name == "test"
        assert p.supports_minute is False

    def test_validate_symbol_can_be_overridden(self):
        """validate_symbol 可被子类覆盖"""
        class SpecialProvider(SyncProvider):
            name = "special"
            supports_minute = False

            def fetch_daily(self, symbol, start_date=None, end_date=None, datalen=1300):
                return []

            def fetch_minute(self, symbol, interval="5m", datalen=3000):
                return []

            def get_stock_list(self, market="A"):
                return []

            def validate_symbol(self, symbol):
                return symbol == "sh600000"

        p = SpecialProvider()
        assert p.validate_symbol("sh600000") is True
        assert p.validate_symbol("sh600001") is False
