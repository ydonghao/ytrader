"""
长期回测绩效指标
================
所有指标基于"日频收益率/日频权益曲线"计算，口径统一、无未来函数。
这些函数是回测可信度的命脉，配套 test_metrics.py 用已知输入校验数值。

参考标准：
  - Sharpe / Sortino / Volatility 按 252 交易日年化
  - CAGR = (final/initial)^(1/years) - 1
  - Max Drawdown = max((peak - trough) / peak)
  - Alpha / Beta 用日频超额收益做线性回归（CAPM）
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

TRADING_DAYS_PER_YEAR = 252


def daily_returns(equity_curve: list[float]) -> list[float]:
    """
    由日频权益曲线（按交易日升序）计算日收益率序列。

    Args:
        equity_curve: 每个交易日的总权益值，等间距（每元素代表一个交易日）。

    Returns:
        日收益率列表，长度 = len(equity_curve) - 1。
    """
    if len(equity_curve) < 2:
        return []
    out: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev == 0:
            out.append(0.0)
            continue
        out.append((equity_curve[i] - prev) / prev)
    return out


def annualized_volatility(
    equity_curve: list[float], periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """年化波动率（%）= std(日收益) * sqrt(252) * 100。"""
    rets = daily_returns(equity_curve)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year) * 100.0


def sharpe_ratio(
    equity_curve: list[float],
    risk_free_rate: float = 0.025,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """
    年化夏普率。

    risk_free_rate 为年化无风险利率（如 2.5%），内部转日频。
    """
    rets = daily_returns(equity_curve)
    if len(rets) < 2:
        return 0.0
    rf_daily = risk_free_rate / periods_per_year
    excess = [r - rf_daily for r in rets]
    mean = sum(excess) / len(excess)
    var = sum((e - mean) ** 2 for e in excess) / (len(excess) - 1)
    # 浮点保护：确定性序列下 var 可能是 ~1e-37 的非零值（绕过 ==0），
    # 导致 mean/std 爆成天文数字。阈值兜底返回 0。
    if var < 1e-18:
        return 0.0
    std = math.sqrt(var)
    return (mean / std) * math.sqrt(periods_per_year)


def sortino_ratio(
    equity_curve: list[float],
    risk_free_rate: float = 0.025,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """
    年化索提诺率（仅对下行波动惩罚）。
    """
    rets = daily_returns(equity_curve)
    if len(rets) < 2:
        return 0.0
    rf_daily = risk_free_rate / periods_per_year
    excess = [r - rf_daily for r in rets]
    mean = sum(excess) / len(excess)
    downside = [e for e in excess if e < 0]
    if not downside:
        return 0.0
    downside_var = sum(e ** 2 for e in downside) / len(downside)
    if downside_var == 0:
        return 0.0
    dd_std = math.sqrt(downside_var)
    return (mean / dd_std) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list[float]) -> tuple[float, int]:
    """
    最大回撤。

    Returns:
        (max_dd_pct, max_dd_duration_days)
        max_dd_pct: 最大回撤幅度（正数，如 0.25 表示回撤 25%）
        max_dd_duration_days: 从回撤开始到回到前高的最长交易日数
    """
    if len(equity_curve) < 2:
        return 0.0, 0
    peak = equity_curve[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_duration = 0
    for i, v in enumerate(equity_curve):
        if v > peak:
            peak = v
            peak_idx = i
            continue
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
                max_dd_duration = i - peak_idx
    return max_dd * 100.0, max_dd_duration


def cagr(
    initial: float, final: float, days: int, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """
    年化复合收益率（%）。

    days: 实际交易日数；年数 = days / 252。
    """
    if initial <= 0 or days <= 0:
        return 0.0
    if final <= 0:
        return -100.0
    years = days / periods_per_year
    ratio = final / initial
    return ((ratio ** (1.0 / years)) - 1.0) * 100.0


def alpha_beta(
    strategy_returns: list[float],
    benchmark_returns: list[float],
    risk_free_rate: float = 0.025,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> tuple[float, float]:
    """
    CAPM 回归：strategy = alpha + beta * benchmark。

    Args:
        strategy_returns:  策略日频收益率序列
        benchmark_returns: 基准日频收益率序列（需等长）

    Returns:
        (annualized_alpha_pct, beta)
        alpha 已年化为百分比；beta 无量纲。
    """
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return 0.0, 0.0
    sr = strategy_returns[:n]
    br = benchmark_returns[:n]
    rf_daily = risk_free_rate / periods_per_year

    mean_s = sum(sr) / n
    mean_b = sum(br) / n
    cov = sum((sr[i] - mean_s) * (br[i] - mean_b) for i in range(n)) / (n - 1)
    var_b = sum((b - mean_b) ** 2 for b in br) / (n - 1)
    if var_b == 0:
        return 0.0, 0.0
    beta = cov / var_b
    # 日频 alpha，再年化
    alpha_daily = mean_s - (rf_daily + beta * (mean_b - rf_daily))
    alpha_annual = alpha_daily * periods_per_year * 100.0
    return alpha_annual, beta


def win_rate_from_trades(trade_returns: list[float]) -> float:
    """胜率（%）：正收益交易占比。"""
    if not trade_returns:
        return 0.0
    wins = sum(1 for r in trade_returns if r > 0)
    return wins / len(trade_returns) * 100.0
