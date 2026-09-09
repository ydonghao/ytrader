"""risk_metrics 纯函数测试 — 已知输入算期望值, 不依赖 DB/网络。

覆盖:
1. Sortino / Calmar 数学正确性(手算期望值);
2. 相关矩阵对称、对角=1、平均相关度;
3. Monte Carlo VaR 合理区间 + 固定 seed 可复现;
4. 场景冲击逻辑: 高有息负债仓位跌幅更大、贡献分解守恒;
5. 历史危机场景参数完备性。
"""
import math

import pytest

from src.domain.market.portfolio.risk_metrics import (
    FACTOR_DRIVEN_SCENARIOS,
    HISTORICAL_CRISIS_SCENARIOS,
    calmar_ratio,
    correlation_matrix,
    debt_shock_multiplier,
    evaluate_stress_scenario,
    monte_carlo_var,
    scenario_position_shocks,
    sortino_ratio,
)


# ══ Sortino ═══════════════════════════════════════════════════════

class TestSortinoRatio:
    def test_known_input_rf_zero(self):
        # 均值 0.005, 下行样本 [-0.01, -0.01]:
        # dd = sqrt((0.0001+0.0001)/2) = 0.01
        rets = [0.02, -0.01, 0.02, -0.01]
        expected = (0.005 / 0.01) * math.sqrt(252)
        assert sortino_ratio(rets, rf=0.0) == pytest.approx(expected)

    def test_known_input_with_rf(self):
        # rf=0.03 → 日频 0.03/252; 负收益日仍为下行样本
        rets = [0.02, -0.01, 0.02, -0.01]
        rf_daily = 0.03 / 252
        excess = [r - rf_daily for r in rets]
        mean = sum(excess) / 4
        downside = [e for e in excess if e < 0]
        dd = math.sqrt(sum(e ** 2 for e in downside) / len(downside))
        expected = (mean / dd) * math.sqrt(252)
        assert sortino_ratio(rets, rf=0.03) == pytest.approx(expected)

    def test_rf_reduces_sortino_for_positive_mean(self):
        rets = [0.02, -0.01, 0.02, -0.01]
        assert sortino_ratio(rets, rf=0.05) < sortino_ratio(rets, rf=0.0)

    def test_no_downside_returns_zero(self):
        assert sortino_ratio([0.01, 0.02, 0.03], rf=0.0) == 0.0

    def test_degenerate_inputs(self):
        assert sortino_ratio([], rf=0.0) == 0.0
        assert sortino_ratio([0.01], rf=0.0) == 0.0

    def test_negative_mean_gives_negative_sortino(self):
        assert sortino_ratio([-0.02, 0.01, -0.02, 0.01], rf=0.0) < 0


# ══ Calmar ════════════════════════════════════════════════════════

class TestCalmarRatio:
    def test_known_input(self):
        # 权益: 1.0 → 1.1 → 0.99 → 1.0395
        # 最大回撤 = (1.1-0.99)/1.1 = 0.1; CAGR = 1.0395^(252/3)-1
        rets = [0.10, -0.10, 0.05]
        final_equity = 1.0 * 1.10 * 0.90 * 1.05
        years = 3 / 252
        cagr = final_equity ** (1.0 / years) - 1.0
        max_dd = (1.10 - 0.99) / 1.10
        assert calmar_ratio(rets) == pytest.approx(cagr / max_dd)

    def test_no_drawdown_returns_zero(self):
        assert calmar_ratio([0.01, 0.01, 0.01]) == 0.0

    def test_monotonic_decline_is_negative(self):
        rets = [-0.01] * 10
        assert calmar_ratio(rets) < 0

    def test_deeper_drawdown_lower_calmar(self):
        # 同终值, 回撤更深 → calmar 更小
        shallow = [0.10, -0.10, 0.05]
        deep = [0.10, -0.50, 0.05]
        assert calmar_ratio(deep) < calmar_ratio(shallow)

    def test_empty(self):
        assert calmar_ratio([]) == 0.0


# ══ 相关矩阵 ══════════════════════════════════════════════════════

class TestCorrelationMatrix:
    def test_perfectly_correlated(self):
        a = [0.01, 0.02, -0.01, 0.005, -0.02]
        rets = {"A": a, "B": [2 * x for x in a]}
        out = correlation_matrix(rets)
        assert out["symbols"] == ["A", "B"]
        assert out["matrix"][0][1] == pytest.approx(1.0)
        assert out["avg_correlation"] == pytest.approx(1.0)

    def test_anti_correlated(self):
        a = [0.01, 0.02, -0.01, 0.005, -0.02]
        rets = {"A": a, "B": [-x for x in a]}
        out = correlation_matrix(rets)
        assert out["matrix"][0][1] == pytest.approx(-1.0)
        assert out["avg_correlation"] == pytest.approx(-1.0)

    def test_symmetric_diagonal_one(self):
        a = [0.01, -0.02, 0.015, 0.004, -0.01, 0.02]
        b = [0.02, -0.01, 0.01, -0.005, 0.0, 0.015]
        c = [-0.01, 0.005, -0.02, 0.01, 0.003, -0.008]
        out = correlation_matrix({"A": a, "B": b, "C": c})
        m = out["matrix"]
        n = len(out["symbols"])
        assert n == 3
        for i in range(n):
            assert m[i][i] == 1.0
            for j in range(n):
                assert m[i][j] == pytest.approx(m[j][i])
                assert -1.0 <= m[i][j] <= 1.0
        # 平均相关度 = 上三角 3 对的均值
        upper = [m[0][1], m[0][2], m[1][2]]
        assert out["avg_correlation"] == pytest.approx(
            sum(upper) / 3
        )

    def test_zero_variance_series(self):
        rets = {"A": [0.01, 0.02, -0.01], "B": [0.0, 0.0, 0.0]}
        out = correlation_matrix(rets)
        assert out["matrix"][0][1] == 0.0
        assert out["matrix"][1][1] == 1.0
        assert out["avg_correlation"] == 0.0

    def test_single_symbol(self):
        out = correlation_matrix({"A": [0.01, 0.02, 0.03]})
        assert out["matrix"] == [[1.0]]
        assert out["avg_correlation"] == 0.0

    def test_mismatched_lengths_truncated(self):
        a = [0.01, 0.02, -0.01, 0.005]
        b = [0.02, 0.04, -0.02]  # 前 3 个与 a 完全正相关
        out = correlation_matrix({"A": a, "B": b})
        assert out["matrix"][0][1] == pytest.approx(1.0)

    def test_short_series_ignored(self):
        out = correlation_matrix({"A": [0.01, 0.02], "B": [0.01]})
        assert out["symbols"] == ["A"]
        assert out["matrix"] == [[1.0]]

    def test_empty(self):
        out = correlation_matrix({})
        assert out == {
            "symbols": [], "matrix": [], "avg_correlation": 0.0
        }


# ══ Monte Carlo VaR ══════════════════════════════════════════════

class TestMonteCarloVar:
    @pytest.fixture()
    def symmetric_returns(self):
        # 50 个 +0.01 / 50 个 -0.01: 均值 0, sigma≈0.01
        return [0.01] * 50 + [-0.01] * 50

    def test_reasonable_range(self, symmetric_returns):
        var = monte_carlo_var(
            symmetric_returns, confidence=0.95, n_sim=10000, seed=7
        )
        sigma = 0.01 * math.sqrt(100 / 99)
        # 正态 95% 分位 ≈ 1.645σ, 允许抽样误差
        assert 1.2 * sigma < var < 2.2 * sigma

    def test_seed_reproducible(self, symmetric_returns):
        v1 = monte_carlo_var(symmetric_returns, seed=42)
        v2 = monte_carlo_var(symmetric_returns, seed=42)
        assert v1 == v2

    def test_higher_confidence_larger_var(self, symmetric_returns):
        v95 = monte_carlo_var(symmetric_returns, 0.95, seed=1)
        v99 = monte_carlo_var(symmetric_returns, 0.99, seed=1)
        assert v99 > v95

    def test_degenerate_inputs(self):
        assert monte_carlo_var([]) == 0.0
        assert monte_carlo_var([0.01], n_sim=0) == 0.0

    def test_zero_variance_positive_drift(self):
        # sigma=0 → 模拟值恒为 mu>0 → 该置信度无损失(<=0)
        assert monte_carlo_var([0.01, 0.01], seed=3) <= 0.0


# ══ 场景冲击逻辑 ═════════════════════════════════════════════════

class TestDebtShockMultiplier:
    def test_high_debt_amplified(self):
        assert debt_shock_multiplier(0.7, 1.0) == pytest.approx(1.75)

    def test_low_debt_dampened(self):
        assert debt_shock_multiplier(0.2, 1.0) == pytest.approx(0.5)

    def test_missing_data_is_neutral(self):
        assert debt_shock_multiplier(None, 1.0) == 1.0

    def test_zero_sensitivity_is_neutral(self):
        assert debt_shock_multiplier(0.9, 0.0) == 1.0

    def test_clamped(self):
        assert debt_shock_multiplier(5.0, 2.0) == 3.0
        assert debt_shock_multiplier(0.0, 10.0) == 0.0


class TestScenarioPositionShocks:
    def test_high_debt_falls_more(self):
        symbols = ["HIGH", "LOW"]
        debt = {"HIGH": 0.7, "LOW": 0.2}
        shocks = scenario_position_shocks(
            symbols, debt, base_shock=-0.08, debt_sensitivity=1.0
        )
        assert shocks["HIGH"] == pytest.approx(-0.14)
        assert shocks["LOW"] == pytest.approx(-0.04)
        assert shocks["HIGH"] < shocks["LOW"] < 0.0

    def test_missing_debt_uses_base(self):
        shocks = scenario_position_shocks(
            ["X", "Y"], {"X": 0.7}, -0.08, debt_sensitivity=1.0
        )
        assert shocks["Y"] == pytest.approx(-0.08)


class TestEvaluateStressScenario:
    POSITIONS = [
        {"symbol": "AAA", "name": "高负债", "market_value": 600.0},
        {"symbol": "BBB", "name": "低负债", "market_value": 400.0},
    ]

    def test_static_uniform_scenario(self):
        sc = {
            "id": "market_crash", "name": "Market Crash",
            "description": "d", "category": "static",
            "shock": -0.20, "probability": 0.03,
        }
        out = evaluate_stress_scenario(sc, self.POSITIONS, {})
        assert out["loss"] == pytest.approx(1000.0 * -0.20)
        assert out["loss_pct"] == pytest.approx(-20.0)
        assert len(out["contributions"]) == 2
        for c in out["contributions"]:
            assert c["shock_pct"] == pytest.approx(-20.0)
        # 贡献之和 = 组合损失
        total = sum(c["loss"] for c in out["contributions"])
        assert total == pytest.approx(out["loss"])

    def test_factor_scenario_high_debt_loses_more(self):
        sc = dict(FACTOR_DRIVEN_SCENARIOS["rate_hike_leverage"])
        debt = {"AAA": 0.7, "BBB": 0.2}
        out = evaluate_stress_scenario(sc, self.POSITIONS, debt)
        by_sym = {c["symbol"]: c for c in out["contributions"]}
        # AAA: -0.08*1.75=-0.14 → 600*(-0.14) = -84
        assert by_sym["AAA"]["loss"] == pytest.approx(-84.0)
        # BBB: -0.08*0.5=-0.04 → 400*(-0.04) = -16
        assert by_sym["BBB"]["loss"] == pytest.approx(-16.0)
        assert out["loss"] == pytest.approx(-100.0)
        assert out["loss_pct"] == pytest.approx(-10.0)
        # 权重和为 1
        assert sum(c["weight"] for c in out["contributions"]) == (
            pytest.approx(1.0)
        )

    def test_factor_without_debt_data_falls_back_to_base(self):
        sc = dict(FACTOR_DRIVEN_SCENARIOS["credit_crunch"])
        out = evaluate_stress_scenario(sc, self.POSITIONS, {})
        assert out["loss"] == pytest.approx(1000.0 * -0.12)

    def test_contributions_sorted_by_loss(self):
        sc = dict(FACTOR_DRIVEN_SCENARIOS["rate_hike_leverage"])
        debt = {"AAA": 0.7, "BBB": 0.2}
        out = evaluate_stress_scenario(sc, self.POSITIONS, debt)
        losses = [c["loss"] for c in out["contributions"]]
        assert losses == sorted(losses)
        assert out["contributions"][0]["symbol"] == "AAA"

    def test_empty_positions(self):
        sc = {"id": "x", "shock": -0.2, "probability": 0.01}
        out = evaluate_stress_scenario(sc, [], {})
        assert out["loss"] == 0.0
        assert out["contributions"] == []

    def test_zero_value_positions_ignored(self):
        positions = self.POSITIONS + [
            {"symbol": "CCC", "name": "零值", "market_value": 0.0}
        ]
        sc = {"id": "x", "shock": -0.2, "probability": 0.01}
        out = evaluate_stress_scenario(sc, positions, {})
        assert out["loss"] == pytest.approx(1000.0 * -0.2)


# ══ 场景定义参数 ══════════════════════════════════════════════════

class TestScenarioDefinitions:
    def test_historical_crises_params(self):
        expected = {
            "crisis_2008": -0.6539,
            "crash_2015": -0.4334,
            "bear_2018": -0.2459,
            "bear_2022": -0.1513,
        }
        assert set(HISTORICAL_CRISIS_SCENARIOS) == set(expected)
        for sid, shock in expected.items():
            sc = HISTORICAL_CRISIS_SCENARIOS[sid]
            assert sc["shock"] == pytest.approx(shock)
            assert sc["category"] == "historical"
            assert sc["source"]  # 参数出处必填
            assert 0 < sc["probability"] < 1

    def test_factor_scenarios_have_sensitivity(self):
        for sc in FACTOR_DRIVEN_SCENARIOS.values():
            assert sc["category"] == "factor"
            assert sc["debt_sensitivity"] > 0
            assert -1.0 < sc["shock"] < 0.0

    def test_all_shocks_valid_range(self):
        for sc in list(FACTOR_DRIVEN_SCENARIOS.values()) + list(
            HISTORICAL_CRISIS_SCENARIOS.values()
        ):
            assert -1.0 <= sc["shock"] < 0.0
            assert 0.0 <= sc["probability"] <= 1.0
