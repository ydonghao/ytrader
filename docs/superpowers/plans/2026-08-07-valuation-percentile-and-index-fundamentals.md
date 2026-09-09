# 估值分位 + 指数/行业财务聚合 + 多指标叠加图 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现个股/指数/行业的估值历史分位、指数/行业财务聚合、以及个股多指标叠加对比图。

**Architecture:** P0a 个股分位复用已有 `stock_valuation` 表实时计算+缓存，提取通用 `percentile` 工具；P0b 新建 3 张表（`index_valuation_daily` / `sw_index_valuation_daily` / `index_financial_quarterly`）+ 同步 job（每日落盘 + 一次性历史回填 + 季度财务聚合），复用 P0a 分位算法；P3 升级现有 `FinancialOverlayChart` 加多选叠加 + 归一化。

**Tech Stack:** FastAPI + SQLModel + PostgreSQL/TimescaleDB（后端）；React 18 + recharts + react-router（前端）。

## Global Constraints

- 后端路径前缀：所有 handler 函数返回 `responses.success(...)` / `responses.not_found(...)`，格式 `{code:0,msg,data}`。
- 前端 API 调用范式：`import { getApiBase } from '../lib/api'` + `fetch(\`${API_BASE}/xxx\`)` + `json.code === 0` 判成功。**不要使用 `@ytrader/arch-api`（孤儿包）。**
- 数据库：PostgreSQL/TimescaleDB，无 Alembic，靠 `SQLModel.metadata.create_all(engine)` 自动建表，新表跟随 `valuation.py` 的 SQLModel + 工厂函数模式。
- 表名/字段：snake_case；symbol 格式 `sh600519` / `sz000001`（带交易所前缀）；申万 sw_code 格式 `sw801010`。
- 测试：`pytest tests/...`，conftest 提供 `db_dsn` / `api_client`（如有）。纯算法测试不需 DB。
- 提交信息格式：`feat(area): 描述` / `test(area): 描述` / `refactor(area): 描述`。
- 中文注释与代码风格匹配现有文件（如 `valuation.py` 的 docstring 风格）。

---

## File Structure

### 后端新建
- `backend/src/domain/market/fundamental/percentile.py` —— 通用分位算法工具（P0a 核心，P0b 复用）
- `backend/src/infra/database/market/index_valuation.py` —— `index_valuation_daily` + `sw_index_valuation_daily` 两张表 + repository
- `backend/src/infra/database/market/index_financial.py` —— `index_financial_quarterly` 表 + repository
- `backend/src/domain/market/sync/jobs/index_valuation_sync.py` —— 每日行业/指数估值落盘 job
- `backend/src/domain/market/sync/jobs/index_valuation_backfill.py` —— 一次性历史回填 job（成分股加权自算）
- `backend/src/domain/market/sync/jobs/index_financial_sync.py` —— 季度财务聚合 job
- `backend/tests/domain/test_percentile.py` —— 分位算法单测
- `backend/tests/api/test_valuation_percentile.py` —— P0a 端点测试

### 后端修改
- `backend/src/api/handler/financial_detail_handler.py` —— 新增 `valuation_percentile()` / `index_valuation_percentile()` / `index_financial_agg()` / `index_valuation_percentile_batch()`
- `backend/src/api/router/financial_router.py` —— 新增 4 条路由
- `backend/src/infra/scheduler.py` —— 注册 2 个新 job（每日估值落盘 + 季度财务）

### 前端新建
- `frontend/apps/web/src/pages/Valuation.tsx` —— P0a 独立页
- `frontend/apps/web/src/components/ValuationPercentileChart.tsx` —— 分位图组件
- `frontend/apps/web/src/components/IndexFinancialChart.tsx` —— 行业/指数财务聚合图
- `frontend/apps/web/src/hooks/useValuationPercentile.ts` —— P0a/P0b 分位数据 hook
- `frontend/apps/web/src/lib/normalize.ts` —— min-max 归一化工具（P3）

### 前端修改
- `frontend/apps/web/src/App.tsx` —— 加 `/valuation` 路由
- `frontend/apps/web/src/components/Layout.tsx` —— Overview 组加菜单项
- `frontend/apps/web/src/components/FinancialOverlayChart.tsx` —— P3 升级（多选叠加 + 归一化）
- `frontend/apps/web/src/pages/SectorScan.tsx` —— 加行业分位列 + 下钻
- `frontend/apps/web/src/pages/Indices.tsx` —— 加指数分位徽章

---

## Task 1: 通用分位算法工具（P0a 核心）

**Files:**
- Create: `backend/src/domain/market/fundamental/percentile.py`
- Create: `backend/tests/domain/test_percentile.py`

**Interfaces:**
- Produces: `calc_percentile(samples, current) -> float | None`、`percentile_stats(samples, current) -> dict | None`、`downsample_monthly(points) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/domain/test_percentile.py`:

```python
"""通用分位算法工具测试。"""
import datetime as dt
import pytest
from src.domain.market.fundamental.percentile import (
    calc_percentile,
    percentile_stats,
    downsample_monthly,
)


class TestCalcPercentile:
    def test_basic(self):
        # 0 在 [0,1,2,...,9] 中分位 = 0.1 (1/10)
        assert calc_percentile([0,1,2,3,4,5,6,7,8,9], 0) == pytest.approx(0.1)

    def test_current_at_max(self):
        assert calc_percentile([1.0, 2.0, 3.0, 4.0, 5.0], 5.0) == pytest.approx(1.0)

    def test_current_below_min(self):
        assert calc_percentile([10.0, 20.0, 30.0], 5.0) == pytest.approx(0.0)

    def test_current_between_samples(self):
        # 7 在 [4,5,6,8,9] 中：<=7 的有 3 个 → 3/5 = 0.6
        assert calc_percentile([4.0, 5.0, 6.0, 8.0, 9.0], 7.0) == pytest.approx(0.6)

    def test_insufficient_samples_returns_none(self):
        assert calc_percentile([1.0, 2.0], 1.5) is None  # < 30

    def test_empty_samples_returns_none(self):
        assert calc_percentile([], 1.0) is None

    def test_exactly_30_samples(self):
        samples = list(range(30))
        assert calc_percentile(samples, 15) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/domain/test_percentile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.domain.market.fundamental.percentile'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/domain/market/fundamental/percentile.py`:

```python
"""通用分位（百分位）算法工具。

供个股/指数/行业估值分位共用。提取自
strategy/longterm/strategies/value_averaging.py 的 _pe_percentile，
泛化为任意指标的分位计算。

口径约定：
  - 样本数 < 30 返回 None（样本不足，统计无意义）
  - 分位 = (样本中 <= current 的个数) / 样本总数，范围 [0, 1]
  - 调用方负责过滤负值/None（PE/PS 为负不应纳入分位）
"""
from __future__ import annotations

import datetime as dt
from typing import Optional


SAMPLE_MIN = 30


def calc_percentile(samples: list[float], current: float) -> Optional[float]:
    """当前值在样本中的分位 (0~1)。

    Args:
        samples: 历史样本值（已剔除 None/负值）。
        current: 当前值。

    Returns:
        分位 (0~1)；样本数 < SAMPLE_MIN 返回 None。
    """
    if len(samples) < SAMPLE_MIN:
        return None
    rank = sum(1 for v in samples if v <= current)
    return rank / len(samples)


def percentile_stats(samples: list[float], current: float) -> Optional[dict]:
    """返回当前值的分位 + 窗口统计量。

    Returns:
        {current, percentile, sample_size, min, max, p25, p50, p75}；
        样本不足返回 None。
    """
    if len(samples) < SAMPLE_MIN:
        return None
    ordered = sorted(samples)
    n = len(ordered)

    def _pct(q: float) -> float:
        idx = max(0, min(n - 1, int(round(q * (n - 1)))))
        return ordered[idx]

    return {
        "current": current,
        "percentile": calc_percentile(samples, current),
        "sample_size": n,
        "min": ordered[0],
        "max": ordered[-1],
        "p25": _pct(0.25),
        "p50": _pct(0.50),
        "p75": _pct(0.75),
    }


def downsample_monthly(points: list[dict]) -> list[dict]:
    """按月降采样：每个自然月保留最后一个有效点。

    用于把日频分位时序降到月频，控制前端渲染量。
    points 每条含 {"date": "YYYY-MM-DD", "value": float}，按 date 升序传入。

    Returns:
        降采样后的点列表（每行原样返回，仅做了月内去重保留最后一条）。
    """
    if not points:
        return []
    last_per_month: dict[str, dict] = {}
    for p in points:
        d = p.get("date", "")
        if len(d) < 7:
            continue
        month_key = d[:7]  # YYYY-MM
        last_per_month[month_key] = p
    return list(last_per_month.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/domain/test_percentile.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Add edge-case tests for percentile_stats and downsample**

Append to `backend/tests/domain/test_percentile.py`:

```python
class TestPercentileStats:
    def test_returns_full_stats(self):
        samples = [float(i) for i in range(30)]
        stats = percentile_stats(samples, 15.0)
        assert stats is not None
        assert stats["current"] == 15.0
        assert stats["sample_size"] == 30
        assert stats["min"] == 0.0
        assert stats["max"] == 29.0
        assert 0.4 < stats["percentile"] < 0.6

    def test_insufficient_returns_none(self):
        assert percentile_stats([1.0, 2.0], 1.5) is None

    def test_quantiles(self):
        samples = [float(i) for i in range(100)]
        stats = percentile_stats(samples, 50.0)
        assert stats["p25"] == 25.0  # approx via nearest-rank
        assert stats["p50"] == 50.0
        assert stats["p75"] == 75.0


class TestDownsampleMonthly:
    def test_keeps_last_per_month(self):
        pts = [
            {"date": "2024-01-05", "value": 1.0},
            {"date": "2024-01-20", "value": 2.0},
            {"date": "2024-02-03", "value": 3.0},
            {"date": "2024-02-28", "value": 4.0},
        ]
        out = downsample_monthly(pts)
        assert len(out) == 2
        assert out[0]["value"] == 2.0  # 1月最后
        assert out[1]["value"] == 4.0  # 2月最后

    def test_empty(self):
        assert downsample_monthly([]) == []

    def test_skips_invalid_dates(self):
        pts = [{"date": "", "value": 1.0}, {"date": "2024-03-15", "value": 2.0}]
        out = downsample_monthly(pts)
        assert len(out) == 1
```

- [ ] **Step 6: Run all percentile tests**

Run: `cd backend && python -m pytest tests/domain/test_percentile.py -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add backend/src/domain/market/fundamental/percentile.py backend/tests/domain/test_percentile.py
git commit -m "feat(fundamental): 通用分位算法工具 calc_percentile/percentile_stats/downsample_monthly"
```

---

## Task 2: P0a 个股估值分位端点（后端）

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（新增 `valuation_percentile()` 函数）
- Modify: `backend/src/api/router/financial_router.py`（新增路由）
- Create: `backend/tests/api/test_valuation_percentile.py`

**Interfaces:**
- Consumes: `StockValuationRepository.get_range(symbol, start, end)`（已有，`valuation.py:120`）、`calc_percentile` / `percentile_stats` / `downsample_monthly`（Task 1）
- Produces: `GET /api/v1/financial/valuation-percentile/{symbol}` 端点

- [ ] **Step 1: Write the endpoint test (integration, against real DB)**

Create `backend/tests/api/test_valuation_percentile.py`:

```python
"""P0a 个股估值分位端点测试。"""
import pytest

SYMBOL = "sz000001"  # 平安银行，数据充足


class TestValuationPercentile:
    def test_returns_200_and_shape(self, api_client):
        resp = api_client.get(f"/financial/valuation-percentile/{SYMBOL}")
        assert resp.status_code == 200
        json = resp.json()
        assert json["code"] == 0
        data = json["data"]
        assert data is not None
        assert data["symbol"] == SYMBOL
        assert "metrics" in data
        assert "as_of" in data

    def test_default_metrics_all_present(self, api_client):
        resp = api_client.get(f"/financial/valuation-percentile/{SYMBOL}")
        data = resp.json()["data"]
        for m in ("pe_ttm", "pb", "ps_ttm", "dv_ttm"):
            assert m in data["metrics"], f"missing metric {m}"

    def test_metric_has_windows(self, api_client):
        resp = api_client.get(f"/financial/valuation-percentile/{SYMBOL}")
        data = resp.json()["data"]
        pe = data["metrics"]["pe_ttm"]
        if pe is None:
            pytest.skip("no pe_ttm data for this symbol")
        assert "windows" in pe
        for w in ("3y", "5y", "10y"):
            assert w in pe["windows"]
            win = pe["windows"][w]
            if win is not None:
                assert "percentile" in win
                assert "sample_size" in win

    def test_custom_window(self, api_client):
        resp = api_client.get(
            f"/financial/valuation-percentile/{SYMBOL}?windows=5y"
        )
        data = resp.json()["data"]
        pe = data["metrics"]["pe_ttm"]
        if pe is None:
            pytest.skip("no pe_ttm data")
        assert set(pe["windows"].keys()) == {"5y"}

    def test_as_of_param(self, api_client):
        resp = api_client.get(
            f"/financial/valuation-percentile/{SYMBOL}?as_of=2024-06-28&windows=5y"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["as_of"] == "2024-06-28"
```

> 注：`api_client` fixture 若不存在，参考 `tests/api/test_market.py` 的 HTTP 调用风格，改用 `requests.Session` 直连。先检查 conftest 是否有该 fixture。

- [ ] **Step 2: Check api_client fixture exists**

Run: `cd backend && grep -n "api_client" tests/conftest.py tests/api/conftest.py 2>/dev/null`
- 若存在 → 直接用。
- 若不存在 → 在 test 文件顶部用 `requests` 直连：把 `api_client` 参数改为 `http_session`（conftest:55 已有），请求改为 `http_session.get(f"{api_base_url}/financial/valuation-percentile/{SYMBOL}")`。

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_valuation_percentile.py -v`
Expected: FAIL (路由不存在，404)

- [ ] **Step 4: Implement the handler function**

在 `backend/src/api/handler/financial_detail_handler.py` 文件**末尾**追加（参考现有 `valuation_history()` 的 import 与缓存模式）：

```python
# ── P0a 个股估值分位 ────────────────────────────────────────────────

import time as _time

_VALPCT_CACHE_TTL = 3600  # 1 小时
_valpct_cache: dict[str, dict] = {"data": {}, "ts": {}}


def valuation_percentile(
    symbol: str,
    windows: list[str] | None = None,
    as_of: str | None = None,
    metrics: list[str] | None = None,
) -> Any:
    """个股估值历史分位（PE_TTM/PB/PS_TTM/股息率 × 3/5/10 年窗口）。

    Args:
        symbol:  sh600519 / sz000001
        windows: ["3y","5y","10y"]，默认全部
        as_of:   "YYYY-MM-DD"，默认最新交易日
        metrics: ["pe_ttm","pb","ps_ttm","dv_ttm"]，默认全部

    Returns:
        success({symbol, as_of, metrics: {metric: {current, windows:{w:stats|None},
        series:[{date,value}]}}}).
    """
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    from src.domain.market.fundamental.percentile import (
        percentile_stats, downsample_monthly,
    )

    windows = windows or ["3y", "5y", "10y"]
    metrics = metrics or ["pe_ttm", "pb", "ps_ttm", "dv_ttm"]

    repo = create_stock_valuation_repository()

    # 确定 as_of
    if as_of:
        as_of_date = _parse_date(as_of)
        if as_of_date is None:
            return responses.fail(f"invalid as_of: {as_of}")
    else:
        latest = repo.get_latest_date(symbol)
        if latest is None:
            return responses.success(
                {"symbol": symbol, "as_of": None, "metrics": {}}
            )
        as_of_date = latest

    window_years = {"3y": 3, "5y": 5, "10y": 10}

    result_metrics: dict[str, dict | None] = {}

    for metric in metrics:
        # 缓存 key
        cache_key = f"{symbol}:{metric}:{as_of_date.isoformat()}:{','.join(windows)}"
        now = _time.time()
        cached = _valpct_cache["data"].get(cache_key)
        cached_ts = _valpct_cache["ts"].get(cache_key, 0)
        if cached is not None and now - cached_ts < _VALPCT_CACHE_TTL:
            result_metrics[metric] = cached
            continue

        metric_result: dict = {"windows": {}, "series": []}
        # series 用最长窗口的原始时序（月度降采样），所有窗口共享
        max_window = max(window_years[w] for w in windows)
        range_start = dt.date(
            as_of_date.year - max_window, as_of_date.month, as_of_date.day
        )
        try:
            rows = repo.get_range(symbol, range_start, as_of_date)
        except Exception as e:
            logger.warning("valuation_percentile get_range failed %s: %s", symbol, e)
            rows = []

        # 提取该 metric 的有效值（过滤 None/负值）
        attr_map = {
            "pe_ttm": "pe_ttm", "pb": "pb",
            "ps_ttm": "ps_ttm", "dv_ttm": "dv_ttm",
        }
        attr = attr_map.get(metric)
        if attr is None:
            result_metrics[metric] = None
            continue

        # 全窗口的有效点（用于 series 画图）
        all_points = [
            {"date": r.trade_date.isoformat(), "value": getattr(r, attr)}
            for r in rows
            if getattr(r, attr) is not None and getattr(r, attr) > 0
        ]
        metric_result["series"] = downsample_monthly(all_points)

        # 当前值
        current = all_points[-1]["value"] if all_points else None

        for w in windows:
            years = window_years[w]
            w_start = dt.date(
                as_of_date.year - years, as_of_date.month, as_of_date.day
            )
            w_samples = [
                getattr(r, attr) for r in rows
                if r.trade_date >= w_start
                and getattr(r, attr) is not None
                and getattr(r, attr) > 0
            ]
            if current is None:
                metric_result["windows"][w] = None
            else:
                metric_result["windows"][w] = percentile_stats(w_samples, current)

        metric_result["current"] = current
        result_metrics[metric] = metric_result
        _valpct_cache["data"][cache_key] = metric_result
        _valpct_cache["ts"][cache_key] = now

    return responses.success({
        "symbol": symbol,
        "as_of": as_of_date.isoformat(),
        "metrics": result_metrics,
    })
```

> 注意：`dt` 在该文件顶部应已 import（`valuation_history` 用了 `_parse_date`）。确认顶部有 `import datetime as dt`，若无则补。`logger` / `responses` / `_parse_date` 均已在文件中。

- [ ] **Step 5: Add the route**

在 `backend/src/api/router/financial_router.py` 的 import 块（约 724-730 行）加入 `valuation_percentile`：

```python
from src.api.handler.financial_detail_handler import (
    detail_series,
    forecast_list,
    industry_valuation_snapshot,
    stock_profile,
    valuation_history,
    valuation_percentile,
)
```

在文件末尾（`industry_valuation_snapshot` 路由之后）追加：

```python
@router.get("/valuation-percentile/{symbol}")
def _valuation_percentile(
    symbol: str,
    windows: str = Query("3y,5y,10y", description="逗号分隔，可选 3y/5y/10y"),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD，默认最新"),
    metrics: str = Query(
        "pe_ttm,pb,ps_ttm,dv_ttm",
        description="逗号分隔的指标",
    ),
):
    """个股估值历史分位（PE/PB/PS/股息率 × 多窗口）。"""
    win_list = [w.strip() for w in windows.split(",") if w.strip()]
    met_list = [m.strip() for m in metrics.split(",") if m.strip()]
    return valuation_percentile(symbol, win_list, as_of, met_list)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/test_valuation_percentile.py -v`
Expected: PASS（需后端服务运行，或 api_client 直连本地 DB。若纯离线无法跑，至少 `python -c "from src.api.handler.financial_detail_handler import valuation_percentile"` 验证 import 无误）

- [ ] **Step 7: Commit**

```bash
git add backend/src/api/handler/financial_detail_handler.py backend/src/api/router/financial_router.py backend/tests/api/test_valuation_percentile.py
git commit -m "feat(financial): P0a 个股估值历史分位端点 /valuation-percentile/{symbol}"
```

---

## Task 3: P0a 前端 —— useValuationPercentile hook

**Files:**
- Create: `frontend/apps/web/src/hooks/useValuationPercentile.ts`

**Interfaces:**
- Consumes: `GET /api/v1/financial/valuation-percentile/{symbol}`（Task 2）
- Produces: `useValuationPercentile(symbol)` hook，返回 `{data, loading, error}`

- [ ] **Step 1: Create the hook**

Create `frontend/apps/web/src/hooks/useValuationPercentile.ts`:

```typescript
/**
 * 个股/指数估值历史分位数据 hook。
 *
 * 调用 GET /financial/valuation-percentile/{symbol}，
 * 支持 windows / as_of / metrics 参数。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface PercentileWindowStats {
  current: number | null;
  percentile: number | null;
  sample_size: number;
  min: number;
  max: number;
  p25: number;
  p50: number;
  p75: number;
}

export interface PercentileMetric {
  current: number | null;
  windows: Record<string, PercentileWindowStats | null>;
  series: Array<{ date: string; value: number }>;
}

export interface ValuationPercentileData {
  symbol: string;
  as_of: string | null;
  metrics: Record<string, PercentileMetric | null>;
}

export interface UseValuationPercentileParams {
  windows?: string;       // "3y,5y,10y"
  asOf?: string;          // "YYYY-MM-DD"
  metrics?: string;       // "pe_ttm,pb,ps_ttm,dv_ttm"
}

export function useValuationPercentile(
  symbol: string | null,
  params: UseValuationPercentileParams = {},
) {
  const { windows, asOf, metrics } = params;
  const [data, setData] = useState<ValuationPercentileData | null>(null);
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

    const qs = new URLSearchParams();
    if (windows) qs.set('windows', windows);
    if (asOf) qs.set('as_of', asOf);
    if (metrics) qs.set('metrics', metrics);

    const url = `${API_BASE}/financial/valuation-percentile/${symbol}${qs.toString() ? '?' + qs.toString() : ''}`;
    fetch(url)
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
  }, [symbol, windows, asOf, metrics]);

  return { data, loading, error };
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && pnpm --filter @ytrader/web exec tsc --noEmit 2>&1 | head -20`
Expected: 无类型错误（或仅有与本次无关的既有错误）。

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/hooks/useValuationPercentile.ts
git commit -m "feat(web): useValuationPercentile hook"
```

---

## Task 4: P0a 前端 —— ValuationPercentileChart 组件

**Files:**
- Create: `frontend/apps/web/src/components/ValuationPercentileChart.tsx`

**Interfaces:**
- Consumes: `PercentileMetric` / `PercentileWindowStats`（Task 3）
- Produces: `<ValuationPercentileChart metric={...} windowKey="10y" />`

- [ ] **Step 1: Create the component**

Create `frontend/apps/web/src/components/ValuationPercentileChart.tsx`:

```tsx
/**
 * 单指标估值分位图。
 *
 * 画法：历史绝对值轨迹（Line）+ 当前窗口的 p25/p50/p75 水平参考线。
 * 右上角徽章显示当前分位百分比 + 状态色。
 */
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
} from 'recharts';
import type { PercentileMetric } from '../hooks/useValuationPercentile';

interface Props {
  title: string;
  unit?: string;
  metric: PercentileMetric | null;
  windowKey: string; // "3y" | "5y" | "10y"
  color?: string;
}

function percentileColor(pct: number | null): string {
  if (pct === null) return '#888';
  if (pct < 0.2) return '#16a34a'; // 低估 绿
  if (pct > 0.8) return '#dc2626'; // 高估 红
  return '#ca8a04'; // 正常 黄
}

export function ValuationPercentileChart({
  title,
  unit = '',
  metric,
  windowKey,
  color = '#2563eb',
}: Props) {
  if (!metric || !metric.windows[windowKey]) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: '#888' }}>
        {title}：数据不足
      </div>
    );
  }

  const stats = metric.windows[windowKey]!;
  const series = (metric.series || []).map((p) => ({
    date: p.date,
    value: p.value,
  }));

  const pct = stats.percentile;
  const pctText = pct !== null ? `${(pct * 100).toFixed(0)}%` : '—';
  const badgeColor = percentileColor(pct);

  return (
    <div
      style={{
        border: '1px solid #2a2a2a',
        borderRadius: 8,
        padding: 12,
        background: '#1a1a1a',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
        }}
      >
        <strong>{title}</strong>
        <span
          style={{
            padding: '2px 10px',
            borderRadius: 12,
            color: '#fff',
            background: badgeColor,
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {windowKey} 分位 {pctText}
        </span>
      </div>
      <div style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>
        当前 {stats.current?.toFixed(2) ?? '—'} {unit}　|　区间{' '}
        {stats.min?.toFixed(2)} ~ {stats.max?.toFixed(2)}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={series} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#333" strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#888' }} minTickGap={40} />
          <YAxis tick={{ fontSize: 10, fill: '#888' }} width={45} />
          <Tooltip
            contentStyle={{ background: '#222', border: '1px solid #444', fontSize: 12 }}
            labelStyle={{ color: '#ccc' }}
          />
          {stats.p25 !== null && stats.p75 !== null && (
            <ReferenceArea
              y1={stats.p25}
              y2={stats.p75}
              fill={color}
              fillOpacity={0.06}
            />
          )}
          <ReferenceLine y={stats.p50} stroke="#666" strokeDasharray="4 4" />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            dot={false}
            strokeWidth={1.5}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && pnpm --filter @ytrader/web exec tsc --noEmit 2>&1 | grep -i "ValuationPercentileChart" | head`
Expected: 无该文件的类型错误。

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/components/ValuationPercentileChart.tsx
git commit -m "feat(web): ValuationPercentileChart 分位图组件"
```

---

## Task 5: P0a 前端 —— Valuation.tsx 页面 + 路由 + 菜单

**Files:**
- Create: `frontend/apps/web/src/pages/Valuation.tsx`
- Modify: `frontend/apps/web/src/App.tsx`
- Modify: `frontend/apps/web/src/components/Layout.tsx`

**Interfaces:**
- Consumes: `useValuationPercentile`（Task 3）、`ValuationPercentileChart`（Task 4）、`StockSearch`（复用 Financial.tsx 的搜索组件）

- [ ] **Step 1: Read StockSearch usage to know its props**

Run: `cd frontend && grep -n "StockSearch" apps/web/src/pages/Financial.tsx | head -5`
确认 StockSearch 的 props（通常是 `onSelect` / `value` 之类）。查看其定义文件确认接口。

- [ ] **Step 2: Create the page**

Create `frontend/apps/web/src/pages/Valuation.tsx`:

```tsx
/**
 * 估值分位页（P0a）。
 *
 * 输入个股 → 展示 PE_TTM/PB/PS_TTM/股息率在 3/5/10 年的分位。
 */
import { useState } from 'react';
import { useValuationPercentile } from '../hooks/useValuationPercentile';
import { ValuationPercentileChart } from '../components/ValuationPercentileChart';
import { StockSearch } from '../components/StockSearch';

const METRIC_DEFS: Array<{ key: string; label: string; unit: string; color: string }> = [
  { key: 'pe_ttm', label: '市盈率 TTM', unit: '', color: '#2563eb' },
  { key: 'pb', label: '市净率', unit: '', color: '#16a34a' },
  { key: 'ps_ttm', label: '市销率 TTM', unit: '', color: '#9333ea' },
  { key: 'dv_ttm', label: '股息率 TTM', unit: '%', color: '#ea580c' },
];

const WINDOW_OPTIONS = ['3y', '5y', '10y'] as const;

export default function Valuation() {
  const [symbol, setSymbol] = useState<string | null>(null);
  const [windowKey, setWindowKey] = useState<string>('10y');

  const { data, loading, error } = useValuationPercentile(symbol, {
    windows: WINDOW_OPTIONS.join(','),
  });

  return (
    <div style={{ padding: 16, color: '#e0e0e0', maxWidth: 1200, margin: '0 auto' }}>
      <h2 style={{ marginBottom: 16 }}>估值分位</h2>

      <div style={{ marginBottom: 12 }}>
        <StockSearch onSelect={(sym: string) => setSymbol(sym)} />
      </div>

      <div style={{ marginBottom: 16, display: 'flex', gap: 8 }}>
        {WINDOW_OPTIONS.map((w) => (
          <button
            key={w}
            onClick={() => setWindowKey(w)}
            style={{
              padding: '4px 14px',
              borderRadius: 16,
              border: '1px solid',
              borderColor: windowKey === w ? '#2563eb' : '#444',
              background: windowKey === w ? '#2563eb' : 'transparent',
              color: '#fff',
              cursor: 'pointer',
            }}
          >
            {w}
          </button>
        ))}
      </div>

      {loading && <div>加载中…</div>}
      {error && <div style={{ color: '#dc2626' }}>{error}</div>}

      {data && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: 12,
          }}
        >
          {METRIC_DEFS.map((md) => (
            <ValuationPercentileChart
              key={md.key}
              title={md.label}
              unit={md.unit}
              color={md.color}
              windowKey={windowKey}
              metric={data.metrics[md.key] ?? null}
            />
          ))}
        </div>
      )}

      {!symbol && !loading && (
        <div style={{ padding: 48, textAlign: 'center', color: '#888' }}>
          请选择一只股票查看估值分位
        </div>
      )}
    </div>
  );
}
```

> 注：若 `StockSearch` 的实际 props 与 `onSelect` 不符，按 Step 1 查到的接口调整。

- [ ] **Step 3: Add route in App.tsx**

在 `frontend/apps/web/src/App.tsx` 找到现有 `<Route>` 列表（约 55-86 行），加一行：

```tsx
<Route path="/valuation" element={<Valuation />} />
```

并在顶部的 lazy import 区或普通 import 区加：

```tsx
import Valuation from './pages/Valuation';
```

> 参考其他非 lazy 页面的 import 方式（如 `Financial`）。

- [ ] **Step 4: Add menu item in Layout.tsx**

在 `frontend/apps/web/src/components/Layout.tsx` 的 `navGroups` Overview 组（约 31-45 行）加一项。先读该文件确认 Overview 组结构，然后在合适位置（如 `/financial` 之后）插入：

```tsx
{ path: '/valuation', label: '估值分位', icon: <ChartIcon /> },
```

> icon 从 `components/icons.tsx` 选一个合适的（如已有的 ChartIcon / TrendIcon）。

- [ ] **Step 5: Verify build**

Run: `cd frontend && pnpm --filter @ytrader/web build 2>&1 | tail -20`
Expected: 构建成功（或仅有既有无关 warning）。

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/pages/Valuation.tsx frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(web): P0a 估值分位独立页 /valuation + 菜单"
```

---

## Task 6: P0b 数据层 —— index_valuation 表 + repository

**Files:**
- Create: `backend/src/infra/database/market/index_valuation.py`

**Interfaces:**
- Produces: `IndexValuationDaily` / `SwIndexValuationDaily` 模型 + `IndexValuationRepository`（含 `upsert` / `get_range` / `bulk_upsert`）+ 工厂函数 `create_index_valuation_repository()`

- [ ] **Step 1: Create the models + repository**

Create `backend/src/infra/database/market/index_valuation.py`（完全照搬 `valuation.py` 的结构模式）:

```python
"""指数/申万行业估值日线表。

两张表结构相同，分别存宽基指数（沪深300/上证50/中证500/1000）和
申万一级行业的估值日线。数据来源：
  - akshare sw_index_first_info（当天快照，每日落盘）
  - 成分股加权自算（历史回填，source='computed'）

口径：PE_TTM/PB/PS_TTM/股息率/总市值合计。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class IndexValuationDaily(SQLModel, table=True):
    """宽基指数估值日线。"""
    __tablename__ = "index_valuation_daily"

    symbol: str = Field(primary_key=True)      # 000300 / 000016 / 000905 / 000852
    trade_date: dt.date = Field(primary_key=True)
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    dv_ttm: Optional[float] = None
    total_mv: Optional[float] = None           # 成分股总市值合计(亿)
    close: Optional[float] = None              # 指数收盘
    source: str = Field(default="akshare")     # akshare | computed
    created_at: datetime = Field(default_factory=datetime.now)


class SwIndexValuationDaily(SQLModel, table=True):
    """申万一级行业估值日线。"""
    __tablename__ = "sw_index_valuation_daily"

    sw_code: str = Field(primary_key=True)     # sw801010
    trade_date: dt.date = Field(primary_key=True)
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    dv_ttm: Optional[float] = None
    total_mv: Optional[float] = None
    close: Optional[float] = None
    source: str = Field(default="akshare")
    created_at: datetime = Field(default_factory=datetime.now)


class IndexValuationRepository:
    """指数/行业估值数据访问。同时管理两张表。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def upsert_index(
        self, symbol: str, trade_date: dt.date,
        pe_ttm=None, pb=None, ps_ttm=None, dv_ttm=None,
        total_mv=None, close=None, source="akshare",
    ) -> None:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(IndexValuationDaily).where(
                    IndexValuationDaily.symbol == symbol,
                    IndexValuationDaily.trade_date == trade_date,
                )
            ).first()
            if existing:
                existing.pe_ttm = pe_ttm
                existing.pb = pb
                existing.ps_ttm = ps_ttm
                existing.dv_ttm = dv_ttm
                existing.total_mv = total_mv
                existing.close = close
                existing.source = source
            else:
                s.add(IndexValuationDaily(
                    symbol=symbol, trade_date=trade_date,
                    pe_ttm=pe_ttm, pb=pb, ps_ttm=ps_ttm, dv_ttm=dv_ttm,
                    total_mv=total_mv, close=close, source=source,
                ))

    def upsert_sw(
        self, sw_code: str, trade_date: dt.date,
        pe_ttm=None, pb=None, ps_ttm=None, dv_ttm=None,
        total_mv=None, close=None, source="akshare",
    ) -> None:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(SwIndexValuationDaily).where(
                    SwIndexValuationDaily.sw_code == sw_code,
                    SwIndexValuationDaily.trade_date == trade_date,
                )
            ).first()
            if existing:
                existing.pe_ttm = pe_ttm
                existing.pb = pb
                existing.ps_ttm = ps_ttm
                existing.dv_ttm = dv_ttm
                existing.total_mv = total_mv
                existing.close = close
                existing.source = source
            else:
                s.add(SwIndexValuationDaily(
                    sw_code=sw_code, trade_date=trade_date,
                    pe_ttm=pe_ttm, pb=pb, ps_ttm=ps_ttm, dv_ttm=dv_ttm,
                    total_mv=total_mv, close=close, source=source,
                ))

    def get_index_range(
        self, symbol: str, start: dt.date, end: dt.date,
    ) -> list[IndexValuationDaily]:
        with self._db.session_scope() as s:
            rows = list(s.exec(
                select(IndexValuationDaily).where(
                    IndexValuationDaily.symbol == symbol,
                    IndexValuationDaily.trade_date >= start,
                    IndexValuationDaily.trade_date <= end,
                ).order_by(IndexValuationDaily.trade_date.asc())
            ).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_sw_range(
        self, sw_code: str, start: dt.date, end: dt.date,
    ) -> list[SwIndexValuationDaily]:
        with self._db.session_scope() as s:
            rows = list(s.exec(
                select(SwIndexValuationDaily).where(
                    SwIndexValuationDaily.sw_code == sw_code,
                    SwIndexValuationDaily.trade_date >= start,
                    SwIndexValuationDaily.trade_date <= end,
                ).order_by(SwIndexValuationDaily.trade_date.asc())
            ).all())
            for r in rows:
                s.expunge(r)
            return rows

    def bulk_upsert_index(self, rows: list[dict]) -> int:
        return self._bulk_upsert(
            rows, "index_valuation_daily", "symbol",
        )

    def bulk_upsert_sw(self, rows: list[dict]) -> int:
        return self._bulk_upsert(
            rows, "sw_index_valuation_daily", "sw_code",
        )

    def _bulk_upsert(
        self, rows: list[dict], table: str, code_key: str,
    ) -> int:
        if not rows:
            return 0
        values = []
        for r in rows:
            td = r.get("trade_date")
            if hasattr(td, "date"):
                td = td.date()
            values.append((
                r[code_key], td,
                r.get("pe_ttm"), r.get("pb"), r.get("ps_ttm"),
                r.get("dv_ttm"), r.get("total_mv"), r.get("close"),
                r.get("source", "akshare"),
            ))
        sql = f"""
            INSERT INTO {table}
                ({code_key}, trade_date, pe_ttm, pb, ps_ttm,
                 dv_ttm, total_mv, close, source)
            VALUES %s
            ON CONFLICT (trade_date, {code_key}) DO UPDATE SET
                pe_ttm=EXCLUDED.pe_ttm, pb=EXCLUDED.pb, ps_ttm=EXCLUDED.ps_ttm,
                dv_ttm=EXCLUDED.dv_ttm, total_mv=EXCLUDED.total_mv,
                close=EXCLUDED.close, source=EXCLUDED.source
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)


# ======== 工厂函数 ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_index_valuation_repository(
    db_connection: DBConnection | None = None,
) -> IndexValuationRepository:
    return IndexValuationRepository(db_connection or _get_db_connection())
```

- [ ] **Step 2: Verify import works and table auto-creates**

Run:
```bash
cd backend && python -c "
from src.infra.database.market.index_valuation import (
    IndexValuationDaily, SwIndexValuationDaily,
    create_index_valuation_repository,
)
print('import OK')
from src.infra.database.sql_engine.engine import engine
from sqlmodel import SQLModel
SQLModel.metadata.create_all(engine)
print('tables ensured')
"
```
Expected: `import OK` + `tables ensured`

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/database/market/index_valuation.py
git commit -m "feat(db): index_valuation_daily + sw_index_valuation_daily 表与 repository"
```

---

## Task 7: P0b 数据层 —— index_financial_quarterly 表

**Files:**
- Create: `backend/src/infra/database/market/index_financial.py`

**Interfaces:**
- Produces: `IndexFinancialQuarterly` 模型 + `IndexFinancialRepository`（`upsert` / `get_series` / `bulk_upsert`）+ 工厂函数

- [ ] **Step 1: Create the model + repository**

Create `backend/src/infra/database/market/index_financial.py`:

```python
"""指数/行业季度财务聚合表。

把指数（沪深300等）或申万一级行业当作整体，按报告期聚合成分股财务：
  ROE（净资产加权）、净利率/毛利率（净利/营收加总比）、
  营收/净利/资产总额（成分股加总）。

scope_type: "index"（宽基）| "sw"（申万行业）
scope_code: 指数代码 或 申万行业代码
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class IndexFinancialQuarterly(SQLModel, table=True):
    """指数/行业季度财务聚合。"""
    __tablename__ = "index_financial_quarterly"

    scope_type: str = Field(primary_key=True)   # index | sw
    scope_code: str = Field(primary_key=True)   # 000300 | sw801010
    report_date: dt.date = Field(primary_key=True)
    roe: Optional[float] = None                 # 净资产加权 ROE (%)
    net_margin: Optional[float] = None          # 净利率 = Σ净利/Σ营收 (%)
    gross_margin: Optional[float] = None        # 毛利率 (%)
    revenue_sum: Optional[float] = None         # 成分股营收加总(亿)
    net_profit_sum: Optional[float] = None      # 成分股净利加总(亿)
    assets_sum: Optional[float] = None          # 成分股总资产加总(亿)
    sample_count: int = 0                       # 纳入计算的成分股数
    created_at: datetime = Field(default_factory=datetime.now)


class IndexFinancialRepository:
    """指数/行业财务聚合数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def upsert(self, scope_type: str, scope_code: str, report_date: dt.date,
               roe=None, net_margin=None, gross_margin=None,
               revenue_sum=None, net_profit_sum=None, assets_sum=None,
               sample_count=0) -> None:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(IndexFinancialQuarterly).where(
                    IndexFinancialQuarterly.scope_type == scope_type,
                    IndexFinancialQuarterly.scope_code == scope_code,
                    IndexFinancialQuarterly.report_date == report_date,
                )
            ).first()
            if existing:
                existing.roe = roe
                existing.net_margin = net_margin
                existing.gross_margin = gross_margin
                existing.revenue_sum = revenue_sum
                existing.net_profit_sum = net_profit_sum
                existing.assets_sum = assets_sum
                existing.sample_count = sample_count
            else:
                s.add(IndexFinancialQuarterly(
                    scope_type=scope_type, scope_code=scope_code,
                    report_date=report_date, roe=roe, net_margin=net_margin,
                    gross_margin=gross_margin, revenue_sum=revenue_sum,
                    net_profit_sum=net_profit_sum, assets_sum=assets_sum,
                    sample_count=sample_count,
                ))

    def get_series(
        self, scope_type: str, scope_code: str,
        start: Optional[dt.date] = None, end: Optional[dt.date] = None,
    ) -> list[IndexFinancialQuarterly]:
        with self._db.session_scope() as s:
            stmt = select(IndexFinancialQuarterly).where(
                IndexFinancialQuarterly.scope_type == scope_type,
                IndexFinancialQuarterly.scope_code == scope_code,
            )
            if start:
                stmt = stmt.where(IndexFinancialQuarterly.report_date >= start)
            if end:
                stmt = stmt.where(IndexFinancialQuarterly.report_date <= end)
            stmt = stmt.order_by(IndexFinancialQuarterly.report_date.asc())
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def bulk_upsert(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        values = []
        for r in rows:
            rd = r.get("report_date")
            if hasattr(rd, "date"):
                rd = rd.date()
            values.append((
                r["scope_type"], r["scope_code"], rd,
                r.get("roe"), r.get("net_margin"), r.get("gross_margin"),
                r.get("revenue_sum"), r.get("net_profit_sum"),
                r.get("assets_sum"), r.get("sample_count", 0),
            ))
        sql = """
            INSERT INTO index_financial_quarterly
                (scope_type, scope_code, report_date, roe, net_margin,
                 gross_margin, revenue_sum, net_profit_sum, assets_sum,
                 sample_count)
            VALUES %s
            ON CONFLICT (scope_type, scope_code, report_date) DO UPDATE SET
                roe=EXCLUDED.roe, net_margin=EXCLUDED.net_margin,
                gross_margin=EXCLUDED.gross_margin, revenue_sum=EXCLUDED.revenue_sum,
                net_profit_sum=EXCLUDED.net_profit_sum, assets_sum=EXCLUDED.assets_sum,
                sample_count=EXCLUDED.sample_count
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)


# ======== 工厂函数 ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_index_financial_repository(
    db_connection: DBConnection | None = None,
) -> IndexFinancialRepository:
    return IndexFinancialRepository(db_connection or _get_db_connection())
```

- [ ] **Step 2: Verify import + table creation**

Run:
```bash
cd backend && python -c "
from src.infra.database.market.index_financial import (
    IndexFinancialQuarterly, create_index_financial_repository,
)
from sqlmodel import SQLModel
from src.infra.database.sql_engine.engine import engine
SQLModel.metadata.create_all(engine)
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/database/market/index_financial.py
git commit -m "feat(db): index_financial_quarterly 表与 repository"
```

---

## Task 8: P0b 同步 job —— 每日行业估值落盘

**Files:**
- Create: `backend/src/domain/market/sync/jobs/index_valuation_sync.py`
- Modify: `backend/src/infra/scheduler.py`

**Interfaces:**
- Consumes: `AkshareProvider.fetch_sw_index_valuation_snapshot()`（已有，`akshare_provider.py:344`）、`IndexValuationRepository.upsert_sw()`（Task 6）
- Produces: `sync_sw_index_valuation_daily()` 函数 + scheduler 注册

- [ ] **Step 1: Create the sync job**

Create `backend/src/domain/market/sync/jobs/index_valuation_sync.py`:

```python
"""每日行业/指数估值落盘 job。

- sync_sw_index_valuation_daily(): 调 akshare sw_index_first_info，
  把当天 31 个行业的 PE/PB/PS/股息率落盘到 sw_index_valuation_daily。
  从今天起积累历史（akshare 该接口无历史）。
"""
import logging
import datetime as dt

from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.infra.database.market.index_valuation import (
    create_index_valuation_repository,
)

log = logging.getLogger(__name__)


def sync_sw_index_valuation_daily() -> int:
    """落盘当天申万一级行业估值快照。

    Returns:
        写入条数。
    """
    prov = AkshareProvider()
    data = prov.fetch_sw_index_valuation_snapshot()
    if not data:
        log.warning("[sync_sw_val] snapshot empty, skip")
        return 0

    repo = create_index_valuation_repository()
    today = dt.date.today()
    count = 0
    for item in data:
        try:
            repo.upsert_sw(
                sw_code=item.get("sw_code"),
                trade_date=today,
                pe_ttm=item.get("pe_ttm"),
                pb=item.get("pb"),
                dv_ttm=item.get("dividend_yield"),
                source="akshare",
            )
            count += 1
        except Exception as e:
            log.warning("[sync_sw_val] upsert %s failed: %s",
                        item.get("sw_code"), e)
    log.info("[sync_sw_val] saved %d industries for %s", count, today)
    return count
```

- [ ] **Step 2: Register in scheduler**

在 `backend/src/infra/scheduler.py` 找到现有的 `sched.add_job(...)` 区块（约 216 行起），在末尾追加：

```python
    # ── 每日行业估值落盘（P0b，工作日 16:10 收盘后）────────────────
    sched.add_job(
        lambda: _import_and_run(
            "src.domain.market.sync.jobs.index_valuation_sync",
            "sync_sw_index_valuation_daily",
        ),
        CronTrigger(hour=16, minute=10, day_of_week="mon-fri",
                    timezone="Asia/Shanghai"),
        id="sync_sw_index_valuation_daily",
        replace_existing=True,
    )
```

并在 scheduler.py 顶部 helper 区（`_build_refresh_job` 附近）加一个通用动态 import 辅助函数（若已有则复用）：

```python
def _import_and_run(module_path: str, func_name: str):
    """动态 import 并执行 job 函数（避免循环引用）。"""
    import importlib
    mod = importlib.import_module(module_path)
    fn = getattr(mod, func_name)
    fn()
```

- [ ] **Step 3: Verify import**

Run: `cd backend && python -c "from src.domain.market.sync.jobs.index_valuation_sync import sync_sw_index_valuation_daily; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/src/domain/market/sync/jobs/index_valuation_sync.py backend/src/infra/scheduler.py
git commit -m "feat(sync): 每日申万行业估值落盘 job + scheduler 注册"
```

---

## Task 9: P0b 同步 job —— 历史回填（成分股加权自算）

**Files:**
- Create: `backend/src/domain/market/sync/jobs/index_valuation_backfill.py`

**Interfaces:**
- Consumes: `StockValuationRepository.get_range()`、成分股映射、`IndexValuationRepository.bulk_upsert_sw/bulk_upsert_index()`
- Produces: `backfill_sw_valuation_history(sw_code, years=10)` / `backfill_index_valuation_history(symbol, years=10)`

> 注：这是本批最复杂的 job。成分股映射来源：申万行业用 `national_team_symbol_sector` 表（已有 symbol→sector）+ akshare `sw_index_first_info` 的 company_count；宽基指数用 akshare `index_stock_cons_csindex` 或硬编码核心成分。先做申万行业的回填，宽基指数回填可后续补。

- [ ] **Step 1: Check available component mapping**

Run:
```bash
cd backend && grep -n "sector\|sw_code\|industry" src/infra/database/market/national_team_holding.py | head -20
```
确认 `national_team_symbol_sector` 的字段（symbol / sector 名称）。这是 symbol→申万行业的映射，但可能缺 sw_code。需要补一个 sector 名称→sw_code 的映射表。

- [ ] **Step 2: Create a SW sector name→code mapping**

在 `index_valuation_backfill.py` 顶部内置申万一级 31 个行业的 名称→code 映射（从 akshare 快照或配置获取）。参考 `backend/conf/config.yaml` 的 `sw_industries` 配置（前次探查已确认存在完整列表）。

先读配置确认格式：
Run: `cd backend && grep -A2 "sw_industries" conf/config.yaml | head -10`

- [ ] **Step 3: Create the backfill job**

Create `backend/src/domain/market/sync/jobs/index_valuation_backfill.py`:

```python
"""一次性历史回填 job：用成分股估值加权自算指数/行业估值历史。

akshare 的 sw_index_first_info 只有当天快照、无历史。
本 job 用当前成分股的 stock_valuation 日线，按总市值加权自算
PE/PB 等的历史日线，回填到 sw_index_valuation_daily / index_valuation_daily，
source='computed'。

口径：用"当前成分股"近似历史成分（标注 source=computed）。
  PE_TTM = Σ(total_mv) / Σ(total_mv / pe_ttm)   （调和加权，避免负值放大）
  PB     = Σ(total_mv) / Σ(total_mv / pb)
"""
import logging
import datetime as dt
from typing import Optional

from src.infra.database.market.valuation import (
    create_stock_valuation_repository,
)
from src.infra.database.market.index_valuation import (
    create_index_valuation_repository,
)
from src.infra.database.market.national_team_holding import (
    NationalTeamSymbolSector,
)
from src.infra.database.sql_engine.engine import engine
from sqlmodel import Session, select

log = logging.getLogger(__name__)


def _load_sw_sector_symbols() -> dict[str, list[str]]:
    """从 national_team_symbol_sector 加载 申万行业名→[symbol]。

    Returns:
        {sector_name: [sh600519, sz000001, ...]}
    """
    out: dict[str, list[str]] = {}
    with Session(engine) as s:
        rows = s.exec(select(NationalTeamSymbolSector)).all()
        for r in rows:
            sector = getattr(r, "sector", None) or getattr(r, "sw_industry", None)
            sym = getattr(r, "symbol", None)
            if sector and sym:
                out.setdefault(sector, []).append(sym)
    return out


def _compute_weighted_pe(
    rows_by_symbol: dict[str, list],
    trade_date: dt.date,
) -> Optional[float]:
    """市值加权 PE_TTM（调和加权）。

    rows_by_symbol: {symbol: [StockValuation, ...]}（已按日期升序）
    trade_date: 取每个 symbol <= trade_date 的最近一行

    Returns:
        加权 PE_TTM；样本不足返回 None。
    """
    mv_sum = 0.0
    pe_weighted_sum = 0.0
    for sym, rows in rows_by_symbol.items():
        # 取 <= trade_date 的最近一行
        row = None
        for r in rows:
            if r.trade_date <= trade_date:
                row = r
            else:
                break
        if row is None or row.pe_ttm is None or row.pe_ttm <= 0:
            continue
        if row.total_mv is None or row.total_mv <= 0:
            continue
        mv_sum += row.total_mv
        pe_weighted_sum += row.total_mv / row.pe_ttm
    if mv_sum <= 0 or pe_weighted_sum <= 0:
        return None
    return mv_sum / pe_weighted_sum


def _compute_weighted_pb(rows_by_symbol, trade_date) -> Optional[float]:
    mv_sum = 0.0
    pb_weighted_sum = 0.0
    for sym, rows in rows_by_symbol.items():
        row = None
        for r in rows:
            if r.trade_date <= trade_date:
                row = r
            else:
                break
        if row is None or row.pb is None or row.pb <= 0:
            continue
        if row.total_mv is None or row.total_mv <= 0:
            continue
        mv_sum += row.total_mv
        pb_weighted_sum += row.total_mv / row.pb
    if mv_sum <= 0 or pb_weighted_sum <= 0:
        return None
    return mv_sum / pb_weighted_sum


def backfill_sw_valuation_by_sector_name(
    sector_name: str,
    sw_code: str,
    years: int = 10,
) -> int:
    """回填单个申万行业的估值历史（成分股加权自算）。

    Args:
        sector_name: 申万行业名称（如 '银行'）
        sw_code:     sw801780
        years:       回填年数

    Returns:
        写入条数。
    """
    sector_map = _load_sw_sector_symbols()
    symbols = sector_map.get(sector_name, [])
    if not symbols:
        log.warning("[backfill_sw] no symbols for sector %s", sector_name)
        return 0

    val_repo = create_stock_valuation_repository()
    idx_repo = create_index_valuation_repository()

    end = dt.date.today()
    start = dt.date(end.year - years, end.month, end.day)

    # 批量拉每个 symbol 的估值区间
    rows_by_symbol: dict[str, list] = {}
    for sym in symbols:
        try:
            rows_by_symbol[sym] = val_repo.get_range(sym, start, end)
        except Exception as e:
            log.debug("[backfill_sw] %s get_range failed: %s", sym, e)

    if not rows_by_symbol:
        return 0

    # 收集所有交易日期（取并集，按月采样降频以控制写入量）
    all_dates: set[dt.date] = set()
    for rows in rows_by_symbol.values():
        for r in rows:
            all_dates.add(r.trade_date)

    # 月度采样：每月最后一个交易日
    month_last: dict[str, dt.date] = {}
    for d in sorted(all_dates):
        month_last[d.strftime("%Y-%m")] = d
    sample_dates = sorted(month_last.values())

    bulk_rows = []
    for d in sample_dates:
        pe = _compute_weighted_pe(rows_by_symbol, d)
        pb = _compute_weighted_pb(rows_by_symbol, d)
        if pe is None and pb is None:
            continue
        bulk_rows.append({
            "sw_code": sw_code, "trade_date": d,
            "pe_ttm": pe, "pb": pb,
            "source": "computed",
        })

    if bulk_rows:
        idx_repo.bulk_upsert_sw(bulk_rows)
    log.info("[backfill_sw] %s(%s): wrote %d monthly points",
             sector_name, sw_code, len(bulk_rows))
    return len(bulk_rows)
```

- [ ] **Step 4: Add a runner function for all SW sectors**

在 `index_valuation_backfill.py` 末尾追加：

```python
def backfill_all_sw_valuation(years: int = 10) -> dict[str, int]:
    """回填全部申万一级行业的估值历史。

    申万行业名→sw_code 映射从 akshare 当天快照取（复用 sync job 的快照）。
    Returns: {sw_code: wrote_count}
    """
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider
    prov = AkshareProvider()
    snapshot = prov.fetch_sw_index_valuation_snapshot()
    results: dict[str, int] = {}
    for item in snapshot:
        sector = item.get("industry")
        sw_code = item.get("sw_code")
        if not sector or not sw_code:
            continue
        try:
            n = backfill_sw_valuation_by_sector_name(sector, sw_code, years)
            results[sw_code] = n
        except Exception as e:
            log.warning("[backfill_all_sw] %s failed: %s", sw_code, e)
            results[sw_code] = 0
    return results
```

- [ ] **Step 5: Verify import**

Run: `cd backend && python -c "from src.domain.market.sync.jobs.index_valuation_backfill import backfill_all_sw_valuation; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/src/domain/market/sync/jobs/index_valuation_backfill.py
git commit -m "feat(sync): 申万行业估值历史回填 job（成分股加权自算，月度采样）"
```

---

## Task 10: P0b 同步 job —— 季度财务聚合

**Files:**
- Create: `backend/src/domain/market/sync/jobs/index_financial_sync.py`

**Interfaces:**
- Consumes: `stock_financial_detail` 数据（成分股财报）、`IndexFinancialRepository.bulk_upsert()`
- Produces: `sync_sw_financial_quarterly()` 函数

- [ ] **Step 1: Create the sync job**

Create `backend/src/domain/market/sync/jobs/index_financial_sync.py`:

```python
"""季度财务聚合 job：把指数/行业的成分股财报聚合为整体财务指标。

按报告期聚合：
  revenue_sum / net_profit_sum / assets_sum = 成分股加总
  net_margin = Σ净利 / Σ营收
  roe = Σ净利 / Σ净资产（净资产加权）
  sample_count = 有效样本数

数据源：stock_financial_detail（成分股三大报表）。
"""
import logging
import datetime as dt

from src.infra.database.market.index_financial import (
    create_index_financial_repository,
)
from src.infra.database.market.national_team_holding import (
    NationalTeamSymbolSector,
)
from src.infra.database.sql_engine.engine import engine
from sqlmodel import Session, select

log = logging.getLogger(__name__)


def _aggregate_sw_sector_financial(
    sector_name: str, sw_code: str,
) -> list[dict]:
    """聚合单个申万行业的季度财务。

    从 stock_financial_detail 取成分股营收/净利/资产，按报告期加总。

    Returns:
        list[dict]，每条含 scope_type/scoped_code/report_date/各聚合值。
    """
    # 取成分股
    symbols: list[str] = []
    with Session(engine) as s:
        rows = s.exec(select(NationalTeamSymbolSector).where(
            NationalTeamSymbolSector.sector == sector_name
        )).all()
        symbols = [r.symbol for r in rows if r.symbol]

    if not symbols:
        return []

    # 用裸 SQL 从 stock_financial_detail 按报告期聚合
    # detail JSONB 里存了各科目，这里取核心几个
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    out: list[dict] = []
    try:
        with conn.cursor() as cur:
            # 取成分股的 income/balance 报告期数据
            cur.execute("""
                SELECT report_date,
                       SUM(COALESCE((detail->>'营业总收入')::numeric, 0)) AS rev,
                       SUM(COALESCE((detail->>'净利润')::numeric, 0)) AS np,
                       SUM(COALESCE((detail->>'资产总计')::numeric, 0)) AS assets,
                       COUNT(*) AS cnt
                FROM stock_financial_detail
                WHERE symbol = ANY(%s)
                  AND statement_type = 'income'
                GROUP BY report_date
                ORDER BY report_date
            """, (symbols,))
            income_rows = cur.fetchall()
            # 资产负债表单独取（statement_type='balance'）
            cur.execute("""
                SELECT report_date,
                       SUM(COALESCE((detail->>'资产总计')::numeric, 0)) AS assets,
                       SUM(COALESCE((detail->>'股东权益合计')::numeric, 0)) AS equity,
                       COUNT(*) AS cnt
                FROM stock_financial_detail
                WHERE symbol = ANY(%s)
                  AND statement_type = 'balance'
                GROUP BY report_date
                ORDER BY report_date
            """, (symbols,))
            balance_map = {
                r[0]: {"assets": float(r[1] or 0), "equity": float(r[2] or 0), "cnt": r[3]}
                for r in cur.fetchall()
            }

            for rd, rev, np, assets, cnt in income_rows:
                rev = float(rev or 0)
                np = float(np or 0)
                bal = balance_map.get(rd, {})
                equity = bal.get("equity", 0)
                roe = (np / equity * 100) if equity > 0 else None
                net_margin = (np / rev * 100) if rev > 0 else None
                out.append({
                    "scope_type": "sw",
                    "scope_code": sw_code,
                    "report_date": rd,
                    "roe": roe,
                    "net_margin": net_margin,
                    "revenue_sum": rev / 1e8,        # 转亿
                    "net_profit_sum": np / 1e8,
                    "assets_sum": (bal.get("assets", 0)) / 1e8,
                    "sample_count": cnt,
                })
    finally:
        conn.close()
    return out


def sync_sw_financial_quarterly() -> dict[str, int]:
    """同步全部申万一级行业的季度财务聚合。

    Returns:
        {sw_code: wrote_count}
    """
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider
    prov = AkshareProvider()
    snapshot = prov.fetch_sw_index_valuation_snapshot()
    repo = create_index_financial_repository()
    results: dict[str, int] = {}
    for item in snapshot:
        sector = item.get("industry")
        sw_code = item.get("sw_code")
        if not sector or not sw_code:
            continue
        try:
            rows = _aggregate_sw_sector_financial(sector, sw_code)
            if rows:
                repo.bulk_upsert(rows)
            results[sw_code] = len(rows)
            log.info("[sync_sw_fin] %s: %d periods", sw_code, len(rows))
        except Exception as e:
            log.warning("[sync_sw_fin] %s failed: %s", sw_code, e)
            results[sw_code] = 0
    return results
```

> 注：`detail->>'营业总收入'` 等科目名需与 `stock_financial_detail` 的实际 JSONB key 对齐。实现时应先 `SELECT detail FROM stock_financial_detail LIMIT 1` 确认实际 key 名（可能是英文或中文），按实际调整。`NationalTeamSymbolSector.sector` 字段名也要确认（可能是 `sw_industry`）。

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "from src.domain.market.sync.jobs.index_financial_sync import sync_sw_financial_quarterly; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/domain/market/sync/jobs/index_financial_sync.py
git commit -m "feat(sync): 申万行业季度财务聚合 job"
```

---

## Task 11: P0b 后端端点 —— 指数/行业估值分位 + 财务聚合

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`
- Modify: `backend/src/api/router/financial_router.py`

**Interfaces:**
- Consumes: `IndexValuationRepository`（Task 6）、`IndexFinancialRepository`（Task 7）、`calc_percentile` / `percentile_stats`（Task 1）
- Produces: 3 个新端点

- [ ] **Step 1: Add handler functions**

在 `backend/src/api/handler/financial_detail_handler.py` 末尾追加：

```python
# ── P0b 指数/行业估值分位 + 财务聚合 ──────────────────────────────


def index_valuation_percentile(
    scope: str,          # "index" | "sw"
    code: str,           # 000300 | sw801010
    window: str = "10y",
    metrics: list[str] | None = None,
) -> Any:
    """指数/行业估值历史分位。

    Returns:
        success({scope, code, window, metrics: {metric: {current,
        stats: percentile_stats|None, series:[...]}}}).
    """
    from src.infra.database.market.index_valuation import (
        create_index_valuation_repository,
    )
    from src.domain.market.fundamental.percentile import (
        percentile_stats, downsample_monthly,
    )

    metrics = metrics or ["pe_ttm", "pb"]
    repo = create_index_valuation_repository()
    window_years = {"3y": 3, "5y": 5, "10y": 10}
    years = window_years.get(window, 10)

    import datetime as dt2
    end = dt2.date.today()
    start = dt2.date(end.year - years, end.month, end.day)

    if scope == "sw":
        rows = repo.get_sw_range(code, start, end)
    else:
        rows = repo.get_index_range(code, start, end)

    if not rows:
        return responses.success({
            "scope": scope, "code": code, "window": window,
            "metrics": {},
        })

    result: dict[str, dict] = {}
    for metric in metrics:
        attr = metric  # pe_ttm / pb / ps_ttm / dv_ttm
        samples = [
            getattr(r, attr) for r in rows
            if getattr(r, attr) is not None and getattr(r, attr) > 0
        ]
        current = samples[-1] if samples else None
        stats = percentile_stats(samples, current) if current else None
        series = downsample_monthly([
            {"date": r.trade_date.isoformat(), "value": getattr(r, attr)}
            for r in rows
            if getattr(r, attr) is not None and getattr(r, attr) > 0
        ])
        result[metric] = {"current": current, "stats": stats, "series": series}

    return responses.success({
        "scope": scope, "code": code, "window": window,
        "metrics": result,
    })


def index_financial_agg(
    scope: str, code: str,
) -> Any:
    """指数/行业季度财务聚合时序。

    Returns:
        success({scope, code, series: [{report_date, roe, net_margin,
        revenue_sum, net_profit_sum, assets_sum, sample_count}]}).
    """
    from src.infra.database.market.index_financial import (
        create_index_financial_repository,
    )
    repo = create_index_financial_repository()
    rows = repo.get_series(scope, code)
    series = [{
        "report_date": r.report_date.isoformat(),
        "roe": r.roe,
        "net_margin": r.net_margin,
        "gross_margin": r.gross_margin,
        "revenue_sum": r.revenue_sum,
        "net_profit_sum": r.net_profit_sum,
        "assets_sum": r.assets_sum,
        "sample_count": r.sample_count,
    } for r in rows]
    return responses.success({"scope": scope, "code": code, "series": series})


def index_valuation_percentile_batch(
    scope: str = "sw",
    window: str = "10y",
    metric: str = "pe_ttm",
) -> Any:
    """批量返回所有行业/指数的单指标分位（用于排行页）。

    Returns:
        success({scope, window, metric, items: [{code, current,
        percentile, sample_size}]}).
    """
    from src.infra.database.market.index_valuation import (
        create_index_valuation_repository,
    )
    from src.domain.market.fundamental.percentile import percentile_stats

    repo = create_index_valuation_repository()
    window_years = {"3y": 3, "5y": 5, "10y": 10}
    years = window_years.get(window, 10)
    import datetime as dt2
    end = dt2.date.today()
    start = dt2.date(end.year - years, end.month, end.day)

    # 取快照拿全部 code 列表
    snapshot = _get_industry_snapshot_cached()
    if scope != "sw" or not snapshot:
        return responses.success({"scope": scope, "window": window,
                                  "metric": metric, "items": []})

    items = []
    for item in snapshot:
        sw_code = item.get("sw_code")
        if not sw_code:
            continue
        rows = repo.get_sw_range(sw_code, start, end)
        samples = [
            getattr(r, metric) for r in rows
            if getattr(r, metric) is not None and getattr(r, metric) > 0
        ]
        current = samples[-1] if samples else None
        stats = percentile_stats(samples, current) if current else None
        items.append({
            "code": sw_code,
            "industry": item.get("industry"),
            "current": current,
            "percentile": stats["percentile"] if stats else None,
            "sample_size": stats["sample_size"] if stats else 0,
        })
    items.sort(key=lambda x: (x["percentile"] is None, x["percentile"]))
    return responses.success({"scope": scope, "window": window,
                              "metric": metric, "items": items})
```

- [ ] **Step 2: Add routes**

在 `backend/src/api/router/financial_router.py` 的 import 块加入新函数名：

```python
from src.api.handler.financial_detail_handler import (
    detail_series,
    forecast_list,
    industry_valuation_snapshot,
    stock_profile,
    valuation_history,
    valuation_percentile,
    index_valuation_percentile,
    index_financial_agg,
    index_valuation_percentile_batch,
)
```

在文件末尾追加：

```python
@router.get("/index-valuation-percentile")
def _index_valuation_percentile(
    scope: str = Query(..., description="index | sw"),
    code: str = Query(..., description="指数代码或申万行业代码"),
    window: str = Query("10y", description="3y/5y/10y"),
    metrics: str = Query("pe_ttm,pb", description="逗号分隔"),
):
    """指数/行业估值历史分位。"""
    met_list = [m.strip() for m in metrics.split(",") if m.strip()]
    return index_valuation_percentile(scope, code, window, met_list)


@router.get("/index-financial-agg")
def _index_financial_agg(
    scope: str = Query(..., description="index | sw"),
    code: str = Query(...),
):
    """指数/行业季度财务聚合时序。"""
    return index_financial_agg(scope, code)


@router.get("/index-valuation-percentile/batch")
def _index_valuation_percentile_batch(
    scope: str = Query("sw"),
    window: str = Query("10y"),
    metric: str = Query("pe_ttm"),
):
    """批量返回所有行业/指数的单指标分位（排行用）。"""
    return index_valuation_percentile_batch(scope, window, metric)
```

- [ ] **Step 3: Verify import**

Run: `cd backend && python -c "from src.api.handler.financial_detail_handler import index_valuation_percentile, index_financial_agg, index_valuation_percentile_batch; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/src/api/handler/financial_detail_handler.py backend/src/api/router/financial_router.py
git commit -m "feat(financial): P0b 指数/行业估值分位+财务聚合 端点"
```

---

## Task 12: P0b 前端 —— SectorScan 加行业分位列 + 下钻

**Files:**
- Modify: `frontend/apps/web/src/pages/SectorScan.tsx`
- Create: `frontend/apps/web/src/components/IndexFinancialChart.tsx`

**Interfaces:**
- Consumes: `GET /financial/index-valuation-percentile/batch`、`GET /financial/index-valuation-percentile`、`GET /financial/index-financial-agg`

- [ ] **Step 1: Create IndexFinancialChart component**

Create `frontend/apps/web/src/components/IndexFinancialChart.tsx`:

```tsx
/**
 * 指数/行业季度财务聚合图。
 * 双轴：左轴营收/净利加总(Bar)，右轴 ROE/净利率(Line %)。
 */
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts';

interface SeriesPoint {
  report_date: string;
  revenue_sum: number | null;
  net_profit_sum: number | null;
  roe: number | null;
  net_margin: number | null;
}

interface Props {
  data: SeriesPoint[];
}

export function IndexFinancialChart({ data }: Props) {
  if (!data || data.length === 0) {
    return <div style={{ padding: 24, textAlign: 'center', color: '#888' }}>财务数据不足</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="#333" strokeDasharray="3 3" />
        <XAxis dataKey="report_date" tick={{ fontSize: 10, fill: '#888' }} minTickGap={30} />
        <YAxis yAxisId="left" tick={{ fontSize: 10, fill: '#888' }} width={50} />
        <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: '#888' }} width={40} unit="%" />
        <Tooltip contentStyle={{ background: '#222', border: '1px solid #444', fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Bar yAxisId="left" dataKey="revenue_sum" name="营收(亿)" fill="#2563eb" opacity={0.6} />
        <Bar yAxisId="left" dataKey="net_profit_sum" name="净利(亿)" fill="#16a34a" opacity={0.6} />
        <Line yAxisId="right" type="monotone" dataKey="roe" name="ROE%" stroke="#ea580c" dot={false} strokeWidth={1.5} />
        <Line yAxisId="right" type="monotone" dataKey="net_margin" name="净利率%" stroke="#9333ea" dot={false} strokeWidth={1.5} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 2: Add batch percentile fetching to SectorScan**

读 `frontend/apps/web/src/pages/SectorScan.tsx` 当前结构，找到表格渲染处。在组件顶部加 batch 分位 fetch：

```tsx
// 在 SectorScan 组件内
const [batchPct, setBatchPct] = useState<Record<string, { percentile: number | null; current: number | null }>>({});

useEffect(() => {
  fetch(`${API_BASE}/financial/index-valuation-percentile/batch?scope=sw&window=10y&metric=pe_ttm`)
    .then((r) => r.json())
    .then((json) => {
      if (json.code === 0 && json.data?.items) {
        const map: Record<string, { percentile: number | null; current: number | null }> = {};
        for (const it of json.data.items) {
          map[it.code] = { percentile: it.percentile, current: it.current };
        }
        setBatchPct(map);
      }
    })
    .catch(() => {});
}, []);
```

在表格里为每个行业行加一列"PE 10y 分位"，从 `batchPct[sw_code]` 取值，显示百分比 + 颜色（复用 `ValuationPercentileChart` 的 `percentileColor` 逻辑，可抽到 lib）。

> 具体 JSX 改动取决于 SectorScan 现有表格结构，实现时读文件后按其 `<table>` 结构插入 `<td>`。

- [ ] **Step 3: Add drilldown on row click**

点击行业行 → 展开一个面板（Modal 或 inline）显示该行业的 `ValuationPercentileChart`（scope=sw）+ `IndexFinancialChart`。数据来自 `GET /financial/index-valuation-percentile?scope=sw&code=...&window=10y` 和 `GET /financial/index-financial-agg?scope=sw&code=...`。

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm --filter @ytrader/web build 2>&1 | tail -10`
Expected: 构建成功。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/SectorScan.tsx frontend/apps/web/src/components/IndexFinancialChart.tsx
git commit -m "feat(web): P0b SectorScan 加行业 PE 分位列 + 下钻分位/财务图"
```

---

## Task 13: P0b 前端 —— Indices 加指数分位徽章

**Files:**
- Modify: `frontend/apps/web/src/pages/Indices.tsx`

**Interfaces:**
- Consumes: `GET /financial/index-valuation-percentile?scope=index&code=...&window=10y&metrics=pe_ttm`

- [ ] **Step 1: Read Indices.tsx card structure**

Run: `cd frontend && grep -n "card\|Card\|pe_ttm\|pe\b" apps/web/src/pages/Indices.tsx | head -15`
确认宽基指数卡片的渲染位置。

- [ ] **Step 2: Add percentile badge to index cards**

在宽基指数卡片上，fetch 其 PE_TTM 10y 分位，显示一个徽章（如"PE 10y: 35%"）。由于 Indices 页已有很多 fetch，加一个轻量的分位 fetch（仅在宽基指数 category 时触发）。

实现时在卡片组件内加：

```tsx
const [pct, setPct] = useState<number | null>(null);
useEffect(() => {
  if (category !== '宽基') return;
  fetch(`${API_BASE}/financial/index-valuation-percentile?scope=index&code=${indexCode}&window=10y&metrics=pe_ttm`)
    .then((r) => r.json())
    .then((json) => {
      if (json.code === 0) {
        const m = json.data?.metrics?.pe_ttm;
        setPct(m?.stats?.percentile ?? null);
      }
    })
    .catch(() => {});
}, [category, indexCode]);
```

徽章 JSX：
```tsx
{pct !== null && (
  <span style={{ fontSize: 11, color: pct < 0.2 ? '#16a34a' : pct > 0.8 ? '#dc2626' : '#ca8a04' }}>
    PE 10y: {(pct * 100).toFixed(0)}%
  </span>
)}
```

> 具体 indexCode 映射（如"沪深300"→"000300"）需从 Indices.tsx 的数据结构确认。

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm --filter @ytrader/web build 2>&1 | tail -10`
Expected: 构建成功。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/pages/Indices.tsx
git commit -m "feat(web): P0b Indices 宽基指数卡片加 PE 10y 分位徽章"
```

---

## Task 14: P3 前端 —— normalize 工具 + FinancialOverlayChart 升级

**Files:**
- Create: `frontend/apps/web/src/lib/normalize.ts`
- Modify: `frontend/apps/web/src/components/FinancialOverlayChart.tsx`

**Interfaces:**
- Produces: `minMaxNormalize(values) -> number[]`、升级后的 `FinancialOverlayChart` 支持 `overlays` 多选 + 归一化

- [ ] **Step 1: Create normalize util**

Create `frontend/apps/web/src/lib/normalize.ts`:

```typescript
/**
 * 归一化工具（min-max 到 0-100）。
 * 用于多指标叠加图，把不同量纲的指标拉到同一刻度。
 */
export function minMaxNormalize(values: number[]): number[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return values.map(() => 50);
  return values.map((v) => ((v - min) / (max - min)) * 100);
}
```

- [ ] **Step 2: Read current FinancialOverlayChart props**

Run: `cd frontend && sed -n '25,80p' apps/web/src/components/FinancialOverlayChart.tsx`
确认现有 `Props` 接口、`MetricDef`、`overlays` 用法。现有组件已支持叠加层（stock_price/industry_index/pe/pb/ps）。

- [ ] **Step 3: Extend MetricDef and Props**

在 `FinancialOverlayChart.tsx` 扩展 `MetricDef`：

```tsx
export interface MetricDef {
  key: string;
  label: string;
  color: string;
  isPercent?: boolean;
  axis?: 'left' | 'right';    // 新增：归属轴
  normalize?: boolean;          // 新增：是否归一化到 0-100
}
```

- [ ] **Step 4: Add overlay multi-select chips**

在组件渲染区（chips 行附近）加一个"叠加指标"多选 chip 组，让用户勾选要叠加的指标（pe/pb/ps/dv/roe/营收/净利/股价归一化）。

实现思路：
- 新增 state `const [selectedOverlays, setSelectedOverlays] = useState<string[]>(['pe', 'pb'])`
- 一组 chip 按钮（参考 Indices.tsx 的筛选 chip 范式），点击 toggle
- 每个 overlay 用 minMaxNormalize 归一化后作为额外 Line 叠加到 ComposedChart

> 关键：向后兼容。现有 `overlays` prop（来自 useFinancialOverlays 的 OverlayData）行为不变，新增能力通过内部 state + chip 控制。

- [ ] **Step 5: Apply normalization in chart data**

在构造 chart data 时，对每个选中的 overlay 指标，若 `normalize=true`，用 `minMaxNormalize` 转换后加为新的 dataKey：

```tsx
import { minMaxNormalize } from '../lib/normalize';

// 在构造 data 时
const overlayKeys = ['pe', 'pb', 'ps', 'dv', 'roe']; // 可选集
// 对每个 key，取所有点的值，归一化，写回 data
```

- [ ] **Step 6: Verify build and no regression**

Run: `cd frontend && pnpm --filter @ytrader/web build 2>&1 | tail -15`
Expected: 构建成功，Financial 页现有图表不受影响（默认行为不变）。

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/web/src/lib/normalize.ts frontend/apps/web/src/components/FinancialOverlayChart.tsx
git commit -m "feat(web): P3 FinancialOverlayChart 多指标叠加 + min-max 归一化"
```

---

## Task 15: 集成验证 + 收尾

**Files:**
- 全局

- [ ] **Step 1: Backend smoke test all new endpoints**

启动后端（`cd backend && python main.py` 或 `./dev-start.sh`），依次请求：

```bash
# P0a
curl -s "http://localhost:12100/api/v1/financial/valuation-percentile/sz000001" | python -m json.tool | head -20

# P0b 单个行业
curl -s "http://localhost:12100/api/v1/financial/index-valuation-percentile?scope=sw&code=sw801010&window=10y" | python -m json.tool | head -20

# P0b 批量
curl -s "http://localhost:12100/api/v1/financial/index-valuation-percentile/batch?scope=sw&window=10y&metric=pe_ttm" | python -m json.tool | head -20

# P0b 财务聚合
curl -s "http://localhost:12100/api/v1/financial/index-financial-agg?scope=sw&code=sw801010" | python -m json.tool | head -20
```

Expected: 均返回 `code: 0`（P0b 端点若数据未回填则 metrics/series 为空，属正常）。

- [ ] **Step 2: Run daily sync job manually (trigger data accumulation)**

```bash
cd backend && python -c "
from src.domain.market.sync.jobs.index_valuation_sync import sync_sw_index_valuation_daily
n = sync_sw_index_valuation_daily()
print(f'synced {n} industries')
"
```
Expected: 写入 ~31 条当天行业估值。

- [ ] **Step 3: Run backfill job manually (one-time, async)**

```bash
cd backend && python -c "
import logging
logging.basicConfig(level=logging.INFO)
from src.domain.market.sync.jobs.index_valuation_backfill import backfill_all_sw_valuation
results = backfill_all_sw_valuation(years=5)
print(f'backfill results: {results}')
" &
```
> 这是耗时 job（拉 5 年成分股估值），放后台跑。完成后 P0b 端点才有历史分位数据。

- [ ] **Step 4: Frontend smoke test**

启动前端，访问：
- `/valuation` → 输入个股 → 看到 4 个分位图（P0a）
- `/market` → SectorScan → 行业行有 PE 分位列 + 点击下钻（P0b）
- `/indices` → 宽基指数卡片有分位徽章（P0b）
- `/financial` → 财务图叠加 chip 可多选 + 归一化（P3）

- [ ] **Step 5: Run backend test suite (no regressions)**

Run: `cd backend && python -m pytest tests/domain/test_percentile.py tests/api/test_valuation_percentile.py -v`
Expected: PASS

- [ ] **Step 6: Final commit if any cleanup**

```bash
git status
# 若有未提交的修复
git add -A && git commit -m "chore: 批次1 集成验证修复"
```

---

## Self-Review Checklist（实现完成后自查）

实现完所有 task 后，对照 spec 自查：

1. **P0a 覆盖**：`/valuation` 页可查个股 PE/PB/PS/股息率 × 3/5/10y 分位？✓ Task 1-5
2. **P0b 估值分位**：行业/指数有估值历史分位？✓ Task 6,8,9,11,12,13
3. **P0b 财务聚合**：行业有 ROE/净利率等季度聚合？✓ Task 7,10,11
4. **P3 多指标叠加**：FinancialOverlayChart 支持多选叠加 + 归一化？✓ Task 14
5. **数据落盘**：每日行业估值 job 已注册到 scheduler？✓ Task 8
6. **历史回填**：成分股加权自算回填 job 可手动跑？✓ Task 9
7. **缓存**：P0a 有 1h 缓存？✓ Task 2 (`_VALPCT_CACHE_TTL`)
8. **负值处理**：PE/PS 负值不纳入分位？✓ Task 1/2 (`> 0` 过滤)
9. **样本下限**：<30 返回 None？✓ Task 1 (`SAMPLE_MIN`)
10. **YAGNI 边界**：未做 restated/自定义作图/B股？✓ 确认无超范围代码

---

## 落地顺序映射

| Spec 落地顺序 | 对应 Task |
|---|---|
| 1. P0a 后端 | Task 1-2 |
| 2. P0a 前端 | Task 3-5 |
| 3. P0b 数据层（表+落盘 job） | Task 6-8 |
| 4. P0b 历史回填 | Task 9 |
| 5. P0b 端点 + 前端 | Task 11-13 |
| 6. P0b 财务聚合 | Task 7,10,11 |
| 7. P3 | Task 14 |
| 集成验证 | Task 15 |
