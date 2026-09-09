# 财务分析图表增强：估值/市场叠加层 + 月季年周期切换

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「财务分析」页（`Financial.tsx`）所有趋势图上增加可折叠的「股价/行业指数/个股 PE·PB·PS + 行业 PE·PB 快照参考线」叠加层（双 Y 轴），并增加 月/季/年 周期切换（季=单季换算，年=年报期过滤）。

**Architecture:** 后端零新表零回补——复用已有 `stock_valuation` 表（860 万行 PE/PB/PS 历史）+ 已有 `/market/kline` + akshare `sw_index_first_info()` 当天快照。新增 2 个只读接口 + 单季换算逻辑；前端新增 1 个双轴叠加图表组件 + 1 个周期切换器 + 3 个数据 hook。

**Tech Stack:** Backend: FastAPI + SQLModel + psycopg2 + akshare 1.18.50。Frontend: React 18 + TypeScript + recharts + pnpm/monorepo。

## Global Constraints

- **后端分层**：router（`financial_router.py`）→ handler（`financial_detail_handler.py`）→ repository（`valuation.py` / `financial_full.py`）。handler 不直接写 SQL，复用 repository。
- **统一返回**：所有 handler 用 `from src.pkg import responses`，返回 `responses.success(data)` / `responses.error(msg)`。
- **Python 行宽**：black line-length=79（见 `backend/pyproject.toml`）。
- **前端图表库**：recharts（已用），不引入新库。
- **akshare 版本**：1.18.50。行业估值用 `sw_index_first_info()`（已验证返回 31 行，列：`行业代码/行业名称/成份个数/静态市盈率/TTM(滚动)市盈率/市净率/静态股息率`）。
- **行业代码格式**：akshare 返回 `801010.SI`；本项目 K 线用 `sw801010`（小写 sw 前缀，无 .SI 后缀，见 `sw_index_backfill_all.py:51-54`）。
- **估值历史数据范围**：`stock_valuation` 表 2018-01-02 至今；股息率字段全为 NULL（不做股息率曲线）。
- **周期默认值**：`quarter`（前后端一致）。
- **单季换算规则**：流量项做差（利润表+现金流量表全部），存量项不做差（资产负债表全部）。
- **测试**：后端用 pytest（`backend/tests/`，已有 `conftest.py` 提供真实 DB connection fixture）；前端无单测框架，靠 `pnpm --filter web build` + 浏览器手测。
- **commit 风格**：`feat:` / `feat(financial):` / `test:` / `refactor:` 前缀，参考现有提交。

---

## File Structure

### 后端新建
- `backend/src/domain/market/fundamental/period_transform.py` — **单季换算纯函数模块**。无 DB 依赖、无副作用，便于单测。`transform_to_quarter(rows)` / `filter_year_only(rows)` / 常量 `FLOW_FIELDS` / `STOCK_FIELDS`。
- `backend/tests/domain/market/fundamental/test_period_transform.py` — 单季换算单元测试。

### 后端修改
- `backend/src/domain/market/sync/providers/akshare_provider.py` — 新增方法 `fetch_sw_index_valuation_snapshot()`（末尾追加，~30 行）。
- `backend/src/api/handler/financial_detail_handler.py` — `detail_series()` 加 `period` 参数（调用 period_transform）；新增 `valuation_history()` / `industry_valuation_snapshot()` 两个 handler 函数。
- `backend/src/api/router/financial_router.py` — 新增 2 个路由（`/valuation-history/{symbol}` / `/industry-valuation-snapshot`），`/detail/{symbol}` 加 `period` query 参数。
- `backend/tests/api/handler/test_financial_detail_handler.py` — 新建 handler 层测试（valuation_history + period 参数）。

### 前端新建
- `frontend/apps/web/src/components/FinancialOverlayChart.tsx` — **双轴叠加图表组件**（`SelectableChart` 的超集 + 叠加层 + 行业参考线）。
- `frontend/apps/web/src/components/PeriodSwitcher.tsx` — **月/季/年 周期切换器**（3 按钮，月按钮可隐藏）。
- `frontend/apps/web/src/hooks/useFinancialOverlays.ts` — **3 个数据 hook**：`useStockValuationHistory` / `usePriceOverlays` / `useIndustryValuationSnapshot` + 合并函数 `buildOverlayData`。

### 前端修改
- `frontend/apps/web/src/pages/Financial.tsx` — 接线：周期状态 + `PeriodSwitcher`；把摘要/利润表/资产负债表/现金流的图从 `SelectableChart` 升级为 `FinancialOverlayChart`；新增「估值与市场表现」卡片（方案 A）；行业下拉。
- `frontend/apps/web/src/pages/Financial.css` — 新增 `.fin-overlay-*` / `.fin-period-switcher` / `.fin-valuation-card` 等样式。

---

## Task 1: 单季换算纯函数模块（后端）

**Files:**
- Create: `backend/src/domain/market/fundamental/__init__.py`
- Create: `backend/src/domain/market/fundamental/period_transform.py`
- Test: `backend/tests/domain/market/fundamental/__init__.py`
- Test: `backend/tests/domain/market/fundamental/test_period_transform.py`

**Interfaces:**
- Produces:
  - `FLOW_FIELDS: frozenset[str]` — 流量项字段名集合（做差）。
  - `STOCK_FIELDS: frozenset[str]` — 存量项字段名集合（不做差）。
  - `transform_to_quarter(rows: list[dict]) -> list[dict]` — 输入升序的报表期 dict 列表（每条含 `report_date` + 任意字段），输出同结构但流量项已做单季差分。**就地修改并返回同一列表对象**。`report_date` 保持原值；新增字段不加。
  - `filter_year_only(rows: list[dict]) -> list[dict]` — 返回 `report_date` 月份为 12 的子集（不改值）。
- 供 Task 2 的 handler 调用。

**字段分类常量**（从 `_DETAIL_COLUMNS` 在 `financial_full.py:299-311` 推导）：
- 流量项（利润表 + 现金流量表的所有发生额）：`revenue, operating_cost, gross_profit, sell_expense, admin_expense, rd_expense, fin_expense, operating_profit, net_profit, net_profit_parent, net_profit_deduct, ocf, icf, fcf`。
- 存量项（资产负债表的所有时点余额）：`monetary_funds, accounts_receivable, inventory, fixed_assets, goodwill, total_assets, total_liabilities, equity, equity_parent, short_loan, long_loan, cash_end`。
- 派生项（换算后重算）：`gross_margin, net_margin, debt_ratio` —— 不做差，在换算后用差分后的值重算。
- **不做处理的字段**：`basic_eps`（每股收益已是当期值，不做差）、`detail`（JSONB 原始全科目，不动）。

- [ ] **Step 1: 写失败测试（基础差分 + 跨年重置）**

Create `backend/tests/domain/market/fundamental/__init__.py` (empty) and `backend/tests/domain/market/fundamental/test_period_transform.py`:

```python
"""单季换算纯函数测试。"""
from datetime import date

from src.domain.market.fundamental.period_transform import (
    FLOW_FIELDS,
    STOCK_FIELDS,
    filter_year_only,
    transform_to_quarter,
)


def _row(rd: str, revenue=100.0, net_profit=10.0,
         total_assets=500.0, total_liabilities=200.0,
         operating_cost=80.0) -> dict:
    """构造一行报告期 dict（模拟 stock_financial_detail 的字段）。"""
    return {
        "report_date": date.fromisoformat(rd),
        "revenue": revenue,
        "operating_cost": operating_cost,
        "net_profit": net_profit,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
    }


def test_flow_fields_classified():
    """流量项含利润表/现金流科目；存量项含资产负债表科目。"""
    assert "revenue" in FLOW_FIELDS
    assert "net_profit" in FLOW_FIELDS
    assert "ocf" in FLOW_FIELDS
    assert "total_assets" in STOCK_FIELDS
    assert "inventory" in STOCK_FIELDS
    assert "cash_end" in STOCK_FIELDS


def test_quarterly_diff_within_year():
    """同年内累计值做差 → 单季值。"""
    rows = [
        _row("2024-03-31", revenue=100),   # Q1 累计
        _row("2024-06-30", revenue=250),   # H1 累计 → 单季 150
        _row("2024-09-30", revenue=400),   # Q3 累计 → 单季 150
        _row("2024-12-31", revenue=500),   # 年报 → 单季 100
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    assert out[0]["revenue"] == 100   # Q1 不变
    assert out[1]["revenue"] == 150
    assert out[2]["revenue"] == 150
    assert out[3]["revenue"] == 100


def test_quarterly_diff_resets_across_years():
    """跨年时，新一年的 Q1 不减上一年的年报（单季重置）。"""
    rows = [
        _row("2023-12-31", revenue=500),
        _row("2024-03-31", revenue=120),   # 2024Q1，不减 2023 年报
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    assert out[1]["revenue"] == 120


def test_stock_fields_not_differenced():
    """存量项（资产负债表）不做差，保持当期值。"""
    rows = [
        _row("2024-03-31", total_assets=500),
        _row("2024-06-30", total_assets=600),
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    assert out[1]["total_assets"] == 600   # 不做 600-500


def test_derived_margins_recomputed():
    """换算后毛利率用单季值重算。"""
    # Q1: revenue=100, cost=80 → 毛利20, 毛利率20%
    # H1: revenue=250(单季150), cost=200(单季120) → 毛利30, 毛利率20%
    rows = [
        _row("2024-03-31", revenue=100, operating_cost=80),
        _row("2024-06-30", revenue=250, operating_cost=200),
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    # Q1 单季毛利率
    assert out[0]["gross_margin"] == round(20 / 100 * 100, 4)
    # H1 单季：毛利 = 150-120 = 30，毛利率 = 30/150
    assert out[1]["gross_margin"] == round(30 / 150 * 100, 4)


def test_filter_year_only_keeps_december():
    rows = [
        _row("2023-03-31"),
        _row("2023-12-31"),
        _row("2024-06-30"),
        _row("2024-12-31"),
    ]
    out = filter_year_only(rows)
    assert [r["report_date"].isoformat() for r in out] == [
        "2023-12-31", "2024-12-31"
    ]


def test_quarterly_none_value_preserved():
    """None 字段做差时保持 None（不报错）。"""
    rows = [
        _row("2024-03-31", revenue=None),
        _row("2024-06-30", revenue=250),
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    # Q1 为 None → H1 无法做差，保持原累计值（降级为累计）
    assert out[1]["revenue"] == 250


def test_quarterly_first_period_of_year_unchanged():
    """每年第一期（Q1）保持累计值不变（无可减的上期）。"""
    rows = [
        _row("2023-12-31", revenue=999),
        _row("2024-03-31", revenue=100),
        _row("2024-06-30", revenue=250),
    ]
    out = transform_to_quarter([dict(r) for r in rows])
    assert out[1]["revenue"] == 100   # 2024Q1 不变
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/domain/market/fundamental/test_period_transform.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.domain.market.fundamental'`

- [ ] **Step 3: 创建包 + 实现模块**

Create `backend/src/domain/market/fundamental/__init__.py` (empty).

Create `backend/src/domain/market/fundamental/period_transform.py`:

```python
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
FLOW_FIELDS: frozenset[str] = frozenset({
    "revenue", "operating_cost", "gross_profit",
    "sell_expense", "admin_expense", "rd_expense", "fin_expense",
    "operating_profit", "net_profit", "net_profit_parent",
    "net_profit_deduct",
    "ocf", "icf", "fcf",
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


def transform_to_quarter(rows: list[dict]) -> list[dict]:
    """把累计报告期序列差分为单季值（就地修改并返回）。

    规则：
      - 按 report_date 升序遍历
      - 对流量项（FLOW_FIELDS）：若同年有上一期，做 cur - prev
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

    prev_by_year: dict[int, dict] = {}
    for r in rows:
        y = _year_of(r.get("report_date"))
        prev = prev_by_year.get(y) if y is not None else None
        if prev is not None:
            for f in FLOW_FIELDS:
                if f in r:
                    r[f] = _diff_or_keep(r[f], prev.get(f))
        _recompute_derived(r)
        if y is not None:
            prev_by_year[y] = r
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/domain/market/fundamental/test_period_transform.py -v`
Expected: 8 passed.

- [ ] **Step 5: 提交**

```bash
cd backend
git add src/domain/market/fundamental/__init__.py \
        src/domain/market/fundamental/period_transform.py \
        tests/domain/market/fundamental/__init__.py \
        tests/domain/market/fundamental/test_period_transform.py
git commit -m "feat(financial): add quarterly period transform pure functions"
```

---

## Task 2: handler 加 period 参数 + 估值历史接口（后端）

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（`detail_series` 加 `period` 参数；新增 `valuation_history`）
- Create: `backend/tests/api/handler/__init__.py`（如不存在）
- Test: `backend/tests/api/handler/test_financial_detail_handler.py`

**Interfaces:**
- Consumes: Task 1 的 `transform_to_quarter` / `filter_year_only`；`StockValuationRepository.get_as_of`（`valuation.py:102`）。
- Produces:
  - `detail_series(symbol, statement_type, limit, start_date, end_date, period)` — `period` 新增参数，默认 `"quarter"`。合法值 `month` / `quarter` / `year`。
  - `valuation_history(symbol, report_dates: list[str]) -> Any` — 返回 `responses.success({"symbol", "points": [{"report_date", "trade_date", "pe", "pe_ttm", "pb", "ps", "total_mv"}]})`。

- [ ] **Step 1: 写失败测试（period=year 过滤 + valuation_history 返回结构）**

Create `backend/tests/api/handler/__init__.py` (empty) and `backend/tests/api/handler/test_financial_detail_handler.py`:

```python
"""financial_detail_handler 的 period 参数 + valuation_history 测试。

用真实本地 DB（conftest 的 db_dsn fixture 间接通过 repo 单例）。
若 sh600519 数据缺失，标记 skip。
"""
import json

import pytest

from src.api.handler.financial_detail_handler import (
    detail_series,
    valuation_history,
)


def _body(resp):
    """从 JSONResponse 取 data dict。"""
    return json.loads(resp.body)["data"]


@pytest.fixture(scope="module")
def has_income_data():
    """探测 sh600519 是否有利润表数据。"""
    data = _body(detail_series("sh600519", "income", limit=50,
                               period="month"))
    return bool(data and data.get("series"))


def test_detail_series_period_year_filters_december(has_income_data):
    """period=year 只返回 12 月年报期。"""
    if not has_income_data:
        pytest.skip("sh600519 无利润表数据")
    data = _body(detail_series("sh600519", "income", limit=50,
                               period="year"))
    series = data["series"]
    assert len(series) > 0
    for item in series:
        # report_date 形如 '2023-12-31'
        assert item["report_date"][5:7] == "12"


def test_detail_series_period_quarter_changes_values(has_income_data):
    """period=quarter 的营收应与 period=month 不同（做了单季差分）。"""
    if not has_income_data:
        pytest.skip("sh600519 无利润表数据")
    month_data = _body(detail_series("sh600519", "income", limit=50,
                                     period="month"))
    qtr_data = _body(detail_series("sh600519", "income", limit=50,
                                   period="quarter"))
    # 至少有一期的 revenue 不同（单季 ≠ 累计）
    month_rev = {r["report_date"]: r["revenue"]
                 for r in month_data["series"]}
    diffs = [
        r for r in qtr_data["series"]
        if r["revenue"] is not None
        and month_rev.get(r["report_date"]) is not None
        and abs((r["revenue"] or 0) - (month_rev[r["report_date"]]
               or 0)) > 0.01
    ]
    assert len(diffs) > 0, "quarter 与 month 的 revenue 应有差异"


def test_detail_series_invalid_period_defaults_quarter(has_income_data):
    """非法 period 值降级为 quarter（不报错）。"""
    if not has_income_data:
        pytest.skip("sh600519 无利润表数据")
    data = _body(detail_series("sh600519", "income", limit=10,
                               period="garbage"))
    assert "series" in data


def test_valuation_history_returns_points():
    """valuation_history 返回每个 report_date 对应的估值点。"""
    # 先拿利润表报告期作为输入
    income = _body(detail_series("sh600519", "income", limit=5,
                                 period="year"))
    dates = [r["report_date"] for r in income["series"]
             if r["report_date"]]
    if not dates:
        pytest.skip("sh600519 无年报数据")
    resp = valuation_history("sh600519", dates)
    data = _body(resp)
    assert data["symbol"] == "sh600519"
    assert isinstance(data["points"], list)
    assert len(data["points"]) <= len(dates)
    # 每个点结构正确
    for p in data["points"]:
        assert "report_date" in p
        assert "trade_date" in p
        assert "pe" in p
        assert "pb" in p


def test_valuation_history_empty_dates_returns_empty():
    data = _body(valuation_history("sh600519", []))
    assert data["points"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/api/handler/test_financial_detail_handler.py -v`
Expected: FAIL with `TypeError: detail_series() got an unexpected keyword argument 'period'` 或 `ImportError: cannot import name 'valuation_history'`。

- [ ] **Step 3: 修改 handler —— detail_series 加 period 参数**

In `backend/src/api/handler/financial_detail_handler.py`:

3a. 在文件顶部 import 区（`from src.pkg import responses` 之后）加：

```python
from src.domain.market.fundamental.period_transform import (
    filter_year_only,
    transform_to_quarter,
)
```

3b. 修改 `detail_series` 签名，加 `period` 参数（在 `end_date` 之后）：

把（`financial_detail_handler.py:29-44`）：
```python
def detail_series(
    symbol: str,
    statement_type: str = "income",
    limit: int = 20,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """单只股票某报表的历史时序（固定列 + detail JSONB）。

    Args:
        symbol:         sh600519 / sz000001 / 00700 / AAPL
        statement_type: income / balance / cashflow / abstract
        limit:          返回最近 N 期（默认 20）；与 start/end 二选一
        start_date:     起始报告期 YYYY-MM-DD（含），指定后 limit 失效
        end_date:       截止报告期 YYYY-MM-DD（含）
    """
```
改为：
```python
def detail_series(
    symbol: str,
    statement_type: str = "income",
    limit: int = 20,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: str = "quarter",
) -> Any:
    """单只股票某报表的历史时序（固定列 + detail JSONB）。

    Args:
        symbol:         sh600519 / sz000001 / 00700 / AAPL
        statement_type: income / balance / cashflow / abstract
        limit:          返回最近 N 期（默认 20）；与 start/end 二选一
        start_date:     起始报告期 YYYY-MM-DD（含），指定后 limit 失效
        end_date:       截止报告期 YYYY-MM-DD（含）
        period:         month=原始报告期；quarter=单季换算（流量项做差，
                        派生指标重算）；year=只返回年报期（12-31）。
                        默认 quarter。非法值降级为 quarter。
    """
```

3c. 在 `recent = ...` 取完最近 N 期之后、`series = []` 循环之前（即 `financial_detail_handler.py:67-68` 之间），插入周期转换：

把：
```python
    else:
        recent = rows[-limit:] if len(rows) > limit else rows
    # 转为前端友好的 dict 列表（降序，最新在前）
    series = []
```
改为：
```python
    else:
        recent = rows[-limit:] if len(rows) > limit else rows

    # 周期转换：把 SQLModel 行转 dict 后按 period 处理
    dicts = []
    for r in recent:
        d = {
            "report_date": r.report_date,
        }
        # 遍历所有固定列字段（避免硬编码列名遗漏）
        for c in (
            "revenue", "operating_cost", "gross_profit",
            "sell_expense", "admin_expense", "rd_expense",
            "fin_expense", "operating_profit", "net_profit",
            "net_profit_parent", "net_profit_deduct", "basic_eps",
            "monetary_funds", "accounts_receivable", "inventory",
            "fixed_assets", "goodwill", "total_assets",
            "total_liabilities", "equity", "equity_parent",
            "short_loan", "long_loan",
            "ocf", "icf", "fcf", "cash_end",
            "gross_margin", "net_margin", "debt_ratio",
        ):
            d[c] = getattr(r, c, None)
        dicts.append(d)

    if period == "year":
        dicts = filter_year_only(dicts)
    elif period != "month":
        # quarter（默认）及任何非法值都走单季换算
        transform_to_quarter(dicts)

    # 转为前端友好的 dict 列表（降序，最新在前）
    series = []
```

3d. 修改下面的 `for r in reversed(recent):` 循环，改为从 `dicts` 取值。把：
```python
    for r in reversed(recent):
        item = {
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "revenue": r.revenue,
            "operating_cost": r.operating_cost,
            "gross_profit": r.gross_profit,
            "sell_expense": r.sell_expense,
            "admin_expense": r.admin_expense,
            "rd_expense": r.rd_expense,
            "fin_expense": r.fin_expense,
            "operating_profit": r.operating_profit,
            "net_profit": r.net_profit,
            "net_profit_parent": r.net_profit_parent,
            "net_profit_deduct": r.net_profit_deduct,
            "basic_eps": r.basic_eps,
            "monetary_funds": r.monetary_funds,
            "accounts_receivable": r.accounts_receivable,
            "inventory": r.inventory,
            "fixed_assets": r.fixed_assets,
            "goodwill": r.goodwill,
            "total_assets": r.total_assets,
            "total_liabilities": r.total_liabilities,
            "equity": r.equity,
            "equity_parent": r.equity_parent,
            "short_loan": r.short_loan,
            "long_loan": r.long_loan,
            "ocf": r.ocf,
            "icf": r.icf,
            "fcf": r.fcf,
            "cash_end": r.cash_end,
            "gross_margin": r.gross_margin,
            "net_margin": r.net_margin,
            "debt_ratio": r.debt_ratio,
            "detail": r.detail,
        }
        series.append(item)
```
改为：
```python
    for d in reversed(dicts):
        item = {
            "report_date": d["report_date"].isoformat()
            if d.get("report_date") else None,
            "revenue": d.get("revenue"),
            "operating_cost": d.get("operating_cost"),
            "gross_profit": d.get("gross_profit"),
            "sell_expense": d.get("sell_expense"),
            "admin_expense": d.get("admin_expense"),
            "rd_expense": d.get("rd_expense"),
            "fin_expense": d.get("fin_expense"),
            "operating_profit": d.get("operating_profit"),
            "net_profit": d.get("net_profit"),
            "net_profit_parent": d.get("net_profit_parent"),
            "net_profit_deduct": d.get("net_profit_deduct"),
            "basic_eps": d.get("basic_eps"),
            "monetary_funds": d.get("monetary_funds"),
            "accounts_receivable": d.get("accounts_receivable"),
            "inventory": d.get("inventory"),
            "fixed_assets": d.get("fixed_assets"),
            "goodwill": d.get("goodwill"),
            "total_assets": d.get("total_assets"),
            "total_liabilities": d.get("total_liabilities"),
            "equity": d.get("equity"),
            "equity_parent": d.get("equity_parent"),
            "short_loan": d.get("short_loan"),
            "long_loan": d.get("long_loan"),
            "ocf": d.get("ocf"),
            "icf": d.get("icf"),
            "fcf": d.get("fcf"),
            "cash_end": d.get("cash_end"),
            "gross_margin": d.get("gross_margin"),
            "net_margin": d.get("net_margin"),
            "debt_ratio": d.get("debt_ratio"),
            "detail": None,  # detail JSONB 不参与周期转换，简化省略
        }
        series.append(item)
```

> **注**：`detail` 字段（全科目 JSONB）在周期转换模式下无意义（单季差分对 195 个原始科目无定义），置 None。前端「对比/明细」如需原始 detail，单独调 `period=month`。`total_periods` 仍用原始 `rows` 长度（`len(rows)`），反映该股真实报告期总数，不受 period 过滤影响。

- [ ] **Step 4: 新增 valuation_history handler**

在 `financial_detail_handler.py` 文件末尾（`stock_profile` 函数之后）追加：

```python
def valuation_history(
    symbol: str, report_dates: list[str]
) -> Any:
    """按报告期末取个股估值历史（PE/PE_TTM/PB/PS/总市值）。

    对每个 report_date，取 stock_valuation 中 trade_date <= report_date
    的最近一行（报告期末交易日对齐）。

    Args:
        symbol:       sh600519 / sz000001
        report_dates: ['2023-12-31', '2024-03-31', ...]（前端传入）

    Returns:
        success({"symbol", "points": [{report_date, trade_date,
        pe, pe_ttm, pb, ps, total_mv}]})
    """
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    repo = create_stock_valuation_repository()

    if not report_dates:
        return responses.success(
            {"symbol": symbol, "points": []}
        )

    points = []
    for rd_str in report_dates:
        rd = _parse_date(rd_str)
        if rd is None:
            continue
        try:
            row = repo.get_as_of(symbol, rd)
        except Exception:
            row = None
        if row:
            points.append({
                "report_date": rd_str,
                "trade_date": row.trade_date.isoformat()
                if row.trade_date else None,
                "pe": row.pe,
                "pe_ttm": row.pe_ttm,
                "pb": row.pb,
                "ps": row.ps,
                "total_mv": row.total_mv,
            })
        else:
            points.append({
                "report_date": rd_str, "trade_date": None,
                "pe": None, "pe_ttm": None, "pb": None,
                "ps": None, "total_mv": None,
            })
    return responses.success({"symbol": symbol, "points": points})
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/api/handler/test_financial_detail_handler.py -v`
Expected: 5 passed（或部分 skip 若 sh600519 无数据，但生产库有数据应全过）。

- [ ] **Step 6: 提交**

```bash
cd backend
git add src/api/handler/financial_detail_handler.py \
        tests/api/handler/__init__.py \
        tests/api/handler/test_financial_detail_handler.py
git commit -m "feat(financial): period param + valuation history endpoint"
```

---

## Task 3: 行业估值快照接口（后端）

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py`（末尾追加 `fetch_sw_index_valuation_snapshot`）
- Modify: `backend/src/api/handler/financial_detail_handler.py`（追加 `industry_valuation_snapshot`）
- Modify: `backend/src/api/router/financial_router.py`（追加 2 个路由 + `/detail` 加 `period` 参数）
- Test: 复用 Task 2 的 `test_financial_detail_handler.py`（追加用例）

**Interfaces:**
- Produces:
  - `AkshareProvider.fetch_sw_index_valuation_snapshot() -> list[dict]` — 返回 31 条申万一级行业快照 dict。
  - `industry_valuation_snapshot(industry: Optional[str]) -> Any` — handler。
- Router 新增：
  - `GET /financial/valuation-history/{symbol}?report_dates=...`
  - `GET /financial/industry-valuation-snapshot?industry=...`
  - `GET /financial/detail/{symbol}?period=...`（已有路由加参数）

- [ ] **Step 1: 写失败测试（快照返回结构）**

追加到 `backend/tests/api/handler/test_financial_detail_handler.py` 末尾：

```python
from src.api.handler.financial_detail_handler import (
    industry_valuation_snapshot,
)


def test_industry_valuation_snapshot_list():
    """无 industry 参数返回全部 31 个申万一级行业快照。"""
    data = _body(industry_valuation_snapshot(None))
    # akshare 可能不可达，降级时 industries 为空——只要不报错即可
    if data is None:
        pytest.skip("akshare 行业快照不可达")
    industries = data.get("industries", [])
    if not industries:
        pytest.skip("akshare 行业快照为空（网络）")
    assert len(industries) >= 20   # 申万一级约 31 个
    first = industries[0]
    assert "industry" in first
    assert "sw_code" in first
    assert "pe_ttm" in first
    assert "pb" in first


def test_industry_valuation_snapshot_single_by_name():
    """按行业名称查单个行业快照。"""
    data = _body(industry_valuation_snapshot("银行"))
    if data is None:
        pytest.skip("akshare 行业快照不可达")
    assert data.get("industry") == "银行"
    assert "sw_code" in data


def test_industry_valuation_snapshot_not_found():
    """不存在的行业名返回 error（code != 0）。"""
    resp = industry_valuation_snapshot("不存在的行业XYZ")
    body = json.loads(resp.body)
    assert body["code"] != 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/api/handler/test_financial_detail_handler.py -v -k industry`
Expected: FAIL with `ImportError: cannot import name 'industry_valuation_snapshot'`。

- [ ] **Step 3: akshare_provider 加快照方法**

在 `backend/src/domain/market/sync/providers/akshare_provider.py` 的 `AkshareProvider` 类内、`fetch_valuation` 方法之后（`akshare_provider.py:341` 之后），追加：

```python
    # ── 申万一级行业估值快照（sw_index_first_info，legulegu，当天）────────
    def fetch_sw_index_valuation_snapshot(self) -> list[dict]:
        """申万一级 31 个行业的当天估值快照（PE/PB/股息率）。

        来源：ak.sw_index_first_info()，无历史，仅当天。
        用于财务页行业估值参考线（不做历史曲线）。

        Returns:
            list[dict]，每条含:
              sw_code('sw801010'), industry('农林牧渔'),
              company_count, pe_static, pe_ttm, pb, dividend_yield。
            失败返回 []。
        """
        df = self._retry_all(lambda: ak.sw_index_first_info())
        if df is None or df.empty:
            return []
        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                code = str(r["行业代码"]).replace(".SI", "")
                name = str(r["行业名称"]).strip()

                def _f(key):
                    v = r.get(key)
                    try:
                        return float(v) if v is not None else None
                    except (TypeError, ValueError):
                        return None

                out.append({
                    "sw_code": f"sw{code}",
                    "industry": name,
                    "company_count": int(r["成份个数"])
                    if r.get("成份个数") else None,
                    "pe_static": _f("静态市盈率"),
                    "pe_ttm": _f("TTM(滚动)市盈率"),
                    "pb": _f("市净率"),
                    "dividend_yield": _f("静态股息率"),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return out
```

- [ ] **Step 4: handler 加 industry_valuation_snapshot（带 1 小时缓存）**

在 `financial_detail_handler.py` 文件顶部（`from src.pkg import responses` 之后，`_parse_date` 之前）加缓存变量：

```python
import time

# 行业估值快照缓存：akshare 调用结果 + 时间戳，1 小时有效
_industry_snapshot_cache: dict = {"data": None, "ts": 0.0}
_INDUSTRY_SNAPSHOT_TTL = 3600  # 秒
```

在文件末尾（`valuation_history` 之后）追加：

```python
def _get_industry_snapshot_cached() -> list[dict]:
    """带 1 小时缓存的申万一级行业估值快照。

    akshare 调用失败时返回 []（不抛异常，让上层降级）。
    """
    now = time.time()
    cached = _industry_snapshot_cache
    if (cached["data"] is not None
            and now - cached["ts"] < _INDUSTRY_SNAPSHOT_TTL):
        return cached["data"]
    try:
        import socket
        socket.setdefaulttimeout(10)
        from src.domain.market.sync.providers.akshare_provider import (
            AkshareProvider,
        )
        prov = AkshareProvider()
        data = prov.fetch_sw_index_valuation_snapshot()
    except Exception:
        data = []
    cached["data"] = data
    cached["ts"] = now
    return data


def industry_valuation_snapshot(
    industry: Optional[str] = None,
) -> Any:
    """申万一级行业估值快照（当天，PE/PB/股息率）。

    Args:
        industry: 行业名称（如 '银行'）或 sw_code（如 'sw801780'）。
                  为空返回全部 31 个行业列表。

    Returns:
        industry 非空：success({industry, sw_code, as_of, pe_static,
        pe_ttm, pb, dividend_yield, company_count})；未找到则
        error('行业未找到')。
        industry 为空：success({as_of, industries: [...]}).
        akshare 不可达：success(None)（前端降级隐藏）。
    """
    data = _get_industry_snapshot_cached()
    if not data:
        return responses.success(None)

    if industry is None:
        return responses.success({
            "as_of": time.strftime("%Y-%m-%d"),
            "industries": data,
        })

    # 精确匹配：先 sw_code 再 industry 名称
    match = next(
        (d for d in data if d["sw_code"] == industry), None
    )
    if match is None:
        match = next(
            (d for d in data if d["industry"] == industry), None
        )
    if match is None:
        return responses.error(f"行业未找到: {industry}")

    return responses.success({
        "industry": match["industry"],
        "sw_code": match["sw_code"],
        "as_of": time.strftime("%Y-%m-%d"),
        "pe_static": match["pe_static"],
        "pe_ttm": match["pe_ttm"],
        "pb": match["pb"],
        "dividend_yield": match["dividend_yield"],
        "company_count": match["company_count"],
    })
```

- [ ] **Step 5: router 加路由 + /detail 加 period 参数**

在 `backend/src/api/router/financial_router.py`：

5a. 修改 import 行（`financial_router.py:724`）：

把：
```python
from src.api.handler.financial_detail_handler import detail_series, forecast_list, stock_profile
```
改为：
```python
from src.api.handler.financial_detail_handler import (
    detail_series,
    forecast_list,
    industry_valuation_snapshot,
    stock_profile,
    valuation_history,
)
```

5b. 修改 `/detail/{symbol}` 路由加 `period` 参数（`financial_router.py:727-736`）：

把：
```python
@router.get("/detail/{symbol}")
def _detail_series(
    symbol: str,
    statement_type: str = Query("income", description="income/balance/cashflow/abstract"),
    limit: int = Query(20, ge=1, le=200, description="返回最近 N 期（与 start/end 二选一）"),
    start_date: Optional[str] = Query(None, description="起始报告期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="截止报告期 YYYY-MM-DD"),
):
    """三大报表历史时序（真实数据，固定列 + detail JSONB）。"""
    return detail_series(symbol, statement_type, limit, start_date, end_date)
```
改为：
```python
@router.get("/detail/{symbol}")
def _detail_series(
    symbol: str,
    statement_type: str = Query("income", description="income/balance/cashflow/abstract"),
    limit: int = Query(20, ge=1, le=200, description="返回最近 N 期（与 start/end 二选一）"),
    start_date: Optional[str] = Query(None, description="起始报告期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="截止报告期 YYYY-MM-DD"),
    period: str = Query("quarter", description="month=原始;quarter=单季换算;year=年报期"),
):
    """三大报表历史时序（真实数据，固定列 + detail JSONB）。"""
    return detail_series(symbol, statement_type, limit, start_date, end_date, period)
```

5c. 在 `/profile/{symbol}` 路由之后（`financial_router.py:752` 之后）追加两个新路由：

```python
@router.get("/valuation-history/{symbol}")
def _valuation_history(
    symbol: str,
    report_dates: str = Query(..., description="逗号分隔的报告期 YYYY-MM-DD"),
):
    """按报告期末对齐的个股估值历史（PE/PB/PS）。"""
    dates = [d.strip() for d in report_dates.split(",") if d.strip()]
    return valuation_history(symbol, dates)


@router.get("/industry-valuation-snapshot")
def _industry_valuation_snapshot(
    industry: Optional[str] = Query(None, description="行业名或sw_code；空=全部"),
):
    """申万一级行业估值当天快照（PE/PB/股息率）。"""
    return industry_valuation_snapshot(industry)
```

- [ ] **Step 6: 运行全部测试确认通过**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/api/handler/test_financial_detail_handler.py tests/domain/market/fundamental/test_period_transform.py -v`
Expected: 全部 passed（行业快照用例可能 skip 若 akshare 网络不通，这是允许的降级）。

- [ ] **Step 7: 冒烟测试三个端点**

```bash
cd backend && source .venv/bin/activate
# 确认后端在跑（若没有则启动）：
# python -m uvicorn src.api.app:app --port 8000 &
curl -s "http://localhost:8000/financial/detail/sh600519?statement_type=income&limit=5&period=year" | python -m json.tool | head -20
curl -s "http://localhost:8000/financial/industry-valuation-snapshot" | python -m json.tool | head -20
curl -s "http://localhost:8000/financial/industry-valuation-snapshot?industry=银行" | python -m json.tool
```
Expected: `period=year` 只返回 12 月期；行业快照返回 31 条；银行返回单条。

- [ ] **Step 8: 提交**

```bash
cd backend
git add src/domain/market/sync/providers/akshare_provider.py \
        src/api/handler/financial_detail_handler.py \
        src/api/router/financial_router.py \
        tests/api/handler/test_financial_detail_handler.py
git commit -m "feat(financial): industry valuation snapshot endpoint + routes"
```

---

## Task 4: PeriodSwitcher 组件（前端）

**Files:**
- Create: `frontend/apps/web/src/components/PeriodSwitcher.tsx`

**Interfaces:**
- Produces:
  - `type Period = 'month' | 'quarter' | 'year'`（导出，后续 Task 6/7 复用）。
  - `PeriodSwitcher` 组件 props：`{ value: Period; onChange: (p: Period) => void; hasMonthly: boolean }`。

- [ ] **Step 1: 创建组件**

Create `frontend/apps/web/src/components/PeriodSwitcher.tsx`:

```tsx
/**
 * PeriodSwitcher —— 财务分析报告期颗粒度切换器（月/季/年）。
 *
 * - 月：原始报告期原样（仅当该股有月报数据时显示此按钮）
 * - 季：单季换算（后端 period=quarter）
 * - 年：只看年报期（后端 period=year）
 *
 * 默认选中「季」。无月报数据时隐藏「月」按钮。
 */
import React from 'react';

export type Period = 'month' | 'quarter' | 'year';

const LABELS: Record<Period, string> = {
  month: '月',
  quarter: '季',
  year: '年',
};

const ORDER: Period[] = ['month', 'quarter', 'year'];

interface Props {
  value: Period;
  onChange: (p: Period) => void;
  /** 是否显示「月」按钮（该股无月报数据时传 false）。默认 false。 */
  hasMonthly?: boolean;
}

export const PeriodSwitcher: React.FC<Props> = ({
  value,
  onChange,
  hasMonthly = false,
}) => {
  const visible = ORDER.filter((p) => p !== 'month' || hasMonthly);
  return (
    <div className="fin-period-switcher" role="group" aria-label="报告期切换">
      {visible.map((p) => (
        <button
          key={p}
          className={`fin-period-switcher__btn ${
            value === p ? 'is-active' : ''
          }`}
          onClick={() => onChange(p)}
          aria-pressed={value === p}
        >
          {LABELS[p]}
        </button>
      ))}
    </div>
  );
};
```

- [ ] **Step 2: 加样式（追加到 Financial.css，Task 7 统一加，此处先跳过避免空提交）**

样式在 Task 7 的 CSS 块里统一加。本步先验证组件能编译。

- [ ] **Step 3: 验证编译**

Run: `cd frontend && pnpm --filter web build 2>&1 | tail -20`（或 `pnpm --filter web lint`）
Expected: 无 TS 错误（PeriodSwitcher 未被引用可能告警 unused，忽略）。

> 注：因组件尚未在页面引用，build 不会报错但会 tree-shake 掉。真正的视觉验证在 Task 6。

- [ ] **Step 4: 提交**

```bash
cd frontend
git add apps/web/src/components/PeriodSwitcher.tsx
git commit -m "feat(financial): add PeriodSwitcher component"
```

---

## Task 5: 叠加层数据 hooks（前端）

**Files:**
- Create: `frontend/apps/web/src/hooks/useFinancialOverlays.ts`

**Interfaces:**
- Produces:
  - `useStockValuationHistory(symbol, reportDates)` → `{data: Map<rd, ValuationPoint>, loading}`
  - `usePriceOverlays(symbol, industrySwCode, startDate, endDate)` → `{data: Map<rd, {stock_price, industry_index}>, loading}`
  - `useIndustryValuationSnapshot(industrySwCode)` → `{data: IndustrySnapshot | null, list: IndustryListItem[], loading}`
  - `buildOverlayData(valMap, priceMap)` → `OverlayData`（合并函数）
  - 类型：`ValuationPoint` / `OverlayData` / `IndustrySnapshot` / `IndustryListItem` / `OverlayKey`

- [ ] **Step 1: 创建 hooks 文件**

Create `frontend/apps/web/src/hooks/useFinancialOverlays.ts`:

```ts
/**
 * 财务分析叠加层数据 hooks。
 *
 * 三个独立 hook 各自降级，互不阻塞：
 *   - useStockValuationHistory: 个股 PE/PB/PS 历史（按报告期末对齐）
 *   - usePriceOverlays: 个股股价 + 行业指数（按报告期末对齐）
 *   - useIndustryValuationSnapshot: 行业 PE/PB 当天快照
 *
 * buildOverlayData: 把前两者合并成 FinancialOverlayChart 需要的 OverlayData。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

// ── 类型 ────────────────────────────────────────────────────────────────

export type OverlayKey =
  | 'stock_price'
  | 'industry_index'
  | 'pe'
  | 'pb'
  | 'ps';

export interface ValuationPoint {
  report_date: string;
  trade_date: string | null;
  pe: number | null;
  pe_ttm: number | null;
  pb: number | null;
  ps: number | null;
  total_mv: number | null;
}

export interface OverlayPoint {
  stock_price?: number;
  industry_index?: number;
  pe?: number;
  pb?: number;
  ps?: number;
}

/** key = report_date（YYYY-MM-DD），与财务图表 x 轴对齐 */
export type OverlayData = Record<string, OverlayPoint>;

export interface IndustrySnapshot {
  industry: string;
  sw_code: string;
  as_of: string;
  pe_static: number | null;
  pe_ttm: number | null;
  pb: number | null;
  dividend_yield: number | null;
  company_count: number | null;
}

export interface IndustryListItem {
  sw_code: string;
  industry: string;
  company_count: number | null;
  pe_static: number | null;
  pe_ttm: number | null;
  pb: number | null;
  dividend_yield: number | null;
}

// ── 1. 个股估值历史（按报告期末）─────────────────────────────────────────

export function useStockValuationHistory(
  symbol: string,
  reportDates: string[],
): { data: Map<string, ValuationPoint>; loading: boolean } {
  const [data, setData] = useState<Map<string, ValuationPoint>>(
    () => new Map(),
  );
  const [loading, setLoading] = useState(false);

  const key = symbol + '|' + reportDates.join(',');
  useEffect(() => {
    if (!symbol || !reportDates.length) {
      setData(new Map());
      return;
    }
    let alive = true;
    setLoading(true);
    const params = new URLSearchParams();
    params.set('report_dates', reportDates.join(','));
    fetch(
      `${API_BASE}/financial/valuation-history/${symbol}?${params}`,
    )
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        const points: ValuationPoint[] = j.data?.points || [];
        const m = new Map<string, ValuationPoint>();
        for (const p of points) m.set(p.report_date, p);
        setData(m);
      })
      .catch(() => {
        if (alive) setData(new Map());
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, loading };
}

// ── 2. 股价 + 行业指数（按报告期末对齐）──────────────────────────────────

interface RawBar {
  trade_date: string;
  close: number;
}

/**
 * 拉个股 + 行业指数日线，按 reportDates 取「<= report_date 的最近收盘价」。
 * 返回 Map<report_date, {stock_price, industry_index}>。
 */
export function usePriceOverlays(
  symbol: string,
  industrySwCode: string | null,
  reportDates: string[],
  startDate: string,
  endDate: string,
): { data: Map<string, OverlayPoint>; loading: boolean } {
  const [data, setData] = useState<Map<string, OverlayPoint>>(
    () => new Map(),
  );
  const [loading, setLoading] = useState(false);

  const key = [
    symbol,
    industrySwCode || '',
    reportDates.join(','),
    startDate,
    endDate,
  ].join('|');

  useEffect(() => {
    if (!symbol || !reportDates.length) {
      setData(new Map());
      return;
    }
    let alive = true;
    setLoading(true);

    const fetchKline = async (sym: string): Promise<RawBar[]> => {
      const params = new URLSearchParams();
      params.set('interval', '1d');
      params.set('limit', '8000');
      if (startDate) params.set('start', startDate);
      if (endDate) params.set('end', endDate);
      try {
        const r = await fetch(
          `${API_BASE}/market/kline/${sym}?${params}`,
        );
        const j = await r.json();
        const bars: any[] = j.data?.bars || [];
        return bars
          .map((b) => ({
            trade_date: String(b.trade_date).slice(0, 10),
            close: Number(b.close),
          }))
          .filter(
            (b) =>
              b.trade_date && Number.isFinite(b.close),
          )
          .sort((a, b) =>
            a.trade_date.localeCompare(b.trade_date),
          );
      } catch {
        return [];
      }
    };

    const symbols = [symbol];
    if (industrySwCode) symbols.push(industrySwCode);

    Promise.all(symbols.map((s) => fetchKline(s))).then(
      (allBars) => {
        if (!alive) return;
        const stockBars = allBars[0] || [];
        const indexBars = allBars[1] || [];

        // 对每个 report_date，二分找 <= report_date 的最近交易日
        const pickClosest = (
          bars: RawBar[],
          rd: string,
        ): number | undefined => {
          // bars 已升序；从末尾往前找第一个 <= rd
          for (let i = bars.length - 1; i >= 0; i--) {
            if (bars[i].trade_date <= rd) return bars[i].close;
          }
          return undefined;
        };

        const m = new Map<string, OverlayPoint>();
        for (const rd of reportDates) {
          const point: OverlayPoint = {};
          const sp = pickClosest(stockBars, rd);
          if (sp !== undefined) point.stock_price = sp;
          if (industrySwCode) {
            const ip = pickClosest(indexBars, rd);
            if (ip !== undefined) point.industry_index = ip;
          }
          m.set(rd, point);
        }
        setData(m);
      },
    ).finally(() => {
      if (alive) setLoading(false);
    });

    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, loading };
}

// ── 3. 行业估值快照 ──────────────────────────────────────────────────────

export function useIndustryValuationSnapshot(
  industrySwCode: string | null,
): {
  data: IndustrySnapshot | null;
  list: IndustryListItem[];
  loading: boolean;
} {
  const [snapshot, setSnapshot] =
    useState<IndustrySnapshot | null>(null);
  const [list, setList] = useState<IndustryListItem[]>([]);
  const [loading, setLoading] = useState(false);

  const listKey = 'all'; // 全行业列表只拉一次
  const singleKey = industrySwCode || '';

  // 拉全行业列表（供下拉，1 小时缓存由后端保证）
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API_BASE}/financial/industry-valuation-snapshot`)
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        const industries: IndustryListItem[] =
          j.data?.industries || [];
        setList(industries);
      })
      .catch(() => {
        if (alive) setList([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listKey]);

  // 按选中行业拉单条快照
  useEffect(() => {
    if (!industrySwCode) {
      setSnapshot(null);
      return;
    }
    let alive = true;
    fetch(
      `${API_BASE}/financial/industry-valuation-snapshot?industry=${encodeURIComponent(industrySwCode)}`,
    )
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        setSnapshot(j.data || null);
      })
      .catch(() => {
        if (alive) setSnapshot(null);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [singleKey]);

  return { data: snapshot, list, loading };
}

// ── 合并函数：估值 + 价格 → OverlayData ──────────────────────────────────

/**
 * 把估值 Map 和价格 Map 合并成 OverlayData（key = report_date）。
 * 任一 Map 缺失的 report_date 不出现（以财务 reportDates 为准）。
 */
export function buildOverlayData(
  valMap: Map<string, ValuationPoint>,
  priceMap: Map<string, OverlayPoint>,
  reportDates: string[],
): OverlayData {
  const out: OverlayData = {};
  for (const rd of reportDates) {
    const v = valMap.get(rd);
    const p = priceMap.get(rd);
    const point: OverlayPoint = {};
    if (p) {
      if (p.stock_price !== undefined)
        point.stock_price = p.stock_price;
      if (p.industry_index !== undefined)
        point.industry_index = p.industry_index;
    }
    if (v) {
      point.pe = v.pe ?? undefined;
      point.pb = v.pb ?? undefined;
      point.ps = v.ps ?? undefined;
    }
    out[rd] = point;
  }
  return out;
}
```

- [ ] **Step 2: 验证编译**

Run: `cd frontend && pnpm --filter web build 2>&1 | tail -15`
Expected: 无 TS 错误。

- [ ] **Step 3: 提交**

```bash
cd frontend
git add apps/web/src/hooks/useFinancialOverlays.ts
git commit -m "feat(financial): add overlay data hooks (valuation/price/industry)"
```

---

## Task 6: FinancialOverlayChart 双轴叠加组件（前端）

**Files:**
- Create: `frontend/apps/web/src/components/FinancialOverlayChart.tsx`

**Interfaces:**
- Consumes: Task 5 的 `OverlayData` / `IndustrySnapshot` / `OverlayKey` 类型。
- Produces:
  - `FinancialOverlayChart` 组件，props 见下方。内部组合使用指标 chip 行（复用 Financial.tsx 的 `MetricDef` 风格）+ recharts `ComposedChart` 双 Y 轴。

- [ ] **Step 1: 创建组件**

Create `frontend/apps/web/src/components/FinancialOverlayChart.tsx`:

```tsx
/**
 * FinancialOverlayChart —— 财务趋势图 + 可折叠叠加层（双 Y 轴）。
 *
 * 在基础财务指标图（柱/线）之上，叠加可开关的：
 *   - 股价（右轴 Line）
 *   - 行业指数（右轴 Line）
 *   - 个股 PE / PB / PS（右轴 Line）
 * 并画行业 PE/PB 当天快照参考虚线。
 *
 * 左轴：财务指标（亿 / %）。
 * 右轴：叠加层（价格元 / 指数点 / 估值倍数）—— 三种量纲不同，右轴只作
 *       大致参考；优先看趋势对齐而非绝对值。
 */
import React from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {
  IndustrySnapshot,
  OverlayData,
  OverlayKey,
} from '../hooks/useFinancialOverlays';

export interface MetricDef {
  key: string;
  label: string;
  color: string;
  isPercent?: boolean;
}

interface Props {
  title: string;
  /** 财务主数据（每条含 label + 各 metric 字段 + reportDate） */
  data: Array<Record<string, unknown>>;
  /** 可选财务指标定义（chip 行） */
  metrics: MetricDef[];
  chartType: 'bar' | 'line';
  selectedKeys: string[];
  onToggleMetric: (key: string) => void;
  /** 叠加层数据（key = reportDate） */
  overlayData?: OverlayData;
  /** 行业快照（画参考虚线） */
  industrySnapshot?: IndustrySnapshot | null;
  /** 当前开启的叠加项 */
  overlaySelection: OverlayKey[];
  onToggleOverlay: (key: OverlayKey) => void;
  /** data 中 reportDate 字段名（默认 'reportDate'） */
  reportDateField?: string;
}

const OVERLAY_DEFS: Array<{
  key: OverlayKey;
  label: string;
  color: string;
}> = [
  { key: 'stock_price', label: '股价', color: '#f85149' },
  { key: 'industry_index', label: '行业指数', color: '#bc8cff' },
  { key: 'pe', label: 'PE', color: '#d29922' },
  { key: 'pb', label: 'PB', color: '#56d364' },
  { key: 'ps', label: 'PS', color: '#79c0ff' },
];

export const FinancialOverlayChart: React.FC<Props> = ({
  title,
  data,
  metrics,
  chartType,
  selectedKeys,
  onToggleMetric,
  overlayData,
  industrySnapshot,
  overlaySelection,
  onToggleOverlay,
  reportDateField = 'reportDate',
}) => {
  const selectedMetrics = metrics.filter((m) =>
    selectedKeys.includes(m.key),
  );
  const isPercent = selectedMetrics.some((m) => m.isPercent);

  // 合并叠加数据到 chart data（按 reportDate 查 overlayData）
  const merged = React.useMemo(() => {
    return data.map((row) => {
      const rd = String(row[reportDateField] || '');
      const ov = overlayData?.[rd];
      return { ...row, ...(ov || {}) };
    });
  }, [data, overlayData, reportDateField]);

  // 右轴是否显示（有任意叠加开启时）
  const hasOverlay = overlaySelection.length > 0;

  // 右轴 domain：从所有开启的叠加项取 min/max
  const rightDomain = React.useMemo(() => {
    if (!hasOverlay) return undefined;
    const vals: number[] = [];
    for (const row of merged) {
      for (const k of overlaySelection) {
        const v = row[k];
        if (typeof v === 'number' && Number.isFinite(v))
          vals.push(v);
      }
    }
    if (!vals.length) return undefined;
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const pad = (hi - lo) * 0.1 || 1;
    return [lo - pad, hi + pad];
  }, [merged, overlaySelection, hasOverlay]);

  const yFormatter = isPercent
    ? (v: number) => `${v}%`
    : (v: number) => `${v}亿`;

  return (
    <div className="fin-chart-card">
      <h3 className="fin-chart-card__title">{title}</h3>
      {/* 财务指标 chip 行 */}
      {metrics.length > 0 && (
        <div className="fin-metric-chips">
          {metrics.map((m) => (
            <button
              key={m.key}
              className={`fin-metric-chip ${
                selectedKeys.includes(m.key) ? 'is-active' : ''
              }`}
              style={
                selectedKeys.includes(m.key)
                  ? { borderColor: m.color, color: m.color }
                  : undefined
              }
              onClick={() => onToggleMetric(m.key)}
            >
              <span
                className="fin-metric-chip__dot"
                style={{
                  background: selectedKeys.includes(m.key)
                    ? m.color
                    : '#484f58',
                }}
              />
              {m.label}
            </button>
          ))}
        </div>
      )}

      {/* 叠加层 chip 行（可折叠） */}
      {overlayData && (
        <div className="fin-overlay-chips">
          <span className="fin-overlay-chips__label">叠加：</span>
          {OVERLAY_DEFS.map((o) => {
            const active = overlaySelection.includes(o.key);
            // 无数据的叠加项禁用
            const hasData = merged.some((row) => {
              const v = row[o.key];
              return typeof v === 'number';
            });
            return (
              <button
                key={o.key}
                className={`fin-overlay-chip ${active ? 'is-active' : ''} ${
                  !hasData ? 'is-disabled' : ''
                }`}
                style={
                  active
                    ? { borderColor: o.color, color: o.color }
                    : undefined
                }
                disabled={!hasData}
                onClick={() => onToggleOverlay(o.key)}
              >
                <span
                  className="fin-metric-chip__dot"
                  style={{ background: active ? o.color : '#484f58' }}
                />
                {o.label}
              </button>
            );
          })}
        </div>
      )}

      {/* 行业快照标注 */}
      {industrySnapshot && (
        <div className="fin-overlay-snapshot">
          行业快照({industrySnapshot.as_of})：PE_TTM=
          {industrySnapshot.pe_ttm ?? '—'} PB=
          {industrySnapshot.pb ?? '—'} 股息率=
          {industrySnapshot.dividend_yield ?? '—'}%
        </div>
      )}

      {data.length > 0 && selectedMetrics.length > 0 ? (
        <ResponsiveContainer width="100%" height={360}>
          <ComposedChart
            data={merged}
            margin={{ top: 10, right: hasOverlay ? 50 : 10, left: 0, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
            <XAxis
              dataKey="label"
              tick={{ fill: '#8b949e', fontSize: 11 }}
              interval="preserveStartEnd"
            />
            <YAxis
              yAxisId="primary"
              tick={{ fill: '#8b949e', fontSize: 11 }}
              tickFormatter={yFormatter}
            />
            {hasOverlay && (
              <YAxis
                yAxisId="overlay"
                orientation="right"
                domain={rightDomain}
                tick={{ fill: '#8b949e', fontSize: 11 }}
              />
            )}
            <Tooltip
              contentStyle={{
                background: '#111822',
                border: '1px solid #1e2a3a',
                borderRadius: 6,
              }}
              formatter={(value: number, name: string) => {
                if (typeof value !== 'number') return [value, name];
                return [value.toFixed(2), name];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {chartType === 'bar'
              ? selectedMetrics.map((m) => (
                  <Bar
                    key={m.key}
                    yAxisId="primary"
                    dataKey={m.key}
                    name={m.label}
                    fill={m.color}
                    opacity={0.75}
                    radius={[3, 3, 0, 0]}
                  />
                ))
              : selectedMetrics.map((m) => (
                  <Line
                    key={m.key}
                    yAxisId="primary"
                    type="monotone"
                    dataKey={m.key}
                    name={m.label}
                    stroke={m.color}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                ))}
            {/* 叠加层 Line（右轴） */}
            {overlaySelection.map((k) => {
              const def = OVERLAY_DEFS.find((o) => o.key === k);
              if (!def) return null;
              return (
                <Line
                  key={k}
                  yAxisId="overlay"
                  type="monotone"
                  dataKey={k}
                  name={def.label}
                  stroke={def.color}
                  strokeWidth={1.5}
                  strokeDasharray="4 2"
                  dot={false}
                />
              );
            })}
            {/* 行业 PE/PB 参考虚线 */}
            {industrySnapshot &&
              overlaySelection.includes('pe') &&
              industrySnapshot.pe_ttm != null && (
                <ReferenceLine
                  yAxisId="overlay"
                  y={industrySnapshot.pe_ttm}
                  stroke="#d29922"
                  strokeDasharray="2 2"
                  opacity={0.4}
                  label={{
                    value: `行业PE ${industrySnapshot.pe_ttm}`,
                    fill: '#d29922',
                    fontSize: 10,
                    position: 'insideTopRight',
                  }}
                />
              )}
            {industrySnapshot &&
              overlaySelection.includes('pb') &&
              industrySnapshot.pb != null && (
                <ReferenceLine
                  yAxisId="overlay"
                  y={industrySnapshot.pb}
                  stroke="#56d364"
                  strokeDasharray="2 2"
                  opacity={0.4}
                  label={{
                    value: `行业PB ${industrySnapshot.pb}`,
                    fill: '#56d364',
                    fontSize: 10,
                    position: 'insideBottomRight',
                  }}
                />
              )}
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <div className="fin-empty">暂无数据</div>
      )}
    </div>
  );
};
```

- [ ] **Step 2: 验证编译**

Run: `cd frontend && pnpm --filter web build 2>&1 | tail -15`
Expected: 无 TS 错误（组件未引用，tree-shake 掉但不报错）。

- [ ] **Step 3: 提交**

```bash
cd frontend
git add apps/web/src/components/FinancialOverlayChart.tsx
git commit -m "feat(financial): add FinancialOverlayChart dual-axis component"
```

---

## Task 7: Financial.tsx 接线 —— 周期切换 + 叠加层 + 估值卡片（前端）

**Files:**
- Modify: `frontend/apps/web/src/pages/Financial.tsx`
- Modify: `frontend/apps/web/src/pages/Financial.css`

**Interfaces:**
- Consumes: Task 4 `PeriodSwitcher` / `Period`；Task 5 三个 hook + `buildOverlayData`；Task 6 `FinancialOverlayChart`。
- 这是最大的一个 Task，分多个子步骤。

> **关键改动点**（对应原文件行号，基于阅读时的状态）：
> - `fetchStatements`（`Financial.tsx:392-413`）：URL 加 `&period=${period}`。
> - `trendData` / `INCOME_TREND_FULL` 等 useMemo（`:476-703`）：每条加 `reportDate` 字段（供叠加层对齐）。
> - renderSummary（`:575-635`）/ renderIncome（`:705-746`）/ renderBalance / renderCashflow：把 `SelectableChart` 替换为 `FinancialOverlayChart`，新增周期切换器 + 叠加层状态。
> - 顶部 header：新增 `PeriodSwitcher` + 行业下拉。

- [ ] **Step 1: CSS 样式（先加，避免渲染错乱）**

在 `frontend/apps/web/src/pages/Financial.css` 末尾追加：

```css
/* ── 周期切换器 ── */
.fin-period-switcher {
  display: inline-flex;
  gap: 0;
  border: 1px solid #1e2a3a;
  border-radius: 6px;
  overflow: hidden;
}
.fin-period-switcher__btn {
  padding: 4px 14px;
  background: #0d1117;
  color: #8b949e;
  border: none;
  border-right: 1px solid #1e2a3a;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
}
.fin-period-switcher__btn:last-child {
  border-right: none;
}
.fin-period-switcher__btn:hover {
  background: #161b22;
  color: #e6edf3;
}
.fin-period-switcher__btn.is-active {
  background: #1f6feb;
  color: #fff;
}

/* ── 叠加层 chip 行 ── */
.fin-overlay-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 6px 0 8px;
  padding: 6px 0;
  border-top: 1px dashed #1e2a3a;
}
.fin-overlay-chips__label {
  color: #8b949e;
  font-size: 12px;
  margin-right: 4px;
}
.fin-overlay-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border: 1px solid #30363d;
  border-radius: 12px;
  background: transparent;
  color: #8b949e;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.fin-overlay-chip:hover {
  border-color: #58a6ff;
}
.fin-overlay-chip.is-active {
  background: rgba(88, 166, 255, 0.1);
}
.fin-overlay-chip.is-disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

/* ── 行业快照标注 ── */
.fin-overlay-snapshot {
  font-size: 12px;
  color: #8b949e;
  padding: 4px 0 8px;
  border-bottom: 1px dashed #1e2a3a;
  margin-bottom: 8px;
}

/* ── 行业下拉 ── */
.fin-industry-select {
  padding: 4px 8px;
  background: #0d1117;
  color: #e6edf3;
  border: 1px solid #30363d;
  border-radius: 6px;
  font-size: 13px;
  margin-left: 8px;
}

/* ── 估值与市场表现卡片 ── */
.fin-valuation-card {
  background: #0d1117;
  border: 1px solid #1e2a3a;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.fin-valuation-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.fin-valuation-card__title {
  font-size: 15px;
  font-weight: 600;
  color: #e6edf3;
  margin: 0;
}
```

- [ ] **Step 2: Financial.tsx —— 加 import + 状态**

在 `Financial.tsx` 顶部 import 区（`import './Financial.css';` 之后，`const API_BASE` 之前）加：

```tsx
import { PeriodSwitcher } from '../components/PeriodSwitcher';
import type { Period } from '../components/PeriodSwitcher';
import { FinancialOverlayChart } from '../components/FinancialOverlayChart';
import type { MetricDef } from '../components/FinancialOverlayChart';
import {
  useStockValuationHistory,
  usePriceOverlays,
  useIndustryValuationSnapshot,
  buildOverlayData,
} from '../hooks/useFinancialOverlays';
import type { OverlayKey } from '../hooks/useFinancialOverlays';
```

> **注**：`MetricDef` 已在 Financial.tsx 内部定义（`:229-234`）。为避免重复定义冲突，把内部的 `interface MetricDef` 删除，改从 `FinancialOverlayChart` 导入（Task 6 已导出 `MetricDef`）。

删除 `Financial.tsx:229-234` 的：
```tsx
interface MetricDef {
  key: string;       // dataKey（useMemo 里的驼峰名）
  label: string;     // 显示名
  color: string;     // hex 颜色
  isPercent?: boolean; // Y轴是否用%
}
```
（改由 import 提供，类型签名一致。）

在 `Financial` 组件内部（`const [chartSelections, ...]` 附近，`:339` 之后）加周期 + 叠加层状态：

```tsx
  // 周期 + 叠加层状态
  const [period, setPeriod] = useState<Period>('quarter');
  const [overlaySelection, setOverlaySelection] = useState<OverlayKey[]>([]);
  const [industrySwCode, setIndustrySwCode] = useState<string | null>(null);

  const toggleOverlay = (k: OverlayKey) => {
    setOverlaySelection((prev) =>
      prev.includes(k)
        ? prev.filter((x) => x !== k)
        : [...prev, k],
    );
  };
```

- [ ] **Step 3: fetchStatements 加 period 参数**

修改 `fetchStatements`（`Financial.tsx:392-413`），把 URL 加 `&period=${period}`：

把：
```tsx
  const fetchStatements = useCallback(async (sym: string, qs: string) => {
    setLoading(true);
    setError(null);
    try {
      const [inc, bal, cf] = await Promise.all([
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=income&${qs}`).then(r => r.json()),
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=balance&${qs}`).then(r => r.json()),
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=cashflow&${qs}`).then(r => r.json()),
      ]);
```
改为：
```tsx
  const fetchStatements = useCallback(async (sym: string, qs: string, p: Period) => {
    setLoading(true);
    setError(null);
    try {
      const [inc, bal, cf] = await Promise.all([
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=income&period=${p}&${qs}`).then(r => r.json()),
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=balance&period=${p}&${qs}`).then(r => r.json()),
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=cashflow&period=${p}&${qs}`).then(r => r.json()),
      ]);
```

修改触发 fetchStatements 的 useEffect（`Financial.tsx:458-461`），把：
```tsx
  useEffect(() => {
    fetchStatements(symbol, buildQuery());
    fetchProfile(symbol);
  }, [symbol, buildQuery, fetchStatements, fetchProfile]);
```
改为：
```tsx
  useEffect(() => {
    fetchStatements(symbol, buildQuery(), period);
    fetchProfile(symbol);
  }, [symbol, buildQuery, fetchStatements, fetchProfile, period]);
```

> 把 `period` 加入 deps，周期切换时自动重拉财务数据。

- [ ] **Step 4: useMemo 数据加 reportDate 字段**

修改 `INCOME_TREND_FULL`（`Financial.tsx:665-679`），每条加 `reportDate`：

把：
```tsx
  const INCOME_TREND_FULL = useMemo(() => {
    return incomeData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      revenue: r.revenue ? r.revenue / 1e8 : null,
```
改为：
```tsx
  const INCOME_TREND_FULL = useMemo(() => {
    return incomeData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      reportDate: r.report_date?.slice(0, 10) || '',
      revenue: r.revenue ? r.revenue / 1e8 : null,
```

同样修改 `BALANCE_TREND_FULL`（`:681-693`）和 `CASHFLOW_TREND_FULL`（`:695-703`），在 `label:` 后加 `reportDate: r.report_date?.slice(0, 10) || '',`。

同样修改 `trendData`（`:476-484`），加 `reportDate`。

- [ ] **Step 5: 叠加层数据 hooks 接线**

在 `Financial` 组件内（`latest` 变量附近，`:572` 之前）加 hooks 调用 + 合并：

```tsx
  // ── 叠加层数据 ──
  const reportDates = useMemo(
    () => incomeData.map((r) => r.report_date?.slice(0, 10) || '').filter(Boolean),
    [incomeData],
  );
  const earliestDate = reportDates[0] || '';
  const latestDate = reportDates[reportDates.length - 1] || '';

  const { data: valMap } = useStockValuationHistory(symbol, reportDates);
  const { data: priceMap } = usePriceOverlays(
    symbol, industrySwCode, reportDates, earliestDate, latestDate,
  );
  const { data: industrySnap, list: industryList } =
    useIndustryValuationSnapshot(industrySwCode);

  const overlayData = useMemo(
    () => buildOverlayData(valMap, priceMap, reportDates),
    [valMap, priceMap, reportDates],
  );

  // 月报可见性：检查是否存在非季末非年末的报告期
  const hasMonthly = useMemo(() => {
    return incomeData.some((r) => {
      const m = r.report_date?.slice(5, 7);
      return m && !['03', '06', '09', '12'].includes(m);
    });
  }, [incomeData]);

  // 自动从 profile 设置默认行业（首次加载）
  useEffect(() => {
    if (industrySwCode === null && profile?.industry && industryList.length) {
      const found = industryList.find((it) => it.industry === profile.industry);
      if (found) setIndustrySwCode(found.sw_code);
    }
  }, [profile?.industry, industryList, industrySwCode]);
```

- [ ] **Step 6: renderSummary —— 用 FinancialOverlayChart 替换 + 加估值卡片**

修改 `renderSummary`（`Financial.tsx:575-635`），把「营收与净利润趋势」和「利润率趋势」两张图从手写 `ComposedChart`/`LineChart` 改为 `FinancialOverlayChart`，并在最前面加「估值与市场表现」卡片（方案 A）。

把整个 `renderSummary` 函数体替换为：

```tsx
  function renderSummary() {
    if (loading && incomeData.length === 0) return <div className="fin-loading">加载中...</div>;
    if (incomeData.length === 0) return <div className="fin-empty">该股票暂无财务数据，请尝试其他代码</div>;
    return (
      <div className="fin-summary">
        <div className="fin-summary__cards">
          <MetricCard label="营业收入" value={fmtYuan(latest?.revenue)} sub={latest ? reportLabel(latest.report_date) : ''} />
          <MetricCard label="净利润" value={fmtYuan(latest?.net_profit)} sub={latest ? reportLabel(latest.report_date) : ''} />
          <MetricCard label="毛利率" value={fmtPct(latest?.gross_margin)} color="green" />
          <MetricCard label="净利率" value={fmtPct(latest?.net_margin)} color="green" />
          <MetricCard label="每股收益" value={fmtNum(latest?.basic_eps)} sub="元" />
          <MetricCard label="报告期数" value={String(incomeData.length)} sub="期历史" />
        </div>

        {/* 方案 A：估值与市场表现卡片 */}
        <div className="fin-valuation-card">
          <div className="fin-valuation-card__header">
            <h3 className="fin-valuation-card__title">估值与市场表现</h3>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <span style={{ color: '#8b949e', fontSize: 13 }}>行业：</span>
              <select
                className="fin-industry-select"
                value={industrySwCode || ''}
                onChange={(e) => setIndustrySwCode(e.target.value || null)}
              >
                <option value="">（未选择）</option>
                {industryList.map((it) => (
                  <option key={it.sw_code} value={it.sw_code}>
                    {it.industry}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <FinancialOverlayChart
            title="估值与市场表现（双轴）"
            data={trendData}
            metrics={[
              { key: 'stock_price', label: '股价', color: '#f85149' },
              { key: 'industry_index', label: '行业指数', color: '#bc8cff' },
            ]}
            chartType="line"
            selectedKeys={overlaySelection.filter((k) => k === 'stock_price' || k === 'industry_index')}
            onToggleMetric={(k) => toggleOverlay(k as OverlayKey)}
            overlayData={overlayData}
            industrySnapshot={industrySnap}
            overlaySelection={overlaySelection.filter((k) => ['pe', 'pb', 'ps'].includes(k))}
            onToggleOverlay={toggleOverlay}
          />
        </div>

        <div className="fin-summary__charts">
          {/* 方案 B：营收与净利润趋势（带叠加层） */}
          <FinancialOverlayChart
            title={`营收与净利润趋势（${incomeData.length} 期）`}
            data={trendData}
            metrics={[
              { key: 'revenue', label: '营业收入', color: '#3fb950' },
              { key: 'netProfit', label: '净利润', color: '#58a6ff' },
            ]}
            chartType="bar"
            selectedKeys={sel('summary-rev', [
              { key: 'revenue' } as any, { key: 'netProfit' } as any,
            ])}
            onToggleMetric={(k) => toggleChartMetric('summary-rev', k)}
            overlayData={overlayData}
            industrySnapshot={industrySnap}
            overlaySelection={overlaySelection}
            onToggleOverlay={toggleOverlay}
          />

          <FinancialOverlayChart
            title="利润率趋势（%）"
            data={trendData}
            metrics={[
              { key: 'grossMargin', label: '毛利率', color: '#3fb950', isPercent: true },
              { key: 'netMargin', label: '净利率', color: '#d29922', isPercent: true },
            ]}
            chartType="line"
            selectedKeys={sel('summary-margin', [
              { key: 'grossMargin' } as any, { key: 'netMargin' } as any,
            ])}
            onToggleMetric={(k) => toggleChartMetric('summary-margin', k)}
            overlayData={overlayData}
            industrySnapshot={industrySnap}
            overlaySelection={overlaySelection}
            onToggleOverlay={toggleOverlay}
          />
        </div>

        <div className="fin-summary__link">
          <a href="/macro" className="fin-macro-link">📊 查看宏观经济政策与指标 →</a>
        </div>
      </div>
    );
  }
```

- [ ] **Step 7: renderIncome / renderBalance / renderCashflow —— SelectableChart → FinancialOverlayChart**

修改 `renderIncome`（`Financial.tsx:705-746`），把两个 `SelectableChart` 替换为 `FinancialOverlayChart`：

把：
```tsx
          <SelectableChart chartId="income-bar" title="利润表指标趋势（柱状）" data={INCOME_TREND_FULL} metrics={INCOME_METRICS} type="bar" selectedKeys={sel('income-bar', INCOME_METRICS)} onToggleMetric={toggleChartMetric} />
          <SelectableChart chartId="income-line" title="利润表指标趋势（折线）" data={INCOME_TREND_FULL} metrics={INCOME_METRICS} type="line" selectedKeys={sel('income-line', INCOME_METRICS)} onToggleMetric={toggleChartMetric} />
```
改为：
```tsx
          <FinancialOverlayChart title="利润表指标趋势（柱状）" data={INCOME_TREND_FULL} metrics={INCOME_METRICS} chartType="bar" selectedKeys={sel('income-bar', INCOME_METRICS)} onToggleMetric={(k) => toggleChartMetric('income-bar', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          <FinancialOverlayChart title="利润表指标趋势（折线）" data={INCOME_TREND_FULL} metrics={INCOME_METRICS} chartType="line" selectedKeys={sel('income-line', INCOME_METRICS)} onToggleMetric={(k) => toggleChartMetric('income-line', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
```

同样修改 `renderBalance`（`:752-753`）的两个 `SelectableChart`：
把：
```tsx
          <SelectableChart chartId="balance-bar" title="资产负债表指标趋势（柱状）" data={BALANCE_TREND_FULL} metrics={BALANCE_METRICS} type="bar" selectedKeys={sel('balance-bar', BALANCE_METRICS)} onToggleMetric={toggleChartMetric} />
          <SelectableChart chartId="balance-line" title="资产负债表指标趋势（折线）" data={BALANCE_TREND_FULL} metrics={BALANCE_METRICS} type="line" selectedKeys={sel('balance-line', BALANCE_METRICS)} onToggleMetric={toggleChartMetric} />
```
改为：
```tsx
          <FinancialOverlayChart title="资产负债表指标趋势（柱状）" data={BALANCE_TREND_FULL} metrics={BALANCE_METRICS} chartType="bar" selectedKeys={sel('balance-bar', BALANCE_METRICS)} onToggleMetric={(k) => toggleChartMetric('balance-bar', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          <FinancialOverlayChart title="资产负债表指标趋势（折线）" data={BALANCE_TREND_FULL} metrics={BALANCE_METRICS} chartType="line" selectedKeys={sel('balance-line', BALANCE_METRICS)} onToggleMetric={(k) => toggleChartMetric('balance-line', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
```

同样修改 `renderCashflow`（找到其两个 `SelectableChart`，用 `CASHFLOW_METRICS` + chartId `cashflow-bar` / `cashflow-line`）：
把：
```tsx
          <SelectableChart chartId="cashflow-bar" title="现金流量表指标趋势（柱状）" data={CASHFLOW_TREND_FULL} metrics={CASHFLOW_METRICS} type="bar" selectedKeys={sel('cashflow-bar', CASHFLOW_METRICS)} onToggleMetric={toggleChartMetric} />
          <SelectableChart chartId="cashflow-line" title="现金流量表指标趋势（折线）" data={CASHFLOW_TREND_FULL} metrics={CASHFLOW_METRICS} type="line" selectedKeys={sel('cashflow-line', CASHFLOW_METRICS)} onToggleMetric={toggleChartMetric} />
```
改为：
```tsx
          <FinancialOverlayChart title="现金流量表指标趋势（柱状）" data={CASHFLOW_TREND_FULL} metrics={CASHFLOW_METRICS} chartType="bar" selectedKeys={sel('cashflow-bar', CASHFLOW_METRICS)} onToggleMetric={(k) => toggleChartMetric('cashflow-bar', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          <FinancialOverlayChart title="现金流量表指标趋势（折线）" data={CASHFLOW_TREND_FULL} metrics={CASHFLOW_METRICS} chartType="line" selectedKeys={sel('cashflow-line', CASHFLOW_METRICS)} onToggleMetric={(k) => toggleChartMetric('cashflow-line', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
```

- [ ] **Step 8: 顶部 header 加全局 PeriodSwitcher**

找到 header 区域（`Financial.tsx:926-985` 的 profile bar，或顶部的 fin-header）。在「时间范围快捷 chips」（`:1003-1030` 附近）之后，加一个全局周期切换器：

在时间范围 chips 的容器末尾加：

```tsx
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 12 }}>
              <span style={{ color: '#8b949e', fontSize: 13 }}>周期：</span>
              <PeriodSwitcher value={period} onChange={setPeriod} hasMonthly={hasMonthly} />
            </div>
```

> 具体插入点：找到 `近1/3/5/10年` chips 所在的 `<div className="fin-period-chips">` 或类似容器，在其同级后追加上述 div。若找不到精确容器，放在 `fin-header` 末尾即可。

- [ ] **Step 9: 删除不再使用的 SelectableChart（可选，保留也无害）**

`SelectableChart` 组件（`:238-302`）在替换后不再被调用。可保留（未来可能复用）或删除。建议**保留**以减少 diff 风险，但需确认无 TS unused 警告——recharts 的 `LineChart`/`BarChart` import 仍在 SelectableChart 里用到，不会触发 unused。

- [ ] **Step 10: 验证编译**

Run: `cd frontend && pnpm --filter web build 2>&1 | tail -25`
Expected: build 成功，无 TS 错误。

> 常见问题排查：
> - 若报 `MetricDef` 重复定义：确认已删除 Financial.tsx 内部的 `interface MetricDef`。
> - 若报 `sel` 参数类型不匹配：`sel` 的签名是 `(chartId, metrics: MetricDef[])`，renderSummary 里传了 `[{key:...} as any]` 是临时绕过；若报错可改为定义完整的 `MetricDef[]` 常量。

- [ ] **Step 11: 浏览器手测**

启动前后端（`./dev-start.sh` 或分启），打开 `http://localhost:port/financial`：

- [ ] 默认周期是「季」，营收图显示单季值
- [ ] 点「年」→ 只显示年报期（每年一个柱）
- [ ] 点「季」→ 恢复单季值
- [ ] 「月」按钮不显示（sh600519 茅台无月报）
- [ ] 摘要页有「估值与市场表现」卡片
- [ ] 点叠加「PE」chip → 右轴出现 PE 折线（黄色虚线）
- [ ] 行业下拉选「银行」→ 行业指数线 + 行业 PE 参考虚线出现
- [ ] 利润表/资产负债表/现金流的图都有叠加 chip 行

- [ ] **Step 12: 提交**

```bash
cd frontend
git add apps/web/src/pages/Financial.tsx apps/web/src/pages/Financial.css
git commit -m "feat(financial): wire overlays + period switch + valuation card

- 替换 SelectableChart 为 FinancialOverlayChart（所有趋势图）
- 新增周期切换器（月/季/年，月按钮按需隐藏）
- 新增「估值与市场表现」卡片（方案A，双轴）
- 行业下拉（默认自动 + 可手动切换）
- 叠加层应用到所有财务图（方案B）"
```

---

## Task 8: 端到端验证 + 文档更新

**Files:**
- 无新文件，验证 + 补充说明。

- [ ] **Step 1: 后端全量测试回归**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: 新增测试全过，既有测试无回归失败。

- [ ] **Step 2: 前端 build 最终验证**

Run: `cd frontend && pnpm --filter web build 2>&1 | tail -15`
Expected: 成功。

- [ ] **Step 3: 完整冒烟（3 个新端点 + 周期 + 叠加）**

```bash
# 后端端点
curl -s "http://localhost:8000/financial/detail/sh600519?statement_type=income&limit=5&period=quarter" | python -m json.tool | head -15
curl -s "http://localhost:8000/financial/valuation-history/sh600519?report_dates=2023-12-31,2024-06-30" | python -m json.tool
curl -s "http://localhost:8000/financial/industry-valuation-snapshot?industry=sw801780" | python -m json.tool

# 前端
# 打开 /financial，切换 月/季/年，开关叠加层，切换行业
```

- [ ] **Step 4: 更新 spec 标记完成（可选）**

若需留痕，在 `docs/superpowers/specs/2026-08-04-financial-chart-overlays-design.md` 顶部把 `状态: 设计待评审` 改为 `状态: 已实现`。

- [ ] **Step 5: 最终提交**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add -A
git commit -m "chore(financial): e2e verification + spec status update"
```

---

## Self-Review

### 1. Spec 覆盖检查
- ✅ 可折叠叠加层（股价/行业指数/PE/PB/PS）→ Task 6 组件 + Task 7 接线
- ✅ 行业 PE/PB 快照（当天值，不做历史）→ Task 3 `industry_valuation_snapshot`
- ✅ 月/季/年周期切换 → Task 4 `PeriodSwitcher` + Task 2 `period` 参数
- ✅ 季=单季换算 → Task 1 `transform_to_quarter`
- ✅ 年=年报期过滤 → Task 1 `filter_year_only`
- ✅ 月报有则显示 → Task 7 `hasMonthly` 逻辑
- ✅ 双 Y 轴 → Task 6 `FinancialOverlayChart`
- ✅ 方案 A（估值卡片）→ Task 7 renderSummary
- ✅ 方案 B（所有财务图叠加）→ Task 7 renderIncome/Balance/Cashflow
- ✅ 行业默认自动 + 可手动改 → Task 7 行业下拉 + useEffect 自动设置
- ✅ 估值按报告期末取点 → Task 2 `valuation_history` 用 `get_as_of`
- ✅ 个股 PE/PB/PS 完整历史 → Task 2 + Task 5 hook
- ✅ 降级处理 → Task 3 缓存返回 [] + Task 5 hooks catch

### 2. 占位符扫描
- 无 TBD / TODO / "implement later"。
- 所有代码块都是完整可执行内容。

### 3. 类型一致性
- `Period` 在 Task 4 定义、Task 7 导入使用 ✅
- `MetricDef` 在 Task 6 定义导出、Task 7 删除内部定义改为导入 ✅
- `OverlayKey` 在 Task 5 定义、Task 6/7 使用 ✅
- `OverlayData` / `ValuationPoint` / `IndustrySnapshot` 在 Task 5 定义、Task 6/7 使用 ✅
- `transform_to_quarter` / `filter_year_only` 在 Task 1 定义、Task 2 导入使用 ✅
- `valuation_history` / `industry_valuation_snapshot` 在 Task 2/3 定义、Task 3 router 导入使用 ✅

### 4. 风险点
- Task 7 Step 6 的 `sel('summary-rev', [{key:...} as any])` 是为了复用既有 `sel` 函数（它返回前 3 个 metric 的 key）。若 `sel` 的第二个参数类型严格，需确保 `as any` 不破坏运行时。备选：直接传 `['revenue', 'netProfit']` 字符串数组。**实现时若报错，改为直接传字符串数组。**
- `SelectableChart` 保留但不再使用——不删除以减小 diff，但 ESLint 可能告警 unused。若 lint 失败则删除。
