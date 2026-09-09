"""
Provider + Fetcher 分离模式

参考 OpenBB 的 Provider/Fetcher 架构：
- Provider: 管理凭证、元数据、Provider 级别的配置
- Fetcher: 负责具体的数据拉取 (extract) 和格式转换 (transform)
"""
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, TypeVar


T = TypeVar("T")


@dataclass
class Provider(ABC):
    """
    数据源 Provider 抽象基类

    Attributes:
        name: Provider 名称
        credentials: 凭证列表（如 API key）
        fetcher_dict: endpoint -> Fetcher 类的映射
    """
    name: str = ""
    credentials: list = field(default_factory=list)
    fetcher_dict: dict = field(default_factory=dict)


@dataclass
class Fetcher(ABC):
    """
    数据拉取 Fetcher 抽象基类

    职责：
    - transform_query: 将通用参数转换为数据源特定格式
    - extract_data: 从数据源拉取原始数据
    - transform_data: 将原始数据转换为统一标准格式
    """

    @staticmethod
    def transform_query(params: dict) -> dict:
        """将通用参数转换为数据源特定格式"""
        return params

    @staticmethod
    def extract_data(query: dict, credentials: list) -> Any:
        """从数据源拉取原始数据"""
        raise NotImplementedError

    @staticmethod
    def transform_data(query: dict, raw_data: Any) -> list:
        """将原始数据转换为统一的标准格式"""
        raise NotImplementedError
