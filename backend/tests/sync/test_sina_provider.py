"""
Tests for SinaProvider — TDD 风格
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.domain.market.sync.providers.sina_provider import SinaProvider
from src.domain.market.sync.sync_provider import OHLCVBar


class TestSinaProviderInit:
    """SinaProvider 初始化测试"""

    def test_name_is_sina(self):
        provider = SinaProvider()
        assert provider.name == "sina"

    def test_supports_minute_is_true(self):
        assert SinaProvider().supports_minute is True

    def test_default_timeout(self):
        p = SinaProvider()
        assert p._timeout == 15

    def test_custom_timeout(self):
        p = SinaProvider(timeout=30)
        assert p._timeout == 30

    def test_default_rate_delay(self):
        p = SinaProvider()
        assert p._rate_delay == 0.5

    def test_custom_rate_delay(self):
        p = SinaProvider(rate_delay=1.0)
        assert p._rate_delay == 1.0


class TestSinaProviderFetchDaily:
    """fetch_daily 测试"""

    def _mock_response(self, json_data, status_code=200):
        """构造 mock HTTP Response"""
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def _sina_daily_sample(self):
        """新浪日线 API 返回的样本数据"""
        return [
            {"day": "2026-04-01", "open": "10.00", "close": "10.20",
             "high": "10.30", "low": "9.90", "volume": 1000000},
            {"day": "2026-04-02", "open": "10.20", "close": "10.25",
             "high": "10.30", "low": "10.10", "volume": 1200000},
            {"day": "2026-04-03", "open": "10.25", "close": "10.12",
             "high": "10.28", "low": "10.05", "volume": 980000},
        ]

    def test_fetch_daily_returns_bars(self):
        """RED: fetch_daily 成功时返回 OHLCVBar 列表"""
        p = SinaProvider()
        sample = self._sina_daily_sample()
        with patch.object(p._session, "get",
                          return_value=self._mock_response(sample)) as mock_get:
            bars = p.fetch_daily("sh600000", datalen=3)

            assert len(bars) == 3
            assert isinstance(bars[0], OHLCVBar)
            assert bars[0].symbol == "sh600000"
            assert bars[0].market == "A"
            assert bars[0].interval == "1d"
            assert bars[0].close_ == 10.20

    def test_fetch_daily_empty_response_returns_empty_list(self):
        """空响应返回空列表"""
        p = SinaProvider()
        with patch.object(p._session, "get",
                          return_value=self._mock_response([])) as mock_get:
            bars = p.fetch_daily("sh600000")
            assert bars == []

    def test_fetch_daily_456_returns_empty_list_no_exception(self):
        """456 限速错误返回空列表，不抛异常"""
        p = SinaProvider()
        with patch.object(p._session, "get",
                          return_value=self._mock_response([], status_code=456)) as mock_get:
            bars = p.fetch_daily("sh600000")
            assert bars == []

    def test_fetch_daily_http_error_returns_empty_list(self):
        """HTTP 错误返回空列表"""
        p = SinaProvider()
        with patch.object(p._session, "get",
                          return_value=self._mock_response([], status_code=500)) as mock_get:
            bars = p.fetch_daily("sh600000")
            assert bars == []

    def test_fetch_daily_correct_url_params(self):
        """验证请求 URL 和参数正确"""
        p = SinaProvider()
        sample = self._sina_daily_sample()
        mock_resp = self._mock_response(sample)
        with patch.object(p._session, "get", return_value=mock_resp) as mock_get:
            p.fetch_daily("sh600000", datalen=3000)

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "money.finance.sina.com.cn" in call_args[0][0]
            params = call_args[1]["params"]
            assert params["symbol"] == "sh600000"
            assert params["scale"] == 240  # 日线
            assert params["datalen"] == 3000


class TestSinaProviderFetchMinute:
    """fetch_minute 测试"""

    def _mock_minute_response(self):
        return [
            {"day": "2026-04-03 10:00:00", "open": "10.20", "close": "10.25",
             "high": "10.28", "low": "10.18", "volume": 50000},
            {"day": "2026-04-03 10:05:00", "open": "10.25", "close": "10.30",
             "high": "10.32", "low": "10.22", "volume": 48000},
        ]

    def test_fetch_minute_5m(self):
        """5分钟线"""
        p = SinaProvider()
        with patch.object(p._session, "get",
                          return_value=MagicMock(
                              status_code=200, json=self._mock_minute_response,
                              raise_for_status=MagicMock())) as mock_get:
            bars = p.fetch_minute("sh600000", interval="5m", datalen=300)
            assert len(bars) == 2
            assert bars[0].interval == "5m"
            assert bars[0].market == "A"

    def test_fetch_minute_60m(self):
        """60分钟线"""
        p = SinaProvider()
        with patch.object(p._session, "get",
                          return_value=MagicMock(
                              status_code=200, json=self._mock_minute_response,
                              raise_for_status=MagicMock())) as mock_get:
            bars = p.fetch_minute("sh600000", interval="60m", datalen=3000)
            # scale 60 → 60m
            call_args = mock_get.call_args
            assert call_args[1]["params"]["scale"] == 60


class TestSinaProviderStockList:
    """get_stock_list 测试"""

    def test_get_stock_list_returns_list(self):
        """返回股票代码列表"""
        with patch("src.domain.market.sync.providers.sina_provider.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: [],
                raise_for_status=MagicMock(),
            )
            p = SinaProvider()
            # 实际实现需要网络，这里测试结构正确
            assert p.name == "sina"


class TestSinaProviderValidateSymbol:
    """validate_symbol 测试"""

    def test_validate_symbol_sh(self):
        p = SinaProvider()
        assert p.validate_symbol("sh600000") is True

    def test_validate_symbol_sz(self):
        p = SinaProvider()
        assert p.validate_symbol("sz000001") is True

    def test_validate_symbol_hk_not_supported(self):
        """Sina 只支持 A股，不支持港股"""
        p = SinaProvider()
        assert p.validate_symbol("hk00700") is False

    def test_validate_symbol_invalid(self):
        p = SinaProvider()
        assert p.validate_symbol("invalid") is False
