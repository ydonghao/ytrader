"""
OBBject - 统一结果封装

参考 OpenBB 的 OBBject 模式：
所有 API 返回值统一封装，保留 provider、warnings、chart 元数据。
"""
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, Optional

import pandas as pd


@dataclass
class Warning_:
    """警告信息"""
    message: str
    code: str | None = None


T = TypeVar("T")


@dataclass
class Chart:
    """图表对象"""
    type: str
    data: Any


@dataclass
class OBBject(Generic[T]):
    """
    统一结果封装容器

    Attributes:
        results: 实际数据
        provider: 数据来源
        warnings: 警告信息列表
        chart: 图表对象（可选）
        extra: 附加数据
    """
    results: T
    provider: str
    warnings: list[Warning_] = field(default_factory=list)
    chart: Chart | None = None
    extra: dict = field(default_factory=dict)

    def to_df(self, index: str | None = None) -> pd.DataFrame:
        """将 results 转为 DataFrame"""
        if self.results is None:
            return pd.DataFrame()
        if isinstance(self.results, pd.DataFrame):
            return self.results
        if isinstance(self.results, list) and len(self.results) > 0:
            return pd.DataFrame(self.results)
        return pd.DataFrame()
