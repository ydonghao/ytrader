"""组合下行风险指标与情景压力测试(纯函数)。

==========================================================

补充风险仪表盘缺口(不依赖 DB/网络, 全部可单测):

  - sortino_ratio        年化 Sortino(下行偏差, 只惩罚下行波动)
  - calmar_ratio         CAGR / 最大回撤
  - correlation_matrix   持仓间 NxN 相关矩阵 + 平均相关度(集中度)
  - monte_carlo_var      参数化 Monte Carlo VaR(历史均值/方差)

情景压力测试(因子驱动 + 历史危机重放):

  - debt_shock_multiplier      按有息负债率差异化的冲击乘数
  - scenario_position_shocks    每仓位的具体冲击幅度
  - evaluate_stress_scenario    组合预计损失 + 各仓位贡献分解
  - FACTOR_DRIVEN_SCENARIOS     因子驱动场景(利率上行/信用紧缩)
  - HISTORICAL_CRISIS_SCENARIOS 历史危机重放(2008/2015/2018/2022)

口径说明:
  - Sortino 与 strategy/longterm/metrics.py 保持一致:
    下行偏差只对下行样本求均(分母 = 下行样本数, 非全样本数)。
  - VaR 返回正数 = 损失比例(与 risk_router._var 同号约定,
    分位收益为正时可能返回负数, 表示该置信度下无损失)。
  - 场景损失沿用 router 原口径: loss 为负数 = 亏损金额。
"""
from __future__ import annotations

import math
import random
from typing import Optional

TRADING_DAYS_PER_YEAR = 252

DEFAULT_RISK_FREE_RATE = 0.03
# 无负债率数据时的中性假设(有息负债/总资产 的市场常见水平)
DEFAULT_NEUTRAL_DEBT_RATIO = 0.4
# 差异化乘数上限, 防止异常负债率把冲击放大到离谱
MAX_SHOCK_MULTIPLIER = 3.0


# ── 基础统计 ────────────────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    """样本标准差(ddof=1); 少于 2 个样本返回 0。"""
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    var = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(var)


# ── 下行风险指标 ────────────────────────────────────────────────────

def sortino_ratio(
    returns: list[float],
    rf: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """年化 Sortino 比率(下行偏差版夏普)。

    Args:
        returns: 日频收益率序列。
        rf: 年化无风险利率, 内部转日频(MAR = rf/252)。
        periods_per_year: 年化周期数。

    下行偏差 = sqrt(sum(min(e,0)^2) / 下行样本数), 与
    strategy/longterm/metrics.py 的 sortino_ratio 同口径。
    无下行样本 / 下行偏差为 0 时返回 0。
    """
    if len(returns) < 2:
        return 0.0
    rf_daily = rf / periods_per_year
    excess = [r - rf_daily for r in returns]
    mean_excess = _mean(excess)
    downside = [e for e in excess if e < 0]
    if not downside:
        return 0.0
    downside_var = sum(e ** 2 for e in downside) / len(downside)
    if downside_var <= 0:
        return 0.0
    dd_std = math.sqrt(downside_var)
    return (mean_excess / dd_std) * math.sqrt(periods_per_year)


def calmar_ratio(
    returns: list[float],
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Calmar 比率 = CAGR / 最大回撤。

    由日频收益率复合出权益曲线(初始 1.0)再计算:
      - CAGR = (prod(1+r))^(252/n) - 1
      - MaxDD = max((peak - trough) / peak)
    无回撤(或输入退化)时返回 0.0, 避免除零/无穷。
    """
    if not returns:
        return 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= (1.0 + r)
        if equity > peak:
            peak = equity
            continue
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
    if max_dd <= 0:
        return 0.0
    years = len(returns) / periods_per_year
    if years <= 0 or equity <= 0:
        # 权益归零: CAGR = -100%, 仍可给出比率
        cagr = -1.0 if equity <= 0 else 0.0
    else:
        cagr = (equity ** (1.0 / years)) - 1.0
    return cagr / max_dd


def correlation_matrix(
    returns_by_symbol: dict[str, list[float]],
) -> dict:
    """持仓间相关矩阵 + 平均相关度(集中度指标)。

    Args:
        returns_by_symbol: symbol -> 日收益序列(长度可不一致,
            不足 2 个观测的 symbol 被忽略; 其余按全局最短长度截齐)。

    Returns:
        {"symbols": [...], "matrix": [[...]], "avg_correlation": f}
        - 对角线恒为 1.0; 零方差序列与其它的相关度记 0.0;
        - avg_correlation = 上三角非对角元素均值, 少于 2 个
          有效 symbol 时为 0.0(无配对可平均)。
    """
    kept = [
        (sym, rets)
        for sym, rets in returns_by_symbol.items()
        if len(rets) >= 2
    ]
    symbols = [sym for sym, _ in kept]
    n = len(symbols)
    if n == 0:
        return {"symbols": [], "matrix": [], "avg_correlation": 0.0}

    m = min(len(rets) for _, rets in kept)
    if m < 2:
        matrix = [
            [1.0 if i == j else 0.0 for j in range(n)]
            for i in range(n)
        ]
        return {
            "symbols": symbols,
            "matrix": matrix,
            "avg_correlation": 0.0,
        }

    series = {sym: rets[:m] for sym, rets in kept}
    stds = {sym: _stdev(series[sym]) for sym in symbols}
    matrix = [[1.0] * n for _ in range(n)]
    pair_corrs: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            si, sj = symbols[i], symbols[j]
            corr = 0.0
            if stds[si] > 0 and stds[sj] > 0:
                mi = _mean(series[si])
                mj = _mean(series[sj])
                cov = sum(
                    (series[si][k] - mi) * (series[sj][k] - mj)
                    for k in range(m)
                ) / (m - 1)
                corr = cov / (stds[si] * stds[sj])
                corr = max(-1.0, min(1.0, corr))
            matrix[i][j] = corr
            matrix[j][i] = corr
            pair_corrs.append(corr)
    avg = _mean(pair_corrs) if pair_corrs else 0.0
    return {
        "symbols": symbols,
        "matrix": matrix,
        "avg_correlation": avg,
    }


def monte_carlo_var(
    returns: list[float],
    confidence: float = 0.95,
    n_sim: int = 10000,
    seed: Optional[int] = None,
) -> float:
    """参数化 Monte Carlo VaR(日频, 收益比例口径)。

    用历史收益的均值/样本方差参数化正态分布, 抽 n_sim 次,
    取 (1-confidence) 分位: VaR = -quantile。正数 = 损失比例,
    与 risk_router._var 同号约定。seed 固定时结果可复现。
    """
    if not returns or n_sim <= 0:
        return 0.0
    mu = _mean(returns)
    sigma = _stdev(returns)
    rng = random.Random(seed)
    sims = [rng.gauss(mu, sigma) for _ in range(int(n_sim))]
    sims.sort()
    index = int((1.0 - confidence) * len(sims))
    index = max(0, min(index, len(sims) - 1))
    return -sims[index]


# ── 因子驱动情景压力测试 ────────────────────────────────────────────

def debt_shock_multiplier(
    debt_ratio: Optional[float],
    sensitivity: float,
    neutral: float = DEFAULT_NEUTRAL_DEBT_RATIO,
) -> float:
    """按有息负债率差异化的冲击乘数。

    multiplier = 1 + sensitivity * (debt_ratio - neutral) / neutral,
    截断到 [0, MAX_SHOCK_MULTIPLIER]。负债率越高(相对中性水平),
    负冲击(base<0)被放大得越多; 无数据 / sensitivity=0 / 中性值
    非正时返回 1.0(即退化为全场统一冲击)。
    """
    if debt_ratio is None or sensitivity == 0 or neutral <= 0:
        return 1.0
    multiplier = 1.0 + sensitivity * (
        (float(debt_ratio) - neutral) / neutral
    )
    return max(0.0, min(MAX_SHOCK_MULTIPLIER, multiplier))


def scenario_position_shocks(
    symbols: list[str],
    debt_ratios: dict[str, Optional[float]],
    base_shock: float,
    debt_sensitivity: float = 0.0,
    neutral: float = DEFAULT_NEUTRAL_DEBT_RATIO,
) -> dict[str, float]:
    """计算每个 symbol 的差异化冲击幅度(负数 = 跌幅)。"""
    shocks: dict[str, float] = {}
    for sym in symbols:
        multiplier = debt_shock_multiplier(
            debt_ratios.get(sym), debt_sensitivity, neutral
        )
        shocks[sym] = float(base_shock) * multiplier
    return shocks


def evaluate_stress_scenario(
    scenario: dict,
    positions: list[dict],
    debt_ratios: Optional[dict[str, Optional[float]]] = None,
) -> dict:
    """评估单个压力场景: 组合预计损失 + 各仓位贡献分解。

    Args:
        scenario: 含 id/name/description/category/shock(基准跌幅,
            负数)/probability, 因子场景可含 debt_sensitivity,
            历史场景可含 source(跌幅参数出处)。
        positions: [{symbol, name, market_value}, ...],
            market_value<=0 的仓位被忽略。
        debt_ratios: symbol -> 有息负债率(有息负债/总资产),
            缺失的 symbol 用中性负债率(冲击 = 基准)。

    Returns:
        {..., "loss": 组合损失金额(负数, 沿用 router 原口径),
         "loss_pct": 组合加权跌幅%, "contributions": 各仓位贡献,
         按亏损从大到小排序}。
    """
    if debt_ratios is None:
        debt_ratios = {}
    base = float(scenario.get("shock", 0.0) or 0.0)
    sensitivity = float(scenario.get("debt_sensitivity", 0.0) or 0.0)

    valid = [
        p for p in positions
        if p.get("market_value", 0) and p.get("market_value", 0) > 0
    ]
    total_value = sum(p["market_value"] for p in valid)
    result = {
        "id": scenario.get("id", ""),
        "name": scenario.get("name", ""),
        "description": scenario.get("description", ""),
        "category": scenario.get("category", "static"),
        "probability": float(scenario.get("probability", 0.0) or 0.0),
        "source": scenario.get("source"),
        "loss": 0.0,
        "loss_pct": 0.0,
        "contributions": [],
    }
    if total_value <= 0:
        return result

    symbols = [p.get("symbol", "") for p in valid]
    shocks = scenario_position_shocks(
        symbols, debt_ratios, base, sensitivity
    )

    contributions = []
    loss = 0.0
    weighted_shock = 0.0
    for p in valid:
        sym = p.get("symbol", "")
        weight = p["market_value"] / total_value
        shock = shocks.get(sym, base)
        pos_loss = p["market_value"] * shock
        loss += pos_loss
        weighted_shock += weight * shock
        contributions.append({
            "symbol": sym,
            "name": p.get("name", ""),
            "weight": weight,
            "shock_pct": shock * 100.0,
            "loss": pos_loss,
        })
    contributions.sort(key=lambda c: c["loss"])
    result["loss"] = loss
    result["loss_pct"] = weighted_shock * 100.0
    result["contributions"] = contributions
    return result


# ── 场景定义(领域常量) ──────────────────────────────────────────────
# 静态 4 场景保留在 risk_router.SCENARIOS(全场统一跌幅, 不动)。

FACTOR_DRIVEN_SCENARIOS: dict[str, dict] = {
    "rate_hike_leverage": {
        "id": "rate_hike_leverage",
        "name": "Interest Rate Hike (Debt-Sensitive)",
        "category": "factor",
        "description": (
            "利率+50bp: 按有息负债率差异化冲击, "
            "高负债仓位跌幅放大、低负债更抗跌"
        ),
        "shock": -0.08,
        "probability": 0.10,
        "debt_sensitivity": 1.0,
    },
    "credit_crunch": {
        "id": "credit_crunch",
        "name": "Credit Crunch (High-Leverage Hit)",
        "category": "factor",
        "description": (
            "信用利差走阔: 高有息负债仓位融资成本骤升, "
            "跌幅显著大于低负债仓位"
        ),
        "shock": -0.12,
        "probability": 0.05,
        "debt_sensitivity": 1.5,
    },
}

# 历史危机重放: 以上证综指公开历史行情的区间跌幅为冲击基准
# (统一全场冲击, source 字段标注参数出处)。
HISTORICAL_CRISIS_SCENARIOS: dict[str, dict] = {
    "crisis_2008": {
        "id": "crisis_2008",
        "name": "2008 Global Financial Crisis (SSE -65.4%)",
        "category": "historical",
        "description": "重放 2008 全球金融危机: 上证综指全年暴跌",
        "shock": -0.6539,
        "probability": 0.01,
        "debt_sensitivity": 0.0,
        "source": "上证综指 2007-12-28 收盘 5261.56 → 2008-12-31 收盘 1820.81",
    },
    "crash_2015": {
        "id": "crash_2015",
        "name": "2015 China Crash (SSE -43.3%)",
        "category": "historical",
        "description": "重放 2015 A股股灾: 去杠杆引发的流动性危机",
        "shock": -0.4334,
        "probability": 0.02,
        "debt_sensitivity": 0.0,
        "source": "上证综指 2015-06-12 收盘 5166.35 → 2015-08-26 收盘 2927.29",
    },
    "bear_2018": {
        "id": "bear_2018",
        "name": "2018 Bear Market (SSE -24.6%)",
        "category": "historical",
        "description": "重放 2018 去杠杆熊市: 贸易摩擦叠加信用收缩",
        "shock": -0.2459,
        "probability": 0.08,
        "debt_sensitivity": 0.0,
        "source": "上证综指 2017-12-29 收盘 3307.17 → 2018-12-28 收盘 2493.90",
    },
    "bear_2022": {
        "id": "bear_2022",
        "name": "2022 Bear Market (SSE -15.1%)",
        "category": "historical",
        "description": "重放 2022 熊市: 疫情反复与美联储加息共振",
        "shock": -0.1513,
        "probability": 0.15,
        "debt_sensitivity": 0.0,
        "source": "上证综指 2021-12-31 收盘 3639.78 → 2022-12-30 收盘 3089.26",
    },
}
