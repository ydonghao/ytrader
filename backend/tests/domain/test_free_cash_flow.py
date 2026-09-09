"""自由现金流(free_cash_flow)派生计算测试。

覆盖 financial_full.compute_derived 与 period_transform 单季换算
对 FCF = ocf - |capex| 的处理（修正 fcf 字段命名陷阱：原 fcf 实为筹资流，
真实自由现金流由 ocf - 资本支出 计算）。
"""
import datetime as dt

from src.infra.database.market.financial_full import compute_derived
from src.domain.market.fundamental.period_transform import (
    transform_to_quarter,
)


class TestComputeDerivedFreeCashFlow:
    def test_fcf_equals_ocf_minus_capex(self):
        d = {"ocf": 100.0, "capex": 30.0}
        compute_derived(d)
        assert d["free_cash_flow"] == 70.0

    def test_fcf_with_negative_capex_uses_abs(self):
        # capex 口径为负（现金流出）时取绝对值
        d = {"ocf": 100.0, "capex": -30.0}
        compute_derived(d)
        assert d["free_cash_flow"] == 70.0

    def test_no_capex_no_fcf(self):
        d = {"ocf": 100.0}
        compute_derived(d)
        assert "free_cash_flow" not in d

    def test_no_ocf_no_fcf(self):
        d = {"capex": 30.0}
        compute_derived(d)
        assert "free_cash_flow" not in d


class TestQuarterTransformFreeCashFlow:
    def test_single_quarter_fcf_recomputed(self):
        # 两期累计：Q1 ocf=100 capex=20；Q2 累计 ocf=250 capex=50
        # 单季 Q2 = ocf 250-100=150, capex 50-20=30, FCF=120
        rows = [
            {
                "report_date": dt.date(2024, 3, 31),
                "ocf": 100.0,
                "capex": 20.0,
            },
            {
                "report_date": dt.date(2024, 6, 30),
                "ocf": 250.0,
                "capex": 50.0,
            },
        ]
        out = transform_to_quarter(rows)
        # Q1 第一期保持累计，FCF=100-20=80
        assert out[0]["free_cash_flow"] == 80.0
        # Q2 单季 FCF=150-30=120
        assert out[1]["free_cash_flow"] == 120.0
