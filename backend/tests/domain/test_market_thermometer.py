"""market_thermometer 纯函数测试。"""
from src.domain.market.fundamental.market_thermometer import (
    market_thermometer,
)


def test_ep_and_erp_math():
    r = market_thermometer(10.0, 2.0)      # EP=10%, ERP=8%
    assert r["ep_pct"] == 10.0
    assert r["erp_pct"] == 8.0
    assert r["level"] == "deep_cold"
    assert r["position_band"] == {"low": 80, "high": 90}


def test_five_bands_boundaries():
    cases = [
        (5.5, "deep_cold"), (5.4, "cold"), (4.5, "cold"),
        (4.4, "neutral"), (3.5, "neutral"), (3.4, "warm"),
        (2.5, "warm"), (2.4, "hot"),
    ]
    for erp_expected, level in cases:
        # erp = 100/pe - bond → 构造 pe=100/(erp+bond), bond=2
        pe = 100.0 / (erp_expected + 2.0)
        r = market_thermometer(pe, 2.0)
        assert r["level"] == level, f"{erp_expected} → {r['level']}"


def test_percentile():
    pe = 100.0 / (6.0 + 2.0)   # ERP=6
    hist = [3.0, 4.0, 5.0, 7.0]
    r = market_thermometer(pe, 2.0, erp_history=hist)
    assert r["erp_percentile"] == 75.0   # 3/4 ≤ 6


def test_buffett_reference():
    r = market_thermometer(10.0, 2.0, total_mv_sum=100.0, gdp=120.0)
    assert r["buffett_pct"] == 83.3
    assert r["buffett_level"] == "fair"
    r2 = market_thermometer(10.0, 2.0, total_mv_sum=114.0, gdp=120.0)
    assert r2["buffett_pct"] == 95.0
    assert r2["buffett_level"] == "elevated"


def test_missing_inputs_degrade():
    r = market_thermometer(None, 2.0)
    assert r["erp_pct"] is None and r["level"] == "unknown"
    assert r["position_band"] is None
    r2 = market_thermometer(10.0, None)
    assert r2["erp_pct"] is None
    r3 = market_thermometer(10.0, 2.0)
    assert r3["buffett_pct"] is None


# ── 收尾B: 真实债券历史对齐 ────────────────────────────────────────────────
from src.domain.market.fundamental.market_thermometer import (
    build_erp_history,
)


def test_erp_history_carry_forward_alignment():
    pe = [("2026-01-05", 10.0), ("2026-01-20", 12.5)]
    bond = [("2026-01-01", 2.0), ("2026-01-15", 1.5)]
    hist, approx = build_erp_history(pe, bond, current_bond=None)
    # 01-05 用 2.0 → 10-2=8; 01-20 用 1.5(最近) → 8-1.5=6.5
    assert hist == [8.0, 6.5]
    assert approx is False


def test_erp_history_skips_before_bond_start():
    pe = [("2020-01-02", 10.0), ("2026-01-05", 10.0)]
    bond = [("2021-01-01", 2.0)]
    hist, approx = build_erp_history(pe, bond, current_bond=None)
    assert hist == [8.0]   # 2020 点早于债券首日被跳过


def test_erp_history_fallback_approx():
    hist, approx = build_erp_history(
        [("2026-01-05", 10.0)], [], current_bond=2.0)
    assert hist == [8.0]
    assert approx is True   # 无债券历史 → 平移近似


# ── 三期G3: 水位策略回测 ──────────────────────────────────────────────────
from src.domain.market.fundamental.market_thermometer import (
    allocation_backtest,
)


def test_allocation_backtest_beats_hold_in_bear():
    # 构造: 前半牛市(指数1→2, 温度hot)后半熊市(2→1, deep_cold)
    thermo, idx = [], []
    n = 40
    for i in range(n):
        d = f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}"
        level = "hot" if i < n // 2 else "deep_cold"
        thermo.append({"trade_date": d, "level": level,
                       "position_band": {"low": 20, "high": 30}
                       if level == "hot" else {"low": 80, "high": 90}})
        price = 2.0 if i < n // 2 else 1.0
        idx.append({"trade_date": d, "close": price})
    out = allocation_backtest(thermo, idx, rebalance_days=5)
    # 熊市满仓持有回撤50%; 水位策略在熊市降仓 → 回撤显著更小
    assert out["strategy"]["max_drawdown_pct"] < \
        out["buy_hold"]["max_drawdown_pct"]
    assert out["strategy"]["rebalances"] >= 2
    assert out["start"] == thermo[0]["trade_date"]


def test_allocation_backtest_empty():
    out = allocation_backtest([], [])
    assert out["strategy"]["cagr_pct"] is None
