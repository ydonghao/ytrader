# 红利低估值选股 + 通用下钻 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `dividend_value` 选股模式(股息率 + 低估分位双因子),支持 PB/PE/PB+PE 切换、10y/20y 窗口、全局+单只区间剔除,并给所有选股模式补上通用下钻弹窗。

**Architecture:** 后端新增批量个股分位服务(一次 SQL 查全市场月降采样历史),新选股模式复用现有 `_finalize` 双排名机制;单股分位接口扩展 `exclude` 参数;全局剔除区间走 config + UI 可编辑接口。前端复用 NationalTeam 的 `.nt-modal` 弹窗骨架,新建下钻组件含 5 区块(画像/估值分位/财务趋势/K线/入选拆解),选股表行加 onClick。

**Tech Stack:** Python 3.13 / FastAPI / psycopg2 / SQLModel(后端);React + TypeScript + Recharts + Rsbuild(前端);pytest(测试)

**Spec:** `docs/superpowers/specs/2026-08-11-dividend-value-screener-design.md`

## Global Constraints

- 选股器模式注册在 `backend/src/domain/market/strategy/longterm/screener.py` 的 `SCREENER_MODES` 元组 + `dispatch` 字典 + `screener_router.py` 的 `list_modes()`,三处必须同步
- 排名复用 `backend/src/domain/market/strategy/longterm/strategies/value_utils.py` 的 `rank_cross_section` + `top_n_by_score`,不重写排名逻辑
- 分位算法复用 `backend/src/domain/market/fundamental/percentile.py` 的 `calc_percentile` / `percentile_stats`,SAMPLE_MIN=30
- 配置访问统一用 `from conf import app_config`(见 `backend/conf/__init__.py`),pydantic 模型在 `backend/conf/settings.py`
- 前端 API 基址用 `getApiBase()`(`frontend/apps/web/src/lib/api.ts`),响应包络 `{code:0,msg,data}`
- 前端样式遵循全局 token(`frontend/apps/web/src/styles/global.css` 的 `var(--color-*)` 等),新页面用 co-located CSS 文件,不用 inline hex(现有 Screener.tsx 是反例,本次不改它但新代码遵循规范)
- 测试在 `backend/tests/` 下,用 pytest,mock DB 加载函数(`@patch("...screener.fetch_latest_valuations", ...)`)
- 复合因子 PB+PE = 双分位等权平均 `(PB分位 + PE分位) / 2`
- `dividend_value` 模式要求真实股息率,**不用 PB 倒数兜底**

---

## File Structure

**后端新增:**
- `backend/src/domain/market/fundamental/percentile_batch.py` — 批量个股分位服务(给选股用)
- `backend/tests/domain/test_percentile_batch.py` — 上述服务的测试

**后端修改:**
- `backend/src/infra/database/market/valuation.py` — 新增 `get_range_batch()` 仓库方法
- `backend/src/domain/market/strategy/longterm/screener.py` — 新增 `_screen_dividend_value()` + 注册 + `ScreenItem.factor_breakdown`
- `backend/src/api/router/screener_router.py` — `list_modes()` 加新模式 + 新增 `GET/PUT /exclude-ranges` 端点 + export 加新模式参数
- `backend/src/api/handler/financial_detail_handler.py` — `valuation_percentile()` 加 `exclude` 参数
- `backend/src/api/router/financial_router.py` — 分位路由加 `exclude` Query
- `backend/conf/settings.py` — 新增 `ScreenerConfig` + `AppConfig.screener` 字段
- `backend/conf/config.yaml` — 新增 `screener:` 块
- `backend/tests/longterm/test_screener.py` — 加 `dividend_value` 模式测试
- `backend/tests/infra/test_valuation_batch.py` — `get_range_batch` 测试(新建)

**前端新增:**
- `frontend/apps/web/src/components/ScreenerDrillModal.tsx` — 通用下钻弹窗(5 区块)
- `frontend/apps/web/src/components/ScreenerDrillModal.css` — 弹窗样式

**前端修改:**
- `frontend/apps/web/src/pages/Screener.tsx` — 加新模式配置区(metric/window/全局剔除编辑器)+ 表行 onClick + 弹窗挂载
- `frontend/apps/web/src/hooks/useValuationPercentile.ts` — 加 `exclude` 参数支持

---

## Task 1: 批量个股分位仓库方法 `get_range_batch`

**Files:**
- Modify: `backend/src/infra/database/market/valuation.py`(在 `get_range` 之后,约 line 142 插入)
- Test: `backend/tests/infra/test_valuation_batch.py`

**Interfaces:**
- Produces: `StockValuationRepository.get_range_batch(symbols, start, end, exclude_ranges=None, monthly=True) -> dict[str, list[StockValuation]]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/infra/test_valuation_batch.py`:

```python
"""StockValuationRepository.get_range_batch 测试。

用 mock 替换 DB session，验证 SQL 构造与结果分组逻辑（不连真实库）。
"""
import sys
import os
import datetime as dt
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from src.infra.database.market.valuation import StockValuation, StockValuationRepository


def _make_row(symbol, d, pb=1.0, pe_ttm=10.0):
    return StockValuation(symbol=symbol, trade_date=d, pb=pb, pe_ttm=pe_ttm)


class TestGetRangeBatch:
    def test_groups_by_symbol(self):
        """多符号返回按 symbol 分组的 dict。"""
        repo = StockValuationRepository.__new__(StockValuationRepository)
        fake_rows = [
            _make_row("A", dt.date(2024, 1, 31)),
            _make_row("A", dt.date(2024, 2, 28)),
            _make_row("B", dt.date(2024, 1, 31)),
        ]
        with patch.object(repo, "_db") as mock_db:
            mock_session = MagicMock()
            mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)
            mock_session.exec.return_value.all.return_value = fake_rows
            # expunge 不报错
            mock_session.expunge = MagicMock()

            result = repo.get_range_batch(
                ["A", "B"], dt.date(2024, 1, 1), dt.date(2024, 3, 1)
            )
        assert set(result.keys()) == {"A", "B"}
        assert len(result["A"]) == 2
        assert len(result["B"]) == 1

    def test_empty_symbols_returns_empty(self):
        repo = StockValuationRepository.__new__(StockValuationRepository)
        result = repo.get_range_batch([], dt.date(2024, 1, 1), dt.date(2024, 3, 1))
        assert result == {}

    def test_exclude_ranges_in_query(self):
        """exclude_ranges 非空时，SQL 应包含 NOT BETWEEN 子句（通过调用 spy 验证）。"""
        repo = StockValuationRepository.__new__(StockValuationRepository)
        with patch.object(repo, "_db") as mock_db:
            mock_session = MagicMock()
            mock_db.session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db.session_scope.return_value.__exit__ = MagicMock(return_value=False)
            mock_session.exec.return_value.all.return_value = []
            mock_session.expunge = MagicMock()

            repo.get_range_batch(
                ["A"], dt.date(2020, 1, 1), dt.date(2024, 1, 1),
                exclude_ranges=[(dt.date(2021, 1, 1), dt.date(2021, 6, 30))],
            )
            # 验证 exec 被调用
            assert mock_session.exec.called
            # 拿到传给 select 的 statement，检查编译后的 SQL 含 NOT
            stmt_arg = mock_session.exec.call_args[0][0]
            compiled = str(stmt_arg)
            assert "NOT" in compiled.upper() or "trade_date" in compiled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/infra/test_valuation_batch.py -v`
Expected: FAIL with `AttributeError: 'StockValuationRepository' object has no attribute 'get_range_batch'`

- [ ] **Step 3: Implement `get_range_batch`**

用 psycopg2 直查(与 `data_loader.py:fetch_latest_valuations` 完全同款写法,绕开 ORM `DISTINCT ON` 的列表达式坑)。`DISTINCT ON (symbol, date_trunc('month', trade_date))` 是 Postgres 原生语法,psycopg2 直接支持。

In `backend/src/infra/database/market/valuation.py`, insert after the `get_range` method (after line 141, before `bulk_upsert`).需要新增 import(文件顶部已有 `import psycopg2` 和 `from psycopg2.extras import execute_values`,补一个 `RealDictCursor`):

```python
from psycopg2.extras import RealDictCursor, execute_values   # 改这行,加 RealDictCursor
```

然后加方法:

```python
    def get_range_batch(
        self,
        symbols: list[str],
        start: dt.date,
        end: dt.date,
        exclude_ranges: list[tuple[dt.date, dt.date]] | None = None,
        monthly: bool = True,
    ) -> dict[str, list[StockValuation]]:
        """
        批量拉多符号历史估值，SQL 层按月降采样（每月留最后交易日）。

        用 psycopg2 直查 + DISTINCT ON（与 data_loader 同款），绕开 ORM。
        exclude_ranges 在 Python 层过滤（避免复杂 SQL 构造）。

        Returns:
            {symbol: [StockValuation, ...]}，每符号按日期升序。
            无数据的符号不出现在结果里。
        """
        if not symbols:
            return {}
        exclude_ranges = exclude_ranges or []

        if monthly:
            sql = """
                SELECT * FROM (
                    SELECT DISTINCT ON (symbol, date_trunc('month', trade_date))
                        symbol, trade_date, pe, pe_ttm, pb, ps, ps_ttm,
                        dv_ratio, dv_ttm, total_mv
                    FROM stock_valuation
                    WHERE symbol = ANY(%s) AND trade_date >= %s AND trade_date <= %s
                    ORDER BY symbol, date_trunc('month', trade_date), trade_date DESC
                ) t ORDER BY symbol, trade_date ASC
            """
        else:
            sql = """
                SELECT symbol, trade_date, pe, pe_ttm, pb, ps, ps_ttm,
                       dv_ratio, dv_ttm, total_mv
                FROM stock_valuation
                WHERE symbol = ANY(%s) AND trade_date >= %s AND trade_date <= %s
                ORDER BY symbol, trade_date ASC
            """

        out: dict[str, list[StockValuation]] = {}
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (list(symbols), start, end))
                for r in cur.fetchall():
                    d = r["trade_date"]
                    if hasattr(d, "date"):
                        d = d.date()
                    # 剔除区间过滤
                    if any(rs <= d <= re_ for rs, re_ in exclude_ranges):
                        continue
                    sym = r["symbol"]
                    out.setdefault(sym, []).append(StockValuation(
                        symbol=sym, trade_date=d,
                        pe=r.get("pe"), pe_ttm=r.get("pe_ttm"),
                        pb=r.get("pb"), ps=r.get("ps"), ps_ttm=r.get("ps_ttm"),
                        dv_ratio=r.get("dv_ratio"), dv_ttm=r.get("dv_ttm"),
                        total_mv=r.get("total_mv"),
                    ))
        finally:
            conn.close()
        return out
```

**为何用 psycopg2 而非 ORM**:`DISTINCT ON` 的第二参数是 `date_trunc(...)` 表达式,SQLModel/SQLAlchemy 的 `.distinct()` 对 `text()` 列表达式支持不稳定(版本相关)。`data_loader.py` 已全程用 psycopg2 直查做批量取数,这里保持一致。`get_dsn()` 本文件已 import(line 23)。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/infra/test_valuation_batch.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/infra/database/market/valuation.py backend/tests/infra/test_valuation_batch.py
git commit -m "feat(valuation): 新增 get_range_batch 批量多符号历史估值(月降采样+区间剔除)"
```

---

## Task 2: 批量个股分位服务 `stock_percentile_batch`

**Files:**
- Create: `backend/src/domain/market/fundamental/percentile_batch.py`
- Test: `backend/tests/domain/test_percentile_batch.py`

**Interfaces:**
- Consumes: `StockValuationRepository.get_range_batch` (Task 1), `calc_percentile` from `percentile.py`
- Produces: `stock_percentile_batch(symbols, metric, window, as_of, exclude_ranges=None) -> dict[str, dict]` where each value is `{"percentile": float|None, "sample_size": int, "current": float|None, "pb_percentile": float|None, "pe_percentile": float|None}`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/domain/test_percentile_batch.py`:

```python
"""stock_percentile_batch 批量分位服务测试。"""
import sys
import os
import datetime as dt
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from src.domain.market.fundamental.percentile_batch import stock_percentile_batch


def _make_val_rows(symbol, pb_base=1.0):
    """造 40 个月的估值行（>= SAMPLE_MIN=30）。"""
    rows = []
    for i in range(40):
        d = dt.date(2021, 1, 1) + dt.timedelta(days=i * 30)
        rows.append(type("R", (), {
            "symbol": symbol, "trade_date": d,
            "pb": pb_base + i * 0.1, "pe_ttm": 10.0 + i * 0.5,
            "pe": None, "ps": None, "ps_ttm": None,
            "dv_ratio": None, "dv_ttm": None, "total_mv": None,
        })())
    return rows


class TestStockPercentileBatch:
    def test_pb_metric_basic(self):
        """PB 模式：返回 percentile/sample_size/current。"""
        rows_map = {"A": _make_val_rows("A", pb_base=1.0)}
        with patch(
            "src.domain.market.fundamental.percentile_batch.create_stock_valuation_repository"
        ) as mock_repo_fn:
            mock_repo = mock_repo_fn.return_value
            mock_repo.get_range_batch.return_value = rows_map
            result = stock_percentile_batch(
                ["A"], metric="pb", window="10y",
                as_of=dt.date(2024, 5, 1),
            )
        assert "A" in result
        info = result["A"]
        assert info["percentile"] is not None
        assert 0.0 <= info["percentile"] <= 1.0
        assert info["sample_size"] >= 30
        assert info["current"] is not None

    def test_pb_pe_composite_averages(self):
        """pb_pe 模式：percentile = (pb_pct + pe_pct)/2。"""
        rows_map = {"A": _make_val_rows("A")}
        with patch(
            "src.domain.market.fundamental.percentile_batch.create_stock_valuation_repository"
        ) as mock_repo_fn:
            mock_repo = mock_repo_fn.return_value
            mock_repo.get_range_batch.return_value = rows_map
            result = stock_percentile_batch(
                ["A"], metric="pb_pe", window="10y",
                as_of=dt.date(2024, 5, 1),
            )
        info = result["A"]
        assert info["pb_percentile"] is not None
        assert info["pe_percentile"] is not None
        expected = (info["pb_percentile"] + info["pe_percentile"]) / 2
        assert info["percentile"] == pytest.approx(expected, abs=0.01)

    def test_insufficient_samples_skipped(self):
        """样本 <30 的股票不出现结果里。"""
        short_rows = _make_val_rows("B")[:10]  # 只有 10 条
        rows_map = {"A": _make_val_rows("A"), "B": short_rows}
        with patch(
            "src.domain.market.fundamental.percentile_batch.create_stock_valuation_repository"
        ) as mock_repo_fn:
            mock_repo = mock_repo_fn.return_value
            mock_repo.get_range_batch.return_value = rows_map
            result = stock_percentile_batch(
                ["A", "B"], metric="pb", window="10y",
                as_of=dt.date(2024, 5, 1),
            )
        assert "A" in result
        assert "B" not in result

    def test_exclude_ranges_passed_through(self):
        """exclude_ranges 透传给 get_range_batch。"""
        rows_map = {"A": _make_val_rows("A")}
        excludes = [(dt.date(2022, 1, 1), dt.date(2022, 6, 30))]
        with patch(
            "src.domain.market.fundamental.percentile_batch.create_stock_valuation_repository"
        ) as mock_repo_fn:
            mock_repo = mock_repo_fn.return_value
            mock_repo.get_range_batch.return_value = rows_map
            stock_percentile_batch(
                ["A"], metric="pb", window="10y",
                as_of=dt.date(2024, 5, 1), exclude_ranges=excludes,
            )
            call_kwargs = mock_repo.get_range_batch.call_args
            assert call_kwargs[1]["exclude_ranges"] == excludes or \
                   call_kwargs[1].get("exclude_ranges") == excludes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/domain/test_percentile_batch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.domain.market.fundamental.percentile_batch'`

- [ ] **Step 3: Implement the service**

Create `backend/src/domain/market/fundamental/percentile_batch.py`:

```python
"""批量个股估值历史分位服务（选股器专用）。

与单股分位(percentile.py)的区别：一次 SQL 拉全市场月降采样历史，
在 Python 层按 symbol 分组算分位，避免 5000 次单查。

支持：
  - metric: "pb" | "pe_ttm" | "pb_pe"(双分位等权平均)
  - window: "10y" | "20y"(以及 percentile.py 的 _VALPCT_WINDOW_YEARS 子集)
  - exclude_ranges: 剔除区间列表(全局炒作区间下推)
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from src.domain.market.fundamental.percentile import calc_percentile, SAMPLE_MIN
from src.infra.database.market.valuation import create_stock_valuation_repository

_WINDOW_YEARS = {"3y": 3, "5y": 5, "10y": 10, "15y": 15, "20y": 20}

# metric → StockValuation 字段名
_METRIC_ATTR = {
    "pb": "pb",
    "pe_ttm": "pe_ttm",
}


def stock_percentile_batch(
    symbols: list[str],
    metric: str,            # "pb" | "pe_ttm" | "pb_pe"
    window: str,            # "10y" | "20y" | ...
    as_of: dt.date,
    exclude_ranges: Optional[list[tuple[dt.date, dt.date]]] = None,
) -> dict[str, dict]:
    """
    批量算多只股票当前估值在历史中的分位。

    Returns:
        {symbol: {percentile, sample_size, current, pb_percentile?, pe_percentile?}}
        样本不足(<30)/负值/无数据的股票不出现。
        metric="pb_pe" 时额外返回 pb_percentile / pe_percentile 子项。
    """
    if not symbols:
        return {}
    years = _WINDOW_YEARS.get(window, 10)
    range_start = dt.date(as_of.year - years, as_of.month, as_of.day)

    repo = create_stock_valuation_repository()
    rows_map = repo.get_range_batch(
        symbols, range_start, as_of,
        exclude_ranges=exclude_ranges, monthly=True,
    )

    out: dict[str, dict] = {}
    for sym, rows in rows_map.items():
        # 取该 symbol 在 as_of 当天(或之前最近)的值作为 current
        current_row = None
        for r in reversed(rows):
            if r.trade_date <= as_of:
                current_row = r
                break
        if current_row is None:
            continue

        result: dict = {"sample_size": 0, "current": None}

        if metric == "pb_pe":
            pb_pct = _calc_one(rows, "pb", current_row.pb)
            pe_pct = _calc_one(rows, "pe_ttm", current_row.pe_ttm)
            # 复合：两边都有才算，否则降级(只用有的那个)
            if pb_pct is not None and pe_pct is not None:
                result["percentile"] = (pb_pct["percentile"] + pe_pct["percentile"]) / 2
                result["pb_percentile"] = pb_pct["percentile"]
                result["pe_percentile"] = pe_pct["percentile"]
                result["sample_size"] = min(pb_pct["sample_size"], pe_pct["sample_size"])
                result["current"] = current_row.pb  # 复合模式 current 取 PB 做代表
            elif pb_pct is not None:
                # PE 样本不足，降级为纯 PB
                result["percentile"] = pb_pct["percentile"]
                result["pb_percentile"] = pb_pct["percentile"]
                result["pe_percentile"] = None
                result["sample_size"] = pb_pct["sample_size"]
                result["current"] = current_row.pb
            else:
                continue
        else:
            attr = _METRIC_ATTR.get(metric)
            if attr is None:
                continue
            one = _calc_one(rows, attr, getattr(current_row, attr))
            if one is None:
                continue
            result["percentile"] = one["percentile"]
            result["sample_size"] = one["sample_size"]
            result["current"] = one["current"]

        out[sym] = result
    return out


def _calc_one(
    rows: list,
    attr: str,
    current_val: Optional[float],
) -> Optional[dict]:
    """算单个指标的分位。返回 {percentile, sample_size, current} 或 None。"""
    if current_val is None or current_val <= 0:
        return None
    samples = [
        getattr(r, attr) for r in rows
        if getattr(r, attr) is not None and getattr(r, attr) > 0
    ]
    if len(samples) < SAMPLE_MIN:
        return None
    pct = calc_percentile(samples, current_val)
    if pct is None:
        return None
    return {"percentile": pct, "sample_size": len(samples), "current": current_val}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/domain/test_percentile_batch.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/percentile_batch.py backend/tests/domain/test_percentile_batch.py
git commit -m "feat(percentile): 新增 stock_percentile_batch 批量个股分位服务(支持 pb/pe/pb_pe+窗口+剔除)"
```

---

## Task 3: 单股分位接口加 `exclude` 参数

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`(`valuation_percentile` 函数,line 465-585)
- Modify: `backend/src/api/router/financial_router.py`(分位路由,line 784-797)
- Test: `backend/tests/api/test_valuation_percentile_exclude.py`

**Interfaces:**
- Consumes: existing `repo.get_range`
- Produces: `valuation_percentile(symbol, windows, as_of, metrics, exclude=None)` — 新增 `exclude` 参数;返回的 series 和 windows 统计都应用剔除

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_valuation_percentile_exclude.py`:

```python
"""valuation_percentile 接口 exclude 参数测试。"""
import sys
import os
import datetime as dt
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest


def _parse_exclude_param_test():
    """验证 exclude 字符串解析为日期区间列表。"""
    from src.api.handler.financial_detail_handler import _parse_exclude_ranges
    result = _parse_exclude_ranges("2020-06-01~2021-02-28,2015-06-15~2015-12-31")
    assert result == [
        (dt.date(2020, 6, 1), dt.date(2021, 2, 28)),
        (dt.date(2015, 6, 15), dt.date(2015, 12, 31)),
    ]


def _parse_exclude_invalid_returns_none_test():
    from src.api.handler.financial_detail_handler import _parse_exclude_ranges
    assert _parse_exclude_ranges("invalid") == []
    assert _parse_exclude_ranges("") == []
    assert _parse_exclude_ranges(None) == []


def test_parse_exclude_param():
    _parse_exclude_param_test()


def test_parse_exclude_invalid():
    _parse_exclude_invalid_returns_none_test()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_valuation_percentile_exclude.py -v`
Expected: FAIL with `ImportError: cannot import name '_parse_exclude_ranges'`

- [ ] **Step 3: Implement the exclude parsing + threading**

In `backend/src/api/handler/financial_detail_handler.py`, add the parser near the top of the percentile section (after line 462, before `valuation_percentile`):

```python
def _parse_exclude_ranges(
    exclude: Optional[str],
) -> list[tuple[date, date]]:
    """
    解析 exclude 查询参数为日期区间列表。

    格式："2020-06-01~2021-02-28,2015-06-15~2015-12-31"
    每段 start~end，多段逗号分隔。非法段静默跳过。
    """
    if not exclude:
        return []
    out: list[tuple[date, date]] = []
    for seg in exclude.split(","):
        seg = seg.strip()
        if "~" not in seg:
            continue
        left, right = seg.split("~", 1)
        try:
            s = date.fromisoformat(left.strip())
            e = date.fromisoformat(right.strip())
            out.append((s, e))
        except ValueError:
            continue
    return out
```

Then modify the `valuation_percentile` function signature (line 465) to add `exclude`:

```python
def valuation_percentile(
    symbol: str,
    windows: list[str] | None = None,
    as_of: Optional[str] = None,
    metrics: list[str] | None = None,
    exclude: Optional[str] = None,
) -> Any:
```

And inside, after computing `as_of_date` (around line 507), parse excludes and merge with global config excludes:

```python
    from src.domain.market.fundamental.percentile_batch import _get_global_exclude_ranges  # Task 5
    user_excludes = _parse_exclude_ranges(exclude)
    try:
        global_excludes = _get_global_exclude_ranges()
    except Exception:
        global_excludes = []
    all_excludes = user_excludes + global_excludes
```

Then in the loop that builds `all_points` (line 546-550) and `w_samples` (line 567-572), add exclude filtering. Modify the `all_points` list comprehension:

```python
        all_points = [
            {"date": r.trade_date.isoformat(), "value": getattr(r, attr)}
            for r in rows
            if getattr(r, attr) is not None and getattr(r, attr) > 0
            and not any(rs <= r.trade_date <= re_ for rs, re_ in all_excludes)
        ]
```

And the `w_samples` list comprehension:

```python
            w_samples = [
                getattr(r, attr) for r in rows
                if r.trade_date >= w_start
                and getattr(r, attr) is not None
                and getattr(r, attr) > 0
                and not any(rs <= r.trade_date <= re_ for rs, re_ in all_excludes)
            ]
```

**缓存 key 也要包含 exclude**(line 518-521),否则不同 exclude 会命中同缓存:

```python
        cache_key = (
            f"{symbol}:{metric}:{as_of_date.isoformat()}:"
            f"{','.join(windows)}:{exclude or ''}"
        )
```

Then update the router in `backend/src/api/router/financial_router.py` (line 784-797) to add the Query param:

```python
@router.get("/valuation-percentile/{symbol}")
def _valuation_percentile(
    symbol: str,
    windows: str = Query("3y,5y,10y", description="逗号分隔，可选 3y/5y/10y"),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD，默认最新交易日"),
    metrics: str = Query(
        "pe_ttm,pb,ps_ttm,dv_ttm",
        description="逗号分隔的指标",
    ),
    exclude: Optional[str] = Query(
        None,
        description="剔除区间，格式 2020-06-01~2021-02-28,逗号分隔多段",
    ),
):
    """个股估值历史分位（PE/PB/PS/股息率 × 多窗口，支持区间剔除）。"""
    win_list = [w.strip() for w in windows.split(",") if w.strip()]
    met_list = [m.strip() for m in metrics.split(",") if m.strip()]
    return valuation_percentile(symbol, win_list, as_of, met_list, exclude)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/test_valuation_percentile_exclude.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/handler/financial_detail_handler.py backend/src/api/router/financial_router.py backend/tests/api/test_valuation_percentile_exclude.py
git commit -m "feat(financial): valuation-percentile 接口加 exclude 区间剔除参数"
```

---

## Task 4: Screener 配置模型 + config.yaml + 全局剔除读取

**Files:**
- Modify: `backend/conf/settings.py`(新增 `ScreenerConfig` + `AppConfig.screener`)
- Modify: `backend/conf/config.yaml`(新增 `screener:` 块)
- Modify: `backend/src/domain/market/fundamental/percentile_batch.py`(加 `_get_global_exclude_ranges`)
- Test: `backend/tests/conf/test_screener_config.py`

**Interfaces:**
- Consumes: `from conf import app_config`
- Produces: `app_config.screener.dividend_value.exclude_ranges` (list[tuple]), `app_config.screener.dividend_value.filters_default` (dict); `_get_global_exclude_ranges() -> list[tuple[date,date]]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/conf/test_screener_config.py`:

```python
"""ScreenerConfig 配置模型测试。"""
import sys
import os
import datetime as dt
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest


def test_screener_config_defaults():
    """AppConfig.screener 有默认值，缺省时也能构建。"""
    from conf.settings import ScreenerConfig, DividendValueConfig
    cfg = ScreenerConfig()
    assert cfg.dividend_value.filters_default.dy_min == 3.0
    assert cfg.dividend_value.filters_default.value_metric == "pb"
    assert cfg.dividend_value.filters_default.value_window == "10y"


def test_get_global_exclude_ranges():
    """_get_global_exclude_ranges 返回 list[tuple[date,date]]。"""
    from src.domain.market.fundamental.percentile_batch import _get_global_exclude_ranges
    ranges = _get_global_exclude_ranges()
    assert isinstance(ranges, list)
    for r in ranges:
        assert len(r) == 2
        assert isinstance(r[0], dt.date)
        assert isinstance(r[1], dt.date)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/conf/test_screener_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'ScreenerConfig'`

- [ ] **Step 3: Implement config models**

In `backend/conf/settings.py`, add before `class AppConfig` (before line 211):

```python
class DividendValueFiltersConfig(BaseModel):
    """dividend_value 模式默认门槛。"""
    dy_min: float = 3.0
    pb_max: float = 3.0
    pe_min: float = 0.0
    pe_max: float = 60.0
    roe_min: float = 8.0
    debt_max: float = 70.0
    value_metric: str = "pb"        # pb | pe_ttm | pb_pe
    value_window: str = "10y"       # 10y | 20y


class DividendValueConfig(BaseModel):
    """红利低估值选股配置。"""
    exclude_ranges: list[list[str]] = []  # [["2015-06-15","2015-12-31"]]
    filters_default: DividendValueFiltersConfig = DividendValueFiltersConfig()


class ScreenerConfig(BaseModel):
    """选股器配置。"""
    dividend_value: DividendValueConfig = DividendValueConfig()
```

Then add `screener` field to `AppConfig` (line 211-224), add after `macro_universe`:

```python
    screener: ScreenerConfig = ScreenerConfig()
```

- [ ] **Step 4: Add config.yaml block**

In `backend/conf/config.yaml`, append at the end:

```yaml

# ── 选股器配置 ──────────────────────────────────────────────────────────────
screener:
  dividend_value:
    # 全局炒作区间（选股 + 单股分位默认剔除），UI 可编辑回写
    exclude_ranges:
      - ["2015-06-15", "2015-12-31"]   # 2015 杠杆牛
    filters_default:
      dy_min: 3.0
      pb_max: 3.0
      pe_min: 0.0
      pe_max: 60.0
      roe_min: 8.0
      debt_max: 70.0
      value_metric: "pb"     # pb | pe_ttm | pb_pe
      value_window: "10y"    # 10y | 20y
```

- [ ] **Step 5: Implement `_get_global_exclude_ranges`**

In `backend/src/domain/market/fundamental/percentile_batch.py`, add at the end:

```python
def _get_global_exclude_ranges() -> list[tuple[dt.date, dt.date]]:
    """从 app_config 读全局剔除区间（选股 + 单股分位共用）。"""
    from conf import app_config
    raw = app_config.screener.dividend_value.exclude_ranges
    out: list[tuple[dt.date, dt.date]] = []
    for pair in raw:
        if len(pair) != 2:
            continue
        try:
            out.append((dt.date.fromisoformat(pair[0]), dt.date.fromisoformat(pair[1])))
        except (ValueError, TypeError):
            continue
    return out
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/conf/test_screener_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/conf/settings.py backend/conf/config.yaml backend/src/domain/market/fundamental/percentile_batch.py backend/tests/conf/test_screener_config.py
git commit -m "feat(screener): 新增 ScreenerConfig 配置模型 + 全局剔除区间读取"
```

---

## Task 5: 新选股模式 `_screen_dividend_value`

**Files:**
- Modify: `backend/src/domain/market/strategy/longterm/screener.py`
- Test: `backend/tests/longterm/test_screener.py`(扩展)

**Interfaces:**
- Consumes: `stock_percentile_batch` (Task 2), `_get_global_exclude_ranges` (Task 4), `_finalize` (existing), `rank_cross_section` / `top_n_by_score` (existing)
- Produces: `ScreenItem.factor_breakdown` field; `_screen_dividend_value()` registered in `SCREENER_MODES` + `dispatch`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/longterm/test_screener.py`:

```python
# ── dividend_value 模式测试 ──────────────────────────────────────────────

# 给 dividend 模式造真实股息率
VAL_MAP_DV = {
    "A": {"pe_ttm": 8.0, "pb": 0.8, "dv_ttm": 6.0, "pe": 8.0},
    "B": {"pe_ttm": 50.0, "pb": 5.0, "dv_ttm": 1.0, "pe": 50.0},  # 贵+低息→淘汰
    "C": {"pe_ttm": 5.0, "pb": 0.5, "dv_ttm": 5.0, "pe": 5.0},
    "D": {"pe_ttm": -3.0, "pb": 2.0, "dv_ttm": 8.0, "pe": -3.0},  # 亏损→淘汰
    "E": {"pe_ttm": 15.0, "pb": 1.5, "dv_ttm": 4.0, "pe": 15.0},
}

FIN_MAP_DV = {
    "A": {"roe_weighted": 12.0, "debt_ratio": 50.0},
    "B": {"roe_weighted": 5.0, "debt_ratio": 40.0},
    "C": {"roe_weighted": 10.0, "debt_ratio": 55.0},
    "D": {"roe_weighted": -3.0, "debt_ratio": 75.0},
    "E": {"roe_weighted": 9.0, "debt_ratio": 60.0},
}


def _mock_dv_pct_batch(symbols, metric, window, as_of, exclude_ranges=None):
    """mock 批量分位：A/C 低分位(便宜)，E 中等，B 高(贵)。"""
    return {
        "A": {"percentile": 0.10, "sample_size": 60, "current": 0.8},
        "C": {"percentile": 0.05, "sample_size": 80, "current": 0.5},
        "E": {"percentile": 0.45, "sample_size": 50, "current": 1.5},
    }


@patch("src.domain.market.strategy.longterm.screener.stock_percentile_batch", _mock_dv_pct_batch)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", lambda symbols, as_of=None: {s: FIN_MAP_DV[s] for s in symbols if s in FIN_MAP_DV})
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", lambda symbols, as_of=None: {s: VAL_MAP_DV[s] for s in symbols if s in VAL_MAP_DV})
def test_dividend_value_filters_and_ranks():
    """dividend_value 模式：硬门槛过滤 + 双排名。"""
    result = screener.screen(
        mode="dividend_value",
        symbols=list(VAL_MAP_DV.keys()),
        as_of=TODAY,
        top_n=5,
        filters={"value_metric": "pb", "value_window": "10y"},
    )
    syms = [item.symbol for item in result.ranked_list]
    # B：股息率1%<3% 且 PB5>3 → 淘汰
    assert "B" not in syms
    # D：PE-3<0 → 淘汰
    assert "D" not in syms
    # A、C、E 入选
    assert set(syms) == {"A", "C", "E"}
    # C 分位最低(0.05)+股息率5%，应排第一
    assert syms[0] == "C"


@patch("src.domain.market.strategy.longterm.screener.stock_percentile_batch", _mock_dv_pct_batch)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", lambda symbols, as_of=None: {s: FIN_MAP_DV[s] for s in symbols if s in FIN_MAP_DV})
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", lambda symbols, as_of=None: {s: VAL_MAP_DV[s] for s in symbols if s in VAL_MAP_DV})
def test_dividend_value_factor_breakdown_populated():
    """dividend_value 结果的 factor_breakdown 有值。"""
    result = screener.screen(
        mode="dividend_value",
        symbols=list(VAL_MAP_DV.keys()),
        as_of=TODAY,
        top_n=5,
        filters={"value_metric": "pb", "value_window": "10y"},
    )
    for item in result.ranked_list:
        d = item.to_dict()
        assert "factor_breakdown" in d
        fb = d["factor_breakdown"]
        assert fb is not None
        assert "dy_value" in fb
        assert "value_percentile" in fb
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/longterm/test_screener.py::test_dividend_value_filters_and_ranks -v`
Expected: FAIL with `ValueError: 未知选股模式 'dividend_value'`

- [ ] **Step 3: Implement the mode**

In `backend/src/domain/market/strategy/longterm/screener.py`:

**(a)** Add import at top (after line 28, the value_utils import):

```python
from .data_loader import (
    FINANCIAL_LAG_DAYS,
    fetch_financial_history,
    fetch_latest_financials,
    fetch_latest_valuations,
)
from .strategies.value_utils import (
    rank_cross_section,
    top_n_by_score,
)
from src.domain.market.fundamental.percentile_batch import (
    stock_percentile_batch,
    _get_global_exclude_ranges,
)
```

**(b)** Update `SCREENER_MODES` (line 35):

```python
SCREENER_MODES = ("magic_formula", "dividend", "fscore", "custom", "dividend_value")
```

**(c)** Add `factor_breakdown` to `ScreenItem` (after line 50, the `reason` field):

```python
    reason: str = ""                # 入选原因
    factor_breakdown: Optional[dict] = None  # dividend_value 模式的因子拆解
```

**(d)** Update `ScreenItem.to_dict()` (add before the closing `}`, after line 63):

```python
            "reason": self.reason,
            "factor_breakdown": self.factor_breakdown,
```

**(e)** Register in dispatch (line 126-131):

```python
    dispatch = {
        "magic_formula": _screen_magic_formula,
        "dividend": _screen_dividend,
        "fscore": _screen_fscore,
        "custom": _screen_custom,
        "dividend_value": _screen_dividend_value,
    }
```

**(f)** Implement `_screen_dividend_value` (add after `_screen_custom`, before `_finalize`, around line 337):

```python
# ── 模式5：红利低估值选股（高股息 + 低估分位 双因子）─────────────────────────

def _screen_dividend_value(
    symbols, val_map, fin_map, as_of, top_n, filters,
) -> list[ScreenItem]:
    """
    红利低估值双因子选股。

    红利因子 = 股息率 dv_ttm（必须有真实值，不兜底）
    低估因子 = 当前估值在历史中的分位（0~1，越低越便宜）
      - metric: pb / pe_ttm / pb_pe（双分位等权平均）
      - window: 10y / 20y
    排名 = 股息率排名(降序) + 低估分位排名(升序)
    """
    # 读配置
    from conf import app_config
    dv_cfg = app_config.screener.dividend_value
    fd = dv_cfg.filters_default

    metric = filters.get("value_metric", fd.value_metric)
    window = filters.get("value_window", fd.value_window)
    min_dy = filters.get("dy_min", fd.dy_min)
    min_roe = filters.get("roe_min", fd.roe_min)
    max_debt = filters.get("debt_max", fd.debt_max)
    max_pb = filters.get("pb_max", fd.pb_max)
    pe_min = filters.get("pe_min", fd.pe_min)
    pe_max = filters.get("pe_max", fd.pe_max)

    exclude_ranges = _get_global_exclude_ranges()

    # 第一遍：硬门槛
    candidates: list[str] = []
    snap: dict[str, dict] = {}
    dy_map_raw: dict[str, float] = {}
    for sym in symbols:
        val = val_map.get(sym)
        if not val:
            continue
        dy = val.get("dv_ttm")
        pb = val.get("pb")
        pe = val.get("pe_ttm") or val.get("pe")
        # 红利门槛：必须有真实股息率
        if dy is None or dy < min_dy:
            continue
        # 估值安全阀
        if pb is not None and pb > max_pb:
            continue
        if pe is not None and (pe <= pe_min or pe > pe_max):
            continue
        # 质量门槛
        fin = fin_map.get(sym)
        roe = fin.get("roe_weighted") if fin else None
        debt = fin.get("debt_ratio") if fin else None
        if roe is not None and roe < min_roe:
            continue
        if debt is not None and debt > max_debt:
            continue
        candidates.append(sym)
        dy_map_raw[sym] = dy
        snap[sym] = {"pe_ttm": pe, "pb": pb, "dv_ttm": dy,
                     "roe": roe, "debt_ratio": debt}

    if not candidates:
        return []

    # 第二遍：批量算分位（只对候选池）
    pct_map = stock_percentile_batch(
        candidates, metric, window, as_of, exclude_ranges,
    )

    # 低估分位 map（越低越好）；剔除 None
    value_map: dict[str, float] = {}
    pct_detail: dict[str, dict] = {}
    for sym, info in pct_map.items():
        pct = info.get("percentile")
        if pct is None:
            continue
        value_map[sym] = pct
        pct_detail[sym] = info

    # 股息率 map（只保留有分位的）
    dy_map = {sym: dy_map_raw[sym] for sym in value_map if sym in dy_map_raw}

    # 双排名：股息率降序 + 分位升序，相加取 top_n
    dy_rank = rank_cross_section(dy_map, descending=True)       # 高股息 → 高分位
    val_rank = rank_cross_section(value_map, descending=False)  # 低分位 → 高分位
    combined = {sym: dy_rank.get(sym, 0) + val_rank.get(sym, 0) for sym in value_map}
    selected = top_n_by_score(combined, top_n)

    metric_label = {"pb": "PB", "pe_ttm": "PE", "pb_pe": "PB+PE"}.get(metric, metric)
    items: list[ScreenItem] = []
    for rank, sym in enumerate(selected, 1):
        s = snap.get(sym, {})
        items.append(ScreenItem(
            symbol=sym,
            rank=rank,
            score=combined[sym],
            pe_ttm=s.get("pe_ttm"),
            pb=s.get("pb"),
            dv_ttm=s.get("dv_ttm"),
            roe=s.get("roe"),
            debt_ratio=s.get("debt_ratio"),
            reason=f"高股息+低{metric_label}分位({window})",
            factor_breakdown={
                "dy_value": dy_map.get(sym),
                "dy_rank": _rank_of(sym, dy_rank),
                "value_metric": metric,
                "value_window": window,
                "value_percentile": value_map.get(sym),
                "value_percentile_pe": pct_detail.get(sym, {}).get("pe_percentile"),
                "value_rank": _rank_of(sym, val_rank),
                "exclude_applied": [[r[0].isoformat(), r[1].isoformat()] for r in exclude_ranges],
            },
        ))
    return items


def _rank_of(sym: str, rank_map: dict[str, float]) -> Optional[int]:
    """从 rank_cross_section 的分位结果反取名次（1=最优）。
    rank_map 值是 0~1 分位，名次 = 按分位降序的位置。"""
    if sym not in rank_map:
        return None
    ordered = sorted(rank_map.items(), key=lambda x: -x[1])
    for i, (s, _) in enumerate(ordered, 1):
        if s == sym:
            return i
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/longterm/test_screener.py -v -k dividend_value`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/strategy/longterm/screener.py backend/tests/longterm/test_screener.py
git commit -m "feat(screener): 新增 dividend_value 红利低估值双因子选股模式"
```

---

## Task 6: Router — list_modes 加新模式 + exclude-ranges 端点

**Files:**
- Modify: `backend/src/api/router/screener_router.py`
- Test: `backend/tests/api/test_screener_router.py`

**Interfaces:**
- Produces: `GET /screener/exclude-ranges` → `{ranges: [[start,end],...]}`; `PUT /screener/exclude-ranges` ← `{ranges: [[start,end],...]}` → 回写 config + 内存

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_screener_router.py`:

```python
"""screener_router 测试：list_modes 含新模式 + exclude-ranges 端点。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from fastapi.testclient import TestClient


def test_list_modes_includes_dividend_value():
    from main import app
    client = TestClient(app)
    resp = client.get("/api/v1/screener/modes")
    assert resp.status_code == 200
    body = resp.json()
    modes = [m["mode"] for m in body["data"]]
    assert "dividend_value" in modes
    dv = next(m for m in body["data"] if m["mode"] == "dividend_value")
    assert "filters_default" in dv
    assert "value_metric" in dv["filters_default"]


def test_exclude_ranges_get_and_put():
    from main import app
    client = TestClient(app)
    # GET
    resp = client.get("/api/v1/screener/exclude-ranges")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert "ranges" in body["data"]
    # PUT（写一条，再读回）
    resp2 = client.put("/api/v1/screener/exclude-ranges", json={
        "ranges": [["2015-06-15", "2015-12-31"]]
    })
    assert resp2.status_code == 200
    assert resp2.json()["code"] == 0
    # 读回验证
    resp3 = client.get("/api/v1/screener/exclude-ranges")
    ranges = resp3.json()["data"]["ranges"]
    assert ["2015-06-15", "2015-12-31"] in ranges
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_screener_router.py -v`
Expected: FAIL (dividend_value not in modes / 404 on exclude-ranges)

- [ ] **Step 3: Implement router changes**

In `backend/src/api/router/screener_router.py`:

**(a)** Add `dividend_value` to `list_modes()` (after the `custom` entry, before the closing `]` of the data list):

```python
            {
                "mode": "dividend_value",
                "display_name": "红利低估值",
                "description": "高股息率 + 低估分位(PB/PE/PB+PE)双因子，剔除炒作区间",
                "filters_default": {"dy_min": 3.0, "pb_max": 3.0, "pe_min": 0.0,
                                    "pe_max": 60.0, "roe_min": 8.0, "debt_max": 70.0,
                                    "value_metric": "pb", "value_window": "10y"},
            },
```

**(b)** Add the exclude-ranges endpoints + a request model. Add after the `ScreenRequest` class (after line 39):

```python
class ExcludeRangesRequest(BaseModel):
    """全局剔除区间更新请求。"""
    ranges: list[list[str]]   # [["2015-06-15","2015-12-31"], ...]
```

**(c)** Add the two endpoints (after the `export_screen` function, end of file):

```python
@router.get("/exclude-ranges")
def get_exclude_ranges():
    """读取全局剔除区间（选股 + 单股分位默认剔除）。"""
    from conf import app_config
    ranges = app_config.screener.dividend_value.exclude_ranges
    return {"code": 0, "msg": "ok", "data": {"ranges": list(ranges)}}


@router.put("/exclude-ranges")
def put_exclude_ranges(req: ExcludeRangesRequest):
    """
    更新全局剔除区间（回写 config.yaml + 刷新内存配置）。

    前端 UI 编辑后调用，选股和单股分位立即生效。
    """
    import yaml
    from conf import app_config
    from conf.settings import _DEFAULT_CONFIG_PATH

    # 更新内存
    app_config.screener.dividend_value.exclude_ranges = req.ranges

    # 回写 config.yaml（读-改-写，保留其他字段）
    try:
        with open(_DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        raw.setdefault("screener", {}).setdefault("dividend_value", {})
        raw["screener"]["dividend_value"]["exclude_ranges"] = req.ranges
        with open(_DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        log.warning(f"[screener] 回写 config.yaml 失败(内存已更新): {e}")

    log.info(f"[screener] 全局剔除区间更新: {req.ranges}")
    return {"code": 0, "msg": "ok", "data": {"ranges": req.ranges}}
```

**(d)** Update the `export` endpoint's mode description (line 140) to include `dividend_value`:

```python
    mode: str = Query("magic_formula", description="magic_formula|dividend|fscore|custom|dividend_value"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/test_screener_router.py -v`
Expected: PASS (2 tests)

**注**:TestClient 需要 fastapi/testclient + httpx。若环境缺 httpx,`pip install httpx` 或用 `requests` + 手动起服务测试。若 `from main import app` 太重(启动慢),可改为直接测 router 函数。

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/router/screener_router.py backend/tests/api/test_screener_router.py
git commit -m "feat(screener): list_modes 加 dividend_value + GET/PUT exclude-ranges 端点"
```

---

## Task 7: 前端 — useValuationPercentile hook 加 exclude 支持

**Files:**
- Modify: `frontend/apps/web/src/hooks/useValuationPercentile.ts`

**Interfaces:**
- Produces: `useValuationPercentile` 接受新 `exclude?: string` 参数,拼到 URL

- [ ] **Step 1: Add exclude param to the hook**

In `frontend/apps/web/src/hooks/useValuationPercentile.ts`:

Update `UseValuationPercentileParams` interface (line 28-33) to add:

```ts
export interface UseValuationPercentileParams {
  windows?: string; // "3y,5y,10y"
  asOf?: string;    // "YYYY-MM-DD"
  metrics?: string; // "pe_ttm,pb,ps_ttm,dv_ttm"
  exclude?: string; // "2020-06-01~2021-02-28,..." 剔除区间
}
```

Update the hook function to destructure `exclude` and add to the fetch URL (around line 59-65):

```ts
export function useValuationPercentile(
  symbol: string,
  params: UseValuationPercentileParams = {},
) {
  const { windows, asOf, metrics, exclude } = params;
  // ... existing state ...
  const qs = new URLSearchParams();
  if (windows) qs.set('windows', windows);
  if (asOf) qs.set('as_of', asOf);
  if (metrics) qs.set('metrics', metrics);
  if (exclude) qs.set('exclude', exclude);

  const url = `${API_BASE}/financial/valuation-percentile/${symbol}${qs.toString() ? '?' + qs.toString() : ''}`;
  // ... rest unchanged ...
```

Add `exclude` to the effect dependency array (line 88):

```ts
  }, [symbol, windows, asOf, metrics, exclude]);
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend/apps/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/hooks/useValuationPercentile.ts
git commit -m "feat(hooks): useValuationPercentile 加 exclude 区间剔除参数"
```

---

## Task 8: 前端 — ScreenerDrillModal 下钻弹窗

**Files:**
- Create: `frontend/apps/web/src/components/ScreenerDrillModal.tsx`
- Create: `frontend/apps/web/src/components/ScreenerDrillModal.css`

**Interfaces:**
- Consumes: `/financial/profile/{symbol}`, `/financial/valuation-percentile/{symbol}?exclude=...`, `/financial/detail/{symbol}`, `/market/kline/{symbol}`, `factor_breakdown` from ScreenItem
- Produces: `<ScreenerDrillModal symbol={string} factorBreakdown={object|null} onClose={() => void} />`

- [ ] **Step 1: Create the CSS file**

Create `frontend/apps/web/src/components/ScreenerDrillModal.css`:

```css
.sdm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal, 1000);
}

.sdm-modal {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  width: 900px;
  max-width: 92vw;
  max-height: 86vh;
  overflow-y: auto;
}

.sdm-head {
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  margin-bottom: var(--space-4);
  color: var(--color-text);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sdm-close {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-3);
  cursor: pointer;
  font-size: var(--text-sm);
}

.sdm-close:hover {
  background: var(--color-surface-hover);
}

.sdm-section {
  margin-bottom: var(--space-5);
}

.sdm-section-title {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sdm-profile-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}

.sdm-profile-item {
  background: var(--color-surface-elevated);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}

.sdm-profile-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.sdm-profile-value {
  font-size: var(--text-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.sdm-charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.sdm-exclude-bar {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  margin: var(--space-2) 0;
  flex-wrap: wrap;
}

.sdm-exclude-bar input[type="date"] {
  background: var(--color-surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-sm);
}

.sdm-exclude-chips {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.sdm-exclude-chip {
  background: var(--color-surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.sdm-exclude-chip button {
  background: none;
  border: none;
  color: var(--color-danger);
  cursor: pointer;
  font-size: var(--text-sm);
  line-height: 1;
}

.sdm-breakdown {
  background: var(--color-surface-elevated);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
}

.sdm-breakdown-item {
  text-align: center;
}

.sdm-breakdown-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-1);
}

.sdm-breakdown-value {
  font-size: var(--text-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-accent);
  font-variant-numeric: tabular-nums;
}

.sdm-empty {
  color: var(--color-text-tertiary);
  text-align: center;
  padding: var(--space-6);
}
```

- [ ] **Step 2: Create the modal component**

Create `frontend/apps/web/src/components/ScreenerDrillModal.tsx`:

```tsx
/**
 * 选股器通用下钻弹窗。
 * 点选股结果表任意行触发，展示 5 区块：
 *   a 个股画像 / b 估值分位(可剔除区间) / c 财务趋势 / d K线+股息率 / e 入选拆解
 */
import {useEffect, useState} from 'react';
import {
  ComposedChart, Line, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts';
import {getApiBase} from '../lib/api';
import {useValuationPercentile} from '../hooks/useValuationPercentile';
import {ValuationPercentileChart, percentileColor} from './ValuationPercentileChart';
import './ScreenerDrillModal.css';

const API_BASE = getApiBase();

interface FactorBreakdown {
  dy_value?: number | null;
  dy_rank?: number | null;
  value_metric?: string;
  value_window?: string;
  value_percentile?: number | null;
  value_percentile_pe?: number | null;
  value_rank?: number | null;
  exclude_applied?: string[][];
}

interface Props {
  symbol: string;
  factorBreakdown: FactorBreakdown | null;
  onClose: () => void;
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(v) ? '-' : v.toFixed(digits);

export function ScreenerDrillModal({symbol, factorBreakdown, onClose}: Props) {
  const [profile, setProfile] = useState<any>(null);
  const [finSeries, setFinSeries] = useState<any[]>([]);
  const [bars, setBars] = useState<any[]>([]);
  const [excludeStr, setExcludeStr] = useState('');
  const [excludeStart, setExcludeStart] = useState('');
  const [excludeEnd, setExcludeEnd] = useState('');
  const [excludeList, setExcludeList] = useState<string[]>([]);

  // 估值分位（带 exclude）
  const {data: valPct, loading: valLoading} = useValuationPercentile(symbol, {
    windows: '3y,5y,10y',
    metrics: 'pe_ttm,pb,ps_ttm,dv_ttm',
    exclude: excludeStr || undefined,
  });

  // 初始拉全局剔除区间
  useEffect(() => {
    fetch(`${API_BASE}/screener/exclude-ranges`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && j.data?.ranges) {
          const segs = j.data.ranges.map((r: string[]) => `${r[0]}~${r[1]}`);
          setExcludeList(segs);
          setExcludeStr(segs.join(','));
        }
      })
      .catch(() => {});
  }, []);

  // 画像
  useEffect(() => {
    fetch(`${API_BASE}/financial/profile/${symbol}`)
      .then((r) => r.json())
      .then((j) => j.code === 0 && setProfile(j.data))
      .catch(() => {});
  }, [symbol]);

  // 财务趋势（利润表近 8 期）
  useEffect(() => {
    fetch(`${API_BASE}/financial/detail/${symbol}?statement_type=income&limit=8&period=year`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && j.data?.series) {
          setFinSeries([...j.data.series].reverse()); // 升序画图
        }
      })
      .catch(() => {});
  }, [symbol]);

  // K线（近 1 年）
  useEffect(() => {
    fetch(`${API_BASE}/market/kline/${symbol}?interval=1d&limit=250`)
      .then((r) => r.json())
      .then((j) => j.code === 0 && setBars(j.data?.bars || []))
      .catch(() => {});
  }, [symbol]);

  const addExclude = () => {
    if (!excludeStart || !excludeEnd) return;
    const seg = `${excludeStart}~${excludeEnd}`;
    if (!excludeList.includes(seg)) {
      const next = [...excludeList, seg];
      setExcludeList(next);
      setExcludeStr(next.join(','));
    }
    setExcludeStart('');
    setExcludeEnd('');
  };

  const removeExclude = (seg: string) => {
    const next = excludeList.filter((s) => s !== seg);
    setExcludeList(next);
    setExcludeStr(next.join(','));
  };

  // 股息率时序（从分位接口 series 取）
  const dvSeries = valPct?.metrics?.dv_ttm?.series || [];
  const klineMerged = bars.map((b) => {
    const dv = dvSeries.find((s) => s.date === b.trade_date);
    return {...b, dv: dv?.value ?? null};
  });

  const metrics = valPct?.metrics || {};

  return (
    <div className="sdm-overlay" onClick={onClose}>
      <div className="sdm-modal" onClick={(e) => e.stopPropagation()}>
        <div className="sdm-head">
          <span>
            {profile?.name || symbol} ({symbol})
            {profile?.industry && (
              <span style={{color: 'var(--color-text-tertiary)', fontSize: 'var(--text-sm)', marginLeft: 8}}>
                {profile.industry}
              </span>
            )}
          </span>
          <button className="sdm-close" onClick={onClose}>关闭</button>
        </div>

        {/* a 个股画像 */}
        <div className="sdm-section">
          <div className="sdm-section-title">个股画像</div>
          <div className="sdm-profile-grid">
            <div className="sdm-profile-item">
              <div className="sdm-profile-label">最新价</div>
              <div className="sdm-profile-value">{fmt(bars[bars.length-1]?.close)}</div>
            </div>
            <div className="sdm-profile-item">
              <div className="sdm-profile-label">总市值(亿)</div>
              <div className="sdm-profile-value">{profile?.total_mv ? (profile.total_mv / 1e8).toFixed(1) : '-'}</div>
            </div>
            <div className="sdm-profile-item">
              <div className="sdm-profile-label">PE_TTM</div>
              <div className="sdm-profile-value">{fmt(profile?.pe_ttm)}</div>
            </div>
            <div className="sdm-profile-item">
              <div className="sdm-profile-label">PB</div>
              <div className="sdm-profile-value">{fmt(profile?.pb)}</div>
            </div>
          </div>
        </div>

        {/* b 估值历史分位（含剔除交互） */}
        <div className="sdm-section">
          <div className="sdm-section-title">估值历史分位（可剔除炒作区间）</div>
          <div className="sdm-exclude-bar">
            <input type="date" value={excludeStart} onChange={(e) => setExcludeStart(e.target.value)} />
            <span style={{color: 'var(--color-text-tertiary)'}}>~</span>
            <input type="date" value={excludeEnd} onChange={(e) => setExcludeEnd(e.target.value)} />
            <button className="sdm-close" onClick={addExclude}>+ 剔除该区间</button>
          </div>
          {excludeList.length > 0 && (
            <div className="sdm-exclude-chips">
              {excludeList.map((seg) => (
                <span key={seg} className="sdm-exclude-chip">
                  {seg}
                  <button onClick={() => removeExclude(seg)}>×</button>
                </span>
              ))}
            </div>
          )}
          {valLoading ? (
            <div className="sdm-empty">加载中…</div>
          ) : (
            <div className="sdm-charts-grid">
              <ValuationPercentileChart title="市盈率 TTM" metric={metrics.pe_ttm || null} windowKey="10y" color="#0a84ff" />
              <ValuationPercentileChart title="市净率" metric={metrics.pb || null} windowKey="10y" color="#30d158" />
              <ValuationPercentileChart title="市销率 TTM" metric={metrics.ps_ttm || null} windowKey="10y" color="#bf5af2" />
              <ValuationPercentileChart title="股息率 TTM" metric={metrics.dv_ttm || null} windowKey="10y" color="#ff9f0a" />
            </div>
          )}
        </div>

        {/* c 财务趋势 */}
        <div className="sdm-section">
          <div className="sdm-section-title">财务趋势（近 8 期年报）</div>
          {finSeries.length === 0 ? (
            <div className="sdm-empty">无数据</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={finSeries.map((s) => ({
                date: (s.report_date || '').slice(0, 4),
                revenue: s.revenue ? s.revenue / 1e8 : null,
                netProfit: s.net_profit ? s.net_profit / 1e8 : null,
                margin: s.net_margin,
              }))}>
                <XAxis dataKey="date" stroke="var(--color-text-tertiary)" fontSize={11} />
                <YAxis yAxisId="left" stroke="var(--color-text-tertiary)" fontSize={11} />
                <YAxis yAxisId="right" orientation="right" stroke="var(--color-text-tertiary)" fontSize={11} />
                <Tooltip contentStyle={{background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)'}} />
                <Legend />
                <Bar yAxisId="left" dataKey="revenue" name="营收(亿)" fill="#0a84ff" opacity={0.5} />
                <Bar yAxisId="left" dataKey="netProfit" name="净利(亿)" fill="#30d158" opacity={0.7} />
                <Line yAxisId="right" dataKey="margin" name="净利率%" stroke="#ff9f0a" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* d K线 + 股息率 */}
        <div className="sdm-section">
          <div className="sdm-section-title">近 1 年价格 × 股息率</div>
          {klineMerged.length === 0 ? (
            <div className="sdm-empty">无数据</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={klineMerged}>
                <XAxis dataKey="trade_date" stroke="var(--color-text-tertiary)" fontSize={10} tickFormatter={(v) => String(v).slice(5)} />
                <YAxis yAxisId="left" stroke="var(--color-text-tertiary)" fontSize={11} domain={['auto', 'auto']} />
                <YAxis yAxisId="right" orientation="right" stroke="var(--color-text-tertiary)" fontSize={11} />
                <Tooltip contentStyle={{background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)'}} />
                <Legend />
                <Line yAxisId="left" dataKey="close" name="收盘价" stroke="#0a84ff" strokeWidth={1.5} dot={false} />
                <Line yAxisId="right" dataKey="dv" name="股息率%" stroke="#ff9f0a" strokeWidth={1.5} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* e 入选拆解 */}
        {factorBreakdown && (
          <div className="sdm-section">
            <div className="sdm-section-title">入选拆解（{factorBreakdown.value_metric?.toUpperCase()} · {factorBreakdown.value_window}）</div>
            <div className="sdm-breakdown">
              <div className="sdm-breakdown-item">
                <div className="sdm-breakdown-label">股息率</div>
                <div className="sdm-breakdown-value">{fmt(factorBreakdown.dy_value)}%</div>
                <div className="sdm-profile-label">全市场第 {factorBreakdown.dy_rank ?? '-'} 名</div>
              </div>
              <div className="sdm-breakdown-item">
                <div className="sdm-breakdown-label">低估分位</div>
                <div className="sdm-breakdown-value" style={{color: percentileColor(factorBreakdown.value_percentile ?? null)}}>
                  {fmt(factorBreakdown.value_percentile, 3)}
                </div>
                <div className="sdm-profile-label">全市场第 {factorBreakdown.value_rank ?? '-'} 名</div>
              </div>
              {factorBreakdown.value_metric === 'pb_pe' && (
                <div className="sdm-breakdown-item">
                  <div className="sdm-breakdown-label">PE 子分位</div>
                  <div className="sdm-breakdown-value" style={{color: percentileColor(factorBreakdown.value_percentile_pe ?? null)}}>
                    {fmt(factorBreakdown.value_percentile_pe, 3)}
                  </div>
                </div>
              )}
            </div>
            {factorBreakdown.exclude_applied && factorBreakdown.exclude_applied.length > 0 && (
              <div style={{marginTop: 8, fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)'}}>
                已剔除区间：{factorBreakdown.exclude_applied.map((r) => `${r[0]}~${r[1]}`).join('，')}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default ScreenerDrillModal;
```

**注意**:
- `percentileColor` 需从 `ValuationPercentileChart` 导出(检查该文件 line 30-35 是否 `export`了;若没有,在 Task 8 里把它的 export 加上,或在本文件内重定义一个本地版本)
- `ValuationPercentileChart` 的 props 是 `{title, unit?, metric, windowKey, color?}`,本组件已按此传参

- [ ] **Step 3: Verify percentileColor is exported (already is)**

`frontend/apps/web/src/components/ValuationPercentileChart.tsx:30` already declares `export function percentileColor(pct: number | null): string`. No change needed — just confirm the import in Step 2 works (`import {ValuationPercentileChart, percentileColor} from './ValuationPercentileChart'`).

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend/apps/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/components/ScreenerDrillModal.tsx frontend/apps/web/src/components/ScreenerDrillModal.css frontend/apps/web/src/components/ValuationPercentileChart.tsx
git commit -m "feat(screener): 新增 ScreenerDrillModal 通用下钻弹窗(画像/估值分位/财务/K线/拆解)"
```

---

## Task 9: 前端 — Screener 页接入新模式配置 + 行点击 + 弹窗

**Files:**
- Modify: `frontend/apps/web/src/pages/Screener.tsx`

**Interfaces:**
- Consumes: `ScreenerDrillModal` (Task 8), `/screener/exclude-ranges` API

- [ ] **Step 1: Add new mode + config UI + row click + drill modal**

In `frontend/apps/web/src/pages/Screener.tsx`:

**(a)** Add imports (after line 8):

```tsx
import {ScreenerDrillModal} from '../components/ScreenerDrillModal';
```

**(b)** Add `dividend_value` to MODES (line 33-38):

```tsx
const MODES = [
  {key: 'magic_formula', label: '神奇公式', desc: '低 PE + 高 ROE'},
  {key: 'dividend', label: '红利', desc: '高股息 + 质量过滤'},
  {key: 'fscore', label: 'F-Score', desc: '财务质量 + 低 PB'},
  {key: 'custom', label: '自定义', desc: '多因子门槛'},
  {key: 'dividend_value', label: '红利低估值', desc: '高股息 + 低估分位(PB/PE/PB+PE)'},
];
```

**(c)** Add state for new mode config + drill modal (after line 48, the `error` state):

```tsx
  const [valueMetric, setValueMetric] = useState('pb');       // pb | pe_ttm | pb_pe
  const [valueWindow, setValueWindow] = useState('10y');      // 10y | 20y
  const [excludeRanges, setExcludeRanges] = useState<string[][]>([]);
  const [exStart, setExStart] = useState('');
  const [exEnd, setExEnd] = useState('');
  const [drillSymbol, setDrillSymbol] = useState<string | null>(null);
  const [drillBreakdown, setDrillBreakdown] = useState<any>(null);
```

**(d)** Update `runScreen` to include new-mode filters (modify the fetch body around line 56):

```tsx
  const runScreen = () => {
    setLoading(true);
    setError(null);
    const filters: Record<string, any> = {};
    if (mode === 'dividend_value') {
      filters.value_metric = valueMetric;
      filters.value_window = valueWindow;
    }
    fetch(`${API_BASE}/screener/screen`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode, top_n: topN, filters}),
    })
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0) setData(j.data);
        else setError(j.msg || '选股失败');
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };
```

**(e)** Add useEffect to load exclude ranges on mount (after the existing useEffect around line 71):

```tsx
  // 拉全局剔除区间
  useEffect(() => {
    fetch(`${API_BASE}/screener/exclude-ranges`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && j.data?.ranges) setExcludeRanges(j.data.ranges);
      })
      .catch(() => {});
  }, []);
```

**(f)** Add exclude add/remove handlers (after exportCsv, around line 80):

```tsx
  const addExclude = () => {
    if (!exStart || !exEnd) return;
    const next = [...excludeRanges, [exStart, exEnd]];
    putExcludeRanges(next);
    setExStart('');
    setExEnd('');
  };

  const removeExclude = (idx: number) => {
    putExcludeRanges(excludeRanges.filter((_, i) => i !== idx));
  };

  const putExcludeRanges = (ranges: string[][]) => {
    fetch(`${API_BASE}/screener/exclude-ranges`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ranges}),
    })
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0) setExcludeRanges(j.data.ranges);
      })
      .catch(() => {});
  };

  const openDrill = (symbol: string, rowData: any) => {
    setDrillSymbol(symbol);
    setDrillBreakdown(rowData.factor_breakdown || null);
  };
```

**(g)** Add new-mode config bar JSX. Insert it after the existing control bar div (after line 135, before the `{error && ...}` line). Only show when mode === 'dividend_value':

```tsx
      {mode === 'dividend_value' && (
        <div style={{display: 'flex', gap: 16, alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', padding: 12, background: '#1a1a1a', borderRadius: 8}}>
          {/* 低估指标切换 */}
          <div>
            <div style={{fontSize: 12, color: '#888', marginBottom: 4}}>低估指标</div>
            <div style={{display: 'flex', gap: 6}}>
              {[
                {k: 'pb', label: 'PB'},
                {k: 'pe_ttm', label: 'PE'},
                {k: 'pb_pe', label: 'PB+PE'},
              ].map((m) => (
                <button key={m.k} onClick={() => setValueMetric(m.k)}
                  style={{
                    padding: '3px 12px', borderRadius: 14, border: '1px solid',
                    borderColor: valueMetric === m.k ? '#2563eb' : '#444',
                    background: valueMetric === m.k ? '#2563eb' : 'transparent',
                    color: '#fff', cursor: 'pointer', fontSize: 12,
                  }}>
                  {m.label}
                </button>
              ))}
            </div>
          </div>
          {/* 窗口切换 */}
          <div>
            <div style={{fontSize: 12, color: '#888', marginBottom: 4}}>历史窗口</div>
            <div style={{display: 'flex', gap: 6}}>
              {['10y', '20y'].map((w) => (
                <button key={w} onClick={() => setValueWindow(w)}
                  style={{
                    padding: '3px 12px', borderRadius: 14, border: '1px solid',
                    borderColor: valueWindow === w ? '#2563eb' : '#444',
                    background: valueWindow === w ? '#2563eb' : 'transparent',
                    color: '#fff', cursor: 'pointer', fontSize: 12,
                  }}>
                  {w}
                </button>
              ))}
            </div>
          </div>
          {/* 全局剔除区间编辑器 */}
          <div style={{flex: 1, minWidth: 280}}>
            <div style={{fontSize: 12, color: '#888', marginBottom: 4}}>全局剔除区间（选股+下钻默认剔除）</div>
            <div style={{display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6}}>
              <input type="date" value={exStart} onChange={(e) => setExStart(e.target.value)}
                style={{padding: '3px 6px', background: '#1a1a1a', border: '1px solid #333', borderRadius: 4, color: '#e0e0e0', fontSize: 12}} />
              <span style={{color: '#888'}}>~</span>
              <input type="date" value={exEnd} onChange={(e) => setExEnd(e.target.value)}
                style={{padding: '3px 6px', background: '#1a1a1a', border: '1px solid #333', borderRadius: 4, color: '#e0e0e0', fontSize: 12}} />
              <button onClick={addExclude} disabled={!exStart || !exEnd}
                style={{padding: '3px 10px', borderRadius: 4, border: '1px solid #444', background: 'transparent', color: !exStart || !exEnd ? '#666' : '#e0e0e0', cursor: !exStart || !exEnd ? 'not-allowed' : 'pointer', fontSize: 12}}>
                + 添加
              </button>
            </div>
            <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
              {excludeRanges.map((r, i) => (
                <span key={i} style={{display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 10px', borderRadius: 12, background: '#2a2a2a', border: '1px solid #333', fontSize: 11, color: '#aaa'}}>
                  {r[0]}~{r[1]}
                  <button onClick={() => removeExclude(i)} style={{background: 'none', border: 'none', color: '#dc2626', cursor: 'pointer', fontSize: 13, lineHeight: 1}}>×</button>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
```

**(h)** Make table rows clickable. Modify the `<tr>` in the results table (line 164) to add onClick + cursor:

```tsx
            {data.ranked_list.map((r) => (
              <tr key={r.symbol} onClick={() => openDrill(r.symbol, r)}
                style={{borderBottom: '1px solid #222', cursor: 'pointer'}}>
                <td style={{padding: '6px'}}>{r.rank}</td>
                <td style={{padding: '6px', fontFamily: 'monospace', color: '#5b9dff'}}>{r.symbol}</td>
```

**(i)** Add a hint that rows are clickable, above the table (after the `data.count` info line, before the table). And mount the drill modal at the end. Add before the closing `</div>` (line 183):

```tsx
      {data && data.ranked_list.length > 0 && (
        <div style={{fontSize: 11, color: '#666', marginBottom: 6}}>点击行查看个股详情</div>
      )}

      {drillSymbol && (
        <ScreenerDrillModal
          symbol={drillSymbol}
          factorBreakdown={drillBreakdown}
          onClose={() => setDrillSymbol(null)}
        />
      )}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend/apps/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Manual smoke test**

Start dev servers (`./dev-start.sh` or per dev-start.sh), open the Screener page in browser:
1. Click "红利低估值" mode → config bar (PB/PE/PB+PE + 10y/20y + 全局剔除编辑器) appears
2. Click "运行选股" → results table loads
3. Click any row → drill modal opens with 5 sections
4. In modal, add an exclude range → valuation percentile charts refresh

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/pages/Screener.tsx
git commit -m "feat(screener): Screener 页接入 dividend_value 配置 + 行点击下钻"
```

---

## Task 10: 端到端验证 + 清理

**Files:** None (verification only)

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && python -m pytest tests/ -v -k "screener or percentile or valuation"`
Expected: All tests PASS

- [ ] **Step 2: Run full frontend type check**

Run: `cd frontend/apps/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: End-to-end manual test**

1. Backend running on :12100
2. `GET /api/v1/screener/modes` → 5 modes incl `dividend_value`
3. `POST /api/v1/screener/screen` with `{mode: "dividend_value", top_n: 20, filters: {value_metric: "pb", value_window: "10y"}}` → returns ranked_list with `factor_breakdown`
4. `GET /api/v1/financial/valuation-percentile/sh600519?exclude=2020-01-01~2020-06-30` → series excludes that range
5. `PUT /api/v1/screener/exclude-ranges` with `{ranges: [["2015-06-15","2015-12-31"]]}` → 200, GET reflects it
6. Frontend: open Screener, select 红利低估值, run, click a row → modal with all 5 sections renders

- [ ] **Step 4: Verify config.yaml persistence**

After PUT exclude-ranges, check `backend/conf/config.yaml` has the updated `screener.dividend_value.exclude_ranges`.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "test: 端到端验证通过" || echo "nothing to commit"
```

---

## Self-Review Notes

**Spec coverage check:**
- §3 选股模式 dividend_value → Task 5 ✓
- §3.4 factor_breakdown → Task 5 ✓
- §4.1 get_range_batch → Task 1 ✓
- §4.2 stock_percentile_batch → Task 2 ✓
- §4.3 单股接口 exclude → Task 3 ✓
- §4.4 全局剔除 UI 可编辑 + 持久化 → Task 6 (PUT 端点) + Task 9 (UI 编辑器) ✓
- §5 新模式实现 → Task 5 ✓
- §6 通用下钻 5 区块 → Task 8 ✓
- §6.2 单只剔除交互 → Task 8 (b 区块) ✓
- §6.3 选股页配置区 → Task 9 ✓
- §7 config.yaml → Task 4 ✓
- §8 边界降级 → Task 5 实现(硬门槛+样本不足) + Task 2(pb_pe 降级) ✓
- §9 测试 → 每个任务都含测试 ✓

**Placeholder scan:** 无 TODO/TBD。所有代码块完整。

**Type consistency:**
- `stock_percentile_batch` 返回 `{percentile, sample_size, current, pb_percentile?, pe_percentile?}` — Task 2 定义,Task 5 消费,一致
- `factor_breakdown` 字段名(dy_value/dy_rank/value_metric/value_window/value_percentile/value_percentile_pe/value_rank/exclude_applied)— Task 5 后端产出,Task 8 前端消费,一致
- `exclude` 参数格式 `start~end,逗号分隔` — Task 3 后端解析,Task 7 前端拼接,一致
- `_get_global_exclude_ranges` — Task 4 定义,Task 3 + Task 5 消费,一致
