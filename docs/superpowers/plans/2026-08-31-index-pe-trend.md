# 指数整体法市盈率趋势 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 沪深300/中证500/中证1000（实为全部 9 个已配置宽基）的整体法市盈率月度序列 + 窗口均值/±σ 参考线，落库 `index_valuation_daily.pe_ttm` 并在 Indices 页出图。

**Architecture:** 复用 mcg 数据链——`index_financial_quarterly`（累计归母净利和）经披露门控 + `to_ttm` 换 TTM，与 mcg 市值回填 job 已算好的月末成分股总市值和相除得 PE，同 job 同行写入 `index_valuation_daily`（source='computed'）；新端点只读表，前端 Indices 页 mcg 区块旁新增 section。

**Tech Stack:** FastAPI + SQLModel/psycopg2（Postgres，无 Alembic）；pytest（子集）；React + recharts + chartTheme 令牌；后端包管理 uv。

**Spec:** `docs/superpowers/specs/2026-08-31-index-pe-trend-design.md`

## Global Constraints

- 单位：市值/净利一律**亿元**；DB 中 `total_mv` 保留 4 位、`pe_ttm` 保留 2 位小数。
- 门控常数 0.8（新模块 `DISCLOSE_MIN_RATIO`；不改 mcg 既有 `MIN_COVER_RATIO`/`_MCG_DISCLOSE_MIN_RATIO`）。
- 响应信封：`responses.success/fail`（HTTP 200 + code=0/1）；前端判 `json.code === 0`。
- 前端图表只用 `chartTheme` 令牌；参考线配色：均值=黄 `colorWarning`、高估=红 `colorUp`、低估=绿 `colorDown`。（Spec 勘误：spec 写固定色 `#eab308`，实际 chartTheme 已有黄令牌 `colorWarning=#ffd60a`，用令牌。）
- 不改表结构（`pe_ttm` 列已存在）、不改调度（job 内部扩展，仍挂 `index_panorama_weekly` 周六链）。
- 后端测试只跑本计划子集（全量回归有既有失败，见项目记忆）；flake8 未装不用跑。
- **工作区有用户其他未提交改动**：每次 commit 只 `git add` 本任务 Files 列出的路径，禁止 `git add -A`。
- 后端命令一律在 `backend/` 目录下 `uv run …`；前端命令在 `frontend/` 目录下。

---

### Task 1: 域纯函数模块 `index_pe.py`

**Files:**
- Create: `backend/src/domain/market/fundamental/index_pe.py`
- Test: `backend/tests/domain/market/fundamental/test_index_pe.py`

**Interfaces:**
- Consumes: `to_ttm(rows)`（`market_cap_growth.py:69`，输入 `[{report_date, revenue, net_profit}]` 累计序列，缺键→None 传播）。
- Produces（Task 2/3 依赖，签名精确如下）:
  - `DISCLOSE_MIN_RATIO = 0.8`
  - `gate_by_sample_count(rows: list[dict], min_ratio=DISCLOSE_MIN_RATIO) -> list[dict]`；入出同形 `[{report_date, net_profit, sample_count}]`，门控期 `net_profit=None`
  - `compute_index_pe(monthly_mv: list[dict], cum_rows: list[dict], min_ratio=DISCLOSE_MIN_RATIO) -> list[dict]`；monthly_mv 元素 `{date: date|str, total_mv: float}`（亿），cum_rows 元素 `{report_date: date|str, net_profit: float|None, sample_count: int}`（亿，累计）；返回 `[{date: "YYYY-MM-DD", pe: float|None}]` 升序
  - `mean_std(values) -> dict | None`：`{mean, std, sample_size}`（总体标准差），非数值剔除，样本 <2 → None

- [ ] **Step 1: Write the failing tests**

创建 `backend/tests/domain/market/fundamental/test_index_pe.py`：

```python
"""index_pe 纯函数单测（手算锁定，模式同 test_market_cap_growth.py）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.domain.market.fundamental.index_pe import (
    compute_index_pe,
    gate_by_sample_count,
    mean_std,
)


def _cum(rd, np_, cnt):
    return {"report_date": rd, "net_profit": np_, "sample_count": cnt}


# ── gate_by_sample_count ────────────────────────────────────────────

def test_gate_hides_partial_disclosure():
    rows = [
        _cum("2025-12-31", 6.0, 300),
        _cum("2026-03-31", 1.4, 300),
        _cum("2026-06-30", 0.5, 34),   # 中报仅 34/300 披露
    ]
    out = gate_by_sample_count(rows)
    assert out[2]["net_profit"] is None
    assert out[0]["net_profit"] == 6.0


def test_gate_boundary_80pct_kept():
    rows = [
        _cum("2025-12-31", 6.0, 300),
        _cum("2026-06-30", 2.5, 240),  # 恰好 80% → 保留
    ]
    assert gate_by_sample_count(rows)[1]["net_profit"] == 2.5


# ── compute_index_pe ────────────────────────────────────────────────

# 累计净利（亿）：FY2022=6.0、2022Q1=0.9、2023Q1=1.0、FY2023=7.0、2024Q1=1.4
# TTM：2023Q1=6.0+1.0−0.9=6.1；FY2023=7.0；2024Q1=7.0+1.4−1.0=7.4
CUM = [
    _cum("2022-03-31", 0.9, 300),
    _cum("2022-12-31", 6.0, 300),
    _cum("2023-03-31", 1.0, 300),
    _cum("2023-12-31", 7.0, 300),
    _cum("2024-03-31", 1.4, 300),
]


def test_compute_pe_ttm_and_align():
    monthly = [
        {"date": "2022-02-28", "total_mv": 6000.0},  # 早于首报告期 → None
        {"date": "2023-04-28", "total_mv": 6100.0},  # 2023Q1 TTM 6.1 → 1000
        {"date": "2024-02-28", "total_mv": 7000.0},  # FY2023 7.0 → 1000
        {"date": "2024-04-30", "total_mv": 7400.0},  # 2024Q1 TTM 7.4 → 1000
    ]
    out = compute_index_pe(monthly, CUM)
    assert [p["pe"] for p in out] == [None, 1000.0, 1000.0, 1000.0]
    assert out[0]["date"] == "2022-02-28"


def test_compute_pe_disclosure_gap_breaks_line():
    cum = [
        _cum("2025-03-31", 1.0, 300),
        _cum("2025-06-30", 2.0, 300),
        _cum("2025-12-31", 6.0, 300),
        _cum("2026-03-31", 1.4, 300),
        _cum("2026-06-30", 0.5, 34),   # 门控：若无门控 TTM=6.0+0.5−2.0=4.5
    ]
    monthly = [
        {"date": "2026-05-31", "total_mv": 6400.0},  # 2026Q1 TTM=6.0+1.4−1.0=6.4
        {"date": "2026-07-31", "total_mv": 4500.0},  # 2026中报被门控 → 断线
    ]
    out = compute_index_pe(monthly, cum)
    assert out[0]["pe"] == 1000.0
    assert out[1]["pe"] is None


def test_compute_pe_nonpositive_profit_none():
    cum = [_cum("2023-12-31", -2.0, 300)]   # 年报 TTM=全年=−2.0（亏损）
    out = compute_index_pe([{"date": "2024-02-28", "total_mv": 5000.0}], cum)
    assert out[0]["pe"] is None


# ── mean_std ────────────────────────────────────────────────────────

def test_mean_std():
    ms = mean_std([1, 2, 3])
    assert ms["mean"] == 2.0
    assert abs(ms["std"] - 0.816496580927726) < 1e-9   # pstdev([1,2,3])=√(2/3)
    assert ms["sample_size"] == 3
    assert mean_std([1]) is None
    assert mean_std([1, None, "x", 3])["sample_size"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/domain/market/fundamental/test_index_pe.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.domain.market.fundamental.index_pe'`（收集错误）。

- [ ] **Step 3: Write the implementation**

创建 `backend/src/domain/market/fundamental/index_pe.py`：

```python
"""指数整体法市盈率（纯函数）。

口径：PE = 成分股总市值和 ÷ 成分股 TTM 归母净利和（整体法）。
输入与 mcg 数据链同源同单位（亿元）。零 IO、dict 进出、不抛异常
（模块惯例同 market_cap_growth）。

披露断档语义：部分披露期（财报季 sample_count 不足）净利被门控置
None，经 to_ttm 传播——该期起至下一期完整披露前 PE 断线（pe=None），
周度任务随披露完善自动回填。
"""
from statistics import fmean, pstdev

from src.domain.market.fundamental.market_cap_growth import to_ttm

# 披露率门控：期样本数低于序列满覆盖的该比例 → 该期净利置 None
# （常数/语义同 financial_detail_handler._MCG_DISCLOSE_MIN_RATIO）
DISCLOSE_MIN_RATIO = 0.8


def gate_by_sample_count(rows: list[dict],
                         min_ratio: float = DISCLOSE_MIN_RATIO) -> list[dict]:
    """[{report_date, net_profit, sample_count}] → 同形列表。

    以序列内 max(sample_count) 为满覆盖基准，不足比例的期 net_profit
    置 None（None 经 to_ttm 传播到依赖期）。
    """
    max_cnt = max((r.get("sample_count") or 0 for r in rows), default=0)
    out = []
    for r in rows:
        partial = (max_cnt > 0
                   and (r.get("sample_count") or 0) < min_ratio * max_cnt)
        out.append({
            **r,
            "net_profit": None if partial else r.get("net_profit"),
        })
    return out


def compute_index_pe(monthly_mv: list[dict], cum_rows: list[dict],
                     min_ratio: float = DISCLOSE_MIN_RATIO) -> list[dict]:
    """月末市值点 × 累计净利序列 → 整体法 PE 月度序列。

    Args:
        monthly_mv: [{date: date|str, total_mv: float}]（亿，mcg 覆盖率
            门控后的月末点）。无市值/无日期的点跳过。
        cum_rows: [{report_date: date|str, net_profit: float|None,
            sample_count: int}]（亿，累计归母净利和）。
    Returns: [{date: "YYYY-MM-DD", pe: float|None}] 升序；
        TTM 净利缺失或 ≤0 → pe None。
    """
    ttm_rows = to_ttm([
        {"report_date": r.get("report_date"),
         "revenue": None,
         "net_profit": r.get("net_profit")}
        for r in gate_by_sample_count(cum_rows, min_ratio)
    ])
    reports = sorted(
        (str(r["report_date"])[:10], r["net_profit"])
        for r in ttm_rows if r.get("report_date") is not None
    )
    pts = sorted(
        (str(p["date"])[:10], p["total_mv"])
        for p in monthly_mv
        if p.get("date") is not None and p.get("total_mv") is not None
    )
    out = []
    j = 0
    cur_np = None
    for d_str, mv in pts:
        # 双指针：报告期 YYYY-MM ≤ 当月即视为已知（与 align_mv 同粒度语义）
        while j < len(reports) and reports[j][0][:7] <= d_str[:7]:
            cur_np = reports[j][1]
            j += 1
        pe = None
        if isinstance(cur_np, (int, float)) and cur_np > 0:
            pe = mv / cur_np
        out.append({"date": d_str, "pe": pe})
    return out


def mean_std(values) -> dict | None:
    """数值统计：{mean, std, sample_size}（总体标准差）；样本<2 → None。"""
    xs = [float(v) for v in values if isinstance(v, (int, float))]
    if len(xs) < 2:
        return None
    return {"mean": fmean(xs), "std": pstdev(xs), "sample_size": len(xs)}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/domain/market/fundamental/test_index_pe.py -v
```
Expected: 8 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/index_pe.py backend/tests/domain/market/fundamental/test_index_pe.py
git commit -m "feat(index-pe): 整体法PE纯函数——披露门控×to_ttm×月末对齐+均值/σ统计"
```

---

### Task 2: repo 扩列 + 市值回填 job 同 pass 算 PE 落库

**Files:**
- Modify: `backend/src/infra/database/market/index_valuation.py:155-180`（`bulk_upsert_index_mv`）
- Modify: `backend/src/domain/market/sync/jobs/index_market_cap_sync.py`（docstring + `sync_index_market_cap`）

**Interfaces:**
- Consumes: Task 1 `compute_index_pe(monthly_mv, cum_rows)`；`IndexFinancialRepository.get_series(scope_type, scope_code, start=None, end=None)`（index_financial.py:80，返回升序，`report_date/revenue_sum/net_profit_sum/sample_count`，单位亿）。
- Produces: `bulk_upsert_index_mv(rows)` 的 rows 每项新增可选键 `pe_ttm`（float|None）；`index_valuation_daily` 表 `pe_ttm` 列开始有 index 口径写入方（月末点、source='computed'）。返回值形状不变（`{index_code: mv点数}`），pe 点数进日志。

- [ ] **Step 1: 扩展 `bulk_upsert_index_mv` 写 pe_ttm**

`backend/src/infra/database/market/index_valuation.py` 中 `bulk_upsert_index_mv`（:155）整个方法替换为：

```python
    def bulk_upsert_index_mv(self, rows: list[dict]) -> int:
        """写 total_mv/pe_ttm 的批量 upsert（不覆盖 pb 等其他列）。"""
        if not rows:
            return 0
        values = []
        for r in rows:
            td = r.get("trade_date")
            if hasattr(td, "date"):
                td = td.date()
            values.append((r["symbol"], td, r.get("total_mv"),
                           r.get("pe_ttm"), r.get("source", "computed")))
        sql = """
            INSERT INTO index_valuation_daily
                (symbol, trade_date, total_mv, pe_ttm, source)
            VALUES %s
            ON CONFLICT (trade_date, symbol) DO UPDATE SET
                total_mv=EXCLUDED.total_mv, pe_ttm=EXCLUDED.pe_ttm,
                source=EXCLUDED.source
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)
```

（docstring 由"只写 total_mv"改为"写 total_mv/pe_ttm"；方法名保留——唯一调用方是本 job。）

- [ ] **Step 2: 扩展 sync job**

`backend/src/domain/market/sync/jobs/index_market_cap_sync.py`：

(a) 模块 docstring（:1-10）末尾追加一段：

```text
整体法市盈率：同 pass 用 index_financial_quarterly 累计净利和
（披露率门控 + to_ttm）与月末市值和相除，pe_ttm 随 mv 同行写入
（source='computed'）；TTM 断档/净利≤0 的月度点 pe 为 NULL。
```

(b) `sync_index_market_cap`（:60）整个函数替换为：

```python
def sync_index_market_cap(years: int = 10) -> dict[str, int]:
    """回填全部配置宽基指数的月度总市值 + 整体法 PE 序列（亿）。

    Returns: {index_code: mv点数}（pe 点数见日志）
    """
    from conf import app_config
    from src.domain.market.fundamental.index_pe import compute_index_pe
    from src.infra.database.market.index_financial import (
        create_index_financial_repository,
    )
    items = app_config.quant_universe.index_constituents
    cons_repo = create_index_constituent_repository()
    val_repo = create_stock_valuation_repository()
    idx_repo = create_index_valuation_repository()
    fin_repo = create_index_financial_repository()

    from dateutil.relativedelta import relativedelta

    end = dt.date.today()
    # 闰日安全：date(y-years, 2, 29) 在平年会 ValueError，用 relativedelta。
    start = end - relativedelta(years=years)

    results: dict[str, int] = {}
    for it in items:
        try:
            symbols = cons_repo.get_members(it.code)
            if not symbols:
                log.warning("[idx_mv] %s no constituents, skip", it.code)
                results[it.code] = 0
                continue
            rows_by_symbol = val_repo.get_range_batch(
                symbols, start, end, monthly=True,
            )
            monthly = _filter_covered(
                _monthly_mv_sum(rows_by_symbol), len(symbols),
            )
            # 整体法 PE：累计净利和多取一年做 TTM 年报基准
            fin_rows = fin_repo.get_series(
                "index", it.code, start=start - relativedelta(years=1),
            )
            pe_series = compute_index_pe(
                [{"date": p["date"], "total_mv": p["total_mv"] / 1e8}
                 for p in monthly],
                [{"report_date": r.report_date,
                  "net_profit": r.net_profit_sum,
                  "sample_count": r.sample_count} for r in fin_rows],
            )
            pe_by_date = {p["date"]: p["pe"] for p in pe_series}
            # 删旧重写：清掉上一轮可能写入的低覆盖点，再写达标点
            idx_repo.delete_index_mv(it.code)
            bulk = [
                {"symbol": it.code, "trade_date": p["date"],
                 "total_mv": round(p["total_mv"] / 1e8, 4),
                 "pe_ttm": (round(pe_by_date[p["date"]], 2)
                            if pe_by_date.get(p["date"]) is not None
                            else None),
                 "source": "computed"}
                for p in monthly
            ]
            if bulk:
                idx_repo.bulk_upsert_index_mv(bulk)
            results[it.code] = len(bulk)
            pe_n = sum(1 for r in bulk if r["pe_ttm"] is not None)
            span = (f"{monthly[0]['date']}~{monthly[-1]['date']}"
                    if monthly else "none")
            log.info("[idx_mv] %s: %d monthly points, pe %d (%s)",
                     it.code, len(bulk), pe_n, span)
        except Exception as e:  # noqa: BLE001
            log.warning("[idx_mv] %s failed: %s", it.code, e)
            results[it.code] = 0
    return results
```

- [ ] **Step 3: 验证导入 + mcg 既有测试不回归**

```bash
cd backend && uv run python -c "import src.domain.market.sync.jobs.index_market_cap_sync; import src.infra.database.market.index_valuation; print('ok')"
uv run pytest tests/api/test_market_cap_growth.py -v
```
Expected: `ok`；mcg 全部测试 passed（本任务只加列不改 handler 语义）。

- [ ] **Step 4: Commit**

```bash
git add backend/src/infra/database/market/index_valuation.py backend/src/domain/market/sync/jobs/index_market_cap_sync.py
git commit -m "feat(index-pe): 市值回填job同pass算整体法PE落库pe_ttm,bulk upsert扩列"
```

---

### Task 3: handler `index_pe_trend` + 路由 + API 测试

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（mcg 函数群后、`market_cap_growth_stock` 之后追加）
- Modify: `backend/src/api/router/financial_router.py`（:744 import 块加一行；:886 `_market_cap_growth_stock` 之后加路由）
- Test: `backend/tests/api/test_index_pe.py`

**Interfaces:**
- Consumes: Task 1 `mean_std`；`_mcg_index_names()/_mcg_round/_mcg_cached`（financial_detail_handler.py:2180/2176/2215）；`create_index_valuation_repository().get_index_range(symbol, start, end)`。
- Produces: `index_pe_trend(code: str, years: int = 8) -> Any`（responses 信封）；HTTP `GET /financial/index-pe/{code}?years=8`（years=0 为全部，ge=0 le=30）。data 形状：

```json
{"kind": "index_pe", "code": "000300", "name": "沪深300", "as_of": "2026-08-31",
 "series": [{"date": "2018-09-28", "pe": 11.82}],
 "stats": {"mean": 11.0, "std": 0.82, "high": 11.82, "low": 10.18, "sample_size": 3},
 "current": {"date": "2022-09-30", "pe": 12.0}, "note": null}
```

- [ ] **Step 1: Write the failing tests**

创建 `backend/tests/api/test_index_pe.py`：

```python
"""index-pe 端点测试（mock 仓储，模式抄 test_market_cap_growth.py）。"""
import json
import math
import os
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


def _clear_cache():
    import src.api.handler.financial_detail_handler as h
    h._mcg_cache["data"].clear()
    h._mcg_cache["ts"].clear()


def _pe_row(td, pe):
    return SimpleNamespace(trade_date=date.fromisoformat(td), pe_ttm=pe)


_FROZEN_TODAY = date(2026, 8, 27)
_LEAP_TODAY = date(2028, 2, 29)


def _frozen_handler(today=_FROZEN_TODAY):
    import src.api.handler.financial_detail_handler as h

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return today

    return patch.object(h, "date", _FrozenDate)


class _IdxValRepo:
    """与真实仓储同语义：按 start/end 过滤。"""

    def __init__(self, rows):
        self._rows = rows

    def get_index_range(self, symbol, start, end):
        assert symbol == "000300"
        return [r for r in self._rows
                if (start is None or r.trade_date >= start)
                and (end is None or r.trade_date <= end)]


# years=8 且 today=2026-08-27 → start=2018-08-27，2016 点在窗口外
PE_ROWS = [
    _pe_row("2016-08-31", 9.0),
    _pe_row("2018-09-28", 10.0),
    _pe_row("2020-09-30", 11.0),
    _pe_row("2022-09-30", 12.0),
    _pe_row("2024-09-30", None),   # TTM 断档点
]


def _call(code="000300", rows=None, years=8, today=_FROZEN_TODAY):
    from src.api.handler.financial_detail_handler import index_pe_trend
    _clear_cache()
    with _frozen_handler(today), patch(
        "src.infra.database.market.index_valuation."
        "create_index_valuation_repository",
        return_value=_IdxValRepo(PE_ROWS if rows is None else rows),
    ):
        return json.loads(index_pe_trend(code, years=years).body)


def test_shape_stats_current():
    body = _call()
    assert body["code"] == 0
    d = body["data"]
    assert d["kind"] == "index_pe" and d["code"] == "000300"
    assert d["name"]                     # 配置名（沪深300）
    assert [p["date"] for p in d["series"]] == [
        "2018-09-28", "2020-09-30", "2022-09-30", "2024-09-30"]
    assert d["series"][-1]["pe"] is None
    # stats 对非空样本 {10,11,12}：mean=11、pstdev=√(2/3)
    s = d["stats"]
    assert s["sample_size"] == 3
    assert s["mean"] == 11.0
    assert s["std"] == round(math.sqrt(2 / 3), 2)
    assert s["high"] == round(11 + math.sqrt(2 / 3), 2)
    assert s["low"] == round(11 - math.sqrt(2 / 3), 2)
    # current = 最后一个非空点
    assert d["current"] == {"date": "2022-09-30", "pe": 12.0}
    assert "1个" in (d.get("note") or "")


def test_years_zero_returns_all():
    body = _call(years=0)
    assert body["code"] == 0
    assert len(body["data"]["series"]) == 5   # 含 2016 窗口外点


def test_unknown_code_error():
    body = _call(code="999999")
    assert body["code"] != 0


def test_empty_series_no_stats():
    body = _call(rows=[])
    assert body["code"] == 0
    d = body["data"]
    assert d["series"] == []
    assert d["stats"] is None
    assert d["current"] is None


def test_leap_today_no_value_error():
    body = _call(today=_LEAP_TODAY)
    assert body["code"] == 0


def test_routes_registered():
    from src.api.router.financial_router import router
    paths = {r.path for r in router.routes}
    assert "/financial/index-pe/{code}" in paths
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/api/test_index_pe.py -v
```
Expected: FAIL — `ImportError: cannot import name 'index_pe_trend'`。

- [ ] **Step 3: Write the handler**

`backend/src/api/handler/financial_detail_handler.py` 文件末尾（`market_cap_growth_stock` 之后）追加：

```python
def index_pe_trend(code: str, years: int = 8) -> Any:
    """指数整体法市盈率趋势（月末 PE 序列 + 窗口均值/±σ 参考线统计）。"""
    names = _mcg_index_names()
    if code not in names:
        return responses.fail(
            f"未配置的指数: {code}（见 quant_universe.index_constituents）"
        )

    def _compute() -> Any:
        from dateutil.relativedelta import relativedelta
        from src.domain.market.fundamental.index_pe import mean_std
        from src.infra.database.market.index_valuation import (
            create_index_valuation_repository,
        )
        end = date.today()
        # years<=0 = 全部历史（同估值分位 "all" 惯例：极早起点回溯全表）
        start = (date(1990, 1, 1) if years <= 0
                 else end - relativedelta(years=years))
        rows = create_index_valuation_repository().get_index_range(
            code, start, end,
        )
        series = [
            {"date": r.trade_date.isoformat(), "pe": _mcg_round(r.pe_ttm)}
            for r in rows
        ]
        ms = mean_std([r.pe_ttm for r in rows])
        stats = None
        if ms:
            stats = {
                "mean": _mcg_round(ms["mean"]),
                "std": _mcg_round(ms["std"]),
                "high": _mcg_round(ms["mean"] + ms["std"]),
                "low": _mcg_round(ms["mean"] - ms["std"]),
                "sample_size": ms["sample_size"],
            }
        current = None
        for p in reversed(series):
            if p["pe"] is not None:
                current = p
                break
        payload = {
            "kind": "index_pe",
            "code": code,
            "name": names.get(code),
            "as_of": end.isoformat(),
            "series": series,
            "stats": stats,
            "current": current,
        }
        null_n = sum(1 for p in series if p["pe"] is None)
        if null_n:
            payload["note"] = (
                f"{null_n}个月度点无TTM净利（披露断档或净利≤0），已断线"
            )
        return responses.success(payload)

    return _mcg_cached(f"ipe:{code}:{years}", _compute)
```

- [ ] **Step 4: 注册路由**

`backend/src/api/router/financial_router.py`：

(a) :744 起的 `from src.api.handler.financial_detail_handler import (` 块中加入一行（紧邻 `market_cap_growth_stock,` 之后）：

```python
    index_pe_trend,
```

(b) `_market_cap_growth_stock`（:880-886）之后追加：

```python
@router.get("/index-pe/{code}")
def _index_pe(
    code: str,
    years: int = Query(8, ge=0, le=30, description="回溯年数，0=全部"),
):
    """指数整体法市盈率趋势（PE 月度序列 + 均值/±σ 参考线统计）。"""
    return index_pe_trend(code, years)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/api/test_index_pe.py tests/api/test_market_cap_growth.py -v
```
Expected: 全部 passed（新 6 个 + mcg 既有不回归）。

- [ ] **Step 6: Commit**

```bash
git add backend/src/api/handler/financial_detail_handler.py backend/src/api/router/financial_router.py backend/tests/api/test_index_pe.py
git commit -m "feat(index-pe): GET /financial/index-pe/{code}——序列+均值/±σ统计+断线note"
```

---

### Task 4: 前端 hook `useIndexPe`

**Files:**
- Create: `frontend/apps/web/src/hooks/useIndexPe.ts`

**Interfaces:**
- Consumes: `getApiBase()`（`src/lib/api`）；Task 3 端点 `GET /financial/index-pe/{code}?years=`。
- Produces（Task 5 依赖）：`useIndexPe(code: string | null, years = 8) -> { data: IndexPeData | null, loading: boolean, error: string | null }`；类型 `IndexPeData { kind: 'index_pe'; code: string; name: string | null; as_of: string | null; series: Array<{date: string; pe: number | null}>; stats: { mean: number; std: number; high: number; low: number; sample_size: number } | null; current: { date: string; pe: number | null } | null; note?: string }`。

- [ ] **Step 1: Write the hook**（前端无测试基建，与 useMarketCapGrowth 同水位，以 Task 5/6 的 tsc build 验证）

创建 `frontend/apps/web/src/hooks/useIndexPe.ts`：

```typescript
/**
 * 指数整体法市盈率趋势数据 hook。
 *
 * 调 GET /financial/index-pe/{code}，years=0 为全部历史。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface IndexPePoint {
  date: string;
  pe: number | null;
}

export interface IndexPeStats {
  mean: number;
  std: number;
  high: number;
  low: number;
  sample_size: number;
}

export interface IndexPeData {
  kind: 'index_pe';
  code: string;
  name: string | null;
  as_of: string | null;
  series: IndexPePoint[];
  stats: IndexPeStats | null;
  current: IndexPePoint | null;
  note?: string;
}

export function useIndexPe(code: string | null, years = 8) {
  const [data, setData] = useState<IndexPeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/financial/index-pe/${code}?years=${years}`)
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
  }, [code, years]);

  return { data, loading, error };
}
```

- [ ] **Step 2: 类型检查**

```bash
cd frontend && pnpm -F web build
```
Expected: EXIT 0（hook 尚无引用，仅编译）。

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/hooks/useIndexPe.ts
git commit -m "feat(index-pe): useIndexPe hook——整体法PE趋势取数"
```

---

### Task 5: 前端组件 `IndexPeChart`

**Files:**
- Create: `frontend/apps/web/src/components/IndexPeChart.tsx`

**Interfaces:**
- Consumes: Task 4 `IndexPeData`；`StateView`（`./ui`）；chartTheme 令牌 `CHART_COLORS/axisProps/gridProps/tooltipProps/colorWarning/colorUp/colorDown`。
- Produces（Task 6 依赖）：`IndexPeChart({ title?, subtitle?, data, loading, error })`。

- [ ] **Step 1: Write the component**

创建 `frontend/apps/web/src/components/IndexPeChart.tsx`：

```typescript
/**
 * IndexPeChart —— 指数整体法市盈率趋势。
 * 蓝 PE 折线（月末点，TTM 断档断线）+ 黄均值虚线 + 红/绿 mean±σ 参考线。
 * 参考用户自研产品截图形态（"沪深300市盈率趋势/近八年"）。
 */
import React, { useMemo } from 'react';
import {
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
import { StateView } from './ui';
import {
  CHART_COLORS,
  axisProps,
  colorDown,
  colorUp,
  colorWarning,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';
import type { IndexPeData } from '../hooks/useIndexPe';

const refLabel = (text: string, color: string) => ({
  value: text,
  position: 'right' as const,
  fill: color,
  fontSize: 11,
});

interface Props {
  title?: string;
  subtitle?: string;
  data: IndexPeData | null;
  loading: boolean;
  error: string | null;
}

export function IndexPeChart({
  title,
  subtitle,
  data,
  loading,
  error,
}: Props) {
  const rows = useMemo(
    () =>
      (data?.series ?? []).map((p) => ({
        date: p.date.slice(0, 7),   // 月度粒度 → YYYY-MM 刻度
        pe: p.pe,
      })),
    [data],
  );

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="error" text={error} />;
  if (!data || rows.length === 0)
    return (
      <StateView
        state="empty"
        text={data?.note || '暂无市盈率数据（等待周度任务回填 pe_ttm）'}
      />
    );

  const s = data.stats;
  return (
    <div>
      {title && (
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>
          {title}
          {subtitle && (
            <small
              style={{
                fontSize: 12,
                fontWeight: 400,
                color: '#a1a1a6',
                marginLeft: 8,
              }}
            >
              {subtitle}
            </small>
          )}
        </h3>
      )}
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart
          data={rows}
          margin={{ top: 5, right: 56, bottom: 0, left: 0 }}
        >
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="date" {...axisProps} minTickGap={30} />
          <YAxis
            {...axisProps}
            width={44}
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => Number(v).toFixed(1)}
          />
          <Tooltip
            {...tooltipProps}
            formatter={(v: number, name: string) => [
              v == null ? '-' : Number(v).toFixed(2),
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {s && (
            <>
              <ReferenceLine
                y={s.mean}
                stroke={colorWarning}
                strokeDasharray="6 4"
                label={refLabel(`均值 ${s.mean.toFixed(1)}`, colorWarning)}
                ifOverflow="extendDomain"
              />
              <ReferenceLine
                y={s.high}
                stroke={colorUp}
                strokeDasharray="6 4"
                label={refLabel(`高估 ${s.high.toFixed(1)}`, colorUp)}
                ifOverflow="extendDomain"
              />
              <ReferenceLine
                y={s.low}
                stroke={colorDown}
                strokeDasharray="6 4"
                label={refLabel(`低估 ${s.low.toFixed(1)}`, colorDown)}
                ifOverflow="extendDomain"
              />
            </>
          )}
          <Line
            type="monotone"
            dataKey="pe"
            name="市盈率"
            stroke={CHART_COLORS[0]}
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      {data.note && (
        <div style={{ fontSize: 11, color: '#86868b', marginTop: 6 }}>
          {data.note}
        </div>
      )}
      <div style={{ fontSize: 11, color: '#86868b', marginTop: 4 }}>
        整体法：成分股总市值和 ÷ TTM归母净利和；月度采样；当前成分近似历史成分
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build 验证**

```bash
cd frontend && pnpm -F web build
```
Expected: EXIT 0。

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/components/IndexPeChart.tsx
git commit -m "feat(index-pe): IndexPeChart——蓝PE线+黄均值/红绿±σ参考线,断线不插值"
```

---

### Task 6: Indices 页挂载「市盈率趋势」区块

**Files:**
- Modify: `frontend/apps/web/src/pages/Indices.tsx`（import 区 :25-26 后；`MCG_INDICES` :63 后；state 区 :210-214 后；mcg section :583 后）

**Interfaces:**
- Consumes: Task 4 `useIndexPe`、Task 5 `IndexPeChart`、既有 `MCG_INDICES`（:53）与 `indices__mcg*` CSS 类（复用，不新增 CSS）。
- Produces: Indices 页 mcg 区块之后新增 section；指数切换 `peCode`（默认 `'000300'`）、窗口 `peYears`（默认 `8`）。

- [ ] **Step 1: 加 import 与常量**

(a) `Indices.tsx:26`（`useMarketCapGrowth` import 之后）加：

```typescript
import { IndexPeChart } from '../components/IndexPeChart';
import { useIndexPe } from '../hooks/useIndexPe';
```

(b) `MCG_INDICES` 数组（:53-63）之后加：

```typescript
// 市盈率趋势窗口（years=0 → 全部，对齐后端 /financial/index-pe 语义）
const PE_WINDOWS: Array<[number, string]> = [
  [3, '近3年'], [5, '近5年'], [8, '近8年'], [10, '近10年'], [0, '全部'],
];
```

- [ ] **Step 2: 加 state + hook（mcg state 块 :210-214 之后）**

```tsx
  const [peCode, setPeCode] = useState('000300');
  const [peYears, setPeYears] = useState(8);
  const { data: peData, loading: peLoading, error: peError } =
    useIndexPe(peCode, peYears);
  const peName = MCG_INDICES.find((i) => i.code === peCode)?.name ?? peCode;
```

- [ ] **Step 3: 加 section JSX（mcg section `</section>` :583 之后、Ranking 之前）**

```tsx
      {/* ── 市盈率趋势（整体法） ── */}
      <section className="indices__mcg">
        <div className="indices__mcg-header">
          <h2 className="indices__mcg-title">市盈率趋势</h2>
          <div className="indices__mcg-switch">
            {PE_WINDOWS.map(([y, l]) => (
              <button
                key={y}
                className={`indices__mcg-btn ${
                  peYears === y ? 'is-active' : ''
                }`}
                onClick={() => setPeYears(y)}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <div className="indices__mcg-switch" style={{ marginBottom: 10 }}>
          {MCG_INDICES.map((i) => (
            <button
              key={i.code}
              className={`indices__mcg-btn ${
                peCode === i.code ? 'is-active' : ''
              }`}
              onClick={() => setPeCode(i.code)}
            >
              {i.name}
            </button>
          ))}
        </div>
        <div className="indices__mcg-body">
          <IndexPeChart
            title={`${peName}市盈率趋势`}
            subtitle={PE_WINDOWS.find(([y]) => y === peYears)?.[1] ?? ''}
            data={peData}
            loading={peLoading}
            error={peError}
          />
        </div>
      </section>
```

- [ ] **Step 4: Build 验证**

```bash
cd frontend && pnpm -F web build
```
Expected: EXIT 0。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/Indices.tsx
git commit -m "feat(index-pe): Indices页新增市盈率趋势区块——9宽基切换+窗口chips"
```

---

### Task 7: 冒烟（真实数据端到端）

**Files:** 无新文件（验证任务；如发现数据问题只修 bug 不扩范围）。

**Interfaces:**
- Consumes: Task 2 job（写表）、Task 3 handler（读表）+ `index_valuation_percentile`（徽章激活验证）。

- [ ] **Step 1: 跑真实回填 job**

```bash
cd backend && uv run python -c "
from src.domain.market.sync.jobs.index_market_cap_sync import sync_index_market_cap
print(sync_index_market_cap(10))
"
```
Expected: 9 个代码各返回 mv 点数（约 100~120）；日志每行 `[idx_mv] 000xxx: N monthly points, pe M (...)`，pe 数应接近 mv 数（早期/披露季少量 null 正常）。前提：`index_constituent` 与 `index_financial_quarterly` 已有数据（weekly 链在跑）；若成分表为空先跑 `index_constituent_sync.run()` 与 `sync_index_financial_quarterly()`。

- [ ] **Step 2: 直调 handler 验证三指数 + 徽章激活**

```bash
cd backend && uv run python -c "
import json
from src.api.handler.financial_detail_handler import index_pe_trend, index_valuation_percentile
for code in ('000300', '000905', '000852'):
    b = json.loads(index_pe_trend(code, years=8).body)
    d = b['data']
    print(code, d['name'], 'points:', len(d['series']),
          'stats:', d['stats'], 'current:', d['current'])
p = json.loads(index_valuation_percentile('index', '000300', '10y', ['pe_ttm']).body)
print('badge percentile:', p['data']['metrics']['pe_ttm']['stats'])
"
```
Expected: 三指数 series 非空；沪深300 PE 区间合理（整体法约 10~15 量级，肉眼对照中证官网）；`badge percentile` 非 null（此前恒为空——本功能顺带激活）。

- [ ] **Step 3: 浏览器目检**

启动前后端（开发进程），打开 Indices 页：
- mcg 区块下方出现「市盈率趋势」区块，默认沪深300 + 近8年；
- 蓝色 PE 折线 + 黄色均值虚线 + 红/绿 ±σ 虚线（右侧带数值标签），与参考图同构；
- 切换 中证500/中证1000 与窗口 chips（含"全部"）数据正常刷新；TTM 断档处折线断开不插值。

- [ ] **Step 4: 回归子集确认**

```bash
cd backend && uv run pytest tests/api/test_index_pe.py tests/domain/market/fundamental/test_index_pe.py tests/api/test_market_cap_growth.py tests/api/test_valuation_percentile_exclude.py -v
```
Expected: 全部 passed。

---

## Self-Review 记录

- **Spec 覆盖**：纯函数（Task 1）、repo+job（Task 2）、handler+路由（Task 3）、hook（Task 4）、Chart（Task 5）、Indices 挂载（Task 6）、冒烟+徽章激活（Task 7）——spec 后端/前端/测试/验证各节均有对应任务。
- **Spec 偏差（有意）**：①均值线色用 chartTheme 令牌 `colorWarning` 替代 spec 写死的 `#eab308`；②job 返回值保持 `{code: mv点数}` 不加 pe 键（spec 措辞两可，取不破坏调用方的一种），pe 点数进日志。
- **占位符扫描**：无 TBD/TODO；所有代码步骤含完整代码。
- **类型一致性**：`compute_index_pe(monthly_mv, cum_rows)`（Task 1 定义 = Task 2 调用）；`mean_std`（Task 1 = Task 3）；`useIndexPe(code, years)` / `IndexPeData`（Task 4 = Task 5/6）；`IndexPeChart` props（Task 5 定义 = Task 6 调用）。
