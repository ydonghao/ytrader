"""经典模型（Altman Z / Beneish M）纯函数测试。"""
import pytest

from src.domain.market.fundamental.classic_models import (
    altman_z_score,
    beneish_m_score,
)


class TestAltmanZScore:
    def test_safe_company(self):
        # 强健公司：高营运资本/留存/EBIT/市值、合理销售
        fin = {"total_assets": 1000, "total_liabilities": 400, "revenue": 1200}
        r = altman_z_score(
            fin, market_cap=2000, retained_earnings=300,
            current_assets=600, current_liabilities=200,
            ebit=150,
        )
        # X1=0.4 X2=0.3 X3=0.15 X4=5.0 X5=1.2
        # Z=1.2*0.4+1.4*0.3+3.3*0.15+0.6*5.0+1.0*1.2 = 0.48+0.42+0.495+3.0+1.2=5.595
        assert r.z == pytest.approx(5.595, rel=1e-3)
        assert r.verdict == "safe"

    def test_distress_company(self):
        # 高负债、亏损、低市值
        fin = {"total_assets": 1000, "total_liabilities": 900, "revenue": 500}
        r = altman_z_score(
            fin, market_cap=100, retained_earnings=-50,
            current_assets=300, current_liabilities=700,
            ebit=-20,
        )
        assert r.verdict == "distress"
        assert r.z < 1.81

    def test_missing_market_cap(self):
        fin = {"total_assets": 1000, "total_liabilities": 400, "revenue": 1200}
        assert altman_z_score(fin, market_cap=None) is None

    def test_missing_core(self):
        # 缺总资产
        assert altman_z_score({}, market_cap=1000) is None

    def test_approximation_when_optional_missing(self):
        # 不传 current_assets/retained/ebit → 用近似/置0 仍出分
        fin = {"total_assets": 1000, "total_liabilities": 400, "revenue": 800,
               "operating_profit": 100, "equity": 500}
        r = altman_z_score(fin, market_cap=1500)
        assert r is not None
        assert r.x1 is None  # 流动资产缺
        assert r.x3 is not None  # 用 operating_profit


class TestBeneishMScore:
    def _clean(self):
        # 两期基本一致、健康 → M 偏低 clean
        return (
            {"revenue": 110, "accounts_receivable": 11, "gross_margin": 0.40,
             "current_assets": 300, "total_assets": 1000, "net_profit": 20,
             "ocf": 25, "total_liabilities": 400},
            {"revenue": 100, "accounts_receivable": 10, "gross_margin": 0.40,
             "current_assets": 280, "total_assets": 950, "net_profit": 18,
             "ocf": 22, "total_liabilities": 380},
        )

    def _manipulator(self):
        # 应收暴增 + 毛利骤降 + 应计大(净利>>OCF) → M 升 manipulator
        return (
            {"revenue": 150, "accounts_receivable": 40, "gross_margin": 0.25,
             "current_assets": 400, "total_assets": 1000, "net_profit": 30,
             "ocf": 5, "total_liabilities": 420},
            {"revenue": 100, "accounts_receivable": 10, "gross_margin": 0.45,
             "current_assets": 300, "total_assets": 1000, "net_profit": 15,
             "ocf": 20, "total_liabilities": 400},
        )

    def test_clean_lower_than_manipulator(self):
        rc = beneish_m_score(*self._clean())
        rm = beneish_m_score(*self._manipulator())
        assert rc is not None and rm is not None
        assert rm.m > rc.m  # 操纵案例 M 更高

    def test_manipulator_components(self):
        r = beneish_m_score(*self._manipulator())
        # DSRI 应显著 >1（应收占比上升）
        assert r.components["DSRI"] > 1.5
        # GMI >1（毛利率下降：0.45/0.25）
        assert r.components["GMI"] > 1.0
        # TATA 为正大值（净利远大于 OCF）
        assert r.components["TATA"] > 0.02

    def test_partial_when_no_depreciation_sga(self):
        r = beneish_m_score(*self._clean())
        assert r.partial is True  # 无折旧/销管费
        assert r.components["DEPI"] is None

    def test_missing_core_returns_none(self):
        bad = {"revenue": 100}  # 缺 total_assets 等
        assert beneish_m_score(bad, bad) is None


# ── 2026-10 红旗补全: 标准 9 因子 Piotroski F-Score ───────────────────────
from src.domain.market.fundamental.classic_models import piotroski_f_score


class TestPiotroskiFScore:
    def _prev(self):
        return {"net_profit": 90.0, "total_assets": 1000.0, "ocf": 80.0,
                "revenue": 900.0, "gross_margin": 0.30,
                "short_loan": 100.0, "long_loan": 100.0,
                "current_assets": 400.0, "current_liabilities": 300.0,
                "share_capital": 100.0}

    def _curr(self):
        # 全因子改善: ROA 9%→10%, OCF 150, 杠杆 20%→10%,
        # 流动比率 1.33→1.50, 股本不变, 毛利率 30%→35%, 周转 0.90→1.00
        return {"net_profit": 100.0, "total_assets": 1000.0, "ocf": 150.0,
                "revenue": 1000.0, "gross_margin": 0.35,
                "short_loan": 50.0, "long_loan": 50.0,
                "current_assets": 450.0, "current_liabilities": 300.0,
                "share_capital": 100.0}

    def test_all_nine_pass(self):
        f = piotroski_f_score(self._curr(), self._prev())
        assert f is not None
        assert f.score == 9 and f.evaluated == 9
        assert f.partial is False and f.verdict == "strong"

    def test_deteriorating_low_score(self):
        prev = {"net_profit": 20.0, "total_assets": 1000.0, "ocf": 30.0,
                "revenue": 950.0, "gross_margin": 0.10,
                "short_loan": 150.0, "long_loan": 150.0,
                "current_assets": 300.0, "current_liabilities": 400.0,
                "share_capital": 100.0}
        curr = {"net_profit": 10.0, "total_assets": 1000.0, "ocf": 5.0,
                "revenue": 900.0, "gross_margin": 0.09,
                "short_loan": 200.0, "long_loan": 200.0,
                "current_assets": 250.0, "current_liabilities": 450.0,
                "share_capital": 120.0}   # 增发
        f = piotroski_f_score(curr, prev)
        assert f.score == 2   # 仅 ROA>0 / OCF>0
        assert f.verdict == "weak"

    def test_partial_when_shares_missing(self):
        curr = {k: v for k, v in self._curr().items()
                if k != "share_capital"}
        prev = {k: v for k, v in self._prev().items()
                if k != "share_capital"}
        f = piotroski_f_score(curr, prev)
        assert f.evaluated == 8 and f.partial is True
        assert f.score == 8   # 其余 8 项全过
        assert f.components["no_share_dilution"]["pass"] is None

    def test_leverage_fallback_to_total_liabilities(self):
        # 有息负债四项全缺 → 退化用资产负债率口径
        curr = {k: v for k, v in self._curr().items()
                if k not in ("short_loan", "long_loan")}
        prev = {k: v for k, v in self._prev().items()
                if k not in ("short_loan", "long_loan")}
        curr["total_liabilities"] = 400.0   # 40%
        prev["total_liabilities"] = 500.0   # 50% → 下降,过
        f = piotroski_f_score(curr, prev)
        assert f.components["leverage_decreasing"]["pass"] is True
        assert "资产负债率" in f.components["leverage_decreasing"]["why"]

    def test_core_missing_returns_none(self):
        prev_no_ta = {k: v for k, v in self._prev().items()
                      if k != "total_assets"}
        assert piotroski_f_score(self._curr(), prev_no_ta) is None
        assert piotroski_f_score({}, self._prev()) is None
