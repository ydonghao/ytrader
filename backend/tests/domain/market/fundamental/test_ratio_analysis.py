"""比率分析纯函数测试。镜像 test_common_size.py 风格。"""
import datetime as dt

import pytest

from src.domain.market.fundamental.ratio_analysis import (
    ALL_FIELDS,
    COST_OF_DEBT,
    RATIO_META,
    _effective_tax_rate,
    ratio_series,
    resolve_metric_fields,
)


class TestResolveMetricFields:
    def test_fixed_column_takes_priority(self):
        # 固定列非 None 应压过 detail 候选
        out = resolve_metric_fields({"revenue": 100.0}, [{"一、营业总收入": 999.0}])
        assert out["revenue"] == 100.0

    def test_detail_candidate_across_details(self):
        # 第一个 detail 无该科目 → 继续在第二个 detail 中找
        out = resolve_metric_fields({}, [{"无关": 1.0}, {"*流动资产合计": 80.0}])
        assert out["current_assets"] == 80.0

    def test_string_amount_parsed(self):
        out = resolve_metric_fields({}, [{"流动负债合计": "5亿"}])
        assert out["current_liabilities"] == pytest.approx(5e8)

    def test_hk_candidates(self):
        # 港股东财科目名：营业额 / 除税前溢利 / 权益总额 / 融资成本
        out = resolve_metric_fields(
            {},
            [{"营业额": 300.0, "除税前溢利": 50.0, "融资成本": 5.0},
             {"权益总额": 150.0}],
        )
        assert out["revenue"] == 300.0
        assert out["ebt"] == 50.0
        assert out["equity"] == 150.0
        assert out["interest_expense"] == 5.0
        # 腾讯实测科目名：总权益
        out2 = resolve_metric_fields({}, [None, {"总权益": 120.0}])
        assert out2["equity"] == 120.0

    def test_fixed_assets_candidates(self):
        out = resolve_metric_fields({}, [None, {"固定资产合计": 88.0}])
        assert out["fixed_assets"] == 88.0
        # 港股东财科目名（腾讯实测为无顿号变体，两者并存时带顿号优先）
        out2 = resolve_metric_fields(
            {}, [None, {"物业厂房及设备": 66.0, "物业、厂房及设备": 55.0}]
        )
        assert out2["fixed_assets"] == 55.0
        out3 = resolve_metric_fields({}, [None, {"物业厂房及设备": 66.0}])
        assert out3["fixed_assets"] == 66.0

    def test_missing_returns_none(self):
        out = resolve_metric_fields({}, [{}])
        for f in ALL_FIELDS:
            assert out[f] is None

    def test_none_details_tolerated(self):
        out = resolve_metric_fields({"revenue": 1.0}, None)
        assert out["revenue"] == 1.0
        assert out["current_assets"] is None

    def test_meta_completeness(self):
        assert len(RATIO_META) == 27
        groups = {m["group"] for m in RATIO_META}
        assert groups == {"profitability", "solvency", "efficiency", "growth",
                          "capital_cost"}
        for m in RATIO_META:
            assert m["unit"] in ("pct", "x", "growth", "day", "yi")
            assert m["formula"]

FIN_2024 = {
    "revenue": 100.0, "operating_cost": 40.0, "net_profit": 20.0,
    "operating_profit": 25.0, "total_assets": 200.0, "total_liabilities": 80.0,
    "equity": 120.0, "inventory": 20.0, "accounts_receivable": 30.0,
}
FIN_2025 = {k: v * 2 for k, v in FIN_2024.items()}


def _rec(date, fin=None, details=None):
    return {"report_date": date, "fin": fin or {}, "details": details or []}


class TestRatioSeries:
    def test_profitability_current_period(self):
        out = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025)])
        p = out["periods"][0]
        assert p["ratios"]["gross_margin"] == pytest.approx(60.0)  # (200-80)/200
        assert p["ratios"]["net_margin"] == pytest.approx(20.0)    # 40/200

    def test_solvency_from_details(self):
        details = [{"流动资产合计": 150.0, "流动负债合计": 100.0, "存货": 50.0}]
        out = ratio_series([_rec(dt.date(2025, 12, 31),
                                 {"total_assets": 300.0, "total_liabilities": 120.0},
                                 details)])
        p = out["periods"][0]
        assert p["ratios"]["debt_ratio"] == pytest.approx(40.0)
        assert p["ratios"]["current_ratio"] == pytest.approx(1.5)
        assert p["ratios"]["quick_ratio"] == pytest.approx(1.0)

    def test_interest_cover_ebt_preferred_then_fallback(self):
        out = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025,
                                 [{"利润总额": 60.0, "其中：利息费用": 6.0}])])
        assert out["periods"][0]["ratios"]["interest_cover"] == pytest.approx(10.0)
        # 利润总额缺失 → 营业利润(50)近似；利息费用候选落到"利息支出"
        out2 = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025,
                                  [{"利息支出": 5.0}])])
        assert out2["periods"][0]["ratios"]["interest_cover"] == pytest.approx(10.0)

    def test_average_balance_and_first_period_none(self):
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        first, latest = out["periods"][-1], out["periods"][0]  # 降序
        assert first["ratios"]["roe"] is None                  # 首期无期初
        assert first["ratios"]["asset_turnover"] is None
        assert latest["ratios"]["roe"] == pytest.approx(40.0 / 180.0 * 100)
        assert latest["ratios"]["asset_turnover"] == pytest.approx(
            200.0 / 300.0, abs=1e-3)
        assert latest["ratios"]["inventory_turnover"] == pytest.approx(
            80.0 / 30.0, abs=1e-3)

    def test_yoy_growth(self):
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        latest = out["periods"][0]
        assert latest["ratios"]["revenue_growth"] == pytest.approx(100.0)
        assert latest["ratios"]["asset_growth"] == pytest.approx(100.0)

    def test_yoy_missing_or_nonpositive_base(self):
        fin_bad = dict(FIN_2024)
        fin_bad["net_profit"] = -5.0
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), fin_bad),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        assert out["periods"][0]["ratios"]["profit_growth"] is None
        # 无去年同期在场
        out2 = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025)])
        assert out2["periods"][0]["ratios"]["revenue_growth"] is None

    def test_division_guards(self):
        fin = dict(FIN_2024)
        fin["revenue"] = 0.0
        fin["operating_cost"] = None
        out = ratio_series([_rec(dt.date(2025, 12, 31), fin)])
        r = out["periods"][0]["ratios"]
        assert r["gross_margin"] is None   # 营业成本缺失（金融股）
        assert r["net_margin"] is None     # 收入为 0

    def test_descending_groups_and_values(self):
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        assert [p["report_date"] for p in out["periods"]] == [
            "2025-12-31", "2024-12-31",
        ]
        assert [g["key"] for g in out["groups"]] == [
            "profitability", "solvency", "efficiency", "growth", "capital_cost",
        ]
        keys = [m["key"] for g in out["groups"] for m in g["ratios"]]
        assert set(keys) == {m["key"] for m in RATIO_META}
        assert out["periods"][0]["values"]["revenue"] == pytest.approx(200.0)

    def test_string_report_date(self):
        out = ratio_series([_rec("2025-12-31", FIN_2024)])
        assert out["periods"][0]["report_date"] == "2025-12-31"

    def test_turnover_days_and_new_turnovers(self):
        details = [{"流动资产合计": 150.0, "固定资产合计": 100.0}]
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024, details),
            _rec(dt.date(2025, 12, 31), FIN_2025, details),
        ])
        latest = out["periods"][0]["ratios"]
        # 流动资产周转率 = 200/((150+150)/2)；天数 = 365/率
        assert latest["current_asset_turnover"] == pytest.approx(
            200.0 / 150.0, abs=1e-3)
        assert latest["current_asset_days"] == pytest.approx(
            365.0 / (200.0 / 150.0), abs=0.1)
        # 固定资产周转率 = 200/((100+100)/2) = 2.0
        assert latest["fixed_asset_turnover"] == pytest.approx(2.0)
        assert latest["fixed_asset_days"] == pytest.approx(182.5)
        # 既有周转率对应的天数（平均应收 45 / 平均存货 30 / 平均总资产 300）
        assert latest["receivable_days"] == pytest.approx(
            365.0 / (200.0 / 45.0), abs=0.1)
        assert latest["inventory_days"] == pytest.approx(
            365.0 / (80.0 / 30.0), abs=0.1)
        assert latest["asset_days"] == pytest.approx(
            365.0 / (200.0 / 300.0), abs=0.1)

    def test_days_none_when_rate_missing_or_nonpositive(self):
        out = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025)])  # 首期无期初
        r = out["periods"][0]["ratios"]
        assert r["receivable_days"] is None
        assert r["asset_days"] is None

    def test_roic_basic_and_avg(self):
        # FIN 无 ebt/税/借款 → EBIT=营业利润(50)、税率退化 0、IC=平均权益 180
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        first, latest = out["periods"][-1], out["periods"][0]
        assert first["ratios"]["roic"] is None            # 首期无期初
        assert latest["ratios"]["roic"] == pytest.approx(50.0 / 180.0 * 100)

    def test_roic_tax_and_loans(self):
        fin24 = dict(FIN_2024)
        fin25 = dict(FIN_2025)
        fin24["short_loan"] = 10.0
        fin25["short_loan"] = 20.0
        # 利润总额 80、所得税 20 → 有效税率 25%；IC = 平均(130+10, 260+20) = 210
        # 茅台实测同花顺科目名带章节前缀
        details = [{"四、利润总额": 40.0, "减：所得税费用": 10.0},
                   {"利润总额": 80.0, "所得税费用": 20.0}]
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), fin24, [details[0]]),
            _rec(dt.date(2025, 12, 31), fin25, [details[1]]),
        ])
        latest = out["periods"][0]["ratios"]
        assert latest["roic"] == pytest.approx(
            80.0 * 0.75 / ((120.0 + 10.0 + 240.0 + 20.0) / 2) * 100)

    def test_roic_guards(self):
        # 权益缺失 → None；权益 ≤0 → None
        fin = dict(FIN_2025)
        fin["equity"] = None
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024),
            _rec(dt.date(2025, 12, 31), fin),
        ])
        assert out["periods"][0]["ratios"]["roic"] is None
        fin2 = dict(FIN_2024)
        fin2["equity"] = -5.0
        out2 = ratio_series([
            _rec(dt.date(2024, 12, 31), fin2),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        # 平均 IC = (-5+240)/2 > 0 仍可算；全负时 None 由 _div 守卫
        assert out2["periods"][0]["ratios"]["roic"] is not None


class TestCapitalCost:
    """资本成本组：投资资本/WACC/经济利润（spec 2026-08-18-capital-cost）。"""

    @staticmethod
    def _rec(date, equity=800.0, short=100.0, long=100.0, ebt=200.0,
             tax=50.0, revenue=1000.0, net_profit=150.0):
        return {
            "report_date": date,
            "fin": {
                "revenue": revenue, "net_profit": net_profit,
                "ebt": ebt, "tax": tax,
                "equity": equity, "short_loan": short, "long_loan": long,
                "total_assets": 2000.0, "total_liabilities": 1200.0,
            },
            "details": [None, None],
        }

    def test_effective_tax_rate(self):
        assert _effective_tax_rate(200.0, 50.0) == pytest.approx(0.25)
        assert _effective_tax_rate(200.0, None) == 0.0       # 税缺失按0
        assert _effective_tax_rate(-100.0, 50.0) == 0.0      # ebt非正
        assert _effective_tax_rate(100.0, 200.0) == 1.0      # clamp上限

    def test_wacc_hand_computed(self):
        """ic=800+100+100=1000；债务权重0.2、权益0.8；税率25%
        → 0.2×4.5%×0.75+0.8×8% = 0.675%+6.4% = 7.075%"""
        recs = [self._rec("2024-12-31"), self._rec("2025-12-31")]
        out = ratio_series(recs, cost_of_equity=0.08)
        latest = out["periods"][0]
        assert latest["values"]["invested_capital"] == pytest.approx(1000.0)
        assert latest["ratios"]["wacc"] == pytest.approx(7.075, abs=1e-3)
        # 首期 invested_capital 也为期末时点值（1000），WACC 不受影响
        first = out["periods"][1]
        assert first["values"]["invested_capital"] == pytest.approx(1000.0)
        assert first["ratios"]["wacc"] == pytest.approx(7.075, abs=1e-3)

    def test_capital_cost_keys_readable_from_ratios(self):
        """前端契约：每组 meta 的 key 必须能从 periods[].ratios 读到。
        （invested_capital 曾只放 values 致 UI 全显示'—'——终审 Critical）"""
        recs = [self._rec("2024-12-31"), self._rec("2025-12-31")]
        out = ratio_series(recs, cost_of_equity=0.08)
        p = out["periods"][0]
        assert "invested_capital" in p["ratios"]
        assert p["ratios"]["invested_capital"] == pytest.approx(1000.0)
        assert p["values"]["invested_capital"] == pytest.approx(1000.0)

    def test_wacc_tax_missing(self):
        rec = self._rec("2025-12-31", tax=None)
        out = ratio_series([rec], cost_of_equity=0.08)
        # 0.2×4.5%+0.8×8% = 7.3%
        assert out["periods"][0]["ratios"]["wacc"] == pytest.approx(7.3, abs=1e-3)

    def test_cost_of_equity_none_degrades(self):
        """无权益成本 → wacc/economic_profit None，invested_capital 照常。"""
        out = ratio_series([self._rec("2025-12-31")])
        p = out["periods"][0]
        assert p["values"]["invested_capital"] == pytest.approx(1000.0)
        assert p["ratios"]["wacc"] is None
        assert p["ratios"]["economic_profit"] is None

    def test_economic_profit_hand_computed(self):
        """两期：ic 同值 1000 → 平均 1000；ROIC 与 WACC 之差×平均IC。
        NOPAT=200×0.75=150 → roic=15%；EP=(0.15-0.07075)×1000=79.25"""
        recs = [self._rec("2024-12-31"), self._rec("2025-12-31")]
        out = ratio_series(recs, cost_of_equity=0.08)
        latest = out["periods"][0]
        assert latest["ratios"]["roic"] == pytest.approx(15.0, abs=1e-3)
        assert latest["ratios"]["economic_profit"] == pytest.approx(
            79.25, abs=1e-2)
        # 首期无平均IC → EP None
        assert out["periods"][1]["ratios"]["economic_profit"] is None

    def test_equity_none_all_none(self):
        rec = self._rec("2025-12-31", equity=None)
        out = ratio_series([rec], cost_of_equity=0.08)
        p = out["periods"][0]
        assert p["values"]["invested_capital"] is None
        assert p["ratios"]["wacc"] is None
        assert p["ratios"]["economic_profit"] is None

    def test_groups_and_meta(self):
        out = ratio_series([self._rec("2025-12-31")], cost_of_equity=0.08)
        keys = [g["key"] for g in out["groups"]]
        assert keys[-1] == "capital_cost"
        metas = [m for g in out["groups"] if g["key"] == "capital_cost"
                 for m in g["ratios"]]
        assert [m["key"] for m in metas] == [
            "invested_capital", "wacc", "economic_profit"]
        units = {m["key"]: m["unit"] for m in metas}
        assert units == {"invested_capital": "yi", "wacc": "pct",
                         "economic_profit": "yi"}

    def test_nopat_behavior_unchanged(self):
        """提取 _effective_tax_rate 后 _nopat 行为回归：200×(1-0.25)=150。"""
        from src.domain.market.fundamental.ratio_analysis import _nopat
        assert _nopat(200.0, 50.0) == pytest.approx(150.0)
        assert _nopat(200.0, None) == pytest.approx(200.0)
        assert _nopat(None, 50.0) is None


class TestPayable:
    """应付账款周转（镜像应收，营运组；五力供应商议价力因子）。"""

    @staticmethod
    def _rec(date, revenue=1000.0, payable_avg_cur=200.0,
             payable_avg_prev=200.0):
        # 应付走 detail 候选名（balance detail），平均余额=期初期末均值
        return {
            "report_date": date,
            "fin": {"revenue": revenue},
            "details": [None, {
                "应付账款": payable_avg_cur,
            }],
        }

    def test_payable_turnover_and_days(self):
        # 两期应付均 200（期初期末），营收 1000 → 周转率 5x、天数 73 天
        recs = [
            {"report_date": "2024-12-31", "fin": {"revenue": 1000.0},
             "details": [None, {"应付账款": 200.0}]},
            {"report_date": "2025-12-31", "fin": {"revenue": 1000.0},
             "details": [None, {"应付账款": 200.0}]},
        ]
        out = ratio_series(recs)
        latest = out["periods"][0]
        assert latest["ratios"]["payable_turnover"] == pytest.approx(5.0)
        assert latest["ratios"]["payable_days"] == pytest.approx(73.0)

    def test_payable_missing_detail_none(self):
        recs = [{"report_date": "2025-12-31", "fin": {"revenue": 1000.0},
                 "details": [None, {}]}]
        out = ratio_series(recs)
        assert out["periods"][0]["ratios"]["payable_turnover"] is None

    def test_payable_candidates_variant(self):
        """候选名'应付票据及应付账款'兜底（茅台实测科目）。"""
        recs = [
            {"report_date": "2024-12-31", "fin": {"revenue": 1000.0},
             "details": [None, {"应付票据及应付账款": 200.0}]},
            {"report_date": "2025-12-31", "fin": {"revenue": 1000.0},
             "details": [None, {"应付票据及应付账款": 200.0}]},
        ]
        out = ratio_series(recs)
        assert out["periods"][0]["ratios"]["payable_turnover"] == \
            pytest.approx(5.0)
