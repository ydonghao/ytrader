"""cashflow_analysis 接口测试（mock repo，不发 HTTP）。
模式抄 test_ratios.py。"""
import datetime as dt
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

INCOME_FIN = {"revenue": 200.0, "net_profit": 40.0}
CASHFLOW_FIN = {
    "ocf": 52.0, "icf": -30.0, "fcf": -10.0, "capex": 8.0,
    "free_cash_flow": 44.0, "cash_end": 100.0,
}


def _income_row(report_date):
    r = MagicMock()
    r.report_date = report_date
    r.detail = {"一、营业总收入": 200.0}
    for k, v in INCOME_FIN.items():
        setattr(r, k, v)
    # MagicMock 自动属性会让 getattr(r, 'ocf') 返回 mock 而非 None，
    # 吞掉 cashflow 行的值——必须显式置 None 模拟"本表无此列"
    for k in ("ocf", "icf", "fcf", "capex", "free_cash_flow", "cash_end"):
        setattr(r, k, None)
    return r


def _cashflow_row(report_date):
    r = MagicMock()
    r.report_date = report_date
    r.detail = {"销售商品、提供劳务收到的现金": 210.0}
    for k, v in CASHFLOW_FIN.items():
        setattr(r, k, v)
    for k in ("revenue", "net_profit"):
        setattr(r, k, None)
    return r


def _cashflow_row_all_none(report_date):
    """数据缺口（如港股）：固定列全未摄取、detail 无候选科目。"""
    r = MagicMock()
    r.report_date = report_date
    r.detail = {}
    for k in ("ocf", "icf", "fcf", "capex", "free_cash_flow", "cash_end",
              "revenue", "net_profit"):
        setattr(r, k, None)
    return r


def _call(income_rows, cashflow_rows, period="month", limit=12):
    from src.api.handler.financial_detail_handler import cashflow_analysis
    repo = MagicMock()
    repo.get_history.side_effect = (
        lambda sym, st: income_rows if st == "income" else cashflow_rows
    )
    with patch(
        "src.infra.database.market.financial_full"
        ".create_financial_detail_repository",
        return_value=repo,
    ):
        resp = cashflow_analysis("sh600519", period, limit)
    return json.loads(resp.body)


def test_basic_merge_and_indicators():
    body = _call(
        [_income_row(dt.date(2024, 12, 31)),
         _income_row(dt.date(2025, 12, 31))],
        [_cashflow_row(dt.date(2024, 12, 31)),
         _cashflow_row(dt.date(2025, 12, 31))],
    )
    assert body["code"] == 0
    data = body["data"]
    assert [p["report_date"] for p in data["periods"]] == [
        "2025-12-31", "2024-12-31",
    ]
    assert [g["key"] for g in data["groups"]] == [
        "profit_quality", "growth", "structure",
    ]
    latest = data["periods"][0]
    assert latest["ratios"]["ocf_to_profit"] == pytest.approx(1.3)
    assert latest["ratios"]["cash_to_revenue"] == pytest.approx(1.05)
    assert latest["ratios"]["fcf_margin"] == pytest.approx(22.0)
    assert latest["ratios"]["financing"] == pytest.approx(-10.0)
    assert latest["values"]["ocf"] == pytest.approx(52.0)
    assert "note" not in data  # 正常路径不附 note


def test_all_none_ratios_note():
    """数据缺口（如港股现金流量表固定列未摄取）：periods 非空但最新期
    11 指标全 None → 附 note 解释，而非让前端渲染纯"—"墙。"""
    body = _call(
        [_income_row(dt.date(2025, 12, 31))],
        [_cashflow_row_all_none(dt.date(2025, 12, 31))],
    )
    assert body["code"] == 0
    data = body["data"]
    assert len(data["periods"]) == 1
    assert all(v is None for v in data["periods"][0]["ratios"].values())
    assert data["note"] == "现金流固定列未摄取（该市场数据待补）"


def test_inner_join_skips_mismatched_dates():
    body = _call(
        [_income_row(dt.date(2024, 12, 31)),
         _income_row(dt.date(2025, 12, 31))],
        [_cashflow_row(dt.date(2025, 12, 31))],  # cashflow 只有 2025
    )
    assert [p["report_date"] for p in body["data"]["periods"]] == \
        ["2025-12-31"]


def test_year_filter_and_limit():
    income = [
        _income_row(dt.date(2024, 12, 31)),
        _income_row(dt.date(2025, 6, 30)),
        _income_row(dt.date(2025, 12, 31)),
    ]
    cashflow = [
        _cashflow_row(dt.date(2024, 12, 31)),
        _cashflow_row(dt.date(2025, 6, 30)),
        _cashflow_row(dt.date(2025, 12, 31)),
    ]
    body = _call(income, cashflow, period="year", limit=1)
    assert [p["report_date"] for p in body["data"]["periods"]] == \
        ["2025-12-31"]


def test_no_income_error():
    assert _call([], [_cashflow_row(dt.date(2025, 12, 31))])["code"] != 0


def test_no_cashflow_error():
    assert _call([_income_row(dt.date(2025, 12, 31))], [])["code"] != 0


def test_route_path_registered_and_distinct():
    """现金流分析路由须用独立路径 /cashflow-analysis——router:477 遗留
    /ratios 遮蔽教训（FastAPI 同路径先注册优先），必须回归测试。"""
    from src.api.router.financial_router import router
    paths = [r.path for r in router.routes]
    assert "/financial/cashflow-analysis/{symbol}" in paths
    assert paths.count("/financial/cashflow-analysis/{symbol}") == 1
    # 既有端点不受影响
    assert "/financial/ratio-analysis/{symbol}" in paths
    assert "/financial/ratios/{symbol}" in paths
