"""
Risk Analysis Router
===================
Portfolio risk metrics: VaR, Monte Carlo, factor exposure,
sector concentration, and real-time risk alerts.

GET  /api/v1/risk/portfolio       — Full risk dashboard data
GET  /api/v1/risk/var             — Value at Risk calculation
GET  /api/v1/risk/exposure        — Sector/factor exposure
GET  /api/v1/risk/scenarios       — Stress test scenarios
POST /api/v1/risk/calculate       — Trigger full risk recalculation
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import math
import json
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.infra.database.sql_engine.dsn import get_dsn
from src.domain.market.portfolio.risk_metrics import (
    FACTOR_DRIVEN_SCENARIOS,
    HISTORICAL_CRISIS_SCENARIOS,
    calmar_ratio,
    correlation_matrix,
    evaluate_stress_scenario,
    monte_carlo_var,
    sortino_ratio,
)

router = APIRouter(prefix="/risk", tags=["risk"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_positions() -> list[dict]:
    conn = psycopg2.connect(get_dsn())
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM positions")
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _load_positions(
    portfolio_id: Optional[int],
) -> tuple[list[dict], Optional[str]]:
    """优先取 perm-portfolio 真实持仓(经 domain 层桥接)。

    无真实持仓时降级到原 positions 表; 两者皆空时返回 warning
    (调用方在响应 data 里标注演示数据), 保留原 demo/random 行为。
    """
    from src.api.handler.perm_portfolio_handler import (
        load_bridge_positions,
    )
    try:
        bridged = load_bridge_positions(portfolio_id)
    except Exception:
        bridged = []
    if bridged:
        return bridged, None
    positions = _get_positions()
    if positions:
        return positions, None
    return [], "无真实持仓,显示演示数据"


def _get_stock_returns(symbol: str, days: int = 252) -> list[float]:
    """Get daily log returns for a stock from OHLCV data."""
    conn = psycopg2.connect(get_dsn())
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT close_ FROM stock_ohlcv
            WHERE symbol = %s
            ORDER BY trade_date DESC
            LIMIT %s
        """, (symbol, days))
        prices = [float(r[0]) for r in cur.fetchall()]
        prices.reverse()  # oldest first
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = math.log(prices[i] / prices[i-1])
                returns.append(ret)
        return returns
    finally:
        conn.close()


def _fetch_returns_by_symbol(
    positions: list[dict], days: int = 60,
) -> dict[str, list[float]]:
    """按 symbol 去重拉取日收益序列(每 symbol 一次 DB 查询)。"""
    rets: dict[str, list[float]] = {}
    for p in positions:
        sym = p.get("symbol", "")
        if sym and sym not in rets:
            rets[sym] = _get_stock_returns(sym, days + 5)
    return rets


def _weighted_returns(
    positions: list[dict],
    rets_by_symbol: dict[str, list[float]],
    days: int = 60,
) -> list[float]:
    """按市值权重把各 symbol 日收益合成组合日收益(缺数据记 0)。"""
    total_value = sum(p.get("market_value", 0) for p in positions)
    if total_value == 0:
        return [0.0] * days
    all_returns = []
    for day in range(days):
        day_ret = 0.0
        for p in positions:
            sym = p.get("symbol", "")
            w = p.get("market_value", 0) / total_value
            rets = rets_by_symbol.get(sym, [])
            if day < len(rets):
                day_ret += w * rets[day]
            else:
                day_ret += w * 0.0
        all_returns.append(day_ret)
    return all_returns


def _get_portfolio_returns(positions: list[dict], days: int = 60) -> list[float]:
    """
    Reconstruct portfolio daily returns from position weights.
    Uses equal-weighted sector returns as proxy when individual stock
    data is not available.
    """
    if not positions:
        # Return simulated market returns for demo
        import random
        return [random.gauss(0.0005, 0.015) for _ in range(days)]
    return _weighted_returns(
        positions, _fetch_returns_by_symbol(positions, days), days
    )


def _get_debt_ratios(symbols: list[str]) -> dict[str, Optional[float]]:
    """有息负债率(symbol -> 有息负债/总资产), 供因子驱动压力场景。

    取 stock_financial_detail 最新一期资产负债表:
    (short_loan + long_loan) / total_assets; 借款缺失时退回
    debt_ratio(资产负债率)列。任何失败(无表/无行/无 DB)都返回
    空 dict, 场景退化为中性负债率(不阻断仪表盘)。
    """
    ratios: dict[str, Optional[float]] = {}
    unique = [s for s in dict.fromkeys(symbols) if s]
    if not unique:
        return ratios
    try:
        conn = psycopg2.connect(get_dsn())
    except Exception:
        return ratios
    try:
        cur = conn.cursor()
        for sym in unique:
            row = None
            try:
                cur.execute("""
                    SELECT short_loan, long_loan,
                           total_assets, debt_ratio
                    FROM stock_financial_detail
                    WHERE symbol = %s
                      AND statement_type = 'balance'
                    ORDER BY report_date DESC
                    LIMIT 1
                """, (sym,))
                row = cur.fetchone()
            except Exception:
                conn.rollback()  # 单标的失败不阻断其余查询
            if not row:
                ratios[sym] = None
                continue
            short_loan, long_loan, total_assets, debt_ratio = row
            loans = sum(
                v for v in (short_loan, long_loan) if v
            )
            if total_assets and total_assets > 0 and loans > 0:
                ratios[sym] = loans / total_assets
            elif debt_ratio is not None:
                ratios[sym] = float(debt_ratio)
            else:
                ratios[sym] = None
    except Exception:
        ratios = {}
    finally:
        conn.close()
    return ratios


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _var(returns: list[float], confidence: float = 0.95) -> float:
    """Historical VaR at given confidence level."""
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    index = int((1 - confidence) * len(sorted_returns))
    return -sorted_returns[index]  # positive number = loss


def _cvar(returns: list[float], confidence: float = 0.95) -> float:
    """Conditional VaR (Expected Shortfall)."""
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    index = int((1 - confidence) * len(sorted_returns))
    tail = sorted_returns[:index + 1]
    return -_mean(tail) if tail else 0.0


def _max_drawdown(values: list[float]) -> tuple[float, int, int]:
    """Return (max_dd_pct, peak_idx, trough_idx)."""
    if not values:
        return 0.0, -1, -1
    peak = values[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_end = 0
    for i, v in enumerate(values):
        if v >= peak:
            peak = v
            peak_idx = i
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_end = i
    return max_dd, peak_idx, max_dd_end


def _sharpe(returns: list[float], rf: float = 0.03) -> float:
    """Annualized Sharpe ratio (rf = risk-free rate)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - rf / 252 for r in returns]
    mean_excess = _mean(excess)
    std_excess = _stdev(excess)
    if std_excess == 0:
        return 0.0
    return (mean_excess / std_excess) * math.sqrt(252)


# ── Sector exposure ────────────────────────────────────────────────────────────

SECTOR_KEYWORDS = {
    "Banking & Finance": ["bank", "finance", "银", "平安", "招商", "工行", "建行", "农行", "中国银行"],
    "Technology": ["tech", "软件", "硬件", "电子", "通信", "科技", "阿里", "腾讯", "华为"],
    "Healthcare": ["health", "医", "药", "生物", "医院", "医疗"],
    "Energy": ["energy", "石", "油", "气", "电", "能源", "煤", "新能"],
    "Consumer": ["consumer", "消费", "零售", "食品", "饮料", "家电", "汽车"],
    "Industrial": ["industr", "制造", "机械", "工业", "基建", "建筑"],
}


def _classify_sector(symbol: str, name: str = "") -> str:
    sym_lower = (symbol + name).lower()
    for sector, keywords in SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in sym_lower:
                return sector
    return "Other"


# ── Scenario definitions ───────────────────────────────────────────────────────

SCENARIOS = {
    "market_crash": {
        "name": "Market Crash (-20%)",
        "description": "Historic 2020-style crash",
        "shock": -0.20,
        "probability": 0.03,
    },
    "rate_hike": {
        "name": "Interest Rate +50bp",
        "description": "Fed rate hike shock",
        "shock": -0.08,
        "probability": 0.10,
    },
    "sector_rotation": {
        "name": "Tech Sector Rotation",
        "description": "Rotation from growth to value",
        "shock": -0.12,
        "probability": 0.15,
    },
    "black_monday": {
        "name": "Black Monday 1987",
        "description": "-22% single day crash",
        "shock": -0.22,
        "probability": 0.01,
    },
}


def _all_stress_scenarios() -> list[dict]:
    """静态(原 4 个) + 因子驱动 + 历史危机重放的完整场景列表。

    静态场景保持原 SCENARIOS 定义与字段不变, 仅补
    id/category/debt_sensitivity 元信息供统一评估。
    """
    merged: list[dict] = []
    for sid, sc in SCENARIOS.items():
        merged.append({
            "id": sid,
            "category": "static",
            "debt_sensitivity": 0.0,
            **sc,
        })
    merged.extend(FACTOR_DRIVEN_SCENARIOS.values())
    merged.extend(HISTORICAL_CRISIS_SCENARIOS.values())
    return merged


def _round_scenario(sc: dict) -> dict:
    """场景输出统一取整(金额/百分比 2 位, 权重 4 位), 去浮点噪声。"""
    sc["loss"] = round(sc["loss"], 2)
    sc["loss_pct"] = round(sc["loss_pct"], 2)
    for c in sc["contributions"]:
        c["weight"] = round(c["weight"], 4)
        c["shock_pct"] = round(c["shock_pct"], 2)
        c["loss"] = round(c["loss"], 2)
    return sc


def _evaluate_all_scenarios(
    positions: list[dict],
    debt_ratios: Optional[dict[str, Optional[float]]] = None,
) -> list[dict]:
    """评估全部压力场景: 每场景组合预计损失 + 各仓位贡献。"""
    return [
        _round_scenario(
            evaluate_stress_scenario(sc, positions, debt_ratios)
        )
        for sc in _all_stress_scenarios()
    ]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/portfolio", response_model=dict)
def risk_portfolio(portfolio_id: Optional[int] = None):
    """
    Full risk dashboard: VaR, CVaR, Sharpe, Max Drawdown,
    sector exposure, scenario analysis, risk score.

    portfolio_id: 可选, 指定 perm-portfolio 组合;
    不传时用 is_active=True 的第一个组合。
    """
    positions, warning = _load_positions(portfolio_id)
    portfolio_value = sum(p.get("market_value", 0) for p in positions)

    if portfolio_value == 0:
        data = {
            "portfolio_value": 0,
            "var_95": 0, "cvar_95": 0,
            "sharpe_ratio": 0, "max_drawdown": 0,
            "sortino_ratio": 0, "calmar_ratio": 0,
            "avg_correlation": 0,
            "correlation_matrix": {
                "symbols": [], "matrix": [], "avg_correlation": 0.0,
            },
            "monte_carlo_var": 0,
            "risk_score": "LOW",
            "sector_exposure": [],
            "top_positions": [],
            "scenarios": [],
            "lever": 0,
            "message": "No positions — nothing to analyze"
        }
        if warning:
            data["warning"] = warning
        return {"code": 0, "msg": "ok", "data": data}

    rets_by_symbol = _fetch_returns_by_symbol(positions, days=60)
    returns = _weighted_returns(positions, rets_by_symbol, days=60)

    # Core metrics
    var_95 = _var(returns, 0.95) * portfolio_value
    cvar_95 = _cvar(returns, 0.95) * portfolio_value
    sharpe = _sharpe(returns)
    sortino = sortino_ratio(returns)
    calmar = calmar_ratio(returns)
    mc_var = monte_carlo_var(
        returns, confidence=0.95, n_sim=10000, seed=42
    )
    corr = correlation_matrix(rets_by_symbol)
    
    equity_values = []
    cur_val = portfolio_value
    for r in returns:
        cur_val *= (1 + r)
        equity_values.append(cur_val)
    
    max_dd, _, _ = _max_drawdown(equity_values)
    max_dd_pct = max_dd * 100

    # Sector exposure
    sector_exposure = {}
    for p in positions:
        sector = _classify_sector(p.get("symbol", ""), p.get("name", ""))
        sector_exposure.setdefault(sector, 0)
        sector_exposure[sector] += p.get("market_value", 0)
    
    sector_list = [
        {"sector": s, "value": v, "weight": v / portfolio_value}
        for s, v in sector_exposure.items()
    ]
    sector_list.sort(key=lambda x: x["value"], reverse=True)

    # Top positions
    top_positions = sorted(positions, key=lambda p: p.get("market_value", 0), reverse=True)[:5]

    # Scenario analysis (静态 + 因子驱动 + 历史危机重放)
    debt_ratios = _get_debt_ratios(
        [p.get("symbol", "") for p in positions]
    )
    scenarios = _evaluate_all_scenarios(positions, debt_ratios)
    for sc in scenarios:
        sc["expected_annual_loss"] = (
            abs(sc["loss"]) * sc["probability"] * 4  # ~quarterly
        )

    # Risk score (0-100, higher = riskier)
    risk_score_num = 0
    risk_score_num += min(var_95 / portfolio_value * 500, 40)  # VaR component
    risk_score_num += min(max_dd_pct * 2, 30)  # Drawdown component
    risk_score_num += (1 - sharpe / 3) * 15 if sharpe > 0 else 15  # Sharpe component
    risk_score_num += min(len(positions) < 3 and portfolio_value > 0, 15)  # Concentration
    
    risk_score = "LOW"
    if risk_score_num > 60:
        risk_score = "HIGH"
    elif risk_score_num > 30:
        risk_score = "MEDIUM"

    return {
        "code": 0, "msg": "ok", "data": {
            "portfolio_value": portfolio_value,
            "var_95": round(var_95, 2),
            "var_95_pct": round(var_95 / portfolio_value * 100, 2),
            "cvar_95": round(cvar_95, 2),
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "calmar_ratio": round(calmar, 3),
            "avg_correlation": round(corr["avg_correlation"], 3),
            "correlation_matrix": {
                "symbols": corr["symbols"],
                "matrix": [
                    [round(v, 3) for v in row]
                    for row in corr["matrix"]
                ],
                "avg_correlation": round(
                    corr["avg_correlation"], 3
                ),
            },
            "monte_carlo_var": round(mc_var * portfolio_value, 2),
            "monte_carlo_var_pct": round(mc_var * 100, 2),
            "max_drawdown": round(max_dd_pct, 2),
            "risk_score": risk_score,
            "sector_exposure": sector_list,
            "top_positions": [
                {
                    "symbol": p.get("symbol"),
                    "name": p.get("name", ""),
                    "weight": p.get("market_value", 0) / portfolio_value,
                    "value": p.get("market_value", 0),
                    "daily_return": p.get("daily_return_pct", 0),
                }
                for p in top_positions
            ],
            "scenarios": scenarios,
            "position_count": len(positions),
            "returns_volatility": round(
                _stdev(returns) * math.sqrt(252) * 100, 2
            ),
            "message": None,
            **({"warning": warning} if warning else {}),
        }
    }


@router.get("/var", response_model=dict)
def risk_var(
    confidence: float = 0.95, days: int = 1,
    portfolio_id: Optional[int] = None,
):
    """
    Compute Value at Risk for the current portfolio.
    GET /api/v1/risk/var?confidence=0.99&days=5

    portfolio_id: 可选, 指定 perm-portfolio 组合。
    """
    positions, warning = _load_positions(portfolio_id)
    portfolio_value = sum(p.get("market_value", 0) for p in positions)

    if portfolio_value == 0:
        data = {
            "var": 0, "cvar": 0,
            "confidence": confidence, "days": days,
        }
        if warning:
            data["warning"] = warning
        return {"code": 0, "msg": "ok", "data": data}

    returns = _get_portfolio_returns(positions, days=120)
    var = _var(returns, confidence) * portfolio_value * math.sqrt(days / 1)
    cvar = _cvar(returns, confidence) * portfolio_value * math.sqrt(days / 1)

    return {
        "code": 0, "msg": "ok", "data": {
            "var": round(var, 2),
            "cvar": round(cvar, 2),
            "var_pct": round(var / portfolio_value * 100, 2),
            "confidence": confidence,
            "days": days,
            "portfolio_value": portfolio_value,
            **({"warning": warning} if warning else {}),
        }
    }


@router.get("/exposure", response_model=dict)
def risk_exposure(portfolio_id: Optional[int] = None):
    """Sector and factor exposure breakdown."""
    positions, warning = _load_positions(portfolio_id)
    portfolio_value = sum(p.get("market_value", 0) for p in positions)

    if portfolio_value == 0:
        data = {"sectors": [], "factors": [], "total_value": 0}
        if warning:
            data["warning"] = warning
        return {"code": 0, "msg": "ok", "data": data}

    # Sector breakdown
    sector_vals = {}
    for p in positions:
        sector = _classify_sector(p.get("symbol", ""), p.get("name", ""))
        sector_vals.setdefault(sector, 0)
        sector_vals[sector] += p.get("market_value", 0)

    sectors = [
        {"sector": s, "value": round(v, 2), "weight": round(v / portfolio_value * 100, 2)}
        for s, v in sector_vals.items()
    ]
    sectors.sort(key=lambda x: x["value"], reverse=True)

    # Simple factor exposure (approximation using sector mapping)
    FACTOR_BETA = {
        "Banking & Finance": 1.1,
        "Technology": 1.3,
        "Healthcare": 0.8,
        "Energy": 1.0,
        "Consumer": 0.9,
        "Industrial": 1.05,
        "Other": 1.0,
    }
    weighted_beta = sum(
        (v / portfolio_value) * FACTOR_BETA.get(s, 1.0)
        for s, v in sector_vals.items()
    )

    factors = [
        {"factor": "Market Beta", "value": round(weighted_beta, 3), "description": "Sensitivity to market moves"},
        {"factor": "Sector Concentration", "value": round(max(v / portfolio_value for v in sector_vals.values()) * 100, 1), "description": "Largest single sector weight %"},
        {"factor": "Diversification Score", "value": len(sector_vals), "description": "Number of sectors held"},
    ]

    return {
        "code": 0, "msg": "ok", "data": {
            "sectors": sectors,
            "factors": factors,
            "total_value": portfolio_value,
            **({"warning": warning} if warning else {}),
        }
    }


@router.get("/scenarios", response_model=dict)
def risk_scenarios(portfolio_id: Optional[int] = None):
    """Stress test scenario analysis.

    静态(原 4 个全场统一跌幅) + 因子驱动(按有息负债率差异化
    冲击) + 历史危机重放(上证综指历史区间跌幅); 每场景返回
    组合预计损失与各仓位贡献分解。
    """
    positions, warning = _load_positions(portfolio_id)
    portfolio_value = sum(p.get("market_value", 0) for p in positions)

    debt_ratios = _get_debt_ratios(
        [p.get("symbol", "") for p in positions]
    )
    scenarios = _evaluate_all_scenarios(positions, debt_ratios)

    return {
        "code": 0, "msg": "ok", "data": {
            "scenarios": scenarios,
            "portfolio_value": portfolio_value,
            **({"warning": warning} if warning else {}),
        }
    }
