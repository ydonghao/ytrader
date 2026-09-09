# 比率分析（Ratio Analysis）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在财务报表功能中新增"比率分析"Tab：后端纯函数计算 14 个核心财务比率（盈利/偿债/营运/成长四组）多期时序 + API 端点 + 前端分组矩阵与趋势图。

**Architecture:** 镜像 common-size 范式——`src/domain/market/fundamental/ratio_analysis.py` 纯函数（dict 进 dict 出、不读 DB、缺 key 返 None）→ `financial_detail_handler.ratios`（income+balance 两表按 report_date 内连接、**先全量计算再截 limit**）→ `GET /financial/ratios/{symbol}` → `useRatios` hook + `RatiosPanel` 组件 + Financial.tsx Tab 注册。

**Tech Stack:** Python 3.11 + FastAPI + SQLModel（后端）；React + recharts + pnpm/Rush monorepo（前端）。

## Global Constraints

- 设计文档：`docs/superpowers/specs/2026-08-18-ratio-analysis-design.md`（口径以它为准）。
- 口径：全部比率报告期累计、不年化；ROE/ROA/三周转率分母 =（期初+期末）÷2（首期缺期初 → None）；同比需去年同期在场且基数 > 0；任一分母缺失/≤0 → None 不抛异常；结果 round(x, 4)。
- 14 比率四分组（键名固定）：profitability= gross_margin/net_margin/roe/roa；solvency= debt_ratio/current_ratio/quick_ratio/interest_cover；efficiency= inventory_turnover/receivable_turnover/asset_turnover；growth= revenue_growth/profit_growth/asset_growth。
- 后端代码风格：flake8 max-line-length 79、ignore E203/W503；black/isort line-length 79。纯函数模块顶部写中文 docstring（方法论+口径）。
- 前端代码风格：对齐 `CommonSizePanel.tsx`/`useCommonSize.ts`；图表用 recharts + `src/lib/chartTheme.ts` 令牌；Δ列中性配色升 `#79c0ff` 降 `#a1a1a6`（无涨跌语义）。
- 测试运行：后端 `cd backend && uv run pytest <path> -q`；前端 `cd frontend && pnpm -F web build`（无前端单测框架）。
- 不改存量 Tab 与既有端点；不动工作区中与本功能无关的未提交改动（backend/tests/api/test_valuation_percentile_exclude.py 等）。
- 每个任务一个 commit，消息格式对齐近期提交（`feat(ratio-analysis): ...`）。

---

### Task 1: 纯函数模块——元数据 + 字段解析 `resolve_metric_fields`

**Files:**
- Create: `backend/src/domain/market/fundamental/ratio_analysis.py`
- Test: `backend/tests/domain/market/fundamental/test_ratio_analysis.py`

**Interfaces:**
- Consumes: `src.infra.database.market.financial_full.parse_amount`（try-import + 本地兜底，模式抄 common_size.py:23-42）。
- Produces（Task 2/3 依赖）:
  - `GROUPS: list[dict]`、`RATIO_META: list[dict]`（key/label/group/unit/formula）
  - `ALL_FIELDS: list[str]`（13 个语义字段）
  - `FIXED_FIELDS: frozenset[str]`（9 个有英文固定列的语义字段）
  - `DETAIL_CANDIDATES: dict[str, list[str]]`
  - `resolve_metric_fields(fin: dict, details: list) -> dict[str, float | None]`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/domain/market/fundamental/test_ratio_analysis.py`：

```python
"""比率分析纯函数测试。镜像 test_common_size.py 风格。"""
import datetime as dt

import pytest

from src.domain.market.fundamental.ratio_analysis import (
    ALL_FIELDS,
    RATIO_META,
    resolve_metric_fields,
)


class TestResolveMetricFields:
    def test_fixed_column_takes_priority(self):
        # 固定列非 None 应压过 detail 候选
        out = resolve_metric_fields({"revenue": 100.0}, [{"一、营业总收入": 999.0}])
        assert out["revenue"] == 100.0

    def test_detail_candidate_across_details(self):
        # 第一个 detail 无该科目 → 继续在第二个 detail 中找
        out = resolve_metric_fields({}, [{"无关": 1.0}, {"*流动资产合计": 80.0}])
        assert out["current_assets"] == 80.0

    def test_string_amount_parsed(self):
        out = resolve_metric_fields({}, [{"流动负债合计": "5亿"}])
        assert out["current_liabilities"] == pytest.approx(5e8)

    def test_hk_candidates(self):
        # 港股东财科目名：营业额 / 除税前溢利 / 权益总额
        out = resolve_metric_fields(
            {}, [{"营业额": 300.0, "除税前溢利": 50.0}, {"权益总额": 150.0}]
        )
        assert out["revenue"] == 300.0
        assert out["ebt"] == 50.0
        assert out["equity"] == 150.0

    def test_missing_returns_none(self):
        out = resolve_metric_fields({}, [{}])
        for f in ALL_FIELDS:
            assert out[f] is None

    def test_none_details_tolerated(self):
        out = resolve_metric_fields({"revenue": 1.0}, None)
        assert out["revenue"] == 1.0
        assert out["current_assets"] is None

    def test_meta_completeness(self):
        assert len(RATIO_META) == 14
        groups = {m["group"] for m in RATIO_META}
        assert groups == {"profitability", "solvency", "efficiency", "growth"}
        for m in RATIO_META:
            assert m["unit"] in ("pct", "x", "growth")
            assert m["formula"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py -q`
Expected: FAIL（`ModuleNotFoundError: ... ratio_analysis`）

- [ ] **Step 3: 写最小实现**

创建 `backend/src/domain/market/fundamental/ratio_analysis.py`：

```python
"""比率分析（Ratio Analysis）纯函数。

跨报表计算 14 个核心财务比率，四组：
  - profitability 盈利能力：毛利率 / 净利率 / ROE / ROA
  - solvency     偿债能力：资产负债率 / 流动比率 / 速动比率 / 利息保障倍数
  - efficiency   营运能力：存货 / 应收账款 / 总资产周转率
  - growth       成长能力：营收 / 净利润 / 总资产同比增长率

口径约定（对齐 common_size.py / quality.py）：缺失/分母 ≤ 0 → None 不抛异常；
全部比率按报告期累计、不年化（Q3 报表算出的 ROE 即"前三季 ROE"）；
ROE/ROA/周转率分母 = 期初期末平均余额（首期缺期初 → None）；
同比需去年同期在场且基数 > 0（负基数同比无意义）。

字段解析：英文固定列（stock_financial_detail 列）非 None 优先，否则按中文
候选名在 details（income/balance 两表 detail JSONB）中匹配，parse_amount 解析。
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


# ── 分组与比率元数据（groups 随 API 下发，前端不重复维护定义）──
GROUPS: list[dict] = [
    {"key": "profitability", "label": "盈利能力"},
    {"key": "solvency", "label": "偿债能力"},
    {"key": "efficiency", "label": "营运能力"},
    {"key": "growth", "label": "成长能力"},
]

RATIO_META: list[dict] = [
    {"key": "gross_margin", "label": "毛利率", "group": "profitability",
     "unit": "pct", "formula": "(营业总收入-营业成本)/营业总收入"},
    {"key": "net_margin", "label": "净利率", "group": "profitability",
     "unit": "pct", "formula": "净利润/营业总收入"},
    {"key": "roe", "label": "ROE", "group": "profitability",
     "unit": "pct", "formula": "净利润/平均净资产"},
    {"key": "roa", "label": "ROA", "group": "profitability",
     "unit": "pct", "formula": "净利润/平均总资产"},
    {"key": "debt_ratio", "label": "资产负债率", "group": "solvency",
     "unit": "pct", "formula": "总负债/总资产"},
    {"key": "current_ratio", "label": "流动比率", "group": "solvency",
     "unit": "x", "formula": "流动资产合计/流动负债合计"},
    {"key": "quick_ratio", "label": "速动比率", "group": "solvency",
     "unit": "x", "formula": "(流动资产合计-存货)/流动负债合计"},
    {"key": "interest_cover", "label": "利息保障倍数", "group": "solvency",
     "unit": "x",
     "formula": "EBIT/利息费用（EBIT≈利润总额，缺则营业利润；利息费用候选："
                "利息费用/利息支出/财务费用）"},
    {"key": "inventory_turnover", "label": "存货周转率", "group": "efficiency",
     "unit": "x", "formula": "营业成本/平均存货（累计口径未年化）"},
    {"key": "receivable_turnover", "label": "应收账款周转率",
     "group": "efficiency", "unit": "x",
     "formula": "营业总收入/平均应收账款（累计口径未年化）"},
    {"key": "asset_turnover", "label": "总资产周转率", "group": "efficiency",
     "unit": "x", "formula": "营业总收入/平均总资产（累计口径未年化）"},
    {"key": "revenue_growth", "label": "营收增长率", "group": "growth",
     "unit": "growth", "formula": "营业总收入同比-1"},
    {"key": "profit_growth", "label": "净利润增长率", "group": "growth",
     "unit": "growth", "formula": "净利润同比-1"},
    {"key": "asset_growth", "label": "总资产增长率", "group": "growth",
     "unit": "growth", "formula": "总资产同比-1"},
]

# detail 中文候选名（A 股同花顺在前、港股东财在后；'*' 前缀为同花顺重述科目）
DETAIL_CANDIDATES: dict[str, list[str]] = {
    "revenue": ["一、营业总收入", "*营业总收入", "营业收入", "营业额", "营业收益"],
    "operating_cost": ["其中：营业成本", "营业成本", "营运支出", "销售成本"],
    "net_profit": ["五、净利润", "*净利润", "除税后溢利"],
    "operating_profit": ["三、营业利润", "*营业利润", "经营溢利"],
    "total_assets": ["*资产合计", "资产合计", "总资产", "资产总额"],
    "total_liabilities": ["*负债合计", "负债合计", "总负债", "负债总额"],
    "equity": ["所有者权益（或股东权益）合计",
               "*所有者权益（或股东权益）合计", "权益总额", "所有者权益合计"],
    "inventory": ["存货", "库存"],
    "accounts_receivable": ["应收账款", "贸易及其他应收款"],
    "current_assets": ["*流动资产合计", "流动资产合计", "流动资产总值"],
    "current_liabilities": ["*流动负债合计", "流动负债合计", "流动负债总值"],
    "ebt": ["利润总额", "*利润总额", "除税前溢利", "税前利润"],
    "interest_expense": ["其中：利息费用", "利息费用", "利息支出", "财务费用"],
}

ALL_FIELDS: list[str] = list(DETAIL_CANDIDATES.keys())

# 有英文固定列的语义字段（stock_financial_detail 列名与语义名一致）
FIXED_FIELDS: frozenset = frozenset({
    "revenue", "operating_cost", "net_profit", "operating_profit",
    "total_assets", "total_liabilities", "equity", "inventory",
    "accounts_receivable",
})


def _pick_amount(detail: dict, candidates: list[str]) -> Optional[float]:
    """按候选顺序取首个数值非 None 的科目（模式抄 common_size._pick_amount）。"""
    for k in candidates:
        if isinstance(detail, dict) and k in detail:
            v = parse_amount(detail.get(k))
            if v is not None:
                return v
    return None


def resolve_metric_fields(fin: dict, details: list) -> dict:
    """单期字段归一：固定列非 None 优先 → 两表 detail 候选名兜底。

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

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py -q`
Expected: PASS（8 个）

- [ ] **Step 5: lint 并提交**

```bash
cd backend && uv run flake8 src/domain/market/fundamental/ratio_analysis.py tests/domain/market/fundamental/test_ratio_analysis.py
git add backend/src/domain/market/fundamental/ratio_analysis.py backend/tests/domain/market/fundamental/test_ratio_analysis.py
git commit -m "feat(ratio-analysis): 纯函数模块——元数据+字段解析(固定列优先/detail中文候选兜底,8测试)"
```

---

### Task 2: 纯函数模块——`ratio_series` 多期比率计算

**Files:**
- Modify: `backend/src/domain/market/fundamental/ratio_analysis.py`（追加）
- Test: `backend/tests/domain/market/fundamental/test_ratio_analysis.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `resolve_metric_fields`/`RATIO_META`/`GROUPS`。
- Produces（Task 3 依赖）: `ratio_series(records: list[dict]) -> dict`
  - 输入升序 `[{report_date: date|str, fin: dict, details: list[dict|None]}]`
  - 输出 `{"groups": [{"key","label","ratios":[{key,label,unit,formula}]}],
    "periods": [{"report_date": iso, "values": {...}, "ratios": {key: float|None}}]}`
    periods 降序（最新在前）。

- [ ] **Step 1: 追加失败测试**

在 `test_ratio_analysis.py` 末尾追加：

```python
FIN_2024 = {
    "revenue": 100.0, "operating_cost": 40.0, "net_profit": 20.0,
    "operating_profit": 25.0, "total_assets": 200.0, "total_liabilities": 80.0,
    "equity": 120.0, "inventory": 20.0, "accounts_receivable": 30.0,
}
FIN_2025 = {k: v * 2 for k, v in FIN_2024.items()}


def _rec(date, fin=None, details=None):
    return {"report_date": date, "fin": fin or {}, "details": details or []}


class TestRatioSeries:
    def test_profitability_current_period(self):
        out = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025)])
        p = out["periods"][0]
        assert p["ratios"]["gross_margin"] == pytest.approx(60.0)  # (200-80)/200
        assert p["ratios"]["net_margin"] == pytest.approx(20.0)    # 40/200

    def test_solvency_from_details(self):
        details = [{"流动资产合计": 150.0, "流动负债合计": 100.0, "存货": 50.0}]
        out = ratio_series([_rec(dt.date(2025, 12, 31),
                                 {"total_assets": 300.0, "total_liabilities": 120.0},
                                 details)])
        p = out["periods"][0]
        assert p["ratios"]["debt_ratio"] == pytest.approx(40.0)
        assert p["ratios"]["current_ratio"] == pytest.approx(1.5)
        assert p["ratios"]["quick_ratio"] == pytest.approx(1.0)

    def test_interest_cover_ebt_preferred_then_fallback(self):
        out = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025,
                                 [{"利润总额": 60.0, "其中：利息费用": 6.0}])])
        assert out["periods"][0]["ratios"]["interest_cover"] == pytest.approx(10.0)
        # 利润总额缺失 → 营业利润(50)近似；利息费用候选落到"利息支出"
        out2 = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025,
                                  [{"利息支出": 5.0}])])
        assert out2["periods"][0]["ratios"]["interest_cover"] == pytest.approx(10.0)

    def test_average_balance_and_first_period_none(self):
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        first, latest = out["periods"][-1], out["periods"][0]  # 降序
        assert first["ratios"]["roe"] is None                  # 首期无期初
        assert first["ratios"]["asset_turnover"] is None
        assert latest["ratios"]["roe"] == pytest.approx(40.0 / 150.0 * 100)
        assert latest["ratios"]["asset_turnover"] == pytest.approx(200.0 / 300.0)
        assert latest["ratios"]["inventory_turnover"] == pytest.approx(80.0 / 30.0)

    def test_yoy_growth(self):
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        latest = out["periods"][0]
        assert latest["ratios"]["revenue_growth"] == pytest.approx(100.0)
        assert latest["ratios"]["asset_growth"] == pytest.approx(100.0)

    def test_yoy_missing_or_nonpositive_base(self):
        fin_bad = dict(FIN_2024)
        fin_bad["net_profit"] = -5.0
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), fin_bad),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        assert out["periods"][0]["ratios"]["profit_growth"] is None
        # 无去年同期在场
        out2 = ratio_series([_rec(dt.date(2025, 12, 31), FIN_2025)])
        assert out2["periods"][0]["ratios"]["revenue_growth"] is None

    def test_division_guards(self):
        fin = dict(FIN_2024)
        fin["revenue"] = 0.0
        fin["operating_cost"] = None
        out = ratio_series([_rec(dt.date(2025, 12, 31), fin)])
        r = out["periods"][0]["ratios"]
        assert r["gross_margin"] is None   # 营业成本缺失（金融股）
        assert r["net_margin"] is None     # 收入为 0

    def test_descending_groups_and_values(self):
        out = ratio_series([
            _rec(dt.date(2024, 12, 31), FIN_2024),
            _rec(dt.date(2025, 12, 31), FIN_2025),
        ])
        assert [p["report_date"] for p in out["periods"]] == [
            "2025-12-31", "2024-12-31",
        ]
        assert [g["key"] for g in out["groups"]] == [
            "profitability", "solvency", "efficiency", "growth",
        ]
        keys = [m["key"] for g in out["groups"] for m in g["ratios"]]
        assert set(keys) == {m["key"] for m in RATIO_META}
        assert out["periods"][0]["values"]["revenue"] == pytest.approx(200.0)

    def test_string_report_date(self):
        out = ratio_series([_rec("2025-12-31", FIN_2024)])
        assert out["periods"][0]["report_date"] == "2025-12-31"
```

同时在文件顶部 import 中加入 `ratio_series`：

```python
from src.domain.market.fundamental.ratio_analysis import (
    ALL_FIELDS,
    RATIO_META,
    ratio_series,
    resolve_metric_fields,
)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py -q`
Expected: FAIL（`ImportError: cannot import name 'ratio_series'`）

- [ ] **Step 3: 在 ratio_analysis.py 末尾追加实现**

```python
def _div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """安全除：任一为 None 或分母 ≤ 0 → None；round 4。"""
    if num is None or den is None or den <= 0:
        return None
    return round(num / den, 4)


def _sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def _avg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return (a + b) / 2.0


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
                for m in RATIO_META if m["group"] == g["key"]
            ],
        }
        for g in GROUPS
    ]


def ratio_series(records: list[dict]) -> dict:
    """多期比率计算（14 比率 × 每期）。

    Args:
        records: 升序 ``[{report_date: date|str, fin: dict,
          details: list[dict|None]}]``（fin=两表固定列合并，
          details=[income_detail, balance_detail]）。
    Returns:
        ``{"groups": [...], "periods": [{"report_date", "values", "ratios"}]}``
        periods 降序（最新在前）。values=resolve_metric_fields 完整结果。
    """
    resolved: list[dict] = []
    for r in records or []:
        r = r or {}
        ds = _date_str(r.get("report_date"))
        if ds is None:
            continue
        resolved.append({
            "ds": ds,
            "values": resolve_metric_fields(r.get("fin"), r.get("details")),
        })
    by_ds = {p["ds"]: p["values"] for p in resolved}

    periods: list[dict] = []
    for i, p in enumerate(resolved):
        v = p["values"]
        prev = resolved[i - 1]["values"] if i > 0 else None
        last = by_ds.get(_year_ago(p["ds"]))

        def avg_prev(field: str) -> Optional[float]:
            return _avg(v.get(field), prev.get(field)) if prev else None

        def yoy(field: str) -> Optional[float]:
            if last is None:
                return None
            cur, base = v.get(field), last.get(field)
            if cur is None or base is None or base <= 0:
                return None
            return round((cur / base - 1) * 100, 4)

        ratios: dict[str, Optional[float]] = {
            # 盈利能力
            "gross_margin": _pct(_div(_sub(v.get("revenue"),
                                           v.get("operating_cost")),
                                      v.get("revenue"))),
            "net_margin": _pct(_div(v.get("net_profit"), v.get("revenue"))),
            "roe": _pct(_div(v.get("net_profit"), avg_prev("equity"))),
            "roa": _pct(_div(v.get("net_profit"),
                             avg_prev("total_assets"))),
            # 偿债能力
            "debt_ratio": _pct(_div(v.get("total_liabilities"),
                                    v.get("total_assets"))),
            "current_ratio": _div(v.get("current_assets"),
                                  v.get("current_liabilities")),
            "quick_ratio": _div(_sub(v.get("current_assets"),
                                     v.get("inventory")),
                                v.get("current_liabilities")),
            # EBIT≈利润总额（缺则营业利润）；利息费用候选含财务费用兜底
            "interest_cover": _div(
                v.get("ebt") if v.get("ebt") is not None
                else v.get("operating_profit"),
                v.get("interest_expense"),
            ),
            # 营运能力（累计口径未年化，分母平均余额）
            "inventory_turnover": _div(v.get("operating_cost"),
                                       avg_prev("inventory")),
            "receivable_turnover": _div(v.get("revenue"),
                                        avg_prev("accounts_receivable")),
            "asset_turnover": _div(v.get("revenue"),
                                   avg_prev("total_assets")),
            # 成长能力（同比）
            "revenue_growth": yoy("revenue"),
            "profit_growth": yoy("net_profit"),
            "asset_growth": yoy("total_assets"),
        }
        periods.append(
            {"report_date": p["ds"], "values": v, "ratios": ratios}
        )

    periods.reverse()
    return {"groups": _build_groups(), "periods": periods}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py -q`
Expected: PASS（17 个）

- [ ] **Step 5: lint 并提交**

```bash
cd backend && uv run flake8 src/domain/market/fundamental/ratio_analysis.py tests/domain/market/fundamental/test_ratio_analysis.py
git add backend/src/domain/market/fundamental/ratio_analysis.py backend/tests/domain/market/fundamental/test_ratio_analysis.py
git commit -m "feat(ratio-analysis): ratio_series——14比率四分组(平均余额/同比/除零守卫,9测试)"
```

---

### Task 3: Handler + 路由 + API 测试

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（文件末尾 `common_size` 之后追加 `ratios`；`filter_year_only` 已在模块顶部 line 17 导入）
- Modify: `backend/src/api/router/financial_router.py`（line 750 导入列表 + 文件末尾 line 1053 之后追加路由）
- Test: `backend/tests/api/test_ratios.py`

**Interfaces:**
- Consumes: Task 1 `FIXED_FIELDS`、Task 2 `ratio_series`；
  `create_financial_detail_repository().get_history(symbol, statement_type)`；
  `filter_year_only`（已在 handler 模块顶部导入）；`responses.success/error`。
- Produces: `ratios(symbol, period="month", limit=12) -> Any`（JSONResponse）；
  路由 `GET /api/v1/financial/ratios/{symbol}`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/api/test_ratios.py`：

```python
"""ratios 接口测试（mock repo，不发 HTTP）。模式抄 test_common_size.py。"""
import datetime as dt
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

INCOME_FIN = {
    "revenue": 100.0, "operating_cost": 40.0, "net_profit": 20.0,
    "operating_profit": 25.0,
}
BALANCE_FIN = {
    "total_assets": 200.0, "total_liabilities": 80.0, "equity": 120.0,
    "inventory": 20.0, "accounts_receivable": 30.0,
}


def _income_row(report_date):
    r = MagicMock()
    r.report_date = report_date
    r.detail = {"一、营业总收入": 100.0}
    for k, v in INCOME_FIN.items():
        setattr(r, k, v)
    return r


def _balance_row(report_date):
    r = MagicMock()
    r.report_date = report_date
    r.detail = {"流动资产合计": 150.0, "流动负债合计": 100.0}
    for k, v in BALANCE_FIN.items():
        setattr(r, k, v)
    return r


def _call(income_rows, balance_rows, period="month", limit=12):
    from src.api.handler.financial_detail_handler import ratios
    repo = MagicMock()
    repo.get_history.side_effect = (
        lambda sym, st: income_rows if st == "income" else balance_rows
    )
    with patch(
        "src.infra.database.market.financial_full"
        ".create_financial_detail_repository",
        return_value=repo,
    ):
        resp = ratios("sh600519", period, limit)
    return json.loads(resp.body)


def test_basic_merge_and_ratios():
    body = _call(
        [_income_row(dt.date(2024, 12, 31)), _income_row(dt.date(2025, 12, 31))],
        [_balance_row(dt.date(2024, 12, 31)), _balance_row(dt.date(2025, 12, 31))],
    )
    assert body["code"] == 0
    data = body["data"]
    assert [p["report_date"] for p in data["periods"]] == [
        "2025-12-31", "2024-12-31",
    ]
    assert [g["key"] for g in data["groups"]] == [
        "profitability", "solvency", "efficiency", "growth",
    ]
    latest = data["periods"][0]
    assert latest["ratios"]["gross_margin"] == pytest.approx(60.0)
    assert latest["ratios"]["current_ratio"] == pytest.approx(1.5)
    assert latest["ratios"]["revenue_growth"] == pytest.approx(0.0)  # 两年同值
    assert latest["values"]["revenue"] == pytest.approx(100.0)


def test_inner_join_skips_mismatched_dates():
    body = _call(
        [_income_row(dt.date(2024, 12, 31)), _income_row(dt.date(2025, 12, 31))],
        [_balance_row(dt.date(2025, 12, 31))],  # balance 只有 2025
    )
    assert [p["report_date"] for p in body["data"]["periods"]] == ["2025-12-31"]


def test_year_filter_and_limit():
    income = [
        _income_row(dt.date(2024, 12, 31)),
        _income_row(dt.date(2025, 6, 30)),
        _income_row(dt.date(2025, 12, 31)),
    ]
    balance = [
        _balance_row(dt.date(2024, 12, 31)),
        _balance_row(dt.date(2025, 6, 30)),
        _balance_row(dt.date(2025, 12, 31)),
    ]
    body = _call(income, balance, period="year", limit=1)
    assert [p["report_date"] for p in body["data"]["periods"]] == ["2025-12-31"]


def test_no_income_error():
    assert _call([], [_balance_row(dt.date(2025, 12, 31))])["code"] != 0


def test_no_balance_error():
    assert _call([_income_row(dt.date(2025, 12, 31))], [])["code"] != 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_ratios.py -q`
Expected: FAIL（`ImportError: cannot import name 'ratios'`）

- [ ] **Step 3: 实现 handler**

在 `backend/src/api/handler/financial_detail_handler.py` 文件末尾（`common_size`
函数之后）追加：

```python
def ratios(symbol: str, period: str = "month", limit: int = 12) -> Any:
    """比率分析（Ratio Analysis）：14 个核心财务比率多期时序。

    四组：盈利（毛利率/净利率/ROE/ROA）、偿债（资产负债率/流动/速动/利息保障）、
    营运（存货/应收/总资产周转）、成长（营收/净利/总资产同比）。

    口径：报告期累计不年化；ROE/ROA/周转率分母=期初期末平均余额；
    同比需去年同期在场。取数：income+balance 两表按 report_date 内连接
    （比率不涉及现金流量表）。先在全量历史上计算（平均余额/同比需要
    前序期），再截最近 limit 期——与 common-size 的"先截再算"相反。

    Args:
        symbol: sh600519 / 00700 / AAPL
        period: month=原始报告期累计口径（默认）；year=只看年报期
        limit:  返回最近 N 期（默认 12）
    """
    from src.domain.market.fundamental.ratio_analysis import (
        FIXED_FIELDS,
        ratio_series,
    )
    from src.infra.database.market.financial_full import (
        create_financial_detail_repository,
    )
    repo = create_financial_detail_repository()
    try:
        income_rows = repo.get_history(symbol, "income")
        balance_rows = repo.get_history(symbol, "balance")
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not income_rows or not balance_rows:
        return responses.error(f"无 {symbol} 财务报表数据")

    balance_by_date = {r.report_date: r for r in balance_rows}
    records: list[dict] = []
    for r in income_rows:
        b = balance_by_date.get(r.report_date)
        if b is None:
            continue  # 内连接：两表同报告期才计算
        fin = {}
        for f in sorted(FIXED_FIELDS):
            v = getattr(r, f, None)
            fin[f] = v if v is not None else getattr(b, f, None)
        records.append({
            "report_date": r.report_date,
            "fin": fin,
            "details": [getattr(r, "detail", None), getattr(b, "detail", None)],
        })
    if period == "year":
        records = filter_year_only(records)

    result = ratio_series(records)
    data = {
        "symbol": symbol,
        "total_periods": len(records),
        "groups": result["groups"],
        "periods": result["periods"][:limit],  # 已降序，截最新 N 期
    }
    if not data["periods"]:
        data["note"] = "无可用报告期（income 与 balance 报告期无交集）"
    return responses.success(data)
```

（注：`records` 为空时 `ratio_series` 返回空 periods，走 note 分支，无需单独报错。）

- [ ] **Step 4: 注册路由**

`backend/src/api/router/financial_router.py` line 750 的导入列表，把
`common_size,` 之后加一行 `ratios,`：

```python
    concentration_report,
    common_size,
    ratios,
)
```

文件末尾（`_common_size` 路由之后）追加：

```python
@router.get("/ratios/{symbol}")
def _ratios(
    symbol: str,
    period: str = Query("month", description="month=原始累计口径;year=年报期"),
    limit: int = Query(12, ge=1, le=60, description="返回最近 N 期"),
):
    """比率分析：14 个核心财务比率（盈利/偿债/营运/成长）多期矩阵。"""
    return ratios(symbol, period, limit)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_ratios.py -q`
Expected: PASS（5 个）

- [ ] **Step 6: lint 并提交**

```bash
cd backend && uv run flake8 src/api/handler/financial_detail_handler.py src/api/router/financial_router.py tests/api/test_ratios.py
git add backend/src/api/handler/financial_detail_handler.py backend/src/api/router/financial_router.py backend/tests/api/test_ratios.py
git commit -m "feat(ratio-analysis): /financial/ratios 端点——两表内连接+先算后截(handler+路由+mock测试)"
```

---

### Task 4: 前端——hook + Panel + Tab 注册

**Files:**
- Create: `frontend/apps/web/src/hooks/useRatios.ts`
- Create: `frontend/apps/web/src/components/RatiosPanel.tsx`
- Modify: `frontend/apps/web/src/pages/Financial.tsx`（4 处：line 24 import、line 243 TabType、line 1106 tabs、line 1259 render）

**Interfaces:**
- Consumes: Task 3 的 `GET /api/v1/financial/ratios/{symbol}` 响应结构
  （`{code, msg, data: {symbol, total_periods, groups, periods, note?}}`）；
  `StateView`（`components/ui`）、`chartTheme` 令牌、`fin-period-switcher`/
  `fin-table`/`fin-chart-card` CSS 类（Financial.css）。
- Produces: `useRatios(symbol, periodMode, limit)` → `{data, loading, error}`；
  `RatiosPanel`（`React.FC<{symbol: string | null}>`）。

- [ ] **Step 1: 创建 hook `src/hooks/useRatios.ts`**

```typescript
/**
 * 比率分析（ratio analysis）数据 hook。
 *
 * 调用 GET /financial/ratios/{symbol}，
 * 14 个核心财务比率（盈利/偿债/营运/成长）多期时序。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export type RatioUnit = 'pct' | 'x' | 'growth';

export interface RatioMeta {
  key: string;
  label: string;
  unit: RatioUnit;
  formula: string;
}

export interface RatioGroup {
  key: string;
  label: string;
  ratios: RatioMeta[];
}

export interface RatioPeriod {
  report_date: string;
  values: Record<string, number | null>;
  ratios: Record<string, number | null>;
}

export interface RatiosData {
  symbol: string;
  total_periods: number;
  groups: RatioGroup[];
  periods: RatioPeriod[];
  note?: string;
}

export type RatioPeriodMode = 'month' | 'year';

export function useRatios(
  symbol: string | null,
  periodMode: RatioPeriodMode,
  limit = 12,
) {
  const [data, setData] = useState<RatiosData | null>(null);
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
    fetch(`${API_BASE}/financial/ratios/${symbol}?${qs.toString()}`)
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

- [ ] **Step 2: 创建组件 `src/components/RatiosPanel.tsx`**

```tsx
/**
 * RatiosPanel —— 比率分析（Ratio Analysis）面板。
 *
 * 14 个核心财务比率四分组矩阵（行=比率、列=报告期，最新期在前），
 * 附"Δ较上期"变动列；点击比率行查看该比率趋势图。
 * 比率无 A股涨跌语义，Δ 用中性色（升蓝/降灰）。
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
import { useRatios } from '../hooks/useRatios';
import type { RatioMeta, RatioUnit } from '../hooks/useRatios';
import {
  CHART_COLORS,
  axisProps,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';

const fmtVal = (v: number | null | undefined, unit: RatioUnit) => {
  if (v == null) return '—';
  if (unit === 'pct') return `${v.toFixed(1)}%`;
  if (unit === 'growth') return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
  return v.toFixed(2);
};

const fmtDelta = (d: number | null, unit: RatioUnit) => {
  if (d == null) return '—';
  const suffix = unit === 'x' ? '' : 'pp';
  return `${d > 0 ? '+' : ''}${d.toFixed(unit === 'x' ? 2 : 1)}${suffix}`;
};

export const RatiosPanel: React.FC<{ symbol: string | null }> = ({ symbol }) => {
  const [periodMode, setPeriodMode] = useState<'month' | 'year'>('month');
  const [selected, setSelected] = useState<string | null>(null);
  const { data, loading, error } = useRatios(symbol, periodMode);

  const dates = useMemo(
    () => (data?.periods ?? []).map((p) => p.report_date),
    [data],
  );
  const metaByKey = useMemo(() => {
    const m = new Map<string, RatioMeta>();
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
  if (!data || data.periods.length === 0)
    return <StateView state="empty" text={data?.note || '暂无比率分析数据'} />;

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
          {([['month', '累计'], ['year', '年报']] as const).map(([k, l]) => (
            <button
              key={k}
              className={`fin-period-switcher__btn ${periodMode === k ? 'is-active' : ''}`}
              onClick={() => setPeriodMode(k)}
            >
              {l}
            </button>
          ))}
        </div>
        <span style={{ fontSize: 12, color: '#a1a1a6' }}>
          口径：报告期累计未年化；ROE/ROA/周转率分母=(期初+期末)÷2
        </span>
      </div>

      <div className="fin-table-wrap">
        <table className="fin-table">
          <thead>
            <tr>
              <th>比率（{data.periods.length} 期）</th>
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
            {selMeta.label} · 趋势{selMeta.unit === 'x' ? '' : '（%）'}
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={chartData}
              margin={{ top: 10, right: 10, left: 0, bottom: 5 }}
            >
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" />
              <YAxis
                {...axisProps}
                tickFormatter={(v: number) =>
                  selMeta.unit === 'x' ? String(v) : `${v}%`
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

1) line 24 import 之后加一行：

```tsx
import { CommonSizePanel } from '../components/CommonSizePanel';
import { RatiosPanel } from '../components/RatiosPanel';
```

2) line 243 TabType（在 `'commonsize'` 后插入 `'ratios'`）：

```tsx
type TabType = 'summary' | 'income' | 'balance' | 'cashflow' | 'commonsize' | 'ratios' | 'forecast' | 'compare' | 'valuation' | 'dcf' | 'fundamental';
```

3) line 1106 tabs 数组（同型分析之后加）：

```tsx
    { key: 'commonsize', label: '同型分析' },
    { key: 'ratios', label: '比率分析' },
```

4) line 1259 render（同型分析之后加）：

```tsx
        {activeTab === 'commonsize' && <CommonSizePanel symbol={symbol} />}
        {activeTab === 'ratios' && <RatiosPanel symbol={symbol} />}
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && pnpm -F web build`
Expected: 构建成功，无 TypeScript 错误。

- [ ] **Step 5: 提交**

```bash
git add frontend/apps/web/src/hooks/useRatios.ts frontend/apps/web/src/components/RatiosPanel.tsx frontend/apps/web/src/pages/Financial.tsx
git commit -m "feat(ratio-analysis): 比率分析Tab——四分组矩阵+Δ较上期+行点击趋势图(useRatios+RatiosPanel)"
```

---

### Task 5: 全量回归 + 冒烟验证

**Files:** 无新文件（只读验证）。

**Interfaces:**
- Consumes: Task 1-4 全部产物。

- [ ] **Step 1: 后端全量回归**

Run: `cd backend && uv run pytest tests/ -q`
Expected: 全部 PASS（含既有 common-size/quality/percentile 等回归）。

- [ ] **Step 2: A 股真库冒烟（茅台）**

Run（若数据库不可用则记录跳过原因，不阻塞）:

```bash
cd backend && uv run python -c "
from src.infra.database.market.financial_full import (
    create_financial_detail_repository,
)
from src.domain.market.fundamental.ratio_analysis import ratio_series
repo = create_financial_detail_repository()
inc = repo.get_history('sh600519', 'income')
bal = repo.get_history('sh600519', 'balance')
by_date = {r.report_date: r for r in bal}
records = [
    {'report_date': r.report_date, 'fin': {}, 'details': [r.detail, by_date[r.report_date].detail]}
    for r in inc if r.report_date in by_date
]
out = ratio_series(records)
p = out['periods'][0]
print('茅台最新期', p['report_date'])
for k in ['gross_margin', 'net_margin', 'roe', 'current_ratio', 'revenue_growth']:
    print(f'  {k} = {p[\"ratios\"][k]}')
"
```

Expected: 最新期为最近报告期；毛利率 ≈ 91-92%（与入库列 gross_margin 口径交叉核对：误差 < 0.5pp，因固定列/明细取数路径不同）；roe/current_ratio 有值或 None（None 需能解释：如首期无期初）。

- [ ] **Step 3: 港股真库冒烟（腾讯）**

同 Step 2，symbol 换 `hk00700`（若库里是 `00700` 则用 `00700`，先
`repo.get_history('00700', 'income')` 探测）。重点核对：revenue 命中"营业额"
候选、ebt 命中"除税前溢利"候选、流动资产/负债合计候选是否可用（缺失 →
current_ratio 为 None 属预期优雅降级，记录实际命中情况到提交信息）。

- [ ] **Step 4: 前端构建（若 Task 4 后有改动则复跑）**

Run: `cd frontend && pnpm -F web build`
Expected: 成功。

- [ ] **Step 5: 冒烟结论提交（空提交记录验证结果）**

```bash
git commit --allow-empty -m "chore(ratio-analysis): 冒烟验证——茅台毛利率91-92%口径吻合;腾讯港股候选命中情况<填实测>"
```

---

## Self-Review 记录

1. **Spec coverage**：spec §4.1（模块/两函数）→ Task 1/2；§4.2（14 比率+口径）→ Task 1 元数据 + Task 2 计算；§4.3（handler/路由/响应结构/先算后截/内连接）→ Task 3；§4.4（两类测试）→ Task 1/2/3；§5.1-5.3（hook/Panel/Tab）→ Task 4；§6（错误处理：单表无数据 error、note、None 不扩散）→ Task 3 测试覆盖；§7（验证）→ Task 5。无遗漏。
2. **Placeholder scan**：无 TBD/TODO；Task 5 Step 5 的 `<填实测>` 是执行时才能得出的冒烟结论占位，属预期。
3. **Type consistency**：`ratio_series` 输出键（groups/periods/report_date/values/ratios）与 Task 3 data 组装、Task 4 `RatiosData` 类型一致；`FIXED_FIELDS`/`resolve_metric_fields` 签名在 Task 1 定义、Task 3 消费一致；前端 `RatioUnit = 'pct'|'x'|'growth'` 与后端 RATIO_META unit 取值一致。
