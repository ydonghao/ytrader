"""course_builder 纯函数测试: 分类/配额/估值带/档位/装配。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.portfolio.course_builder import (
    CandidateRow,
    allocate_slots,
    assemble_plan,
    classify_candidates,
    classify_stock,
    derive_payout_ratio,
    derive_revenue_growth,
    pick_top_n,
    plan_ladder,
    plan_pe_band,
    round_to_lot_amount,
    select_pools,
)


# ── 派生指标 ──────────────────────────────────────────────────────
def test_derive_revenue_growth():
    assert abs(derive_revenue_growth([220.0, 200.0]) - 0.10) < 1e-9
    assert derive_revenue_growth([200.0]) is None
    assert derive_revenue_growth([100.0, 0.0]) is None


def test_derive_payout_ratio():
    # dv 5% × PE 10 → 派息率 0.5
    assert derive_payout_ratio(5.0, 10.0) == 0.5
    assert derive_payout_ratio(None, 10.0) is None
    assert derive_payout_ratio(5.0, None) is None


# ── 分类 ──────────────────────────────────────────────────────────
def _row(**kw) -> CandidateRow:
    base = dict(symbol="sh600000", dv_ttm=None, pe_ttm=None, total_mv=None,
                roe_pct=None, annual_revenues=[], in_csi300=False)
    base.update(kw)
    return CandidateRow(**base)


def test_classify_dividend():
    # 派息 0.48 ≥0.3, 增速 0.0526 <0.1, 股息率 6 ≥3 → 红利
    row = _row(dv_ttm=6.0, pe_ttm=8.0, annual_revenues=[105.0, 100.0])
    assert classify_stock(row) == "dividend"


def test_classify_growth():
    # 增速 1/3 ≥0.1, 派息 0.2 <0.3, ROE 15 ≥10 → 创新
    row = _row(dv_ttm=0.5, pe_ttm=40.0, annual_revenues=[200.0, 150.0], roe_pct=15.0)
    assert classify_stock(row) == "growth"


def test_classify_bluechip():
    # 沪深300 + ROE 12 → 蓝筹(增长派息都不满足红利/创新)
    row = _row(dv_ttm=2.0, pe_ttm=15.0, annual_revenues=[100.0, 99.0],
               roe_pct=12.0, in_csi300=True)
    assert classify_stock(row) == "bluechip"


def test_classify_dividend_beats_bluechip():
    # 高派息低增长的大盘银行: 同时满足红利与蓝筹 → 红利优先
    row = _row(dv_ttm=6.0, pe_ttm=8.0, annual_revenues=[103.0, 100.0],
               roe_pct=11.0, in_csi300=True)
    assert classify_stock(row) == "dividend"


def test_classify_none_when_insufficient():
    assert classify_stock(_row(dv_ttm=6.0, pe_ttm=8.0)) is None  # 无年报增速
    assert classify_stock(_row(annual_revenues=[200.0, 100.0])) is None  # 无估值


def test_classify_candidates_ranking():
    rows = [
        _row(symbol="A", dv_ttm=6.0, pe_ttm=8.0, annual_revenues=[105.0, 100.0]),
        _row(symbol="B", dv_ttm=8.0, pe_ttm=8.0, annual_revenues=[105.0, 100.0]),
    ]
    out = classify_candidates(rows)
    assert [c.symbol for c in pick_top_n(out, "dividend", 2)] == ["B", "A"]


# ── 配额 ──────────────────────────────────────────────────────────
def test_allocate_slots_balanced_5():
    # 稳健 5:4:1 × 5 → 2/2/1
    assert allocate_slots(5, {"dividend": 0.5, "bluechip": 0.4, "growth": 0.1}) == {
        "dividend": 2, "bluechip": 2, "growth": 1}


def test_allocate_slots_aggressive_8():
    # 积极 3:5:2 × 8 → 2/4/2
    assert allocate_slots(8, {"dividend": 0.3, "bluechip": 0.5, "growth": 0.2}) == {
        "dividend": 2, "bluechip": 4, "growth": 2}


def test_allocate_slots_zero_weight_excluded():
    # 防御 7:3:0 × 6 → 4/2/0(零配比类别显式为 0)
    assert allocate_slots(6, {"dividend": 0.7, "bluechip": 0.3, "growth": 0.0}) == {
        "dividend": 4, "bluechip": 2, "growth": 0}


def test_allocate_slots_radical_6():
    # 激进 0:3:7 × 6 → 2/4
    assert allocate_slots(6, {"dividend": 0.0, "bluechip": 0.3, "growth": 0.7}) == {
        "dividend": 0, "bluechip": 2, "growth": 4}


# ── 整手取整 ──────────────────────────────────────────────────────
def test_round_to_lot_amount():
    assert round_to_lot_amount(15000.0, 10.0) == 15000.0      # 1500股
    assert round_to_lot_amount(15000.0, 7.0) == 14700.0       # 2100股
    assert round_to_lot_amount(50.0, 10.0) == 0.0             # 不足一手


# ── 估值带 ────────────────────────────────────────────────────────
_SERIES_24 = [10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0,
              11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0,
              9.0, 10.0, 11.0, 9.0]


def test_plan_pe_band_low_fair():
    band = plan_pe_band(_SERIES_24, 9.5)  # μ=10, current 9.5 → z<0
    assert band["state"] == "low_fair"
    assert band["sample_count"] == 24
    assert abs(band["mean"] - 10.0) < 0.01


def test_plan_pe_band_insufficient():
    assert plan_pe_band([10.0, 11.0], 10.5)["state"] == "insufficient"
    assert plan_pe_band([], None)["state"] == "insufficient"


def test_plan_pe_band_overvalued():
    series = [10.0] * 30
    assert plan_pe_band(series, 20.0)["state"] == "overvalued"


# ── 档位 ──────────────────────────────────────────────────────────
def test_plan_ladder_low_fair_four_rungs():
    band = {"state": "low_fair", "mean": 10.0, "std": 0.87, "z_score": -0.5,
            "sample_count": 30, "current_pe": 9.5}
    rungs = plan_ladder(band, 10.0, 60000.0)
    assert [r.rung_index for r in rungs] == [0, 1, 2, 3]
    assert rungs[0].price_level == 10.0
    assert abs(rungs[1].price_level - 9.5) < 1e-9
    assert abs(rungs[2].price_level - 9.0) < 1e-9
    assert abs(rungs[3].price_level - 8.5) < 1e-9
    assert all(r.amount > 0 for r in rungs)
    assert not any(r.executed for r in rungs)


def test_plan_ladder_high_fair_anchors():
    band = {"state": "high_fair", "mean": 10.0, "std": 1.0, "z_score": 0.5,
            "sample_count": 30, "current_pe": 10.5}
    rungs = plan_ladder(band, 10.5, 60000.0)
    # 锚定 μ/μ-0.5σ/μ-1σ/μ-1.5σ: 价格=现价×PE目标/现PE
    levels = [r.price_level for r in rungs]
    assert abs(levels[0] - 10.5 * 10.0 / 10.5) < 1e-9
    assert levels == sorted(levels, reverse=True)
    assert levels[0] < 10.5  # 首档低于现价(等待回调)


def test_plan_ladder_waiting_states():
    assert plan_ladder({"state": "overvalued"}, 10.0, 60000.0) == []
    assert plan_ladder({"state": "insufficient"}, 10.0, 60000.0) == []
    assert plan_ladder(None, 10.0, 60000.0) == []


# ── 装配 ──────────────────────────────────────────────────────────
def test_assemble_plan_end_to_end():
    rows = [
        _row(symbol="sh600000", dv_ttm=6.0, pe_ttm=8.0,
             annual_revenues=[105.0, 100.0]),                       # 红利
        _row(symbol="sh601288", dv_ttm=7.0, pe_ttm=6.0,
             annual_revenues=[103.0, 100.0]),                       # 红利
        _row(symbol="sh600036", dv_ttm=2.0, pe_ttm=15.0,
             annual_revenues=[100.0, 99.0], roe_pct=12.0, in_csi300=True),  # 蓝筹
        _row(symbol="sz000858", dv_ttm=2.5, pe_ttm=12.0,
             annual_revenues=[100.0, 99.0], roe_pct=13.0, in_csi300=True),  # 蓝筹
        _row(symbol="sh300750", dv_ttm=0.5, pe_ttm=40.0,
             annual_revenues=[200.0, 150.0], roe_pct=15.0),         # 创新
    ]
    classified = classify_candidates(rows)
    weights = {"dividend": 0.5, "bluechip": 0.4, "growth": 0.1}
    slots = allocate_slots(5, weights)
    pools = select_pools(classified, slots, multiplier=3)
    names = {r.symbol: r.symbol for r in rows}
    prices = {r.symbol: 10.0 for r in rows}
    pe_series = {r.symbol: list(_SERIES_24) for r in rows}
    current_pes = {r.symbol: 9.5 for r in rows}
    draft = assemble_plan(
        pools=pools, slots=slots, weights=weights, total_capital=500000.0,
        cash_reserve_pct=0.10, names=names, prices=prices,
        pe_series=pe_series, current_pes=current_pes,
    )
    cats = {l.category for l in draft.legs}
    assert cats == {"dividend", "bluechip", "growth"}
    assert len(draft.legs) == 5
    for leg in draft.legs:
        assert leg.target_weight > 0
        assert leg.target_amount > 0
        assert leg.pe_band is not None
        assert len(leg.entry_plan) == 4  # low_fair → 4档
    assert abs(sum(l.target_weight for l in draft.legs) - 1.0) < 1e-6
    # investable = 45万;红利类 2 腿各 11.25万
    div_legs = [l for l in draft.legs if l.category == "dividend"]
    assert all(abs(l.target_amount - 112500.0) < 0.01 for l in div_legs)


def test_assemble_plan_empty_category_warns():
    rows = [
        _row(symbol="sh600000", dv_ttm=6.0, pe_ttm=8.0,
             annual_revenues=[105.0, 100.0]),
    ]
    classified = classify_candidates(rows)
    weights = {"dividend": 0.5, "bluechip": 0.4, "growth": 0.1}
    slots = allocate_slots(5, weights)
    pools = select_pools(classified, slots)
    draft = assemble_plan(
        pools=pools, slots=slots, weights=weights, total_capital=500000.0,
        cash_reserve_pct=0.10, names={"sh600000": "sh600000"},
        prices={"sh600000": 10.0}, pe_series={"sh600000": []},
        current_pes={"sh600000": 8.0},
    )
    assert any("候选池为空" in w for w in draft.warnings)
    assert len(draft.legs) == 1
    assert draft.legs[0].entry_plan == []  # 样本不足 → 无档位
