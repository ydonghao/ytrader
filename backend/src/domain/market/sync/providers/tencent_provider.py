"""
TencentProvider
==============
腾讯行情数据源 SyncProvider 实现。

支持：
  - 日线（2000交易日≈8年，H股） / 641交易日≈2.5年（A股）
  - 分钟级（5/15/30/60分钟，datalen=3000限制）

数据源：web.ifzq.gtimg.cn
"""
import json
import re
import time as time_module
from datetime import datetime
from typing import Optional

import requests

from ..sync_provider import OHLCVBar, SyncProvider

__all__ = ["TencentProvider"]


class TencentProvider(SyncProvider):
    """
    腾讯行情数据源

    特点：
      - 日线H股：datalen=2000（上限），约8年历史
      - 日线A股：datalen=1300（上限），约640天（2.5年）
      - 分钟线：datalen=3000有限制
      - 无限速问题，吞吐量高
    """

    name = "tencent"
    supports_minute = True

    def __init__(
        self,
        timeout: int = 15,
        rate_delay: float = 0.05,
        session: Optional[requests.Session] = None,
    ):
        self._timeout = timeout
        self._rate_delay = rate_delay
        self._session = session or self._make_session()

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/",
        })
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=30, pool_maxsize=30,
            max_retries=requests.packages.urllib3.util.retry.Retry(
                total=3, backoff_factor=0.3,
                status_forcelist=[500, 502, 503, 504])
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s

    # ── 日线 ──────────────────────────────────────────────────────────────

    def fetch_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: int = 2000,
    ) -> list[OHLCVBar]:
        """
        腾讯日线数据
        - H股（如 hk00700）：datalen=2000，上限约8年
        - A股（如 sh600000）：datalen=1000，上限约640天（腾讯限制）
        注意：datalen 过大（>1000 for A, >2000 for HK）会返回空数组
        """
        # 转换symbol格式
        api_sym = self._to_api_symbol(symbol)
        # 限制 datalen 避免空响应
        is_hk = symbol.lower().startswith("hk")
        safe_datalen = min(datalen, 2000 if is_hk else 1000)
        try:
            url = (
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                f"?_var=kline_dayqfq&param={api_sym},day,,,{safe_datalen},qfq"
            )
            r = self._session.get(url, timeout=self._timeout)
            r.raise_for_status()
            raw = r.text
            m = re.match(r"kline_dayqfq=(.+)", raw, re.DOTALL)
            if not m:
                return []
            data = json.loads(m.group(1))
            inner = data.get("data", {})
            if isinstance(inner, list):
                return []  # 空
            stock_data = inner.get(api_sym, {})
            if not stock_data:
                return []
            bars = stock_data.get("qfqday") or stock_data.get("day") or []
            if not bars:
                return []
            return self._parse_bars(symbol, bars, "1d")
        except Exception:
            return []

    def _parse_bars(self, symbol: str, bars: list, interval: str) -> list[OHLCVBar]:
        result = []
        for b in bars:
            if not isinstance(b, list) or len(b) < 6:
                continue
            try:
                # 区分日期字符串（"2026-04-03"）和 Unix ms 时间戳（"1743600000000"）
                if b[0].isdigit():
                    t = datetime.fromtimestamp(int(b[0]) / 1000)
                else:
                    t = datetime.strptime(b[0], "%Y-%m-%d")
                result.append(OHLCVBar(
                    symbol=self._to_stored_symbol(symbol),
                    trade_time=t,
                    open_=float(b[1]),
                    close_=float(b[2]),
                    high_=float(b[3]),
                    low_=float(b[4]),
                    volume=float(b[5]),
                    amount=0.0,
                    interval=interval,
                    market=self._detect_market(symbol),
                    provider=self.name,
                ))
            except (KeyError, ValueError, IndexError):
                continue
        return result

    # ── 分钟线 ──────────────────────────────────────────────────────────

    def fetch_minute(
        self,
        symbol: str,
        interval: str = "5m",
        datalen: int = 3000,
    ) -> list[OHLCVBar]:
        """
        腾讯分钟数据
        注意：datalen 限制因市场而异，需要测试
        """
        api_sym = self._to_api_symbol(symbol)
        # 转换 interval 字符串到腾讯的 scale
        # 腾讯 API: day=日线, m5=5分钟, m15=15分钟, m60=60分钟
        period_map = {
            "1m": "m1", "5m": "m5", "15m": "m15", "30m": "m30", "60m": "m60",
            "1d": "day",
        }
        period = period_map.get(interval, "m5")
        try:
            url = (
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                f"?_var=kline_dayqfq&param={api_sym},{period},,,{datalen},qfq"
            )
            r = self._session.get(url, timeout=self._timeout)
            r.raise_for_status()
            raw = r.text
            m = re.match(r"kline_dayqfq=(.+)", raw, re.DOTALL)
            if not m:
                return []
            data = json.loads(m.group(1))
            inner = data.get("data", {})
            if isinstance(inner, list):
                return []
            stock_data = inner.get(api_sym, {})
            if not stock_data:
                return []
            bars = stock_data.get("qfqday") or stock_data.get("day") or []
            if not bars:
                return []
            return self._parse_bars(symbol, bars, interval)
        except Exception:
            return []

    # ── 股票列表 ────────────────────────────────────────────────────────

    def get_stock_list(self, market: str = "A") -> list[str]:
        """通过 Sina 获取A股列表，腾讯只提供K线"""
        from .sina_provider import SinaProvider
        sina = SinaProvider(timeout=self._timeout, rate_delay=0.1)
        return sina.get_stock_list(market=market)

    def validate_symbol(self, symbol: str) -> bool:
        if symbol.startswith(("sh6", "sh5", "sh9")):
            return True
        if symbol.startswith(("sz0", "sz3")):
            return True
        if symbol.startswith("hk") or symbol.startswith("HK"):
            return True
        return False

    # ── 工具 ────────────────────────────────────────────────────────────

    def _to_api_symbol(self, symbol: str) -> str:
        """转换为腾讯API需要的格式"""
        # A股：直接用 sh600000
        # H股：转换为 hk00700
        s = symbol.lower()
        if s.startswith("hk"):
            return s  # 腾讯格式 hk00700
        return symbol  # Sina格式 sh600000 / sz000001

    def _to_stored_symbol(self, symbol: str) -> str:
        """转换为存储格式"""
        s = symbol.lower()
        if s.startswith("hk"):
            return symbol.replace("hk", "").upper()  # hk00700 → 00700
        return symbol  # sh600000 → sh600000

    @staticmethod
    def _detect_market(symbol: str) -> str:
        if symbol.lower().startswith("hk"):
            return "HK"
        return "A"
