"""
Tests for TencentProvider — TDD 风格
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.domain.market.sync.providers.tencent_provider import TencentProvider
from src.domain.market.sync.sync_provider import OHLCVBar


class TestTencentProviderInit:
    """TencentProvider 初始化测试"""

    def test_name_is_tencent(self):
        provider = TencentProvider()
        assert provider.name == "tencent"

    def test_supports_minute_is_true(self):
        assert TencentProvider().supports_minute is True

    def test_default_rate_delay(self):
        p = TencentProvider()
        assert p._rate_delay == 0.05  # 更快，因为无严格限速

    def test_custom_rate_delay(self):
        p = TencentProvider(rate_delay=0.1)
        assert p._rate_delay == 0.1


def _make_tencent_response(api_sym: str, bars: list) -> MagicMock:
    """构造腾讯 API 响应 mock（text 格式：kline_dayqfq=...json...）"""
    import json
    inner = {api_sym: {"qfqday": bars}}
    text = "kline_dayqfq=" + json.dumps({"data": inner})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = text
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestTencentProviderFetchDaily:
    """fetch_daily 测试"""

    def test_fetch_daily_returns_bars(self):
        """成功时返回 OHLCVBar 列表"""
        p = TencentProvider()
        # 腾讯日线格式: [日期, open, close, high, low, volume]
        # close = sample[0][2] = "10.20"
        sample = [
            ["2026-04-01", "10.00", "10.20", "10.30", "9.90", "1000000"],
            ["2026-04-02", "10.20", "10.25", "10.30", "10.10", "1200000"],
        ]
        mock_resp = _make_tencent_response("hk00700", sample)
        with patch.object(p._session, "get", return_value=mock_resp):
            bars = p.fetch_daily("hk00700", datalen=2)

            assert len(bars) == 2
            assert isinstance(bars[0], OHLCVBar)
            assert bars[0].market == "HK"
            assert bars[0].close_ == 10.20

    def test_fetch_daily_empty_returns_empty_list(self):
        """空数组返回空列表"""
        p = TencentProvider()
        mock_resp = _make_tencent_response("sh600000", [])
        with patch.object(p._session, "get", return_value=mock_resp):
            bars = p.fetch_daily("sh600000")
            assert bars == []

    def test_fetch_daily_http_error_returns_empty_list(self):
        """HTTP 错误返回空列表"""
        p = TencentProvider()
        with patch.object(p._session, "get",
                         side_effect=Exception("Network error")) as mock_get:
            bars = p.fetch_daily("sh600000")
            assert bars == []

    def test_fetch_daily_datalen_1000_max_for_a_share(self):
        """A股 datalen 上限 1000"""
        p = TencentProvider()
        mock_resp = _make_tencent_response("sh600000", [])
        with patch.object(p._session, "get", return_value=mock_resp) as mock_get:
            p.fetch_daily("sh600000", datalen=2000)  # 请求2000
            # 实际调用用了 min(2000, 1000) = 1000
            call_args = mock_get.call_args
            assert "param=sh600000,day,,,1000,qfq" in call_args[0][0]

    def test_fetch_daily_datalen_2000_max_for_hk(self):
        """港股 datalen 上限 2000"""
        p = TencentProvider()
        mock_resp = _make_tencent_response("hk00700", [])
        with patch.object(p._session, "get", return_value=mock_resp) as mock_get:
            p.fetch_daily("hk00700", datalen=5000)  # 请求5000
            # 实际调用用了 min(5000, 2000) = 2000
            call_args = mock_get.call_args
            assert "param=hk00700,day,,,2000,qfq" in call_args[0][0]


class TestTencentProviderFetchMinute:
    """fetch_minute 测试 — 直接测试 _parse_bars 解析逻辑"""

    def test_parse_bars_extracts_interval(self):
        """_parse_bars 正确设置 interval"""
        p = TencentProvider()
        # 腾讯分钟数据格式: [时间戳(ms), open, close, high, low, volume]
        # 2026-04-03 10:00:00 = 1743645600000 ms
        ts_ms = str(int(datetime(2026, 4, 3, 10, 0).timestamp() * 1000))
        sample = [[ts_ms, "10.20", "10.25", "10.28", "10.18", "50000"]]
        bars = p._parse_bars("sh600000", sample, "5m")

        assert len(bars) == 1
        assert bars[0].interval == "5m"
        assert bars[0].market == "A"
        assert bars[0].close_ == 10.25

    def test_parse_bars_hk_market(self):
        """港股分钟线正确识别 market=HK"""
        p = TencentProvider()
        ts_ms = str(int(datetime(2026, 4, 3, 10, 0).timestamp() * 1000))
        sample = [[ts_ms, "300.0", "305.0", "308.0", "298.0", "50000"]]
        bars = p._parse_bars("hk00700", sample, "60m")

        assert len(bars) == 1
        assert bars[0].interval == "60m"
        assert bars[0].market == "HK"

    def test_parse_bars_skips_invalid_rows(self):
        """格式错误的行被跳过"""
        p = TencentProvider()
        ts_ms = str(int(datetime(2026, 4, 3, 10, 0).timestamp() * 1000))
        sample = [
            [ts_ms, "10.20", "10.25", "10.28", "10.18", "50000"],
            "invalid",  # 跳过
            ["not-a-list"],  # 跳过
        ]
        bars = p._parse_bars("sh600000", sample, "5m")
        assert len(bars) == 1

    def test_parse_bars_60m_interval(self):
        """60分钟线的 interval 参数正确传递"""
        p = TencentProvider()
        ts_ms = str(int(datetime(2026, 4, 3, 10, 0).timestamp() * 1000))
        sample = [[ts_ms, "10.20", "10.25", "10.28", "10.18", "50000"]]
        bars = p._parse_bars("sh600000", sample, "60m")
        assert bars[0].interval == "60m"


class TestTencentProviderValidateSymbol:
    """validate_symbol 测试"""

    def test_validate_symbol_sh(self):
        p = TencentProvider()
        assert p.validate_symbol("sh600000") is True

    def test_validate_symbol_sz(self):
        p = TencentProvider()
        assert p.validate_symbol("sz000001") is True

    def test_validate_symbol_hk(self):
        p = TencentProvider()
        assert p.validate_symbol("hk00700") is True

    def test_validate_symbol_invalid(self):
        p = TencentProvider()
        assert p.validate_symbol("invalid_code") is False
