"""common_size 接口测试（mock repo，不发 HTTP）。模式抄 test_valuation_percentile_exclude.py。"""
import datetime as dt
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

Q1 = {"一、营业总收入": 100.0, "其中：营业成本": 40.0, "五、净利润": 20.0}
Q2 = {"*营业总收入": 200.0, "其中：营业成本": 60.0}
NO_BASE = {"营业成本": 40.0}


def _row(report_date, detail):
    r = MagicMock()
    r.report_date = report_date
    r.detail = detail
    return r


def _call(rows):
    from src.api.handler.financial_detail_handler import common_size
    repo = MagicMock()
    repo.get_history.return_value = rows
    with patch(
        "src.infra.database.market.financial_full.create_financial_detail_repository",
        return_value=repo,
    ):
        resp = common_size("sh600519", "income", "month", 12)
    return json.loads(resp.body)


def test_basic_descending_and_skip():
    body = _call([
        _row(dt.date(2026, 3, 31), NO_BASE),
        _row(dt.date(2026, 6, 30), Q2),
        _row(dt.date(2026, 9, 30), Q1),
    ])
    assert body["code"] == 0
    data = body["data"]
    assert [p["report_date"] for p in data["periods"]] == ["2026-09-30", "2026-06-30"]
    assert data["base_name"] == "一、营业总收入"
    assert data["total_periods"] == 3
    items = {it["name"]: it for it in data["periods"][0]["items"]}
    assert items["其中：营业成本"]["pct"] == pytest.approx(40.0)
    assert items["一、营业总收入"]["pct"] == 100.0


def test_year_filter_and_limit():
    rows = [
        _row(dt.date(2024, 12, 31), Q1),
        _row(dt.date(2025, 3, 31), Q2),
        _row(dt.date(2025, 12, 31), Q2),
        _row(dt.date(2026, 3, 31), Q1),
    ]
    from src.api.handler.financial_detail_handler import common_size
    repo = MagicMock()
    repo.get_history.return_value = rows
    with patch(
        "src.infra.database.market.financial_full.create_financial_detail_repository",
        return_value=repo,
    ):
        resp = common_size("sh600519", "income", "year", 1)
    data = json.loads(resp.body)["data"]
    assert [p["report_date"] for p in data["periods"]] == ["2025-12-31"]  # 只年报+limit=1


def test_no_data_error():
    body = _call([])
    assert body["code"] != 0


def test_all_periods_no_base():
    body = _call([_row(dt.date(2026, 3, 31), NO_BASE)])
    assert body["code"] == 0
    assert body["data"]["periods"] == []
    assert "note" in body["data"]
