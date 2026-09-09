# 现金流分析（Cashflow Analysis）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在财务报表功能中新增"现金流分析"Tab：后端纯函数计算 11 个现金流指标（盈利质量/增长趋势/现金流结构三组）多期时序 + API 端点 + 前端分组矩阵与趋势图。

**Architecture:** 镜像 ratio-analysis 范式——`src/domain/market/fundamental/cashflow_analysis.py` 纯函数（dict 进 dict 出、不读 DB、缺 key 返 None）→ `financial_detail_handler.cashflow_analysis`（income+cashflow 两表按 report_date 内连接、**先全量计算再截 limit**）→ `GET /financial/cashflow-analysis/{symbol}`（独立路径，已核实与现有 31 条路径零冲突）→ `useCashflowAnalysis` hook + `CashflowAnalysisPanel` 组件 + Financial.tsx Tab 注册。

**Tech Stack:** Python 3.11 + FastAPI + SQLModel（后端）；React + recharts + pnpm/Rush monorepo（前端）。

## Global Constraints

- 设计文档：`docs/superpowers/specs/2026-08-18-cashflow-analysis-design.md`（口径以它为准）。
- 口径：报告期累计、不年化；同比需去年同期在场且基数 > 0；任一分母缺失/≤0 → None 不抛异常；派生比率只在最终赋值处 round 一次（比率 `_r4`/百分比 `_pct`，绝对额**不 round**——前端转亿显示）。
- 11 指标三分组（键名固定）：profit_quality= ocf_to_profit/cash_to_revenue/fcf_margin；growth= ocf_yoy/fcf_yoy/net_profit_yoy；structure= ocf/icf/financing/capex/capex_to_ocf。
- **`fcf` 列陷阱**：`stock_financial_detail.fcf` 是筹资活动净额、不是自由现金流（quality.py 有两处警告）。自由现金流用 `free_cash_flow` 列，缺列时兜底 `ocf - abs(capex)`；capex 一律 `abs()`（同花顺存正、部分源存负）。
- 后端代码风格：flake8 max-line-length 79、ignore E203/W503；black/isort line-length 79。纯函数模块顶部写中文 docstring（方法论+口径）。flake8 若未安装则跳过 lint 步骤，以 pytest 为准。
- 前端代码风格：对齐 `RatiosPanel.tsx`/`useRatios.ts`；图表用 recharts + `src/lib/chartTheme.ts` 令牌；Δ列中性配色升 `#79c0ff` 降 `#a1a1a6`（现金流指标无 A股涨跌语义）。
- 测试运行：后端 `cd backend && uv run pytest <path> -q`；前端 `cd frontend && pnpm -F web build`（无前端单测框架）。
- 后端全量回归**存在既有失败**（52 失败 + 6 收集错误属历史遗留）：Task 5 以"新增测试全过 + 失败数不高于基线"为标准，不要求全绿。
- 不改存量 Tab 与既有端点；不动工作区中与本功能无关的未提交改动（backend/uv.lock、ValuationPercentileChart.tsx 等）。
- 每个任务一个 commit，消息格式对齐近期提交（`feat(cashflow-analysis): ...`）。

---

### Task 1: 纯函数模块——元数据 + 字段解析 `resolve_cashflow_fields`

**Files:**
- Create: `backend/src/domain/market/fundamental/cashflow_analysis.py`
- Test: `backend/tests/domain/market/fundamental/test_cashflow_analysis.py`

**Interfaces:**
- Consumes: `src.infra.database.market.financial_full.parse_amount`（try-import + 本地兜底，模式抄 ratio_analysis.py:22-41）。
- Produces（Task 2/3 依赖）:
  - `GROUPS: list[dict]`、`CASHFLOW_META: list[dict]`（key/label/group/unit/formula）
  - `ALL_FIELDS: list[str]`（9 个语义字段）
  - `FIXED_FIELDS: frozenset[str]`（8 个有英文固定列的语义字段）
  - `DETAIL_CANDIDATES: dict[str, list[str]]`
  - `resolve_cashflow_fields(fin: dict, details: list) -> dict[str, float | None]`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/domain/market/fundamental/test_cashflow_analysis.py`：

```python
"""现金流分析纯函数测试。镜像 test_ratio_analysis.py 风格。"""
import datetime as dt

import pytest

from src.domain.market.fundamental.cashflow_analysis import (
    ALL_FIELDS,
    CASHFLOW_META,
    resolve_cashflow_fields,
)


class TestResolveCashflowFields:
    def test_fixed_column_takes_priority(self):
        # 固定列非 None 应压过 detail 候选
        out = resolve_cashflow_fields(
            {"ocf": 52.0}, [{"经营活动产生的现金流量净额": 999.0}]
        )
        assert out["ocf"] == 52.0

    def test_cash_from_sales_from_detail(self):
        # 销售商品收到的现金无固定列 → cashflow detail 候选名
        out = resolve_cashflow_fields(
            {}, [{"销售商品、提供劳务收到的现金": 210.0}]
        )
        assert out["cash_from_sales"] == 210.0

    def test_restarred_candidate(self):
        out = resolve_cashflow_fields(
            {}, [{"*销售商品、提供劳务收到的现金": 180.0}]
        )
        assert out["cash_from_sales"] == 180.0

    def test_string_amount_parsed(self):
        out = resolve_cashflow_fields({}, [{"销售商品、提供劳务收到的现金": "5亿"}])
        assert out["cash_from_sales"] == pytest.approx(5e8)

    def test_income_fields_from_fin(self):
        out = resolve_cashflow_fields(
            {"revenue": 200.0, "net_profit": 40.0}, [{}]
        )
        assert out["revenue"] == 200.0
        assert out["net_profit"] == 40.0

    def test_missing_returns_none(self):
        out = resolve_cashflow_fields({}, [{}])
        for f in ALL_FIELDS:
            assert out[f] is None

    def test_none_details_tolerated(self):
        out = resolve_cashflow_fields({"ocf": 1.0}, None)
        assert out["ocf"] == 1.0
        assert out["cash_from_sales"] is None

    def test_meta_completeness(self):
        assert len(CASHFLOW_META) == 11
        groups = {m["group"] for m in CASHFLOW_META}
        assert groups == {"profit_quality", "growth", "structure"}
        for m in CASHFLOW_META:
            assert m["unit"] in ("pct", "x", "growth", "yi")
            assert m["formula"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_cashflow_analysis.py -q`
Expected: FAIL（`ModuleNotFoundError: ... cashflow_analysis`）

- [ ] **Step 3: 写最小实现**

创建 `backend/src/domain/market/fundamental/cashflow_analysis.py`：

```python
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
                v = _pick_amount(d, DETAIL_CANDIDATES[field])
                if v is not None:
                    break
        out[field] = v
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_cashflow_analysis.py -q`
Expected: PASS（8 个）

- [ ] **Step 5: lint 并提交**

```bash
cd backend && uv run flake8 src/domain/market/fundamental/cashflow_analysis.py tests/domain/market/fundamental/test_cashflow_analysis.py
git add backend/src/domain/market/fundamental/cashflow_analysis.py backend/tests/domain/market/fundamental/test_cashflow_analysis.py
git commit -m "feat(cashflow-analysis): 纯函数模块——元数据+字段解析(固定列优先/cash_from_sales候选兜底,8测试)"
```

---

### Task 2: 纯函数模块——`cashflow_series` 多期指标计算

**Files:**
- Modify: `backend/src/domain/market/fundamental/cashflow_analysis.py`（追加）
- Test: `backend/tests/domain/market/fundamental/test_cashflow_analysis.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `resolve_cashflow_fields`/`CASHFLOW_META`/`GROUPS`。
- Produces（Task 3 依赖）: `cashflow_series(records: list[dict]) -> dict`
  - 输入升序 `[{report_date: date|str, fin: dict, details: list[dict|None]}]`
    （fin=income+cashflow 固定列合并，details=[cashflow_detail, income_detail]）
  - 输出 `{"groups": [{"key","label","ratios":[{key,label,unit,formula}]}],
    "periods": [{"report_date": iso, "values": {...}, "ratios": {key: float|None}}]}`
    periods 降序（最新在前）。

- [ ] **Step 1: 追加失败测试**

在 `test_cashflow_analysis.py` 末尾追加（并把文件顶部 import 中加入
`cashflow_series`）：

```python
from src.domain.market.fundamental.cashflow_analysis import (
    ALL_FIELDS,
    CASHFLOW_META,
    cashflow_series,
    resolve_cashflow_fields,
)

FIN_2024 = {
    "revenue": 100.0, "net_profit": 20.0, "ocf": 26.0, "icf": -15.0,
    "fcf": -5.0, "capex": 4.0, "free_cash_flow": 22.0, "cash_end": 50.0,
}
FIN_2025 = {k: v * 2 for k, v in FIN_2024.items()}
DETAIL_SALES = [{"销售商品、提供劳务收到的现金": 105.0}]


def _rec(date, fin=None, details=None):
    return {"report_date": date, "fin": fin or {}, "details": details or []}


class TestCashflowSeries:
    def test_profit_quality_current_period(self):
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 {"revenue": 200.0, "net_profit": 40.0, "ocf": 52.0,
                  "capex": 8.0, "free_cash_flow": 44.0},
                 [{"销售商品、提供劳务收到的现金": 210.0}]),
        ])
        r = out["periods"][0]["ratios"]
        assert r["ocf_to_profit"] == pytest.approx(1.3)      # 52/40
        assert r["cash_to_revenue"] == pytest.approx(1.05)   # 210/200
        assert r["fcf_margin"] == pytest.approx(22.0)        # 44/200
        assert r["capex_to_ocf"] == pytest.approx(8.0 / 52.0 * 100)

    def test_fcf_fallback_when_column_missing(self):
        # 旧库缺 free_cash_flow 惰性列 → 兜底 ocf - abs(capex)
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 {"revenue": 200.0, "ocf": 52.0, "capex": 8.0}, []),
        ])
        r = out["periods"][0]["ratios"]
        assert r["fcf_margin"] == pytest.approx(44.0 / 200.0 * 100)
        assert out["periods"][0]["values"]["free_cash_flow"] == \
            pytest.approx(44.0)

    def test_nonpositive_net_profit_and_missing_sales(self):
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 {"revenue": 200.0, "net_profit": -5.0, "ocf": 52.0}, []),
        ])
        r = out["periods"][0]["ratios"]
        assert r["ocf_to_profit"] is None   # 净利≤0（对齐 quality.py）
        assert r["cash_to_revenue"] is None  # 港股常见：科目缺失

    def test_structure_passthrough_with_abs_capex(self):
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 dict(FIN_2025, capex=-16.0, free_cash_flow=None), []),
        ])
        r = out["periods"][0]["ratios"]
        assert r["ocf"] == pytest.approx(52.0)     # 原值透传（元）
        assert r["icf"] == pytest.approx(-30.0)
        assert r["financing"] == pytest.approx(-10.0)  # fcf 列=筹资净额
        assert r["capex"] == pytest.approx(16.0)   # 负值存储 → abs
        assert r["capex_to_ocf"] == pytest.approx(16.0 / 52.0 * 100)
        assert r["fcf_margin"] == pytest.approx(36.0 / 400.0 * 100)  # 52-16

    def test_ocf_nonpositive_guards(self):
        out = cashflow_series([
            _rec(dt.date(2025, 12, 31),
                 {"revenue": 200.0, "net_profit": 40.0, "ocf": -3.0,
                  "capex": 8.0}, []),
        ])
        r = out["periods"][0]["ratios"]
        assert r["capex_to_ocf"] is None       # OCF≤0
        assert r["fcf_margin"] is not None     # FCF 可为负，率照算

    def test_yoy_growth(self):
        out = cashflow_series([
            _rec(dt.date(2024, 12, 31), FIN_2024, DETAIL_SALES),
            _rec(dt.date(2025, 12, 31), FIN_2025, DETAIL_SALES),
        ])
        r = out["periods"][0]["ratios"]
        assert r["ocf_yoy"] == pytest.approx(100.0)
        assert r["fcf_yoy"] == pytest.approx(100.0)
        assert r["net_profit_yoy"] == pytest.approx(100.0)
        # 首期（降序后最后一行）无去年同期 → None
        assert out["periods"][-1]["ratios"]["ocf_yoy"] is None

    def test_yoy_nonpositive_base(self):
        fin_bad = dict(FIN_2024)
        fin_bad["ocf"] = -26.0
        out = cashflow_series([
            _rec(dt.date(2024, 12, 31), fin_bad, []),
            _rec(dt.date(2025, 12, 31), FIN_2025, []),
        ])
        assert out["periods"][0]["ratios"]["ocf_yoy"] is None

    def test_descending_groups_and_values(self):
        out = cashflow_series([
            _rec(dt.date(2024, 12, 31), FIN_2024, DETAIL_SALES),
            _rec(dt.date(2025, 12, 31), FIN_2025, DETAIL_SALES),
        ])
        assert [p["report_date"] for p in out["periods"]] == [
            "2025-12-31", "2024-12-31",
        ]
        assert [g["key"] for g in out["groups"]] == [
            "profit_quality", "growth", "structure",
        ]
        keys = [m["key"] for g in out["groups"] for m in g["ratios"]]
        assert set(keys) == {m["key"] for m in CASHFLOW_META}
        assert out["periods"][0]["values"]["ocf"] == pytest.approx(52.0)
        assert out["periods"][0]["values"]["cash_from_sales"] == \
            pytest.approx(105.0)

    def test_string_report_date(self):
        out = cashflow_series([_rec("2025-12-31", FIN_2024, [])])
        assert out["periods"][0]["report_date"] == "2025-12-31"

    def test_empty_and_none_records(self):
        assert cashflow_series([])["periods"] == []
        assert cashflow_series(None)["periods"] == []
        assert cashflow_series([{}])["periods"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_cashflow_analysis.py -q`
Expected: FAIL（`ImportError: cannot import name 'cashflow_series'`）

- [ ] **Step 3: 在 cashflow_analysis.py 末尾追加实现**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_cashflow_analysis.py -q`
Expected: PASS（18 个）

- [ ] **Step 5: lint 并提交**

```bash
cd backend && uv run flake8 src/domain/market/fundamental/cashflow_analysis.py tests/domain/market/fundamental/test_cashflow_analysis.py
git add backend/src/domain/market/fundamental/cashflow_analysis.py backend/tests/domain/market/fundamental/test_cashflow_analysis.py
git commit -m "feat(cashflow-analysis): cashflow_series——11指标三分组(fcf兜底/abs防御/同比守卫,10测试)"
```

---

### Task 3: Handler + 路由 + API 测试

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（文件末尾 `ratios` 之后追加 `cashflow_analysis`；`filter_year_only` 已在模块顶部 line 17 导入）
- Modify: `backend/src/api/router/financial_router.py`（line 752 导入列表加 `cashflow_analysis,` + 文件末尾 line 1067 之后追加路由）
- Test: `backend/tests/api/test_cashflow_analysis.py`

**Interfaces:**
- Consumes: Task 1 `FIXED_FIELDS`、Task 2 `cashflow_series`；
  `create_financial_detail_repository().get_history(symbol, statement_type)`；
  `filter_year_only`（handler 模块顶部已导入）；`responses.success/error`。
- Produces: `cashflow_analysis(symbol, period="month", limit=12) -> Any`
  （JSONResponse）；路由 `GET /api/v1/financial/cashflow-analysis/{symbol}`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/api/test_cashflow_analysis.py`：

```python
"""cashflow_analysis 接口测试（mock repo，不发 HTTP）。
模式抄 test_ratios.py。"""
import datetime as dt
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

INCOME_FIN = {"revenue": 200.0, "net_profit": 40.0}
CASHFLOW_FIN = {
    "ocf": 52.0, "icf": -30.0, "fcf": -10.0, "capex": 8.0,
    "free_cash_flow": 44.0, "cash_end": 100.0,
}


def _income_row(report_date):
    r = MagicMock()
    r.report_date = report_date
    r.detail = {"一、营业总收入": 200.0}
    for k, v in INCOME_FIN.items():
        setattr(r, k, v)
    # MagicMock 自动属性会让 getattr(r, 'ocf') 返回 mock 而非 None，
    # 吞掉 cashflow 行的值——必须显式置 None 模拟"本表无此列"
    for k in ("ocf", "icf", "fcf", "capex", "free_cash_flow", "cash_end"):
        setattr(r, k, None)
    return r


def _cashflow_row(report_date):
    r = MagicMock()
    r.report_date = report_date
    r.detail = {"销售商品、提供劳务收到的现金": 210.0}
    for k, v in CASHFLOW_FIN.items():
        setattr(r, k, v)
    for k in ("revenue", "net_profit"):
        setattr(r, k, None)
    return r


def _call(income_rows, cashflow_rows, period="month", limit=12):
    from src.api.handler.financial_detail_handler import cashflow_analysis
    repo = MagicMock()
    repo.get_history.side_effect = (
        lambda sym, st: income_rows if st == "income" else cashflow_rows
    )
    with patch(
        "src.infra.database.market.financial_full"
        ".create_financial_detail_repository",
        return_value=repo,
    ):
        resp = cashflow_analysis("sh600519", period, limit)
    return json.loads(resp.body)


def test_basic_merge_and_indicators():
    body = _call(
        [_income_row(dt.date(2024, 12, 31)),
         _income_row(dt.date(2025, 12, 31))],
        [_cashflow_row(dt.date(2024, 12, 31)),
         _cashflow_row(dt.date(2025, 12, 31))],
    )
    assert body["code"] == 0
    data = body["data"]
    assert [p["report_date"] for p in data["periods"]] == [
        "2025-12-31", "2024-12-31",
    ]
    assert [g["key"] for g in data["groups"]] == [
        "profit_quality", "growth", "structure",
    ]
    latest = data["periods"][0]
    assert latest["ratios"]["ocf_to_profit"] == pytest.approx(1.3)
    assert latest["ratios"]["cash_to_revenue"] == pytest.approx(1.05)
    assert latest["ratios"]["fcf_margin"] == pytest.approx(22.0)
    assert latest["ratios"]["financing"] == pytest.approx(-10.0)
    assert latest["values"]["ocf"] == pytest.approx(52.0)


def test_inner_join_skips_mismatched_dates():
    body = _call(
        [_income_row(dt.date(2024, 12, 31)),
         _income_row(dt.date(2025, 12, 31))],
        [_cashflow_row(dt.date(2025, 12, 31))],  # cashflow 只有 2025
    )
    assert [p["report_date"] for p in body["data"]["periods"]] == \
        ["2025-12-31"]


def test_year_filter_and_limit():
    income = [
        _income_row(dt.date(2024, 12, 31)),
        _income_row(dt.date(2025, 6, 30)),
        _income_row(dt.date(2025, 12, 31)),
    ]
    cashflow = [
        _cashflow_row(dt.date(2024, 12, 31)),
        _cashflow_row(dt.date(2025, 6, 30)),
        _cashflow_row(dt.date(2025, 12, 31)),
    ]
    body = _call(income, cashflow, period="year", limit=1)
    assert [p["report_date"] for p in body["data"]["periods"]] == \
        ["2025-12-31"]


def test_no_income_error():
    assert _call([], [_cashflow_row(dt.date(2025, 12, 31))])["code"] != 0


def test_no_cashflow_error():
    assert _call([_income_row(dt.date(2025, 12, 31))], [])["code"] != 0


def test_route_path_registered_and_distinct():
    """现金流分析路由须用独立路径 /cashflow-analysis——router:477 遗留
    /ratios 遮蔽教训（FastAPI 同路径先注册优先），必须回归测试。"""
    from src.api.router.financial_router import router
    paths = [r.path for r in router.routes]
    assert "/financial/cashflow-analysis/{symbol}" in paths
    assert paths.count("/financial/cashflow-analysis/{symbol}") == 1
    # 既有端点不受影响
    assert "/financial/ratio-analysis/{symbol}" in paths
    assert "/financial/ratios/{symbol}" in paths
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_cashflow_analysis.py -q`
Expected: FAIL（`ImportError: cannot import name 'cashflow_analysis'`）

- [ ] **Step 3: 实现 handler**

在 `backend/src/api/handler/financial_detail_handler.py` 文件末尾（`ratios`
函数之后，当前 line 1897 后）追加：

```python
def cashflow_analysis(symbol: str, period: str = "month",
                      limit: int = 12) -> Any:
    """现金流分析（Cashflow Analysis）：11 个现金流指标多期时序。

    三组：盈利质量（净现比/收现比/FCF率）、增长趋势（OCF/FCF/净利同比）、
    现金流结构（经营/投资/筹资净额、资本开支、资本开支强度）。

    口径：报告期累计不年化；同比需去年同期在场。取数：income+cashflow
    两表按 report_date 内连接（不涉及 balance）。fcf 列=筹资活动净额
    （非自由现金流）；FCF 用 free_cash_flow 列，缺列时兜底 ocf-|capex|。
    先在全量历史上计算（同比需要前序期），再截最近 limit 期。

    Args:
        symbol: sh600519 / 00700 / AAPL
        period: month=原始报告期累计口径（默认）；year=只看年报期
        limit:  返回最近 N 期（默认 12）
    """
    from src.domain.market.fundamental.cashflow_analysis import (
        FIXED_FIELDS,
        cashflow_series,
    )
    from src.infra.database.market.financial_full import (
        create_financial_detail_repository,
    )
    repo = create_financial_detail_repository()
    try:
        income_rows = repo.get_history(symbol, "income")
        cashflow_rows = repo.get_history(symbol, "cashflow")
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not income_rows or not cashflow_rows:
        return responses.error(f"无 {symbol} 财务报表数据")

    cashflow_by_date = {r.report_date: r for r in cashflow_rows}
    records: list[dict] = []
    for r in income_rows:
        c = cashflow_by_date.get(r.report_date)
        if c is None:
            continue  # 内连接：两表同报告期才计算
        fin = {}
        for f in sorted(FIXED_FIELDS):
            v = getattr(r, f, None)
            fin[f] = v if v is not None else getattr(c, f, None)
        records.append({
            "report_date": r.report_date,
            "fin": fin,
            # cashflow detail 在前：cash_from_sales 候选优先查现金流量表
            "details": [getattr(c, "detail", None),
                        getattr(r, "detail", None)],
        })
    if period == "year":
        records = filter_year_only(records)

    result = cashflow_series(records)
    data = {
        "symbol": symbol,
        "total_periods": len(records),
        "groups": result["groups"],
        "periods": result["periods"][:limit],  # 已降序，截最新 N 期
    }
    if not data["periods"]:
        data["note"] = "无可用报告期（income 与 cashflow 报告期无交集）"
    return responses.success(data)
```

（注：`records` 为空时 `cashflow_series` 返回空 periods，走 note 分支，
无需单独报错。）

- [ ] **Step 4: 注册路由**

`backend/src/api/router/financial_router.py` line 752 导入列表，在
`ratios,` 之后加一行 `cashflow_analysis,`：

```python
    common_size,
    ratios,
    cashflow_analysis,
)
```

文件末尾（`_ratio_analysis` 路由之后）追加：

```python
@router.get("/cashflow-analysis/{symbol}")
def _cashflow_analysis(
    symbol: str,
    period: str = Query("month", description="month=原始累计口径;year=年报期"),
    limit: int = Query(12, ge=1, le=60, description="返回最近 N 期"),
):
    """现金流分析：11 个现金流指标（盈利质量/增长趋势/现金流结构）多期矩阵。

    独立路径——已核实与既有 31 条路径零冲突（router:477 遮蔽教训）。
    """
    return cashflow_analysis(symbol, period, limit)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_cashflow_analysis.py -q`
Expected: PASS（6 个）

- [ ] **Step 6: lint 并提交**

```bash
cd backend && uv run flake8 src/api/handler/financial_detail_handler.py src/api/router/financial_router.py tests/api/test_cashflow_analysis.py
git add backend/src/api/handler/financial_detail_handler.py backend/src/api/router/financial_router.py backend/tests/api/test_cashflow_analysis.py
git commit -m "feat(cashflow-analysis): /financial/cashflow-analysis 端点——income+cashflow内连接+先算后截(handler+路由+mock测试+路径回归)"
```

---

### Task 4: 前端——hook + Panel + Tab 注册

**Files:**
- Create: `frontend/apps/web/src/hooks/useCashflowAnalysis.ts`
- Create: `frontend/apps/web/src/components/CashflowAnalysisPanel.tsx`
- Modify: `frontend/apps/web/src/pages/Financial.tsx`（4 处：line 25 import、line 244 TabType、line 1108 tabs、line 1262 render）

**Interfaces:**
- Consumes: Task 3 的 `GET /api/v1/financial/cashflow-analysis/{symbol}`
  响应结构（`{code, msg, data: {symbol, total_periods, groups, periods,
  note?}}`）；`StateView`（`components/ui`）、`chartTheme` 令牌、
  `fin-period-switcher`/`fin-table`/`fin-chart-card` CSS 类（Financial.css）。
- Produces: `useCashflowAnalysis(symbol, periodMode, limit)` →
  `{data, loading, error}`；`CashflowAnalysisPanel`
  （`React.FC<{symbol: string | null}>`）。

- [ ] **Step 1: 创建 hook `src/hooks/useCashflowAnalysis.ts`**

```typescript
/**
 * 现金流分析（cashflow analysis）数据 hook。
 *
 * 调用 GET /financial/cashflow-analysis/{symbol}，
 * 11 个现金流指标（盈利质量/增长趋势/现金流结构）多期时序。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export type CashflowUnit = 'pct' | 'x' | 'growth' | 'yi';

export interface CashflowMeta {
  key: string;
  label: string;
  unit: CashflowUnit;
  formula: string;
}

export interface CashflowGroup {
  key: string;
  label: string;
  ratios: CashflowMeta[];
}

export interface CashflowPeriod {
  report_date: string;
  values: Record<string, number | null>;
  ratios: Record<string, number | null>;
}

export interface CashflowData {
  symbol: string;
  total_periods: number;
  groups: CashflowGroup[];
  periods: CashflowPeriod[];
  note?: string;
}

export type CashflowPeriodMode = 'month' | 'year';

export function useCashflowAnalysis(
  symbol: string | null,
  periodMode: CashflowPeriodMode,
  limit = 12,
) {
  const [data, setData] = useState<CashflowData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams({
      period: periodMode,
      limit: String(limit),
    });
    fetch(
      `${API_BASE}/financial/cashflow-analysis/${symbol}?${qs.toString()}`,
    )
      .then((r) => r.json())
      .then((json) => {
        if (cancelled) return;
        if (json.code === 0) {
          setData(json.data);
        } else {
          setError(json.msg || '请求失败');
          setData(null);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, periodMode, limit]);

  return { data, loading, error };
}
```

- [ ] **Step 2: 创建组件 `src/components/CashflowAnalysisPanel.tsx`**

```tsx
/**
 * CashflowAnalysisPanel —— 现金流分析（Cashflow Analysis）面板。
 *
 * 11 个现金流指标三分组矩阵（行=指标、列=报告期，最新期在前），
 * 附"Δ较上期"变动列；点击指标行查看该指标趋势图。
 * 指标无 A股涨跌语义，Δ 用中性色（升蓝/降灰）。
 * 绝对额（yi 单位）API 传原始元、显示层转亿。
 */
import React, { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { StateView } from './ui';
import { useCashflowAnalysis } from '../hooks/useCashflowAnalysis';
import type {
  CashflowMeta,
  CashflowUnit,
} from '../hooks/useCashflowAnalysis';
import {
  CHART_COLORS,
  axisProps,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';

const fmtVal = (v: number | null | undefined, unit: CashflowUnit) => {
  if (v == null) return '—';
  if (unit === 'yi') return `${(v / 1e8).toFixed(2)}亿`;
  if (unit === 'pct') return `${v.toFixed(1)}%`;
  if (unit === 'growth') return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
  return v.toFixed(2);
};

const fmtDelta = (d: number | null, unit: CashflowUnit) => {
  if (d == null) return '—';
  if (unit === 'yi') return `${d > 0 ? '+' : ''}${(d / 1e8).toFixed(2)}亿`;
  if (unit === 'x') return `${d > 0 ? '+' : ''}${d.toFixed(2)}`;
  return `${d > 0 ? '+' : ''}${d.toFixed(1)}pp`;
};

export const CashflowAnalysisPanel: React.FC<{
  symbol: string | null;
}> = ({ symbol }) => {
  const [periodMode, setPeriodMode] = useState<'month' | 'year'>('month');
  const [selected, setSelected] = useState<string | null>(null);
  const { data, loading, error } = useCashflowAnalysis(symbol, periodMode);

  const dates = useMemo(
    () => (data?.periods ?? []).map((p) => p.report_date),
    [data],
  );
  const metaByKey = useMemo(() => {
    const m = new Map<string, CashflowMeta>();
    for (const g of data?.groups ?? []) {
      for (const r of g.ratios) m.set(r.key, r);
    }
    return m;
  }, [data]);

  // 趋势图数据：时间升序（从最早到最新）
  const chartData = useMemo(() => {
    if (!selected || !data) return [];
    return data.periods
      .slice()
      .reverse()
      .map((p) => ({
        label: p.report_date.slice(2, 7),
        value: p.ratios[selected] ?? null,
      }));
  }, [data, selected]);

  const selMeta = selected ? metaByKey.get(selected) : undefined;

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="error" text={error} />;
  // periods 缺失（如响应形状不符）时降级为空态，而非渲染崩溃
  if (!data || !data.periods?.length)
    return (
      <StateView state="empty" text={data?.note || '暂无现金流分析数据'} />
    );

  return (
    <div className="fin-chart-card">
      <div
        style={{
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          flexWrap: 'wrap',
          marginBottom: 12,
        }}
      >
        <div className="fin-period-switcher">
          {([['month', '累计'], ['year', '年报']] as const).map(
            ([k, l]) => (
              <button
                key={k}
                className={`fin-period-switcher__btn ${periodMode === k ? 'is-active' : ''}`}
                onClick={() => setPeriodMode(k)}
              >
                {l}
              </button>
            ),
          )}
        </div>
        <span style={{ fontSize: 12, color: '#a1a1a6' }}>
          口径：报告期累计未年化；FCF=经营净额-|资本开支|；筹资净额≠自由现金流
        </span>
      </div>

      <div className="fin-table-wrap">
        <table className="fin-table">
          <thead>
            <tr>
              <th>指标（{data.periods.length} 期）</th>
              {dates.map((d) => (
                <th key={d}>{d.slice(2)}</th>
              ))}
              <th>Δ较上期</th>
            </tr>
          </thead>
          <tbody>
            {data.groups.map((g) => (
              <React.Fragment key={g.key}>
                <tr>
                  <td
                    colSpan={dates.length + 2}
                    style={{
                      fontWeight: 600,
                      color: '#79c0ff',
                      background: 'rgba(121,192,255,0.06)',
                    }}
                  >
                    {g.label}
                  </td>
                </tr>
                {g.ratios.map((m) => {
                  const vals = data.periods.map(
                    (p) => p.ratios[m.key] ?? null,
                  );
                  const delta =
                    vals[0] != null && vals[1] != null
                      ? vals[0]! - vals[1]!
                      : null;
                  return (
                    <tr
                      key={m.key}
                      style={{ cursor: 'pointer' }}
                      title={m.formula}
                      onClick={() =>
                        setSelected(selected === m.key ? null : m.key)
                      }
                    >
                      <td style={{ paddingLeft: 24 }}>{m.label}</td>
                      {vals.map((v, i) => (
                        <td key={i}>{fmtVal(v, m.unit)}</td>
                      ))}
                      <td
                        style={{
                          color:
                            delta == null
                              ? undefined
                              : delta >= 0
                                ? '#79c0ff'
                                : '#a1a1a6',
                        }}
                      >
                        {fmtDelta(delta, m.unit)}
                      </td>
                    </tr>
                  );
                })}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {selected && chartData.length > 0 && selMeta && (
        <div style={{ marginTop: 16 }}>
          <h3 className="fin-chart-card__title">
            {selMeta.label} · 趋势
            {selMeta.unit === 'yi'
              ? '（亿元）'
              : selMeta.unit === 'x'
                ? ''
                : '（%）'}
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={chartData}
              margin={{ top: 10, right: 10, left: 0, bottom: 5 }}
            >
              <CartesianGrid {...gridProps} />
              <XAxis
                dataKey="label"
                {...axisProps}
                interval="preserveStartEnd"
              />
              <YAxis
                {...axisProps}
                tickFormatter={(v: number) =>
                  selMeta.unit === 'yi'
                    ? `${(v / 1e8).toFixed(0)}亿`
                    : selMeta.unit === 'x'
                      ? String(v)
                      : `${v}%`
                }
              />
              <Tooltip
                {...tooltipProps}
                formatter={(v: number) => [
                  fmtVal(v, selMeta.unit),
                  selMeta.label,
                ]}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="value"
                name={selMeta.label}
                stroke={CHART_COLORS[1]}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 3: 注册到 Financial.tsx（4 处 Edit）**

1) line 25（`import { RatiosPanel } ...` 之后）加一行：

```tsx
import { CashflowAnalysisPanel } from '../components/CashflowAnalysisPanel';
```

2) line 244 TabType（在 `'ratios'` 后插入 `'cashflowanalysis'`）：

```tsx
type TabType = 'summary' | 'income' | 'balance' | 'cashflow' | 'commonsize' | 'ratios' | 'cashflowanalysis' | 'forecast' | 'compare' | 'valuation' | 'dcf' | 'fundamental';
```

3) line 1108 tabs 数组（比率分析之后加）：

```tsx
    { key: 'ratios', label: '比率分析' },
    { key: 'cashflowanalysis', label: '现金流分析' },
```

4) line 1262 render（比率分析之后加）：

```tsx
        {activeTab === 'ratios' && <RatiosPanel symbol={symbol} />}
        {activeTab === 'cashflowanalysis' && (
          <CashflowAnalysisPanel symbol={symbol} />
        )}
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && pnpm -F web build`
Expected: 构建成功，无 TypeScript 错误。

- [ ] **Step 5: 提交**

```bash
git add frontend/apps/web/src/hooks/useCashflowAnalysis.ts frontend/apps/web/src/components/CashflowAnalysisPanel.tsx frontend/apps/web/src/pages/Financial.tsx
git commit -m "feat(cashflow-analysis): 现金流分析Tab——三分组矩阵+Δ较上期+行点击趋势图(useCashflowAnalysis+CashflowAnalysisPanel)"
```

---

### Task 5: 全量回归 + 冒烟验证

**Files:** 无新文件（只读验证）。

**Interfaces:**
- Consumes: Task 1-4 全部产物。

- [ ] **Step 1: 后端定向回归**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_cashflow_analysis.py tests/api/test_cashflow_analysis.py tests/domain/market/fundamental/test_ratio_analysis.py tests/api/test_ratios.py tests/api/test_common_size.py -q`
Expected: 全部 PASS（新旧模块互不影响）。

- [ ] **Step 2: 后端全量回归（与既有失败基线对照）**

Run: `cd backend && uv run pytest tests/ -q 2>&1 | tail -5`
Expected: 新增测试全过；失败/收集错误数 **不高于既有基线**（历史遗留 52 失败 + 6 收集错误，见项目记忆）。若出现新增失败，定位修复后再继续。

- [ ] **Step 3: A 股真库冒烟（茅台）**

Run（若数据库不可用则记录跳过原因，不阻塞）:

```bash
cd backend && uv run python -c "
from src.infra.database.market.financial_full import (
    create_financial_detail_repository,
)
from src.domain.market.fundamental.cashflow_analysis import cashflow_series
repo = create_financial_detail_repository()
inc = repo.get_history('sh600519', 'income')
cf = repo.get_history('sh600519', 'cashflow')
by_date = {r.report_date: r for r in cf}
records = []
for r in inc:
    c = by_date.get(r.report_date)
    if c is None:
        continue
    fin = {}
    for f in ('revenue', 'net_profit', 'ocf', 'icf', 'fcf', 'capex',
              'free_cash_flow', 'cash_end'):
        v = getattr(r, f, None)
        fin[f] = v if v is not None else getattr(c, f, None)
    records.append({'report_date': r.report_date, 'fin': fin,
                    'details': [c.detail, r.detail]})
out = cashflow_series(records)
p = out['periods'][0]
print('茅台最新期', p['report_date'])
for k in ('ocf_to_profit', 'cash_to_revenue', 'fcf_margin',
          'ocf_yoy', 'financing', 'capex_to_ocf'):
    print(f'  {k} = {p[\"ratios\"][k]}')
"
```

Expected: 最新期为最近报告期；净现比通常 > 0（白酒预收/经销商打款模式常年 > 1，
属正常）；收现比 ≈ 1.0-1.2（增值税销项使销售收现略高于营收）；fcf_margin 为
正；financing 与 ocf/icf 量级合理。异常值需能解释（如 None 需说明缺列原因）。

- [ ] **Step 4: 港股真库冒烟（腾讯）**

同 Step 3，symbol 换 `00700`（若库里是 `hk00700` 则先
`repo.get_history('hk00700', 'income')` 探测）。重点核对：ocf/icf/fcf
固定列命中（东财 _HK_CASHFLOW_MAP 摄取）；`cash_from_sales` 港股普遍
缺科目 → 收现比 None 属预期优雅降级；free_cash_flow 列缺失时兜底
`ocf - abs(capex)` 是否生效（HK capex 候选"购买物业、厂房及设备"）。
记录实际命中情况到提交信息。

- [ ] **Step 5: 前端构建（若 Task 4 后有改动则复跑）**

Run: `cd frontend && pnpm -F web build`
Expected: 成功。

- [ ] **Step 6: 冒烟结论提交（空提交记录验证结果）**

```bash
git commit --allow-empty -m "chore(cashflow-analysis): 冒烟验证——茅台净现比/收现比口径吻合;腾讯港股收现比None属预期降级<填实测>"
```

---

## Self-Review 记录

1. **Spec coverage**：spec §后端设计-1（模块/两函数/11 指标元数据/fcf 陷阱/abs 防御）→ Task 1/2；§后端设计-2（handler/内连接/先算后截/note）→ Task 3；§后端设计-3（独立路径 + 注册回归测试）→ Task 3 Step 1/4；§前端设计-4/5/6（hook/Panel/Tab 四处注册/yi 单位转亿）→ Task 4；§错误处理（除零守卫/净利≤0/科目缺失/periods 纵深防御）→ Task 2 测试 + Task 4 `periods?.length`；§测试（纯函数 + mock handler + 路由回归）→ Task 1/2/3；§预估验证 → Task 5。无遗漏。
2. **Placeholder scan**：无 TBD/TODO；Task 5 Step 6 的 `<填实测>` 是执行时才能得出的冒烟结论占位，属预期。
3. **Type consistency**：`cashflow_series` 输出键（groups/periods/report_date/values/ratios）与 Task 3 data 组装、Task 4 `CashflowData` 类型一致；`FIXED_FIELDS`/`resolve_cashflow_fields` 签名 Task 1 定义、Task 3 消费一致；前端 `CashflowUnit = 'pct'|'x'|'growth'|'yi'` 与后端 CASHFLOW_META unit 取值一致；指标键名三组 11 个在 Global Constraints、Task 1 元数据、Task 2 计算字典、Task 3 测试断言四处一致。
4. **MagicMock 陷阱（执行者注意）**：handler 测试的行构造器必须显式 `setattr` 另一表的固定列为 `None`——MagicMock 的自动属性会让 `getattr(r, 'ocf')` 返回 mock 对象（非 None），使固定列合并取到 mock、吞掉 cashflow 行的真实值，断言静默失败（test_ratios.py 靠 detail 候选兜底侥幸绕过，本功能的 ocf_to_profit 直接依赖固定列，绕不过）。
