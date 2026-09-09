"""同型分析纯函数测试。镜像 test_quality.py 风格。"""
import datetime as dt

import pytest

from src.domain.market.fundamental.common_size import (
    common_size_rows,
    common_size_series,
    subject_level,
)


class TestSubjectLevel:
    def test_basic(self):
        assert subject_level("一、营业总收入") == 0
        assert subject_level("五、净利润") == 0
        assert subject_level("其中：营业成本") == 2
        assert subject_level("销售费用") == 1
        assert subject_level("*营业总收入") == 1

    def test_edge(self):
        assert subject_level("") == 1
        assert subject_level("其中:营业成本") == 2  # 半角冒号


class TestCommonSizeRows:
    def test_income_basic(self):
        detail = {
            "一、营业总收入": 100.0,
            "其中：营业成本": 40.0,
            "销售费用": 10.0,
            "五、净利润": 20.0,
            "研发费用": None,
        }
        rows = common_size_rows(detail, "income")
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["一、营业总收入"]["pct"] == 100.0
        assert by_name["其中：营业成本"]["pct"] == pytest.approx(40.0)
        assert by_name["销售费用"]["pct"] == pytest.approx(10.0)
        assert by_name["研发费用"]["raw"] is None
        assert by_name["研发费用"]["pct"] is None
        # 顺序 = detail 原始顺序
        assert [r["name"] for r in rows] == list(detail.keys())

    def test_income_star_restatement_and_string_amount(self):
        detail = {"*营业总收入": "1亿", "其中：营业成本": "5000万"}
        rows = common_size_rows(detail, "income")
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["其中：营业成本"]["pct"] == pytest.approx(50.0)

    def test_balance_basic(self):
        rows = common_size_rows({"*资产合计": 200.0, "货币资金": 50.0}, "balance")
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["货币资金"]["pct"] == pytest.approx(25.0)

    def test_cashflow_base_is_inflow_sum(self):
        detail = {
            "经营活动现金流入小计": 60.0,
            "投资活动现金流入小计": 30.0,
            "筹资活动现金流入小计": 10.0,
            "经营活动现金流出小计": 50.0,
        }
        rows = common_size_rows(detail, "cashflow")  # 基准=100
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["经营活动现金流入小计"]["pct"] == pytest.approx(60.0)

    def test_cashflow_missing_inflow_counts_zero(self):
        # 同花顺对无筹资流入的公司填 None（如茅台）→ 按 0 计入基准
        detail = {"经营活动现金流入小计": 60.0, "投资活动现金流入小计": 30.0,
                  "筹资活动现金流入小计": None}
        rows = common_size_rows(detail, "cashflow")  # 基准=90
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["经营活动现金流入小计"]["pct"] == pytest.approx(66.67)

    def test_cashflow_all_inflow_missing_returns_none(self):
        assert common_size_rows({"经营活动现金流出小计": 50.0}, "cashflow") is None

    def test_missing_base_returns_none(self):
        assert common_size_rows({"营业成本": 40.0}, "income") is None
        assert common_size_rows({"货币资金": 1.0}, "balance") is None

    def test_zero_base_returns_none(self):
        assert common_size_rows({"一、营业总收入": 0.0, "营业成本": 1.0}, "income") is None

    def test_hk_subject_names(self):
        # 东财港股科目名：营业额 / 总资产
        rows = common_size_rows({"营业额": 300.0, "行政开支": 30.0}, "income")
        assert rows is not None
        assert {r["name"]: r for r in rows}["行政开支"]["pct"] == pytest.approx(10.0)
        rows = common_size_rows({"总资产": 400.0, "存货": 100.0}, "balance")
        assert rows is not None
        assert {r["name"]: r for r in rows}["存货"]["pct"] == pytest.approx(25.0)

    def test_empty_or_bad_input_returns_none(self):
        assert common_size_rows(None, "income") is None
        assert common_size_rows({}, "income") is None
        assert common_size_rows({"x": 1.0}, "abstract") is None  # 未知 statement_type


class TestCommonSizeSeries:
    def test_descending_and_skip_no_base(self):
        rows = common_size_series(
            [
                {"report_date": dt.date(2026, 3, 31), "detail": {"营业成本": 40.0}},   # 无基准→跳过
                {"report_date": dt.date(2026, 6, 30), "detail": {"*营业总收入": 200.0, "其中：营业成本": 60.0}},
                {"report_date": dt.date(2026, 9, 30), "detail": {"一、营业总收入": 100.0, "其中：营业成本": 40.0}},
            ],
            "income",
        )
        assert [p["report_date"] for p in rows["periods"]] == ["2026-09-30", "2026-06-30"]
        assert rows["base_name"] == "一、营业总收入"  # 最新期命中的候选名
        latest = rows["periods"][0]
        assert latest["base_value"] == 100.0
        by_name = {it["name"]: it for it in latest["items"]}
        assert by_name["其中：营业成本"]["pct"] == pytest.approx(40.0)

    def test_all_no_base(self):
        rows = common_size_series(
            [{"report_date": dt.date(2026, 3, 31), "detail": {"x": 1.0}}], "income"
        )
        assert rows["periods"] == []
        assert rows["base_name"] is None

    def test_string_report_date(self):
        rows = common_size_series(
            [{"report_date": "2025-12-31", "detail": {"一、营业总收入": 10.0}}], "income"
        )
        assert rows["periods"][0]["report_date"] == "2025-12-31"

    def test_cashflow_base_name(self):
        rows = common_size_series(
            [{
                "report_date": dt.date(2025, 12, 31),
                "detail": {
                    "经营活动现金流入小计": 60.0,
                    "投资活动现金流入小计": 30.0,
                    "筹资活动现金流入小计": 10.0,
                },
            }],
            "cashflow",
        )
        assert rows["base_name"] == "现金流入总额(经营+投资+筹资流入小计)"
        assert rows["periods"][0]["base_value"] == pytest.approx(100.0)
