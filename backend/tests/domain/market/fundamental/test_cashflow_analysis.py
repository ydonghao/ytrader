"""现金流分析纯函数测试。镜像 test_ratio_analysis.py 风格。"""
import datetime as dt

import pytest

from src.domain.market.fundamental.cashflow_analysis import (
    ALL_FIELDS,
    CASHFLOW_META,
    cashflow_series,
    resolve_cashflow_fields,
)


class TestResolveCashflowFields:
    def test_fixed_column_takes_priority(self):
        # 固定列非 None 应压过 detail 候选
        out = resolve_cashflow_fields(
            {"ocf": 52.0}, [{"经营活动产生的现金流量净额": 999.0}]
        )
        assert out["ocf"] == 52.0

    def test_cash_from_sales_from_detail(self):
        # 销售商品收到的现金无固定列 → cashflow detail 候选名
        out = resolve_cashflow_fields(
            {}, [{"销售商品、提供劳务收到的现金": 210.0}]
        )
        assert out["cash_from_sales"] == 210.0

    def test_restarred_candidate(self):
        out = resolve_cashflow_fields(
            {}, [{"*销售商品、提供劳务收到的现金": 180.0}]
        )
        assert out["cash_from_sales"] == 180.0

    def test_string_amount_parsed(self):
        out = resolve_cashflow_fields({}, [{"销售商品、提供劳务收到的现金": "5亿"}])
        assert out["cash_from_sales"] == pytest.approx(5e8)

    def test_income_fields_from_fin(self):
        out = resolve_cashflow_fields(
            {"revenue": 200.0, "net_profit": 40.0}, [{}]
        )
        assert out["revenue"] == 200.0
        assert out["net_profit"] == 40.0

    def test_missing_returns_none(self):
        out = resolve_cashflow_fields({}, [{}])
        for f in ALL_FIELDS:
            assert out[f] is None

    def test_none_details_tolerated(self):
        out = resolve_cashflow_fields({"ocf": 1.0}, None)
        assert out["ocf"] == 1.0
        assert out["cash_from_sales"] is None

    def test_meta_completeness(self):
        assert len(CASHFLOW_META) == 11
        groups = {m["group"] for m in CASHFLOW_META}
        assert groups == {"profit_quality", "growth", "structure"}
        for m in CASHFLOW_META:
            assert m["unit"] in ("pct", "x", "growth", "yi")
            assert m["formula"]


FIN_2024 = {
    "revenue": 100.0, "net_profit": 20.0, "ocf": 26.0, "icf": -15.0,
    "fcf": -5.0, "capex": 4.0, "free_cash_flow": 22.0, "cash_end": 50.0,
}
FIN_2025 = {k: v * 2 for k, v in FIN_2024.items()}
DETAIL_SALES = [{"销售商品、提供劳务收到的现金": 105.0}]


def _rec(date, fin=None, details=None):
    return {"report_date": date, "fin": fin or {}, "details": details or []}


class TestCashflowSeries:
    def test_profit_quality_current_period(self):
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 {"revenue": 200.0, "net_profit": 40.0, "ocf": 52.0,
                  "capex": 8.0, "free_cash_flow": 44.0},
                 [{"销售商品、提供劳务收到的现金": 210.0}]),
        ])
        r = out["periods"][0]["ratios"]
        assert r["ocf_to_profit"] == pytest.approx(1.3)      # 52/40
        assert r["cash_to_revenue"] == pytest.approx(1.05)   # 210/200
        assert r["fcf_margin"] == pytest.approx(22.0)        # 44/200
        assert r["capex_to_ocf"] == pytest.approx(8.0 / 52.0 * 100)

    def test_fcf_fallback_when_column_missing(self):
        # 旧库缺 free_cash_flow 惰性列 → 兜底 ocf - abs(capex)
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 {"revenue": 200.0, "ocf": 52.0, "capex": 8.0}, []),
        ])
        r = out["periods"][0]["ratios"]
        assert r["fcf_margin"] == pytest.approx(44.0 / 200.0 * 100)
        assert out["periods"][0]["values"]["free_cash_flow"] == \
            pytest.approx(44.0)

    def test_nonpositive_net_profit_and_missing_sales(self):
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 {"revenue": 200.0, "net_profit": -5.0, "ocf": 52.0}, []),
        ])
        r = out["periods"][0]["ratios"]
        assert r["ocf_to_profit"] is None   # 净利≤0（对齐 quality.py）
        assert r["cash_to_revenue"] is None  # 港股常见：科目缺失

    def test_structure_passthrough_with_abs_capex(self):
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 dict(FIN_2025, capex=-16.0, free_cash_flow=None), []),
        ])
        r = out["periods"][0]["ratios"]
        assert r["ocf"] == pytest.approx(52.0)     # 原值透传（元）
        assert r["icf"] == pytest.approx(-30.0)
        assert r["financing"] == pytest.approx(-10.0)  # fcf 列=筹资净额
        assert r["capex"] == pytest.approx(16.0)   # 负值存储 → abs
        assert r["capex_to_ocf"] == pytest.approx(16.0 / 52.0 * 100)
        assert r["fcf_margin"] == pytest.approx(36.0 / 200.0 * 100)  # 52-16

    def test_ocf_nonpositive_guards(self):
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 {"revenue": 200.0, "net_profit": 40.0, "ocf": -3.0,
                  "capex": 8.0}, []),
        ])
        r = out["periods"][0]["ratios"]
        assert r["capex_to_ocf"] is None       # OCF≤0
        assert r["fcf_margin"] is not None     # FCF 可为负，率照算

    def test_yoy_growth(self):
        out = cashflow_series([
            _rec(dt.date(2024, 12, 31), FIN_2024, DETAIL_SALES),
            _rec(dt.date(2025, 12, 31), FIN_2025, DETAIL_SALES),
        ])
        r = out["periods"][0]["ratios"]
        assert r["ocf_yoy"] == pytest.approx(100.0)
        assert r["fcf_yoy"] == pytest.approx(100.0)
        assert r["net_profit_yoy"] == pytest.approx(100.0)
        # 首期（降序后最后一行）无去年同期 → None
        assert out["periods"][-1]["ratios"]["ocf_yoy"] is None

    def test_yoy_nonpositive_base(self):
        fin_bad = dict(FIN_2024)
        fin_bad["ocf"] = -26.0
        out = cashflow_series([
            _rec(dt.date(2024, 12, 31), fin_bad, []),
            _rec(dt.date(2025, 12, 31), FIN_2025, []),
        ])
        assert out["periods"][0]["ratios"]["ocf_yoy"] is None

    def test_descending_groups_and_values(self):
        out = cashflow_series([
            _rec(dt.date(2024, 12, 31), FIN_2024, DETAIL_SALES),
            _rec(dt.date(2025, 12, 31), FIN_2025, DETAIL_SALES),
        ])
        assert [p["report_date"] for p in out["periods"]] == [
            "2025-12-31", "2024-12-31",
        ]
        assert [g["key"] for g in out["groups"]] == [
            "profit_quality", "growth", "structure",
        ]
        keys = [m["key"] for g in out["groups"] for m in g["ratios"]]
        assert set(keys) == {m["key"] for m in CASHFLOW_META}
        assert out["periods"][0]["values"]["ocf"] == pytest.approx(52.0)
        assert out["periods"][0]["values"]["cash_from_sales"] == \
            pytest.approx(105.0)

    def test_string_report_date(self):
        out = cashflow_series([_rec("2025-12-31", FIN_2024, [])])
        assert out["periods"][0]["report_date"] == "2025-12-31"

    def test_empty_and_none_records(self):
        assert cashflow_series([])["periods"] == []
        assert cashflow_series(None)["periods"] == []
        assert cashflow_series([{}])["periods"] == []
