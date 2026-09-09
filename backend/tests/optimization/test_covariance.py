"""优化纯函数单测：covariance + solvers。

合成已知数据验证数值正确性，纯函数无 DB 依赖。
"""
import numpy as np
import pytest

from src.domain.market.sync.sync_provider import OHLCVBar
from src.domain.market.strategy.optimization import covariance as cov_mod
from src.domain.market.strategy.optimization import solvers


# ── 协方差 ──────────────────────────────────────────────────────────────────────


def _bars(closes, sym="s", base_day=np.datetime64("2024-01-01")):
    """把收盘价序列构造成 OHLCVBar 列表。"""
    out = []
    for i, c in enumerate(closes):
        out.append(OHLCVBar(
            symbol=sym, trade_time=__import__("datetime").datetime(2024, 1, 1)
            + __import__("datetime").timedelta(days=i),
            open_=c, close_=c, high_=c, low_=c, volume=100.0,
        ))
    return out


class TestPriceMatrix:
    def test_aligns_common_dates_and_truncates_lookback(self):
        bars = {
            "a": _bars([10, 11, 12, 13, 14], "a"),
            "b": _bars([20, 21, 22, 23, 24], "b"),
        }
        symbols, prices = cov_mod.price_matrix(bars, lookback=3)
        assert set(symbols) == {"a", "b"}
        assert prices.shape == (3, 2)
        # 末尾 3 根：a=[12,13,14] b=[22,23,24]
        a_col = prices[:, symbols.index("a")]
        assert np.allclose(a_col, [12, 13, 14])

    def test_returns_empty_when_fewer_than_two_symbols(self):
        bars = {"a": _bars([1, 2, 3], "a")}
        symbols, prices = cov_mod.price_matrix(bars, lookback=10)
        assert symbols == []
        assert prices.shape == (0, 0)

    def test_drops_symbol_with_insufficient_history(self):
        bars = {
            "a": _bars([1, 2, 3, 4, 5], "a"),
            "b": _bars([9], "b"),  # 只有 1 根
        }
        symbols, prices = cov_mod.price_matrix(bars, lookback=5)
        assert symbols == []  # 只剩 1 个有效标的 < 2


class TestReturnsAndCovariance:
    def test_daily_returns_pct_change(self):
        prices = np.array([[10.0], [11.0], [12.1]])
        ret = cov_mod.daily_returns(prices)
        assert ret.shape == (2, 1)
        assert np.allclose(ret[:, 0], [0.1, 0.1])

    def test_covariance_is_symmetric_pd(self):
        rng = np.random.default_rng(42)
        rets = rng.normal(0, 0.01, size=(300, 4))
        cov = cov_mod.covariance_matrix(rets)
        assert cov.shape == (4, 4)
        assert np.allclose(cov, cov.T)
        # 正定：Cholesky 不抛错
        np.linalg.cholesky(cov)

    def test_ensure_pd_repairs_singular_matrix(self):
        singular = np.array([[1.0, 1.0], [1.0, 1.0]])  # 秩 1
        repaired = cov_mod.ensure_positive_definite(singular)
        np.linalg.cholesky(repaired)  # 不抛错即正定

    def test_annualize_scales_by_252(self):
        cov_d = np.array([[0.01, 0.0], [0.0, 0.02]])
        assert np.allclose(cov_mod.annualize_cov(cov_d), cov_d * 252)
        mu_d = np.array([0.001, 0.002])
        assert np.allclose(cov_mod.annualize_returns(mu_d), mu_d * 252)


# ── 求解器 ──────────────────────────────────────────────────────────────────────


def _diag_cov(vols):
    """对角协方差（各资产独立），便于解析校验。"""
    return np.diag(np.array(vols, dtype=float) ** 2)


class TestMinVariance:
    def test_weights_sum_to_full_and_bounded(self):
        cov = _diag_cov([0.2, 0.1, 0.3])
        w = solvers.solve_min_variance(cov, max_weight=0.4, cash_buffer=0.05)
        assert w.shape == (3,)
        assert w.sum() == pytest.approx(0.95, abs=1e-4)
        assert w.min() >= -1e-6
        assert w.max() <= 0.4 + 1e-4

    def test_low_vol_asset_gets_more_weight(self):
        # 资产1波动 0.1 < 资产0 0.2 → 最小方差应更重配资产1
        cov = _diag_cov([0.2, 0.1])
        w = solvers.solve_min_variance(cov, max_weight=0.6, cash_buffer=0.0)
        assert w[1] > w[0]

    def test_variance_le_equal_weight(self):
        rng = np.random.default_rng(7)
        rets = rng.normal(0, 0.02, size=(200, 5))
        cov = cov_mod.covariance_matrix(rets)
        w = solvers.solve_min_variance(cov, max_weight=0.5, cash_buffer=0.0)
        v_min = w @ cov @ w
        w_eq = np.full(5, 0.2)
        v_eq = w_eq @ cov @ w_eq
        assert v_min <= v_eq + 1e-9


class TestMaxSharpe:
    def test_weights_sum_and_bounded(self):
        cov = _diag_cov([0.2, 0.15, 0.25])
        mu = np.array([0.10, 0.12, 0.08])
        w = solvers.solve_max_sharpe(mu, cov, max_weight=0.5, cash_buffer=0.05)
        assert w.sum() == pytest.approx(0.95, abs=1e-4)
        assert w.max() <= 0.5 + 1e-4

    def test_higher_sharpe_than_equal_weight(self):
        cov = _diag_cov([0.2, 0.15, 0.25])
        mu = np.array([0.10, 0.12, 0.08])
        w = solvers.solve_max_sharpe(mu, cov, max_weight=0.6, cash_buffer=0.0)
        sh = (w @ mu) / np.sqrt(w @ cov @ w)
        w_eq = np.full(3, 1 / 3)
        sh_eq = (w_eq @ mu) / np.sqrt(w_eq @ cov @ w_eq)
        assert sh >= sh_eq - 1e-6


class TestRiskParity:
    def test_risk_contributions_approximately_equal(self):
        # 不同波动率 → ERC 让低波动资产占更高权重，使风险贡献相等
        cov = _diag_cov([0.25, 0.15])
        w = solvers.solve_risk_parity(cov, max_weight=0.9, cash_buffer=0.0)
        rc = solvers.risk_contributions(w, cov)
        # 两资产风险贡献应近似相等
        assert rc[0] == pytest.approx(rc[1], rel=0.05)
        assert w.sum() == pytest.approx(1.0, abs=1e-4)

    def test_low_vol_gets_more_weight(self):
        cov = _diag_cov([0.30, 0.10])
        w = solvers.solve_risk_parity(cov, max_weight=0.9, cash_buffer=0.0)
        # 资产1波动小 → 权重更大
        assert w[1] > w[0]


class TestEfficientFrontier:
    def test_frontier_monotone_and_contains_extremes(self):
        cov = _diag_cov([0.2, 0.15, 0.25])
        mu = np.array([0.10, 0.12, 0.08])
        pts = solvers.efficient_frontier(
            mu, cov, n_points=15, max_weight=0.6, cash_buffer=0.0
        )
        assert len(pts) >= 2
        risks = [p.risk for p in pts]
        rets = [p.ret for p in pts]
        # 收益单调不减
        assert all(rets[i + 1] >= rets[i] - 1e-4 for i in range(len(rets) - 1))
        # 第一点风险最小（前沿起点）
        assert risks[0] == pytest.approx(min(risks), abs=1e-6)

    def test_frontier_to_dict_has_weights_per_symbol(self):
        cov = _diag_cov([0.2, 0.15])
        mu = np.array([0.10, 0.12])
        pts = solvers.efficient_frontier(mu, cov, n_points=5)
        d = pts[0].to_dict(["a", "b"])
        assert set(d["weights"].keys()) == {"a", "b"}
        assert "ret" in d and "risk" in d and "sharpe" in d
