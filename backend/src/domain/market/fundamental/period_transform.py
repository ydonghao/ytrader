"""财务报表周期转换（单季换算 / 年报过滤）。

纯函数、无 DB 依赖。输入输出均为 dict 列表（字段名对齐
stock_financial_detail 的固定列）。

分类依据（参考 financial_full.py 的 _DETAIL_COLUMNS）：
  - 流量项（发生额，累计值需做差）: 利润表 + 现金流量表全部
  - 存量项（时点余额，不做差）: 资产负债表全部
  - 派生项（毛利率/净利率/资产负债率）: 换算后用单季值重算
"""
from typing import Any

# ── 字段分类常量 ──────────────────────────────────────────────────────────

# 流量项：累计值，需做差得到单季值（利润表 + 现金流量表的所有发生额）
# 注意：gross_profit 不在此列——它是派生项（revenue - operating_cost），
# 由 _recompute_derived 在差分后统一重算，避免"既做差又重算"的语义歧义。
FLOW_FIELDS: frozenset[str] = frozenset({
    "revenue", "operating_cost",
    "sell_expense", "admin_expense", "rd_expense", "fin_expense",
    "operating_profit", "net_profit", "net_profit_parent",
    "net_profit_deduct",
    "ocf", "icf", "fcf", "capex",
})

# 存量项：时点余额，不做差（资产负债表全部）
STOCK_FIELDS: frozenset[str] = frozenset({
    "monetary_funds", "accounts_receivable", "inventory",
    "fixed_assets", "goodwill",
    "total_assets", "total_liabilities",
    "equity", "equity_parent",
    "short_loan", "long_loan", "cash_end",
})


def _year_of(report_date: Any) -> int | None:
    """从 report_date（date 或 'YYYY-MM-DD' 字符串）取年份。"""
    if report_date is None:
        return None
    if hasattr(report_date, "year"):
        return report_date.year
    s = str(report_date)[:4]
    return int(s) if s.isdigit() else None


def _diff_or_keep(cur: Any, prev: Any) -> Any:
    """两者都为数值时做差；任一为 None 时返回 cur（降级为累计）。"""
    if isinstance(cur, (int, float)) and isinstance(
        prev, (int, float)
    ):
        return cur - prev
    return cur


def _recompute_derived(d: dict) -> None:
    """用差分后的单季值重算毛利率/净利率/资产负债率（保护除零）。"""
    revenue = d.get("revenue")
    op_cost = d.get("operating_cost")
    if isinstance(revenue, (int, float)) and isinstance(
        op_cost, (int, float)
    ) and revenue:
        gross = revenue - op_cost
        d["gross_profit"] = gross
        d["gross_margin"] = round(gross / revenue * 100, 4)
    net = d.get("net_profit")
    if isinstance(net, (int, float)) and revenue:
        d["net_margin"] = round(net / revenue * 100, 4)
    liab = d.get("total_liabilities")
    assets = d.get("total_assets")
    if isinstance(liab, (int, float)) and isinstance(
        assets, (int, float)
    ) and assets:
        d["debt_ratio"] = round(liab / assets * 100, 4)
    ocf = d.get("ocf")
    capex = d.get("capex")
    if isinstance(ocf, (int, float)) and isinstance(capex, (int, float)):
        d["free_cash_flow"] = ocf - abs(capex)


def transform_to_quarter(rows: list[dict]) -> list[dict]:
    """把累计报告期序列差分为单季值（就地修改并返回）。

    规则：
      - 按 report_date 升序遍历
      - 对流量项（FLOW_FIELDS）：若同年有上一期，做 cur - prev
        （prev 取上一期的**原始累计值**，而非已差分后的单季值）
      - 对存量项（STOCK_FIELDS）：保持当期值不变
      - 派生项（gross_margin 等）：换算后重算
      - 每年第一期（Q1）保持累计值（无上期可减）
      - 跨年时新一年的 Q1 不减上一年年报（按年份分组）

    Args:
        rows: 升序的报表期 dict 列表，每条含 report_date + 字段。

    Returns:
        同一 list 对象（就地修改），流量项已转为单季值。
    """
    if not rows:
        return rows

    # 保存每年上一期的**原始累计值**快照（做差基准）。
    # 不能直接存已就地修改后的 r，否则下一期会减去单季值而非累计值。
    prev_cum_by_year: dict[int, dict] = {}
    for r in rows:
        y = _year_of(r.get("report_date"))
        # 先抓取本期原始累计值（做差前），作为下一期的基准
        orig_cum = {f: r[f] for f in FLOW_FIELDS if f in r}
        prev = prev_cum_by_year.get(y) if y is not None else None
        if prev is not None:
            for f in FLOW_FIELDS:
                if f in r:
                    r[f] = _diff_or_keep(r[f], prev.get(f))
        _recompute_derived(r)
        if y is not None:
            prev_cum_by_year[y] = orig_cum
    return rows


def filter_year_only(rows: list[dict]) -> list[dict]:
    """只保留年报期（report_date 月份 == 12）。不改值。"""
    out = []
    for r in rows:
        rd = r.get("report_date")
        m = getattr(rd, "month", None)
        if m is None and rd:
            parts = str(rd)[:10].split("-")
            m = int(parts[1]) if len(parts) >= 2 else None
        if m == 12:
            out.append(r)
    return out
