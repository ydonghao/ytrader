"""AkshareProvider 港股分流与 HKDCNY 汇率单测。

用 mock 避免真实网络调用, 验证分流逻辑与汇率 pair 放开。
"""
from unittest.mock import patch, MagicMock
from datetime import datetime

import pytest

from src.domain.market.sync.providers.akshare_provider import (
    AkshareProvider,
    _HK_TICKER_RE,
    _A_PREFIX_RE,
    _US_TICKER_RE,
)


class TestSymbolRegex:
    """三种 symbol 正则互斥性测试。"""

    def test_us_ticker(self):
        assert _US_TICKER_RE.match("VOO")
        assert _US_TICKER_RE.match("TLT")
        assert not _US_TICKER_RE.match("sh510300")
        assert not _US_TICKER_RE.match("02800")

    def test_a_prefix(self):
        assert _A_PREFIX_RE.match("sh510300")
        assert _A_PREFIX_RE.match("sz159934")
        assert not _A_PREFIX_RE.match("VOO")
        assert not _A_PREFIX_RE.match("02800")

    def test_hk_digits(self):
        assert _HK_TICKER_RE.match("02800")
        assert _HK_TICKER_RE.match("02819")
        assert not _HK_TICKER_RE.match("VOO")
        assert not _HK_TICKER_RE.match("sh510300")
        # 注意: A股 6 位数字带前缀不会与 5 位纯数字碰撞
        assert not _HK_TICKER_RE.match("510300")  # 6位不匹配5位


class TestValidateSymbol:
    """validate_symbol 接受三类标的。"""

    def test_accepts_all_three_markets(self):
        prov = AkshareProvider()
        assert prov.validate_symbol("VOO")        # 美股
        assert prov.validate_symbol("sh510300")   # A股
        assert prov.validate_symbol("sz159934")   # A股
        assert prov.validate_symbol("02800")      # 港股
        assert prov.validate_symbol("02819")      # 港股

    def test_rejects_invalid(self):
        prov = AkshareProvider()
        assert not prov.validate_symbol("")
        assert not prov.validate_symbol("123456")   # 6位纯数字(无前缀)
        assert not prov.validate_symbol("sh51030")  # 5位+前缀
        assert not prov.validate_symbol("vo")       # 小写


class TestFetchDailyRouting:
    """fetch_daily 主入口分流测试(mock akshare)。"""

    def test_hk_symbol_routes_to_hk_method(self):
        """5位纯数字应分流到 fetch_hk_stock_daily, 不是 _fetch_a_etf。"""
        prov = AkshareProvider()
        with patch.object(
            prov, "fetch_hk_stock_daily", return_value=[]
        ) as mock_hk, patch.object(
            prov, "_fetch_a_etf", return_value=[]
        ) as mock_a:
            prov.fetch_daily("02800")
            mock_hk.assert_called_once()
            mock_a.assert_not_called()

    def test_us_symbol_routes_to_us(self):
        prov = AkshareProvider()
        with patch.object(
            prov, "_fetch_us", return_value=[]
        ) as mock_us, patch.object(
            prov, "fetch_hk_stock_daily", return_value=[]
        ) as mock_hk:
            prov.fetch_daily("VOO")
            mock_us.assert_called_once()
            mock_hk.assert_not_called()

    def test_a_symbol_routes_to_a_etf(self):
        prov = AkshareProvider()
        with patch.object(
            prov, "_fetch_a_etf", return_value=[]
        ) as mock_a, patch.object(
            prov, "fetch_hk_stock_daily", return_value=[]
        ) as mock_hk:
            prov.fetch_daily("sh510300")
            mock_a.assert_called_once()
            mock_hk.assert_not_called()


class TestFetchFxDailyMultiPair:
    """fetch_fx_daily 多 pair 支持测试。"""

    def test_hkcny_not_blocked(self):
        """HKDCNY 不再被早 return, 会查映射表调 currency_boc_sina。"""
        prov = AkshareProvider()
        # mock akshare 返回空 DataFrame, 只验证不被 pair != USDCNY 拦截
        import pandas as pd
        with patch("akshare.currency_boc_sina", return_value=pd.DataFrame()):
            result = prov.fetch_fx_daily("HKDCNY")
            assert result == []  # 空 df 返回空列表, 但没被早 return 拦截

    def test_unknown_pair_returns_empty(self):
        """未在映射表的 pair 返回空。"""
        prov = AkshareProvider()
        result = prov.fetch_fx_daily("XYZCNY")
        assert result == []

    def test_usdcny_still_works(self):
        """USDCNY 路径不被破坏。"""
        prov = AkshareProvider()
        import pandas as pd
        mock_df = pd.DataFrame(
            [{"日期": "2026-01-01", "中行折算价": "700.00"}]
        )
        with patch("akshare.currency_boc_sina", return_value=mock_df):
            result = prov.fetch_fx_daily("USDCNY")
            assert len(result) == 1
            d, rate = result[0]
            assert rate == pytest.approx(7.0)
