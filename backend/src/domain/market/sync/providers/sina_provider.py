"""
SinaProvider
============
新浪财经数据源 SyncProvider 实现。

支持：
  - 日线（5年，datalen=3000）
  - 分钟级（5/15/30/60分钟）

数据源：
  - K线：money.finance.sina.com.cn（需注意456限速）
  - 列表：vip.stock.finance.sina.com.cn（HTTP）
"""
import re
import time as time_module
from datetime import datetime
from typing import Optional

import requests

from ..sync_provider import OHLCVBar, SyncProvider

__all__ = ["SinaProvider"]


# scale → interval 映射
SCALE_TO_INTERVAL = {
    5: "5m",
    15: "15m",
    30: "30m",
    60: "60m",
    240: "1d",
}
INTERVAL_TO_SCALE = {v: k for k, v in SCALE_TO_INTERVAL.items()}


class SinaProvider(SyncProvider):
    """
    新浪财经数据源

    注意事项：
      - 日线：datalen=3000 ≈ 5年，超过3000返回空
      - 分钟线：datalen=3000 有上限（约3个月/5m）
      - 限速：456错误表示日配额耗尽，需等待次日
    """

    name = "sina"
    supports_minute = True

    def __init__(
        self,
        timeout: int = 15,
        rate_delay: float = 0.5,
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
            pool_connections=20, pool_maxsize=20,
            max_retries=requests.packages.urllib3.util.retry.Retry(
                total=3, backoff_factor=0.5,
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
        datalen: int = 3000,
    ) -> list[OHLCVBar]:
        """
        新浪日线数据

        注意：新浪API不支持按日期范围，只能用datalen指定bar数量。
        start_date/end_date 参数仅供记录用，实际通过datalen控制范围。
        """
        try:
            url = (
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
                "/CN_MarketData.getKLineData"
            )
            params = {"symbol": symbol, "scale": 240, "ma": "no", "datalen": datalen}
            r = self._session.get(url, params=params, timeout=self._timeout)
            if r.status_code == 456:
                return []  # 限速，不抛异常
            r.raise_for_status()
            bars = r.json()
            if not isinstance(bars, list):
                return []
            return self._parse_daily(symbol, bars)
        except Exception:
            return []

    def _parse_daily(self, symbol: str, bars: list) -> list[OHLCVBar]:
        result = []
        for b in bars:
            try:
                result.append(OHLCVBar(
                    symbol=symbol,
                    trade_time=datetime.strptime(b["day"], "%Y-%m-%d"),
                    open_=float(b["open"]),
                    close_=float(b["close"]),
                    high_=float(b["high"]),
                    low_=float(b["low"]),
                    volume=float(b["volume"]),
                    amount=0.0,
                    interval="1d",
                    market=self._detect_market(symbol),
                    provider=self.name,
                ))
            except (KeyError, ValueError):
                continue
        return result

    # ── 分钟线 ──────────────────────────────────────────────────────────

    def fetch_minute(
        self,
        symbol: str,
        interval: str = "5m",
        datalen: int = 3000,
    ) -> list[OHLCVBar]:
        scale = INTERVAL_TO_SCALE.get(interval, 5)
        try:
            url = (
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
                "/CN_MarketData.getKLineData"
            )
            params = {"symbol": symbol, "scale": scale, "ma": "no", "datalen": datalen}
            r = self._session.get(url, params=params, timeout=self._timeout)
            if r.status_code == 456:
                return []
            r.raise_for_status()
            bars = r.json()
            if not isinstance(bars, list):
                return []
            return self._parse_minute(symbol, interval, bars)
        except Exception:
            return []

    def _parse_minute(self, symbol: str, interval: str, bars: list) -> list[OHLCVBar]:
        result = []
        for b in bars:
            try:
                # 新浪分钟线格式: {"day": "2026-04-03 14:15:00", ...}
                t = datetime.strptime(b["day"], "%Y-%m-%d %H:%M:%S")
                result.append(OHLCVBar(
                    symbol=symbol,
                    trade_time=t,
                    open_=float(b["open"]),
                    close_=float(b["close"]),
                    high_=float(b["high"]),
                    low_=float(b["low"]),
                    volume=float(b["volume"]),
                    amount=0.0,
                    interval=interval,
                    market=self._detect_market(symbol),
                    provider=self.name,
                ))
            except (KeyError, ValueError):
                continue
        return result

    # ── 股票列表 ────────────────────────────────────────────────────────

    def get_stock_list(self, market: str = "A") -> list[str]:
        if market == "HK":
            return self._get_hk_list()
        return self._get_a_list()

    def _get_a_list(self) -> list[str]:
        """获取A股列表（沪深北交）"""
        all_symbols = []
        for node in ["sh_a", "sz_a"]:
            page = 1
            while True:
                try:
                    url = (
                        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
                        "/Market_Center.getHQNodeData"
                    )
                    params = {
                        "page": page, "num": 1000, "sort": "symbol",
                        "asc": 1, "node": node, "_s_r_a": "page",
                    }
                    r = self._session.get(url, params=params, timeout=self._timeout)
                    r.raise_for_status()
                    items = r.json()
                    if not items:
                        break
                    for item in items:
                        sym = item.get("symbol", "")
                        if self.validate_symbol(sym):
                            all_symbols.append(sym)
                    page += 1
                    if len(items) < 100:
                        break
                    time_module.sleep(0.15)
                except Exception:
                    break
        # 去重保序
        seen = set()
        result = []
        for s in all_symbols:
            if s not in seen:
                seen.add(s)
                result.append(s)
        return result

    def _get_hk_list(self) -> list[str]:
        """获取H股列表（Sina hq批量探测）"""
        hk_codes = set()
        for start in range(1, 10000, 50):
            codes = [f"hk{str(i).zfill(5)}" for i in range(start, start + 50)]
            try:
                r = self._session.get(
                    f"https://hq.sinajs.cn/list={','.join(codes)}",
                    timeout=self._timeout,
                    headers={"Referer": "https://finance.sina.com.cn/"}
                )
                r.raise_for_status()
                for m in re.finditer(r'hq_str_(hk\d+)\s*=\s*"([^"]{5,})"', r.text):
                    hk_codes.add(m.group(1))
            except Exception:
                pass
            time_module.sleep(0.05)
        return sorted(list(hk_codes))

    def validate_symbol(self, symbol: str) -> bool:
        """验证A股代码"""
        return (
            symbol.startswith(("sh6", "sh5", "sh9")) or
            symbol.startswith(("sz0", "sz3")) or
            symbol.startswith(("bj8", "bj4"))
        )

    @staticmethod
    def _detect_market(symbol: str) -> str:
        if symbol.startswith("hk") or symbol.startswith("HK"):
            return "HK"
        return "A"
