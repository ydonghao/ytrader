"""portfolio_risk 纯函数测试。"""
from src.domain.market.fundamental.portfolio_risk import (
    correlation_matrix,
    fair_value_range,
    industry_concentration,
    portfolio_valuation,
)


def _pos(sym, value, industry, pe=None, pb=None):
    return {"symbol": sym, "value": value, "industry": industry,
            "pe_ttm": pe, "pb": pb}


def test_industry_concentration_flags():
    positions = [
        _pos("sh600036", 100.0, "银行", 8, 0.9),
        _pos("sh601166", 90.0, "银行", 6, 0.6),
        _pos("sh600519", 60.0, "白酒", 25, 8),
        _pos("sh600276", 50.0, "白酒", 30, 5),
    ]
    out = industry_concentration(positions)
    by = {g["industry"]: g for g in out["groups"]}
    assert round(by["银行"]["weight_pct"], 1) == 63.3   # 190/300
    assert round(by["白酒"]["weight_pct"], 1) == 36.7
    assert any("银行" in f for f in out["flags"])   # >40%


def test_concentration_unknown_industry_grouped():
    out = industry_concentration([
        _pos("a", 1.0, None), _pos("b", 1.0, "白酒"),
    ])
    names = {g["industry"] for g in out["groups"]}
    assert "未知" in names and "白酒" in names


def test_correlation_matrix_and_effective_n():
    # 两只完全同步 + 一只零波动(相关不可算按0) → 有效仓位显著<3
    r = {"a": [0.01, -0.02, 0.03, 0.01],
         "b": [0.01, -0.02, 0.03, 0.01],
         "c": [0.0, 0.0, 0.0, 0.0]}
    weights = {"a": 0.4, "b": 0.4, "c": 0.2}
    out = correlation_matrix(r, weights)
    assert abs(out["matrix"][("a", "b")] - 1.0) < 1e-9
    assert ("a", "c") not in out["matrix"]   # 零方差→None
    # ΣΣwᵢwⱼρ=0.68 → N_eff≈1.47
    assert out["effective_positions"] < 2.0


def test_correlation_matrix_missing_series_degrades():
    out = correlation_matrix({"a": [0.01, 0.02]}, {"a": 1.0})
    assert out["matrix"] == {} and out["effective_positions"] is None


def test_portfolio_valuation_weighted():
    out = portfolio_valuation([
        _pos("a", 100.0, "X", pe=10.0, pb=1.0),
        _pos("b", 300.0, "Y", pe=20.0, pb=2.0),
    ])
    assert out["pe_ttm"] == 17.5     # (100*10+300*20)/400
    assert out["pb"] == 1.75


def test_fair_value_range():
    out = fair_value_range({
        "dcf_upside": 0.8, "ddm_upside": 0.2,
        "asset_upside": 0.6, "comps_upside": 0.4,
    })
    # ratio = 1+upside → [1.2,1.8] 中位 1.4
    assert out["median_ratio"] == 1.5   # 偶数个取中间均值(1.4,1.6)
    assert out["low_ratio"] == 1.2 and out["high_ratio"] == 1.8
    assert out["verdict"] == "undervalued"   # 现价=1.0 < 1.2


# ── F3a: DCF 敏感性网格 ───────────────────────────────────────────────────
from src.domain.market.fundamental.dcf import (
    dcf_intrinsic_value,
    dcf_sensitivity_grid,
)


def test_sensitivity_grid_shape_and_monotonicity():
    waccs = [0.08, 0.09, 0.10]
    growths = [0.02, 0.03]
    base = 100.0
    grid = dcf_sensitivity_grid(
        base, waccs, growths,
    )
    assert len(grid) == len(waccs) and len(grid[0]) == len(growths)
    # wacc 越低内在值越高; g 越高内在值越高
    assert grid[0][0] > grid[2][0]
    assert grid[0][1] > grid[0][0]
    # 越界组合(wacc<=g)为 None
    bad = dcf_sensitivity_grid(base, [0.02], [0.05])
    assert bad[0][0] is None


# ── 三期G4: 压力测试 ──────────────────────────────────────────────────────
from src.domain.market.fundamental.portfolio_risk import (
    stress_test as stress_fn,
)


def test_stress_test_uses_own_history():
    positions = [
        {"symbol": "a", "weight": 0.5},
        {"symbol": "b", "weight": 0.5},
    ]
    scenarios = [{"name": "2018", "index_drop_pct": -30.0}]
    history = {"2018": {"a": -40.0, "b": None}}   # b 缺历史→用指数
    out = stress_fn(positions, scenarios, history)
    sc = out["scenarios"][0]
    assert sc["portfolio_pct"] == -35.0          # 0.5×-40 + 0.5×-30
    assert sc["worst_symbol"] == "a"
    assert sc["imputed"][0] == ("b", "指数×1.0")


def test_stress_empty():
    assert stress_fn([], [], {})["scenarios"] == []
