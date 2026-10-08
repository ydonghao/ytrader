# 持仓论点体系（卖出体检 + 财报联动重估）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-09-27-thesis-sell-system-design.md`：论点即持仓（4 张新表）、四区卖出体检、财报联动每日重估 job、前端持仓体检页 + 预警中心分区。

**Architecture:** 后端 DDD 四层：纯函数 `domain/market/fundamental/thesis_monitor.py` + 业务服务 `domain/market/thesis/service.py` → SQLModel 表/仓库 `infra/database/portfolio/thesis_models.py` + `thesis_repository.py` → handler+router `api/handler/thesis_handler.py` + `api/router/thesis_router.py` → APScheduler 17:35 job。前端单页 master-detail `pages/Thesis.tsx`。

**Tech Stack:** FastAPI + SQLModel（无 Alembic，main.py import 建表）+ APScheduler + React/TS（RSBuild）。

## Global Constraints

- operator 取值 `">=" / ">" / "<=" / "<"`（对齐 `evaluate_thesis` 原实现；spec 中 gt/lt 的表述随 Task 10 修订）。
- 后端格式：`black + isort, line-length 79`；handler 返回 `src.pkg.responses.success`。
- 前端：A股红涨绿跌；复用 `getApiBase()`（`../lib/api`）、`PageHeader/StateView`（`../components/ui`）、`StockSearch`。
- 每 Task 一个 commit；测试命令统一 `cd backend && .venv/bin/python -m pytest <path> -v`。
- DB 里 JSON 字段用 `sa_column=Column(JSON)`（sqlite 测试可跑）。

---

### Task 1: 搬迁 evaluate_thesis 到 thesis_monitor.py

**Files:**
- Create: `backend/src/domain/market/fundamental/thesis_monitor.py`
- Modify: `backend/src/domain/market/portfolio/course_allocation.py`（3.7 节改为 re-export）
- Test: `backend/tests/domain/test_thesis_monitor.py`

**Interfaces:**
- Produces: `ThesisCondition(metric, operator, threshold, label="")`、`ThesisMonitorResult(breached, held, recommend_sell)`、`evaluate_thesis(conditions: list[ThesisCondition], current_metrics: dict) -> ThesisMonitorResult`

- [ ] **Step 1: 写失败测试**

```python
"""thesis_monitor 纯函数测试：evaluate_thesis 搬迁后行为不变。"""
from src.domain.market.fundamental.thesis_monitor import (
    ThesisCondition,
    evaluate_thesis,
)


def _cond(metric, op, thr):
    return ThesisCondition(metric=metric, operator=op, threshold=thr)


def test_all_held():
    r = evaluate_thesis(
        [_cond("roe", ">=", 15), _cond("debt_ratio", "<=", 60)],
        {"roe": 18.0, "debt_ratio": 50.0},
    )
    assert r.breached == [] and len(r.held) == 2
    assert r.recommend_sell is False


def test_any_breach_recommends_sell():
    r = evaluate_thesis(
        [_cond("roe", ">=", 15), _cond("debt_ratio", "<=", 60)],
        {"roe": 12.0, "debt_ratio": 50.0},
    )
    assert len(r.breached) == 1 and r.breached[0].metric == "roe"
    assert r.recommend_sell is True


def test_missing_metric_is_held_not_breached():
    r = evaluate_thesis([_cond("roe", ">=", 15)], {"debt_ratio": 50.0})
    assert r.breached == [] and len(r.held) == 1
    assert r.recommend_sell is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_monitor.py -v`
Expected: FAIL（ModuleNotFoundError: thesis_monitor）

- [ ] **Step 3: 实现——从 course_allocation.py 剪切 3.7 节到新模块**

`backend/src/domain/market/fundamental/thesis_monitor.py`：

```python
"""论点监控纯函数（课程 3.7 买卖一致性：论点破即卖）。

自 portfolio/course_allocation.py 搬迁（2026-09-27），course_allocation
原位 re-export 保持兼容。本模块后续承载 METRIC_REGISTRY / 卖出体检 /
重估 verdict 等持仓论点体系纯函数。
"""
from dataclasses import dataclass, field


@dataclass
class ThesisCondition:
    """单条量化入场论点（用于论点破即卖）。"""

    metric: str          # 指标名（与 current_metrics 字典 key 对齐）
    operator: str        # ">=" / ">" / "<=" / "<" / "=="
    threshold: float
    label: str = ""


@dataclass
class ThesisMonitorResult:
    """论点监控结果。"""

    breached: list = field(default_factory=list)
    held: list = field(default_factory=list)
    recommend_sell: bool = False


_OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def evaluate_thesis(conditions: list, current_metrics: dict):
    """任一条件破 → recommend_sell；无法评估（缺值/类型错）视为暂未破。"""
    res = ThesisMonitorResult()
    for c in conditions:
        op = _OPS.get(c.operator)
        v = current_metrics.get(c.metric)
        if op is None or v is None:
            res.held.append(c)
            continue
        try:
            ok = op(v, c.threshold)
        except TypeError:
            res.held.append(c)
            continue
        (res.held if ok else res.breached).append(c)
    res.recommend_sell = len(res.breached) > 0
    return res
```

course_allocation.py：删除 3.7 节的三个定义，在文件 imports 之后加：

```python
from src.domain.market.fundamental.thesis_monitor import (  # noqa: F401
    ThesisCondition,
    ThesisMonitorResult,
    evaluate_thesis,
)
```

- [ ] **Step 4: 跑测试 + 既有 course 测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_monitor.py tests/domain/test_course_builder.py tests/domain/test_course_review.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/thesis_monitor.py backend/src/domain/market/portfolio/course_allocation.py backend/tests/domain/test_thesis_monitor.py
git commit -m "feat(thesis): evaluate_thesis搬迁至fundamental/thesis_monitor+兼容re-export"
```

---

### Task 2: METRIC_REGISTRY + compute_metric_values + reeval_verdict + check_price_band

**Files:**
- Modify: `backend/src/domain/market/fundamental/thesis_monitor.py`
- Test: `backend/tests/domain/test_thesis_monitor.py`（追加）

**Interfaces:**
- Consumes: Task 1 的模块。
- Produces:
  - `METRIC_REGISTRY: dict[str, dict]`（9 个 metric_key）
  - `compute_metric_values(assembled: dict) -> dict[str, float]`，assembled 键：`roe, revenue, revenue_prev, net_profit, net_profit_prev, ocf, net_profit_any, gross_margin, total_assets, total_liabilities, pe_ttm, pb, dv_ttm`（值可缺）
  - `reeval_verdict(quality_now: dict|None, quality_base: dict|None, conditions_result: list[dict]) -> str`，返回 `pass/review/sell_signal`
  - `check_price_band(band: dict|None, price: float|None, metrics: dict) -> dict`，返回 `{metric, current, low, high, reached}`，reached 为 None 表示无法评估

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/domain/test_thesis_monitor.py
from src.domain.market.fundamental.thesis_monitor import (
    METRIC_REGISTRY,
    check_price_band,
    compute_metric_values,
    reeval_verdict,
)


def test_registry_has_nine_metrics():
    assert set(METRIC_REGISTRY) == {
        "roe", "revenue_yoy", "net_profit_yoy", "gross_margin",
        "ocf_ratio", "debt_ratio", "pe_ttm", "pb", "dv_ttm",
    }


def test_compute_metric_values_full():
    v = compute_metric_values({
        "net_profit": 100.0, "equity": 500.0,
        "revenue": 1200.0, "revenue_prev": 1000.0,
        "net_profit_prev": 80.0,
        "ocf": 90.0, "gross_margin": 30.0,
        "total_assets": 900.0, "total_liabilities": 450.0,
        "pe_ttm": 12.0, "pb": 1.5, "dv_ttm": 3.0,
    })
    assert v["roe"] == 20.0            # 100/500*100
    assert v["revenue_yoy"] == 20.0    # (1200-1000)/1000*100
    assert v["net_profit_yoy"] == 25.0
    assert v["ocf_ratio"] == 0.9       # ocf/net_profit
    assert v["debt_ratio"] == 50.0     # 负债/资产*100
    assert v["gross_margin"] == 30.0
    assert v["pe_ttm"] == 12.0 and v["pb"] == 1.5 and v["dv_ttm"] == 3.0


def test_compute_metric_values_skips_missing():
    v = compute_metric_values({"revenue": 100.0})
    assert v == {"revenue_yoy": None} or "revenue_yoy" not in v


def test_verdict_condition_breach_is_sell_signal():
    cr = [{"status": "breached"}]
    assert reeval_verdict({"score": 80}, {"score": 80}, cr) == "sell_signal"


def test_verdict_eliminate_is_sell_signal():
    assert reeval_verdict(
        {"score": 30, "verdict": "eliminate"}, {"score": 80}, []
    ) == "sell_signal"


def test_verdict_score_drop_is_review():
    assert reeval_verdict({"score": 60}, {"score": 80}, []) == "review"


def test_verdict_new_red_flag_is_review():
    assert reeval_verdict(
        {"score": 80, "red_flags": ["a"]}, {"score": 80, "red_flags": []}, []
    ) == "review"


def test_verdict_pass():
    assert reeval_verdict({"score": 80}, {"score": 80}, []) == "pass"


def test_verdict_no_base_quality_is_pass():
    assert reeval_verdict({"score": 50}, None, []) == "pass"


def test_band_price_reached():
    r = check_price_band({"metric": "price", "low": 40, "high": 50}, 51.0, {})
    assert r == {"metric": "price", "current": 51.0, "low": 40, "high": 50,
                 "reached": True}


def test_band_pe_not_reached():
    r = check_price_band(
        {"metric": "pe_ttm", "low": 20, "high": 30}, None, {"pe_ttm": 15.0}
    )
    assert r["reached"] is False and r["current"] == 15.0


def test_band_missing_current_is_unknown():
    r = check_price_band({"metric": "pb", "low": 2, "high": 3}, None, {})
    assert r["reached"] is None


def test_band_none_is_unknown():
    assert check_price_band(None, 10.0, {})["reached"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_monitor.py -v`
Expected: 新增用例 FAIL（ImportError）

- [ ] **Step 3: 实现（追加到 thesis_monitor.py）**

```python
# ── 论点指标注册表与派生计算 ──────────────────────────────────────────

METRIC_REGISTRY: dict = {
    "roe":           {"label": "ROE",            "unit": "%"},
    "revenue_yoy":   {"label": "营收同比",        "unit": "%"},
    "net_profit_yoy": {"label": "净利同比",       "unit": "%"},
    "gross_margin":  {"label": "毛利率",          "unit": "%"},
    "ocf_ratio":     {"label": "经营现金流/净利润", "unit": "x"},
    "debt_ratio":    {"label": "资产负债率",      "unit": "%"},
    "pe_ttm":        {"label": "PE(TTM)",         "unit": "x"},
    "pb":            {"label": "PB",              "unit": "x"},
    "dv_ttm":        {"label": "股息率",          "unit": "%"},
}


def _yoy(now, prev):
    if now is None or prev in (None, 0):
        return None
    return (now - prev) / abs(prev) * 100.0


def compute_metric_values(assembled: dict) -> dict:
    """从装配字典计算 METRIC_REGISTRY 全部指标；缺数据的键输出 None。"""
    np_ = assembled.get("net_profit")
    eq = assembled.get("equity")
    ta = assembled.get("total_assets")
    tl = assembled.get("total_liabilities")
    return {
        "roe": (np_ / eq * 100.0) if np_ and eq else None,
        "revenue_yoy": _yoy(assembled.get("revenue"),
                            assembled.get("revenue_prev")),
        "net_profit_yoy": _yoy(np_, assembled.get("net_profit_prev")),
        "gross_margin": assembled.get("gross_margin"),
        "ocf_ratio": (assembled.get("ocf") / np_)
        if assembled.get("ocf") and np_ else None,
        "debt_ratio": (tl / ta * 100.0) if tl and ta else None,
        "pe_ttm": assembled.get("pe_ttm"),
        "pb": assembled.get("pb"),
        "dv_ttm": assembled.get("dv_ttm"),
    }


def reeval_verdict(quality_now, quality_base, conditions_result) -> str:
    """重估三档：条件破/质量淘汰→sell_signal；降分>10或新红旗→review。"""
    if any(c.get("status") == "breached" for c in conditions_result):
        return "sell_signal"
    if quality_now and quality_now.get("verdict") == "eliminate":
        return "sell_signal"
    if quality_now and quality_base:
        drop = (quality_base.get("score") or 0) - (
            quality_now.get("score") or 0
        )
        if drop > 10:
            return "review"
        base_flags = set(quality_base.get("red_flags") or [])
        now_flags = set(quality_now.get("red_flags") or [])
        if now_flags - base_flags:
            return "review"
    return "pass"


def check_price_band(band, price, metrics) -> dict:
    """估值带到价检测；reached=None 表示无法评估（band 空或缺现值）。"""
    if not band:
        return {"metric": None, "current": None, "low": None,
                "high": None, "reached": None}
    metric = band.get("metric") or "price"
    current = price if metric == "price" else metrics.get(metric)
    low, high = band.get("low"), band.get("high")
    reached = None
    if current is not None and low is not None and high is not None:
        reached = current >= high or current <= low
    return {"metric": metric, "current": current, "low": low,
            "high": high, "reached": reached}
```

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_monitor.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/thesis_monitor.py backend/tests/domain/test_thesis_monitor.py
git commit -m "feat(thesis): METRIC_REGISTRY/compute_metric_values/reeval_verdict/check_price_band纯函数"
```

---

### Task 3: build_sell_check 四区报告纯组装

**Files:**
- Modify: `backend/src/domain/market/fundamental/thesis_monitor.py`
- Test: `backend/tests/domain/test_thesis_monitor.py`（追加）

**Interfaces:**
- Consumes: Task 1/2 的函数。
- Produces: `build_sell_check(thesis: dict, conditions: list[dict], current_metrics: dict, band_result: dict|None, snapshot: dict|None, valuation_now: dict|None, quality_now: dict|None, now=None) -> dict`，返回 `{sections: {thesis, valuation, fundamentals, decision}, recommend_sell, stale_days}`

- [ ] **Step 1: 追加失败测试**

```python
import datetime as dt
from src.domain.market.fundamental.thesis_monitor import build_sell_check


def _base_inputs():
    thesis = {
        "buy_date": "2026-01-10", "buy_price": 30.0,
        "last_reviewed_at": dt.datetime.now() - dt.timedelta(days=100),
        "decision": None,
        "target_band": {"metric": "price", "low": 40, "high": 50},
        "thesis_text": "ROE 持续>15",
    }
    conditions = [
        {"id": 1, "metric_key": "roe", "operator": ">=",
         "threshold": 15.0, "label": "ROE>=15"},
    ]
    return thesis, conditions


def test_sell_check_sections_present():
    thesis, conditions = _base_inputs()
    r = build_sell_check(
        thesis, conditions, {"roe": 18.0},
        {"metric": "price", "current": 45.0, "low": 40, "high": 50,
         "reached": True},
        {"date": "2026-01-10", "price": 30.0,
         "quality": {"score": 80, "verdict": "pass", "red_flag_count": 0},
         "valuation": {"dcf_fair": 35.0}},
        {"price": 45.0, "dcf_fair": 42.0},
        {"score": 75, "verdict": "pass", "red_flags": []},
    )
    assert set(r["sections"]) == {
        "thesis", "valuation", "fundamentals", "decision"
    }
    assert r["recommend_sell"] is False
    assert r["sections"]["thesis"]["items"][0]["status"] == "holding"
    assert r["sections"]["valuation"]["band"]["reached"] is True
    # 安全边际消耗: 登记时价30 vs dcf35 → +16.7%; 现在45 vs42 → +7.1%
    assert r["sections"]["valuation"]["margin_consumed"] > 0
    assert r["sections"]["fundamentals"]["score_diff"] == -5
    assert r["stale_days"] >= 100


def test_sell_check_breach_flags_recommend_sell():
    thesis, conditions = _base_inputs()
    r = build_sell_check(thesis, conditions, {"roe": 10.0},
                         None, None, None, None)
    assert r["recommend_sell"] is True
    assert r["sections"]["thesis"]["items"][0]["status"] == "breached"


def test_sell_check_missing_metric_is_unknown():
    thesis, conditions = _base_inputs()
    r = build_sell_check(thesis, conditions, {}, None, None, None, None)
    assert r["sections"]["thesis"]["items"][0]["status"] == "unknown"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_monitor.py -v`
Expected: 新增 FAIL（ImportError build_sell_check）

- [ ] **Step 3: 实现（追加）**

```python
def _margin(price, fair):
    if not price or not fair:
        return None
    return (price / fair - 1.0) * 100.0


def build_sell_check(
    thesis, conditions, current_metrics, band_result=None,
    snapshot=None, valuation_now=None, quality_now=None, now=None,
):
    """四区卖出体检纯组装。数据装配由 handler/service 注入。"""
    now = now or dt.datetime.now()
    last = thesis.get("last_reviewed_at")
    if isinstance(last, str):
        last = dt.datetime.fromisoformat(last)
    stale_days = (now - last).days if last else None

    eval_conditions = [
        ThesisCondition(
            metric=c["metric_key"], operator=c["operator"],
            threshold=c["threshold"], label=c.get("label", ""),
        )
        for c in conditions
    ]
    res = evaluate_thesis(eval_conditions, current_metrics)
    breached_keys = {id(c) for c in res.breached}
    cond_by_key = {
        (c["metric_key"], c["operator"], c["threshold"]): c
        for c in conditions
    }
    items = []
    for ec in (res.breached + res.held):
        base = cond_by_key.get(
            (ec.metric, ec.operator, ec.threshold), {}
        )
        items.append({
            "id": base.get("id"),
            "metric_key": ec.metric,
            "label": base.get("label") or ec.label
            or METRIC_REGISTRY.get(ec.metric, {}).get("label", ec.metric),
            "operator": ec.operator,
            "threshold": ec.threshold,
            "current": current_metrics.get(ec.metric),
            "status": "breached" if id(ec) in breached_keys
            else ("unknown" if current_metrics.get(ec.metric) is None
                  else "holding"),
        })

    snap_val = (snapshot or {}).get("valuation") or {}
    margin_then = _margin((snapshot or {}).get("price"),
                          snap_val.get("dcf_fair"))
    margin_now = _margin(
        (valuation_now or {}).get("price"),
        (valuation_now or {}).get("dcf_fair"),
    )
    margin_consumed = (
        margin_then - margin_now
        if margin_then is not None and margin_now is not None else None
    )
    snap_q = (snapshot or {}).get("quality") or {}
    score_diff = (
        (quality_now or {}).get("score", 0) - snap_q.get("score", 0)
        if quality_now and snap_q else None
    )
    new_flags = list(
        set((quality_now or {}).get("red_flags") or [])
        - set(snap_q.get("red_flags") or [])
    )

    return {
        "sections": {
            "thesis": {
                "title": "论点体检",
                "items": items,
                "recommend_sell": res.recommend_sell,
                "stale": bool(stale_days is not None and stale_days > 90),
            },
            "valuation": {
                "title": "估值到位",
                "band": band_result
                or {"metric": None, "current": None, "low": None,
                    "high": None, "reached": None},
                "margin_then": margin_then,
                "margin_now": margin_now,
                "margin_consumed": margin_consumed,
                "valuation_now": valuation_now,
            },
            "fundamentals": {
                "title": "基本面变化",
                "quality_now": quality_now,
                "quality_then": snap_q or None,
                "score_diff": score_diff,
                "new_red_flags": new_flags,
            },
            "decision": {
                "title": "卖出决策",
                "questions": [
                    "买入逻辑是否已被证伪？",
                    "估值是否到达目标卖出区间？",
                    "是否有明显更优的替代标的？",
                ],
                "decision": thesis.get("decision"),
                "decision_note": thesis.get("decision_note"),
            },
        },
        "recommend_sell": res.recommend_sell,
        "stale_days": stale_days,
    }
```

文件顶部补 `import datetime as dt`。

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_monitor.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/thesis_monitor.py backend/tests/domain/test_thesis_monitor.py
git commit -m "feat(thesis): build_sell_check四区卖出体检纯组装"
```

---

### Task 4: 4 张表 + Repository + main.py 注册

**Files:**
- Create: `backend/src/infra/database/portfolio/thesis_models.py`
- Create: `backend/src/infra/database/portfolio/thesis_repository.py`
- Modify: `backend/main.py`（lifespan 建表 import 区 + router 注册区）
- Test: `backend/tests/infra/test_thesis_repository.py`

**Interfaces:**
- Produces:
  - 表类 `InvestmentThesis / ThesisCondition / ThesisReeval / ThesisEvent`（字段见 spec §3）
  - `ThesisRepository(db)`：`create_thesis(data)->int`、`list_theses(status=None)->list[dict]`、`get_thesis(id)->dict|None`、`update_thesis(id, **fields)`、`close_thesis(id, reason, price)`、`replace_conditions(thesis_id, items:list[dict])`、`list_conditions(thesis_id)->list[dict]`、`add_reeval(row:dict)->int`、`list_reevals(thesis_id)->list[dict]`、`latest_reeval_report_date(thesis_id)->date|None`、`add_event(thesis_id, kind, detail)->int`、`list_events(unread_only=False)->list[dict]`、`mark_event_read(id)`、`has_band_event(thesis_id, band_key)->bool`、`latest_close(symbols)->dict`、`latest_report_dates(symbols)->dict`、`latest_earnings_dates(symbols)->dict`
  - `create_thesis_repository()` 工厂

- [ ] **Step 1: 写失败测试（sqlite 内存）**

```python
"""thesis_repository CRUD 测试（sqlite 内存）。"""
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from src.infra.database.portfolio.thesis_models import (
    InvestmentThesis, ThesisCondition, ThesisEvent, ThesisReeval,
)
from src.infra.database.portfolio.thesis_repository import (
    ThesisRepository,
)


class _SqliteDb:
    """仅提供 session_scope 的 DBConnection 替身。"""

    def __init__(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(
            self.engine,
            tables=[
                InvestmentThesis.__table__, ThesisCondition.__table__,
                ThesisReeval.__table__, ThesisEvent.__table__,
            ],
        )

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as s:
            yield s


@pytest.fixture()
def repo():
    return ThesisRepository(_SqliteDb())


def test_thesis_crud_and_close(repo):
    tid = repo.create_thesis({
        "symbol": "sh600519", "thesis_text": "高端白酒护城河",
        "buy_date": dt.date(2026, 1, 10), "buy_price": 1500.0,
        "shares": 100,
        "snapshot": {"price": 1500.0},
        "target_band": {"metric": "pe_ttm", "low": 25, "high": 35},
    })
    assert tid > 0
    theses = repo.list_theses(status="active")
    assert len(theses) == 1 and theses[0]["symbol"] == "sh600519"
    repo.update_thesis(tid, decision="hold", decision_note="持有")
    assert repo.get_thesis(tid)["decision"] == "hold"
    repo.close_thesis(tid, reason="valuation_reached", price=2100.0)
    assert repo.get_thesis(tid)["status"] == "closed"
    assert repo.list_theses(status="active") == []
    assert len(repo.list_theses(status="closed")) == 1


def test_conditions_replace(repo):
    tid = repo.create_thesis({"symbol": "sz000001"})
    repo.replace_conditions(tid, [
        {"metric_key": "roe", "operator": ">=", "threshold": 15,
         "label": "ROE>=15"},
    ])
    assert len(repo.list_conditions(tid)) == 1
    repo.replace_conditions(tid, [
        {"metric_key": "roe", "operator": ">=", "threshold": 12,
         "label": "ROE>=12"},
        {"metric_key": "debt_ratio", "operator": "<=", "threshold": 60,
         "label": "负债率<=60"},
    ])
    conds = repo.list_conditions(tid)
    assert len(conds) == 2 and conds[0]["threshold"] == 12


def test_reeval_unique_and_latest(repo):
    tid = repo.create_thesis({"symbol": "sh600519"})
    repo.add_reeval({
        "thesis_id": tid, "report_date": dt.date(2026, 6, 30),
        "trigger": "formal", "quality_now": {"score": 80},
        "verdict": "pass",
    })
    dup = repo.add_reeval({
        "thesis_id": tid, "report_date": dt.date(2026, 6, 30),
        "trigger": "formal", "quality_now": {"score": 80},
        "verdict": "pass",
    })
    assert dup is None  # 幂等：同 thesis+report_date+trigger 不重复
    assert len(repo.list_reevals(tid)) == 1
    assert repo.latest_reeval_report_date(tid) == dt.date(2026, 6, 30)


def test_events_read_and_band_dedup(repo):
    tid = repo.create_thesis({"symbol": "sh600519"})
    repo.add_event(tid, "price_band_reached",
                   {"band": "pe_ttm:25:35", "alerted": True})
    assert repo.has_band_event(tid, "pe_ttm:25:35") is True
    assert repo.has_band_event(tid, "pe_ttm:30:40") is False
    evs = repo.list_events(unread_only=True)
    assert len(evs) == 1 and evs[0]["read"] is False
    repo.mark_event_read(evs[0]["id"])
    assert repo.list_events(unread_only=True) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/test_thesis_repository.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现表与仓库**

`thesis_models.py`：

```python
"""持仓论点体系 SQLModel 表（spec 2026-09-27 §3）。

4 张表：investment_thesis / thesis_condition / thesis_reeval /
thesis_event。main.py lifespan import 建表（无 Alembic 惯例）。
"""
import datetime as dt
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class InvestmentThesis(SQLModel, table=True):
    """论点 = 持仓登记（持有 = 论点未破）。"""

    __tablename__ = "investment_thesis"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)              # sh600519
    status: str = Field(default="active")        # active|closed
    buy_date: Optional[dt.date] = None
    buy_price: Optional[float] = None
    shares: Optional[int] = None
    thesis_text: str = ""
    snapshot: Any = Field(default=None, sa_column=Column(JSON))
    target_band: Any = Field(default=None, sa_column=Column(JSON))
    decision: Optional[str] = None               # hold|reduce|sell
    decision_note: Optional[str] = None
    decision_at: Optional[datetime] = None
    last_reviewed_at: Optional[datetime] = None
    close_reason: Optional[str] = None
    close_price: Optional[float] = None
    closed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ThesisCondition(SQLModel, table=True):
    """假设条件（论点破即卖）。operator ∈ >= > <= <。"""

    __tablename__ = "thesis_condition"

    id: Optional[int] = Field(default=None, primary_key=True)
    thesis_id: int = Field(
        foreign_key="investment_thesis.id", index=True
    )
    metric_key: str
    operator: str
    threshold: float
    label: str = ""
    status: str = "holding"                      # holding|breached|unknown
    breached_at: Optional[datetime] = None


class ThesisReeval(SQLModel, table=True):
    """财报联动重估历史（thesis+report_date+trigger 唯一，幂等）。"""

    __tablename__ = "thesis_reeval"
    __table_args__ = (
        UniqueConstraint(
            "thesis_id", "report_date", "trigger",
            name="uq_thesis_reeval",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    thesis_id: int = Field(
        foreign_key="investment_thesis.id", index=True
    )
    report_date: Optional[dt.date] = None
    trigger: str                                 # formal|express|preannounce|price_band|manual
    quality_now: Any = Field(default=None, sa_column=Column(JSON))
    quality_delta: Any = Field(default=None, sa_column=Column(JSON))
    valuation_now: Any = Field(default=None, sa_column=Column(JSON))
    conditions_result: Any = Field(default=None, sa_column=Column(JSON))
    verdict: str = "pass"                        # pass|review|sell_signal
    created_at: datetime = Field(default_factory=datetime.now)


class ThesisEvent(SQLModel, table=True):
    """轻事件表（预警中心"持仓论点"分区数据源）。"""

    __tablename__ = "thesis_event"

    id: Optional[int] = Field(default=None, primary_key=True)
    thesis_id: int = Field(
        foreign_key="investment_thesis.id", index=True
    )
    kind: str        # reeval_done|condition_breached|price_band_reached
    detail: Any = Field(default=None, sa_column=Column(JSON))
    read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)
```

`thesis_repository.py`：

```python
"""持仓论点 repository：4 表 CRUD + 收盘价/新报告检测查询。"""
import datetime as dt
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlmodel import select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

from .thesis_models import (
    InvestmentThesis,
    ThesisCondition,
    ThesisEvent,
    ThesisReeval,
)


def _thesis_dict(t: InvestmentThesis) -> dict:
    return {
        "id": t.id, "symbol": t.symbol, "status": t.status,
        "buy_date": t.buy_date.isoformat() if t.buy_date else None,
        "buy_price": t.buy_price, "shares": t.shares,
        "thesis_text": t.thesis_text, "snapshot": t.snapshot,
        "target_band": t.target_band, "decision": t.decision,
        "decision_note": t.decision_note,
        "decision_at": t.decision_at.isoformat()
        if t.decision_at else None,
        "last_reviewed_at": t.last_reviewed_at.isoformat()
        if t.last_reviewed_at else None,
        "close_reason": t.close_reason, "close_price": t.close_price,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "created_at": t.created_at.isoformat(),
    }


class ThesisRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    # ── 论点 CRUD ─────────────────────────────────────────────
    def create_thesis(self, data: dict) -> int:
        with self._db.session_scope() as s:
            t = InvestmentThesis(**data)
            s.add(t)
            s.flush()
            return t.id

    def list_theses(self, status: Optional[str] = None) -> list:
        with self._db.session_scope() as s:
            q = select(InvestmentThesis).order_by(
                InvestmentThesis.created_at.desc()
            )
            if status:
                q = q.where(InvestmentThesis.status == status)
            return [_thesis_dict(t) for t in s.exec(q).all()]

    def get_thesis(self, thesis_id: int) -> Optional[dict]:
        with self._db.session_scope() as s:
            t = s.get(InvestmentThesis, thesis_id)
            return _thesis_dict(t) if t else None

    def update_thesis(self, thesis_id: int, **fields) -> bool:
        with self._db.session_scope() as s:
            t = s.get(InvestmentThesis, thesis_id)
            if not t:
                return False
            for k, v in fields.items():
                setattr(t, k, v)
            t.updated_at = datetime.now()
            return True

    def close_thesis(self, thesis_id: int, reason: str,
                     price: Optional[float] = None) -> bool:
        return self.update_thesis(
            thesis_id, status="closed", close_reason=reason,
            close_price=price, closed_at=datetime.now(),
        )

    # ── 假设条件（整表替换） ───────────────────────────────────
    def replace_conditions(self, thesis_id: int, items: list) -> int:
        with self._db.session_scope() as s:
            olds = s.exec(
                select(ThesisCondition).where(
                    ThesisCondition.thesis_id == thesis_id
                )
            ).all()
            for o in olds:
                s.delete(o)
            for it in items:
                s.add(ThesisCondition(thesis_id=thesis_id, **it))
            return len(items)

    def list_conditions(self, thesis_id: int) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisCondition)
                .where(ThesisCondition.thesis_id == thesis_id)
                .order_by(ThesisCondition.id)
            ).all()
            return [
                {
                    "id": r.id, "thesis_id": r.thesis_id,
                    "metric_key": r.metric_key, "operator": r.operator,
                    "threshold": r.threshold, "label": r.label,
                    "status": r.status,
                    "breached_at": r.breached_at.isoformat()
                    if r.breached_at else None,
                }
                for r in rows
            ]

    def update_condition_status(self, cond_id: int, status: str) -> bool:
        with self._db.session_scope() as s:
            c = s.get(ThesisCondition, cond_id)
            if not c:
                return False
            c.status = status
            if status == "breached" and not c.breached_at:
                c.breached_at = datetime.now()
            return True

    # ── 重估历史（幂等） ───────────────────────────────────────
    def add_reeval(self, row: dict) -> Optional[int]:
        with self._db.session_scope() as s:
            exists = s.exec(
                select(ThesisReeval).where(
                    ThesisReeval.thesis_id == row["thesis_id"],
                    ThesisReeval.report_date == row.get("report_date"),
                    ThesisReeval.trigger == row["trigger"],
                )
            ).first()
            if exists:
                return None
            r = ThesisReeval(**row)
            s.add(r)
            s.flush()
            return r.id

    def list_reevals(self, thesis_id: int, limit: int = 50) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisReeval)
                .where(ThesisReeval.thesis_id == thesis_id)
                .order_by(ThesisReeval.created_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": r.id, "report_date": r.report_date.isoformat()
                    if r.report_date else None,
                    "trigger": r.trigger, "quality_now": r.quality_now,
                    "quality_delta": r.quality_delta,
                    "valuation_now": r.valuation_now,
                    "conditions_result": r.conditions_result,
                    "verdict": r.verdict,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]

    def latest_reeval_report_date(self, thesis_id: int):
        with self._db.session_scope() as s:
            r = s.exec(
                select(ThesisReeval)
                .where(ThesisReeval.thesis_id == thesis_id)
                .order_by(ThesisReeval.report_date.desc())
            ).first()
            return r.report_date if r else None

    # ── 事件 ──────────────────────────────────────────────────
    def add_event(self, thesis_id: int, kind: str,
                  detail: Optional[dict] = None) -> int:
        with self._db.session_scope() as s:
            e = ThesisEvent(
                thesis_id=thesis_id, kind=kind, detail=detail
            )
            s.add(e)
            s.flush()
            return e.id

    def list_events(self, unread_only: bool = False,
                    limit: int = 100) -> list:
        with self._db.session_scope() as s:
            q = select(ThesisEvent).order_by(
                ThesisEvent.created_at.desc()
            ).limit(limit)
            if unread_only:
                q = q.where(ThesisEvent.read == False)  # noqa: E712
            rows = s.exec(q).all()
            return [
                {
                    "id": r.id, "thesis_id": r.thesis_id, "kind": r.kind,
                    "detail": r.detail, "read": r.read,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]

    def mark_event_read(self, event_id: int) -> bool:
        with self._db.session_scope() as s:
            e = s.get(ThesisEvent, event_id)
            if not e:
                return False
            e.read = True
            return True

    def has_band_event(self, thesis_id: int, band_key: str) -> bool:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisEvent).where(
                    ThesisEvent.thesis_id == thesis_id,
                    ThesisEvent.kind == "price_band_reached",
                )
            ).all()
            return any(
                (r.detail or {}).get("band") == band_key for r in rows
            )

    # ── 行情/新报告检测（裸 SQL 表，text() 查询） ─────────────
    def latest_close(self, symbols: list) -> dict:
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT symbol, close FROM stock_ohlcv "
                    "WHERE symbol = ANY(:syms) "
                    "AND (symbol, trade_date) IN ("
                    "  SELECT symbol, MAX(trade_date) FROM stock_ohlcv "
                    "  WHERE symbol = ANY(:syms) GROUP BY symbol)"
                ),
                {"syms": symbols},
            ).all()
            return {r[0]: float(r[1]) for r in rows if r[1] is not None}

    def latest_report_dates(self, symbols: list) -> dict:
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT symbol, MAX(report_date) "
                    "FROM stock_financial_detail "
                    "WHERE symbol = ANY(:syms) GROUP BY symbol"
                ),
                {"syms": symbols},
            ).all()
            return {r[0]: r[1] for r in rows if r[0]}

    def latest_earnings_dates(self, symbols: list) -> dict:
        """{symbol: (report_date, announce_date, forecast_type)}。"""
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT DISTINCT ON (symbol) symbol, report_date, "
                    "announce_date, forecast_type "
                    "FROM stock_earnings_forecast "
                    "WHERE symbol = ANY(:syms) "
                    "ORDER BY symbol, announce_date DESC"
                ),
                {"syms": symbols},
            ).all()
            return {
                r[0]: (r[1], r[2], r[3]) for r in rows if r[0]
            }


_db_connection: DBConnection | None = None


def create_thesis_repository(
    db_connection: DBConnection | None = None,
) -> ThesisRepository:
    global _db_connection
    if db_connection is None:
        if _db_connection is None:
            _db_connection = create_db_connection(get_dsn())
        db_connection = _db_connection
    return ThesisRepository(db_connection)
```

`main.py`：lifespan 建表 import 区（course 模型 import 附近）加：

```python
from src.infra.database.portfolio.thesis_models import (  # noqa: F401
    InvestmentThesis,
    ThesisCondition,
    ThesisEvent,
    ThesisReeval,
)  # 持仓论点体系建表注册
```

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/test_thesis_repository.py -v`
Expected: 全 PASS。注意 sqlite 不支持 `ANY(:syms)`——`latest_close/latest_report_dates/latest_earnings_dates` 三个方法不在 sqlite 测试范围（服务层 mock），无需测试。

- [ ] **Step 5: Commit**

```bash
git add backend/src/infra/database/portfolio/thesis_models.py backend/src/infra/database/portfolio/thesis_repository.py backend/main.py backend/tests/infra/test_thesis_repository.py
git commit -m "feat(thesis): 4张SQLModel表+repository(幂等重估/band去重)+main建表注册"
```

---

### Task 5: 领域服务 snapshot/指标装配/重估执行

**Files:**
- Create: `backend/src/domain/market/thesis/__init__.py`（空文件）
- Create: `backend/src/domain/market/thesis/service.py`
- Test: `backend/tests/domain/test_thesis_service.py`

**Interfaces:**
- Consumes: Task 1–4 全部产物；`quality_report / dcf_valuation / ddm_valuation / asset_value_report / comps_valuation`（financial_detail_handler，均返回 `responses.success` JSONResponse）；`fetch_financial_snapshot / fetch_financial_history`（longterm/data_loader）；`create_alert_repository().get_latest_metric_value`。
- Produces:
  - `capture_snapshot(symbol) -> dict`（spec §3.5，失败源置 null）
  - `assemble_metrics(symbol) -> dict`（METRIC_REGISTRY 全键，缺=None）
  - `run_reeval(thesis_id, trigger, report_date=None) -> dict|None`（None=无新数据/幂等跳过）
  - `run_daily(today=None) -> dict`（{active, reevaluated, band_alerts}）
  - `get_band_key(band) -> str`（如 `"pe_ttm:25:35"`）

- [ ] **Step 1: 写失败测试（monkeypatch 全部 IO）**

```python
"""thesis service 测试：全部外部 IO monkeypatch，只测编排逻辑。"""
import datetime as dt

import pytest

from src.domain.market.thesis import service


class _Repo:
    def __init__(self):
        self.theses = [{
            "id": 1, "symbol": "sh600519", "status": "active",
            "buy_date": "2026-01-10", "buy_price": 1500.0,
            "shares": 100, "thesis_text": "t",
            "snapshot": {"price": 1500.0, "quality": {
                "score": 80, "verdict": "pass", "red_flags": []}},
            "target_band": {"metric": "price", "low": 2000,
                            "high": 2100},
            "decision": None, "last_reviewed_at": None,
        }]
        self.reevals = []
        self.events = []

    def list_theses(self, status=None):
        return [t for t in self.theses
                if status is None or t["status"] == status]

    def get_thesis(self, tid):
        return next((t for t in self.theses if t["id"] == tid), None)

    def list_conditions(self, tid):
        return [{"id": 11, "metric_key": "roe", "operator": ">=",
                 "threshold": 15.0, "label": ""}]

    def update_condition_status(self, cid, status):
        return True

    def update_thesis(self, tid, **f):
        self.theses[0].update(f)
        return True

    def add_reeval(self, row):
        key = (row["thesis_id"], row["report_date"], row["trigger"])
        if key in [(r["thesis_id"], r["report_date"], r["trigger"])
                   for r in self.reevals]:
            return None
        self.reevals.append(row)
        return len(self.reevals)

    def add_event(self, tid, kind, detail=None):
        self.events.append({"thesis_id": tid, "kind": kind,
                            "detail": detail})
        return len(self.events)

    def has_band_event(self, tid, band_key):
        return any(
            e["kind"] == "price_band_reached"
            and (e["detail"] or {}).get("band") == band_key
            for e in self.events
        )

    def latest_reeval_report_date(self, tid):
        return None

    def latest_close(self, symbols):
        return {"sh600519": 2050.0}

    def latest_report_dates(self, symbols):
        return {"sh600519": dt.date(2026, 6, 30)}

    def latest_earnings_dates(self, symbols):
        return {}


@pytest.fixture()
def patched(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr(service, "_repo", lambda: repo)
    monkeypatch.setattr(
        service, "_quality_report",
        lambda sym: {"score": 70, "verdict": "pass", "red_flags": []},
    )
    monkeypatch.setattr(
        service, "_valuation_handlers",
        lambda sym: {"dcf_fair": 1900.0, "ddm_fair": None,
                     "asset_fair": None, "comps_fair": None,
                     "pe_percentile": None},
    )
    monkeypatch.setattr(
        service, "_financial_assembly",
        lambda sym: {"net_profit": 100.0, "equity": 500.0,
                     "roe": None, "pe_ttm": 30.0, "pb": None,
                     "dv_ttm": None},
    )
    return repo


def test_capture_snapshot_tolerates_failures(monkeypatch):
    monkeypatch.setattr(service, "_quality_report",
                        lambda sym: (_ for _ in ()).throw(
                            RuntimeError("x")))
    monkeypatch.setattr(service, "_valuation_handlers",
                        lambda sym: {})
    snap = service.capture_snapshot("sh600519", price=1500.0)
    assert snap["quality"] is None
    assert snap["price"] == 1500.0


def test_assemble_metrics_covers_registry(patched):
    m = service.assemble_metrics("sh600519")
    assert m["roe"] == 20.0      # 100/500*100
    assert m["pe_ttm"] == 30.0
    assert m["revenue_yoy"] is None


def test_run_daily_triggers_reeval_and_band(patched):
    summary = service.run_daily()
    assert summary["active"] == 1
    assert summary["reevaluated"] == 1
    assert summary["band_alerts"] == 1   # 2050 在 [2000,2100] 带内
    # 幂等：再跑一次不再新增
    summary2 = service.run_daily()
    assert summary2["reevaluated"] == 0
    assert summary2["band_alerts"] == 0


def test_run_daily_verdict_rules(patched):
    service.run_daily()
    verdicts = [r["verdict"] for r in patched.reevals]
    assert verdicts == ["pass"]  # roe=20>=15, 质量 80→70 降 10 分不超
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_service.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 service.py**

```python
"""持仓论点业务服务：快照抓取 / 指标装配 / 财报联动重估 / 到价检测。

纯编排层——所有数据访问通过模块级函数（_repo/_quality_report/
_valuation_handlers/_financial_assembly），便于测试 monkeypatch。
"""
import datetime as dt
import json
import logging
from datetime import date
from typing import Any, Optional

from src.api.handler.financial_detail_handler import (
    asset_value_report,
    comps_valuation,
    dcf_valuation,
    ddm_valuation,
    quality_report,
)
from src.domain.market.fundamental.thesis_monitor import (
    ThesisCondition,
    check_price_band,
    compute_metric_values,
    evaluate_thesis,
    reeval_verdict,
)
from src.domain.market.strategy.longterm.data_loader import (
    fetch_financial_history,
    fetch_financial_snapshot,
)
from src.infra.database.alert.repository import (
    create_alert_repository,
)
from src.infra.database.portfolio.thesis_repository import (
    create_thesis_repository,
)

log = logging.getLogger(__name__)


def _data(resp: Any) -> Optional[dict]:
    """JSONResponse → data dict（checklist_handler 同款降级模式）。"""
    try:
        body = json.loads(resp.body)
        return body.get("data") if body.get("code") == 0 else None
    except Exception:
        return None


def _repo():
    return create_thesis_repository()


def _quality_report(symbol: str) -> Optional[dict]:
    d = _data(quality_report(symbol)) or {}
    if not d:
        return None
    return {
        "score": d.get("quality_score"),
        "verdict": d.get("verdict"),
        "red_flags": d.get("red_flags") or [],
    }


def _valuation_handlers(symbol: str) -> dict:
    """五法公允价摘要；单法失败置 None 不阻塞。"""
    out = {}
    for key, fn in (
        ("dcf_fair", dcf_valuation),
        ("ddm_fair", ddm_valuation),
        ("asset_fair", asset_value_report),
        ("comps_fair", comps_valuation),
    ):
        try:
            d = _data(fn(symbol)) or {}
            out[key] = d.get("fair_value") or d.get("intrinsic_value")
        except Exception:
            out[key] = None
    return out


def _financial_assembly(symbol: str) -> dict:
    """财务装配字典（compute_metric_values 的输入）。"""
    out = {}
    snap = fetch_financial_snapshot([symbol], include_detail=True)
    if symbol in snap:
        out.update(snap[symbol])
    hist = fetch_financial_history([symbol], lookback_reports=2)
    rows = hist.get(symbol) or []
    if len(rows) >= 2:
        prev, cur = rows[-2], rows[-1]
        out.setdefault("revenue_prev", prev.get("revenue"))
        out.setdefault("net_profit_prev",
                       prev.get("net_profit_parent"))
        out.setdefault("revenue", cur.get("revenue"))
        out.setdefault("net_profit", cur.get("net_profit_parent"))
    alert_repo = create_alert_repository()
    for mk in ("pe_ttm", "pb", "dv_ttm"):
        if out.get(mk) is None:
            out[mk] = alert_repo.get_latest_metric_value(symbol, mk)
    return out


def capture_snapshot(symbol: str, price: Optional[float] = None
                     ) -> dict:
    """登记时快照（spec §3.5）：任一来源失败置 None。"""
    if price is None:
        price = _repo().latest_close([symbol]).get(symbol)
    quality = None
    try:
        quality = _quality_report(symbol)
    except Exception as e:
        log.warning("capture_snapshot quality 失败 %s: %s", symbol, e)
    try:
        valuation = _valuation_handlers(symbol)
    except Exception as e:
        log.warning("capture_snapshot valuation 失败 %s: %s",
                    symbol, e)
        valuation = {}
    return {
        "date": date.today().isoformat(),
        "price": price,
        "quality": quality,
        "valuation": valuation,
    }


def assemble_metrics(symbol: str) -> dict:
    """METRIC_REGISTRY 全键现值（缺=None）。"""
    return compute_metric_values(_financial_assembly(symbol))


def get_band_key(band: Optional[dict]) -> Optional[str]:
    if not band:
        return None
    return "{}:{}:{}".format(
        band.get("metric", "price"), band.get("low"),
        band.get("high"),
    )


def _run_one(thesis: dict, repo, trigger: str,
             report_date: Optional[date]) -> bool:
    """单论点重估；返回是否落了新重估记录。"""
    conditions = repo.list_conditions(thesis["id"])
    metrics = assemble_metrics(thesis["symbol"])
    eval_conditions = [
        ThesisCondition(
            metric=c["metric_key"], operator=c["operator"],
            threshold=c["threshold"],
        )
        for c in conditions
    ]
    result = evaluate_thesis(eval_conditions, metrics)
    cond_result = []
    for c, ec in zip(conditions, eval_conditions):
        status = ("breached" if ec in result.breached
                  else "unknown" if metrics.get(c["metric_key"]) is None
                  else "holding")
        cond_result.append({
            "condition_id": c["id"], "metric_key": c["metric_key"],
            "operator": c["operator"], "threshold": c["threshold"],
            "current": metrics.get(c["metric_key"]), "status": status,
        })
        repo.update_condition_status(c["id"], status)

    quality_now = _quality_report(thesis["symbol"])
    snap_q = (thesis.get("snapshot") or {}).get("quality")
    verdict = reeval_verdict(quality_now, snap_q, cond_result)

    new_id = repo.add_reeval({
        "thesis_id": thesis["id"],
        "report_date": report_date,
        "trigger": trigger,
        "quality_now": quality_now,
        "quality_delta": {
            "score_diff": (
                quality_now["score"] - snap_q["score"]
                if quality_now and snap_q
                and quality_now.get("score") is not None
                and snap_q.get("score") is not None else None
            ),
        },
        "valuation_now": _valuation_handlers(thesis["symbol"]),
        "conditions_result": cond_result,
        "verdict": verdict,
    })
    if new_id is None:
        return False
    repo.add_event(
        thesis["id"], "reeval_done",
        {"verdict": verdict, "report_date":
            report_date.isoformat() if report_date else None},
    )
    if verdict == "sell_signal":
        breached = [c for c in cond_result
                    if c["status"] == "breached"]
        repo.add_event(
            thesis["id"], "condition_breached",
            {"verdict": verdict,
             "breached": [b["metric_key"] for b in breached]},
        )
    repo.update_thesis(
        thesis["id"], last_reviewed_at=dt.datetime.now()
    )
    return True


def _check_band(thesis: dict, repo) -> bool:
    band = thesis.get("target_band")
    band_key = get_band_key(band)
    if not band or not band_key:
        return False
    if repo.has_band_event(thesis["id"], band_key):
        return False
    price = repo.latest_close([thesis["symbol"]]).get(
        thesis["symbol"]
    )
    band_result = check_price_band(band, price, {})
    if band_result.get("metric") not in (None, "price"):
        band_result = check_price_band(band, None,
                                       assemble_metrics(
                                           thesis["symbol"]))
    if band_result.get("reached") is not True:
        return False
    repo.add_event(
        thesis["id"], "price_band_reached",
        {"band": band_key, "current": band_result.get("current"),
         "alerted": True},
    )
    return True


def run_daily(today: Optional[date] = None) -> dict:
    """每日 17:35：新财报重估 + 估值带到价检测。幂等。"""
    today = today or date.today()
    repo = _repo()
    theses = repo.list_theses(status="active")
    summary = {"active": len(theses), "reevaluated": 0,
               "band_alerts": 0}
    if not theses:
        return summary
    symbols = [t["symbol"] for t in theses]
    report_dates = repo.latest_report_dates(symbols)
    earnings = repo.latest_earnings_dates(symbols)
    for t in theses:
        sym = t["symbol"]
        trigger, report_date = None, None
        last_r = repo.latest_reeval_report_date(t["id"])
        formal = report_dates.get(sym)
        if formal and (last_r is None or formal > last_r):
            trigger, report_date = "formal", formal
        else:
            ann = earnings.get(sym)
            if ann and ann[1] and (
                last_r is None or ann[0] > last_r
            ):
                trigger, report_date = (
                    ann[2] or "express", ann[0]
                )
        try:
            if trigger and _run_one(t, repo, trigger, report_date):
                summary["reevaluated"] += 1
            if _check_band(t, repo):
                summary["band_alerts"] += 1
        except Exception as e:
            log.error("[THESIS_DAILY] %s 失败: %s", sym, e)
    return summary


def run_reeval(thesis_id: int, trigger: str = "manual",
               report_date: Optional[date] = None) -> Optional[dict]:
    """手动重估（API 调用）。"""
    repo = _repo()
    thesis = repo.get_thesis(thesis_id)
    if not thesis:
        return None
    did = _run_one(thesis, repo, trigger, report_date)
    reevals = repo.list_reevals(thesis_id, limit=1)
    return {"created": did, "latest": reevals[0] if reevals else None}
```

`__init__.py` 留空。

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_service.py -v`
Expected: 全 PASS。若 `dcf_valuation` 返回结构无 `fair_value/intrinsic_value` 键，跑一次
`cd backend && .venv/bin/python -c "from src.api.handler.financial_detail_handler import dcf_valuation; print(list(__import__('json').loads(dcf_valuation('sh600519').body)['data'].keys()))"`
按实际键名修正 `_valuation_handlers` 的取值键。

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/thesis/ backend/tests/domain/test_thesis_service.py
git commit -m "feat(thesis): 领域服务——snapshot抓取/指标装配/每日重估/到价检测(全IO可mock)"
```

---

### Task 6: handler + router + main 注册

**Files:**
- Create: `backend/src/api/handler/thesis_handler.py`
- Create: `backend/src/api/router/thesis_router.py`
- Modify: `backend/main.py`（import + include_router）
- Test: `backend/tests/api/test_thesis_router.py`

**Interfaces:**
- Consumes: Task 4 repo、Task 5 service、Task 3 build_sell_check。
- Produces: `/api/v1/thesis` 全部端点（spec §5，10 个）。

- [ ] **Step 1: 写失败测试**

```python
"""thesis router 端点测试（monkeypatch repo 与 service）。"""
from fastapi.testclient import TestClient

import main  # noqa: E402
from src.domain.market.thesis import service
from src.infra.database.portfolio import thesis_repository


class _Repo:
    theses = [{
        "id": 1, "symbol": "sh600519", "status": "active",
        "buy_date": "2026-01-10", "buy_price": 1500.0,
        "shares": 100, "thesis_text": "t", "snapshot": None,
        "target_band": None, "decision": None, "decision_note": None,
        "decision_at": None, "last_reviewed_at": None,
        "close_reason": None, "close_price": None, "closed_at": None,
        "created_at": "2026-01-10T00:00:00",
    }]

    def list_theses(self, status=None):
        return self.theses

    def create_thesis(self, data):
        return 1

    def get_thesis(self, tid):
        return self.theses[0]

    def update_thesis(self, tid, **f):
        return True

    def close_thesis(self, tid, reason, price=None):
        return True

    def list_conditions(self, tid):
        return []

    def replace_conditions(self, tid, items):
        return len(items)

    def list_reevals(self, tid, limit=50):
        return []

    def add_event(self, tid, kind, detail=None):
        return 1

    def list_events(self, unread_only=False, limit=100):
        return [{"id": 1, "thesis_id": 1, "kind": "reeval_done",
                 "detail": {"verdict": "pass"}, "read": False,
                 "created_at": "2026-09-27T00:00:00"}]

    def mark_event_read(self, eid):
        return True


def _patch(monkeypatch):
    monkeypatch.setattr(
        thesis_repository, "create_thesis_repository",
        lambda *a, **k: _Repo(),
    )
    monkeypatch.setattr(
        service, "capture_snapshot",
        lambda sym, price=None: {"date": "2026-09-27",
                                 "price": 1500.0},
    )


def test_list_and_create(monkeypatch):
    _patch(monkeypatch)
    client = TestClient(main.app)
    r = client.get("/api/v1/thesis")
    assert r.json()["code"] == 0
    assert r.json()["data"][0]["symbol"] == "sh600519"
    r2 = client.post(
        "/api/v1/thesis",
        json={"symbol": "sh600519", "thesis_text": "x"},
    )
    assert r2.json()["code"] == 0
    assert r2.json()["data"]["id"] == 1


def test_events_read(monkeypatch):
    _patch(monkeypatch)
    client = TestClient(main.app)
    r = client.get("/api/v1/thesis/events?unread=true")
    assert r.json()["data"][0]["kind"] == "reeval_done"
    r2 = client.put("/api/v1/thesis/events/1/read")
    assert r2.json()["code"] == 0
```

注意：main import 时 lifespan 不跑，建表不触发，安全。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/api/test_thesis_router.py -v`
Expected: FAIL（404，路由不存在）

- [ ] **Step 3: 实现 handler 与 router**

`thesis_handler.py`：

```python
"""持仓论点 handler：端点编排 + 卖出体检聚合。"""
import datetime as dt
from typing import Any, Optional

from src.domain.market.fundamental.thesis_monitor import (
    build_sell_check,
    check_price_band,
)
from src.domain.market.thesis import service
from src.infra.database.portfolio.thesis_repository import (
    create_thesis_repository,
)
from src.pkg import responses


def _repo():
    return create_thesis_repository()


def list_theses(status: Optional[str] = None) -> Any:
    repo = _repo()
    theses = repo.list_theses(
        status=status or None
    )
    symbols = [t["symbol"] for t in theses]
    prices = repo.latest_close(symbols) if symbols else {}
    cond_map = {t["id"]: repo.list_conditions(t["id"])
                for t in theses}
    reeval_map = {}
    for t in theses:
        rows = repo.list_reevals(t["id"], limit=1)
        reeval_map[t["id"]] = rows[0] if rows else None
    for t in theses:
        t["current_price"] = prices.get(t["symbol"])
        if t["current_price"] and t["buy_price"]:
            t["pnl_pct"] = (
                t["current_price"] / t["buy_price"] - 1.0
            ) * 100.0
        else:
            t["pnl_pct"] = None
        conds = cond_map[t["id"]]
        t["condition_summary"] = {
            "total": len(conds),
            "breached": sum(
                1 for c in conds if c["status"] == "breached"
            ),
            "unknown": sum(
                1 for c in conds if c["status"] == "unknown"
            ),
        }
        t["last_reeval_verdict"] = (
            reeval_map[t["id"]] or {}
        ).get("verdict")
        lr = t.get("last_reviewed_at")
        if lr:
            age = dt.datetime.now() - dt.datetime.fromisoformat(lr)
            t["stale"] = age.days > 90
    return responses.success(theses)


def create_thesis(payload: dict) -> Any:
    symbol = (payload.get("symbol") or "").strip().lower()
    if not symbol:
        return responses.error("symbol 必填")
    repo = _repo()
    data = {
        k: payload[k] for k in (
            "buy_date", "buy_price", "shares", "thesis_text",
            "target_band",
        ) if k in payload
    }
    data["symbol"] = symbol
    data["snapshot"] = service.capture_snapshot(symbol)
    tid = repo.create_thesis(data)
    conditions = payload.get("conditions") or []
    if conditions:
        repo.replace_conditions(tid, conditions)
    return responses.success({"id": tid})


def get_thesis(thesis_id: int) -> Any:
    repo = _repo()
    t = repo.get_thesis(thesis_id)
    if not t:
        return responses.error("论点不存在", 404)
    t["conditions"] = repo.list_conditions(thesis_id)
    t["reevals"] = repo.list_reevals(thesis_id)
    return responses.success(t)


def update_thesis(thesis_id: int, payload: dict) -> Any:
    allowed = {
        "buy_date", "buy_price", "shares", "thesis_text",
        "target_band", "decision", "decision_note",
    }
    fields = {k: v for k, v in payload.items() if k in allowed}
    if "decision" in fields:
        fields["decision_at"] = dt.datetime.now()
    ok = _repo().update_thesis(thesis_id, **fields)
    if not ok:
        return responses.error("论点不存在", 404)
    return responses.success({"updated": True})


def close_thesis(thesis_id: int, payload: dict) -> Any:
    ok = _repo().close_thesis(
        thesis_id,
        reason=payload.get("reason", "manual"),
        price=payload.get("price"),
    )
    if not ok:
        return responses.error("论点不存在", 404)
    return responses.success({"closed": True})


def replace_conditions(thesis_id: int, payload: dict) -> Any:
    items = payload.get("conditions") or []
    for it in items:
        if it.get("metric_key") not in (
            __import__(
                "src.domain.market.fundamental.thesis_monitor",
                fromlist=["METRIC_REGISTRY"],
            ).METRIC_REGISTRY
        ):
            return responses.error(
                f"未知指标 {it.get('metric_key')}"
            )
    n = _repo().replace_conditions(thesis_id, items)
    return responses.success({"count": n})


def sell_check(thesis_id: int) -> Any:
    repo = _repo()
    t = repo.get_thesis(thesis_id)
    if not t:
        return responses.error("论点不存在", 404)
    conditions = repo.list_conditions(thesis_id)
    metrics = service.assemble_metrics(t["symbol"])
    price = repo.latest_close([t["symbol"]]).get(t["symbol"])
    band_result = check_price_band(
        t.get("target_band"), price, metrics
    )
    quality_now = service._quality_report(t["symbol"])
    report = build_sell_check(
        t, conditions, metrics, band_result,
        snapshot=t.get("snapshot"),
        valuation_now=service._valuation_handlers(t["symbol"]),
        quality_now=quality_now,
    )
    return responses.success(report)


def run_reeval(thesis_id: int) -> Any:
    out = service.run_reeval(thesis_id)
    if out is None:
        return responses.error("论点不存在", 404)
    return responses.success(out)


def list_events(unread: bool = False) -> Any:
    events = _repo().list_events(unread_only=unread)
    thesis_map = {
        t["id"]: t for t in _repo().list_theses()
    }
    for e in events:
        t = thesis_map.get(e["thesis_id"])
        e["symbol"] = t["symbol"] if t else None
    return responses.success(events)


def mark_event_read(event_id: int) -> Any:
    ok = _repo().mark_event_read(event_id)
    if not ok:
        return responses.error("事件不存在", 404)
    return responses.success({"read": True})
```

`thesis_router.py`：

```python
"""持仓论点路由（spec §5）。"""
from typing import Any, Optional

from fastapi import APIRouter, Body

from src.api.handler.thesis_handler import (
    close_thesis,
    create_thesis,
    get_thesis,
    list_events,
    list_theses,
    mark_event_read,
    replace_conditions,
    run_reeval,
    sell_check,
    update_thesis,
)

router = APIRouter(prefix="/thesis", tags=["thesis"])


@router.get("")
def get_theses(status: Optional[str] = None) -> Any:
    """论点列表（实时盈亏/条件汇总/最近重估verdict/复检提醒）。"""
    return list_theses(status)


@router.post("")
def post_thesis(payload: dict = Body(...)) -> Any:
    """登记论点（服务端抓 snapshot）。"""
    return create_thesis(payload)


@router.get("/{thesis_id}")
def get_thesis_detail(thesis_id: int) -> Any:
    """详情：论点+条件+快照+重估历史。"""
    return get_thesis(thesis_id)


@router.put("/{thesis_id}")
def put_thesis(thesis_id: int, payload: dict = Body(...)) -> Any:
    """更新基础字段/决策。"""
    return update_thesis(thesis_id, payload)


@router.post("/{thesis_id}/close")
def post_close(thesis_id: int, payload: dict = Body(...)) -> Any:
    """关闭论点（thesis_broken/valuation_reached/better_alt/manual）。"""
    return close_thesis(thesis_id, payload)


@router.get("/{thesis_id}/sell-check")
def get_sell_check(thesis_id: int) -> Any:
    """四区卖出体检报告（实时聚合）。"""
    return sell_check(thesis_id)


@router.post("/{thesis_id}/reeval")
def post_reeval(thesis_id: int) -> Any:
    """手动重估。"""
    return run_reeval(thesis_id)


@router.put("/{thesis_id}/conditions")
def put_conditions(thesis_id: int,
                   payload: dict = Body(...)) -> Any:
    """条件整表替换。"""
    return replace_conditions(thesis_id, payload)


@router.get("/events/list")
def get_events(unread: bool = False) -> Any:
    """事件列表（预警中心持仓论点分区）。"""
    return list_events(unread)


@router.put("/events/{event_id}/read")
def put_event_read(event_id: int) -> Any:
    return mark_event_read(event_id)
```

注意路由顺序：`/events/list` 必须在 `/{thesis_id}` 之前注册（FastAPI 按序匹配），上面代码已按此排列——`/events/list` 在 `/{thesis_id}` 前。**但 `/events/list` 在文件中位于其后定义**，需把 `get_events` 移到 `get_thesis_detail` 之前。最终顺序：`""` → `/events/list` → `/{thesis_id}` → 其余。

`main.py`：import 区加 `from src.api.router.thesis_router import router as thesis_router`；注册区（lt_backtest 附近）加 `app.include_router(thesis_router, prefix="/api/v1")  # /api/v1/thesis`。

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && .venv/bin/python -m pytest tests/api/test_thesis_router.py -v`
Expected: 全 PASS。`responses.error` 若签名不同（第二参数非 code），跑
`grep -n "def error" backend/src/pkg/responses.py` 按实际签名调整调用。

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/handler/thesis_handler.py backend/src/api/router/thesis_router.py backend/main.py backend/tests/api/test_thesis_router.py
git commit -m "feat(thesis): /api/v1/thesis 10端点——列表/登记/详情/卖出体检/手动重估/事件"
```

---

### Task 7: 17:35 每日重估 job

**Files:**
- Modify: `backend/src/infra/scheduler.py`（boom_radar_daily 之后）
- Test: 手动验证 import + job 注册

**Interfaces:**
- Consumes: Task 5 `service.run_daily`。

- [ ] **Step 1: 实现注册（在 boom_radar_daily add_job 块之后插入）**

```python
    # ── 持仓论点重估（每日 17:35，业绩同步 17:00 / boom 17:30 之后）────
    # active 论点：新财报(formal/express/preannounce)触发重估 +
    # 目标估值带到价检测；幂等（reeval 唯一约束 + band 事件去重）。
    def _run_thesis_reeval_daily():
        from src.domain.market.thesis.service import run_daily
        try:
            summary = run_daily()
            if summary.get("reevaluated") or summary.get(
                "band_alerts"
            ):
                log.info(
                    "[THESIS_DAILY] %s", summary,
                )
        except Exception as e:
            log.error("[THESIS_DAILY] failed: %s", e)

    sched.add_job(
        _run_thesis_reeval_daily,
        CronTrigger(hour=17, minute=35, timezone="Asia/Shanghai"),
        id="thesis_reeval_daily",
        name="持仓论点每日重估",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 2: 验证**

Run: `cd backend && .venv/bin/python -c "
from src.infra.scheduler import setup_scheduler
s = setup_scheduler()
jobs = [j.id for j in s.get_jobs()]
assert 'thesis_reeval_daily' in jobs, jobs
print('job registered OK')"`
Expected: `job registered OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/scheduler.py
git commit -m "feat(thesis): 17:35持仓论点每日重估job(财报触发+估值带到价)"
```

---

### Task 8: 前端 Thesis 页 + 路由 + 菜单

**Files:**
- Create: `frontend/apps/web/src/pages/Thesis.tsx`
- Create: `frontend/apps/web/src/pages/Thesis.css`
- Modify: `frontend/apps/web/src/App.tsx`（lazy import + Route）
- Modify: `frontend/apps/web/src/components/Layout.tsx`（交易分组菜单）

**Interfaces:**
- Consumes: `/api/v1/thesis` 全部端点、`StockSearch`、`PageHeader/StateView`、chartTheme 无需（无图表）。
- Produces: 路由 `/thesis`（支持 `?symbol=` 预填登记框）。

- [ ] **Step 1: Thesis.tsx 完整实现**

```tsx
/**
 * 持仓体检 — Thesis
 * 路径：/thesis（侧边栏"持仓体检"）
 *
 * 论点即持仓：登记买入论点+可证伪假设+目标估值带；
 * 卖出体检四区报告；财报联动重估历史。
 */
import React, {useState, useEffect, useCallback} from 'react';
import {Link} from 'react-router-dom';
import {Button, Badge} from '@ytrader/common-components';
import {getApiBase} from '../lib/api';
import {PageHeader, StateView} from '../components/ui';
import {StockSearch} from '../components/StockSearch';
import './Thesis.css';

const API = `${getApiBase()}/thesis`;

// ── 类型 ─────────────────────────────────────────────────────────────────
interface Condition {
  id: number;
  metric_key: string;
  operator: string;
  threshold: number;
  label: string;
  status: string;
  current?: number | null;
}
interface Thesis {
  id: number;
  symbol: string;
  status: string;
  buy_date: string | null;
  buy_price: number | null;
  shares: number | null;
  thesis_text: string;
  snapshot: any;
  target_band: any;
  decision: string | null;
  decision_note: string | null;
  last_reviewed_at: string | null;
  close_reason: string | null;
  close_price: number | null;
  current_price?: number | null;
  pnl_pct?: number | null;
  condition_summary?: {total: number; breached: number; unknown: number};
  last_reeval_verdict?: string | null;
  stale?: boolean;
}
interface Reeval {
  id: number;
  report_date: string | null;
  trigger: string;
  verdict: string;
  created_at: string;
}
interface SellCheck {
  sections: {
    thesis: {title: string; items: Condition[]; recommend_sell: boolean; stale: boolean};
    valuation: {title: string; band: any; margin_then: number | null; margin_now: number | null; margin_consumed: number | null};
    fundamentals: {title: string; quality_now: any; quality_then: any; score_diff: number | null; new_red_flags: string[]};
    decision: {title: string; questions: string[]; decision: string | null; decision_note: string | null};
  };
  recommend_sell: boolean;
  stale_days: number | null;
}

const METRICS = [
  {key: 'roe', label: 'ROE(%)'}, {key: 'revenue_yoy', label: '营收同比(%)'},
  {key: 'net_profit_yoy', label: '净利同比(%)'}, {key: 'gross_margin', label: '毛利率(%)'},
  {key: 'ocf_ratio', label: '现金流/净利(x)'}, {key: 'debt_ratio', label: '资产负债率(%)'},
  {key: 'pe_ttm', label: 'PE(TTM)'}, {key: 'pb', label: 'PB'}, {key: 'dv_ttm', label: '股息率(%)'},
];
const OPS = ['>=', '>', '<=', '<'];
const BAND_METRICS = [
  {key: 'price', label: '价格'}, {key: 'pe_ttm', label: 'PE(TTM)'},
  {key: 'pb', label: 'PB'}, {key: 'dv_ttm', label: '股息率(%)'},
];
const VERDICT_TONE: Record<string, string> = {
  pass: 'var(--color-success)', review: 'var(--color-warning)',
  sell_signal: 'var(--color-danger)',
};
const fmtPct = (n: number | null | undefined) =>
  n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`;


// ── 登记对话框 ────────────────────────────────────────────────────────────
const CreateDialog: React.FC<{
  initialSymbol?: string;
  onDone: () => void;
  onClose: () => void;
}> = ({initialSymbol = '', onDone, onClose}) => {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [buyDate, setBuyDate] = useState('');
  const [buyPrice, setBuyPrice] = useState('');
  const [shares, setShares] = useState('');
  const [text, setText] = useState('');
  const [bandMetric, setBandMetric] = useState('price');
  const [bandLow, setBandLow] = useState('');
  const [bandHigh, setBandHigh] = useState('');
  const [conds, setConds] = useState<{metric_key: string; operator: string; threshold: string; label: string}[]>([
    {metric_key: 'roe', operator: '>=', threshold: '', label: ''},
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!symbol) {setError('请选择股票'); return;}
    setSaving(true); setError(null);
    try {
      const res = await fetch(API, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          symbol,
          buy_date: buyDate || null,
          buy_price: buyPrice ? +buyPrice : null,
          shares: shares ? +shares : null,
          thesis_text: text,
          target_band: bandLow && bandHigh
            ? {metric: bandMetric, low: +bandLow, high: +bandHigh}
            : null,
          conditions: conds
            .filter(c => c.threshold !== '')
            .map(c => ({
              metric_key: c.metric_key, operator: c.operator,
              threshold: +c.threshold, label: c.label,
            })),
        }),
      });
      const d = await res.json();
      if (d.code !== 0) throw new Error(d.msg || '登记失败');
      onDone();
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="thesis-dialog__mask" onClick={onClose}>
      <div className="thesis-dialog" onClick={e => e.stopPropagation()}>
        <h3>登记持仓论点</h3>
        <div className="thesis-dialog__row">
          <label>股票</label>
          <StockSearch value={symbol} onSelect={setSymbol}/>
        </div>
        <div className="thesis-dialog__grid">
          <div><label>买入日期</label><input type="date" value={buyDate} onChange={e => setBuyDate(e.target.value)}/></div>
          <div><label>买入价</label><input type="number" value={buyPrice} onChange={e => setBuyPrice(e.target.value)}/></div>
          <div><label>股数</label><input type="number" value={shares} onChange={e => setShares(e.target.value)}/></div>
        </div>
        <div className="thesis-dialog__row">
          <label>买入逻辑</label>
          <textarea rows={3} value={text} onChange={e => setText(e.target.value)}
            placeholder="为什么买？核心逻辑一两句话"/>
        </div>
        <div className="thesis-dialog__row">
          <label>目标卖出带</label>
          <div className="thesis-dialog__band">
            <select value={bandMetric} onChange={e => setBandMetric(e.target.value)}>
              {BAND_METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
            <input type="number" placeholder="低" value={bandLow} onChange={e => setBandLow(e.target.value)}/>
            <span>~</span>
            <input type="number" placeholder="高" value={bandHigh} onChange={e => setBandHigh(e.target.value)}/>
          </div>
        </div>
        <div className="thesis-dialog__row">
          <label>假设条件（任一破即建议卖出）</label>
          {conds.map((c, i) => (
            <div className="thesis-dialog__cond" key={i}>
              <select value={c.metric_key} onChange={e => {
                const next = [...conds]; next[i] = {...c, metric_key: e.target.value}; setConds(next);
              }}>
                {METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
              <select value={c.operator} onChange={e => {
                const next = [...conds]; next[i] = {...c, operator: e.target.value}; setConds(next);
              }}>
                {OPS.map(o => <option key={o}>{o}</option>)}
              </select>
              <input type="number" placeholder="阈值" value={c.threshold} onChange={e => {
                const next = [...conds]; next[i] = {...c, threshold: e.target.value}; setConds(next);
              }}/>
              <input placeholder="备注(可选)" value={c.label} onChange={e => {
                const next = [...conds]; next[i] = {...c, label: e.target.value}; setConds(next);
              }}/>
              <button onClick={() => setConds(conds.filter((_, j) => j !== i))}>删</button>
            </div>
          ))}
          <Button size="sm" onClick={() => setConds([...conds, {metric_key: 'roe', operator: '>=', threshold: '', label: ''}])}>
            + 条件
          </Button>
        </div>
        {error && <p className="thesis-dialog__error">{error}</p>}
        <div className="thesis-dialog__actions">
          <Button variant="primary" loading={saving} onClick={save}>登记</Button>
          <Button onClick={onClose}>取消</Button>
        </div>
      </div>
    </div>
  );
};


// ── 详情面板 ─────────────────────────────────────────────────────────────
const Detail: React.FC<{
  id: number;
  onBack: () => void;
  onChanged: () => void;
}> = ({id, onBack, onChanged}) => {
  const [thesis, setThesis] = useState<Thesis | null>(null);
  const [check, setCheck] = useState<SellCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [decision, setDecision] = useState('hold');
  const [note, setNote] = useState('');
  const [reevaling, setReevaling] = useState(false);

  const load = useCallback(() => {
    fetch(`${API}/${id}`).then(r => r.json()).then(d => {
      if (d.code === 0) {
        setThesis(d.data);
        setDecision(d.data.decision || 'hold');
        setNote(d.data.decision_note || '');
      }
    }).catch(() => {});
  }, [id]);
  useEffect(load, [load]);

  async function runCheck() {
    setChecking(true);
    try {
      const d = await (await fetch(`${API}/${id}/sell-check`)).json();
      if (d.code === 0) setCheck(d.data);
    } finally {setChecking(false);}
  }
  async function reeval() {
    setReevaling(true);
    try {
      await fetch(`${API}/${id}/reeval`, {method: 'POST'});
      load(); onChanged();
    } finally {setReevaling(false);}
  }
  async function saveDecision() {
    await fetch(`${API}/${id}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({decision, decision_note: note}),
    });
    load(); onChanged();
  }
  async function close(reason: string) {
    await fetch(`${API}/${id}/close`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({reason}),
    });
    onChanged(); onBack();
  }

  if (!thesis) return <StateView state="loading" text="加载中…"/>;
  const conds: Condition[] = (thesis as any).conditions || [];
  const reevals: Reeval[] = (thesis as any).reevals || [];

  return (
    <div className="thesis-detail">
      <div className="thesis-detail__head">
        <Button size="sm" onClick={onBack}>← 返回列表</Button>
        <h2 className="mono">{thesis.symbol}</h2>
        {thesis.buy_price && (
          <span>成本 {thesis.buy_price} · 现价 {thesis.current_price ?? '—'} ·
            <span className={thesis.pnl_pct != null && thesis.pnl_pct >= 0 ? 'pos' : 'neg'}>
              {fmtPct(thesis.pnl_pct)}
            </span>
          </span>
        )}
        <span>
          <Button size="sm" variant="primary" loading={checking} onClick={runCheck}>卖出体检</Button>
          <Button size="sm" loading={reevaling} onClick={reeval}>立即重估</Button>
        </span>
      </div>
      {thesis.stale && (
        <div className="thesis-detail__stale">⚠ 已超过 90 天未复检，建议重过体检</div>
      )}

      <section className="thesis-detail__section">
        <h3>买入逻辑</h3>
        <p>{thesis.thesis_text || '—'}</p>
      </section>

      <section className="thesis-detail__section">
        <h3>假设条件</h3>
        {conds.length === 0 && <p className="dim">未设置条件</p>}
        <table className="thesis-table">
          <thead><tr><th>指标</th><th>条件</th><th>现值</th><th>状态</th></tr></thead>
          <tbody>
            {conds.map(c => (
              <tr key={c.id}>
                <td>{c.label || c.metric_key}</td>
                <td className="mono">{c.metric_key} {c.operator} {c.threshold}</td>
                <td className="mono">{c.current ?? '—'}</td>
                <td><span className={`cond-status cond-status--${c.status}`}>{c.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {check && (
        <section className="thesis-detail__section thesis-sellcheck">
          <h3>卖出体检报告</h3>
          {check.recommend_sell && (
            <div className="thesis-sellcheck__alert">存在破位条件，建议执行卖出决策流程</div>
          )}
          <div className="thesis-sellcheck__grid">
            <div>
              <h4>A {check.sections.thesis.title}</h4>
              <ul>
                {check.sections.thesis.items.map((it, i) => (
                  <li key={i} className={`cond-status--${it.status}`}>
                    {it.label}：{it.operator}{it.threshold}（现值 {it.current ?? '—'}）→ {it.status}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4>B {check.sections.valuation.title}</h4>
              <p>目标带：{check.sections.valuation.band.metric} {check.sections.valuation.band.low}~{check.sections.valuation.band.high}，
                现值 {check.sections.valuation.band.current ?? '—'}，
                到位：{String(check.sections.valuation.band.reached ?? '无法评估')}</p>
              {check.sections.valuation.margin_consumed != null && (
                <p>安全边际消耗：{check.sections.valuation.margin_consumed.toFixed(1)}%</p>
              )}
            </div>
            <div>
              <h4>C {check.sections.fundamentals.title}</h4>
              <p>质量分：{check.sections.fundamentals.quality_then?.score ?? '—'} →
                {check.sections.fundamentals.quality_now?.score ?? '—'}
                {check.sections.fundamentals.score_diff != null &&
                  `（${check.sections.fundamentals.score_diff > 0 ? '+' : ''}${check.sections.fundamentals.score_diff}）`}</p>
              {check.sections.fundamentals.new_red_flags.length > 0 && (
                <p className="neg">新增红旗：{check.sections.fundamentals.new_red_flags.join('、')}</p>
              )}
            </div>
            <div>
              <h4>D {check.sections.decision.title}</h4>
              <ul>{check.sections.decision.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
            </div>
          </div>
        </section>
      )}

      <section className="thesis-detail__section">
        <h3>决策记录</h3>
        <div className="thesis-detail__decision">
          <select value={decision} onChange={e => setDecision(e.target.value)}>
            <option value="hold">持有</option><option value="reduce">减仓</option><option value="sell">清仓</option>
          </select>
          <input placeholder="决策备注" value={note} onChange={e => setNote(e.target.value)}/>
          <Button size="sm" onClick={saveDecision}>保存决策</Button>
        </div>
      </section>

      <section className="thesis-detail__section">
        <h3>重估历史</h3>
        {reevals.length === 0 && <p className="dim">暂无（每日 17:35 自动检测新财报触发）</p>}
        <table className="thesis-table">
          <thead><tr><th>财报期</th><th>触发</th><th>结论</th><th>时间</th></tr></thead>
          <tbody>
            {reevals.map(r => (
              <tr key={r.id}>
                <td>{r.report_date ?? '—'}</td>
                <td>{r.trigger}</td>
                <td><span style={{color: VERDICT_TONE[r.verdict]}}>{r.verdict}</span></td>
                <td>{r.created_at?.slice(0, 16)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="thesis-detail__close">
        <Button size="sm" onClick={() => close('thesis_broken')}>论点破位关闭</Button>
        <Button size="sm" onClick={() => close('valuation_reached')}>估值到位关闭</Button>
        <Button size="sm" onClick={() => close('better_alt')}>换标的关闭</Button>
        <Button size="sm" onClick={() => close('manual')}>手动关闭</Button>
      </div>
    </div>
  );
};


// ── 主页面 ───────────────────────────────────────────────────────────────
export const Thesis: React.FC = () => {
  const qp = new URLSearchParams(window.location.search);
  const [list, setList] = useState<Thesis[]>([]);
  const [closed, setClosed] = useState<Thesis[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(!!qp.get('symbol'));
  const [prefill] = useState(qp.get('symbol') || '');
  const [showClosed, setShowClosed] = useState(false);

  const load = useCallback(() => {
    fetch(`${API}?status=active`).then(r => r.json())
      .then(d => d.code === 0 && setList(d.data)).catch(() => {});
    fetch(`${API}?status=closed`).then(r => r.json())
      .then(d => d.code === 0 && setClosed(d.data)).catch(() => {});
  }, []);
  useEffect(load, [load]);

  if (selected != null) {
    return <div className="thesis-page">
      <Detail id={selected} onBack={() => setSelected(null)} onChanged={load}/>
    </div>;
  }

  return (
    <div className="thesis-page">
      <PageHeader
        title="持仓体检"
        subtitle="论点即持仓：登记买入逻辑与可证伪假设，财报联动自动重估，论点破即卖。"
        actions={<Button variant="primary" onClick={() => setShowCreate(true)}>+ 登记论点</Button>}
      />
      {list.length === 0 && (
        <StateView state="empty" text="还没有登记论点——从自选股或财务分析页进入，或点击右上角登记"/>
      )}
      <div className="thesis-list">
        {list.map(t => (
          <div key={t.id} className={`thesis-card${t.stale ? ' thesis-card--stale' : ''}`}
               onClick={() => setSelected(t.id)}>
            <div className="thesis-card__head">
              <span className="mono">{t.symbol}</span>
              {t.pnl_pct != null && (
                <span className={t.pnl_pct >= 0 ? 'pos' : 'neg'}>{fmtPct(t.pnl_pct)}</span>
              )}
              {t.condition_summary && t.condition_summary.breached > 0 ? (
                <Badge variant="danger">{t.condition_summary.breached} 条破位</Badge>
              ) : t.condition_summary && t.condition_summary.unknown > 0 ? (
                <Badge variant="info">{t.condition_summary.unknown} 条待评估</Badge>
              ) : (
                <Badge variant="success">论点成立</Badge>
              )}
              {t.last_reeval_verdict && (
                <span style={{color: VERDICT_TONE[t.last_reeval_verdict]}}>
                  {t.last_reeval_verdict}
                </span>
              )}
              {t.stale && <Badge variant="warning">90天未复检</Badge>}
            </div>
            <p className="thesis-card__text">{t.thesis_text || '—'}</p>
            {t.target_band && (
              <p className="thesis-card__band dim">
                卖出带 {t.target_band.metric} {t.target_band.low}~{t.target_band.high}
              </p>
            )}
          </div>
        ))}
      </div>

      {closed.length > 0 && (
        <div className="thesis-closed">
          <button className="thesis-closed__toggle" onClick={() => setShowClosed(!showClosed)}>
            已关闭（{closed.length}）{showClosed ? '▴' : '▾'}
          </button>
          {showClosed && (
            <table className="thesis-table">
              <thead><tr><th>标的</th><th>关闭原因</th><th>关闭价</th><th>时间</th></tr></thead>
              <tbody>
                {closed.map(t => (
                  <tr key={t.id}>
                    <td className="mono">{t.symbol}</td>
                    <td>{t.close_reason}</td>
                    <td>{t.close_price ?? '—'}</td>
                    <td>{t.closed_at?.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {showCreate && (
        <CreateDialog
          initialSymbol={prefill}
          onDone={() => {setShowCreate(false); load();}}
          onClose={() => setShowCreate(false)}
        />
      )}
    </div>
  );
};
```

- [ ] **Step 2: Thesis.css**

```css
.thesis-page {padding: var(--space-4);}
.thesis-list {display: flex; flex-direction: column; gap: var(--space-3);}
.thesis-card {
  border: 1px solid var(--color-border); border-radius: 8px;
  padding: var(--space-3); cursor: pointer; background: var(--color-bg-secondary, transparent);
}
.thesis-card:hover {border-color: var(--color-accent);}
.thesis-card--stale {border-color: var(--color-warning);}
.thesis-card__head {display: flex; align-items: center; gap: var(--space-3); font-weight: 600;}
.thesis-card__text {margin: var(--space-2) 0 0; color: var(--color-text-secondary);}
.thesis-card__band {font-size: var(--text-xs);}
.thesis-table {width: 100%; border-collapse: collapse; font-size: var(--text-sm);}
.thesis-table th, .thesis-table td {padding: 6px 10px; border-bottom: 1px solid var(--color-border); text-align: left;}
.cond-status--holding {color: var(--color-success);}
.cond-status--breached {color: var(--color-danger);}
.cond-status--unknown {color: var(--color-text-tertiary);}
.thesis-dialog__mask {
  position: fixed; inset: 0; background: rgba(0,0,0,.5);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.thesis-dialog {
  background: var(--color-bg, #1a1a1a); border-radius: 10px;
  padding: var(--space-4); width: min(680px, 92vw);
  max-height: 86vh; overflow-y: auto;
}
.thesis-dialog__row {margin: var(--space-3) 0; display: flex; flex-direction: column; gap: var(--space-1);}
.thesis-dialog__grid {display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-2);}
.thesis-dialog__band {display: flex; gap: var(--space-2); align-items: center;}
.thesis-dialog__cond {display: flex; gap: var(--space-1); margin-bottom: var(--space-1);}
.thesis-dialog__cond input, .thesis-dialog__cond select {flex: 1; min-width: 0;}
.thesis-dialog__error {color: var(--color-danger);}
.thesis-dialog__actions {display: flex; gap: var(--space-2); margin-top: var(--space-3);}
.thesis-detail__head {display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap;}
.thesis-detail__stale {
  color: var(--color-warning); border: 1px solid var(--color-warning);
  border-radius: 6px; padding: var(--space-2); margin: var(--space-2) 0;
}
.thesis-detail__section {margin: var(--space-4) 0;}
.thesis-detail__decision {display: flex; gap: var(--space-2);}
.thesis-sellcheck__alert {
  color: var(--color-danger); border: 1px solid var(--color-danger);
  border-radius: 6px; padding: var(--space-2); margin-bottom: var(--space-2);
}
.thesis-sellcheck__grid {display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3);}
.thesis-detail__close {display: flex; gap: var(--space-2); margin-top: var(--space-4);}
.thesis-closed__toggle {
  background: none; border: none; color: var(--color-text-secondary);
  cursor: pointer; margin-top: var(--space-4);
}
.pos {color: var(--color-up, #e03131);}
.neg {color: var(--color-down, #2f9e44);}
.dim {color: var(--color-text-tertiary);}
```

注意：`.pos/.neg` 若全局样式已有（A股红涨绿跌），删除重复定义。

- [ ] **Step 3: 路由与菜单**

App.tsx：lazy import 区（Checklist 行附近）加

```tsx
const Thesis = lazy(() => import('./pages/Thesis').then(m => ({default: m.Thesis})));
```

Route 区（/lt-backtest 附近）加

```tsx
<Route path="/thesis" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><Thesis /></Suspense>} />
```

Layout.tsx：交易分组（`{path: '/trading', label: '交易', ...}` 行附近）加

```tsx
{path: '/thesis', label: '持仓体检', icon: Icon.portfolio},
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && pnpm --filter web build 2>&1 | tail -5`
Expected: 构建成功无 TS 报错

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/Thesis.tsx frontend/apps/web/src/pages/Thesis.css frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(thesis): 持仓体检页——论点登记/四区卖出体检/重估历史+路由菜单"
```

---

### Task 9: 深链 + 预警中心持仓论点分区

**Files:**
- Modify: `frontend/apps/web/src/pages/Watchlist.tsx`（"体检"链接旁）
- Modify: `frontend/apps/web/src/pages/Financial.tsx`（"买入体检 →"旁）
- Modify: `frontend/apps/web/src/pages/Alerts.tsx`（页尾加分区）

- [ ] **Step 1: Watchlist.tsx 深链**

在 `<Link to={`/checklist?symbol=${it.symbol}`} ...>体检</Link>` 之后插入：

```tsx
<Link
  to={`/thesis?symbol=${it.symbol}`}
  className="watchlist__checklist-link"
  title="登记/查看持仓论点（卖出体检）">
  论点
</Link>
```

- [ ] **Step 2: Financial.tsx 深链**

在 `<Link to={`/checklist?symbol=${symbol}`} ...>买入体检 →</Link>` 之后插入：

```tsx
<Link
  to={`/thesis?symbol=${symbol}`}
  className="fin-checklist-link"
  title="登记持仓论点，跟踪卖出体检">
  论点 →
</Link>
```

- [ ] **Step 3: Alerts.tsx 持仓论点分区**

在 Alerts.tsx 顶部 import 区加：

```tsx
import {ThesisEventsSection} from './ThesisEvents';
```

在页面 JSX 的价格告警主区块之后（`</PageHeader>` 对应内容区末尾、return 的闭合 `</div>` 之前）渲染：

```tsx
<ThesisEvents />
```

新建 `frontend/apps/web/src/pages/ThesisEvents.tsx`：

```tsx
/** 预警中心"持仓论点"分区：重估/破位/到价事件流。 */
import React, {useEffect, useState} from 'react';
import {getApiBase} from '../lib/api';

const API = getApiBase();

interface TEvent {
  id: number;
  thesis_id: number;
  symbol: string | null;
  kind: string;
  detail: any;
  read: boolean;
  created_at: string;
}

const KIND_LABEL: Record<string, string> = {
  reeval_done: '财报重估',
  condition_breached: '论点破位',
  price_band_reached: '估值带到价',
};
const VERDICT_TONE: Record<string, string> = {
  pass: 'var(--color-success)', review: 'var(--color-warning)',
  sell_signal: 'var(--color-danger)',
};

export const ThesisEventsSection: React.FC = () => {
  const [events, setEvents] = useState<TEvent[]>([]);

  const load = () => {
    fetch(`${API}/thesis/events/list`).then(r => r.json())
      .then(d => d.code === 0 && setEvents(d.data)).catch(() => {});
  };
  useEffect(load, []);

  const markRead = async (id: number) => {
    await fetch(`${API}/thesis/events/${id}/read`, {method: 'PUT'});
    load();
  };

  if (events.length === 0) return null;
  return (
    <section className="alerts-thesis">
      <h3 className="alerts-thesis__title">
        持仓论点（{events.filter(e => !e.read).length} 未读）
      </h3>
      <table className="thesis-table">
        <thead><tr><th>时间</th><th>标的</th><th>事件</th><th>详情</th><th></th></tr></thead>
        <tbody>
          {events.map(e => (
            <tr key={e.id} style={e.read ? {opacity: .55} : undefined}>
              <td>{e.created_at?.slice(5, 16)}</td>
              <td className="mono">{e.symbol ?? e.thesis_id}</td>
              <td>{KIND_LABEL[e.kind] || e.kind}</td>
              <td>
                {e.kind === 'reeval_done' && (
                  <span style={{color: VERDICT_TONE[e.detail?.verdict] || undefined}}>
                    {e.detail?.verdict}
                  </span>
                )}
                {e.kind === 'condition_breached' &&
                  (e.detail?.breached || []).join('、') + ' 破位'}
                {e.kind === 'price_band_reached' &&
                  `现值 ${e.detail?.current} 进入卖出带`}
              </td>
              <td>{!e.read && <button onClick={() => markRead(e.id)}>已读</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
};
```

- [ ] **Step 4: 构建验证 + Commit**

Run: `cd frontend && pnpm --filter web build 2>&1 | tail -3`
Expected: 成功

```bash
git add frontend/apps/web/src/pages/Watchlist.tsx frontend/apps/web/src/pages/Financial.tsx frontend/apps/web/src/pages/Alerts.tsx frontend/apps/web/src/pages/ThesisEvents.tsx
git commit -m "feat(thesis): Watchlist/Financial深链+预警中心持仓论点分区"
```

---

### Task 10: 全量验证 + spec 修订

**Files:**
- Modify: `docs/superpowers/specs/2026-09-27-thesis-sell-system-design.md`（operator 表述）

- [ ] **Step 1: spec 修订**

§3.2 `operator | str | gt / lt` 改为 `operator | str | ">=" / ">" / "<=" / "<"（对齐 evaluate_thesis）`。

- [ ] **Step 2: 后端全量相关测试**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/test_thesis_monitor.py tests/domain/test_thesis_service.py tests/infra/test_thesis_repository.py tests/api/test_thesis_router.py tests/strategy -v`
Expected: 全 PASS

- [ ] **Step 3: 后端导入 + 前端构建**

Run: `cd backend && .venv/bin/python -c "import main; print('OK')"`
Run: `cd frontend && pnpm --filter web build 2>&1 | tail -3`
Expected: 均 OK

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-27-thesis-sell-system-design.md
git commit -m "docs(thesis): spec修订——operator对齐evaluate_thesis算子集"
```

---

## Self-Review 记录

- Spec 覆盖：§3 四表（Task 4）、§3.5 snapshot（Task 5）、§4 纯函数（Task 1-3）、§5 十端点（Task 6）、§6 job（Task 7）、§7 前端（Task 8-9）、§8 测试（各 Task 内嵌）、§9 验收（Task 10）——全覆盖。
- 类型一致性：`_repo()`/`_quality_report()`/`_valuation_handlers()`/`_financial_assembly()` 在 Task 5 定义、Task 6 handler 引用 `service._quality_report`（下划线函数跨模块引用在测试 monkeypatch 下成立）；前端 `Thesis` 类型与 handler 返回字段对齐。
- 已知执行期需现场校准两点（Task 5 Step 4、Task 6 Step 4 已写明探测命令）：估值 handler 返回键名、`responses.error` 签名。
