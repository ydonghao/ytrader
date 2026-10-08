# backend/tests/domain/market/industry_analysis/test_prosperity.py
import math

import pytest

from src.domain.market.industry_analysis.prosperity import (
    DEFAULT_WEIGHTS, IndustryInputs, compute_prosperity, net_profit_yoy,
)


def inp(code, **kw):
    base = dict(sw_code=code, name=code, revenue_yoy=None,
                net_profit_yoy=None, pb=None, pb_pct=None, pe_ttm=None,
                pe_pct=None, rs60=None, flow20=None)
    base.update(kw)
    return IndustryInputs(**base)


def test_net_profit_yoy():
    assert net_profit_yoy(120.0, 100.0) == pytest.approx(20.0)
    assert net_profit_yoy(80.0, -100.0) == pytest.approx(180.0)  # 扭亏为盈记正(分母|prev|,方向随变化)
    assert net_profit_yoy(None, 100.0) is None
    assert net_profit_yoy(100.0, 0.0) is None


def test_score_ranks_and_reweights():
    out = compute_prosperity({
        "A": inp("A", revenue_yoy=50.0, net_profit_yoy=60.0, pb=1.0,
                 pb_pct=90.0, pe_ttm=10.0, pe_pct=80.0, rs60=0.3,
                 flow20=1e9),
        "B": inp("B", revenue_yoy=10.0, net_profit_yoy=5.0, pb=2.0,
                 pb_pct=10.0, pe_ttm=30.0, pe_pct=20.0, rs60=-0.1,
                 flow20=-1e9),
    })
    a, b = out["A"], out["B"]
    assert a.score > b.score
    # 盈利分:midrank 截面——A(55) → (1+0.5)/2=75;B(7.5) → 25
    assert a.score_profit == 75.0 and b.score_profit == 25.0
    # 估值分:取反分位 → A 低(高分位=贵)
    assert a.score_valuation < b.score_valuation
    assert a.score_momentum == 75.0
    assert a.inputs["rs60"] == 0.3   # 快照可追溯


def test_missing_component_reweights():
    # 无任何 flow 输入 → flow 分项 None,总分按剩余权重归一仍 0-100
    out = compute_prosperity({
        "A": inp("A", revenue_yoy=20.0, pb_pct=50.0, pe_pct=50.0, rs60=0.1),
    })
    a = out["A"]
    assert a.score_flow is None
    assert a.score is not None and 0 <= a.score <= 100
    # 单行业截面:midrank 全 50,总分 = 50
    assert a.score == 50.0


def test_all_missing_returns_none_score():
    out = compute_prosperity({"A": inp("A")})
    assert out["A"].score is None
    assert out["A"].inputs == {}


def test_weights_from_config():
    out = compute_prosperity({
        "A": inp("A", revenue_yoy=10.0, pb_pct=50.0, pe_pct=50.0, rs60=0.1),
    }, weights={"profit": 1.0, "valuation": 0.0, "momentum": 0.0,
                "flow": 0.0})
    assert out["A"].score == out["A"].score_profit


def test_default_weights_sum_to_one():
    assert math.isclose(sum(DEFAULT_WEIGHTS.values()), 1.0)
