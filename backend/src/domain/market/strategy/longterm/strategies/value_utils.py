"""
价值策略公共工具
================
点-in-time 查询 + 横截面排名，三个价值策略（magic_formula/fscore_value/dividend）共用。

关键：点-in-time 处理 —— 决策日只能用"已公开披露"的数据：
  - 估值（PE/PB/股息率）：用 trade_date <= 决策日 的最新值（日频，无滞后）
  - 财务（ROE 等）：用 report_date <= 决策日 - 60天 的最新值
    （财报有 1~3 个月披露滞后，预留 60 天避免未来函数）
"""
from datetime import date, datetime, timedelta
from typing import Optional

# 财报披露滞后（天）。季报通常滞后 1~3 个月，60 天偏保守。
FINANCIAL_LAG_DAYS = 60


def _as_date(d) -> Optional[date]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        try:
            return datetime.strptime(d[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def latest_valuation(
    valuation_rows: Optional[list[dict]],
    today: date,
) -> Optional[dict]:
    """
    点-in-time 估值：返回 trade_date <= today 的最新一条估值记录。
    估值是日频数据，无披露滞后。
    """
    if not valuation_rows:
        return None
    best: Optional[dict] = None
    best_date = None
    for r in valuation_rows:
        d = _as_date(r.get("trade_date"))
        if d is None or d > today:
            continue
        if best_date is None or d > best_date:
            best_date = d
            best = r
    return best


def latest_financials(
    financial_rows: Optional[list[dict]],
    today: date,
    lag_days: int = FINANCIAL_LAG_DAYS,
) -> Optional[dict]:
    """
    点-in-time 财务：返回 report_date <= today - lag_days 的最新一期财报。
    预留披露滞后，避免未来函数。
    """
    if not financial_rows:
        return None
    cutoff = today - timedelta(days=lag_days)
    best: Optional[dict] = None
    best_date = None
    for r in financial_rows:
        d = _as_date(r.get("report_date"))
        if d is None or d > cutoff:
            continue
        if best_date is None or d > best_date:
            best_date = d
            best = r
    return best


def rank_cross_section(
    candidates: dict[str, float],
    descending: bool = True,
) -> dict[str, float]:
    """
    横截面排名：把绝对值转成 0~1 分位。
    descending=True → 值越大分位越高（如 ROIC、股息率，越大越好）。
    descending=False → 值越小分位越高（如 PE、PB，越小越便宜）。

    Returns:
        {symbol: 分位 0~1}，1 表示最优。
    """
    if not candidates:
        return {}
    items = sorted(
        candidates.items(),
        key=lambda x: x[1],
        reverse=descending,
    )
    n = len(items)
    return {sym: (n - i) / n for i, (sym, _) in enumerate(items)}


def top_n_by_score(
    scores: dict[str, float],
    n: int,
    min_score: Optional[float] = None,
) -> list[str]:
    """
    按综合得分取前 N 名标的。可设最低分阈值。
    """
    filtered = scores
    if min_score is not None:
        filtered = {s: v for s, v in scores.items() if v >= min_score}
    ranked = sorted(filtered.items(), key=lambda x: -x[1])
    return [s for s, _ in ranked[:n]]


def equal_weights(symbols: list[str]) -> dict[str, float]:
    """等权分配。空列表返回空。"""
    if not symbols:
        return {}
    w = 1.0 / len(symbols)
    return {s: round(w, 6) for s in symbols}
