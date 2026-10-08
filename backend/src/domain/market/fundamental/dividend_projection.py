"""股息现金流投影纯函数（价值投资二期 F4）。

由历史分红事件（stock_dividend）外推未来 12 月：
- 年度每股分红合计与增速（近一年 vs 上一年）；
- 未来 12 月排期沿用历史除息月份分布，金额=最近年度合计×(1+增速)
  按各月历史份额分摊；外推仅为预期，实际以公告为准。
"""
import datetime as dt
from typing import Optional


def dividend_projection(
    dividends: list, shares: float, today: Optional[dt.date] = None,
) -> dict:
    """dividends: [{ex_date, div_per_share}] 升序任意序均可。"""
    today = today or dt.date.today()
    events = sorted(
        (d for d in dividends
         if d.get("ex_date") and d.get("div_per_share")),
        key=lambda d: d["ex_date"],
    )
    if not events or not shares:
        return {
            "annual": [], "latest_growth_pct": None,
            "monthly": [], "next_12m_amount": None,
            "note": "无分红历史或无持仓股数。",
        }

    # 年度每股合计
    by_year: dict = {}
    for e in events:
        y = e["ex_date"].year
        by_year[y] = by_year.get(y, 0.0) + e["div_per_share"]
    years = sorted(by_year)
    annual = [
        {"year": y, "dps_total": round(by_year[y], 4)} for y in years
    ]
    latest_year = years[-1]
    prev_year = years[-2] if len(years) >= 2 else None
    growth = None
    # 当前年未走完(年报分红多在次年5-6月) → 年度不完整,
    # 算增速会用半年度冒充全年 → 置 None 且不用增速外推
    latest_year_complete = (
        latest_year < today.year or today.month == 12
    )
    if (prev_year is not None and by_year[prev_year] > 0
            and latest_year_complete):
        growth = round(
            (by_year[latest_year] / by_year[prev_year] - 1) * 100, 2
        )

    # 未来12月排期: 近2年除息月份分布(任何季度/半年/年度节奏
    # 都能看到完整周期; 金额锚仍是最近完整年度)
    recent = [
        e for e in events
        if (today - e["ex_date"]).days <= 730
    ]
    pattern: dict = {}   # month -> 权重(最近年度每股)
    for e in recent:
        pattern.setdefault(e["ex_date"].month, 0.0)
        pattern[e["ex_date"].month] += e["div_per_share"]
    pat_total = sum(pattern.values()) or 1.0
    base_total = by_year[latest_year]
    factor = 1 + (growth / 100 if growth else 0)
    # 不完整年度: base 用最近年合计,但按历史完整年度的月度形状
    # pattern 本身覆盖近400天,已含上一完整年度 → 形状不失真

    monthly = []
    horizon = today.replace(year=today.year + 1)
    m = today.replace(day=1)
    while m <= horizon:
        if m.month in pattern:
            share = pattern[m.month] / pat_total
            amt = round(shares * base_total * factor * share, 2)
            monthly.append({"month": m.isoformat()[:7], "amount": amt})
        # 前进一个月
        m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    next_12m = round(sum(x["amount"] for x in monthly), 2) \
        if monthly else None

    return {
        "annual": annual,
        "latest_growth_pct": growth,
        "latest_annual_dps": round(base_total, 4),
        "monthly": monthly,
        "next_12m_amount": next_12m,
        "note": "未来排期按历史除息月分布外推(含增速),"
                "实际以公司公告为准。",
    }
