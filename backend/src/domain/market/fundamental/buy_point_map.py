"""历史买点地图 + 分红税持有期（价值投资四期 P1/P2）。

P1：历史指标值落在当前值 ±band 内的交易日 → N 日远期收益分布。
历史研究性质（含幸存者偏差），不是回测信号。
P2：个人分红差别化税率（持股<1月20% / 1月-1年10% / ≥1年0%）。
"""
import datetime as dt
import statistics
from typing import Optional


def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(q * (len(s) - 1))))
    return round(s[k], 2)


def buy_point_map(
    val_rows: list, price_rows: list, metric: str = "pe_ttm",
    current_value: Optional[float] = None, band: float = 0.10,
    horizons: Optional[list] = None,
) -> dict:
    """val_rows: [{trade_date, pe_ttm|pb}]; price_rows: [{trade_date,
    close}]（均升序）。current_value 缺省用最新值。

    输出 by_horizon: {N: {n, avg_pct, median_pct, win_rate, p10, p90}}。
    """
    horizons = horizons or [252, 756, 1260]
    if current_value is None and val_rows:
        current_value = next(
            (r.get(metric) for r in reversed(val_rows)
             if r.get(metric)), None,
        )
    out = {
        "metric": metric, "current_value": current_value,
        "band": band, "sample_count": 0, "by_horizon": {},
        "note": "历史研究:指标在当前值±band内的交易日,N日远期收益"
                "分布。含幸存者偏差,非预测。",
    }
    if current_value is None:
        return out

    px_by_date = {r["trade_date"]: float(r["close"])
                  for r in price_rows if r.get("close")}
    px_dates = sorted(px_by_date)
    px_vals = [px_by_date[d] for d in px_dates]

    def _forward_ret(d, n):
        """d 起 n 个交易日的远期收益（对齐到价格序列索引）。"""
        try:
            i = px_dates.index(d)
        except ValueError:
            # 估值日无价格(如当日停牌) → 取 d 之后最近交易日
            i = None
            for j, dd in enumerate(px_dates):
                if dd >= d:
                    i = j
                    break
            if i is None:
                return None
        j = i + n
        if j >= len(px_vals) or px_vals[i] <= 0:
            return None
        return (px_vals[j] / px_vals[i] - 1) * 100

    lo, hi = current_value * (1 - band), current_value * (1 + band)
    for n in horizons:
        rets = []
        for r in val_rows:
            v = r.get(metric)
            d = r.get("trade_date")
            if v is None or not lo <= v <= hi:
                continue
            ret = _forward_ret(d, n)
            if ret is not None:
                rets.append(ret)
        out["by_horizon"][str(n)] = {
            "n": len(rets),
            "avg_pct": round(statistics.mean(rets), 2) if rets else None,
            "median_pct": round(statistics.median(rets), 2)
            if rets else None,
            "win_rate": round(
                sum(1 for x in rets if x > 0) / len(rets) * 100, 1
            ) if rets else None,
            "p10": _pct(rets, 0.10), "p90": _pct(rets, 0.90),
        }
    out["sample_count"] = out["by_horizon"][str(horizons[0])]["n"]
    return out


def dividend_tax(buy_date, ex_date) -> dict:
    """个人分红差别化税率：持股<1月20% / 1月-1年10% / ≥1年0%。

    免税线 = 买入日 + 1年（持有到除息日满一年即 0%）。
    """
    if not buy_date or not ex_date:
        return {"rate_pct": None, "free_after": None,
                "days_to_free": None}
    free_date = buy_date.replace(year=buy_date.year + 1) \
        if not (buy_date.month == 2 and buy_date.day == 29) \
        else buy_date.replace(year=buy_date.year + 1, day=28)
    if ex_date >= free_date:
        rate = 0
    elif (ex_date - buy_date).days >= 31:
        rate = 10
    else:
        rate = 20
    return {
        "rate_pct": rate,
        "free_after": free_date.isoformat(),
        "days_to_free": max((free_date - ex_date).days, 0),
        "note": "个人差别化:持股≥1年免/1月-1年10%/<1月20%",
    }
