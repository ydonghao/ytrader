"""
TDD: Provider + Fetcher 分离模式测试

Ref: market-data-design.md §三 Provider + Fetcher 分离模式
"""
import sys
import os

# Add backend/ to path (same pattern as existing tests)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar


# === 测试 1: Provider 抽象基类 ===

def test_provider_has_name():
    """Provider 必须有 name 属性"""
    from src.domain.market.providers.base import Provider

    @dataclass
    class TestProvider(Provider):
        pass

    p = TestProvider(name="test_provider")
    assert p.name == "test_provider"


def test_provider_has_credentials():
    """Provider 必须有 credentials 列表（可为空）"""
    from src.domain.market.providers.base import Provider

    @dataclass
    class TestProvider(Provider):
        name = "test"
        credentials: list = field(default_factory=list)
        fetcher_dict: dict = field(default_factory=dict)

    p = TestProvider()
    assert isinstance(p.credentials, list)


def test_provider_has_fetcher_dict():
    """Provider 必须有 fetcher_dict，映射 endpoint -> Fetcher 类"""
    from src.domain.market.providers.base import Provider

    @dataclass
    class MockFetcher:
        pass

    @dataclass
    class TestProvider(Provider):
        name = "test"
        credentials: list = field(default_factory=list)
        fetcher_dict: dict = field(default_factory=dict)

    p = TestProvider()
    p.fetcher_dict["equity_historical"] = MockFetcher
    assert "equity_historical" in p.fetcher_dict
    assert p.fetcher_dict["equity_historical"] is MockFetcher


# === 测试 2: Fetcher 抽象基类 ===

def test_fetcher_has_transform_query():
    """Fetcher 必须有 transform_query 静态方法"""
    from src.domain.market.providers.base import Fetcher

    @dataclass
    class TestFetcher(Fetcher):
        pass

    f = TestFetcher()
    assert hasattr(f, "transform_query")
    assert callable(f.transform_query)


def test_fetcher_has_extract_data():
    """Fetcher 必须有 extract_data 静态方法"""
    from src.domain.market.providers.base import Fetcher

    @dataclass
    class TestFetcher(Fetcher):
        pass

    f = TestFetcher()
    assert hasattr(f, "extract_data")
    assert callable(f.extract_data)


def test_fetcher_has_transform_data():
    """Fetcher 必须有 transform_data 静态方法"""
    from src.domain.market.providers.base import Fetcher

    @dataclass
    class TestFetcher(Fetcher):
        pass

    f = TestFetcher()
    assert hasattr(f, "transform_data")
    assert callable(f.transform_data)


def test_fetcher_transform_query_accepts_dict():
    """Fetcher.transform_query 接受 dict 参数并返回 dict"""
    from src.domain.market.providers.base import Fetcher

    @dataclass
    class TestFetcher(Fetcher):
        pass

    params = {"symbol": "AAPL", "start_date": "2024-01-01"}
    result = TestFetcher.transform_query(params)
    assert isinstance(result, dict)


# === 测试 3: OBBject 统一结果封装 ===

def test_obbject_has_results():
    """OBBject 必须有 results 字段"""
    from src.domain.market.obbject import OBBject

    obj = OBBject(results=[1, 2, 3], provider="test")
    assert obj.results == [1, 2, 3]


def test_obbject_has_provider():
    """OBBject 必须有 provider 字段标识数据来源"""
    from src.domain.market.obbject import OBBject

    obj = OBBject(results=[], provider="akshare")
    assert obj.provider == "akshare"


def test_obbject_has_warnings():
    """OBBject 必须有 warnings 列表"""
    from src.domain.market.obbject import OBBject

    obj = OBBject(results=[], provider="akshare", warnings=["data stale"])
    assert obj.warnings == ["data stale"]


def test_obbject_has_chart():
    """OBBject 可选有 chart 字段"""
    from src.domain.market.obbject import OBBject

    obj = OBBject(results=[], provider="akshare", chart=None)
    assert obj.chart is None


def test_obbject_has_extra():
    """OBBject 必须有 extra dict"""
    from src.domain.market.obbject import OBBject

    obj = OBBject(results=[], provider="akshare", extra={"meta": "data"})
    assert obj.extra == {"meta": "data"}


def test_obbject_to_df_method():
    """OBBject 必须有 to_df 方法将 results 转为 DataFrame"""
    from src.domain.market.obbject import OBBject

    data = [{"symbol": "AAPL", "close": 150.0}, {"symbol": "TSLA", "close": 200.0}]
    obj = OBBject(results=data, provider="akshare")
    df = obj.to_df()
    assert len(df) == 2
    assert df["symbol"].iloc[0] == "AAPL"


# === 测试 4: 具体的 AKShare Provider 实现 ===

def test_akshare_provider_instantiable():
    """AKShareProvider 可以被实例化"""
    from src.domain.market.providers.akshare import AKShareProvider

    provider = AKShareProvider()
    assert provider.name == "akshare"
    assert isinstance(provider.credentials, list)


def test_akshare_provider_has_fetcher_dict():
    """AKShareProvider 有预注册的 Fetcher"""
    from src.domain.market.providers.akshare import AKShareProvider

    provider = AKShareProvider()
    assert isinstance(provider.fetcher_dict, dict)
    assert len(provider.fetcher_dict) > 0


def test_akshare_equity_historical_fetcher_exists():
    """AKShareEquityHistoricalFetcher 存在且可实例化"""
    from src.domain.market.providers.akshare import AKShareEquityHistoricalFetcher

    f = AKShareEquityHistoricalFetcher()
    assert hasattr(f, "transform_query")
    assert hasattr(f, "extract_data")
    assert hasattr(f, "transform_data")
