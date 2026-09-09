"""ratios 接口测试（mock repo，不发 HTTP）。模式抄 test_common_size.py。"""
import datetime as dt
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

INCOME_FIN = {
    "revenue": 100.0, "operating_cost": 40.0, "net_profit": 20.0,
    "operating_profit": 25.0,
}
BALANCE_FIN = {
    "total_assets": 200.0, "total_liabilities": 80.0, "equity": 120.0,
    "inventory": 20.0, "accounts_receivable": 30.0,
}


def _income_row(report_date):
    r = MagicMock()
    r.report_date = report_date
    r.detail = {"一、营业总收入": 100.0}
    for k, v in INCOME_FIN.items():
        setattr(r, k, v)
    return r


def _balance_row(report_date):
    r = MagicMock()
    r.report_date = report_date
    r.detail = {"流动资产合计": 150.0, "流动负债合计": 100.0}
    for k, v in BALANCE_FIN.items():
        setattr(r, k, v)
    return r


def _call(income_rows, balance_rows, period="month", limit=12):
    from src.api.handler.financial_detail_handler import ratios
    repo = MagicMock()
    repo.get_history.side_effect = (
        lambda sym, st: income_rows if st == "income" else balance_rows
    )
    # 权益成本解析默认走"无归属"路径（get_member → None），
    # 否则未 mock 时会打到真实库，sh600519 恰好有申万归属 → wacc 非 None，
    # 测试随库数据状态漂移。
    sw_repo = MagicMock()
    sw_repo.get_member.return_value = None
    with patch(
        "src.infra.database.market.financial_full"
        ".create_financial_detail_repository",
        return_value=repo,
    ), patch(
        "src.infra.database.market.sw_industry"
        ".create_sw_industry_repository",
        return_value=sw_repo,
    ):
        resp = ratios("sh600519", period, limit)
    return json.loads(resp.body)


def test_basic_merge_and_ratios():
    body = _call(
        [_income_row(dt.date(2024, 12, 31)), _income_row(dt.date(2025, 12, 31))],
        [_balance_row(dt.date(2024, 12, 31)), _balance_row(dt.date(2025, 12, 31))],
    )
    assert body["code"] == 0
    data = body["data"]
    assert [p["report_date"] for p in data["periods"]] == [
        "2025-12-31", "2024-12-31",
    ]
    assert [g["key"] for g in data["groups"]] == [
        "profitability", "solvency", "efficiency", "growth", "capital_cost",
    ]
    latest = data["periods"][0]
    assert latest["ratios"]["gross_margin"] == pytest.approx(60.0)
    assert latest["ratios"]["current_ratio"] == pytest.approx(1.5)
    assert latest["ratios"]["revenue_growth"] == pytest.approx(0.0)  # 两年同值
    assert latest["values"]["revenue"] == pytest.approx(100.0)


def test_inner_join_skips_mismatched_dates():
    body = _call(
        [_income_row(dt.date(2024, 12, 31)), _income_row(dt.date(2025, 12, 31))],
        [_balance_row(dt.date(2025, 12, 31))],  # balance 只有 2025
    )
    assert [p["report_date"] for p in body["data"]["periods"]] == ["2025-12-31"]


def test_year_filter_and_limit():
    income = [
        _income_row(dt.date(2024, 12, 31)),
        _income_row(dt.date(2025, 6, 30)),
        _income_row(dt.date(2025, 12, 31)),
    ]
    balance = [
        _balance_row(dt.date(2024, 12, 31)),
        _balance_row(dt.date(2025, 6, 30)),
        _balance_row(dt.date(2025, 12, 31)),
    ]
    body = _call(income, balance, period="year", limit=1)
    assert [p["report_date"] for p in body["data"]["periods"]] == ["2025-12-31"]


def test_no_income_error():
    assert _call([], [_balance_row(dt.date(2025, 12, 31))])["code"] != 0


def test_no_balance_error():
    assert _call([_income_row(dt.date(2025, 12, 31))], [])["code"] != 0


def test_route_path_registered_and_distinct_from_legacy():
    """比率分析路由须用独立路径 /ratio-analysis——router:477 已有遗留 /ratios
    （FastAPI 同路径先注册优先会遮蔽后注册的），2026-08-18 曾因此崩溃前端。"""
    from src.api.router.financial_router import router
    paths = [r.path for r in router.routes]
    assert "/financial/ratio-analysis/{symbol}" in paths
    # 遗留端点不受影响
    assert "/financial/ratios/{symbol}" in paths
    assert paths.count("/financial/ratio-analysis/{symbol}") == 1


class TestCostOfEquityInjection:

    SECTIONS_801125 = [
        {"sw_code": "801125", "report_date": "2026-06-30", "level": 2,
         "sw_name": "白酒Ⅱ", "sample_count": 2, "revenue_sum": 1e11,
         "net_profit_sum": 4e10, "cr4": None, "cr8": None, "hhi": None,
         "revenue_yoy": None, "distribution": None},
        {"sw_code": "801125", "report_date": "2025-12-31", "level": 2,
         "sw_name": "白酒Ⅱ", "sample_count": 19, "revenue_sum": 9e11,
         "net_profit_sum": 3.4e11, "cr4": 0.77, "cr8": 0.9, "hhi": 2600.0,
         "revenue_yoy": 0.06,
         "distribution": {"gross_margin": {"mean": 70.0},
                          "roe": {"mean": 10.1, "median": 7.939},
                          "net_margin": {"mean": 35.0}}},
    ]

    @staticmethod
    def _sw_repo(member=None, sections=None):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.get_member.return_value = member
        r.fetch_sections.return_value = sections or []
        return r

    def test_annual_median_picked_over_thin_latest(self):
        """最新充足期(2026-06-30 n=2 非年报)被跳过，取 2025-12-31 年报 median。"""
        from src.api.handler.financial_detail_handler import (
            _resolve_cost_of_equity,
        )
        from unittest.mock import patch
        member = {"sw_code_l1": "801080", "sw_code_l2": "801125"}
        repo = self._sw_repo(member, self.SECTIONS_801125)
        with patch(
            "src.infra.database.market.sw_industry"
            ".create_sw_industry_repository", return_value=repo,
        ):
            coe, note = _resolve_cost_of_equity("sh600519")
        assert coe == pytest.approx(0.07939)
        assert "白酒Ⅱ" in note and "7.939" in note and "4.5%" in note

    def test_no_member_returns_none(self):
        """港美股无归属 → (None, None)，不抛异常。"""
        from src.api.handler.financial_detail_handler import (
            _resolve_cost_of_equity,
        )
        from unittest.mock import patch
        with patch(
            "src.infra.database.market.sw_industry"
            ".create_sw_industry_repository",
            return_value=self._sw_repo(None, []),
        ):
            assert _resolve_cost_of_equity("hk00700") == (None, None)

    def test_ratios_no_coe_path(self):
        """无权益成本（未 mock sw 仓库 → 无归属路径）→ wacc None、组仍在。"""
        body = _call(
            [_income_row(dt.date(2024, 12, 31)),
             _income_row(dt.date(2025, 12, 31))],
            [_balance_row(dt.date(2024, 12, 31)),
             _balance_row(dt.date(2025, 12, 31))],
        )
        groups = [g["key"] for g in body["data"]["groups"]]
        assert "capital_cost" in groups
        assert body["data"]["periods"][0]["ratios"]["wacc"] is None

    def test_ratios_with_coe_note(self):
        """有权益成本 → wacc 非 None + note 含行业与假设。"""
        from unittest.mock import MagicMock, patch
        from src.api.handler.financial_detail_handler import ratios
        fin_repo = MagicMock()
        fin_repo.get_history.side_effect = (
            lambda sym, st: (
                [_income_row(dt.date(2024, 12, 31)),
                 _income_row(dt.date(2025, 12, 31))]
                if st == "income" else
                [_balance_row(dt.date(2024, 12, 31)),
                 _balance_row(dt.date(2025, 12, 31))]
            )
        )
        sw_repo = self._sw_repo(
            {"sw_code_l1": "801080", "sw_code_l2": "801125"},
            self.SECTIONS_801125,
        )
        with patch(
            "src.infra.database.market.financial_full"
            ".create_financial_detail_repository", return_value=fin_repo,
        ), patch(
            "src.infra.database.market.sw_industry"
            ".create_sw_industry_repository", return_value=sw_repo,
        ):
            body = json.loads(ratios("sh600519", "month", 12).body)
        d = body["data"]
        assert d["periods"][0]["ratios"]["wacc"] is not None
        assert "ROE中位数" in d["note"] and "4.5%" in d["note"]
