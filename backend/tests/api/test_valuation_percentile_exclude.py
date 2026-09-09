"""valuation_percentile 接口 exclude 参数测试。"""
import sys
import os
import datetime as dt
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest


def _parse_exclude_param_test():
    """验证 exclude 字符串解析为日期区间列表。"""
    from src.api.handler.financial_detail_handler import _parse_exclude_ranges
    result = _parse_exclude_ranges("2020-06-01~2021-02-28,2015-06-15~2015-12-31")
    assert result == [
        (dt.date(2020, 6, 1), dt.date(2021, 2, 28)),
        (dt.date(2015, 6, 15), dt.date(2015, 12, 31)),
    ]


def _parse_exclude_invalid_returns_none_test():
    from src.api.handler.financial_detail_handler import _parse_exclude_ranges
    assert _parse_exclude_ranges("invalid") == []
    assert _parse_exclude_ranges("") == []
    assert _parse_exclude_ranges(None) == []


def test_parse_exclude_param():
    _parse_exclude_param_test()


def test_parse_exclude_invalid():
    _parse_exclude_invalid_returns_none_test()


def test_all_window_fetches_full_history():
    """windows=["all"] 应回溯全部历史（get_range 起点远早于任何固定窗口）。"""
    import json
    from src.api.handler.financial_detail_handler import valuation_percentile
    from src.infra.database.market.valuation import StockValuation

    rows = [
        # 2005~2008 年每季度一个点（32 个样本，过 SAMPLE_MIN=30 门槛）
        StockValuation(
            symbol="sh600519",
            trade_date=dt.date(2005 + i // 4, (i % 4) * 3 + 1, 4),
            pe_ttm=10.0 + i,
        )
        for i in range(31)
    ] + [
        StockValuation(symbol="sh600519", trade_date=dt.date(2026, 7, 24),
                       pe_ttm=100.0),
    ]
    repo = MagicMock()
    repo.get_latest_date.return_value = dt.date(2026, 7, 24)
    repo.get_range.return_value = rows

    with patch(
        "src.infra.database.market.valuation"
        ".create_stock_valuation_repository",
        return_value=repo,
    ), patch(
        "src.domain.market.fundamental.percentile_batch"
        "._get_global_exclude_ranges",
        return_value=[],
    ):
        resp = valuation_percentile(
            "sh600519", windows=["all"], metrics=["pe_ttm"],
        )

    data = json.loads(resp.body)["data"]
    # get_range 起点应早于最早数据（覆盖全部历史而非固定窗口）
    start = repo.get_range.call_args[0][1]
    assert start.year <= 1990
    # series 覆盖最早点；all 窗口分位基于全部样本（100.0 为 32 样本最大值 → 1.0）
    m = data["metrics"]["pe_ttm"]
    assert m["series"][0]["date"] == "2005-01-04"
    assert m["windows"]["all"]["percentile"] == 1.0
    assert m["windows"]["all"]["sample_size"] == 32
