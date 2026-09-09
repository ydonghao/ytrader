"""
Tests for daily.py job — 每日增量同步测试
"""
import pytest
from unittest.mock import MagicMock, patch

from src.domain.market.sync.jobs import daily
from src.domain.market.sync.sync_service import SyncResult


class TestSyncMarket:
    """sync_market 函数测试"""

    @patch("src.domain.market.sync.jobs.daily.SyncService")
    @patch("src.domain.market.sync.jobs.daily.ProgressTracker")
    @patch("src.domain.market.sync.jobs.daily.SinaProvider")
    def test_sync_market_calls_backfill_with_symbols(self, mock_sina_cls, mock_tracker_cls, mock_service_cls):
        """验证构建了正确的 Service 配置并传入股票列表"""
        mock_provider = MagicMock()
        mock_provider.name = "sina"
        mock_provider.get_stock_list.return_value = ["sh600000", "sh600001"]
        mock_sina_cls.return_value = mock_provider

        mock_tracker = MagicMock()
        mock_tracker_cls.return_value = mock_tracker

        mock_result = SyncResult(provider="sina", interval="1d", total_rows=1000, done_symbols=2, total_symbols=2)
        mock_service = MagicMock()
        mock_service.backfill.return_value = mock_result
        mock_service_cls.return_value = mock_service

        with patch.dict("os.environ", {"TIMESCALE_DSN": "postgresql://localhost/test"}):
            result = daily.sync_market(
                provider="sina",
                market="A",
                interval="1d",
                max_workers=4,
                rate_delay=1.0,
            )

        assert result.total_rows == 1000
        mock_sina_cls.assert_called_once()
        mock_service.backfill.assert_called_once_with(
            symbols=["sh600000", "sh600001"],
            interval="1d",
            mode="incremental",
        )

    @patch("src.domain.market.sync.jobs.daily.SyncService")
    @patch("src.domain.market.sync.jobs.daily.ProgressTracker")
    @patch("src.domain.market.sync.jobs.daily.TencentProvider")
    def test_sync_market_tencent(self, mock_tencent_cls, mock_tracker_cls, mock_service_cls):
        """Tencent provider 被正确构造"""
        mock_provider = MagicMock()
        mock_provider.name = "tencent"
        mock_provider.get_stock_list.return_value = []
        mock_tencent_cls.return_value = mock_provider

        mock_tracker = MagicMock()
        mock_tracker_cls.return_value = mock_tracker

        mock_result = SyncResult(provider="tencent", interval="1d")
        mock_service = MagicMock()
        mock_service.backfill.return_value = mock_result
        mock_service_cls.return_value = mock_service

        with patch.dict("os.environ", {"TIMESCALE_DSN": "postgresql://localhost/test"}):
            result = daily.sync_market(
                provider="tencent",
                market="HK",
                interval="1d",
                max_workers=8,
                rate_delay=0.05,
            )

        assert result.provider == "tencent"
        mock_tencent_cls.assert_called_once()

    @patch("src.domain.market.sync.jobs.daily.SyncService")
    @patch("src.domain.market.sync.jobs.daily.ProgressTracker")
    @patch("src.domain.market.sync.jobs.daily.SinaProvider")
    def test_sync_market_empty_symbol_list(self, mock_sina_cls, mock_tracker_cls, mock_service_cls):
        """股票列表为空时直接返回，不调用 service.backfill"""
        mock_provider = MagicMock()
        mock_provider.name = "sina"
        mock_provider.get_stock_list.return_value = []
        mock_sina_cls.return_value = mock_provider

        mock_tracker = MagicMock()
        mock_tracker_cls.return_value = mock_tracker

        mock_result = SyncResult(provider="sina", interval="1d")
        mock_service = MagicMock()
        mock_service.backfill.return_value = mock_result
        mock_service_cls.return_value = mock_service

        with patch.dict("os.environ", {"TIMESCALE_DSN": "postgresql://localhost/test"}):
            result = daily.sync_market(
                provider="sina", market="A", interval="1d",
                max_workers=4, rate_delay=1.0,
            )

        mock_service.backfill.assert_not_called()
        assert result.total_symbols == 0


class TestBuildProvider:
    """_build_provider 测试"""

    def test_build_sina(self):
        with patch("src.domain.market.sync.jobs.daily.SinaProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            p = daily._build_provider("sina")
            mock_cls.assert_called_once()

    def test_build_tencent(self):
        with patch("src.domain.market.sync.jobs.daily.TencentProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            p = daily._build_provider("tencent")
            mock_cls.assert_called_once()

    def test_build_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            daily._build_provider("unknown_source")
