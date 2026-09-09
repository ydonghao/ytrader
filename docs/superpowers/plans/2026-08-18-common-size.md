# 同型分析（Common-Size）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 三大报表全科目 ÷ 基准值 → 结构百分比时序，后端纯函数模块+API+前端独立 Tab。

**Architecture:** 后端新增 `fundamental/common_size.py` 纯函数（输入 detail JSONB dict，输出结构百分比），handler 包装 `repo.get_history` 原始行后调用，router 加 `/financial/common-size/{symbol}`；前端 `useCommonSize` hook + `CommonSizePanel` 组件（百分比矩阵表 + 行点击趋势图），Financial.tsx 加 `commonsize` Tab。纯增量，不动现有 Tab 与端点。

**Tech Stack:** Python/FastAPI/SQLModel（既有）、React 18 + recharts（既有）、pytest。

## Global Constraints

- 科目值为 float 或 `'547.03亿'` 字符串 → 统一走 `parse_amount`（`src/infra/database/market/financial_full.py`；domain 模块内 try-import + 本地兜底，先例 `bank_metrics.py`）。
- 纯函数缺 key/无基准返回 None 不抛异常；百分比 round 2 位（对齐 quality.py 范式）。
- 基准：income=`*营业总收入`/`一、营业总收入`/`营业收入`（按序取首个）；balance=`*资产合计`/`资产合计`；cashflow=三项活动现金流入小计之和（任缺该期跳过）。
- 不提供 quarter 口径（detail 全科目无法正确单季差分）。
- 前端：A股红涨绿跌语义不适用结构占比，Δ列用中性色（升 #79c0ff / 降 #a1a1a6）；样式复用 `fin-table`/`fin-chart-card`/`fin-period-switcher` 既有类与 chartTheme 令牌。
- 每个任务独立可测、独立提交；测试命令均在 `backend/` 下 `uv run pytest`。

---

### Task 1: 纯函数模块 `common_size.py`

**Files:**
- Create: `backend/src/domain/market/fundamental/common_size.py`
- Test: `backend/tests/domain/market/fundamental/test_common_size.py`

**Interfaces:**
- Produces: `subject_level(name: str) -> int`；`common_size_rows(detail: dict, statement_type: str) -> Optional[list[dict]]`（元素 `{name, level, raw, pct}`，pct=round(raw/base*100,2)，基准行=100.0，无基准/基准≤0/空 detail → None）；`common_size_series(rows: list[dict], statement_type: str) -> dict`（输入升序 `[{report_date, detail}]`，输出 `{"base_name", "periods": [{"report_date"(iso str), "base_value", "items"}]}` 降序，跳过无基准期）。

- [ ] **Step 1: 写失败测试**（完整代码见下）— 覆盖：层级推断、三表基准解析（含 `*` 重述与字符串金额 `'5000万'`）、无基准/零基准/空 detail → None、cashflow 三项加总与缺项跳过、series 降序+跳期+date→iso。
- [ ] **Step 2:** `uv run pytest tests/domain/market/fundamental/test_common_size.py -q` → FAIL（ModuleNotFoundError）
- [ ] **Step 3: 实现模块**（完整代码见下）
- [ ] **Step 4:** 同命令 → PASS
- [ ] **Step 5:** `git add backend/src/domain/market/fundamental/common_size.py backend/tests/domain/market/fundamental/test_common_size.py && git commit -m "feat(common-size): 纯函数模块——三大报表科目÷基准值结构百分比"`

<details><summary>test_common_size.py 完整代码</summary>

```python
"""同型分析纯函数测试。镜像 test_quality.py 风格。"""
import datetime as dt

import pytest

from src.domain.market.fundamental.common_size import (
    common_size_rows,
    common_size_series,
    subject_level,
)


class TestSubjectLevel:
    def test_basic(self):
        assert subject_level("一、营业总收入") == 0
        assert subject_level("五、净利润") == 0
        assert subject_level("其中：营业成本") == 2
        assert subject_level("销售费用") == 1
        assert subject_level("*营业总收入") == 1

    def test_edge(self):
        assert subject_level("") == 1
        assert subject_level("其中:营业成本") == 2  # 半角冒号


class TestCommonSizeRows:
    def test_income_basic(self):
        detail = {
            "一、营业总收入": 100.0,
            "其中：营业成本": 40.0,
            "销售费用": 10.0,
            "五、净利润": 20.0,
            "研发费用": None,
        }
        rows = common_size_rows(detail, "income")
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["一、营业总收入"]["pct"] == 100.0
        assert by_name["其中：营业成本"]["pct"] == pytest.approx(40.0)
        assert by_name["销售费用"]["pct"] == pytest.approx(10.0)
        assert by_name["研发费用"]["raw"] is None
        assert by_name["研发费用"]["pct"] is None
        # 顺序 = detail 原始顺序
        assert [r["name"] for r in rows] == list(detail.keys())

    def test_income_star_restatement_and_string_amount(self):
        detail = {"*营业总收入": "1亿", "其中：营业成本": "5000万"}
        rows = common_size_rows(detail, "income")
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["其中：营业成本"]["pct"] == pytest.approx(50.0)

    def test_balance_basic(self):
        rows = common_size_rows({"*资产合计": 200.0, "货币资金": 50.0}, "balance")
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["货币资金"]["pct"] == pytest.approx(25.0)

    def test_cashflow_base_is_inflow_sum(self):
        detail = {
            "经营活动现金流入小计": 60.0,
            "投资活动现金流入小计": 30.0,
            "筹资活动现金流入小计": 10.0,
            "经营活动现金流出小计": 50.0,
        }
        rows = common_size_rows(detail, "cashflow")  # 基准=100
        assert rows is not None
        by_name = {r["name"]: r for r in rows}
        assert by_name["经营活动现金流入小计"]["pct"] == pytest.approx(60.0)

    def test_missing_base_returns_none(self):
        assert common_size_rows({"营业成本": 40.0}, "income") is None
        assert common_size_rows({"货币资金": 1.0}, "balance") is None
        # cashflow 三项流入缺一 → 无基准
        assert common_size_rows(
            {"经营活动现金流入小计": 60.0, "投资活动现金流入小计": 30.0}, "cashflow"
        ) is None

    def test_zero_base_returns_none(self):
        assert common_size_rows({"一、营业总收入": 0.0, "营业成本": 1.0}, "income") is None

    def test_empty_or_bad_input_returns_none(self):
        assert common_size_rows(None, "income") is None
        assert common_size_rows({}, "income") is None
        assert common_size_rows({"x": 1.0}, "abstract") is None  # 未知 statement_type


class TestCommonSizeSeries:
    def test_descending_and_skip_no_base(self):
        rows = common_size_series(
            [
                {"report_date": dt.date(2026, 3, 31), "detail": {"营业成本": 40.0}},   # 无基准→跳过
                {"report_date": dt.date(2026, 6, 30), "detail": {"*营业总收入": 200.0, "其中：营业成本": 60.0}},
                {"report_date": dt.date(2026, 9, 30), "detail": {"一、营业总收入": 100.0, "其中：营业成本": 40.0}},
            ],
            "income",
        )
        assert [p["report_date"] for p in rows["periods"]] == ["2026-09-30", "2026-06-30"]
        assert rows["base_name"] == "一、营业总收入"  # 最新期命中的候选名
        latest = rows["periods"][0]
        assert latest["base_value"] == 100.0
        by_name = {it["name"]: it for it in latest["items"]}
        assert by_name["其中：营业成本"]["pct"] == pytest.approx(40.0)

    def test_all_no_base(self):
        rows = common_size_series(
            [{"report_date": dt.date(2026, 3, 31), "detail": {"x": 1.0}}], "income"
        )
        assert rows["periods"] == []
        assert rows["base_name"] is None

    def test_string_report_date(self):
        rows = common_size_series(
            [{"report_date": "2025-12-31", "detail": {"一、营业总收入": 10.0}}], "income"
        )
        assert rows["periods"][0]["report_date"] == "2025-12-31"

    def test_cashflow_base_name(self):
        rows = common_size_series(
            [{
                "report_date": dt.date(2025, 12, 31),
                "detail": {
                    "经营活动现金流入小计": 60.0,
                    "投资活动现金流入小计": 30.0,
                    "筹资活动现金流入小计": 10.0,
                },
            }],
            "cashflow",
        )
        assert rows["base_name"] == "现金流入总额(经营+投资+筹资流入小计)"
        assert rows["periods"][0]["base_value"] == pytest.approx(100.0)
```

</details>

<details><summary>common_size.py 完整代码</summary>

```python
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


# ── 基准科目候选（按优先级；'*' 前缀为同花顺重述科目）─────────────────────
BASE_CANDIDATES: dict[str, list[str]] = {
    "income": ["*营业总收入", "一、营业总收入", "营业收入"],
    "balance": ["*资产合计", "资产合计"],
}

# 现金流量表无"现金流入总额"总科目：基准 = 三项活动流入小计之和（任缺则无基准）
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
            if v is None:
                return None, None
            total += v
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
```

</details>

---

### Task 2: Handler + 路由 + API 测试

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（文件尾部追加 `common_size()`）
- Modify: `backend/src/api/router/financial_router.py`（尾部追加端点）
- Test: `backend/tests/api/test_common_size.py`

**Interfaces:**
- Consumes: Task 1 的 `common_size_series`；既有 `filter_year_only`（period_transform）、`create_financial_detail_repository().get_history(symbol, statement_type)`（升序）、`responses.success/error`。
- Produces: `common_size(symbol, statement_type="income", period="month", limit=12) -> JSONResponse`；HTTP `GET /financial/common-size/{symbol}`；data 结构 `{symbol, statement_type, base_name, total_periods, periods, note?}`。

- [ ] **Step 1: 写失败测试**（mock repo + patch `src.infra.database.market.financial_full.create_financial_detail_repository`，模式抄 test_valuation_percentile_exclude.py；覆盖：正常降序+跳期、year 过滤、limit、无数据 error、全部期无基准 → periods=[]+note）
- [ ] **Step 2:** `uv run pytest tests/api/test_common_size.py -q` → FAIL（ImportError: common_size）
- [ ] **Step 3: 实现 handler 函数 + 路由**（代码见下；路由 import 名对齐文件内既有 `from src.api.handler.financial_detail_handler import ...` 形式）
- [ ] **Step 4:** `uv run pytest tests/api/test_common_size.py tests/domain/market/fundamental/test_common_size.py -q` → PASS
- [ ] **Step 5:** 真库冒烟：`uv run python -c "…common_size('sh600519','income','month',3)…"` 断言茅台最新期营业成本占比在 3–12% 区间（毛利率≈91%）
- [ ] **Step 6:** `git add -A backend && git commit -m "feat(common-size): /financial/common-size 端点——handler+路由+mock测试"`

<details><summary>test_common_size.py 完整代码</summary>

```python
"""common_size 接口测试（mock repo，不发 HTTP）。模式抄 test_valuation_percentile_exclude.py。"""
import datetime as dt
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

Q1 = {"一、营业总收入": 100.0, "其中：营业成本": 40.0, "五、净利润": 20.0}
Q2 = {"*营业总收入": 200.0, "其中：营业成本": 60.0}
NO_BASE = {"营业成本": 40.0}


def _row(report_date, detail):
    r = MagicMock()
    r.report_date = report_date
    r.detail = detail
    return r


def _call(rows):
    from src.api.handler.financial_detail_handler import common_size
    repo = MagicMock()
    repo.get_history.return_value = rows
    with patch(
        "src.infra.database.market.financial_full.create_financial_detail_repository",
        return_value=repo,
    ):
        resp = common_size("sh600519", "income", "month", 12)
    return json.loads(resp.body)


def test_basic_descending_and_skip():
    body = _call([
        _row(dt.date(2026, 3, 31), NO_BASE),
        _row(dt.date(2026, 6, 30), Q2),
        _row(dt.date(2026, 9, 30), Q1),
    ])
    assert body["code"] == 0
    data = body["data"]
    assert [p["report_date"] for p in data["periods"]] == ["2026-09-30", "2026-06-30"]
    assert data["base_name"] == "一、营业总收入"
    assert data["total_periods"] == 3
    items = {it["name"]: it for it in data["periods"][0]["items"]}
    assert items["其中：营业成本"]["pct"] == pytest.approx(40.0)
    assert items["一、营业总收入"]["pct"] == 100.0


def test_year_filter_and_limit():
    rows = [
        _row(dt.date(2024, 12, 31), Q1),
        _row(dt.date(2025, 3, 31), Q2),
        _row(dt.date(2025, 12, 31), Q2),
        _row(dt.date(2026, 3, 31), Q1),
    ]
    from src.api.handler.financial_detail_handler import common_size
    repo = MagicMock()
    repo.get_history.return_value = rows
    with patch(
        "src.infra.database.market.financial_full.create_financial_detail_repository",
        return_value=repo,
    ):
        resp = common_size("sh600519", "income", "year", 1)
    data = json.loads(resp.body)["data"]
    assert [p["report_date"] for p in data["periods"]] == ["2025-12-31"]  # 只年报+limit=1


def test_no_data_error():
    body = _call([])
    assert body["code"] != 0


def test_all_periods_no_base():
    body = _call([_row(dt.date(2026, 3, 31), NO_BASE)])
    assert body["code"] == 0
    assert body["data"]["periods"] == []
    assert "note" in body["data"]
```

</details>

<details><summary>handler 追加代码（financial_detail_handler.py 尾部）</summary>

```python
def common_size(
    symbol: str,
    statement_type: str = "income",
    period: str = "month",
    limit: int = 12,
) -> Any:
    """同型分析（Common-Size）：三大报表全科目 ÷ 基准值 → 结构百分比时序。

    基准：income=营业总收入；balance=资产合计；cashflow=现金流入总额
    （经营+投资+筹资三项流入小计之和）。科目来自 detail JSONB（原始累计口径）。

    Args:
        symbol:         sh600519 / 00700 / AAPL
        statement_type: income / balance / cashflow
        period:         month=原始报告期累计口径（默认）；year=只看年报期。
                        不提供 quarter——detail 全科目无法正确单季差分。
        limit:          返回最近 N 期（默认 12）
    """
    from src.domain.market.fundamental.common_size import common_size_series
    from src.domain.market.fundamental.period_transform import filter_year_only
    from src.infra.database.market.financial_full import (
        create_financial_detail_repository,
    )
    repo = create_financial_detail_repository()
    try:
        rows = repo.get_history(symbol, statement_type)
    except Exception as e:
        return responses.error(f"查询失败: {e}")
    if not rows:
        return responses.error(f"无 {symbol} {statement_type} 数据")

    dicts = [
        {"report_date": r.report_date, "detail": getattr(r, "detail", None)}
        for r in rows
    ]
    if period == "year":
        dicts = filter_year_only(dicts)
    if len(dicts) > limit:
        dicts = dicts[-limit:]

    result = common_size_series(dicts, statement_type)
    data = {
        "symbol": symbol,
        "statement_type": statement_type,
        "base_name": result["base_name"],
        "total_periods": len(rows),
        "periods": result["periods"],
    }
    if not result["periods"]:
        data["note"] = "各报告期均缺少基准科目，无法计算结构占比"
    return responses.success(data)
```

</details>

<details><summary>router 追加代码（financial_router.py 尾部，import 并入既有 handler import 行）</summary>

```python
@router.get("/common-size/{symbol}")
def _common_size(
    symbol: str,
    statement_type: str = Query("income", description="income/balance/cashflow"),
    period: str = Query("month", description="month=原始累计口径;year=年报期"),
    limit: int = Query(12, ge=1, le=60, description="返回最近 N 期"),
):
    """同型分析：三大报表全科目结构百分比（科目÷基准值，跨期对比）。"""
    return financial_detail.common_size(symbol, statement_type, period, limit)
```

（实现时确认 router 内 handler 模块的引用名——现有端点形如 `return detail_series(...)` 还是 `financial_detail.detail_series(...)`，对齐之。）

</details>

---

### Task 3: 前端 hook + CommonSizePanel + Tab 集成

**Files:**
- Create: `frontend/apps/web/src/hooks/useCommonSize.ts`
- Create: `frontend/apps/web/src/components/CommonSizePanel.tsx`
- Modify: `frontend/apps/web/src/pages/Financial.tsx`（`TabType` 加 `'commonsize'`@242；tabs 数组 cashflow 后插入@1104；渲染链 cashflow 行后插入@1256；顶部 import）

**Interfaces:**
- Consumes: Task 2 的 HTTP 端点；`getApiBase`（`../lib/api`）；`StateView`（`./ui`）；chartTheme 的 `CHART_COLORS/axisProps/gridProps/tooltipProps`；CSS 类 `fin-table-wrap/fin-table/fin-chart-card/fin-period-switcher*`。
- Produces: `useCommonSize(symbol, statementType, periodMode, limit=12) → {data, loading, error}`；类型 `CommonSizeItem/CommonSizePeriod/CommonSizeData/CommonSizeStatement`；组件 `<CommonSizePanel symbol={string|null} />`。

- [ ] **Step 1: 写 hook**（完整代码见下，模式对齐 useValuationPercentile.ts）
- [ ] **Step 2: 写 CommonSizePanel**（完整代码见下）
- [ ] **Step 3: Financial.tsx 集成**（4 处编辑见下）
- [ ] **Step 4:** 前端构建 `pnpm build`（在 `frontend/apps/web` 下；若无 pnpm 脚本用 npm run build）→ 0 error
- [ ] **Step 5:** `git add frontend && git commit -m "feat(common-size): 同型分析Tab——占比矩阵+Δ列+科目趋势图"`

<details><summary>useCommonSize.ts 完整代码</summary>

```typescript
/**
 * 同型分析（common-size）数据 hook。
 *
 * 调用 GET /financial/common-size/{symbol}，
 * 三大报表全科目 ÷ 基准值 → 结构百分比时序。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface CommonSizeItem {
  name: string;
  level: number;
  raw: number | null;
  pct: number | null;
}

export interface CommonSizePeriod {
  report_date: string;
  base_value: number;
  items: CommonSizeItem[];
}

export interface CommonSizeData {
  symbol: string;
  statement_type: string;
  base_name: string | null;
  total_periods: number;
  periods: CommonSizePeriod[];
  note?: string;
}

export type CommonSizeStatement = 'income' | 'balance' | 'cashflow';
export type CommonSizePeriodMode = 'month' | 'year';

export function useCommonSize(
  symbol: string | null,
  statementType: CommonSizeStatement,
  periodMode: CommonSizePeriodMode,
  limit = 12,
) {
  const [data, setData] = useState<CommonSizeData | null>(null);
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
      statement_type: statementType,
      period: periodMode,
      limit: String(limit),
    });
    fetch(`${API_BASE}/financial/common-size/${symbol}?${qs.toString()}`)
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
  }, [symbol, statementType, periodMode, limit]);

  return { data, loading, error };
}
```

</details>

<details><summary>CommonSizePanel.tsx 完整代码</summary>

```tsx
/**
 * CommonSizePanel —— 同型分析（Common-Size / 垂直分析）面板。
 *
 * 三大报表全科目 ÷ 基准值 → 结构百分比矩阵（行=科目按报表顺序缩进、
 * 列=报告期，最新期在前），附"Δ较上期"变动列；点击科目行查看占比趋势图。
 * 结构占比无 A股涨跌语义，Δ 用中性色（升蓝/降灰）。
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
import { useCommonSize } from '../hooks/useCommonSize';
import type { CommonSizeStatement } from '../hooks/useCommonSize';
import {
  CHART_COLORS,
  axisProps,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';

const STATEMENTS: { key: CommonSizeStatement; label: string }[] = [
  { key: 'income', label: '利润表' },
  { key: 'balance', label: '资产负债表' },
  { key: 'cashflow', label: '现金流量表' },
];

const fmtPct = (v: number | null | undefined) =>
  v == null ? '—' : `${v.toFixed(1)}%`;

const fmtDelta = (d: number | null) =>
  d == null ? '—' : `${d > 0 ? '+' : ''}${d.toFixed(1)}pp`;

const fmtYi = (v: number | null | undefined) =>
  v == null ? '—' : `${(v / 1e8).toFixed(2)}亿`;

export const CommonSizePanel: React.FC<{ symbol: string | null }> = ({ symbol }) => {
  const [statement, setStatement] = useState<CommonSizeStatement>('income');
  const [periodMode, setPeriodMode] = useState<'month' | 'year'>('month');
  const [selected, setSelected] = useState<string | null>(null);
  const { data, loading, error } = useCommonSize(symbol, statement, periodMode);

  // 行序 = 期次顺序（最新期科目顺序优先），pcts[i] 对应 dates[i]
  const { rows, dates } = useMemo(() => {
    const periods = data?.periods ?? [];
    const dates = periods.map((p) => p.report_date);
    const order: string[] = [];
    const levels = new Map<string, number>();
    for (const p of periods) {
      for (const it of p.items) {
        if (!levels.has(it.name)) {
          order.push(it.name);
          levels.set(it.name, it.level);
        }
      }
    }
    const lookup = periods.map((p) => {
      const m = new Map<string, number | null>();
      for (const it of p.items) m.set(it.name, it.pct);
      return m;
    });
    const rows = order.map((name) => ({
      name,
      level: levels.get(name) ?? 1,
      pcts: lookup.map((m) => m.get(name) ?? null),
    }));
    return { rows, dates };
  }, [data]);

  // 趋势图数据：时间升序（从最早到最新）
  const chartData = useMemo(() => {
    if (!selected || !data) return [];
    return data.periods
      .slice()
      .reverse()
      .map((p) => ({
        label: p.report_date.slice(2, 7),
        value: p.items.find((it) => it.name === selected)?.pct ?? null,
      }));
  }, [data, selected]);

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="empty" text={error} />;
  if (!data || data.periods.length === 0)
    return <StateView state="empty" text={data?.note || '暂无同型分析数据'} />;

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
          {STATEMENTS.map((s) => (
            <button
              key={s.key}
              className={`fin-period-switcher__btn ${statement === s.key ? 'is-active' : ''}`}
              onClick={() => {
                setStatement(s.key);
                setSelected(null);
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
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
        {data.base_name && (
          <span style={{ fontSize: 12, color: '#a1a1a6' }}>
            基准：{data.base_name} = {fmtYi(data.periods[0].base_value)}
          </span>
        )}
      </div>

      <div className="fin-table-wrap">
        <table className="fin-table">
          <thead>
            <tr>
              <th>科目（占基准 %）</th>
              {dates.map((d) => (
                <th key={d}>{d.slice(2)}</th>
              ))}
              <th>Δ较上期</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const delta =
                r.pcts[0] != null && r.pcts[1] != null
                  ? r.pcts[0]! - r.pcts[1]!
                  : null;
              return (
                <tr
                  key={r.name}
                  style={{ cursor: 'pointer' }}
                  onClick={() => setSelected(selected === r.name ? null : r.name)}
                >
                  <td style={{ paddingLeft: 8 + r.level * 16 }}>{r.name}</td>
                  {r.pcts.map((p, i) => (
                    <td key={i}>{fmtPct(p)}</td>
                  ))}
                  <td
                    style={{
                      color: delta == null ? undefined : delta >= 0 ? '#79c0ff' : '#a1a1a6',
                    }}
                  >
                    {fmtDelta(delta)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {selected && chartData.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3 className="fin-chart-card__title">{selected} · 占比趋势（%）</h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" />
              <YAxis {...axisProps} tickFormatter={(v: number) => `${v}%`} />
              <Tooltip
                {...tooltipProps}
                formatter={(v: number) => [`${v?.toFixed(2)}%`, '占比']}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="value"
                name={selected}
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

</details>

<details><summary>Financial.tsx 4 处编辑</summary>

```tsx
// 1) 顶部 import 区（与 DcfPanel 等 import 相邻处）加：
import { CommonSizePanel } from '../components/CommonSizePanel';

// 2) TabType（行 242）：
type TabType = 'summary' | 'income' | 'balance' | 'cashflow' | 'commonsize' | 'forecast' | 'compare' | 'valuation' | 'dcf' | 'fundamental';

// 3) tabs 数组 cashflow 项后插：
    { key: 'commonsize', label: '同型分析' },

// 4) 渲染链（行 1256 cashflow 行后）插：
        {activeTab === 'commonsize' && <CommonSizePanel symbol={symbol} />}
```

</details>

---

### Task 4: 全量验证

- [ ] `cd backend && uv run pytest tests/domain/market/fundamental/test_common_size.py tests/api/test_common_size.py -q` → 全 PASS
- [ ] 回归：`uv run pytest tests/domain/market/fundamental/ tests/api/test_valuation_percentile_exclude.py -q` → 无新增失败
- [ ] 前端构建（web app）→ 0 error
- [ ] 真库冒烟：`common_size('sh600519', 'income'|'balance'|'cashflow', 'month', 3)` 三表均返回 periods，茅台 income 营业成本占比 ∈ [3,12]
- [ ] `git add -A && git commit -m "test(common-size): 全量验证通过"`（仅在有未提交修补时）
