# 市值与业绩增长趋势（指数+个股）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 中证系 9 宽基指数与个股两层提供「营收/归母净利润（单季/累计/TTM）柱 + 总市值折线」双轴趋势图（参考直播截图形态）。

**Architecture:** 新表 `index_constituent`（csindex 成分快照）驱动两个灌数 job——指数财务聚合（写既有 `index_financial_quarterly` scope='index'）与月度市值回填（写既有 `index_valuation_daily.total_mv`）；口径换算收敛在后端纯函数模块；两个同形新端点一次返回三口径；前端单一 `MarketCapGrowthChart` 组件复用在 Indices 页区块与 Financial 页新 Tab。

**Tech Stack:** FastAPI + SQLModel/psycopg2 + APScheduler（后端）；react + recharts + chartTheme 常量（前端）。

**规格:** `docs/superpowers/specs/2026-08-27-market-cap-growth-design.md`（已批准）。

## Global Constraints

- 后端命令在 `backend/` 目录下执行，用 `uv run pytest <file> -v`；**只跑本计划涉及的测试文件**（全量回归有既有失败，见项目记忆）。
- 前端构建在 `frontend/` 目录下 `pnpm -F web build`，期望 EXIT=0。
- 单位约定：API 响应统一**亿元、round 2**；`index_financial_quarterly` 存亿；`stock_valuation`/`stock_financial_detail` 是元，读出后 `/1e8`。
- 纯函数模块惯例：dict 进 dict 出、零 IO、不抛异常（参考 `period_transform.py` 文件头）。
- handler 内部 import 仓储（函数体内 `from ...`，模式同 `valuation_history`）；统一 `responses.success`/`responses.error` 包裹。
- 新路由独立命名 `/market-cap-growth/...`（防路径遮蔽，教训见 financial_router.py:1060 注释）。
- 图表系列色只取 `chartTheme` 常量：柱=`CHART_COLORS[0]`（蓝），线=`CHART_COLORS[2]`（橙，避开红/绿涨跌语义色）。
- 每个 Task 结束单独 commit，消息风格仿仓库近期（`feat(xxx): 中文描述`）。
- 规格偏差说明：规格里 06:30/07:00/07:30 三个调度时间在实现中合并为**一个链式 job（周六 06:30，成分→财务聚合→市值回填顺序执行）**，依赖顺序更强保证，调度面更小。
- 工作区有他人未提交改动（`backend/.news_backfill_progress.json` 等 6 个文件）——**每次 commit 只 `git add` 本任务明确列出的文件**，绝不 `git add -A`。

## 文件结构总览

```
backend/
  conf/settings.py                                  [改] +QuantUniverseIndexConstituentConfig
  conf/config.yaml                                  [改] +index_constituents 配置段
  src/infra/database/market/index_constituent.py    [新] 表+仓储
  src/domain/market/sync/jobs/index_constituent_sync.py  [新] 成分同步 job
  src/domain/market/sync/jobs/index_financial_sync.py    [改] +sync_index_financial_quarterly
  src/domain/market/sync/jobs/index_market_cap_sync.py   [新] 市值回填 job
  src/infra/database/market/index_valuation.py      [改] +bulk_upsert_index_mv
  src/infra/scheduler.py                            [改] +index_panorama_weekly job
  src/domain/market/fundamental/market_cap_growth.py [新] 口径换算纯函数
  src/api/handler/financial_detail_handler.py       [改] +两个 handler+缓存
  src/api/router/financial_router.py                [改] +两个路由
  tests/domain/market/fundamental/test_market_cap_growth.py [新]
  tests/sync/test_index_constituent_sync.py         [新]
  tests/sync/test_index_market_cap_sync.py          [新]
  tests/api/test_market_cap_growth.py               [新]
frontend/apps/web/src/
  hooks/useMarketCapGrowth.ts                       [新]
  components/MarketCapGrowthChart.tsx               [新]（取代孤儿 IndexFinancialChart.tsx 的定位）
  components/MarketCapGrowthPanel.tsx               [新]
  pages/Financial.tsx                               [改] 第14个Tab
  pages/Indices.tsx                                 [改] 新区块
  pages/Indices.css                                 [改] 新区块样式
```

孤儿组件 `components/IndexFinancialChart.tsx` 保持不动（无人引用，不在本计划清理范围）。

---

### Task 1: 口径换算纯函数 `market_cap_growth.py`

**Files:**
- Create: `backend/src/domain/market/fundamental/market_cap_growth.py`
- Test: `backend/tests/domain/market/fundamental/test_market_cap_growth.py`

**Interfaces:**
- Consumes: `src.domain.market.fundamental.period_transform.transform_to_quarter`（已存在，`transform_to_quarter(rows: list[dict]) -> list[dict]` 就地差分，revenue/net_profit 均属 FLOW_FIELDS）。
- Produces（Task 8 依赖，签名固定）:
  - `to_quarterly(rows: list[dict]) -> list[dict]`——输入输出均为 `[{report_date: date|str, revenue: float|None, net_profit: float|None}]`（输入累计口径升序；输出单季，不改调用方数据）。
  - `to_ttm(rows: list[dict]) -> list[dict]`——同形；`TTM = 上年年报 + 本期累计 − 上年同期累计`；年报期（month==12）TTM=全年本身；依赖期缺失→该期 None。
  - `align_mv(monthly_mv: list[dict], report_dates: list) -> list[dict]`——`monthly_mv=[{date: date|str, total_mv: float|None}]`，返回 `[{report_date: "YYYY-MM-DD", total_mv: float|None}]`（取 ≤report_date 的最近月度点；无→None）。

- [ ] **Step 1: Write the failing test**

```python
"""市值与业绩增长口径换算纯函数测试。"""
from datetime import date

from src.domain.market.fundamental.market_cap_growth import (
    align_mv,
    to_quarterly,
    to_ttm,
)


def _row(rd: str, revenue=None, net_profit=None) -> dict:
    return {
        "report_date": date.fromisoformat(rd),
        "revenue": revenue,
        "net_profit": net_profit,
    }


def test_to_quarterly_diff_and_year_reset():
    rows = [
        _row("2023-03-31", 10.0, 1.0),
        _row("2023-06-30", 25.0, 2.5),
        _row("2023-09-30", 40.0, 4.0),
        _row("2023-12-31", 60.0, 6.0),
        _row("2024-03-31", 14.0, 1.4),
        _row("2024-06-30", 30.0, 3.0),
    ]
    out = to_quarterly(rows)
    assert [r["revenue"] for r in out] == [10, 15, 15, 20, 14, 16]
    assert [r["net_profit"] for r in out] == [1.0, 1.5, 1.5, 2.0, 1.4, 1.6]
    # 不改调用方数据
    assert rows[1]["revenue"] == 25.0


def test_to_quarterly_empty_and_none_passthrough():
    assert to_quarterly([]) == []
    out = to_quarterly([_row("2023-03-31", None, None)])
    assert out[0]["revenue"] is None and out[0]["net_profit"] is None


def test_to_ttm_cross_year():
    rows = [
        _row("2023-03-31", 10.0, 1.0),
        _row("2023-06-30", 25.0, 2.5),
        _row("2023-09-30", 40.0, 4.0),
        _row("2023-12-31", 60.0, 6.0),
        _row("2024-03-31", 14.0, 1.4),
        _row("2024-06-30", 30.0, 3.0),
    ]
    out = to_ttm(rows)
    # 2023 各期缺 2022 年报与同期 → None；年报期 TTM=全年本身
    assert out[0]["revenue"] is None
    assert out[3]["revenue"] == 60.0
    # 2024Q1 = FY2023 + YTD2024Q1 − YTD2023Q1 = 60+14−10
    assert out[4]["revenue"] == 64.0
    # 2024H1 = 60+30−25
    assert out[5]["revenue"] == 65.0
    assert out[5]["net_profit"] == 6.0 + 3.0 - 2.5


def test_to_ttm_missing_dependency_none():
    rows = [
        _row("2023-06-30", 25.0),
        _row("2024-06-30", 30.0),   # 缺 2023 年报
    ]
    out = to_ttm(rows)
    assert out[0]["revenue"] is None   # 缺 2022 年报
    assert out[1]["revenue"] is None   # 缺 2023 年报


def test_align_mv_pick_latest_le():
    monthly = [
        {"date": "2023-01-31", "total_mv": 100.0},
        {"date": "2023-02-28", "total_mv": 110.0},
        {"date": "2023-03-31", "total_mv": 120.0},
    ]
    out = align_mv(monthly, [date(2023, 2, 15), "2023-03-31", "2022-12-31"])
    assert out == [
        {"report_date": "2023-02-15", "total_mv": 110.0},
        {"report_date": "2023-03-31", "total_mv": 120.0},
        {"report_date": "2022-12-31", "total_mv": None},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_market_cap_growth.py -v`
Expected: FAIL（`ModuleNotFoundError: ... market_cap_growth`）

- [ ] **Step 3: Write minimal implementation**

```python
"""市值与业绩增长趋势口径换算（纯函数）。

输入序列：[{report_date: date|str, revenue: float|None,
net_profit: float|None}]，**累计口径**、升序。输出同形序列。
零 IO、不抛异常（模块惯例同 period_transform）。
"""
from typing import Any

from src.domain.market.fundamental.period_transform import transform_to_quarter


def _rd_key(report_date: Any) -> tuple[int, int] | None:
    """report_date（date|str）→ (year, month)；无效返回 None。"""
    if report_date is None:
        return None
    y = getattr(report_date, "year", None)
    m = getattr(report_date, "month", None)
    if y is None:
        parts = str(report_date)[:10].split("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            y, m = int(parts[0]), int(parts[1])
        else:
            return None
    return (int(y), int(m))


def to_quarterly(rows: list[dict]) -> list[dict]:
    """累计序列 → 单季序列（委托 transform_to_quarter，含跨年重置）。

    委托后会混入 transform 派生的多余键，这里收敛回三键。
    """
    stripped = [
        {"report_date": r.get("report_date"),
         "revenue": r.get("revenue"),
         "net_profit": r.get("net_profit")}
        for r in rows
    ]
    out = transform_to_quarter(stripped)
    return [
        {"report_date": r.get("report_date"),
         "revenue": r.get("revenue"),
         "net_profit": r.get("net_profit")}
        for r in out
    ]


def to_ttm(rows: list[dict]) -> list[dict]:
    """累计序列 → TTM 序列。

    TTM_t = FY_{y-1} + YTD_t − YTD_{y-1 同期}；
    年报期（month==12）TTM = 全年值本身；
    依赖期缺失或非数值 → 该期 None（不外推）。
    """
    cum: dict[tuple[int, int], dict] = {}
    for r in rows:
        k = _rd_key(r.get("report_date"))
        if k is not None:
            cum[k] = r
    out: list[dict] = []
    for r in rows:
        k = _rd_key(r.get("report_date"))
        item = {f: r.get(f) for f in ("report_date", "revenue", "net_profit")}
        if k is None:
            item["revenue"] = None
            item["net_profit"] = None
            out.append(item)
            continue
        y, m = k
        if m == 12:
            out.append(item)          # 年报即 TTM
            continue
        fy_prev = cum.get((y - 1, 12))
        same_prev = cum.get((y - 1, m))
        for f in ("revenue", "net_profit"):
            cur = r.get(f)
            base = fy_prev.get(f) if fy_prev else None
            prev = same_prev.get(f) if same_prev else None
            if all(isinstance(v, (int, float))
                   for v in (cur, base, prev)):
                item[f] = cur + base - prev
            else:
                item[f] = None
        out.append(item)
    return out


def align_mv(
    monthly_mv: list[dict], report_dates: list,
) -> list[dict]:
    """月度市值序列对齐报告期末：取 ≤ report_date 的最近月度点。

    Args:
        monthly_mv: [{date: date|str, total_mv: float|None}]（乱序可容忍）。
        report_dates: 报告期列表（date|str）。
    Returns:
        [{report_date: "YYYY-MM-DD", total_mv: float|None}]，
        早于首个月度点或无可用点 → total_mv None。
    """

    def _as_str(d: Any):
        if d is None:
            return None
        return d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]

    pts = sorted(
        [(_as_str(p.get("date")), p.get("total_mv"))
         for p in monthly_mv if _as_str(p.get("date"))],
        key=lambda t: t[0],
    )
    out = []
    for rd in report_dates:
        rd_str = _as_str(rd)
        mv = None
        if rd_str:
            for d_str, v in pts:
                if d_str <= rd_str:
                    mv = v
                else:
                    break
        out.append({"report_date": rd_str, "total_mv": mv})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_market_cap_growth.py -v`
Expected: 6 passed

- [ ] **Step 5: 既有 period_transform 测试不回归**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_period_transform.py -v`
Expected: all passed（未改动该模块）

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/domain/market/fundamental/market_cap_growth.py \
        backend/tests/domain/market/fundamental/test_market_cap_growth.py
git commit -m "feat(mcg): 口径换算纯函数——累计→单季(委托period_transform)/TTM/市值报告期对齐"
```

---

### Task 2: 配置段 `quant_universe.index_constituents`

**Files:**
- Modify: `backend/conf/settings.py`（约 147-163 行，QuantUniverse 配置区）
- Modify: `backend/conf/config.yaml`（约 160-175 行，indices 列表之后）

**Interfaces:**
- Produces（Task 4/5/6/8 依赖）: `app_config.quant_universe.index_constituents` —— `list[QuantUniverseIndexConstituentConfig]`，各项有 `.code`（"000300"）/`.symbol`（"sh000300"）/`.name`（"沪深300"）属性。

- [ ] **Step 1: settings.py 加配置模型**

在 `QuantUniverseIndexConfig` 类（约 147-150 行）之后、`QuantUniverseConfig` 类之前插入：

```python
class QuantUniverseIndexConstituentConfig(BaseModel):
    """宽基指数成分股清单项（akshare index_stock_cons_weight_csindex）"""
    code: str        # 纯6位指数代码（000300），csindex 参数与聚合表 scope_code
    symbol: str      # 带前缀代码（sh000300），对齐 indices 清单
    name: str = ""
```

在 `QuantUniverseConfig` 字段 `sw_industries` 行（约 163 行）之后加一行字段：

```python
    index_constituents: list[QuantUniverseIndexConstituentConfig] = []  # 宽基成分股（csindex）
```

- [ ] **Step 2: config.yaml 加清单**

在 `conf/config.yaml` 的 `indices:` 列表结束（`sh000903 中证100` 行）与 `# 申万一级行业指数` 注释行之间插入：

```yaml
  # 宽基指数成分股（走 akshare index_stock_cons_weight_csindex，中证官网）
  index_constituents:
    - { code: "000300", symbol: "sh000300", name: "沪深300" }
    - { code: "000016", symbol: "sh000016", name: "上证50" }
    - { code: "000905", symbol: "sh000905", name: "中证500" }
    - { code: "000852", symbol: "sh000852", name: "中证1000" }
    - { code: "932000", symbol: "sh932000", name: "中证2000" }
    - { code: "000903", symbol: "sh000903", name: "中证100" }
    - { code: "000010", symbol: "sh000010", name: "上证180" }
    - { code: "000985", symbol: "sh000985", name: "中证全指" }
    - { code: "000688", symbol: "sh000688", name: "科创50" }
```

注意：同目录 `config.local.yaml`（gitignore）若存在同名段会 deep-merge 覆盖，不需要动它。

- [ ] **Step 3: 验证配置可读**

Run: `cd backend && uv run python -c "from conf import app_config; items=app_config.quant_universe.index_constituents; print(len(items), [i.code for i in items])"`
Expected: `9 ['000300', '000016', '000905', '000852', '932000', '000903', '000010', '000985', '000688']`

- [ ] **Step 4: Commit**

```bash
git add backend/conf/settings.py backend/conf/config.yaml
git commit -m "feat(mcg): quant_universe.index_constituents 配置段——中证系9宽基成分清单"
```

---

### Task 3: `index_constituent` 表 + 仓储

**Files:**
- Create: `backend/src/infra/database/market/index_constituent.py`

**Interfaces:**
- Produces（Task 4/5/6 依赖）:
  - `IndexConstituent`（SQLModel 表 `index_constituent`，PK=(index_code, stock_symbol)）。
  - `IndexConstituentRepository.replace_members(index_code: str, rows: list[dict]) -> int`——rows 每项含 `_MEMBER_COLUMNS` 五键：`index_code/stock_symbol/stock_name/weight/as_of_date`，单事务 DELETE 该指数+INSERT，返回写入数。
  - `IndexConstituentRepository.get_members(index_code: str) -> list[str]`——成分股 symbol（sh600519…）列表。
  - 工厂 `create_index_constituent_repository(db_connection=None)`（模块级单例连接）。
- 模式参照：`src/infra/database/market/sw_industry.py` 的 `replace_all_members`（94-112 行）与工厂（222-247 行）。建表走 `SQLModel.metadata.create_all` 惰性，无 Alembic。

- [ ] **Step 1: 写整文件**

```python
"""宽基指数成分股快照表。

index_constituent: 中证系宽基指数（沪深300/中证500/…）最新成分快照，
  job 全量重灌（事务内 DELETE + INSERT，幂等）。
  历史成分不做回溯（csindex 只有最新快照）——下游聚合以当前成分近似
  历史口径（幸存者偏差，数据行 source='computed' 标注）。

下游：指数财务聚合（index_financial_quarterly scope='index'）、
      指数市值回填（index_valuation_daily.total_mv）。
表由 SQLModel.metadata.create_all 惰性建表（同 sw_industry_member 惯例）。
"""
import datetime as dt
import threading
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import Column, DateTime, func
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class IndexConstituent(SQLModel, table=True):
    """宽基指数成分股快照（PK(index_code, stock_symbol)）。"""
    __tablename__ = "index_constituent"

    index_code: str = Field(primary_key=True)    # 000300
    stock_symbol: str = Field(primary_key=True)  # sh600519
    stock_name: Optional[str] = None
    weight: Optional[float] = None               # 权重%
    as_of_date: Optional[dt.date] = None         # 成分快照日
    synced_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now()),
    )


_MEMBER_COLUMNS = (
    "index_code", "stock_symbol", "stock_name", "weight", "as_of_date",
)


class IndexConstituentRepository:
    """指数成分股数据访问（SQLModel 读 + psycopg2 批量写）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def replace_members(self, index_code: str, rows: list[dict]) -> int:
        """单指数全量重灌（单事务 DELETE + INSERT，幂等）。"""
        if not rows:
            return 0
        values = [tuple(r.get(c) for c in _MEMBER_COLUMNS) for r in rows]
        dele = "DELETE FROM index_constituent WHERE index_code = %s"
        ins = """
            INSERT INTO index_constituent ({cols})
            VALUES %s
        """.format(cols=", ".join(_MEMBER_COLUMNS))
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(dele, (index_code,))
                execute_values(cur, ins, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def get_members(self, index_code: str) -> list[str]:
        """成分股 symbol 列表（sh600519…）。"""
        with self._db.session_scope() as s:
            rows = list(s.exec(
                select(IndexConstituent.stock_symbol).where(
                    IndexConstituent.index_code == index_code
                )
            ).all())
            return [r for r in rows if r]


# ======== 工厂函数（模式同 index_financial.py）========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_index_constituent_repository(
    db_connection: DBConnection | None = None,
) -> IndexConstituentRepository:
    """创建指数成分股仓储实例（首次调用触发惰性建表）。"""
    return IndexConstituentRepository(db_connection or _get_db_connection())
```

- [ ] **Step 2: 导入冒烟（不触库）**

Run: `cd backend && uv run python -c "from src.infra.database.market.index_constituent import create_index_constituent_repository, IndexConstituent; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/database/market/index_constituent.py
git commit -m "feat(mcg): index_constituent 成分快照表+仓储——单指数全量重灌/成分查询"
```

---

### Task 4: 成分同步 job（csindex → index_constituent）

**Files:**
- Create: `backend/src/domain/market/sync/jobs/index_constituent_sync.py`
- Test: `backend/tests/sync/test_index_constituent_sync.py`

**Interfaces:**
- Consumes: Task 2 `app_config.quant_universe.index_constituents`（`.code`）；Task 3 `create_index_constituent_repository().replace_members(index_code, rows)`。
- Produces（Task 7 调度依赖）: `run(interval: float = 0.5) -> dict[str, int]`（`{index_code: wrote_count}`，单指数失败记 0 继续）。
- akshare 接口返回列（已实测 akshare 1.18.50）：`日期/指数代码/指数名称/成分券代码/成分券名称/交易所/权重`，权重为百分数（如 0.433）。

- [ ] **Step 1: Write the failing test**

```python
"""指数成分同步 job 纯转换测试。"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pandas as pd

from src.domain.market.sync.jobs.index_constituent_sync import _build_rows


def _df():
    return pd.DataFrame({
        "日期": ["2026-07-31", "2026-07-31"],
        "指数代码": ["000300", "000300"],
        "成分券代码": ["600519", "000001"],
        "成分券名称": ["贵州茅台", "平安银行"],
        "权重": [2.5, 0.433],
    })


def test_build_rows_prefix_and_fields():
    rows = _build_rows("000300", _df())
    assert rows[0] == {
        "index_code": "000300",
        "stock_symbol": "sh600519",
        "stock_name": "贵州茅台",
        "weight": 2.5,
        "as_of_date": date(2026, 7, 31),
    }
    assert rows[1]["stock_symbol"] == "sz000001"
    assert rows[1]["weight"] == 0.433


def test_build_rows_missing_weight_none():
    df = _df()
    df.loc[0, "权重"] = None
    rows = _build_rows("000905", df)
    assert rows[0]["weight"] is None
    assert rows[0]["index_code"] == "000905"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/sync/test_index_constituent_sync.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: Write minimal implementation**

```python
"""宽基指数成分股同步 job：csindex 最新成分 → index_constituent 全量重灌。

数据源 akshare index_stock_cons_weight_csindex（中证指数官网，含权重，
只有最新快照——历史成分近似由下游 source='computed' 标注）。
指数清单来自 conf quant_universe.index_constituents。
单指数失败跳过（warning），不阻塞其他指数。
"""
import logging
import time
import datetime as dt

import akshare as ak
import pandas as pd

from src.infra.database.market.index_constituent import (
    create_index_constituent_repository,
)

log = logging.getLogger(__name__)


def _to_prefixed(code: str) -> str:
    """纯 6 位代码 → sh/sz/bj 前缀（与 index_valuation_backfill 同款）。"""
    c = code.strip()
    if c.startswith(("sh", "sz", "bj")):
        return c
    if c.startswith("6"):
        return f"sh{c}"
    if c.startswith(("0", "3")):
        return f"sz{c}"
    if c.startswith(("8", "4")):
        return f"bj{c}"
    return c


def _build_rows(index_code: str, df: pd.DataFrame) -> list[dict]:
    """csindex 成分 DataFrame → member 行（纯转换，权重缺失容忍 None）。"""
    rows: list[dict] = []
    as_of = None
    if not df.empty and "日期" in df.columns:
        v = df.iloc[0]["日期"]
        s = v.isoformat() if hasattr(v, "isoformat") else str(v)
        try:
            as_of = dt.date.fromisoformat(s[:10])
        except ValueError:
            as_of = None
    for _, r in df.iterrows():
        w = r.get("权重")
        rows.append({
            "index_code": index_code,
            "stock_symbol": _to_prefixed(str(r["成分券代码"])),
            "stock_name": r.get("成分券名称"),
            "weight": float(w) if pd.notna(w) else None,
            "as_of_date": as_of,
        })
    return rows


def run(interval: float = 0.5) -> dict[str, int]:
    """同步全部配置指数的成分。Returns {index_code: wrote_count}。"""
    from conf import app_config
    items = app_config.quant_universe.index_constituents
    repo = create_index_constituent_repository()
    results: dict[str, int] = {}
    for it in items:
        try:
            df = ak.index_stock_cons_weight_csindex(symbol=it.code)
            rows = _build_rows(it.code, df)
            wrote = repo.replace_members(it.code, rows)
            results[it.code] = wrote
            log.info("[idx_cons] %s: %d members", it.code, wrote)
        except Exception as e:  # noqa: BLE001
            log.warning("[idx_cons] %s failed: %s", it.code, e)
            results[it.code] = 0
        finally:
            time.sleep(interval)
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/sync/test_index_constituent_sync.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/sync/jobs/index_constituent_sync.py \
        backend/tests/sync/test_index_constituent_sync.py
git commit -m "feat(mcg): csindex成分同步job——9宽基全量重灌index_constituent"
```

---

### Task 5: 指数财务聚合 job（index_financial_quarterly scope='index'）

**Files:**
- Modify: `backend/src/domain/market/sync/jobs/index_financial_sync.py`（文件尾部追加两个函数）

**Interfaces:**
- Consumes: Task 2 配置清单；Task 3 `index_constituent` 表（SQL JOIN）；既有 `create_index_financial_repository().bulk_upsert(rows)`（rows 键：`scope_type/scope_code/report_date/revenue_sum/net_profit_sum/sample_count`，单位亿）。
- Produces（Task 7 调度依赖）: `sync_index_financial_quarterly() -> dict[str, int]`（`{index_code: wrote_count}`）。
- 说明：SQL 直查无单测（仓库先例——`_aggregate_sw_sector_financial` 同样无单测），验证在 Task 14 冒烟。

- [ ] **Step 1: 在 index_financial_sync.py 文件末尾追加**

```python
def _aggregate_index_financial(index_code: str) -> list[dict]:
    """聚合单个宽基指数成分股的季度财务（**累计口径**，亿）。

    用固定列 revenue/net_profit_parent（sw 聚合走 detail JSONB 是历史
    口径；指数侧统一用固定列，net_profit 取归母口径）。
    """
    conn = psycopg2.connect(get_dsn())
    out: list[dict] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.report_date,
                       SUM(COALESCE(f.revenue, 0)) AS rev,
                       SUM(COALESCE(f.net_profit_parent, 0)) AS np,
                       COUNT(f.revenue) AS cnt
                FROM stock_financial_detail f
                JOIN index_constituent c ON c.stock_symbol = f.symbol
                WHERE c.index_code = %s
                  AND f.statement_type = 'income'
                GROUP BY f.report_date
                ORDER BY f.report_date
                """,
                (index_code,),
            )
            for rd, rev, np_, cnt in cur.fetchall():
                out.append({
                    "scope_type": "index",
                    "scope_code": index_code,
                    "report_date": rd,
                    "revenue_sum": float(rev or 0) / 1e8,
                    "net_profit_sum": float(np_ or 0) / 1e8,
                    "sample_count": cnt,
                })
    finally:
        conn.close()
    return out


def sync_index_financial_quarterly() -> dict[str, int]:
    """同步全部配置宽基指数的季度财务聚合（全量重算幂等）。

    Returns: {index_code: wrote_count}
    """
    from conf import app_config
    items = app_config.quant_universe.index_constituents
    repo = create_index_financial_repository()
    results: dict[str, int] = {}
    for it in items:
        try:
            rows = _aggregate_index_financial(it.code)
            if rows:
                repo.bulk_upsert(rows)
            results[it.code] = len(rows)
            log.info("[sync_idx_fin] %s: %d periods", it.code, len(rows))
        except Exception as e:  # noqa: BLE001
            log.warning("[sync_idx_fin] %s failed: %s", it.code, e)
            results[it.code] = 0
    return results
```

- [ ] **Step 2: 导入冒烟**

Run: `cd backend && uv run python -c "from src.domain.market.sync.jobs.index_financial_sync import sync_index_financial_quarterly; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/src/domain/market/sync/jobs/index_financial_sync.py
git commit -m "feat(mcg): 宽基指数财务聚合job——成分股JOIN三大表按报告期SUM(累计口径,亿)"
```

---

### Task 6: 指数市值月度回填 job + 仓储方法

**Files:**
- Modify: `backend/src/infra/database/market/index_valuation.py`（`IndexValuationRepository` 类内、`bulk_upsert_index` 方法后加一个方法）
- Create: `backend/src/domain/market/sync/jobs/index_market_cap_sync.py`
- Test: `backend/tests/sync/test_index_market_cap_sync.py`

**Interfaces:**
- Consumes: Task 3 `get_members(index_code)`；既有 `StockValuationRepository.get_range_batch(symbols, start, end, exclude_ranges=None, monthly=True) -> dict[str, list[StockValuation]]`（SQL 月度降采样，valuation.py:145）。
- Produces:
  - `IndexValuationRepository.bulk_upsert_index_mv(rows: list[dict]) -> int`——rows 键 `symbol/trade_date/total_mv/source`；ON CONFLICT 只更新 total_mv/source（不覆盖 pe/pb 等列）。
  - `sync_index_market_cap(years: int = 10) -> dict[str, int]`（Task 7 依赖）。
  - 纯函数 `_monthly_mv_sum(rows_by_symbol: dict) -> list[dict]`——`[{date, total_mv}]` 升序，元。

- [ ] **Step 1: Write the failing test**

```python
"""指数市值回填 job 纯函数测试。"""
import datetime as dt
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.sync.jobs.index_market_cap_sync import _monthly_mv_sum


def test_monthly_mv_sum_accumulates_and_sorts():
    rows = {
        "sh600519": [
            SimpleNamespace(trade_date=dt.date(2024, 1, 31), total_mv=2.0e12),
            SimpleNamespace(trade_date=dt.date(2024, 2, 29), total_mv=2.1e12),
        ],
        "sz000001": [
            SimpleNamespace(trade_date=dt.date(2024, 1, 31), total_mv=3.0e11),
            SimpleNamespace(trade_date=dt.date(2024, 2, 29), total_mv=None),
        ],
    }
    out = _monthly_mv_sum(rows)
    assert [p["date"] for p in out] == [
        dt.date(2024, 1, 31), dt.date(2024, 2, 29),
    ]
    assert out[0]["total_mv"] == 2.3e12
    assert out[1]["total_mv"] == 2.1e12   # None 跳过
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/sync/test_index_market_cap_sync.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 加仓储方法 `bulk_upsert_index_mv`**

在 `index_valuation.py` 的 `IndexValuationRepository` 类中、`bulk_upsert_index` 方法（152 行起）之后插入：

```python
    def bulk_upsert_index_mv(self, rows: list[dict]) -> int:
        """只写 total_mv 的批量 upsert（不覆盖 pe/pb 等其他列）。"""
        if not rows:
            return 0
        values = []
        for r in rows:
            td = r.get("trade_date")
            if hasattr(td, "date"):
                td = td.date()
            values.append((r["symbol"], td, r.get("total_mv"),
                           r.get("source", "computed")))
        sql = """
            INSERT INTO index_valuation_daily
                (symbol, trade_date, total_mv, source)
            VALUES %s
            ON CONFLICT (trade_date, symbol) DO UPDATE SET
                total_mv=EXCLUDED.total_mv, source=EXCLUDED.source
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

- [ ] **Step 4: 写 job 文件**

```python
"""宽基指数市值回填 job：成分股 stock_valuation 月末加总 → index_valuation_daily。

口径：用当前成分近似历史成分（csindex 无历史成分，幸存者偏差，
source='computed'）；月末采样（与 index_valuation_backfill 一致）。
全量重算近 N 年月度序列（幂等 upsert）。
"""
import logging
import datetime as dt

from src.infra.database.market.index_constituent import (
    create_index_constituent_repository,
)
from src.infra.database.market.index_valuation import (
    create_index_valuation_repository,
)
from src.infra.database.market.valuation import (
    create_stock_valuation_repository,
)

log = logging.getLogger(__name__)


def _monthly_mv_sum(rows_by_symbol: dict) -> list[dict]:
    """{symbol: [StockValuation…]} → 按月末日期加总 total_mv（纯函数，元）。

    Returns: [{date: date, total_mv: float}]，升序；total_mv None 跳过。
    """
    acc: dict = {}
    for rows in rows_by_symbol.values():
        for r in rows:
            d, mv = r.trade_date, r.total_mv
            if d is None or mv is None:
                continue
            acc[d] = acc.get(d, 0.0) + float(mv)
    return [{"date": d, "total_mv": acc[d]} for d in sorted(acc.keys())]


def sync_index_market_cap(years: int = 10) -> dict[str, int]:
    """回填全部配置宽基指数的月度总市值序列（亿）。

    Returns: {index_code: wrote_count}
    """
    from conf import app_config
    items = app_config.quant_universe.index_constituents
    cons_repo = create_index_constituent_repository()
    val_repo = create_stock_valuation_repository()
    idx_repo = create_index_valuation_repository()

    end = dt.date.today()
    start = dt.date(end.year - years, end.month, end.day)

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
            monthly = _monthly_mv_sum(rows_by_symbol)
            bulk = [
                {"symbol": it.code, "trade_date": p["date"],
                 "total_mv": round(p["total_mv"] / 1e8, 4),
                 "source": "computed"}
                for p in monthly
            ]
            if bulk:
                idx_repo.bulk_upsert_index_mv(bulk)
            results[it.code] = len(bulk)
            log.info("[idx_mv] %s: %d monthly points", it.code, len(bulk))
        except Exception as e:  # noqa: BLE001
            log.warning("[idx_mv] %s failed: %s", it.code, e)
            results[it.code] = 0
    return results
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/sync/test_index_market_cap_sync.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/infra/database/market/index_valuation.py \
        backend/src/domain/market/sync/jobs/index_market_cap_sync.py \
        backend/tests/sync/test_index_market_cap_sync.py
git commit -m "feat(mcg): 宽基指数月度市值回填——成分股total_mv月末加总,只更新mv列的upsert"
```

---

### Task 7: 调度注册 `index_panorama_weekly`

**Files:**
- Modify: `backend/src/infra/scheduler.py`（`sw_industry_weekly` 的 `sched.add_job(...)` 之后、`# ── 业绩预告/快报增量` 注释之前，约 777-779 行之间插入）

**Interfaces:**
- Consumes: Task 4 `index_constituent_sync.run()`、Task 5 `sync_index_financial_quarterly()`、Task 6 `sync_index_market_cap()`。
- Produces: scheduler job id `index_panorama_weekly`（周六 06:30 Asia/Shanghai，链式 成分→财务→市值）。

- [ ] **Step 1: 插入调度代码**

```python
    # ── 宽基指数成分/财务聚合/市值回填（每周六 06:30，先成分后下游）──────
    # 06:30 的原因：financial_full_weekly（05:00，三大表）与
    # fundamentals_weekly（03:00，估值）之后；单 job 链式执行保证
    # 成分 → 财务聚合 → 市值回填 的先后依赖（等价于规格的
    # 06:30/07:00/07:30 三连发，依赖顺序更强保证）。
    def _run_index_panorama_weekly():
        from src.domain.market.sync.jobs import (
            index_constituent_sync,
            index_financial_sync,
            index_market_cap_sync,
        )
        try:
            r1 = index_constituent_sync.run()
            log.info("[INDEX_PANORAMA_WEEKLY] constituents=%s", r1)
        except Exception as e:  # noqa: BLE001
            log.error("[INDEX_PANORAMA_WEEKLY] constituent sync failed: %s", e)
            return  # 成分失败，下游跳过
        try:
            r2 = index_financial_sync.sync_index_financial_quarterly()
            log.info("[INDEX_PANORAMA_WEEKLY] financial=%s", r2)
        except Exception as e:  # noqa: BLE001
            log.error("[INDEX_PANORAMA_WEEKLY] financial agg failed: %s", e)
        try:
            r3 = index_market_cap_sync.sync_index_market_cap()
            log.info("[INDEX_PANORAMA_WEEKLY] mv=%s", r3)
        except Exception as e:  # noqa: BLE001
            log.error("[INDEX_PANORAMA_WEEKLY] mv backfill failed: %s", e)

    sched.add_job(
        _run_index_panorama_weekly,
        CronTrigger(day_of_week="sat", hour=6, minute=30,
                    timezone="Asia/Shanghai"),
        id="index_panorama_weekly",
        name="宽基指数成分/财务聚合/市值回填",
        replace_existing=True,
        misfire_grace_time=14400,
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 2: 导入冒烟**

Run: `cd backend && uv run python -c "import src.infra.scheduler; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/scheduler.py
git commit -m "feat(mcg): index_panorama_weekly调度——周六06:30成分→财务聚合→市值回填链"
```

---

### Task 8: Handler 两函数 + 1h 缓存

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（文件末尾追加一节）
- Test: `backend/tests/api/test_market_cap_growth.py`

**Interfaces:**
- Consumes: Task 1 纯函数三件套；Task 2 配置名映射；既有仓储 `create_index_financial_repository().get_series(scope_type, scope_code, start=)`（返回对象含 `.report_date/.revenue_sum/.net_profit_sum/.sample_count`）、`create_index_valuation_repository().get_index_range(symbol, start, end)`（`.trade_date/.total_mv`）、`create_financial_detail_repository().get_history(symbol, statement_type, start, end)`（`.report_date/.revenue/.net_profit_parent`）、`create_stock_valuation_repository().get_as_of(symbol, date)`（`.total_mv` 元）。
- Produces（Task 9 路由 & 前端 Task 10 依赖，响应形状固定）:
  - `market_cap_growth_index(code: str, years: int = 10)` → `success({kind:"index", code, name, as_of, bars:{quarter|cumulative|ttm: [{report_date, revenue, net_profit}]}, mv_series:[{report_date, total_mv}], sample_count:[{report_date, count}]})`；未配置指数 → `responses.error`。
  - `market_cap_growth_stock(symbol: str, years: int = 10)` → 同形（无 sample_count；非 sh/sz/bj 前缀 → 空 bars + note，code 仍为 0）。
  - 模块级 `_mcg_cache`（dict）——测试用例间需手动清空。

- [ ] **Step 1: Write the failing test**

```python
"""market-cap-growth 端点测试（mock 仓储，模式抄 test_five_forces.py）。"""
import json
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


def _fin_row(rd, rev, np_, cnt):
    return SimpleNamespace(report_date=date.fromisoformat(rd),
                           revenue_sum=rev, net_profit_sum=np_,
                           sample_count=cnt)


def _val_row(td, mv):
    return SimpleNamespace(trade_date=date.fromisoformat(td), total_mv=mv)


class _FinRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_series(self, scope_type, scope_code, start=None, end=None):
        assert scope_type == "index"
        return self._rows


class _IdxValRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_index_range(self, symbol, start, end):
        return self._rows


FIN_ROWS = [
    _fin_row("2023-03-31", 10.0, 1.0, 300),
    _fin_row("2023-12-31", 60.0, 6.0, 300),
    _fin_row("2024-03-31", 14.0, 1.4, 300),
]
VAL_ROWS = [
    _val_row("2023-03-31", 5.0e5),
    _val_row("2024-03-31", 5.5e5),
]


def _call_index(code="000300"):
    from src.api.handler.financial_detail_handler import (
        market_cap_growth_index,
    )
    _clear_cache()
    with patch(
        "src.infra.database.market.index_financial."
        "create_index_financial_repository",
        return_value=_FinRepo(FIN_ROWS),
    ), patch(
        "src.infra.database.market.index_valuation."
        "create_index_valuation_repository",
        return_value=_IdxValRepo(VAL_ROWS),
    ):
        return json.loads(market_cap_growth_index(code).body)


def test_index_shape_and_ttm():
    body = _call_index()
    assert body["code"] == 0
    d = body["data"]
    assert d["kind"] == "index" and d["code"] == "000300"
    assert d["name"]                      # 配置名（沪深300）
    assert set(d["bars"]) == {"quarter", "cumulative", "ttm"}
    # 2024Q1 TTM = FY2023 + YTD2024Q1 − YTD2023Q1 = 60+14−10
    ttm = {b["report_date"]: b for b in d["bars"]["ttm"]}
    assert ttm["2024-03-31"]["revenue"] == 64.0
    # 2023 年报单季 = 60 − 10
    q = {b["report_date"]: b for b in d["bars"]["quarter"]}
    assert q["2023-12-31"]["revenue"] == 50.0
    # mv 对齐：2023-03-31 → 5e5；2023-12-31 → 取 ≤ 的最近点 2023-03-31
    mv = {p["report_date"]: p["total_mv"] for p in d["mv_series"]}
    assert mv["2023-03-31"] == 500000.0
    assert mv["2023-12-31"] == 500000.0
    assert d["sample_count"][0]["count"] == 300


def test_index_unknown_code_error():
    body = _call_index(code="999999")
    assert body["code"] != 0


class _SDetailRepo:
    def get_history(self, symbol, statement_type, start=None, end=None):
        assert statement_type == "income"
        return [
            SimpleNamespace(report_date=date.fromisoformat("2023-03-31"),
                            revenue=3.0e10, net_profit_parent=3.0e9),
            SimpleNamespace(report_date=date.fromisoformat("2023-12-31"),
                            revenue=1.2e11, net_profit_parent=1.2e10),
            SimpleNamespace(report_date=date.fromisoformat("2024-03-31"),
                            revenue=4.0e10, net_profit_parent=4.0e9),
        ]


class _SValRepo:
    def get_as_of(self, symbol, d):
        return SimpleNamespace(trade_date=d, total_mv=2.0e12)


def _call_stock(symbol="sh600519"):
    from src.api.handler.financial_detail_handler import (
        market_cap_growth_stock,
    )
    _clear_cache()
    with patch(
        "src.infra.database.market.financial_full."
        "create_financial_detail_repository",
        return_value=_SDetailRepo(),
    ), patch(
        "src.infra.database.market.valuation."
        "create_stock_valuation_repository",
        return_value=_SValRepo(),
    ):
        return json.loads(market_cap_growth_stock(symbol).body)


def test_stock_units_yi_and_shape():
    body = _call_stock()
    assert body["code"] == 0
    d = body["data"]
    assert d["kind"] == "stock"
    cum = {b["report_date"]: b for b in d["bars"]["cumulative"]}
    assert cum["2023-03-31"]["revenue"] == 300.0   # 3e10 元 → 300 亿
    ttm = {b["report_date"]: b for b in d["bars"]["ttm"]}
    assert ttm["2024-03-31"]["revenue"] == 400.0 + 1200.0 - 300.0
    assert d["mv_series"][0]["total_mv"] == 200.0  # 2e12 元 → 200 亿
    assert "sample_count" not in d


def test_stock_non_a_empty_with_note():
    body = _call_stock(symbol="hk00700")
    assert body["code"] == 0
    assert body["data"]["bars"]["quarter"] == []
    assert body["data"]["note"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_market_cap_growth.py -v`
Expected: FAIL（`cannot import name 'market_cap_growth_index'`）

- [ ] **Step 3: 在 financial_detail_handler.py 文件末尾追加**

```python
# ════════════════════════════════════════════════════════════════════════════
#  市值与业绩增长趋势（指数/个股）：营收/归母净利三口径 + 报告期末总市值
#  指数源 index_financial_quarterly + index_valuation_daily；
#  个股源 stock_financial_detail + stock_valuation。单位统一亿元。
# ════════════════════════════════════════════════════════════════════════════

_mcg_cache: dict = {"data": {}, "ts": {}}
_MCG_CACHE_TTL = 3600  # 秒（成分/财务周更，1h 缓存无害）


def _mcg_round(v) -> Optional[float]:
    return round(v, 2) if isinstance(v, (int, float)) else None


def _mcg_index_names() -> dict:
    """配置段宽基指数 code → name。"""
    from conf import app_config
    return {
        it.code: it.name
        for it in app_config.quant_universe.index_constituents
    }


def _mcg_fmt_rows(rows: list) -> list:
    out = []
    for r in rows:
        rd = r.get("report_date")
        rd = rd.isoformat() if hasattr(rd, "isoformat") else str(rd)[:10]
        out.append({
            "report_date": rd,
            "revenue": _mcg_round(r.get("revenue")),
            "net_profit": _mcg_round(r.get("net_profit")),
        })
    return out


def _mcg_bars(cum: list) -> dict:
    """累计序列（revenue/net_profit，亿）→ 三口径 bars。"""
    from src.domain.market.fundamental.market_cap_growth import (
        to_quarterly,
        to_ttm,
    )
    return {
        "quarter": _mcg_fmt_rows(to_quarterly(cum)),
        "cumulative": _mcg_fmt_rows(cum),
        "ttm": _mcg_fmt_rows(to_ttm(cum)),
    }


def _mcg_cached(key: str, compute):
    """1h 结果缓存（仿 _valpct_cache）。"""
    now = time.time()
    if (key in _mcg_cache["data"]
            and now - _mcg_cache["ts"].get(key, 0) < _MCG_CACHE_TTL):
        return _mcg_cache["data"][key]
    result = compute()
    _mcg_cache["data"][key] = result
    _mcg_cache["ts"][key] = now
    return result


def market_cap_growth_index(code: str, years: int = 10) -> Any:
    """指数市值与业绩增长趋势（营收/归母净利 单季/累计/TTM + 总市值）。"""
    names = _mcg_index_names()
    if code not in names:
        return responses.error(
            f"未配置的指数: {code}（见 quant_universe.index_constituents）"
        )

    def _compute() -> Any:
        from src.domain.market.fundamental.market_cap_growth import align_mv
        from src.infra.database.market.index_financial import (
            create_index_financial_repository,
        )
        from src.infra.database.market.index_valuation import (
            create_index_valuation_repository,
        )
        end = date.today()
        start = date(end.year - years, end.month, end.day)
        fin_rows = create_index_financial_repository().get_series(
            "index", code, start=start,
        )
        cum = [{
            "report_date": r.report_date,
            "revenue": r.revenue_sum,
            "net_profit": r.net_profit_sum,
        } for r in fin_rows]
        mv_rows = create_index_valuation_repository().get_index_range(
            code, start, end,
        )
        monthly = [
            {"date": r.trade_date, "total_mv": r.total_mv} for r in mv_rows
        ]
        return responses.success({
            "kind": "index",
            "code": code,
            "name": names.get(code),
            "as_of": end.isoformat(),
            "bars": _mcg_bars(cum),
            "mv_series": align_mv(monthly, [r["report_date"] for r in cum]),
            "sample_count": [
                {"report_date": r.report_date.isoformat(),
                 "count": r.sample_count} for r in fin_rows
            ],
        })

    return _mcg_cached(f"index:{code}:{years}", _compute)


def market_cap_growth_stock(symbol: str, years: int = 10) -> Any:
    """个股市值与业绩增长趋势（口径同指数版，单位统一亿元）。"""
    if not symbol.startswith(("sh", "sz", "bj")):
        return responses.success({
            "kind": "stock", "code": symbol, "name": None, "as_of": None,
            "bars": {"quarter": [], "cumulative": [], "ttm": []},
            "mv_series": [],
            "note": "仅支持A股个股（stock_valuation 只有A股市值）",
        })

    def _compute() -> Any:
        from src.infra.database.market.financial_full import (
            create_financial_detail_repository,
        )
        from src.infra.database.market.valuation import (
            create_stock_valuation_repository,
        )
        end = date.today()
        start = date(end.year - years, end.month, end.day)
        fin_rows = create_financial_detail_repository().get_history(
            symbol, "income", start, None,
        )
        cum = [{
            "report_date": r.report_date,
            "revenue": r.revenue / 1e8 if r.revenue is not None else None,
            "net_profit": (r.net_profit_parent / 1e8
                           if r.net_profit_parent is not None else None),
        } for r in fin_rows]
        val_repo = create_stock_valuation_repository()
        mv_series = []
        for r in fin_rows:
            row = None
            try:
                row = val_repo.get_as_of(symbol, r.report_date)
            except Exception as e:
                logger.warning(
                    "mcg mv query failed %s@%s: %s",
                    symbol, r.report_date, e,
                )
            mv_series.append({
                "report_date": r.report_date.isoformat(),
                "total_mv": _mcg_round(row.total_mv / 1e8)
                if row and row.total_mv is not None else None,
            })
        return responses.success({
            "kind": "stock",
            "code": symbol,
            "name": None,
            "as_of": end.isoformat(),
            "bars": _mcg_bars(cum),
            "mv_series": mv_series,
        })

    return _mcg_cached(f"stock:{symbol}:{years}", _compute)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_market_cap_growth.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/handler/financial_detail_handler.py \
        backend/tests/api/test_market_cap_growth.py
git commit -m "feat(mcg): 指数/个股市值与业绩增长handler——三口径bars+报告期末市值对齐+1h缓存"
```

---

### Task 9: 路由注册 + 路由回归测试

**Files:**
- Modify: `backend/src/api/router/financial_router.py`（导入块 724 行起 + index-financial-agg 端点 846 行之后）
- Test: `backend/tests/api/test_market_cap_growth.py`（追加）

**Interfaces:**
- Consumes: Task 8 两个 handler。
- Produces（前端 Task 10 依赖）:
  - `GET /api/v1/financial/market-cap-growth/index/{code}?years=10`
  - `GET /api/v1/financial/market-cap-growth/stock/{symbol}?years=10`

- [ ] **Step 1: 追加路由测试（先失败）**

在 `tests/api/test_market_cap_growth.py` 末尾追加：

```python
def test_routes_registered():
    from src.api.router.financial_router import router
    paths = {r.path for r in router.routes}
    assert "/financial/market-cap-growth/index/{code}" in paths
    assert "/financial/market-cap-growth/stock/{symbol}" in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_market_cap_growth.py::test_routes_registered -v`
Expected: FAIL（两个断言路径不存在）

- [ ] **Step 3: 注册路由**

3a. 导入块（`five_forces_report,` 之后）追加两项：

```python
    market_cap_growth_index,
    market_cap_growth_stock,
```

3b. 在 `_index_financial_agg` 端点函数（846 行 `return index_financial_agg(scope, code)`）之后插入：

```python
@router.get("/market-cap-growth/index/{code}")
def _market_cap_growth_index(
    code: str,
    years: int = Query(10, ge=1, le=30, description="回溯年数"),
):
    """指数市值与业绩增长趋势（营收/归母净利三口径 + 总市值折线）。"""
    return market_cap_growth_index(code, years)


@router.get("/market-cap-growth/stock/{symbol}")
def _market_cap_growth_stock(
    symbol: str,
    years: int = Query(10, ge=1, le=30, description="回溯年数"),
):
    """个股市值与业绩增长趋势（营收/归母净利三口径 + 总市值折线）。"""
    return market_cap_growth_stock(symbol, years)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_market_cap_growth.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/router/financial_router.py \
        backend/tests/api/test_market_cap_growth.py
git commit -m "feat(mcg): 注册market-cap-growth双端点——指数/个股同形响应"
```

---

### Task 10: 前端 hook `useMarketCapGrowth`

**Files:**
- Create: `frontend/apps/web/src/hooks/useMarketCapGrowth.ts`

**Interfaces:**
- Consumes: Task 9 端点。
- Produces（Task 11/12/13 依赖，类型固定）:
  - `McgBarPoint = {report_date: string; revenue: number|null; net_profit: number|null}`
  - `McgData = {kind:'index'|'stock'; code:string; name:string|null; as_of:string|null; bars:{quarter:McgBarPoint[]; cumulative:McgBarPoint[]; ttm:McgBarPoint[]}; mv_series:{report_date:string; total_mv:number|null}[]; sample_count?:{report_date:string; count:number}[]; note?:string}`
  - `useMarketCapGrowth(kind:'index'|'stock', code:string|null, years=10) -> {data: McgData|null; loading: boolean; error: string|null}`
- 模式参照：`hooks/useValuationPercentile.ts`（模块级 API_BASE、cancelled 竞态保护、`json.code===0` 判定）。

- [ ] **Step 1: 写整文件**

```typescript
/**
 * 市值与业绩增长趋势数据 hook（指数/个股共用）。
 * 调 GET /financial/market-cap-growth/{kind}/{code}，
 * 三口径（单季/累计/TTM）一次返回，前端切换零请求。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface McgBarPoint {
  report_date: string;
  revenue: number | null;
  net_profit: number | null;
}

export interface McgData {
  kind: 'index' | 'stock';
  code: string;
  name: string | null;
  as_of: string | null;
  bars: {
    quarter: McgBarPoint[];
    cumulative: McgBarPoint[];
    ttm: McgBarPoint[];
  };
  mv_series: Array<{ report_date: string; total_mv: number | null }>;
  sample_count?: Array<{ report_date: string; count: number }>;
  note?: string;
}

export function useMarketCapGrowth(
  kind: 'index' | 'stock',
  code: string | null,
  years = 10,
) {
  const [data, setData] = useState<McgData | null>(null);
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
    fetch(
      `${API_BASE}/financial/market-cap-growth/${kind}/${code}?years=${years}`,
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
  }, [kind, code, years]);

  return { data, loading, error };
}
```

- [ ] **Step 2: 类型检查（build 在 Task 14 统一跑，这里先 tsc 快验）**

Run: `cd frontend && pnpm -F web exec tsc --noEmit 2>&1 | head -20`
Expected: 无本文件相关报错（仓库既有文件报错可忽略，只确认无 `useMarketCapGrowth` 相关错误）

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/hooks/useMarketCapGrowth.ts
git commit -m "feat(mcg): useMarketCapGrowth hook——三口径bars+市值线一次拉取"
```

---

### Task 11: 图表组件 `MarketCapGrowthChart`

**Files:**
- Create: `frontend/apps/web/src/components/MarketCapGrowthChart.tsx`

**Interfaces:**
- Consumes: Task 10 `McgData`；`lib/chartTheme`（CHART_COLORS/axisProps/gridProps/tooltipProps）；`components/ui` 的 StateView。
- Produces（Task 12/13 依赖）:
  - `MarketCapGrowthChart({title?, data: McgData|null, loading: boolean, error: string|null})`——自渲染指标×口径 chip 切换（默认营收+单季）、双轴 ComposedChart（左柱业绩/右线市值，单位亿）、指数版显示最新成分样本数。
- 自包含约定：chip 用内联样式（不依赖 Financial.css 的 fin-period-switcher，Indices 页无该类）；系列色只取 chartTheme 常量。

- [ ] **Step 1: 写整文件**

```tsx
/**
 * MarketCapGrowthChart —— 市值与业绩增长趋势（指数/个股共用）。
 * 左轴柱=业绩指标（营收/归母净利润 × 单季/累计/TTM），
 * 右轴折线=总市值（报告期末对齐，亿）。参考直播截图双轴形态。
 */
import React, { useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { StateView } from './ui';
import {
  CHART_COLORS,
  axisProps,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';
import type { McgData } from '../hooks/useMarketCapGrowth';

type MetricKey = 'revenue' | 'net_profit';
type PeriodKey = 'quarter' | 'cumulative' | 'ttm';

const METRICS: Array<[MetricKey, string]> = [
  ['revenue', '营收'],
  ['net_profit', '归母净利润'],
];
const PERIODS: Array<[PeriodKey, string]> = [
  ['quarter', '单季'],
  ['cumulative', '累计'],
  ['ttm', 'TTM'],
];

const chipStyle = (active: boolean): React.CSSProperties => ({
  padding: '3px 10px',
  fontSize: 12,
  borderRadius: 999,
  cursor: 'pointer',
  border: `1px solid ${
    active ? 'rgba(10,132,255,0.55)' : 'rgba(255,255,255,0.14)'
  }`,
  background: active ? 'rgba(10,132,255,0.15)' : 'transparent',
  color: active ? '#0a84ff' : '#a1a1a6',
});

interface Props {
  title?: string;
  data: McgData | null;
  loading: boolean;
  error: string | null;
}

export function MarketCapGrowthChart({ title, data, loading, error }: Props) {
  const [metric, setMetric] = useState<MetricKey>('revenue');
  const [period, setPeriod] = useState<PeriodKey>('quarter');

  const rows = useMemo(() => {
    if (!data?.bars) return [];
    const mvMap = new Map(
      (data.mv_series ?? []).map((p) => [p.report_date, p.total_mv]),
    );
    return (data.bars[period] ?? []).map((b) => ({
      label: b.report_date.slice(2, 7),
      metric: b[metric],
      total_mv: mvMap.get(b.report_date) ?? null,
    }));
  }, [data, metric, period]);

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="error" text={error} />;
  if (!data || rows.length === 0)
    return <StateView state="empty" text={data?.note || '暂无市值与业绩数据'} />;

  const metricLabel = METRICS.find(([k]) => k === metric)![1];
  const periodLabel = PERIODS.find(([k]) => k === period)![1];
  const lastCount = data.sample_count?.length
    ? data.sample_count[data.sample_count.length - 1].count
    : null;

  return (
    <div>
      {title && (
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>
          {title}
        </h3>
      )}
      <div
        style={{
          display: 'flex',
          gap: 8,
          flexWrap: 'wrap',
          marginBottom: 10,
          alignItems: 'center',
        }}
      >
        {METRICS.map(([k, l]) => (
          <button
            key={k}
            style={chipStyle(metric === k)}
            onClick={() => setMetric(k)}
          >
            {l}
          </button>
        ))}
        <span style={{ width: 8 }} />
        {PERIODS.map(([k, l]) => (
          <button
            key={k}
            style={chipStyle(period === k)}
            onClick={() => setPeriod(k)}
          >
            {l}
          </button>
        ))}
        {lastCount != null && (
          <span
            style={{
              fontSize: 11,
              color: '#86868b',
              marginLeft: 'auto',
            }}
          >
            成分股 {lastCount} 只
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart
          data={rows}
          margin={{ top: 5, right: 10, bottom: 0, left: 0 }}
        >
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" {...axisProps} minTickGap={30} />
          <YAxis
            yAxisId="left"
            {...axisProps}
            width={56}
            tickFormatter={(v: number) => `${v}亿`}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            {...axisProps}
            width={56}
            tickFormatter={(v: number) => `${v}亿`}
          />
          <Tooltip
            {...tooltipProps}
            formatter={(v: number, name: string) => [
              `${Number(v).toFixed(1)}亿`,
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar
            yAxisId="left"
            dataKey="metric"
            name={`${metricLabel}(${periodLabel})`}
            fill={CHART_COLORS[0]}
            opacity={0.6}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="total_mv"
            name="总市值"
            stroke={CHART_COLORS[2]}
            strokeWidth={2}
            dot={{ r: 2 }}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && pnpm -F web exec tsc --noEmit 2>&1 | head -20`
Expected: 无本文件相关报错

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/components/MarketCapGrowthChart.tsx
git commit -m "feat(mcg): MarketCapGrowthChart——蓝柱业绩/橙线市值双轴,指标×口径chip切换"
```

---

### Task 12: 个股 Panel + Financial 页「市值业绩」Tab

**Files:**
- Create: `frontend/apps/web/src/components/MarketCapGrowthPanel.tsx`
- Modify: `frontend/apps/web/src/pages/Financial.tsx`（四处小改）

**Interfaces:**
- Consumes: Task 10 hook、Task 11 Chart。
- Produces: `MarketCapGrowthPanel({symbol: string|null})`；Financial 页新 Tab key `'marketcapgrowth'`（label「市值业绩」）。
- 模式参照：`components/RatiosPanel.tsx`（自包含 Panel + `.fin-chart-card` 外壳）。

- [ ] **Step 1: 写 Panel 整文件**

```tsx
/**
 * MarketCapGrowthPanel —— 个股「市值业绩」Tab 面板。
 * 营收/归母净利润（单季/累计/TTM）柱 + 总市值折线，单位亿。
 */
import React from 'react';
import { MarketCapGrowthChart } from './MarketCapGrowthChart';
import { useMarketCapGrowth } from '../hooks/useMarketCapGrowth';

export const MarketCapGrowthPanel: React.FC<{ symbol: string | null }> = ({
  symbol,
}) => {
  const { data, loading, error } = useMarketCapGrowth('stock', symbol);
  return (
    <div className="fin-chart-card">
      <MarketCapGrowthChart
        title="市值与业绩增长趋势"
        data={data}
        loading={loading}
        error={error}
      />
    </div>
  );
};
```

- [ ] **Step 2: Financial.tsx 四处挂载**

2a. 导入（`import { FiveForcesPanel } ...` 行之后）：

```tsx
import { MarketCapGrowthPanel } from '../components/MarketCapGrowthPanel';
```

2b. TabType（246 行附近，`'valuation'` 之后）加 `| 'marketcapgrowth'`，完整行改为：

```tsx
type TabType = 'summary' | 'income' | 'balance' | 'cashflow' | 'commonsize' | 'ratios' | 'fiveforces' | 'cashflowanalysis' | 'forecast' | 'compare' | 'valuation' | 'marketcapgrowth' | 'dcf' | 'fundamental';
```

2c. tabs 数组：`{ key: 'valuation', label: '估值分位' },` 行之后插入：

```tsx
    { key: 'marketcapgrowth', label: '市值业绩' },
```

2d. 内容分支：`{activeTab === 'valuation' && renderValuation()}` 行之后插入：

```tsx
        {activeTab === 'marketcapgrowth' && <MarketCapGrowthPanel symbol={symbol} />}
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && pnpm -F web exec tsc --noEmit 2>&1 | head -20`
Expected: 无本任务文件相关报错

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/components/MarketCapGrowthPanel.tsx \
        frontend/apps/web/src/pages/Financial.tsx
git commit -m "feat(mcg): Financial页第14Tab「市值业绩」——自包含Panel挂载"
```

---

### Task 13: Indices 页「市值与业绩增长趋势」区块

**Files:**
- Modify: `frontend/apps/web/src/pages/Indices.tsx`（导入区+组件内 state+JSX 三处）
- Modify: `frontend/apps/web/src/pages/Indices.css`（文件末尾追加样式）

**Interfaces:**
- Consumes: Task 10 hook（kind='index'）、Task 11 Chart。
- Produces: Indices 页 9 指数切换区块（segmented 按钮，默认 000300 沪深300）。

- [ ] **Step 1: Indices.tsx 加导入**

在 `import { PageHeader, StateView } from '../components/ui';` 之后加：

```tsx
import { MarketCapGrowthChart } from '../components/MarketCapGrowthChart';
import { useMarketCapGrowth } from '../hooks/useMarketCapGrowth';
```

- [ ] **Step 2: 加常量（CORE_SYMBOLS 定义之后）**

```tsx
// 市值与业绩增长趋势区块支持的宽基指数（后端 quant_universe.index_constituents 对应）
const MCG_INDICES = [
  { code: '000300', name: '沪深300' },
  { code: '000016', name: '上证50' },
  { code: '000905', name: '中证500' },
  { code: '000852', name: '中证1000' },
  { code: '932000', name: '中证2000' },
  { code: '000903', name: '中证100' },
  { code: '000010', name: '上证180' },
  { code: '000985', name: '中证全指' },
  { code: '000688', name: '科创50' },
];
```

- [ ] **Step 3: 组件内加 state 与数据（其它 useState 声明之后）**

```tsx
  const [mcgCode, setMcgCode] = useState('000300');
  const { data: mcgData, loading: mcgLoading, error: mcgError } =
    useMarketCapGrowth('index', mcgCode);
  const mcgName =
    MCG_INDICES.find((i) => i.code === mcgCode)?.name ?? mcgCode;
```

- [ ] **Step 4: JSX 插入区块**

锚点：K 线区块的 `</section>` 与 `{/* ── Ranking table ── */}` 注释之间（用 `grep -n "Ranking table" pages/Indices.tsx` 定位）插入：

```tsx
      {/* ── 市值与业绩增长趋势 ── */}
      <section className="indices__mcg">
        <div className="indices__mcg-header">
          <h2 className="indices__mcg-title">市值与业绩增长趋势</h2>
          <div className="indices__mcg-switch">
            {MCG_INDICES.map((i) => (
              <button
                key={i.code}
                className={`indices__mcg-btn ${
                  mcgCode === i.code ? 'is-active' : ''
                }`}
                onClick={() => setMcgCode(i.code)}
              >
                {i.name}
              </button>
            ))}
          </div>
        </div>
        <div className="indices__mcg-body">
          <MarketCapGrowthChart
            title={`${mcgName}市值与业绩增长趋势`}
            data={mcgData}
            loading={mcgLoading}
            error={mcgError}
          />
        </div>
      </section>
```

- [ ] **Step 5: Indices.css 末尾追加样式**

```css
/* ── 市值与业绩增长趋势区块 ─────────────────────────────── */
.indices__mcg {
  margin-top: 20px;
}

.indices__mcg-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.indices__mcg-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.indices__mcg-switch {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.indices__mcg-btn {
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}

.indices__mcg-btn:hover {
  color: var(--color-text);
}

.indices__mcg-btn.is-active {
  color: var(--color-accent);
  border-color: var(--color-accent);
  background: rgba(10, 132, 255, 0.12);
}

.indices__mcg-body {
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 12px;
}
```

- [ ] **Step 6: 类型检查**

Run: `cd frontend && pnpm -F web exec tsc --noEmit 2>&1 | head -20`
Expected: 无本任务文件相关报错

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/web/src/pages/Indices.tsx frontend/apps/web/src/pages/Indices.css
git commit -m "feat(mcg): Indices页市值与业绩增长趋势区块——9宽基切换,默认沪深300"
```

---

### Task 14: 端到端验证（冒烟灌数 + 构建）

**Files:**
- 无新文件（验证性任务；如冒烟发现 bug，修复后归入对应文件 commit）

**Interfaces:**
- Consumes: Task 4/5/6 三个 job、Task 9 端点、Task 11-13 前端。

- [ ] **Step 1: 本地冒烟灌数（需要 DB + 外网；失败则记 TODO 不阻塞代码验收）**

```bash
cd backend
uv run python -c "
from src.domain.market.sync.jobs import index_constituent_sync as c
print('constituents:', c.run())
"
uv run python -c "
from src.domain.market.sync.jobs.index_financial_sync import sync_index_financial_quarterly as f
print('financial:', f())
"
uv run python -c "
from src.domain.market.sync.jobs.index_market_cap_sync import sync_index_market_cap as m
print('mv:', m())
"
```

Expected: `constituents:` 里 `000300: 300`（932000 应为 2000）；`financial:` 里 000300 有 40+ 期；`mv:` 里各指数 100+ 月度点。网络/DB 不可用时跳过并记录。

- [ ] **Step 2: 端点冒烟（不依赖 Step 1 也可验响应形状，bars 可能为空）**

```bash
cd backend
uv run python -c "
import json
from src.api.handler.financial_detail_handler import market_cap_growth_index, market_cap_growth_stock
r = json.loads(market_cap_growth_index('000300').body)
print('index code:', r['code'], 'bars periods:', len(r['data']['bars']['quarter']), 'mv points:', len(r['data']['mv_series']))
r2 = json.loads(market_cap_growth_stock('sh600519').body)
print('stock code:', r2['code'], 'bars periods:', len(r2['data']['bars']['quarter']), 'mv points:', len(r2['data']['mv_series']))
"
```

Expected: 两个 `code: 0`；灌数后 index 000300 bars ≥ 40 期、mv ≥ 40 点；stock sh600519 同量级。

- [ ] **Step 3: 后端相关测试全量重跑**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_market_cap_growth.py tests/domain/market/fundamental/test_period_transform.py tests/sync/test_index_constituent_sync.py tests/sync/test_index_market_cap_sync.py tests/api/test_market_cap_growth.py -v`
Expected: all passed

- [ ] **Step 4: 前端构建**

Run: `cd frontend && pnpm -F web build`
Expected: EXIT=0

- [ ] **Step 5: 浏览器目检（可选，dev server 可用时）**

`cd frontend && pnpm -F web dev` + 后端 `uv run uvicorn main:app`：
- `/indices` 页：新区块默认沪深300，蓝柱+橙线双轴，chip 切换（指标×口径）生效，TTM 线平滑、单季柱有季节性；
- `/financial` 选 sh600519：第 14 个 Tab「市值业绩」图表正常；
- 切到中证2000 等其他指数无报错。

- [ ] **Step 6: 收尾 commit（如有修复）**

```bash
git add <修复涉及的文件>
git commit -m "fix(mcg): 冒烟修复"
```

---

## 计划自审记录（写计划时已核对）

1. **规格覆盖**：规格§1 成分表/配置（Task 2/3/4）、§2 财务聚合（Task 5）、§3 市值回填（Task 6）、§调度（Task 7，合并为单链式 job 已在 Global Constraints 声明）、§4 纯函数（Task 1）、§5 handler/路由/缓存（Task 8/9）、§前端 hook/Chart/Panel/Tab/Indices 区块（Task 10-13）、§错误处理（非A股note/未配置指数error/None传播/connectNulls=false——Task 8/11）、§测试（各 Task 内嵌）、§验证（Task 14）。规格「预估」不属任务。
2. **占位符**：无 TBD/TODO；每个代码步骤含完整代码。
3. **类型一致性**：`replace_members(index_code, rows)`/`get_members(index_code)`（Task 3↔4/5/6）、`sync_index_financial_quarterly`/`sync_index_market_cap`/`index_constituent_sync.run`（Task 4/5/6↔7）、`to_quarterly/to_ttm/align_mv` 三键输入输出（Task 1↔8）、`McgData`/`McgBarPoint`（Task 10↔11/12/13）、handler 响应键 `bars.quarter|cumulative|ttm`/`mv_series`/`sample_count`/`note`（Task 8↔9↔10）逐一核对一致。
