"""指数成分同步 job 纯转换测试。"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pandas as pd

from src.domain.market.sync.jobs.index_constituent_sync import _build_rows


def _df():
    return pd.DataFrame({
        "日期": ["2026-07-31", "2026-07-31"],
        "指数代码": ["000300", "000300"],
        "成分券代码": ["600519", "000001"],
        "成分券名称": ["贵州茅台", "平安银行"],
        "权重": [2.5, 0.433],
    })


def test_build_rows_prefix_and_fields():
    rows = _build_rows("000300", _df())
    assert rows[0] == {
        "index_code": "000300",
        "stock_symbol": "sh600519",
        "stock_name": "贵州茅台",
        "weight": 2.5,
        "as_of_date": date(2026, 7, 31),
    }
    assert rows[1]["stock_symbol"] == "sz000001"
    assert rows[1]["weight"] == 0.433


def test_build_rows_missing_weight_none():
    df = _df()
    df.loc[0, "权重"] = None
    rows = _build_rows("000905", df)
    assert rows[0]["weight"] is None
    assert rows[0]["index_code"] == "000905"
