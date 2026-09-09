"""
AKShare 数据源 Provider

参考 TradingAgents-CN 的 AkShare 集成：
- AKShare 是免费数据源，无需凭证
- 支持 A股、港股、美股、ETF、指数
"""
from dataclasses import dataclass, field
from typing import Any

from .base import Provider, Fetcher


@dataclass
class AKShareProvider(Provider):
    """AKShare 数据源 Provider"""
    name: str = "akshare"
    credentials: list = field(default_factory=list)
    fetcher_dict: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.fetcher_dict:
            self.fetcher_dict = {
                "equity_historical": AKShareEquityHistoricalFetcher,
                "equity_bars": AKShareEquityBarsFetcher,
            }


@dataclass
class AKShareEquityHistoricalFetcher(Fetcher):
    """AKShare 股票历史行情 Fetcher"""

    @staticmethod
    def transform_query(params: dict) -> dict:
        """将通用参数转换为 AKShare 特定格式"""
        return params

    @staticmethod
    def extract_data(query: dict, credentials: list) -> dict:
        """从 AKShare 拉取原始数据（需要实际集成 akshare 库）"""
        raise NotImplementedError("AKShare integration not yet implemented")

    @staticmethod
    def transform_data(query: dict, raw_data: Any) -> list:
        """将原始数据转换为统一的标准格式"""
        raise NotImplementedError("AKShare integration not yet implemented")


@dataclass
class AKShareEquityBarsFetcher(Fetcher):
    """AKShare K线数据 Fetcher"""

    @staticmethod
    def transform_query(params: dict) -> dict:
        """将通用参数转换为 AKShare 特定格式"""
        return params

    @staticmethod
    def extract_data(query: dict, credentials: list) -> dict:
        """从 AKShare 拉取 K线数据"""
        raise NotImplementedError("AKShare integration not yet implemented")

    @staticmethod
    def transform_data(query: dict, raw_data: Any) -> list:
        """将原始数据转换为统一的标准格式"""
        raise NotImplementedError("AKShare integration not yet implemented")
