"""五力评分纯函数测试。dict 字面量 + pytest.approx。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.fundamental.five_forces import (
    _absolute_score,
    _score,
    _tier,
    _trend_score,
    five_forces,
)


class TestScoreNormalizer:

    def test_anchor_points(self):
        """p25/p50/p75 → 25/50/75 锚点。"""
        assert _score(10.0, 10.0, 20.0, 30.0) == pytest.approx(25.0)
        assert _score(20.0, 10.0, 20.0, 30.0) == pytest.approx(50.0)
        assert _score(30.0, 10.0, 20.0, 30.0) == pytest.approx(75.0)

    def test_linear_between_anchors(self):
        """p50~p75 中点 → 62.5。"""
        assert _score(25.0, 10.0, 20.0, 30.0) == pytest.approx(62.5)

    def test_clamp_and_invert(self):
        """超出锚点 clamp；invert 翻转（越小越好）。"""
        assert _score(100.0, 10.0, 20.0, 30.0) == pytest.approx(100.0)
        assert _score(0.0, 10.0, 20.0, 30.0) == pytest.approx(0.0)
        # invert：p25→75、p75→25
        assert _score(10.0, 10.0, 20.0, 30.0, invert=True) == \
            pytest.approx(75.0)

    def test_none_and_degenerate(self):
        assert _score(None, 10.0, 20.0, 30.0) is None
        # p25==p75 退化（分布无离散）→ 中位 50
        assert _score(20.0, 15.0, 15.0, 15.0) == pytest.approx(50.0)


class TestTrendScore:

    def test_improving_series_high(self):
        """近3期持续上升 → 高分（应付天数变长=占款增强）。"""
        s = _trend_score([150.0, 140.0, 130.0])  # 最新在前，递增
        assert s > 60.0

    def test_worsening_series_low(self):
        s = _trend_score([100.0, 120.0, 140.0])  # 递减
        assert s < 40.0

    def test_flat_series_mid(self):
        s = _trend_score([100.0, 100.0, 100.0])
        assert s == pytest.approx(50.0)

    def test_insufficient_points_none(self):
        assert _trend_score([100.0]) is None
        assert _trend_score([]) is None


class TestAbsoluteScore:

    def test_rd_intensity_tiers(self):
        """研发费率绝对分档（三段线性：2%→25、5%→50、≥7.5%→100）。"""
        assert _absolute_score(0.05) == pytest.approx(50.0)
        assert _absolute_score(0.035) == pytest.approx(37.5)
        assert _absolute_score(0.06) == pytest.approx(70.0)
        assert _absolute_score(0.01) == pytest.approx(12.5)
        assert _absolute_score(None) is None


class TestTier:

    def test_anchors_exact(self):
        """t1→low、(t1+t2)/2→mid、t2→high 锚点精确。"""
        assert _tier(8.0, 8.0, 15.0, 25.0, 50.0, 75.0) == pytest.approx(25.0)
        assert _tier(11.5, 8.0, 15.0, 25.0, 50.0, 75.0) == pytest.approx(50.0)
        assert _tier(15.0, 8.0, 15.0, 25.0, 50.0, 75.0) == pytest.approx(75.0)

    def test_inverted_extrapolate_clamp(self):
        """σ 稳定性（越低越好）：锚点翻转；超界外延后 clamp[0,100]。"""
        assert _tier(3.0, 3.0, 8.0, 75.0, 50.0, 25.0) == pytest.approx(75.0)
        assert _tier(5.5, 3.0, 8.0, 75.0, 50.0, 25.0) == pytest.approx(50.0)
        assert _tier(8.0, 3.0, 8.0, 75.0, 50.0, 25.0) == pytest.approx(25.0)
        # σ=0 → 75+3*10=105 → clamp 100；σ=100 → clamp 0
        assert _tier(0.0, 3.0, 8.0, 75.0, 50.0, 25.0) == pytest.approx(100.0)
        assert _tier(100.0, 3.0, 8.0, 75.0, 50.0, 25.0) == pytest.approx(0.0)

    def test_none(self):
        assert _tier(None, 8.0, 15.0, 25.0, 50.0, 75.0) is None


def _ratio_period(rd, payable=140.0, receivable=30.0, gm=91.0,
                  roe=34.0, rd_expense=1.9e8, revenue=1.7e11):
    return {"report_date": rd,
            "ratios": {"payable_days": payable, "receivable_days": receivable,
                       "gross_margin": gm, "roe": roe},
            "values": {"revenue": revenue, "rd_expense": rd_expense}}


def _industry(cr4_latest=0.77, hhi=2600.0, roe_med=15.0, gm_med=70.0,
              rev_yoy=0.08, share=0.178, pct_roe=1.0,
              cr4_series=None):
    return {
        "industry": {"level": 2, "code": "801125", "name": "白酒Ⅱ",
                     "degraded": False},
        "sections": [
            {"report_date": "2025-12-31", "cr4": cr4_latest, "hhi": hhi,
             "revenue_yoy": rev_yoy,
             "distribution": {
                 "gross_margin": {"p25": 55.0, "median": gm_med, "p75": 78.0},
                 "roe": {"p25": 8.0, "median": roe_med, "p75": 22.0},
             }},
        ] + (cr4_series or []),
        "peers": [],
        "target": {"revenue_share": share, "percentile_roe": pct_roe,
                   "percentile_gross_margin": 1.0},
    }


class TestLatestSectionAdequacy:

    def test_skips_thin_latest(self):
        """披露中段稀薄期(sample_count<8)被跳过，取最新充足期。
        茅台 substitute 曾因 2026-06-30(n=2,yoy=-53.5%) 得 0。"""
        from src.domain.market.fundamental.five_forces import _latest_section
        industry = {"sections": [
            {"report_date": "2026-06-30", "sample_count": 2,
             "revenue_yoy": -0.535},
            {"report_date": "2026-03-31", "sample_count": 19,
             "revenue_yoy": 0.02},
        ]}
        assert _latest_section(industry)["report_date"] == "2026-03-31"

    def test_missing_sample_count_treated_adequate(self):
        from src.domain.market.fundamental.five_forces import _latest_section
        industry = {"sections": [{"report_date": "2025-12-31"}]}
        assert _latest_section(industry)["report_date"] == "2025-12-31"

    def test_all_thin_falls_back_to_first(self):
        from src.domain.market.fundamental.five_forces import _latest_section
        industry = {"sections": [
            {"report_date": "2026-06-30", "sample_count": 2},
            {"report_date": "2026-03-31", "sample_count": 3},
        ]}
        assert _latest_section(industry)["report_date"] == "2026-06-30"


class TestFiveForces:

    def test_rivalry_high_for_leader(self):
        """龙头（高CR4+份额+毛利/ROE领先）→ rivalry 高分。"""
        data = {
            "ratios": [_ratio_period("2025-12-31")],
            "cashflow": [{"report_date": "2025-12-31",
                          "ratios": {"cash_to_revenue": 1.1}}],
            "industry": _industry(cr4_series=[
                {"report_date": "2024-12-31", "cr4": 0.72},
                {"report_date": "2023-12-31", "cr4": 0.68}]),
        }
        out = five_forces(data)
        rivalry = next(f for f in out["forces"] if f["key"] == "rivalry")
        assert rivalry["score"] > 70.0
        assert rivalry["label"] == "同业竞争格局"
        assert len(rivalry["evidence"]) >= 3

    def test_pct_evidence_values_in_percent_units(self):
        """pct 单位证据值与前端 fmtVal 约定一致：值已是百分数
        （同 gross_margin=91.0），非 0~1 分数——市占率 0.178→17.8、
        行业营收同比 0.08→8.0；score 计算不受影响（仍是分数量纲）。"""
        data = {"ratios": [_ratio_period("2025-12-31")],
                "cashflow": [], "industry": _industry()}
        out = five_forces(data)
        rivalry = next(f for f in out["forces"] if f["key"] == "rivalry")
        share_ev = next(e for e in rivalry["evidence"]
                        if e["metric"] == "市占率")
        assert share_ev["unit"] == "pct"
        assert share_ev["value"] == pytest.approx(17.8)
        assert "17.8%" in share_ev["interpretation"]
        substitute = next(f for f in out["forces"] if f["key"] == "substitute")
        yoy_ev = next(e for e in substitute["evidence"]
                      if e["metric"] == "行业营收同比")
        assert yoy_ev["unit"] == "pct"
        assert yoy_ev["value"] == pytest.approx(8.0)
        assert "8.0%" in yoy_ev["interpretation"]
        rd_ev = next(e for e in substitute["evidence"]
                     if e["metric"] == "研发费率")
        # rd_expense/revenue = 1.9e8/1.7e11 ≈ 0.001118 → 0.1118%
        assert rd_ev["value"] == pytest.approx(0.1118, abs=1e-3)

    def test_rivalry_cr4_window_skips_thin_sections(self):
        """CR4 趋势窗口同走充足期过滤（992a223 同规则）：
        稀薄期(n=2, cr4=0.99)被跳过，cr4_latest 取充足期 0.77。"""
        industry = _industry()
        industry["sections"] = [
            {"report_date": "2026-06-30", "sample_count": 2, "cr4": 0.99},
            {"report_date": "2026-03-31", "sample_count": 19, "cr4": 0.77},
            {"report_date": "2025-12-31", "sample_count": 20, "cr4": 0.75},
        ]
        data = {"ratios": [_ratio_period("2025-12-31")],
                "cashflow": [], "industry": industry}
        out = five_forces(data)
        rivalry = next(f for f in out["forces"] if f["key"] == "rivalry")
        cr4_ev = next(e for e in rivalry["evidence"]
                      if e["metric"] == "CR4趋势")
        assert cr4_ev["value"] == pytest.approx(0.77)
        assert cr4_ev["trend"][:2] == [pytest.approx(0.77),
                                       pytest.approx(0.75)]
        assert "0.77" in cr4_ev["interpretation"]

    def test_forces_structure_and_total(self):
        data = {
            "ratios": [_ratio_period("2025-12-31")],
            "cashflow": [{"report_date": "2025-12-31",
                          "ratios": {"cash_to_revenue": 1.1}}],
            "industry": _industry(),
        }
        out = five_forces(data)
        assert [f["key"] for f in out["forces"]] == [
            "supplier", "buyer", "barrier", "substitute", "rivalry"]
        scored = [f["score"] for f in out["forces"]
                  if f["score"] is not None]
        assert out["total_score"] == pytest.approx(
            sum(scored) / len(scored), abs=1e-2)
        # 每项证据有 metric/value/interpretation
        ev = out["forces"][0]["evidence"][0]
        assert {"metric", "value", "interpretation"} <= set(ev)

    def test_missing_factor_renormalize(self):
        """cashflow 缺失 → buyer 的收现比因子剔除，权重再归一（不None）。"""
        data = {
            "ratios": [_ratio_period("2025-12-31")],
            "cashflow": [],
            "industry": _industry(),
        }
        out = five_forces(data)
        buyer = next(f for f in out["forces"] if f["key"] == "buyer")
        assert buyer["score"] is not None  # 应收+CR4仍可算

    def test_no_industry_partial(self):
        """无行业归属 → 行业因子缺，个股因子仍算，rivalry/barrier None+note。"""
        data = {"ratios": [_ratio_period("2025-12-31")],
                "cashflow": [], "industry": None}
        out = five_forces(data)
        barrier = next(f for f in out["forces"] if f["key"] == "barrier")
        assert barrier["score"] is None
        assert out["note"]

    def test_interpretation_text_present(self):
        data = {"ratios": [_ratio_period("2025-12-31")],
                "cashflow": [], "industry": _industry()}
        out = five_forces(data)
        for f in out["forces"]:
            for ev in f["evidence"]:
                assert isinstance(ev["interpretation"], str)
                assert len(ev["interpretation"]) > 0

    def test_buyer_hand_calc(self):
        """buyer 手算：收现比1.1→100、CR4 0.77→77、应收趋势缺→权重再归一。"""
        data = {
            "ratios": [_ratio_period("2025-12-31")],
            "cashflow": [{"report_date": "2025-12-31",
                          "ratios": {"cash_to_revenue": 1.1}}],
            "industry": _industry(),
        }
        out = five_forces(data)
        buyer = next(f for f in out["forces"] if f["key"] == "buyer")
        # _tier(1.1, .8/1.0, 25/50/75)：超 t2 外延 75+0.1*250→clamp 100
        # _score(0.77, .25/.5/.75)：超 p75 外延 75+0.02*100=77
        expected = (100.0 * 0.35 + 77.0 * 0.3) / (0.35 + 0.3)
        assert buyer["score"] == pytest.approx(expected, abs=1e-2)

    def test_supplier_hand_calc_multi_period(self):
        """supplier 手算：3 期数据 → 应付趋势+毛利率σ+vs行业 三因子齐。"""
        data = {
            "ratios": [
                _ratio_period("2025-12-31", payable=150.0, gm=91.0),
                _ratio_period("2024-12-31", payable=140.0, gm=90.0),
                _ratio_period("2023-12-31", payable=130.0, gm=89.0),
            ],
            "cashflow": [],
            "industry": _industry(),
        }
        out = five_forces(data)
        sup = next(f for f in out["forces"] if f["key"] == "supplier")
        # 应付趋势：_trend_score([150,140,130]) mean=140 slope=10
        s_trend = ((10.0 / 140.0) + 0.1) / 0.2 * 100.0
        # σ=pstdev([91,90,89])=sqrt(2/3)（总体标准差）；<3 → 首段斜率-10 外延
        sigma = (2.0 / 3.0) ** 0.5
        s_sigma = 75.0 + (sigma - 3.0) * (50.0 - 75.0) / (5.5 - 3.0)
        # 毛利率 91 vs 行业分布(55,70,78) → 超 p75 外延后 clamp 100
        expected = s_trend * 0.4 + s_sigma * 0.3 + 100.0 * 0.3
        assert sup["score"] == pytest.approx(expected, abs=1e-2)
