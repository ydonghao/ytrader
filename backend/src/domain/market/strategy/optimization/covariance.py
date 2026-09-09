"""协方差与预期收益估计（纯函数，仅依赖 numpy）。

设计要点：
  - price_matrix() 把各标的 K 线按公共交易日对齐成价格矩阵，
    剔除历史不足的标的，返回 (symbols, prices[T×N])。
  - daily_returns() 价格矩阵 → 日简单收益率矩阵 (T-1)×N。
  - covariance_matrix() 样本协方差，非正定时加 ridge 收缩保证可逆。
  - annualize_cov() / annualize_returns() 年化（×252），供前沿/夏普口径统一。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import numpy as np

from ...sync.sync_provider import OHLCVBar

TRADING_DAYS = 252


def _bar_day(b: OHLCVBar):
    """K 线的交易日（取 date 部分）。"""
    t = b.trade_time
    if hasattr(t, "date"):
        return t.date()
    return t


def price_matrix(
    bars_by_symbol: dict[str, list[OHLCVBar]],
    lookback: int = 120,
) -> tuple[list[str], np.ndarray]:
    """各标的末尾 lookback 根收盘价按公共交易日对齐。

    Returns:
        (symbols, prices[T×N])；可用标的 < 2 或公共交易日 < 2 时
        返回 ([], 空矩阵)。
    """
    per_sym: dict[str, dict] = {}
    for sym, bars in bars_by_symbol.items():
        if not bars:
            continue
        tail = bars[-lookback:] if lookback and len(bars) > lookback else bars
        d2c: dict = {}
        for b in tail:
            c = b.close_
            if c is None or c <= 0:
                continue
            d2c[_bar_day(b)] = float(c)
        if len(d2c) >= 2:
            per_sym[sym] = d2c

    symbols = list(per_sym.keys())
    if len(symbols) < 2:
        return [], np.empty((0, 0))

    common = sorted(set.intersection(*[set(d) for d in per_sym.values()]))
    if len(common) < 2:
        return [], np.empty((0, 0))

    t_len, n = len(common), len(symbols)
    prices = np.empty((t_len, n), dtype=float)
    for j, sym in enumerate(symbols):
        d2c = per_sym[sym]
        for i, dt in enumerate(common):
            prices[i, j] = d2c[dt]
    return symbols, prices


def daily_returns(prices: np.ndarray) -> np.ndarray:
    """价格矩阵 T×N → 日简单收益率 (T-1)×N。"""
    if prices.shape[0] < 2:
        return np.empty((0, prices.shape[1] if prices.ndim == 2 else 0))
    prev = prices[:-1]
    return prices[1:] / prev - 1.0


def _is_pd(m: np.ndarray) -> bool:
    """矩阵是否对称正定（Cholesky 判定）。"""
    try:
        np.linalg.cholesky(m)
        return True
    except np.linalg.LinAlgError:
        return False


def ensure_positive_definite(m: np.ndarray, ridge: float = 1e-8) -> np.ndarray:
    """非正定时加逐步增大的 ridge（对角占优）直到正定。"""
    m = 0.5 * (m + m.T)  # 强制对称
    if _is_pd(m):
        return m
    eye = np.eye(m.shape[0])
    d = max(ridge, 1e-10) * max(np.trace(m) / m.shape[0], 1e-8)
    for _ in range(30):
        m2 = m + d * eye
        if _is_pd(m2):
            return m2
        d *= 10
    return m + d * eye


def covariance_matrix(returns: np.ndarray) -> np.ndarray:
    """样本协方差矩阵 N×N（returns 列为资产）。非正定时收缩。"""
    if returns.shape[0] < 2 or returns.shape[1] == 0:
        return np.empty((0, 0))
    cov = np.cov(returns, rowvar=False)
    cov = np.atleast_2d(cov)
    return ensure_positive_definite(cov)


def annualize_cov(cov_daily: np.ndarray) -> np.ndarray:
    """日协方差 → 年化（×252）。"""
    return cov_daily * TRADING_DAYS


def annualize_returns(ret_daily_mean: np.ndarray) -> np.ndarray:
    """日均收益向量 → 年化（×252）。"""
    return ret_daily_mean * TRADING_DAYS
