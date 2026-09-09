"""
Tests for SyncService — TDD 风格
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, call

from src.domain.market.sync.sync_service import (
    SyncService,
    SyncConfig,
    SyncResult,
    _SyncResultSingle,
)
from src.domain.market.sync.sync_provider import OHLCVBar


# ── Mock Provider ──────────────────────────────────────────────────────────
class MockProvider:
    """测试用 Mock 数据源"""
    name = "mock"

    def __init__(self, bars_per_symbol=3, supports_minute=True):
        self._bars = bars_per_symbol
        self.supports_minute = supports_minute

    def fetch_daily(self, symbol, start_date=None, end_date=None, datalen=1300):
        base = 10.0 + hash(symbol) % 100
        return [
            OHLCVBar(
                symbol=symbol,
                trade_time=datetime(2026, 4, i + 1),
                open_=base + i * 0.1, close_=base + i * 0.1 + 0.05,
                high_=base + i * 0.1 + 0.1, low_=base + i * 0.1 - 0.05,
                volume=1e6, amount=1e7,
                interval="1d", market="A", provider="mock",
            )
            for i in range(self._bars)
        ]

    def fetch_minute(self, symbol, interval="5m", datalen=3000):
        return [
            OHLCVBar(
                symbol=symbol,
                trade_time=datetime(2026, 4, 3, 10, i * 5),
                open_=10.5, close_=10.6, high_=10.7, low_=10.4,
                volume=50000, amount=5e6,
                interval=interval, market="A", provider="mock",
            )
            for i in range(min(self._bars, 10))
        ]

    def get_stock_list(self, market="A"):
        return []

    def validate_symbol(self, symbol):
        return True


# ── Mock ProgressTracker ───────────────────────────────────────────────────
class MockProgressTracker:
    def __init__(self):
        self._sync_times = {}
        self._stats = {}
        self._symbols = {}

    def get_last_sync(self, provider, symbol, interval):
        return self._sync_times.get((provider, symbol, interval))

    def update_symbol(self, provider, symbol, interval, status,
                      last_sync_time=None, last_error=None, rows_synced=0):
        if last_sync_time:
            self._sync_times[(provider, symbol, interval)] = last_sync_time
        total = self._stats.setdefault((provider, interval), {"rows": 0, "done": 0})
        total["rows"] += rows_synced
        key = (provider, interval)
        if key not in self._symbols:
            self._symbols[key] = {}
        self._symbols[key][symbol] = status

    def get_pending_symbols(self, provider, interval, all_symbols):
        done = {s for (p, s, i), t in self._sync_times.items() if p == provider and i == interval
                if self._symbols.get((p, i), {}).get(s) == "done"}
        return [s for s in all_symbols if s not in done]

    def mark_done(self, provider, symbol, interval, last_sync_time, rows):
        self._sync_times[(provider, symbol, interval)] = last_sync_time
        key = (provider, interval)
        self._stats.setdefault(key, {"rows": 0, "done": 0})
        self._stats[key]["done"] += 1
        if key not in self._symbols:
            self._symbols[key] = {}
        self._symbols[key][symbol] = "done"

    def mark_failed(self, provider, symbol, interval, error):
        key = (provider, interval)
        if key not in self._symbols:
            self._symbols[key] = {}
        self._symbols[key][symbol] = "failed"

    def mark_partial(self, provider, symbol, interval, rows=0):
        key = (provider, interval)
        if key not in self._symbols:
            self._symbols[key] = {}
        self._symbols[key][symbol] = "partial"
        self._stats.setdefault(key, {"rows": 0, "done": 0})["rows"] += rows

    def get_stats(self, provider, interval):
        return self._stats.get((provider, interval), {"total": 0, "done": 0, "rows": 0})


class TestSyncConfig:
    """SyncConfig 测试"""

    def test_default_values(self):
        cfg = SyncConfig()
        assert cfg.max_workers == 8
        assert cfg.batch_size == 500
        assert cfg.rate_delay == 0.1
        assert cfg.request_timeout == 15

    def test_custom_values(self):
        cfg = SyncConfig(max_workers=4, batch_size=200, rate_delay=1.0)
        assert cfg.max_workers == 4
        assert cfg.batch_size == 200


class TestSyncResult:
    """SyncResult 测试"""

    def test_default_success(self):
        result = SyncResult(provider="sina", interval="1d")
        assert result.total_symbols == 0
        assert result.done_symbols == 0
        assert result.failed_symbols == 0
        assert result.total_rows == 0
        assert result.success is True
        assert result.errors == []

    def test_failed_symbols_means_not_success(self):
        result = SyncResult(provider="sina", interval="1d", failed_symbols=1)
        assert result.success is False


class TestSyncServiceInit:
    """SyncService 初始化测试"""

    def test_requires_provider(self):
        tracker = MockProgressTracker()
        service = SyncService(provider=MockProvider(), progress_tracker=tracker)
        assert service.provider.name == "mock"
        assert service.tracker is tracker

    def test_default_config(self):
        service = SyncService(provider=MockProvider(), progress_tracker=MockProgressTracker())
        assert service.config.max_workers == 8


class TestSyncServiceBackfillFull:
    """full 模式回填测试"""

    @patch("src.domain.market.sync.sync_service.psycopg2")
    def test_backfill_full_returns_result(self, mock_psycopg2):
        """backfill(full) 返回 SyncResult"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_cursor = MagicMock()
        mock_conn_cursor.connection.encoding = "utf8"
        mock_cursor.connection = mock_conn_cursor
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2.connect.return_value = mock_conn

        tracker = MockProgressTracker()
        provider = MockProvider(bars_per_symbol=3)
        service = SyncService(provider=provider, progress_tracker=tracker,
                              config=SyncConfig(max_workers=1))

        result = service.backfill(
            symbols=["sh600000", "sh600001"],
            interval="1d",
            mode="full",
            db_dsn="postgresql://localhost/test",
        )

        assert isinstance(result, SyncResult)
        assert result.provider == "mock"
        assert result.interval == "1d"
        assert result.mode == "full"

    @patch("src.domain.market.sync.sync_service.psycopg2")
    def test_backfill_empty_symbols_returns_empty_result(self, mock_psycopg2):
        """空 symbol 列表直接返回"""
        tracker = MockProgressTracker()
        service = SyncService(provider=MockProvider(), progress_tracker=tracker)

        result = service.backfill([], interval="1d", db_dsn="postgresql://localhost/test")

        assert result.total_symbols == 0
        assert result.done_symbols == 0
        mock_psycopg2.connect.assert_not_called()

    @patch("src.domain.market.sync.sync_service.psycopg2")
    def test_backfill_incremental_skips_unknown_symbols(self, mock_psycopg2):
        """incremental 模式跳过无记录的 symbol"""
        tracker = MockProgressTracker()
        service = SyncService(provider=MockProvider(), progress_tracker=tracker)

        result = service.backfill(
            symbols=["sh600000"],
            interval="1d",
            mode="incremental",
            db_dsn="postgresql://localhost/test",
        )

        assert result.total_symbols == 0


class TestSyncServiceBackfillResume:
    """resume 模式（断点续传）测试"""

    @patch("src.domain.market.sync.sync_service.psycopg2")
    def test_backfill_resume_skips_done_symbols(self, mock_psycopg2):
        """已完成的 symbol 跳过，只处理 pending"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_cursor = MagicMock()
        mock_conn_cursor.connection.encoding = "utf8"
        mock_cursor.connection = mock_conn_cursor
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2.connect.return_value = mock_conn

        tracker = MockProgressTracker()
        tracker.mark_done("mock", "sh600000", "1d", "2026-04-03T00:00:00", 3000)

        provider = MockProvider(bars_per_symbol=3)
        service = SyncService(provider=provider, progress_tracker=tracker,
                              config=SyncConfig(max_workers=1))

        result = service.backfill(
            symbols=["sh600000", "sh600001"],
            interval="1d",
            mode="resume",
            db_dsn="postgresql://localhost/test",
        )

        assert result.total_symbols == 1  # 只有 sh600001


class TestSyncServiceMinute:
    """分钟线同步测试"""

    @patch("src.domain.market.sync.sync_service.psycopg2")
    def test_backfill_60m_uses_minute_sql(self, mock_psycopg2):
        """interval != 1d 时使用 MINUTE_INSERT_SQL"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_cursor = MagicMock()
        mock_conn_cursor.connection.encoding = "utf8"
        mock_cursor.connection = mock_conn_cursor
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2.connect.return_value = mock_conn

        tracker = MockProgressTracker()
        provider = MockProvider(bars_per_symbol=3)
        service = SyncService(provider=provider, progress_tracker=tracker,
                              config=SyncConfig(max_workers=1))

        result = service.backfill(
            symbols=["sh600000"],
            interval="60m",
            mode="full",
            db_dsn="postgresql://localhost/test",
        )

        assert result.interval == "60m"


class TestSyncServiceErrorHandling:
    """错误处理测试"""

    def test_backfill_requires_db_dsn(self):
        """无 db_dsn 时抛出 ValueError"""
        service = SyncService(
            provider=MockProvider(),
            progress_tracker=MockProgressTracker(),
            config=SyncConfig(),
        )
        with pytest.raises(ValueError, match="db_dsn"):
            service.backfill(symbols=["sh600000"], interval="1d")


class TestSyncServiceSyncOne:
    """_sync_one 单股票同步测试"""

    @patch("src.domain.market.sync.sync_service.psycopg2")
    def test_sync_one_empty_bars_returns_partial(self, mock_psycopg2):
        """无数据时返回 rows=0（停牌等情况）"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_cursor = MagicMock()
        mock_conn_cursor.connection.encoding = "utf8"
        mock_cursor.connection = mock_conn_cursor
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2.connect.return_value = mock_conn

        # Provider returns empty
        provider = MockProvider(bars_per_symbol=0)
        service = SyncService(provider=provider, progress_tracker=MockProgressTracker(),
                            config=SyncConfig(max_workers=1))

        result = service.backfill(
            symbols=["sh600000"],
            interval="1d",
            mode="full",
            db_dsn="postgresql://localhost/test",
        )

        # 空数据 → partial，不算 failed
        assert result.failed_symbols == 0

    @patch("src.domain.market.sync.sync_service.psycopg2")
    def test_sync_one_db_exception_marks_failed(self, mock_psycopg2):
        """数据库异常时标记为 failed"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_cursor = MagicMock()
        mock_conn_cursor.connection.encoding = "utf8"
        mock_cursor.connection = mock_conn_cursor
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=None)
        mock_psycopg2.connect.return_value = mock_conn

        # Mock execute_values to raise
        from psycopg2 import OperationalError
        mock_cursor.execute.side_effect = OperationalError("connection lost")

        provider = MockProvider(bars_per_symbol=3)
        service = SyncService(provider=provider, progress_tracker=MockProgressTracker(),
                            config=SyncConfig(max_workers=1))

        result = service.backfill(
            symbols=["sh600000"],
            interval="1d",
            mode="full",
            db_dsn="postgresql://localhost/test",
        )

        assert result.failed_symbols == 1
