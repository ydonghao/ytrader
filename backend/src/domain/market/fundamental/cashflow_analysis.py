"""现金流分析（Cashflow Analysis）纯函数。

跨 income+cashflow 两表计算 11 个现金流指标，三组：
  - profit_quality 盈利质量：净现比 / 收现比 / FCF率
  - growth         增长趋势：经营现金流 / 自由现金流 / 净利润同比
  - structure      现金流结构：经营/投资/筹资净额、资本开支、资本开支强度

口径约定（对齐 ratio_analysis.py / quality.py）：缺失/分母 ≤ 0 → None
不抛异常；报告期累计、不年化；同比需去年同期在场且基数 > 0（负基数同比
无意义）；派生比率只在最终赋值处 round，绝对额不 round（前端转亿显示）。

陷阱标注：stock_financial_detail.fcf 列是**筹资活动净额**、不是自由
现金流（quality.py 有两处警告）。自由现金流用 free_cash_flow 列（摄取时
compute_derived 已算 = ocf - abs(capex)），旧库缺该惰性列时计算兜底。
capex 同花顺宽表存正值、部分源存负值 → 一律 abs() 防御。
"""
from __future__ import annotations

from typing import Optional

try:
    from src.infra.database.market.financial_full import parse_amount
except Exception:  # pragma: no cover — 脱离后端环境时的最小兜底

    def parse_amount(v) -> Optional[float]:
        if isinstance(v, bool) or v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "").replace(" ", "")
        if s in ("", "nan", "NaN", "None", "--", "null"):
            return None
        try:
            if s.endswith("亿"):
                return float(s[:-1]) * 1e8
            if s.endswith("万"):
                return float(s[:-1]) * 1e4
            return float(s)
        except ValueError:
            return None


# ── 分组与指标元数据（groups 随 API 下发，前端不重复维护定义）──
GROUPS: list[dict] = [
    {"key": "profit_quality", "label": "盈利质量"},
    {"key": "growth", "label": "增长趋势"},
    {"key": "structure", "label": "现金流结构"},
]

CASHFLOW_META: list[dict] = [
    {"key": "ocf_to_profit", "label": "净现比", "group": "profit_quality",
     "unit": "x", "formula": "经营活动现金流净额/净利润（净利≤0→None）"},
    {"key": "cash_to_revenue", "label": "收现比",
     "group": "profit_quality", "unit": "x",
     "formula": "销售商品、提供劳务收到的现金/营业总收入（科目缺失→None）"},
    {"key": "fcf_margin", "label": "FCF率", "group": "profit_quality",
     "unit": "pct", "formula": "自由现金流/营业总收入"},
    {"key": "ocf_yoy", "label": "经营现金流同比", "group": "growth",
     "unit": "growth", "formula": "经营现金流净额同比-1（基数>0）"},
    {"key": "fcf_yoy", "label": "自由现金流同比", "group": "growth",
     "unit": "growth", "formula": "自由现金流同比-1（基数>0）"},
    {"key": "net_profit_yoy", "label": "净利润同比", "group": "growth",
     "unit": "growth",
     "formula": "净利润同比-1（基数>0，与OCF交叉验证背离）"},
    {"key": "ocf", "label": "经营净额", "group": "structure",
     "unit": "yi", "formula": "固定列 ocf（元）"},
    {"key": "icf", "label": "投资净额", "group": "structure",
     "unit": "yi", "formula": "固定列 icf（元）"},
    {"key": "financing", "label": "筹资净额", "group": "structure",
     "unit": "yi",
     "formula": "固定列 fcf（注意：该列是筹资活动净额，非自由现金流）"},
    {"key": "capex", "label": "资本开支", "group": "structure",
     "unit": "yi", "formula": "固定列 capex（元，取绝对值）"},
    {"key": "capex_to_ocf", "label": "资本开支强度",
     "group": "structure", "unit": "pct",
     "formula": "|资本开支|/经营现金流净额（OCF≤0→None）"},
]

# detail 中文候选名（A 股同花顺在前；'*' 前缀为同花顺重述科目）
DETAIL_CANDIDATES: dict[str, list[str]] = {
    "cash_from_sales": ["销售商品、提供劳务收到的现金",
                        "*销售商品、提供劳务收到的现金"],
}

ALL_FIELDS: list[str] = [
    "revenue", "net_profit", "ocf", "icf", "fcf", "capex",
    "free_cash_flow", "cash_end", "cash_from_sales",
]

# 有英文固定列的语义字段（stock_financial_detail 列名与语义名一致）
FIXED_FIELDS: frozenset = frozenset({
    "revenue", "net_profit", "ocf", "icf", "fcf", "capex",
    "free_cash_flow", "cash_end",
})


def _pick_amount(detail: dict, candidates: list[str]) -> Optional[float]:
    """按候选顺序取首个数值非 None 的科目（模式抄 ratio_analysis）。"""
    for k in candidates:
        if isinstance(detail, dict) and k in detail:
            v = parse_amount(detail.get(k))
            if v is not None:
                return v
    return None


def resolve_cashflow_fields(fin: dict, details: list) -> dict:
    """单期字段归一：固定列非 None 优先 → detail 候选名兜底。

    Returns:
        ``{语义字段: float | None}``，覆盖 ALL_FIELDS 全部键。
    """
    fin = fin if isinstance(fin, dict) else {}
    details = [d for d in (details or []) if isinstance(d, dict)]
    out: dict[str, Optional[float]] = {}
    for field in ALL_FIELDS:
        v = None
        if field in FIXED_FIELDS:
            v = parse_amount(fin.get(field))
        if v is None:
            for d in details:
                v = _pick_amount(d, DETAIL_CANDIDATES.get(field, []))
                if v is not None:
                    break
        out[field] = v
    return out


def _div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """安全除：任一为 None 或分母 ≤ 0 → None。不舍入（调用处终值舍入）。"""
    if num is None or den is None or den <= 0:
        return None
    return num / den


def _r4(x: Optional[float]) -> Optional[float]:
    """倍数类终值舍入（只在最终赋值处舍入一次）。"""
    return None if x is None else round(x, 4)


def _pct(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x * 100, 4)


def _date_str(rd) -> Optional[str]:
    """report_date 归一为 ISO 字符串（兼容 date 与 str）。"""
    if rd is None:
        return None
    if hasattr(rd, "isoformat"):
        return rd.isoformat()
    return str(rd)[:10]


def _year_ago(ds: Optional[str]) -> Optional[str]:
    """去年同日字符串（报告期均为季末，无 2/29 边缘）。"""
    if not ds or len(ds) < 4:
        return None
    try:
        return str(int(ds[:4]) - 1) + ds[4:]
    except ValueError:
        return None


def _build_groups() -> list[dict]:
    return [
        {
            "key": g["key"],
            "label": g["label"],
            "ratios": [
                {"key": m["key"], "label": m["label"],
                 "unit": m["unit"], "formula": m["formula"]}
                for m in CASHFLOW_META if m["group"] == g["key"]
            ],
        }
        for g in GROUPS
    ]


def cashflow_series(records: list[dict]) -> dict:
    """多期现金流指标计算（11 指标 × 每期）。

    Args:
        records: 升序 ``[{report_date: date|str, fin: dict,
          details: list[dict|None]}]``（fin=两表固定列合并，
          details=[cashflow_detail, income_detail]）。
    Returns:
        ``{"groups": [...], "periods": [{"report_date", "values", "ratios"}]}``
        periods 降序（最新在前）。values=resolve_cashflow_fields 完整结果
        （free_cash_flow 缺列时已兜底写回）。
    """
    resolved: list[dict] = []
    for r in records or []:
        r = r or {}
        ds = _date_str(r.get("report_date"))
        if ds is None:
            continue
        vals = resolve_cashflow_fields(r.get("fin"), r.get("details"))
        # 旧库可能缺 free_cash_flow 惰性列 → 兜底（同比也需历史期 FCF）
        if vals.get("free_cash_flow") is None:
            ocf_v, capex_v = vals.get("ocf"), vals.get("capex")
            if ocf_v is not None and capex_v is not None:
                vals["free_cash_flow"] = ocf_v - abs(capex_v)
        resolved.append({"ds": ds, "values": vals})
    by_ds = {p["ds"]: p["values"] for p in resolved}

    periods: list[dict] = []
    for p in resolved:
        v = p["values"]
        last = by_ds.get(_year_ago(p["ds"]))

        def yoy(field: str) -> Optional[float]:
            if last is None:
                return None
            cur, base = v.get(field), last.get(field)
            if cur is None or base is None or base <= 0:
                return None
            return round((cur / base - 1) * 100, 4)

        capex_abs = abs(v["capex"]) if v.get("capex") is not None else None

        ratios: dict[str, Optional[float]] = {
            # 盈利质量
            "ocf_to_profit": _r4(_div(v.get("ocf"), v.get("net_profit"))),
            "cash_to_revenue": _r4(_div(v.get("cash_from_sales"),
                                        v.get("revenue"))),
            "fcf_margin": _pct(_div(v.get("free_cash_flow"),
                                    v.get("revenue"))),
            # 增长趋势（同比）
            "ocf_yoy": yoy("ocf"),
            "fcf_yoy": yoy("free_cash_flow"),
            "net_profit_yoy": yoy("net_profit"),
            # 现金流结构（绝对额原值透传，前端转亿；capex 取 abs）
            "ocf": v.get("ocf"),
            "icf": v.get("icf"),
            "financing": v.get("fcf"),  # fcf 列=筹资活动净额（非FCF）
            "capex": capex_abs,
            "capex_to_ocf": _pct(_div(capex_abs, v.get("ocf"))),
        }
        periods.append(
            {"report_date": p["ds"], "values": v, "ratios": ratios}
        )

    periods.reverse()
    return {"groups": _build_groups(), "periods": periods}
