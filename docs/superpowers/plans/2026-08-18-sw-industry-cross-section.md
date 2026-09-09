# 申万行业截面基础设施（SW Industry Cross-Section）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立申万一/二级行业成分股表与行业截面指标预计算表（集中度 CR4/CR8/HHI、毛利率/净利率/ROE 分布、行业营收同比，2016 年以来可回溯），并暴露个股行业归属与同行截面两个 API——为波特五力个股分析（子项目2）提供数据底座。

**Architecture:** 全预计算落表——job1 全量同步 131 个申万二级行业成分股到 `sw_industry_member`；job2 把成分股 × `stock_financial_detail`（income⋈balance 同期 JOIN，ROE=净利/权益）按 (行业, 报告期) 分组聚合到 `sw_industry_cross_section`；统计口径全部下沉纯函数模块 `industry_cross_section.py`（dict 进 dict 出，不读库不抛异常）；handler 消费两张表输出截面时序 + 同行明细 + 目标股分位。

**Tech Stack:** Python 3.12 / FastAPI / SQLModel（惰性建表，无 Alembic）/ psycopg2 execute_values / akshare（`sw_index_first_info` `sw_index_second_info` `index_component_sw`）/ pytest。

**Spec:** `docs/superpowers/specs/2026-08-18-sw-industry-cross-section-design.md`（口径与响应结构的唯一权威来源，实现有出入以 spec 为准）

## Global Constraints

- 工作目录 `backend/`，测试用 `uv run pytest <路径> -q`。既有全量回归存在 52 处失败（与本计划无关），**只看新增测试子集**。
- 纯函数模块惯例（`src/domain/market/fundamental/` 20+ 模块验证过）：模块顶部中文 docstring 写方法论（引课程 14 集）；dict 进 dict 出；不读 DB、不发 HTTP、不抛异常；缺失/分母≤0 → `None`；派生值只在最终赋值处 `round(x, 4)` 一次，绝对额不 round。
- 表名/列名/路由路径必须与 spec 完全一致：`sw_industry_member`、`sw_industry_cross_section`、`/financial/industry-members/{symbol}`、`/financial/industry-peers/{symbol}`。
- `sw_code` 一律不带 `.SI` 后缀（如 `801120`，与 `index_financial_quarterly` 一致；akshare 返回 `801120.SI` 需剥离）。
- symbol 前缀规则：`6*`→`sh`、`0*/3*`→`sz`、`4*/8*`→`bj`（如 `sh600519`）。
- ROE 非固定列：`= net_profit / equity × 100`（income⋈balance 同报告期，报告期累计未年化、全口径非归母）。
- API 响应信封 `{"code": 0, "msg": ..., "data": ...}`（`responses.success/error`）；handler 不直接 import akshare。
- 每个任务完成后独立 commit；commit message 用项目惯例（中文，`feat(scope):` / `test(scope):` 前缀）。

---

### Task 1: 纯函数 `cross_section_metrics`（单期截面统计）

**Files:**
- Create: `src/domain/market/fundamental/industry_cross_section.py`
- Test: `tests/domain/market/fundamental/test_industry_cross_section.py`

**Interfaces:**
- Consumes: 无（最底层模块）。
- Produces: `cross_section_metrics(peers: list[dict]) -> dict`。输入行 `{symbol, revenue, net_profit, gross_margin, net_margin, roe}`（revenue None 的行内部剔除）；输出 `{sample_count, revenue_sum, net_profit_sum, cr4, cr8, hhi, distribution}`，`distribution = {"gross_margin": {mean, median, std, p25, p75} | None, "net_margin": ..., "roe": ...}`。Task 5 的 `build_sections` 依赖此签名。

- [ ] **Step 1: 写失败测试**

创建 `tests/domain/market/fundamental/test_industry_cross_section.py`：

```python
"""行业截面纯函数测试。模式抄 test_ratio_analysis.py：dict 字面量 + pytest.approx。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.fundamental.industry_cross_section import (
    cross_section_metrics,
)


def _peer(symbol, revenue, net_profit=1.0, gross_margin=30.0,
          net_margin=10.0, roe=12.0):
    return {"symbol": symbol, "revenue": revenue, "net_profit": net_profit,
            "gross_margin": gross_margin, "net_margin": net_margin, "roe": roe}


# 5 家公司：营收 [50,30,10,5,5]，总营收 100
PEERS5 = [
    _peer("a", 50.0, gross_margin=50.0),
    _peer("b", 30.0, gross_margin=40.0),
    _peer("c", 10.0, gross_margin=30.0),
    _peer("d", 5.0, gross_margin=20.0),
    _peer("e", 5.0, gross_margin=10.0),
]


class TestCrossSectionMetrics:

    def test_concentration_hand_computed(self):
        """CR4=0.95, CR8=1.0, HHI=(.25+.09+.01+.0025+.0025)*10000=3550。"""
        m = cross_section_metrics(PEERS5)
        assert m["sample_count"] == 5
        assert m["revenue_sum"] == pytest.approx(100.0)
        assert m["cr4"] == pytest.approx(0.95)
        assert m["cr8"] == pytest.approx(1.0)
        assert m["hhi"] == pytest.approx(3550.0)

    def test_distribution_hand_computed(self):
        """gross_margin [10,20,30,40,50]：mean=30 median=30 p25=20 p75=40。"""
        d = cross_section_metrics(PEERS5)["distribution"]["gross_margin"]
        assert d["mean"] == pytest.approx(30.0)
        assert d["median"] == pytest.approx(30.0)
        assert d["p25"] == pytest.approx(20.0)
        assert d["p75"] == pytest.approx(40.0)
        assert d["std"] == pytest.approx(15.8114, abs=1e-3)

    def test_none_metric_excluded_but_kept_in_concentration(self):
        """毛利率 None 的股票从分布剔除，但仍计入营收/集中度。"""
        peers = [
            _peer("a", 50.0, gross_margin=None),
            _peer("b", 30.0, gross_margin=40.0),
            _peer("c", 10.0, gross_margin=20.0),
            _peer("d", 5.0, gross_margin=10.0),
        ]
        m = cross_section_metrics(peers)
        assert m["sample_count"] == 4
        d = m["distribution"]["gross_margin"]
        assert d["mean"] == pytest.approx(23.3333, abs=1e-3)  # 3 家
        assert m["cr4"] == pytest.approx(1.0)

    def test_revenue_none_row_dropped(self):
        peers = PEERS5 + [_peer("f", None)]
        assert cross_section_metrics(peers)["sample_count"] == 5

    def test_small_sample_all_none(self):
        """sample_count < 4 → 集中度与分布全 None。"""
        m = cross_section_metrics(PEERS5[:3])
        assert m["sample_count"] == 3
        assert m["cr4"] is None and m["cr8"] is None and m["hhi"] is None
        assert m["distribution"]["gross_margin"] is None

    def test_empty_peers(self):
        m = cross_section_metrics([])
        assert m["sample_count"] == 0
        assert m["revenue_sum"] is None and m["cr4"] is None

    def test_net_profit_sum_skips_none(self):
        peers = [
            _peer("a", 50.0, net_profit=None),
            _peer("b", 30.0, net_profit=3.0),
            _peer("c", 10.0, net_profit=-1.0),
            _peer("d", 5.0, net_profit=None),
        ]
        m = cross_section_metrics(peers)
        assert m["net_profit_sum"] == pytest.approx(2.0)  # 全 None 剔除后求和
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_industry_cross_section.py -q`
Expected: FAIL——`ModuleNotFoundError: No module named 'src.domain.market.fundamental.industry_cross_section'`

- [ ] **Step 3: 写最小实现**

创建 `src/domain/market/fundamental/industry_cross_section.py`：

```python
"""行业截面统计（纯函数）。

下游背景：波特五力行业分析（课程 14 集）的数据基础——集中度
（CR4/CR8/HHI）刻画"行业内竞争强度/进入壁垒"，盈利分布（毛利率/
净利率/ROE 的 mean/median/std/p25/p75）刻画"议价能力与行业盈利性"。

口径约定（spec: 2026-08-18-sw-industry-cross-section-design.md）：
- revenue 为 None 的行不进本期截面（调用方先剔除，此处再防御）；
- CR4/CR8/HHI 只用 revenue > 0 的行（份额非负才有意义）；
- revenue_sum/net_profit_sum 用全部非 None 行（净利可为负）；
- sample_count < 4 → 集中度与分布全 None（统计下限防微小样本噪声）；
- 分布用标准库 statistics：median / stdev（样本标准差，n≥2）/
  quantiles(n=4, method="inclusive") 取 p25/p75；
- 派生值只在最终赋值处 round 4 位；绝对额不 round。

dict 进 dict 出，不读 DB、不发 HTTP、不抛异常（fundamental 模块惯例）。
"""
import statistics

#: 参与分布统计的指标（固定列/派生列名，单位均为 %）
DIST_METRICS = ("gross_margin", "net_margin", "roe")

_MIN_SAMPLE = 4  # 集中度/分布统计下限


def _r4(v):
    return round(v, 4) if v is not None else None


def _dist(vals):
    """单指标分布；全 None → None。"""
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None
    d = {"mean": _r4(statistics.mean(xs)), "median": _r4(statistics.median(xs))}
    if len(xs) >= 2:
        q = statistics.quantiles(xs, n=4, method="inclusive")
        d["std"] = _r4(statistics.stdev(xs))
        d["p25"], d["p75"] = _r4(q[0]), _r4(q[2])
    else:
        d["std"] = d["p25"] = d["p75"] = None
    return d


def cross_section_metrics(peers: list) -> dict:
    """单期行业截面。

    Args:
        peers: [{symbol, revenue, net_profit, gross_margin, net_margin, roe}]
            （revenue None 的行内部剔除；净利/毛利率等可为 None）

    Returns:
        {sample_count, revenue_sum, net_profit_sum, cr4, cr8, hhi,
         distribution: {metric: {mean, median, std, p25, p75} | None}}
    """
    rows = [p for p in peers if p.get("revenue") is not None]
    n = len(rows)

    np_vals = [p["net_profit"] for p in rows if p.get("net_profit") is not None]
    out = {
        "sample_count": n,
        "revenue_sum": sum(p["revenue"] for p in rows) if rows else None,
        "net_profit_sum": sum(np_vals) if np_vals else None,
        "cr4": None, "cr8": None, "hhi": None,
        "distribution": {m: None for m in DIST_METRICS},
    }
    if n == 0:
        return out

    if n >= _MIN_SAMPLE:
        rev_total = out["revenue_sum"]
        pos = [p["revenue"] for p in rows if p["revenue"] > 0]
        if pos and rev_total and rev_total > 0:
            shares = sorted((v / rev_total for v in pos), reverse=True)
            out["cr4"] = _r4(sum(shares[:4]))
            out["cr8"] = _r4(sum(shares[:8]))
            out["hhi"] = _r4(sum(s * s for s in shares) * 10000)
        out["distribution"] = {
            m: _dist([p.get(m) for p in rows]) for m in DIST_METRICS
        }
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_industry_cross_section.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/fundamental/industry_cross_section.py tests/domain/market/fundamental/test_industry_cross_section.py
git commit -m "feat(industry-cross-section): 单期截面纯函数——CR4/CR8/HHI营收口径+三指标分布;样本<4全None;None剔除口径"
```

---

### Task 2: 纯函数 `attach_yoy` + `peer_ranks`

**Files:**
- Modify: `src/domain/market/fundamental/industry_cross_section.py`（追加）
- Test: `tests/domain/market/fundamental/test_industry_cross_section.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_r4`。
- Produces:
  - `attach_yoy(sections: list[dict]) -> list[dict]`——同一行业按 `report_date` **升序**的指标行（含 `revenue_sum`），就地补 `revenue_yoy`（去年同期 `revenue_sum` 同比-1；匹配不上/基数≤0/缺失 → `None`）。`report_date` 兼容 `str`（`YYYY-MM-DD`）与 `datetime.date`。Task 5 依赖。
  - `peer_ranks(peers: list[dict], target_symbol: str) -> dict`——`{"peers": [...], "target": {...} | None}`；每行补 `rank_revenue`/`rank_gross_margin`（降序名次，并列同名次，None 不参与）；`target = {percentile_revenue, percentile_gross_margin, percentile_roe, revenue_share}`（分位=值≤该股的样本数(含自身)/该指标有效样本数；revenue_share=该股营收/同行营收和）。目标股不在 peers → `target: None`。Task 6 依赖。

- [ ] **Step 1: 写失败测试（追加到测试文件）**

```python
import datetime as dt

from src.domain.market.fundamental.industry_cross_section import (
    attach_yoy,
    peer_ranks,
)


class TestAttachYoy:

    def _sections(self):
        return [
            {"report_date": "2023-12-31", "revenue_sum": 80.0},
            {"report_date": "2024-12-31", "revenue_sum": 100.0},
            {"report_date": "2025-12-31", "revenue_sum": 120.0},
        ]

    def test_yoy_chain(self):
        out = attach_yoy(self._sections())
        assert out[0]["revenue_yoy"] is None          # 首期无去年同期
        assert out[1]["revenue_yoy"] == pytest.approx(0.25)
        assert out[2]["revenue_yoy"] == pytest.approx(0.20)

    def test_quarter_matches_same_period_only(self):
        """2025-09-30 的同比期是 2024-09-30，不是相邻年报。"""
        secs = [
            {"report_date": "2024-09-30", "revenue_sum": 50.0},
            {"report_date": "2024-12-31", "revenue_sum": 90.0},
            {"report_date": "2025-09-30", "revenue_sum": 60.0},
        ]
        out = attach_yoy(secs)
        assert out[2]["revenue_yoy"] == pytest.approx(0.20)

    def test_base_le_zero_or_missing(self):
        secs = [
            {"report_date": "2024-12-31", "revenue_sum": 0.0},
            {"report_date": "2025-12-31", "revenue_sum": 10.0},
        ]
        assert attach_yoy(secs)[1]["revenue_yoy"] is None

    def test_date_object_and_none_revenue(self):
        secs = [
            {"report_date": dt.date(2024, 12, 31), "revenue_sum": None},
            {"report_date": dt.date(2025, 12, 31), "revenue_sum": 10.0},
        ]
        assert attach_yoy(secs)[1]["revenue_yoy"] is None


class TestPeerRanks:

    PEERS = [
        {"symbol": "sh600519", "name": "贵州茅台", "revenue": 170.0,
         "gross_margin": 91.6, "roe": 34.0},
        {"symbol": "sz000858", "name": "五粮液", "revenue": 90.0,
         "gross_margin": 75.0, "roe": 22.0},
        {"symbol": "sh603369", "name": "今世缘", "revenue": 100.0,
         "gross_margin": 75.0, "roe": 20.0},
        {"symbol": "sz000568", "name": "泸州老窖", "revenue": 30.0,
         "gross_margin": 88.0, "roe": None},
    ]

    def test_ranks_descending_with_ties(self):
        out = peer_ranks(self.PEERS, "sh600519")["peers"]
        by = {p["symbol"]: p for p in out}
        assert by["sh600519"]["rank_revenue"] == 1
        assert by["sh603369"]["rank_revenue"] == 2
        # 毛利率排序：茅台 91.6 第 1；泸州老窖 88.0 第 2；两家 75.0 并列第 3
        assert by["sz000568"]["rank_gross_margin"] == 2
        assert by["sz000858"]["rank_gross_margin"] == 3
        assert by["sh603369"]["rank_gross_margin"] == 3

    def test_target_percentile_and_share(self):
        out = peer_ranks(self.PEERS, "sh600519")
        t = out["target"]
        # 毛利率 91.6 全行业最高（4 家全有值）→ 1.0
        assert t["percentile_gross_margin"] == pytest.approx(1.0)
        # ROE 有效样本 3 家，茅台 34.0 最高 → 1.0
        assert t["percentile_roe"] == pytest.approx(1.0)
        # 营收份额 170/390
        assert t["revenue_share"] == pytest.approx(170.0 / 390.0)

    def test_target_absent(self):
        out = peer_ranks(self.PEERS, "hk00700")
        assert out["target"] is None
        assert len(out["peers"]) == 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_industry_cross_section.py -q`
Expected: FAIL——`ImportError: cannot import name 'attach_yoy'`

- [ ] **Step 3: 追加实现**

在 `industry_cross_section.py` 末尾追加：

```python
def _year_ago(report_date) -> str:
    """去年同期 ISO 日期串（兼容 str/date/datetime）。"""
    if isinstance(report_date, str):
        y, m, d = report_date[:4], report_date[5:7], report_date[8:10]
    else:
        y, m, d = (
            f"{report_date.year:04d}",
            f"{report_date.month:02d}",
            f"{report_date.day:02d}",
        )
    return f"{int(y) - 1}-{m}-{d}"


def attach_yoy(sections: list) -> list:
    """按行业时序补 revenue_yoy（去年同期营收和同比-1）。

    Args:
        sections: 同一行业按 report_date 升序的指标行，
            行含 report_date 与 revenue_sum（就地修改并返回）。
    """
    by_date = {}
    for s in sections:
        key = s["report_date"]
        key = key if isinstance(key, str) else key.isoformat()
        by_date[key] = s
    for s in sections:
        prev = by_date.get(_year_ago(s["report_date"]))
        cur, base = s.get("revenue_sum"), prev.get("revenue_sum") if prev else None
        if cur is None or base is None or base <= 0:
            s["revenue_yoy"] = None
        else:
            s["revenue_yoy"] = _r4(cur / base - 1)
    return sections


def peer_ranks(peers: list, target_symbol: str) -> dict:
    """最新期同行明细排名 + 目标股相对位置。

    Args:
        peers: [{symbol, name?, revenue, gross_margin, roe}]（最新期明细）
        target_symbol: 目标股 symbol（如 sh600519）

    Returns:
        {"peers": [行 + rank_revenue/rank_gross_margin],
         "target": {percentile_revenue, percentile_gross_margin,
                    percentile_roe, revenue_share} | None}
        分位 = 值<=该股的样本数（含自身）/ 该指标有效样本数；
        rank 降序并列同名次；指标 None 不参与该指标排名/分位。
    """
    out = [dict(p) for p in peers]
    for key, rank_key in (("revenue", "rank_revenue"),
                          ("gross_margin", "rank_gross_margin")):
        vals = sorted(
            (p[key] for p in out if p.get(key) is not None), reverse=True,
        )
        for p in out:
            v = p.get(key)
            p[rank_key] = vals.index(v) + 1 if v is not None else None

    tp = next((p for p in out if p.get("symbol") == target_symbol), None)
    target = None
    if tp is not None:
        target = {}
        rev_total = sum(
            p["revenue"] for p in out if p.get("revenue") is not None
        )
        for m in ("revenue", "gross_margin", "roe"):
            xs = [p[m] for p in out if p.get(m) is not None]
            v = tp.get(m)
            target[f"percentile_{m}"] = (
                _r4(sum(1 for x in xs if x <= v) / len(xs))
                if v is not None and xs else None
            )
        target["revenue_share"] = (
            _r4(tp["revenue"] / rev_total)
            if tp.get("revenue") is not None and rev_total and rev_total > 0
            else None
        )
    return {"peers": out, "target": target}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_industry_cross_section.py -q`
Expected: PASS（14 passed）

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/fundamental/industry_cross_section.py tests/domain/market/fundamental/test_industry_cross_section.py
git commit -m "feat(industry-cross-section): attach_yoy同比链+peer_ranks排名分位——并列同名次/含自身分位/目标缺席None"
```

---

### Task 3: SQLModel 两表 + 仓库层

**Files:**
- Create: `src/infra/database/market/sw_industry.py`
- 无单测（项目惯例：infra 层由 API 层 mock 测试 + 真库冒烟兜底，见 `index_financial.py`/`financial_full.py` 均无单测）。本任务验证 = 导入建表 + psql 抽查。

**Interfaces:**
- Consumes: `src.infra.database.sql_engine.engine.DBConnection/create_db_connection`、`get_dsn`（既有）。
- Produces:
  - `SwIndustryMember` / `SwIndustryCrossSection`（SQLModel 模型；模块导入即注册进 metadata，连接初始化时惰性建表）
  - `create_sw_industry_repository() -> SwIndustryRepository`，方法：
    - `replace_all_members(rows: list[dict]) -> int`——事务内 DELETE 全表 + 批量 INSERT（job1 用）
    - `get_member(symbol: str) -> dict | None`——dict 形式（`{symbol, code, name, sw_code_l1, sw_name_l1, sw_code_l2, sw_name_l2, weight, included_date}`；`included_date` 序列化为 ISO str）
    - `fetch_members() -> list[dict]`——全量（job2 备用/排查用）
    - `upsert_sections(rows: list[dict]) -> int`——`ON CONFLICT (sw_code, report_date) DO UPDATE`（job2 用）
    - `fetch_sections(sw_code: str, level: int, limit: int = 200) -> list[dict]`——按 `report_date` **降序**，行 dict 含全部截面列（`report_date` 转 ISO str，`distribution` 转 dict）；不足/无数据返回 `[]`
    - `fetch_peer_details(sw_code: str, level: int, report_date) -> list[dict]`——该行业该期同行明细 `[{symbol, name, revenue, net_profit, gross_margin, net_margin, roe}]`（roe 现算；revenue None 的行不返回）。Task 5/6 依赖。

- [ ] **Step 1: 写模型 + 仓库**

创建 `src/infra/database/market/sw_industry.py`（结构镜像 `index_financial.py`：SQLModel 会话读 + psycopg2 execute_values 批量写）：

```python
"""申万行业成分股与行业截面表。

sw_industry_member:      全市场申万一级/二级归属快照（job1 全量重灌）。
sw_industry_cross_section: 行业截面指标按报告期预计算（job2 全量重算
  upsert）——集中度 CR4/CR8/HHI（营收口径）、毛利率/净利率/ROE 分布、
  行业营收/净利总和与同比。下游：波特五力个股分析（课程 14 集）。

表由 SQLModel.metadata.create_all 惰性建表（项目无 Alembic，
同 national_team_holding 惯例）。
"""
import datetime as dt
import threading
from datetime import datetime
from typing import Any, Optional

import psycopg2
from psycopg2.extras import execute_values, Json
from sqlalchemy import JSON, Column, DateTime, func
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class SwIndustryMember(SQLModel, table=True):
    """申万成分股快照（PK(symbol, sw_code_l2) 防御偶发重复归属）。"""
    __tablename__ = "sw_industry_member"

    symbol: str = Field(primary_key=True)        # sh600519
    sw_code_l2: str = Field(primary_key=True)    # 801120（不带 .SI）
    code: str                                    # 纯6位
    name: Optional[str] = None
    sw_code_l1: str
    sw_name_l1: str
    sw_name_l2: str
    weight: Optional[float] = None               # akshare 最新权重%
    included_date: Optional[dt.date] = None
    synced_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now()),
    )


class SwIndustryCrossSection(SQLModel, table=True):
    """行业截面指标（PK(sw_code, report_date)；level=1/2 代码空间互斥）。"""
    __tablename__ = "sw_industry_cross_section"

    sw_code: str = Field(primary_key=True)
    report_date: dt.date = Field(primary_key=True)
    level: int                                    # 1=一级 2=二级
    sw_name: str
    sample_count: int = 0
    revenue_sum: Optional[float] = None           # 元（不转亿，前端格式化）
    net_profit_sum: Optional[float] = None
    cr4: Optional[float] = None                   # 0~1
    cr8: Optional[float] = None
    hhi: Optional[float] = None                   # 0~10000
    revenue_yoy: Optional[float] = None
    distribution: Any = Field(default=None, sa_column=Column(JSON))
    updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, server_default=func.now()),
    )


_MEMBER_COLUMNS = (
    "symbol", "sw_code_l2", "code", "name",
    "sw_code_l1", "sw_name_l1", "sw_name_l2",
    "weight", "included_date",
)
_SECTION_COLUMNS = (
    "sw_code", "report_date", "level", "sw_name", "sample_count",
    "revenue_sum", "net_profit_sum", "cr4", "cr8", "hhi",
    "revenue_yoy", "distribution",
)


def _member_dict(r) -> dict:
    d = {c: getattr(r, c) for c in _MEMBER_COLUMNS}
    d["included_date"] = (
        d["included_date"].isoformat() if d.get("included_date") else None
    )
    return d


class SwIndustryRepository:
    """申万行业数据访问（SQLModel 读 + psycopg2 批量写）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 成分股 ──

    def replace_all_members(self, rows: list) -> int:
        """全量重灌（单事务 DELETE + INSERT，幂等）。"""
        if not rows:
            return 0
        values = [tuple(r.get(c) for c in _MEMBER_COLUMNS) for r in rows]
        sql = "DELETE FROM sw_industry_member"
        ins = """
            INSERT INTO sw_industry_member ({cols})
            VALUES %s
        """.format(cols=", ".join(_MEMBER_COLUMNS))
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                execute_values(cur, ins, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def get_member(self, symbol: str) -> Optional[dict]:
        with self._db.session_scope() as s:
            r = s.exec(
                select(SwIndustryMember).where(
                    SwIndustryMember.symbol == symbol,
                )
            ).first()
            return _member_dict(r) if r else None

    def fetch_members(self) -> list:
        with self._db.session_scope() as s:
            rows = list(
                s.exec(select(SwIndustryMember)).all()
            )
            return [_member_dict(r) for r in rows]

    # ── 截面 ──

    def upsert_sections(self, rows: list) -> int:
        """批量 upsert（ON CONFLICT (sw_code, report_date) DO UPDATE）。"""
        if not rows:
            return 0
        values = []
        for r in rows:
            rd = r.get("report_date")
            if hasattr(rd, "isoformat"):
                rd = rd.isoformat()
            values.append(tuple(
                Json(r[c]) if c == "distribution" else r.get(c)
                if c != "report_date" else rd
                for c in _SECTION_COLUMNS
            ))
        sql = """
            INSERT INTO sw_industry_cross_section ({cols})
            VALUES %s
            ON CONFLICT (sw_code, report_date) DO UPDATE SET
                level=EXCLUDED.level, sw_name=EXCLUDED.sw_name,
                sample_count=EXCLUDED.sample_count,
                revenue_sum=EXCLUDED.revenue_sum,
                net_profit_sum=EXCLUDED.net_profit_sum,
                cr4=EXCLUDED.cr4, cr8=EXCLUDED.cr8, hhi=EXCLUDED.hhi,
                revenue_yoy=EXCLUDED.revenue_yoy,
                distribution=EXCLUDED.distribution,
                updated_at=now()
        """.format(cols=", ".join(_SECTION_COLUMNS))
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def fetch_sections(self, sw_code: str, level: int,
                       limit: int = 200) -> list:
        """截面时序，report_date 降序（最新期在前）。"""
        with self._db.session_scope() as s:
            rows = list(s.exec(
                select(SwIndustryCrossSection)
                .where(SwIndustryCrossSection.sw_code == sw_code,
                       SwIndustryCrossSection.level == level)
                .order_by(SwIndustryCrossSection.report_date.desc())
                .limit(limit)
            ).all())
            out = []
            for r in rows:
                d = {c: getattr(r, c) for c in _SECTION_COLUMNS}
                d["report_date"] = d["report_date"].isoformat()
                out.append(d)
            return out

    def fetch_peer_details(self, sw_code: str, level: int,
                           report_date) -> list:
        """同行明细：member ⋈ income ⋈ balance（同期），roe 现算。

        revenue 为 None 的行不返回（spec 剔除口径）。
        """
        sw_col = "sw_code_l2" if level == 2 else "sw_code_l1"
        sql = f"""
            SELECT m.symbol, m.name,
                   i.revenue, i.net_profit, i.gross_margin, i.net_margin,
                   b.equity
            FROM sw_industry_member m
            JOIN stock_financial_detail i
              ON i.symbol = m.symbol
             AND i.statement_type = 'income'
             AND i.report_date = %(rd)s
            LEFT JOIN stock_financial_detail b
              ON b.symbol = i.symbol
             AND b.statement_type = 'balance'
             AND b.report_date = %(rd)s
            WHERE m.{sw_col} = %(sw)s
              AND i.revenue IS NOT NULL
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"rd": report_date, "sw": sw_code})
                raw = cur.fetchall()
        finally:
            conn.close()
        out = []
        for symbol, name, rev, np_, gm, nm, equity in raw:
            roe = None
            if np_ is not None and equity and equity > 0:
                roe = round(np_ / equity * 100, 4)
            out.append({
                "symbol": symbol, "name": name, "revenue": rev,
                "net_profit": np_, "gross_margin": gm,
                "net_margin": nm, "roe": roe,
            })
        return out


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


def create_sw_industry_repository(
    db_connection: DBConnection | None = None,
) -> SwIndustryRepository:
    """创建申万行业仓储实例（首次调用触发惰性建表）。"""
    return SwIndustryRepository(db_connection or _get_db_connection())
```

- [ ] **Step 2: 验证建表**

Run:
```bash
cd backend && uv run python -c "
from src.infra.database.market.sw_industry import create_sw_industry_repository
repo = create_sw_industry_repository()  # 触发建表
print(repo.get_member('sh600519'))      # 预期 None（job1 未跑）
print(repo.fetch_sections('801120', 2)) # 预期 []
" 2>&1 | tail -3
```
Expected: `None` 与 `[]`（表已建，查询不报错；日志行忽略）

- [ ] **Step 3: psql 确认表结构**

Run: `psql "$YTRADER_DB_DSN" -c '\d sw_industry_member' -c '\d sw_industry_cross_section'`
Expected: 两表存在，主键分别为 `(symbol, sw_code_l2)`、`(sw_code, report_date)`

- [ ] **Step 4: Commit**

```bash
git add src/infra/database/market/sw_industry.py
git commit -m "feat(sw-industry): 成分股+截面两表SQLModel模型与仓库——全量重灌/降序时序/同行明细JOIN(roe现算)"
```

---

### Task 4: job1 成分股同步

**Files:**
- Create: `src/domain/market/sync/jobs/sw_industry_member_sync.py`
- Test: `tests/domain/market/sync/test_sw_industry_member_sync.py`（新建目录 `__init__.py` 不需要——pytest rootdir 发现即可；若既有 `tests/domain/market/` 无 `__init__.py` 则同样不加）

**Interfaces:**
- Consumes: Task 3 的 `create_sw_industry_repository().replace_all_members(rows)`。
- Produces: `run(interval: float = 0.3) -> dict`——`{"industries": 成功行业数, "failed": [sw_code...], "members": 总行数}`；`build_member_rows(first_info, second_info, cons_by_code) -> list[dict]`（纯转换，rows 形状=Task 3 `_MEMBER_COLUMNS`）。

- [ ] **Step 1: 写失败测试**

创建 `tests/domain/market/sync/test_sw_industry_member_sync.py`：

```python
"""job1 转换逻辑测试（mock 小 DataFrame，不发 HTTP）。"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.domain.market.sync.jobs.sw_industry_member_sync import (
    build_member_rows,
)

FIRST = pd.DataFrame([
    {"行业代码": "801080.SI", "行业名称": "食品饮料"},
    {"行业代码": "801010.SI", "行业名称": "农林牧渔"},
])
SECOND = pd.DataFrame([
    {"行业代码": "801120.SI", "行业名称": "白酒Ⅱ", "上级行业": "食品饮料"},
    {"行业代码": "801125.SI", "行业名称": "啤酒", "上级行业": "食品饮料"},
])
# 白酒 2 只 + 啤酒 1 只；啤酒拉取失败（不在 cons_by_code）
CONS = {
    "801120": pd.DataFrame([
        {"证券代码": "600519", "证券名称": "贵州茅台",
         "最新权重": 12.3, "计入日期": "2021-12-13"},
        {"证券代码": "000596", "证券名称": "古井贡酒",
         "最新权重": 1.2, "计入日期": "2021-12-13"},
    ]),
}


def test_transform_si_stripped_prefix_mapped():
    rows = build_member_rows(FIRST, SECOND, CONS)
    assert len(rows) == 2  # 啤酒缺成分 → 跳过
    m = next(r for r in rows if r["symbol"] == "sh600519")
    assert m["sw_code_l2"] == "801120"          # .SI 剥离
    assert m["sw_name_l2"] == "白酒Ⅱ"
    assert m["sw_code_l1"] == "801080"          # 上级行业名 → 一级代码
    assert m["sw_name_l1"] == "食品饮料"
    assert m["code"] == "600519"
    assert m["weight"] == 12.3
    assert m["included_date"] is not None


def test_prefix_rules():
    rows = build_member_rows(FIRST, SECOND, {
        "801120": pd.DataFrame([{"证券代码": "300750", "证券名称": "X",
                                 "最新权重": None, "计入日期": None}]),
        "801125": pd.DataFrame([{"证券代码": "830799", "证券名称": "Y",
                                 "最新权重": None, "计入日期": None}]),
    })
    syms = {r["code"]: r["symbol"] for r in rows}
    assert syms["300750"] == "sz300750"
    assert syms["830799"] == "bj830799"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/sync/test_sw_industry_member_sync.py -q`
Expected: FAIL——`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

创建 `src/domain/market/sync/jobs/sw_industry_member_sync.py`：

```python
"""申万成分股同步 job：二级行业成分 → sw_industry_member 全量重灌。

数据源（akshare 直连，仅 job 内消费；handler 不 import akshare）：
  sw_index_first_info()      31 个一级（行业名称 → 行业代码 映射）
  sw_index_second_info()     131 个二级（含"上级行业"名称列）
  index_component_sw(code)   每个二级的成分股（约 5400 行合计）

一级归属由 second_info 的上级行业**名称**经 first_info 映射为代码——
不单独拉一级成分（与申万官方一级成分可能有个股级微差，spec 已注明）。
单行业失败跳过（全量重灌幂等，下轮补齐）；0.3s 间隔防限流。
"""
import logging
import time

import akshare as ak
import pandas as pd

from src.infra.database.market.sw_industry import (
    create_sw_industry_repository,
)

log = logging.getLogger(__name__)


def _strip_si(code: str) -> str:
    return str(code).split(".")[0].strip()


def _to_prefixed(code: str) -> str:
    c = str(code).strip()
    if c.startswith(("sh", "sz", "bj")):
        return c
    if c.startswith("6"):
        return f"sh{c}"
    if c.startswith(("0", "3")):
        return f"sz{c}"
    if c.startswith(("8", "4")):
        return f"bj{c}"
    return c


def build_member_rows(first_info: pd.DataFrame,
                      second_info: pd.DataFrame,
                      cons_by_code: dict) -> list:
    """纯转换：一二级清单 + 各行业成分 DataFrame → member 行。

    cons_by_code 缺失的行业（拉取失败）整组跳过。
    """
    l1_code_by_name = {
        str(r["行业名称"]).strip(): _strip_si(r["行业代码"])
        for _, r in first_info.iterrows()
    }
    rows: list[dict] = []
    for _, sec in second_info.iterrows():
        l2_code = _strip_si(sec["行业代码"])
        l2_name = str(sec["行业名称"]).strip()
        l1_name = str(sec["上级行业"]).strip()
        l1_code = l1_code_by_name.get(l1_name)
        if not l1_code:
            log.warning("[sw_member] 一级映射缺失: %s", l1_name)
            continue
        cons = cons_by_code.get(l2_code)
        if cons is None or cons.empty:
            continue
        for _, c in cons.iterrows():
            inc = c.get("计入日期")
            rows.append({
                "symbol": _to_prefixed(c["证券代码"]),
                "sw_code_l2": l2_code,
                "code": str(c["证券代码"]).strip(),
                "name": c.get("证券名称"),
                "sw_code_l1": l1_code,
                "sw_name_l1": l1_name,
                "sw_name_l2": l2_name,
                "weight": float(c["最新权重"])
                if pd.notna(c.get("最新权重")) else None,
                "included_date": inc if isinstance(inc, str) else None,
            })
    return rows


def run(interval: float = 0.3) -> dict:
    """全量同步。Returns {industries, failed: [sw_code...], members}。"""
    first_info = ak.sw_index_first_info()
    second_info = ak.sw_index_second_info()
    cons_by_code: dict = {}
    failed: list[str] = []
    for _, sec in second_info.iterrows():
        code = _strip_si(sec["行业代码"])
        try:
            cons_by_code[code] = ak.index_component_sw(code)
            time.sleep(interval)
        except Exception as e:  # noqa: BLE001
            failed.append(code)
            log.warning("[sw_member] %s 拉取失败: %s", code, e)
    rows = build_member_rows(first_info, second_info, cons_by_code)
    wrote = create_sw_industry_repository().replace_all_members(rows)
    log.info("[sw_member] 成员 %d 行，失败行业 %d 个",
             wrote, len(failed))
    return {
        "industries": len(cons_by_code), "failed": failed, "members": wrote,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/sync/test_sw_industry_member_sync.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: 真跑同步（约 2~3 分钟，131 次调用）**

Run:
```bash
cd backend && uv run python -c "
from src.domain.market.sync.jobs.sw_industry_member_sync import run
print(run())
" 2>&1 | tail -2
```
Expected: `{'industries': 13x, 'failed': [], 'members': 5xxx}`（members 约 5400±500；`failed` 允许个位数——下轮补齐）

- [ ] **Step 6: 抽查茅台归属**

Run: `cd backend && uv run python -c "
from src.infra.database.market.sw_industry import create_sw_industry_repository
print(create_sw_industry_repository().get_member('sh600519'))
" 2>&1 | tail -1`
Expected: dict 含 `'sw_code_l2': '801120'`、`'sw_name_l1': '食品饮料'`（一级名称以 akshare 当日返回为准）

- [ ] **Step 7: Commit**

```bash
git add src/domain/market/sync/jobs/sw_industry_member_sync.py tests/domain/market/sync/test_sw_industry_member_sync.py
git commit -m "feat(sw-industry): 成分股同步job——131二级行业0.3s限流/失败跳过/全量重灌;茅台归属白酒II实测"
```

---

### Task 5: job2 行业截面同步

**Files:**
- Create: `src/domain/market/sync/jobs/sw_industry_cross_section_sync.py`
- Test: `tests/domain/market/sync/test_sw_industry_cross_section_sync.py`

**Interfaces:**
- Consumes: Task 1/2 的 `cross_section_metrics`/`attach_yoy`；Task 3 的 `create_sw_industry_repository().upsert_sections(rows)`。
- Produces:
  - `build_sections(details: list[dict]) -> list[dict]`——明细行 → 截面行（行键=Task 3 `_SECTION_COLUMNS`）。明细行 `{sw_code_l1, sw_name_l1, sw_code_l2, sw_name_l2, report_date, symbol, revenue, net_profit, gross_margin, net_margin, equity}`（report_date 为 `datetime.date`；revenue None 的行 SQL 已过滤，函数内再防御）。每行先派生 `roe = net_profit / equity × 100`，再展开 level2（按 `sw_code_l2` 分组）+ level1（按 `sw_code_l1` 分组，成员=二级并集）两套组，组内按 `report_date` 升序逐期 `cross_section_metrics`，最后每组时序 `attach_yoy`。
  - `run() -> dict`——`{"sections": 行数, "industries": 行业数}`；SQL 取数（报告期窗口：`>= DATE '2016-01-01'` 且（12 月年报 或 `>= CURRENT_DATE - INTERVAL '28 months'`））→ `build_sections` → `upsert_sections`。

- [ ] **Step 1: 写失败测试**

创建 `tests/domain/market/sync/test_sw_industry_cross_section_sync.py`：

```python
"""job2 编排纯函数测试（明细行 → 截面行，不发 HTTP 不读库）。"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.domain.market.sync.jobs.sw_industry_cross_section_sync import (
    build_sections,
)


def _d(year):
    return dt.date(year, 12, 31)


def _detail(symbol, year, revenue, net_profit=1.0, gm=30.0, equity=10.0):
    return {
        "sw_code_l1": "801080", "sw_name_l1": "食品饮料",
        "sw_code_l2": "801120", "sw_name_l2": "白酒Ⅱ",
        "report_date": _d(year), "symbol": symbol,
        "revenue": revenue, "net_profit": net_profit,
        "gross_margin": gm, "net_margin": 10.0, "equity": equity,
    }


def _two_years():
    rows = []
    for year in (2024, 2025):
        for i in range(4):
            rows.append(_detail(f"s{i}", year, 40.0 - i * 10,
                                net_profit=4.0 - i, gm=80.0 - i * 20))
    return rows


class TestBuildSections:

    def test_two_levels_two_periods_with_yoy(self):
        out = build_sections(_two_years())
        # 2 级 × 2 年 = 4 行
        assert len(out) == 4
        keys = {(r["level"], r["sw_code"], r["report_date"]) for r in out}
        assert (2, "801120", _d(2025)) in keys
        assert (1, "801080", _d(2025)) in keys
        s25 = next(r for r in out
                   if r["level"] == 2 and r["report_date"] == _d(2025))
        s24 = next(r for r in out
                   if r["level"] == 2 and r["report_date"] == _d(2024))
        assert s25["sample_count"] == 4
        assert s25["revenue_sum"] == pytest.approx(100.0)
        # 营收两年同值 → yoy=0；首期 yoy=None
        assert s25["revenue_yoy"] == pytest.approx(0.0)
        assert s24["revenue_yoy"] is None
        assert s25["distribution"]["gross_margin"]["mean"] == (
            pytest.approx(50.0)
        )

    def test_roe_derived_from_equity(self):
        rows = [_detail("s0", 2025, 50.0, net_profit=10.0, equity=40.0)]
        out = build_sections(rows)
        # roe=10/40*100=25 进入样本（样本<4 分布 None，但不报错）
        assert out[0]["sample_count"] == 1

    def test_level1_is_union_of_level2(self):
        """一级成分=名下二级并集（本测试两组同规模→一级样本=二级样本）。"""
        rows = []
        for year in (2025,):
            for i in range(4):
                d = _detail(f"s{i}", year, 10.0)
                d["sw_code_l2"] = "801120" if i < 2 else "801125"
                d["sw_name_l2"] = "白酒Ⅱ" if i < 2 else "啤酒"
                rows.append(d)
        out = build_sections(rows)
        l1 = next(r for r in out if r["level"] == 1)
        assert l1["sample_count"] == 4  # 两个二级各 2 只并集

    def test_revenue_none_row_defensive(self):
        rows = _two_years()
        bad = _detail("s9", 2025, None)
        out = build_sections(rows + [bad])
        s25 = next(r for r in out
                   if r["level"] == 2 and r["report_date"] == _d(2025))
        assert s25["sample_count"] == 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/sync/test_sw_industry_cross_section_sync.py -q`
Expected: FAIL——`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

创建 `src/domain/market/sync/jobs/sw_industry_cross_section_sync.py`：

```python
"""行业截面同步 job：成分股 × 财务明细 → sw_industry_cross_section。

取数（raw psycopg2）：sw_industry_member ⋈ stock_financial_detail
  income（报告期窗口内、revenue 非空）LEFT JOIN balance（同期，取 equity）。
报告期窗口：>= 2016-01-01 且（12-31 年报 或 最近 28 个月≈8 季度）。
统计（纯函数）：每 (level, sw_code, report_date) 分组调
  cross_section_metrics；每组按期升序 attach_yoy。
口径：ROE=净利/权益×100（全口径未年化）；一级成分=名下二级并集。
全量重算 upsert——财务回填后重跑即自动修正（幂等）。
"""
import logging

import psycopg2

from src.domain.market.fundamental.industry_cross_section import (
    attach_yoy,
    cross_section_metrics,
)
from src.infra.database.market.sw_industry import (
    create_sw_industry_repository,
)
from src.infra.database.sql_engine.dsn import get_dsn

log = logging.getLogger(__name__)

_DETAIL_SQL = """
    SELECT m.sw_code_l1, m.sw_name_l1, m.sw_code_l2, m.sw_name_l2,
           i.report_date, i.symbol,
           i.revenue, i.net_profit, i.gross_margin, i.net_margin,
           b.equity
    FROM sw_industry_member m
    JOIN stock_financial_detail i
      ON i.symbol = m.symbol
     AND i.statement_type = 'income'
     AND i.report_date >= DATE '2016-01-01'
     AND (EXTRACT(MONTH FROM i.report_date) = 12
          OR i.report_date >= CURRENT_DATE - INTERVAL '28 months')
    LEFT JOIN stock_financial_detail b
      ON b.symbol = i.symbol
     AND b.statement_type = 'balance'
     AND b.report_date = i.report_date
    WHERE i.revenue IS NOT NULL
"""


def _derive_roe(row: dict) -> float | None:
    np_, eq = row.get("net_profit"), row.get("equity")
    if np_ is None or eq is None or eq <= 0:
        return None
    return np_ / eq * 100


def build_sections(details: list) -> list:
    """明细行 → 截面行（level2 + level1 两套组）。

    Returns: [{sw_code, report_date, level, sw_name, sample_count,
               revenue_sum, net_profit_sum, cr4, cr8, hhi,
               revenue_yoy, distribution}]
    """
    peers_by_key: dict = {}  # (level, sw_code) -> {report_date -> [peer]}
    names: dict = {}
    for row in details:
        if row.get("revenue") is None:
            continue
        peer = dict(row)
        peer["roe"] = _derive_roe(row)
        for level, code_col, name_col in (
            (2, "sw_code_l2", "sw_name_l2"),
            (1, "sw_code_l1", "sw_name_l1"),
        ):
            code = row[code_col]
            names[(level, code)] = row[name_col]
            peers_by_key.setdefault((level, code), {}).setdefault(
                row["report_date"], []
            ).append(peer)

    out: list[dict] = []
    for (level, code), by_date in peers_by_key.items():
        dates = sorted(by_date)
        secs = []
        for d in dates:
            m = cross_section_metrics(by_date[d])
            secs.append({
                "sw_code": code, "report_date": d, "level": level,
                "sw_name": names[(level, code)], **m,
            })
        attach_yoy(secs)
        out.extend(secs)
    return out


def run() -> dict:
    """全量重算截面。Returns {sections, industries}。"""
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(_DETAIL_SQL)
            cols = [c.name for c in cur.description]
            details = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()
    log.info("[sw_xs] 明细行 %d", len(details))

    rows = build_sections(details)
    wrote = create_sw_industry_repository().upsert_sections(rows)
    industries = len({(r["level"], r["sw_code"]) for r in rows})
    log.info("[sw_xs] 截面 %d 行 / %d 个(级别,行业)", wrote, industries)
    return {"sections": wrote, "industries": industries}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/sync/test_sw_industry_cross_section_sync.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 真跑同步（秒级~分钟级）**

Run:
```bash
cd backend && uv run python -c "
from src.domain.market.sync.jobs.sw_industry_cross_section_sync import run
print(run())
" 2>&1 | tail -2
```
Expected: `{'sections': 3xxx~4xxx, 'industries': 3xx}`（131 二级 + 31 一级 = 162 组 × 期数不等）

- [ ] **Step 6: 白酒截面抽查（对照直觉）**

Run: `cd backend && uv run python -c "
from src.infra.database.market.sw_industry import create_sw_industry_repository
secs = create_sw_industry_repository().fetch_sections('801125', 2, limit=3)
for s in secs: print(s['report_date'], 'n=', s['sample_count'], 'cr4=', s['cr4'], 'hhi=', s['hhi'])
" 2>&1 | tail -3`
Expected: 最新期 n≈112；`cr4` 明显大于 0.5（白酒头部集中）；含 2025-12-31 期

（801125 = 白酒Ⅱ 二级真实代码——Task 4 真跑已验证 801120 是一级食品饮料、801125 才是白酒二级。）

- [ ] **Step 7: Commit**

```bash
git add src/domain/market/sync/jobs/sw_industry_cross_section_sync.py tests/domain/market/sync/test_sw_industry_cross_section_sync.py
git commit -m "feat(sw-industry): 截面同步job——member⋈income⋈balance取数+纯函数编排两级分组;yoy同期链;全量重算幂等"
```

---

### Task 6: Handler + 路由 + API 测试

**Files:**
- Modify: `src/api/handler/financial_detail_handler.py`（文件末尾追加，`ratios()` 之后）
- Modify: `src/api/router/financial_router.py`（`_ratio_analysis` 块之后追加）
- Test: `tests/api/test_industry_peers.py`

**Interfaces:**
- Consumes: Task 2 `peer_ranks`；Task 3 仓库（`get_member`/`fetch_sections`/`fetch_peer_details`）。
- Produces: `industry_members(symbol: str) -> Any` 与 `industry_peers(symbol: str, level: int = 2, limit: int = 13) -> Any`（handler 函数，路由薄壳调用）。响应结构见 spec 第 5 节（`industry`/`sections`/`peers`/`target` 四块）。

- [ ] **Step 1: 写失败测试**

创建 `tests/api/test_industry_peers.py`：

```python
"""行业截面端点测试（mock repo，模式抄 test_ratios.py）。"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

MEMBER = {
    "symbol": "sh600519", "code": "600519", "name": "贵州茅台",
    "sw_code_l1": "801080", "sw_name_l1": "食品饮料",
    "sw_code_l2": "801120", "sw_name_l2": "白酒Ⅱ",
    "weight": 12.3, "included_date": "2021-12-13",
}

SECTIONS = [
    {"sw_code": "801120", "report_date": "2025-12-31", "level": 2,
     "sw_name": "白酒Ⅱ", "sample_count": 112, "revenue_sum": 9.5e12,
     "net_profit_sum": 3.2e12, "cr4": 0.52, "cr8": 0.71, "hhi": 980.2,
     "revenue_yoy": 0.08,
     "distribution": {"gross_margin": {"mean": 60.0, "median": 70.0,
                                       "std": 15.0, "p25": 55.0, "p75": 78.0}}},
    {"sw_code": "801120", "report_date": "2024-12-31", "level": 2,
     "sw_name": "白酒Ⅱ", "sample_count": 110, "revenue_sum": 8.8e12,
     "net_profit_sum": 3.0e12, "cr4": 0.50, "cr8": 0.70, "hhi": 950.0,
     "revenue_yoy": None, "distribution": None},
]

PEERS = [
    {"symbol": "sh600519", "name": "贵州茅台", "revenue": 1.7e11,
     "net_profit": 8.5e10, "gross_margin": 91.6, "net_margin": 50.0,
     "roe": 34.0},
    {"symbol": "sz000858", "name": "五粮液", "revenue": 9.0e10,
     "net_profit": 3.2e10, "gross_margin": 75.0, "net_margin": 35.0,
     "roe": 22.0},
]


def _repo(**kw):
    r = MagicMock()
    r.get_member.return_value = kw.get("member", MEMBER)
    r.fetch_sections.return_value = kw.get("sections", SECTIONS)
    r.fetch_peer_details.return_value = kw.get("peers", PEERS)
    return r


def _call_members(repo):
    from src.api.handler.financial_detail_handler import industry_members
    with patch(
        "src.infra.database.market.sw_industry"
        ".create_sw_industry_repository",
        return_value=repo,
    ):
        return json.loads(industry_members("sh600519").body)


def _call_peers(repo, level=2, limit=13):
    from src.api.handler.financial_detail_handler import industry_peers
    with patch(
        "src.infra.database.market.sw_industry"
        ".create_sw_industry_repository",
        return_value=repo,
    ):
        return json.loads(industry_peers("sh600519", level, limit).body)


def test_industry_members_ok():
    body = _call_members(_repo())
    assert body["code"] == 0
    d = body["data"]
    assert d["sw_l2"] == {"code": "801120", "name": "白酒Ⅱ"}
    assert d["sw_l1"]["code"] == "801080"


def test_industry_members_no_attribution_error():
    body = _call_members(_repo(member=None))
    assert body["code"] != 0


def test_industry_peers_full_shape():
    body = _call_peers(_repo())
    assert body["code"] == 0
    d = body["data"]
    assert d["industry"]["level"] == 2
    assert d["industry"]["code"] == "801120"
    assert d["industry"]["degraded"] is False
    assert [s["report_date"] for s in d["sections"]] == [
        "2025-12-31", "2024-12-31",
    ]
    assert d["peers"][0]["rank_revenue"] == 1
    assert d["target"]["percentile_gross_margin"] == 1.0


def test_industry_peers_empty_sections_error():
    body = _call_peers(_repo(sections=[]))
    assert body["code"] != 0


def test_industry_peers_degrades_to_level1():
    """二级最新期 sample_count<8 → 降一级，degraded=true。"""
    small = [dict(SECTIONS[0], sample_count=5)]
    repo = _repo(sections=small)
    body = _call_peers(repo)
    assert body["code"] == 0
    d = body["data"]
    assert d["industry"]["degraded"] is True
    assert d["industry"]["level"] == 1
    assert d["industry"]["code"] == "801080"
    assert "降" in d["industry"]["note"]
    # 降级后用一级 code + level=1 重新取截面与明细
    assert repo.fetch_sections.call_count == 2


def test_industry_peers_target_absent_note():
    """目标股有归属但最新期无财务 → target None + note。"""
    peers = [p for p in PEERS if p["symbol"] != "sh600519"]
    body = _call_peers(_repo(peers=peers))
    assert body["code"] == 0
    assert body["data"]["target"] is None
    assert "note" in body["data"]


def test_routes_registered_once():
    """路径存在且各注册一次——router 遮蔽教训（b661566）。"""
    from src.api.router.financial_router import router
    paths = [r.path for r in router.routes]
    assert paths.count("/financial/industry-members/{symbol}") == 1
    assert paths.count("/financial/industry-peers/{symbol}") == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_industry_peers.py -q`
Expected: FAIL——`ImportError: cannot import name 'industry_members'`

- [ ] **Step 3: 写 handler（追加到 `financial_detail_handler.py` 末尾）**

```python
def industry_members(symbol: str) -> Any:
    """个股申万行业归属（波特五力行业分析的数据入口，课程 14 集）。"""
    from src.infra.database.market.sw_industry import (
        create_sw_industry_repository,
    )
    try:
        repo = create_sw_industry_repository()
        m = repo.get_member(symbol)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not m:
        return responses.error(f"{symbol} 无申万行业归属（非 A 股成分或未同步）")
    return responses.success({
        "symbol": symbol,
        "sw_l1": {"code": m["sw_code_l1"], "name": m["sw_name_l1"]},
        "sw_l2": {"code": m["sw_code_l2"], "name": m["sw_name_l2"]},
        "weight": m.get("weight"),
        "included_date": m.get("included_date"),
    })


def industry_peers(symbol: str, level: int = 2, limit: int = 13) -> Any:
    """同行截面：行业归属 + 截面时序 + 同行明细 + 目标股相对位置。

    level 默认 2（二级）；最新期 sample_count < 8 自动降一级并在
    industry.degraded/note 标注。sections 降序截 limit 期；
    同行明细仅最新期（实时 JOIN，毫秒级）。
    """
    from src.domain.market.fundamental.industry_cross_section import (
        peer_ranks,
    )
    from src.infra.database.market.sw_industry import (
        create_sw_industry_repository,
    )
    try:
        repo = create_sw_industry_repository()
        m = repo.get_member(symbol)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not m:
        return responses.error(f"{symbol} 无申万行业归属（非 A 股成分或未同步）")

    sw_code = m["sw_code_l2"] if level == 2 else m["sw_code_l1"]
    degraded, note = False, None
    try:
        sections = repo.fetch_sections(sw_code, level, limit=200)
        if level == 2 and sections and \
                (sections[0].get("sample_count") or 0) < 8:
            level, sw_code = 1, m["sw_code_l1"]
            degraded, note = True, "二级样本不足，已降为一级行业"
            sections = repo.fetch_sections(sw_code, 1, limit=200)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not sections:
        return responses.error("行业截面数据未同步，请先运行 "
                               "sw_industry_cross_section_sync")

    latest = sections[0]["report_date"]
    try:
        peers = repo.fetch_peer_details(sw_code, level, latest)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")

    ranked = peer_ranks(peers, symbol)
    data = {
        "symbol": symbol,
        "industry": {
            "level": level, "code": sw_code,
            "name": sections[0].get("sw_name"),
            "parent": (
                {"code": m["sw_code_l1"], "name": m["sw_name_l1"]}
                if level == 2 else None
            ),
            "degraded": degraded, "note": note,
        },
        "sections": sections[:limit],
        "peers": ranked["peers"],
        "target": ranked["target"],
    }
    if ranked["target"] is None:
        data["note"] = "目标股有归属但最新期无财务数据"
    return responses.success(data)
```

- [ ] **Step 4: 注册路由（`financial_router.py`，`_ratio_analysis` 块之后追加）**

```python
@router.get("/industry-members/{symbol}")
def _industry_members(symbol: str):
    """个股申万行业归属（一级/二级 + 权重 + 计入日期）。"""
    return industry_members(symbol)


@router.get("/industry-peers/{symbol}")
def _industry_peers(
    symbol: str,
    level: int = Query(2, ge=1, le=2, description="2=申万二级(默认);1=一级"),
    limit: int = Query(13, ge=1, le=40, description="截面时序返回期数"),
):
    """同行截面：截面时序（CR4/HHI/分布）+ 同行明细 + 目标股分位。

    五力分析（课程 14 集）的数据底座；独立路径，与既有
    /industry-valuation-snapshot 无冲突。
    """
    return industry_peers(symbol, level, limit)
```

同时在 `financial_router.py` 的 handler 导入块（L724 起，`from src.api.handler.financial_detail_handler import (`）内、`ratios,` 行之后追加两行：

```python
    industry_members,
    industry_peers,
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_industry_peers.py -q`
Expected: PASS（7 passed）

- [ ] **Step 6: 全部新增测试回归**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_industry_cross_section.py tests/domain/market/sync/test_sw_industry_member_sync.py tests/domain/market/sync/test_sw_industry_cross_section_sync.py tests/api/test_industry_peers.py -q`
Expected: PASS（27 passed = 14 纯函数 + 2 job1 + 4 job2 + 7 API）

- [ ] **Step 7: 冒烟（真库）**

Run: `cd backend && uv run python -c "
from src.api.handler.financial_detail_handler import industry_peers
import json
body = industry_peers('sh600519')
d = json.loads(body.body)['data']
print(d['industry']['name'], '| 最新期', d['sections'][0]['report_date'],
      '| CR4', d['sections'][0]['cr4'], '| 同行', len(d['peers']), '家',
      '| 毛利率分位', d['target']['percentile_gross_margin'])
"`
Expected: `白酒Ⅱ | 最新期 2025-12-31 | CR4 >0.5 | 同行 ~110 家 | 毛利率分位 ≈1.0`

- [ ] **Step 8: Commit**

```bash
git add src/api/handler/financial_detail_handler.py src/api/router/financial_router.py tests/api/test_industry_peers.py
git commit -m "feat(sw-industry): industry-members/industry-peers两端点——归属查询+四块同行截面;二级样本<8自动降级;路由注册回归"
```

---

### Task 7: 调度接入 + 全量验证

**Files:**
- Modify: `src/infra/scheduler.py`（`_run_financial_full_weekly` 的 `sched.add_job` 块之后追加）

**Interfaces:**
- Consumes: Task 4/5 的 `sw_industry_member_sync.run` / `sw_industry_cross_section_sync.run`。
- Produces: 每周自动同步（无代码接口消费，运维性质）。

- [ ] **Step 1: 追加调度块**

在 `setup_scheduler()` 内、`financial_full_weekly` 的 `add_job` 块之后（`# ── 业绩预告/快报增量` 注释之前）插入：

```python
    # ── 申万行业成分股 + 行业截面（每周六 04:00，先成分后截面）─────────
    def _run_sw_industry_weekly():
        from src.domain.market.sync.jobs import (
            sw_industry_cross_section_sync,
            sw_industry_member_sync,
        )
        try:
            r1 = sw_industry_member_sync.run()
            r2 = sw_industry_cross_section_sync.run()
            log.info(
                "[SW_INDUSTRY_WEEKLY] members=%d industries=%d sections=%d",
                r1.get("members", 0), r1.get("industries", 0),
                r2.get("sections", 0),
            )
        except Exception as e:  # noqa: BLE001
            log.error("[SW_INDUSTRY_WEEKLY] failed: %s", e)

    sched.add_job(
        _run_sw_industry_weekly,
        CronTrigger(day_of_week="sat", hour=4, minute=0,
                    timezone="Asia/Shanghai"),
        id="sw_industry_weekly",
        name="申万行业成分股与截面同步",
        replace_existing=True,
        misfire_grace_time=14400,
        max_instances=1,
        coalesce=True,
    )
```

（`log` 为该文件 L18 既有 logger：`log = logging.getLogger(__name__)`，直接使用。）

- [ ] **Step 2: 语法与导入验证**

Run: `cd backend && uv run python -c "import src.infra.scheduler; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 全部新增测试最终回归**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_industry_cross_section.py tests/domain/market/sync/test_sw_industry_member_sync.py tests/domain/market/sync/test_sw_industry_cross_section_sync.py tests/api/test_industry_peers.py -q`
Expected: 全 PASS（27 passed）

- [ ] **Step 4: spec 验证清单逐项确认（真库）**

```bash
cd backend && uv run python -c "
from src.infra.database.market.sw_industry import create_sw_industry_repository
repo = create_sw_industry_repository()
# 1) 茅台归属白酒II（真实代码 801125——Task 4 真跑验证的映射）
m = repo.get_member('sh600519'); assert m and m['sw_code_l2'] == '801125', m
# 2) 截面含 2016-2025 年报期
secs = repo.fetch_sections('801125', 2, limit=200)
years = {s['report_date'][:4] for s in secs if s['report_date'].endswith('12-31')}
assert {'2016', '2020', '2025'} <= years, years
# 3) 白酒 CR4 > 0.5
latest = secs[0]; assert latest['cr4'] and latest['cr4'] > 0.5, latest
print('spec 验证清单全过: 归属/回溯期/CR4')
"
```
Expected: `spec 验证清单全过: 归属/回溯期/CR4`

- [ ] **Step 5: Commit**

```bash
git add src/infra/scheduler.py
git commit -m "feat(sw-industry): 周度调度接入——周六04:00先成分后截面;财务full同步错峰1小时"
```

---

## 收尾

- 本计划完成后**不做前端**、**不做五力评分**（子项目2 另开 spec：`五力分析模块 + Financial 页 Tab`，消费 `/financial/industry-peers`）。
- 执行中发现 spec 口径与实现冲突时，以 spec 为准并回报；spec 本身的修订需单独提交 `docs(spec)` commit。
