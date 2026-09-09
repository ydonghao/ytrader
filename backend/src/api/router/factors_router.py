"""
Factor Analysis Router
====================
Fama-French Three-Factor Model + Momentum factor for Chinese A-Stocks.
Decomposes portfolio/stock returns into systematic risk factors.

GET  /api/v1/factors/portfolio          — Portfolio factor exposure
GET  /api/v1/factors/stock/{symbol}     — Individual stock factor betas
GET  /api/v1/factors/market            — Market factor (MKT) time series
GET  /api/v1/factors/calendar           — Calendar effect analysis (monthly/weekly)
"""

from fastapi import APIRouter
import math

import psycopg2
import psycopg2.extras

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.infra.database.sql_engine.dsn import get_dsn

router = APIRouter(prefix="/factors", tags=["factors"])

# ── Math helpers (from original) ─────────────────────────────────────────────

def _mean(vals):
    return sum(vals) / len(vals) if vals else 0.0

def _stdev(vals):
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))

def _corr(xs, ys):
    if len(xs) < 2 or len(ys) < 2:
        return 0.0
    n = len(xs)
    mx, my = _mean(xs), _mean(ys)
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den > 0 else 0.0

def _cov(xs, ys):
    if len(xs) < 2:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs))) / (len(xs) - 1)

def _regress(y_vals, x_vals):
    """Simple OLS: y = alpha + beta * x + epsilon"""
    if len(y_vals) < 3 or len(x_vals) < 3 or len(y_vals) != len(x_vals):
        return {"alpha": 0, "beta": 0, "r_squared": 0}
    x_mean = _mean(x_vals)
    y_mean = _mean(y_vals)
    num = sum((x_vals[i] - x_mean) * (y_vals[i] - y_mean) for i in range(len(x_vals)))
    den = sum((x_vals[i] - x_mean) ** 2 for i in range(len(x_vals)))
    beta = num / den if den != 0 else 0.0
    alpha = y_mean - beta * x_mean
    y_pred = [alpha + beta * x for x in x_vals]
    ss_res = sum((y_vals[i] - y_pred[i]) ** 2 for i in range(len(y_vals)))
    ss_tot = sum((y_vals[i] - y_mean) ** 2 for i in range(len(y_vals)))
    r_sq = 1 - ss_res / ss_tot if ss_tot != 0 else 0
    return {"alpha": alpha, "beta": beta, "r_squared": r_sq}

def _regress_multi(y_vals, x_matrix):
    n = len(y_vals)
    k = len(x_matrix[0]) if x_matrix else 0
    if n < k + 2 or n < 3:
        return {"betas": [0.0] * k, "r_squared": 0, "residuals": y_vals}
    X = [[1.0] + row for row in x_matrix]
    n_vars = k + 1
    XtX = [[sum(X[i][j] * X[i][m] for i in range(n)) for m in range(n_vars)] for j in range(n_vars)]
    Xty = [sum(X[i][j] * y_vals[i] for i in range(n)) for j in range(n_vars)]
    aug = [XtX[i] + [Xty[i]] for i in range(n_vars)]
    for i in range(n_vars):
        pivot = aug[i][i]
        if abs(pivot) < 1e-12:
            for j in range(i + 1, n_vars):
                if abs(aug[j][i]) > 1e-12:
                    aug[i], aug[j] = aug[j], aug[i]
                    pivot = aug[i][i]
                    break
        if abs(pivot) < 1e-12:
            continue
        for j in range(i + 1, n_vars):
            factor = aug[j][i] / pivot
            for m in range(i, n_vars + 1):
                aug[j][m] -= factor * aug[i][m]
    betas = [0.0] * n_vars
    for i in range(n_vars - 1, -1, -1):
        if abs(aug[i][i]) < 1e-12:
            betas[i] = 0.0
            continue
        betas[i] = (aug[i][n_vars] - sum(aug[i][j] * betas[j] for j in range(i + 1, n_vars))) / aug[i][i]
    residuals = [y_vals[i] - sum(betas[j] * X[i][j] for j in range(n_vars)) for i in range(n)]
    y_mean = _mean(y_vals)
    ss_res = sum(r ** 2 for r in residuals)
    ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
    r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return {"betas": betas, "r_squared": max(0, r_sq), "residuals": residuals}


# ── Data fetchers (from original) ───────────────────────────────────────────

def _get_stock_monthly_returns(symbol: str, months: int = 36) -> list[dict]:
    conn = psycopg2.connect(get_dsn())
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH monthly AS (
                SELECT
                    DATE_TRUNC('month', trade_date)::date AS month,
                    FIRST_VALUE(close_) OVER (PARTITION BY DATE_TRUNC('month', trade_date) ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS open_price,
                    LAST_VALUE(close_) OVER (PARTITION BY DATE_TRUNC('month', trade_date) ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS close_price
                FROM stock_ohlcv
                WHERE symbol = %s
                ORDER BY month DESC
                LIMIT %s
            )
            SELECT month, open_price, close_price,
                   CASE WHEN open_price > 0 THEN (close_price - open_price) / open_price ELSE 0 END AS ret
            FROM monthly
            ORDER BY month ASC
        """, (symbol, months))
        rows = cur.fetchall()
        return [{"month": str(r[0]), "return": r[3]} for r in rows]
    finally:
        conn.close()


def _get_market_monthly_returns(months: int = 36) -> list[dict]:
    conn = psycopg2.connect(get_dsn())
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH monthly AS (
                SELECT
                    DATE_TRUNC('month', trade_date)::date AS month,
                    AVG(close_) AS avg_close
                FROM stock_ohlcv
                WHERE symbol = 'sh600000'
                GROUP BY month
                ORDER BY month ASC
            )
            SELECT month,
                   CASE WHEN LAG(avg_close) OVER (ORDER BY month) > 0
                        THEN (avg_close - LAG(avg_close) OVER (ORDER BY month))
                             / LAG(avg_close) OVER (ORDER BY month)
                        ELSE 0 END AS ret
            FROM monthly
            ORDER BY month ASC
            LIMIT %s
        """, (months,))
        rows = cur.fetchall()
        result = [{"month": str(r[0]), "return": r[1] if r[1] is not None else 0} for r in rows]
        return result
    finally:
        conn.close()


def _get_positions() -> list[dict]:
    conn = psycopg2.connect(get_dsn())
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM positions")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _get_stock_info(symbol: str) -> dict | None:
    conn = psycopg2.connect(get_dsn())
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM stock_info WHERE symbol = %s LIMIT 1", (symbol,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Factor model (from original) ────────────────────────────────────────────

def _build_fama_french_factors(monthly_returns: list[float], market_returns: list[float]) -> tuple:
    n = min(len(monthly_returns), len(market_returns))
    if n < 6:
        return None
    stock_rets = monthly_returns[-n:]
    mkt_rets = market_returns[-n:]
    rf = 0.02 / 12
    mkt_excess = [mkt_rets[i] - rf for i in range(n)]
    if n > 13:
        mom_12 = [stock_rets[i - 12] if i >= 12 else 0 for i in range(n)]
    else:
        mom_12 = [0.0] * n
    capm = _regress(stock_rets, mkt_excess)
    x_matrix = [[mkt_excess[i], mom_12[i]] for i in range(n)]
    ff2 = _regress_multi(stock_rets, x_matrix)
    return {
        "n_observations": n,
        "capm": {
            "alpha_monthly": capm["alpha"],
            "beta_mkt": capm["beta"],
            "r_squared": capm["r_squared"],
            "annualized_alpha": capm["alpha"] * 12,
            "interpretation": f"Beta={capm['beta']:.3f}: 市场每涨跌1%，该股平均涨跌{capm['beta']*1:.3f}%"
        },
        "two_factor": {
            "alpha": ff2["betas"][0],
            "beta_mkt": ff2["betas"][1],
            "beta_mom": ff2["betas"][2],
            "r_squared": ff2["r_squared"],
        },
        "factors": {
            "market_excess": [round(v, 5) for v in mkt_excess],
            "momentum_12": [round(v, 5) for v in mom_12],
        }
    }


# ── Calendar effects (from original) ─────────────────────────────────────────

def _analyze_calendar_effects(monthly_returns: list[dict]) -> dict:
    if len(monthly_returns) < 12:
        return {"monthly": [], "note": "数据不足"}
    month_returns: dict[int, list[float]] = {}
    for item in monthly_returns:
        month_num = int(item["month"].split("-")[1])
        month_returns.setdefault(month_num, []).append(item["return"])
    monthly_analysis = []
    for m in range(1, 13):
        rets = month_returns.get(m, [])
        if rets:
            monthly_analysis.append({
                "month": m,
                "month_name": ["一月", "二月", "三月", "四月", "五月", "六月",
                               "七月", "八月", "九月", "十月", "十一月", "十二月"][m - 1],
                "avg_return": round(_mean(rets) * 100, 3),
                "count": len(rets),
                "positive_pct": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
            })
    all_rets = [r["return"] for r in monthly_returns]
    best_month = max(monthly_analysis, key=lambda x: x["avg_return"])
    worst_month = min(monthly_analysis, key=lambda x: x["avg_return"])
    jan_rets = month_returns.get(1, [])
    other_rets = [r for m, rs in month_returns.items() if m != 1 for r in rs]
    jan_effect = _mean(jan_rets) - _mean(other_rets) if jan_rets and other_rets else 0
    return {
        "monthly": monthly_analysis,
        "best_month": {"name": best_month["month_name"], "return": best_month["avg_return"]},
        "worst_month": {"name": worst_month["month_name"], "return": worst_month["avg_return"]},
        "jan_effect": round(jan_effect * 100, 3),
        "jan_effect_pct": round(jan_effect / (_mean(other_rets) + 1e-9) * 100, 2) if other_rets else 0,
        "total_months": len(monthly_returns),
        "avg_monthly_return": round(_mean(all_rets) * 100, 3),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/portfolio", response_model=dict)
def factor_portfolio():
    """
    Factor exposure for the current portfolio.
    For each position, compute CAPM beta and factor loadings.
    Aggregate to portfolio-level factor exposure.
    """
    positions = _get_positions()
    portfolio_value = sum(p.get("market_value", 0) for p in positions)
    if not positions:
        return {"code": 0, "msg": "ok", "data": {"positions": [], "portfolio_beta": 0, "message": "No positions"}}
    market_rets = _get_market_monthly_returns(months=36)
    position_factors = []
    for p in positions:
        sym = p.get("symbol", "")
        stock_monthly = _get_stock_monthly_returns(sym, months=36)
        if len(stock_monthly) < 6:
            continue
        mkt = _get_market_monthly_returns(months=len(stock_monthly))
        result = _build_fama_french_factors(
            [r["return"] for r in stock_monthly],
            [r["return"] for r in mkt],
        )
        if result:
            capm = result["capm"]
            weight = p.get("market_value", 0) / portfolio_value
            position_factors.append({
                "symbol": sym,
                "name": p.get("name", ""),
                "weight": round(weight * 100, 2),
                "beta_mkt": round(capm["beta_mkt"], 3),
                "r_squared": round(capm["r_squared"], 3),
                "annualized_alpha": round(capm["annualized_alpha"] * 100, 3),
                "interpretation": capm["interpretation"],
            })
    portfolio_beta = sum(pf["weight"] / 100 * pf["beta_mkt"] for pf in position_factors)
    return {
        "code": 0, "msg": "ok", "data": {
            "portfolio_beta": round(portfolio_beta, 3),
            "positions": position_factors,
            "factor_count": len(position_factors),
            "note": "Beta > 1 表示系统性风险高于大盘；Alpha > 0 表示跑赢大盘"
        }
    }


@router.get("/stock/{symbol}", response_model=dict)
def factor_stock(symbol: str):
    stock_info = _get_stock_info(symbol)
    stock_monthly = _get_stock_monthly_returns(symbol, months=36)
    mkt_monthly = _get_market_monthly_returns(months=36)
    if len(stock_monthly) < 6:
        return {
            "code": 0, "msg": "ok", "data": {
                "symbol": symbol,
                "note": f"数据不足（仅{len(stock_monthly)}个月），需要至少6个月数据",
                "calendar": None,
            }
        }
    stock_rets = [r["return"] for r in stock_monthly]
    mkt_rets = [r["return"] for r in mkt_monthly]
    ff_result = _build_fama_french_factors(stock_rets, mkt_rets)
    calendar = _analyze_calendar_effects(stock_monthly)
    total_ret = (1 + stock_rets[-1] if stock_rets else 0) - 1
    vol_monthly = _stdev(stock_rets)
    sharpe_monthly = (_mean(stock_rets) - 0.02/12) / vol_monthly if vol_monthly > 0 else 0
    return {
        "code": 0, "msg": "ok", "data": {
            "symbol": symbol,
            "name": stock_info.get("name", "") if stock_info else "",
            "data_months": len(stock_monthly),
            "summary": {
                "total_return": round(total_ret * 100, 2),
                "avg_monthly_return": round(_mean(stock_rets) * 100, 3),
                "monthly_volatility": round(vol_monthly * 100, 3),
                "annualized_volatility": round(vol_monthly * math.sqrt(12) * 100, 2),
                "sharpe_monthly": round(sharpe_monthly, 3),
            },
            "capm": ff_result["capm"] if ff_result else None,
            "two_factor": ff_result["two_factor"] if ff_result else None,
            "calendar": calendar,
            "monthly_returns": stock_monthly[-24:],
        }
    }


@router.get("/calendar", response_model=dict)
def factor_calendar(symbol: str = "sh000300"):
    stock_monthly = _get_stock_monthly_returns(symbol, months=60)
    if len(stock_monthly) < 12:
        return {"code": 0, "msg": "ok", "data": {"monthly": [], "note": "数据不足"}}
    calendar = _analyze_calendar_effects(stock_monthly)
    return {"code": 0, "msg": "ok", "data": calendar}


@router.get("/market", response_model=dict)
def factor_market():
    mkt_monthly = _get_market_monthly_returns(months=36)
    rf = 0.02 / 12
    mkt_excess = [{"month": r["month"], "mkt_excess": round((r["return"] - rf) * 100, 3)}
                  for r in mkt_monthly]
    return {"code": 0, "msg": "ok", "data": mkt_excess}
