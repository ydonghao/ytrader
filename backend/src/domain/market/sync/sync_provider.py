"""
SyncProvider 接口
=================
数据源 Provider 必须实现的接口。
统一的数据格式：OHLCVBar
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class OHLCVBar:
    """统一K线格式（所有数据源共用）"""
    symbol: str
    trade_time: datetime
    open_: float
    close_: float
    high_: float
    low_: float
    volume: float
    amount: float = 0.0
    interval: str = "1d"   # "1d", "5m", "15m", "60m"
    market: str = "A"       # "A", "HK"
    provider: str = ""       # "sina", "tencent"


class SyncProvider(ABC):
    """
    数据源Provider接口

    所有数据源（Sina/Tencent/Akshare）必须实现此接口，
    确保 SyncService 可以统一调用。
    """

    name: str = ""           # "sina" | "tencent"
    supports_minute: bool = False  # 是否支持分钟级

    @abstractmethod
    def fetch_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: int = 1300,
    ) -> list[OHLCVBar]:
        """
        获取日线数据

        Args:
            symbol:     股票代码，如 sh600000 / hk00700
            start_date: 开始日期 YYYY-MM-DD（可选）
            end_date:   结束日期 YYYY-MM-DD（可选）
            datalen:    请求的bar数量（覆盖start_date）

        Returns:
            OHLCVBar 列表，按时间升序
        """
        ...

    @abstractmethod
    def fetch_minute(
        self,
        symbol: str,
        interval: str = "5m",
        datalen: int = 3000,
    ) -> list[OHLCVBar]:
        """
        获取分钟级数据

        Args:
            symbol:   股票代码
            interval: "1m" | "5m" | "15m" | "30m" | "60m"
            datalen:  请求的bar数量

        Returns:
            OHLCVBar 列表，按时间升序
        """
        ...

    @abstractmethod
    def get_stock_list(self, market: str = "A") -> list[str]:
        """
        获取股票列表

        Args:
            market: "A" | "HK"

        Returns:
            symbol 列表，如 ["sh600000", "sz000001"]
        """
        ...

    @abstractmethod
    def validate_symbol(self, symbol: str) -> bool:
        """验证symbol是否有效"""
        ...

    # ── 日期范围拉取（可选，支持长历史的 Provider 覆盖）────────────────────
    def fetch_daily_range(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """按日期范围拉日线。默认回退到 fetch_daily(datalen)，忽略日期
        （Sina/Tencent 不支持服务端日期范围）。AkshareProvider 等覆盖此方法。"""
        return self.fetch_daily(symbol, datalen=3000)

    def fetch_minute_range(
        self,
        symbol: str,
        interval: str = "5m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """按日期范围拉分钟线。默认回退到 fetch_minute(datalen)。"""
        return self.fetch_minute(symbol, interval=interval, datalen=3000)
