"""同型分析（Common-Size Analysis / 垂直分析）纯函数。

把三大报表的全部科目（stock_financial_detail.detail JSONB）除以基准值
转为结构百分比，消除规模差异，用于跨期比较报表结构：

  - income   利润表：     科目 ÷ 营业总收入（原始报告期累计口径）
  - balance  资产负债表： 科目 ÷ 资产合计
  - cashflow 现金流量表： 科目 ÷ 现金流入总额（经营+投资+筹资三项流入小计之和）

输入 detail dict：akshare 同花顺/东财原始科目名 → 数值（float 或 '547.03亿'
这类字符串）。dict key 顺序即报表科目顺序，输出保持该顺序。

口径约定（对齐 quality.py）：缺失/无基准返回 None 不抛异常；百分比保留
2 位小数；科目值为 None 的行保留（raw/pct=None）以维持结构完整。

⚠️ 单季口径不可用：detail 科目是累计值且无法可靠差分（period_transform
只处理固定列），本模块只用于原始报告期与年报期。
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


# ── 基准科目候选（按优先级；'*' 前缀为同花顺重述科目；后段为东财港股科目名）──
BASE_CANDIDATES: dict[str, list[str]] = {
    "income": ["*营业总收入", "一、营业总收入", "营业收入", "营业额", "营业收益"],
    "balance": ["*资产合计", "资产合计", "总资产", "资产总额"],
}

# 现金流量表无"现金流入总额"总科目：基准 = 三项活动流入小计之和。
# 同花顺对无该类流入的公司填 None（如茅台无筹资流入）→ 按 0 计入；
# 三项全缺/全 0 → 无基准。
CASHFLOW_INFLOW_CANDIDATES: list[list[str]] = [
    ["经营活动现金流入小计", "*经营活动现金流入小计"],
    ["投资活动现金流入小计", "*投资活动现金流入小计"],
    ["筹资活动现金流入小计", "*筹资活动现金流入小计"],
]
CASHFLOW_BASE_NAME = "现金流入总额(经营+投资+筹资流入小计)"

_CHAPTER_CHARS = "一二三四五六七八九十"


def subject_level(name: str) -> int:
    """科目层级推断（前端缩进用）：'一、'→0（章）；'其中：'→2（子项）；其余→1。"""
    if not name:
        return 1
    if len(name) >= 2 and name[0] in _CHAPTER_CHARS and name[1] == "、":
        return 0
    if name.startswith("其中：") or name.startswith("其中:"):
        return 2
    return 1


def _pick_amount(
    detail: dict, candidates: list[str]
) -> tuple[Optional[str], Optional[float]]:
    """按候选顺序取首个数值非 None 的科目；返回 (命中科目名, 数值)。"""
    for k in candidates:
        if k in detail:
            v = parse_amount(detail.get(k))
            if v is not None:
                return k, v
    return None, None


def _resolve_base(
    detail: dict, statement_type: str
) -> tuple[Optional[str], Optional[float]]:
    """解析该期基准：(基准名, 基准值)；无基准返回 (None, None)。"""
    if not isinstance(detail, dict):
        return None, None
    if statement_type == "cashflow":
        total = 0.0
        for candidates in CASHFLOW_INFLOW_CANDIDATES:
            _, v = _pick_amount(detail, candidates)
            total += v if v is not None else 0.0  # 缺失按 0（无该类流入）
        if total <= 0:
            return None, None
        return CASHFLOW_BASE_NAME, total
    candidates = BASE_CANDIDATES.get(statement_type)
    if not candidates:
        return None, None
    return _pick_amount(detail, candidates)


def common_size_rows(detail: dict, statement_type: str) -> Optional[list[dict]]:
    """单期同型分析：全部科目 ÷ 基准值 → 结构百分比。

    Returns:
        ``[{name, level, raw, pct}]`` 按 detail 原始顺序；基准行 pct=100.0。
        基准缺失或 ≤ 0、detail 为空、statement_type 未知 → None。
    """
    if not isinstance(detail, dict) or not detail:
        return None
    _, base = _resolve_base(detail, statement_type)
    if base is None or base <= 0:
        return None
    rows: list[dict] = []
    for name, raw_v in detail.items():
        raw = parse_amount(raw_v)
        pct = round(raw / base * 100, 2) if raw is not None else None
        rows.append({"name": name, "level": subject_level(name), "raw": raw, "pct": pct})
    return rows


def common_size_series(rows: list[dict], statement_type: str) -> dict:
    """多期聚合。

    Args:
        rows: 升序 ``[{report_date: date|str, detail: dict|None}]``。
    Returns:
        ``{"base_name": str|None, "periods": [{"report_date": iso, "base_value", "items"}]}``
        periods 降序（最新在前），无基准期跳过。
    """
    periods: list[dict] = []
    base_name: Optional[str] = None
    for r in rows or []:
        detail = (r or {}).get("detail")
        items = common_size_rows(detail, statement_type)
        if items is None:
            continue
        name, value = _resolve_base(detail, statement_type)
        base_name = name or base_name
        rd = (r or {}).get("report_date")
        rd_str = rd.isoformat() if hasattr(rd, "isoformat") else (str(rd) if rd else None)
        periods.append({"report_date": rd_str, "base_value": value, "items": items})
    periods.reverse()
    return {"base_name": base_name, "periods": periods}
