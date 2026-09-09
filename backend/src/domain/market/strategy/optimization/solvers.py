"""组合优化求解器（scipy SLSQP）。

统一约束：
  - 做多：0 ≤ wᵢ ≤ max_weight
  - 留现金：Σwᵢ = 1 - cash_buffer
  - 单标的上限：wᵢ ≤ max_weight（默认 0.4，避免过度集中）

求解器均返回归一化权重向量（和 = 1 - cash_buffer），并 clip 到非负。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import minimize


def _normalize(w: np.ndarray, full: float) -> np.ndarray:
    """clip 非负后归一到 full。"""
    w = np.clip(w, 0.0, None)
    s = w.sum()
    if s > 1e-12:
        return w / s * full
    return w


def solve_min_variance(
    cov: np.ndarray,
    max_weight: float = 0.4,
    cash_buffer: float = 0.05,
) -> np.ndarray:
    """最小方差组合：min wᵀΣw s.t. Σw=full, 0≤wᵢ≤max_weight。"""
    n = cov.shape[0]
    full = 1.0 - cash_buffer

    def obj(w):
        return float(w @ cov @ w)

    def grad(w):
        return 2.0 * (cov @ w)

    cons = [{
        "type": "eq",
        "fun": lambda w: float(np.sum(w) - full),
        "jac": lambda w: np.ones_like(w),
    }]
    bounds = [(0.0, max_weight)] * n
    x0 = np.full(n, full / n)
    res = minimize(
        obj, x0, jac=grad, method="SLSQP",
        bounds=bounds, constraints=cons,
        options={"maxiter": 500, "ftol": 1e-12},
    )
    return _normalize(res.x, full)


def solve_max_sharpe(
    mu: np.ndarray,
    cov: np.ndarray,
    rf: float = 0.0,
    max_weight: float = 0.4,
    cash_buffer: float = 0.05,
) -> np.ndarray:
    """最大夏普（切线）组合：max (wᵀμ-rf)/√(wᵀΣw)。"""
    n = len(mu)
    full = 1.0 - cash_buffer

    def neg_sharpe(w):
        ret = float(w @ mu)
        vol = float(np.sqrt(max(w @ cov @ w, 1e-24)))
        return -(ret - rf) / vol

    cons = [{"type": "eq", "fun": lambda w: float(np.sum(w) - full)}]
    bounds = [(0.0, max_weight)] * n
    x0 = np.full(n, full / n)
    res = minimize(
        neg_sharpe, x0, method="SLSQP",
        bounds=bounds, constraints=cons,
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    return _normalize(res.x, full)


def solve_risk_parity(
    cov: np.ndarray,
    max_weight: float = 0.4,
    cash_buffer: float = 0.05,
) -> np.ndarray:
    """等风险贡献（ERC）：各资产风险贡献相等。

    目标 min Σ(RCᵢ - RC̄)²，其中 RCᵢ = wᵢ·(Σw)ᵢ。
    """
    n = cov.shape[0]
    full = 1.0 - cash_buffer

    def obj(w):
        port_var = float(w @ cov @ w)
        if port_var < 1e-16:
            return 1e6
        rc = w * (cov @ w)  # 各资产风险贡献
        target = port_var / n
        return float(np.sum((rc - target) ** 2))

    cons = [{"type": "eq", "fun": lambda w: float(np.sum(w) - full)}]
    bounds = [(0.0, max_weight)] * n
    x0 = np.full(n, full / n)
    res = minimize(
        obj, x0, method="SLSQP",
        bounds=bounds, constraints=cons,
        options={"maxiter": 2000, "ftol": 1e-14},
    )
    return _normalize(res.x, full)


def risk_contributions(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """各资产的风险贡献（绝对值），用于校验 ERC。"""
    port_var = float(w @ cov @ w)
    if port_var < 1e-16:
        return np.zeros_like(w)
    return w * (cov @ w)


@dataclass
class FrontierPoint:
    weights: np.ndarray
    ret: float
    risk: float
    sharpe: float

    def to_dict(self, symbols: list[str]) -> dict:
        return {
            "ret": round(self.ret, 4),
            "risk": round(self.risk, 4),
            "sharpe": round(self.sharpe, 4),
            "weights": {
                s: round(float(wi), 4)
                for s, wi in zip(symbols, self.weights)
            },
        }


def efficient_frontier(
    mu: np.ndarray,
    cov: np.ndarray,
    n_points: int = 25,
    max_weight: float = 0.4,
    cash_buffer: float = 0.05,
    rf: float = 0.0,
) -> list[FrontierPoint]:
    """采样有效前沿：从最小方差到最大可达收益。

    对每个目标收益解最小方差，得到 (风险, 收益, 夏普, 权重) 序列。
    """
    n = len(mu)
    full = 1.0 - cash_buffer
    if n == 0:
        return []

    bounds = [(0.0, max_weight)] * n
    w_min = solve_min_variance(cov, max_weight, cash_buffer)
    r_min = float(w_min @ mu)
    # 最大可达收益：把 full 全压到收益最高且未触上限的标的
    r_max = float(np.max(mu)) * full
    if r_max <= r_min:
        r_max = r_min + abs(r_min) * 0.1 + 1e-6

    targets = np.linspace(r_min, r_max, n_points)
    pts: list[FrontierPoint] = []
    for tgt in targets:
        cons = [
            {"type": "eq", "fun": lambda w: float(np.sum(w) - full)},
            {"type": "ineq", "fun": lambda w, t=tgt: float(w @ mu - t)},
        ]
        x0 = np.full(n, full / n)
        res = minimize(
            lambda w: float(w @ cov @ w), x0, method="SLSQP",
            bounds=bounds, constraints=cons,
            options={"maxiter": 500, "ftol": 1e-12},
        )
        w = _normalize(res.x, full)
        ret = float(w @ mu)
        risk = float(np.sqrt(max(w @ cov @ w, 0.0)))
        sharpe = (ret - rf) / risk if risk > 1e-12 else 0.0
        pts.append(FrontierPoint(w, ret, risk, sharpe))
    return pts
