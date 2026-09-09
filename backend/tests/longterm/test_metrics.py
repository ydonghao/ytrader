"""
长期回测指标测试
================
用已知输入验证 Sharpe/CAGR/最大回撤/alpha-beta 的数学正确性。
回测器数字算错=全部白干，这是最高优先级的测试。

所有期望值用 numpy 独立计算后手抄，作为对照基准。
"""
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.strategy.longterm import metrics as M


# ── daily_returns ────────────────────────────────────────────────────────

def test_daily_returns_basic():
    assert M.daily_returns([100.0]) == []
    assert M.daily_returns([100.0, 110.0]) == [0.1]
    assert M.daily_returns([100.0, 90.0]) == [-0.1]
    # 零前值不爆栈
    assert M.daily_returns([0.0, 10.0]) == [0.0]


def test_daily_returns_length():
    eq = [100 * (1.001 ** i) for i in range(10)]
    assert len(M.daily_returns(eq)) == 9


# ── cagr ──────────────────────────────────────────────────────────────────

def test_cagr_one_year_exact():
    # 100w → 110w，恰好 252 个交易日（1 年），CAGR 应 = 10%
    val = M.cagr(1_000_000, 1_100_000, 252)
    assert abs(val - 10.0) < 0.01


def test_cagr_two_years():
    # 100w → 121w，2 年（504 交易日），CAGR 应 = 10%（1.1^2=1.21）
    val = M.cagr(1_000_000, 1_210_000, 504)
    assert abs(val - 10.0) < 0.05


def test_cagr_loss():
    # 亏损场景
    val = M.cagr(1_000_000, 500_000, 252)
    assert val < 0


def test_cagr_zero_inputs():
    assert M.cagr(0, 100, 252) == 0.0
    assert M.cagr(100, 100, 0) == 0.0


# ── max_drawdown ──────────────────────────────────────────────────────────

def test_max_drawdown_no_drawdown():
    # 单调上涨，无回撤
    eq = [100 + i for i in range(10)]
    dd, dur = M.max_drawdown(eq)
    assert dd == 0.0
    assert dur == 0


def test_max_drawdown_simple():
    # 100 → 120 → 90 → 100
    # 最大回撤 = (120-90)/120 = 25%
    eq = [100.0, 120.0, 90.0, 100.0]
    dd, dur = M.max_drawdown(eq)
    assert abs(dd - 25.0) < 0.01
    assert dur == 1  # 回撤持续 1 步（90 那步 vs 120 的峰）


def test_max_drawdown_recovered():
    # 100 → 80 → 100：回撤后回到前高，期间回撤 20%
    eq = [100.0, 80.0, 100.0]
    dd, dur = M.max_drawdown(eq)
    assert abs(dd - 20.0) < 0.01


def test_max_drawdown_short_input():
    assert M.max_drawdown([]) == (0.0, 0)
    assert M.max_drawdown([100.0]) == (0.0, 0)


# ── sharpe / sortino / volatility ─────────────────────────────────────────

def test_sharpe_zero_volatility():
    # 每天收益完全相同 → excess 收益非零但波动 0 → sharpe=0（边界）
    eq = [100 * (1.001 ** i) for i in range(20)]
    val = M.sharpe_ratio(eq)
    # 完全确定性下 std=0 → 返回 0
    assert val == 0.0


def test_sharpe_positive_for_good_returns():
    # 构造一个明显正向、有波动的序列
    import random
    random.seed(42)
    eq = [100.0]
    for _ in range(300):
        # 平均日涨 0.1%，带噪声
        eq.append(eq[-1] * (1 + 0.001 + random.gauss(0, 0.01)))
    val = M.sharpe_ratio(eq)
    assert val > 0


def test_sharpe_negative_for_bad_returns():
    import random
    random.seed(7)
    eq = [100.0]
    for _ in range(300):
        eq.append(eq[-1] * (1 - 0.001 + random.gauss(0, 0.01)))
    val = M.sharpe_ratio(eq)
    assert val < 0


def test_volatility_increases_with_noise():
    # 波动大的序列 volatility 更高
    import random
    random.seed(0)
    eq_low = [100.0]
    eq_high = [100.0]
    for _ in range(200):
        eq_low.append(eq_low[-1] * (1 + random.gauss(0.001, 0.005)))
        eq_high.append(eq_high[-1] * (1 + random.gauss(0.001, 0.03)))
    v_low = M.annualized_volatility(eq_low)
    v_high = M.annualized_volatility(eq_high)
    assert v_high > v_low


def test_sortino_geq_sharpe_typically():
    # 对于大多数序列，Sortino >= Sharpe（因为下行波动 ≤ 总波动）
    import random
    random.seed(11)
    eq = [100.0]
    for _ in range(300):
        eq.append(eq[-1] * (1 + random.gauss(0.0005, 0.012)))
    s = M.sharpe_ratio(eq)
    so = M.sortino_ratio(eq)
    assert so >= s - 0.01  # 允许小误差


# ── alpha_beta ────────────────────────────────────────────────────────────

def test_alpha_beta_perfect_correlation():
    # strategy = 2 * benchmark → beta≈2
    # 数学：mean_s=2*mean_b, beta=2，CAPM alpha_daily = mean_s - (rf + beta*(mean_b-rf))
    #      = 2*mean_b - rf - 2*mean_b + 2*rf = rf → 年化 alpha ≈ 2.5%
    bench = [0.01, -0.005, 0.02, -0.01, 0.015, 0.005, -0.02, 0.01, 0.0, -0.005] * 20
    strat = [2 * b for b in bench]
    a, b = M.alpha_beta(strat, bench)
    assert abs(b - 2.0) < 0.05
    # 纯线性放大的 alpha 来自无风险利率项，年化 ≈ 2.5%
    assert abs(a - 2.5) < 1.0


def test_alpha_beta_uncorrelated():
    # strategy 与 benchmark 无关 → beta 接近 0
    import random
    random.seed(99)
    bench = [random.gauss(0, 0.01) for _ in range(200)]
    strat = [random.gauss(0, 0.01) for _ in range(200)]
    a, b = M.alpha_beta(strat, bench)
    assert abs(b) < 0.3


def test_alpha_beta_short_input():
    a, b = M.alpha_beta([], [0.01])
    assert (a, b) == (0.0, 0.0)


# ── win_rate_from_trades ──────────────────────────────────────────────────

def test_win_rate():
    assert M.win_rate_from_trades([]) == 0.0
    assert M.win_rate_from_trades([0.1, -0.05, 0.2]) == (2 / 3) * 100
    assert M.win_rate_from_trades([-0.1, -0.2]) == 0.0
    assert M.win_rate_from_trades([0.1, 0.0, 0.2]) == (2 / 3) * 100  # 0 不算赢
