"""
个股股息率计算（纯函数）
=========================
基于分红明细计算 TTM（滚动十二个月）每股股息与股息率。

口径（价值投资严谨性）：
  - 以「除权除息日」为生效时点：只有 ex_date <= as_of 的分红才计入。
  - TTM 窗口：as_of 往前回溯 lookback_days（默认 365）内已实施的现金分红。
  - 只计「派息」（现金）；送股/转增是股票股利，不影响现金股息率。
  - dv_ttm (%) = TTM 每股派息 / 每股股价 × 100

数据来源：stock_dividend 表（akshare stock_history_dividend_detail）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Sequence


def _as_date(v) -> Optional[date]:
    """把 datetime/date/字符串统一为 date；失败返回 None。"""
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, type(None)):
        # datetime 是 date 的子类，.date() 取日期部分
        if hasattr(v, "date") and callable(v.date):
            try:
                return v.date()
            except Exception:  # noqa: BLE001
                return None
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def ttm_dividend_per_share(
    dividends: Sequence[dict],
    as_of: date,
    lookback_days: int = 365,
) -> Optional[float]:
    """
    过去 lookback_days 天内（按除权除息日）已实施现金分红的
    每股派息合计（元/股）。

    Args:
        dividends: [{ex_date, div_per_share, ...}, ...]，乱序或有序均可。
        as_of: 评估日（含）。
        lookback_days: 回溯天数（默认 365，约 TTM）。

    Returns:
        每股派息合计；区间内无任何分红返回 None。
    """
    if not dividends:
        return None
    cutoff = as_of - timedelta(days=lookback_days)
    total = 0.0
    found = False
    for d in dividends:
        ex = _as_date(d.get("ex_date"))
        dps = d.get("div_per_share")
        if ex is None or dps is None:
            continue
        if cutoff < ex <= as_of:
            try:
                total += float(dps)
                found = True
            except (TypeError, ValueError):
                continue
    return total if found else None


def dividend_yield_ttm(
    dividends: Sequence[dict],
    price: float,
    as_of: date,
    lookback_days: int = 365,
) -> Optional[float]:
    """
    TTM 股息率（%）= TTM 每股派息 / price × 100。

    price <= 0 或区间内无分红时返回 None。
    """
    if price is None or price <= 0:
        return None
    dps = ttm_dividend_per_share(dividends, as_of, lookback_days)
    if dps is None or dps <= 0:
        return None
    return dps / price * 100.0
