# 财报季景气雷达(Earnings Boom Radar)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 财报季每日自动筛出「业绩大增 + 文本景气信号」候选股(雷达页呈现/一键入自选),并用历史数据回测验证该策略。

**Architecture:** 新建独立域模块 `backend/src/domain/market/boom/`(纯函数词典扫描 + 财报季窗口 + 服务编排 + LLM 深读 + 回测),3 张新表(词典/命中/候选),`/boom` 路由,前端新页 `EarningsRadar.tsx`。规则引擎负责召回与回测(确定性),LLM 只对候选池深读。

**Tech Stack:** Python 3.11 + FastAPI + SQLModel(同步 Session)+ psycopg2;React + 裸 fetch hook + BEM/CSS 变量(无 Tailwind/axios)。

**Spec:** `docs/superpowers/specs/2026-09-08-earnings-boom-radar-design.md`

## Global Constraints

- 后端测试一律在 `backend/` 目录跑 `uv run pytest <path> -v`(uv 环境);前端验证在 `frontend/apps/web/` 跑 `npm run build`。
- 建表靠 `SQLModel.metadata.create_all`(DBConnection 初始化时触发),**不写迁移脚本**;新模型必须在 `main.py` lifespan 里 import。
- API 响应约定 `{code, msg, data}`,`code===0` 成功;HTTP 错误用 `HTTPException`。
- symbol 口径:`boom_*` 表内 = 纯 6 位(与 `stock_earnings_forecast` 一致);查 `news_articles`/`stock_ohlcv`/写 watchlist 时用 `to_prefixed()` 加 sh/sz 前缀。
- 前端样式:CSS 变量 design token(`var(--color-*)`)+ BEM 类 + 独立 `.css` 文件;涨红跌绿用 `is-up`/`is-down` 工具类,不自造色值。
- 每个 Task 结束 commit 一次,格式 `feat(boom): ...` / `test(boom): ...`;**不要把工作区其他未提交文件带进 commit**(git add 精确到文件)。
- 回测绝不用 LLM;扫描词典从 DB 读(`boom_keyword` 表),种子由代码常量播种。
- 中文注释/中文 UI 文案,与现有代码一致。

---

### Task 1: 景气词典种子 + 扫描器纯函数

**Files:**
- Create: `backend/src/domain/market/boom/__init__.py`(空文件)
- Create: `backend/src/domain/market/boom/keywords.py`
- Create: `backend/src/domain/market/boom/scanner.py`
- Test: `backend/tests/domain/boom/__init__.py`(空)、`backend/tests/domain/boom/test_scanner.py`

**Interfaces:**
- Produces:
  - `keywords.KeywordDef(category: str, keyword: str, weight: int)`(frozen dataclass)
  - `keywords.CATEGORIES: tuple[str, ...]`、`keywords.CATEGORY_LABELS: dict[str, str]`
  - `keywords.SEED_KEYWORDS: tuple[KeywordDef, ...]`、`keywords.default_keywords() -> list[KeywordDef]`
  - `scanner.ScanHit(keyword: str, category: str, weight: int, snippet: str)`(frozen dataclass)
  - `scanner.scan_text(text: str, keywords: Sequence[KeywordDef]) -> list[ScanHit]`(同词只取首次命中;命中词前 8 字内有否定词则跳过)
  - `scanner.summarize(hits: list[ScanHit]) -> dict`(返回 `{"categories": [...排序去重], "keyword_count": int, "score": int}`)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/boom/test_scanner.py
"""景气词典扫描器纯函数测试。"""
from src.domain.market.boom.keywords import (
    CATEGORIES, CATEGORY_LABELS, SEED_KEYWORDS, default_keywords, KeywordDef,
)
from src.domain.market.boom.scanner import scan_text, summarize


def test_seed_covers_all_categories():
    cats = {k.category for k in SEED_KEYWORDS}
    assert cats == set(CATEGORIES)
    assert all(c in CATEGORY_LABELS for c in cats)


def test_scan_hits_multiple_categories():
    text = "公司产品供不应求,行业处于高景气周期,新品上市后持续放量。"
    hits = scan_text(text, default_keywords())
    cats = {h.category for h in hits}
    assert "supply_tight" in cats      # 供不应求
    assert "boom_up" in cats           # 高景气
    assert any(h.snippet and "供不应求" in h.snippet for h in hits)


def test_scan_negation_context_skipped():
    text = "随着新产能释放,公司产品已不再供不应求。"
    hits = scan_text(text, default_keywords())
    assert all(h.keyword != "供不应求" for h in hits)


def test_scan_dedup_same_keyword():
    text = "产品供不应求,海外市场同样供不应求。"
    hits = scan_text(text, default_keywords())
    assert sum(1 for h in hits if h.keyword == "供不应求") == 1


def test_scan_empty_text_and_no_hit():
    assert scan_text("", default_keywords()) == []
    assert scan_text("今天天气不错", default_keywords()) == []


def test_summarize():
    kws = [KeywordDef("supply_tight", "供不应求", 3), KeywordDef("boom_up", "高景气", 2)]
    hits = scan_text("供不应求叠加高景气", kws)
    s = summarize(hits)
    assert s["categories"] == ["boom_up", "supply_tight"]
    assert s["keyword_count"] == 2
    assert s["score"] == 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/boom/test_scanner.py -v`
Expected: FAIL(`ModuleNotFoundError: src.domain.market.boom`)

- [ ] **Step 3: 实现 keywords.py**

```python
# backend/src/domain/market/boom/keywords.py
"""景气信号词典 —— 种子常量 + 分类元数据。

分类英文码入库/API 稳定,中文标签仅展示用。种子词为原文 7 信号 + 同义扩展。
"""
from dataclasses import dataclass

CATEGORIES = (
    "supply_tight",    # 供给紧张
    "boom_up",         # 景气上行
    "beat",            # 超预期
    "price_up",        # 价格上行
    "demand_strong",   # 需求旺盛
    "new_product",     # 新品放量
    "expand",          # 拓展替代
)

CATEGORY_LABELS = {
    "supply_tight": "供给紧张",
    "boom_up": "景气上行",
    "beat": "超预期",
    "price_up": "价格上行",
    "demand_strong": "需求旺盛",
    "new_product": "新品放量",
    "expand": "拓展替代",
}


@dataclass(frozen=True)
class KeywordDef:
    category: str
    keyword: str
    weight: int = 1


SEED_KEYWORDS: tuple[KeywordDef, ...] = (
    KeywordDef("supply_tight", "供不应求", 3),
    KeywordDef("supply_tight", "供给偏紧", 3),
    KeywordDef("supply_tight", "供应紧张", 2),
    KeywordDef("supply_tight", "紧缺", 1),
    KeywordDef("supply_tight", "排队提货", 2),
    KeywordDef("boom_up", "高景气", 3),
    KeywordDef("boom_up", "景气度上行", 3),
    KeywordDef("boom_up", "景气周期向上", 3),
    KeywordDef("boom_up", "行业景气", 2),
    KeywordDef("beat", "超预期", 3),
    KeywordDef("beat", "好于预期", 2),
    KeywordDef("beat", "超出预期", 2),
    KeywordDef("beat", "大超预期", 3),
    KeywordDef("price_up", "价格中枢上涨", 3),
    KeywordDef("price_up", "价格中枢上移", 3),
    KeywordDef("price_up", "量价齐升", 3),
    KeywordDef("price_up", "提价", 2),
    KeywordDef("price_up", "涨价", 2),
    KeywordDef("demand_strong", "需求旺盛", 3),
    KeywordDef("demand_strong", "产销两旺", 3),
    KeywordDef("demand_strong", "满产满销", 3),
    KeywordDef("demand_strong", "订单饱满", 3),
    KeywordDef("demand_strong", "需求强劲", 2),
    KeywordDef("new_product", "新品上市", 2),
    KeywordDef("new_product", "新品放量", 3),
    KeywordDef("new_product", "渗透率提升", 2),
    KeywordDef("new_product", "产品结构升级", 2),
    KeywordDef("expand", "超预期拓展", 3),
    KeywordDef("expand", "市场拓展", 2),
    KeywordDef("expand", "国产替代", 2),
    KeywordDef("expand", "新客户突破", 2),
)


def default_keywords() -> list[KeywordDef]:
    return list(SEED_KEYWORDS)
```

- [ ] **Step 4: 实现 scanner.py**

```python
# backend/src/domain/market/boom/scanner.py
"""景气文本扫描器(纯函数)。同词去重取首现;否定语境丢弃。"""
from dataclasses import dataclass
from typing import Sequence

from src.domain.market.boom.keywords import KeywordDef

NEGATION_WORDS = ("未", "不再", "难以", "没有", "无法", "不复")
NEGATION_WINDOW = 8   # 命中词往前看 8 个字符
SNIPPET_RADIUS = 30   # 摘录上下文半径


@dataclass(frozen=True)
class ScanHit:
    keyword: str
    category: str
    weight: int
    snippet: str


def _negated(text: str, idx: int) -> bool:
    start = max(0, idx - NEGATION_WINDOW)
    return any(n in text[start:idx] for n in NEGATION_WORDS)


def scan_text(text: str, keywords: Sequence[KeywordDef]) -> list[ScanHit]:
    if not text:
        return []
    hits: list[ScanHit] = []
    seen: set[str] = set()
    for kw in keywords:
        if kw.keyword in seen:
            continue
        idx = text.find(kw.keyword)
        if idx < 0 or _negated(text, idx):
            continue
        seen.add(kw.keyword)
        lo = max(0, idx - SNIPPET_RADIUS)
        hi = min(len(text), idx + len(kw.keyword) + SNIPPET_RADIUS)
        hits.append(ScanHit(kw.keyword, kw.category, kw.weight, text[lo:hi]))
    return hits


def summarize(hits: list[ScanHit]) -> dict:
    return {
        "categories": sorted({h.category for h in hits}),
        "keyword_count": len(hits),
        "score": sum(h.weight for h in hits),
    }
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/boom/test_scanner.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/domain/market/boom/ backend/tests/domain/boom/
git commit -m "feat(boom): 景气词典种子+文本扫描纯函数(否定语境/同词去重)"
```

---

### Task 2: 财报季窗口纯函数

**Files:**
- Create: `backend/src/domain/market/boom/season.py`
- Test: `backend/tests/domain/boom/test_season.py`

**Interfaces:**
- Produces:
  - `season.SeasonStatus(in_season: bool, window_name: str, window_start: dt.date, window_end: dt.date, report_date: dt.date | None, next_window_start: dt.date)`(frozen dataclass)
  - `season.prev_quarter_end(d: dt.date) -> dt.date`
  - `season.announce_window(today: dt.date) -> SeasonStatus`(预告窗 = 1/4/7/10 月整月;report_date = 上一季末)
  - `season.is_formal_window(today: dt.date) -> bool`(正式报表窗 = 3/4/8/10 月 21 日至月末)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/boom/test_season.py
"""财报季窗口判定测试。"""
import datetime as dt

from src.domain.market.boom.season import (
    announce_window, is_formal_window, prev_quarter_end,
)


def test_prev_quarter_end():
    assert prev_quarter_end(dt.date(2026, 1, 15)) == dt.date(2025, 12, 31)
    assert prev_quarter_end(dt.date(2026, 4, 2)) == dt.date(2026, 3, 31)
    assert prev_quarter_end(dt.date(2026, 7, 31)) == dt.date(2026, 6, 30)
    assert prev_quarter_end(dt.date(2026, 10, 1)) == dt.date(2026, 9, 30)


def test_october_is_announce_season():
    s = announce_window(dt.date(2026, 10, 15))
    assert s.in_season
    assert s.window_start == dt.date(2026, 10, 1)
    assert s.window_end == dt.date(2026, 10, 31)
    assert s.report_date == dt.date(2026, 9, 30)
    assert s.window_name == "2026Q3预告窗"


def test_september_off_season_with_countdown():
    s = announce_window(dt.date(2026, 9, 8))
    assert not s.in_season
    assert s.report_date is None
    assert s.next_window_start == dt.date(2026, 10, 1)


def test_december_countdown_to_next_january():
    s = announce_window(dt.date(2026, 12, 20))
    assert not s.in_season
    assert s.next_window_start == dt.date(2027, 1, 1)


def test_formal_windows():
    assert is_formal_window(dt.date(2026, 8, 25))
    assert is_formal_window(dt.date(2026, 4, 30))
    assert not is_formal_window(dt.date(2026, 8, 10))
    assert not is_formal_window(dt.date(2026, 9, 21))   # 9月无正式报表
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/boom/test_season.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现 season.py**

```python
# backend/src/domain/market/boom/season.py
"""财报季窗口判定(纯函数)。

预告窗:1/4/7/10 月整月(对应报告期 = 上一季末)。
正式报表窗:3/4/8/10 月 21 日至月末(年报/季报集中披露尾段)。
"""
import datetime as dt
from dataclasses import dataclass

ANNOUNCE_MONTHS = (1, 4, 7, 10)
FORMAL_MONTHS = (3, 4, 8, 10)
FORMAL_START_DAY = 21


@dataclass(frozen=True)
class SeasonStatus:
    in_season: bool
    window_name: str          # 如 "2026Q3预告窗";非财报季为 ""
    window_start: dt.date
    window_end: dt.date
    report_date: dt.date | None   # 当季报告期(季末);非财报季 None
    next_window_start: dt.date


def _month_end(y: int, m: int) -> dt.date:
    return dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1)


def prev_quarter_end(d: dt.date) -> dt.date:
    q_month = ((d.month - 1) // 3) * 3        # 1/4/7/10
    if q_month == 0:
        return dt.date(d.year - 1, 12, 31)
    return dt.date(d.year, q_month, 1) - dt.timedelta(days=1)


def announce_window(today: dt.date) -> SeasonStatus:
    if today.month in ANNOUNCE_MONTHS:
        start = dt.date(today.year, today.month, 1)
        end = _month_end(today.year, today.month)
        rd = prev_quarter_end(start)
        quarter = (rd.month + 2) // 3          # 12月→4季末→Q4? rd 是上季末:12→Q4
        return SeasonStatus(True, f"{rd.year}Q{quarter}预告窗", start, end, rd, end)
    # 非财报季:找下一个预告窗首日
    for delta_month in range(1, 13):
        y, m = today.year, today.month + delta_month
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        if m in ANNOUNCE_MONTHS:
            return SeasonStatus(False, "", today, today, None, dt.date(y, m, 1))
    raise AssertionError("unreachable")


def is_formal_window(today: dt.date) -> bool:
    return today.month in FORMAL_MONTHS and today.day >= FORMAL_START_DAY
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/boom/test_season.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/boom/season.py backend/tests/domain/boom/test_season.py
git commit -m "feat(boom): 财报季预告窗/正式报表窗判定纯函数"
```

---

### Task 3: DB 三表模型 + BoomRepository + 预告按公告日查询

**Files:**
- Create: `backend/src/infra/database/market/boom.py`
- Modify: `backend/src/infra/database/market/financial_full.py`(`EarningsForecastRepository` 类内,`get_by_report_date` 方法后新增方法)
- Test: `backend/tests/infra/test_boom_repository.py`

**Interfaces:**
- Consumes: `keywords.SEED_KEYWORDS`、`scanner.ScanHit`
- Produces:
  - `boom.BoomKeywordTable(id, category, keyword, weight, enabled)` 表 `boom_keyword`
  - `boom.BoomScanHitTable(id, symbol, source_type, source_ref, source_date, keyword, category, snippet, created_at)` 表 `boom_scan_hit`,唯一约束 `(source_type, source_ref, keyword)`
  - `boom.BoomCandidateTable(symbol, report_date, forecast_type, company_name, announce_date, change_pct, forecast_type_label, categories, keyword_count, news_hit_count, news_synced, llm_score, llm_verdict, llm_summary, llm_analyzed_at, status, updated_at)` 表 `boom_candidate`,主键 `(symbol, report_date)`
  - `boom.create_boom_repository() -> BoomRepository`;`BoomRepository(session_scope)`(参数为产出 session 的 context manager,便于 sqlite 单测)
  - 方法:`seed_keywords() / list_keywords(enabled_only=True) / create_keyword(category, keyword, weight) / update_keyword(kid, **fields) / delete_keyword(kid) / upsert_hits(rows: list[dict]) -> int / upsert_candidates(rows: list[dict]) -> int / get_candidates(report_date=None, limit=1000) / get_candidate(symbol, report_date) / get_hits(symbol, report_date=None) / get_hits_as_of(symbols, max_source_date) / mark_news_synced(symbol, report_date) / mark_llm(symbol, report_date, score, verdict, summary) / set_status(symbol, report_date, status)`
  - `financial_full.EarningsForecastRepository.get_by_announce_date_range(start, end, forecast_type=None, limit=20000)`

- [ ] **Step 1: 写失败测试(sqlite 内存库,只建本任务表)**

```python
# backend/tests/infra/test_boom_repository.py
"""boom 三表仓储测试(sqlite 内存库)。"""
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlmodel import SQLModel, Session, create_engine

from src.domain.market.boom.keywords import SEED_KEYWORDS
from src.infra.database.market.boom import (
    BoomCandidateTable, BoomKeywordTable, BoomScanHitTable,
    BoomRepository,
)


@pytest.fixture()
def repo(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/boom.db")
    SQLModel.metadata.create_all(
        engine,
        tables=[BoomKeywordTable.__table__, BoomScanHitTable.__table__,
                BoomCandidateTable.__table__],
    )

    @contextmanager
    def scope():
        with Session(engine) as s:
            yield s

    yield BoomRepository(scope)
    engine.dispose()


def test_seed_and_list_keywords(repo):
    n = repo.seed_keywords()
    assert n == len(SEED_KEYWORDS)
    assert repo.seed_keywords() == 0            # 幂等
    kws = repo.list_keywords()
    assert len(kws) == len(SEED_KEYWORDS)
    assert all(isinstance(k.weight, int) for k in kws)


def test_keyword_crud(repo):
    repo.seed_keywords()
    k = repo.create_keyword("supply_tight", "一货难求", 2)
    assert k.id is not None
    repo.update_keyword(k.id, enabled=False)
    assert all(x.keyword != "一货难求" for x in repo.list_keywords(enabled_only=True))
    repo.delete_keyword(k.id)
    assert repo.get_keyword(k.id) is None


def test_upsert_hits_idempotent(repo):
    rows = [{"symbol": "600519", "source_type": "news", "source_ref": "http://a",
             "source_date": dt.date(2026, 9, 7), "keyword": "供不应求",
             "category": "supply_tight", "snippet": "…供不应求…"}]
    assert repo.upsert_hits(rows) == 1
    assert repo.upsert_hits(rows) == 0          # 冲突跳过
    hits = repo.get_hits("600519")
    assert len(hits) == 1 and hits[0].keyword == "供不应求"


def test_upsert_candidates_and_query(repo):
    row = {"symbol": "600519", "report_date": dt.date(2026, 9, 30),
           "forecast_type": "preannounce", "company_name": "贵州茅台",
           "announce_date": dt.date(2026, 10, 12), "change_pct": 60.0,
           "forecast_type_label": "预增", "categories": ["supply_tight"],
           "keyword_count": 2, "news_hit_count": 1}
    repo.upsert_candidates([row])
    row["change_pct"] = 65.0                     # 重新扫 → 更新
    repo.upsert_candidates([row])
    got = repo.get_candidates()
    assert len(got) == 1 and got[0].change_pct == 65.0
    one = repo.get_candidate("600519", dt.date(2026, 9, 30))
    assert one.company_name == "贵州茅台"
    repo.mark_news_synced("600519", dt.date(2026, 9, 30))
    assert repo.get_candidate("600519", dt.date(2026, 9, 30)).news_synced


def test_hits_as_of_lookahead_guard(repo):
    repo.upsert_hits([
        {"symbol": "600519", "source_type": "news", "source_ref": "u1",
         "source_date": dt.date(2026, 10, 11), "keyword": "供不应求",
         "category": "supply_tight", "snippet": ""},
        {"symbol": "600519", "source_type": "news", "source_ref": "u2",
         "source_date": dt.date(2026, 10, 13), "keyword": "高景气",
         "category": "boom_up", "snippet": ""},
    ])
    asof = repo.get_hits_as_of(["600519"], dt.date(2026, 10, 12))
    assert [h.keyword for h in asof] == ["供不应求"]   # 晚于 10-12 的不入


def test_mark_llm_and_status(repo):
    rd = dt.date(2026, 9, 30)
    repo.upsert_candidates([{"symbol": "600519", "report_date": rd,
                             "forecast_type": "preannounce",
                             "categories": [], "keyword_count": 0,
                             "news_hit_count": 0}])
    repo.mark_llm("600519", rd, score=82, verdict="focus", summary="量价齐升")
    repo.set_status("600519", rd, "added_watchlist")
    c = repo.get_candidate("600519", rd)
    assert c.llm_score == 82 and c.llm_verdict == "focus"
    assert c.status == "added_watchlist"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/infra/test_boom_repository.py -v`
Expected: FAIL(`ModuleNotFoundError: ...market.boom`)

- [ ] **Step 3: 实现 boom.py**

```python
# backend/src/infra/database/market/boom.py
"""财报季景气雷达三表:词典 / 扫描命中 / 候选池。

session-loop upsert(非 execute_values):日频量级小(千级),换取
方言无关(sqlite 单测 + PG 生产都可跑)。
"""
import datetime as dt
import threading
from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy import JSON, Column, DateTime, Text, UniqueConstraint, func
from sqlmodel import Field, SQLModel, Session, select

from src.domain.market.boom.keywords import SEED_KEYWORDS
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)

_CANDIDATE_COLS = (
    "symbol", "report_date", "forecast_type", "company_name", "announce_date",
    "change_pct", "forecast_type_label", "categories", "keyword_count",
    "news_hit_count",
)


class BoomKeywordTable(SQLModel, table=True):
    __tablename__ = "boom_keyword"
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True)
    keyword: str = Field(unique=True)
    weight: int = Field(default=1)
    enabled: bool = Field(default=True)


class BoomScanHitTable(SQLModel, table=True):
    __tablename__ = "boom_scan_hit"
    __table_args__ = (
        UniqueConstraint("source_type", "source_ref", "keyword",
                         name="uq_boom_hit"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)              # 纯 6 位
    source_type: str = Field()                   # forecast / news / survey
    source_ref: str = Field()                    # forecast主键串 / 新闻url / 调研日期串
    source_date: Optional[dt.date] = Field(default=None)
    keyword: str = Field()
    category: str = Field(index=True)
    snippet: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.now)


class BoomCandidateTable(SQLModel, table=True):
    __tablename__ = "boom_candidate"
    symbol: str = Field(primary_key=True)        # 纯 6 位
    report_date: dt.date = Field(primary_key=True)
    forecast_type: str = Field(default="preannounce")
    company_name: Optional[str] = None
    announce_date: Optional[dt.date] = None
    change_pct: Optional[float] = None
    forecast_type_label: Optional[str] = None
    categories: Any = Field(default=[], sa_column=Column(JSON))
    keyword_count: int = Field(default=0)
    news_hit_count: int = Field(default=0)
    news_synced: bool = Field(default=False)     # 新闻已同步过,重跑跳过
    llm_score: Optional[int] = None
    llm_verdict: Optional[str] = None            # focus / watch / exclude
    llm_summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    llm_analyzed_at: Optional[datetime] = None
    status: str = Field(default="new")           # new/confirmed/dismissed/added_watchlist
    updated_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now()),
    )


class BoomRepository:
    def __init__(self, session_scope: Callable):
        self._scope = session_scope

    # ── 词典 ──────────────────────────────────────────────
    def seed_keywords(self) -> int:
        with self._scope() as s:
            existing = {k.keyword for k in s.exec(select(BoomKeywordTable)).all()}
            new = [BoomKeywordTable(category=k.category, keyword=k.keyword,
                                    weight=k.weight)
                   for k in SEED_KEYWORDS if k.keyword not in existing]
            s.add_all(new)
            s.commit()
            return len(new)

    def list_keywords(self, enabled_only: bool = True) -> list[BoomKeywordTable]:
        with self._scope() as s:
            stmt = select(BoomKeywordTable)
            if enabled_only:
                stmt = stmt.where(BoomKeywordTable.enabled == True)  # noqa: E712
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_keyword(self, kid: int) -> Optional[BoomKeywordTable]:
        with self._scope() as s:
            return s.get(BoomKeywordTable, kid)

    def create_keyword(self, category: str, keyword: str, weight: int = 1):
        with self._scope() as s:
            row = BoomKeywordTable(category=category, keyword=keyword, weight=weight)
            s.add(row)
            s.commit()
            s.refresh(row)
            s.expunge(row)
            return row

    def update_keyword(self, kid: int, **fields):
        with self._scope() as s:
            row = s.get(BoomKeywordTable, kid)
            if row is None:
                return None
            for k, v in fields.items():
                setattr(row, k, v)
            s.commit()
            return row

    def delete_keyword(self, kid: int) -> bool:
        with self._scope() as s:
            row = s.get(BoomKeywordTable, kid)
            if row is None:
                return False
            s.delete(row)
            s.commit()
            return True

    # ── 命中明细 ──────────────────────────────────────────
    def upsert_hits(self, rows: list[dict]) -> int:
        added = 0
        with self._scope() as s:
            for r in rows:
                stmt = select(BoomScanHitTable).where(
                    BoomScanHitTable.source_type == r["source_type"],
                    BoomScanHitTable.source_ref == r["source_ref"],
                    BoomScanHitTable.keyword == r["keyword"],
                )
                if s.exec(stmt).first() is not None:
                    continue
                s.add(BoomScanHitTable(**r))
                added += 1
            s.commit()
        return added

    def get_hits(self, symbol: str, report_date: Optional[dt.date] = None):
        with self._scope() as s:
            stmt = select(BoomScanHitTable).where(
                BoomScanHitTable.symbol == symbol
            ).order_by(BoomScanHitTable.source_date.desc())
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_hits_as_of(self, symbols: list[str], max_source_date: dt.date):
        """回测用:只取 source_date ≤ max_source_date 的命中(前视守卫数据腿)。"""
        if not symbols:
            return []
        with self._scope() as s:
            stmt = select(BoomScanHitTable).where(
                BoomScanHitTable.symbol.in_(symbols),
                BoomScanHitTable.source_date <= max_source_date,
            )
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    # ── 候选池 ────────────────────────────────────────────
    def upsert_candidates(self, rows: list[dict]) -> int:
        with self._scope() as s:
            for r in rows:
                existing = s.get(BoomCandidateTable,
                                 (r["symbol"], r["report_date"]))
                if existing is None:
                    s.add(BoomCandidateTable(**{k: r[k] for k in _CANDIDATE_COLS
                                                if k in r}))
                else:
                    for k in _CANDIDATE_COLS:
                        if k in r:
                            setattr(existing, k, r[k])
            s.commit()
        return len(rows)

    def get_candidates(self, report_date: Optional[dt.date] = None,
                       limit: int = 1000) -> list[BoomCandidateTable]:
        with self._scope() as s:
            stmt = select(BoomCandidateTable)
            if report_date is None:
                latest = s.exec(select(BoomCandidateTable.report_date)
                                .order_by(BoomCandidateTable.report_date.desc())
                                ).first()
                if latest is None:
                    return []
                report_date = latest
            stmt = (stmt.where(BoomCandidateTable.report_date == report_date)
                    .order_by(BoomCandidateTable.change_pct.desc())
                    .limit(limit))
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_candidate(self, symbol: str, report_date: dt.date):
        with self._scope() as s:
            row = s.get(BoomCandidateTable, (symbol, report_date))
            if row is not None:
                s.expunge(row)
            return row

    def mark_news_synced(self, symbol: str, report_date: dt.date):
        with self._scope() as s:
            row = s.get(BoomCandidateTable, (symbol, report_date))
            if row is not None:
                row.news_synced = True
                s.commit()

    def mark_llm(self, symbol: str, report_date: dt.date,
                 score: Optional[int], verdict: Optional[str],
                 summary: Optional[str]):
        with self._scope() as s:
            row = s.get(BoomCandidateTable, (symbol, report_date))
            if row is not None:
                row.llm_score = score
                row.llm_verdict = verdict
                row.llm_summary = summary
                row.llm_analyzed_at = datetime.now()
                s.commit()

    def set_status(self, symbol: str, report_date: dt.date, status: str):
        with self._scope() as s:
            row = s.get(BoomCandidateTable, (symbol, report_date))
            if row is not None:
                row.status = status
                s.commit()


_db_connection: Optional[DBConnection] = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_boom_repository() -> BoomRepository:
    return BoomRepository(_get_db_connection().session_scope)
```

- [ ] **Step 4: financial_full.py 增加 announce_date 范围查询**

在 `EarningsForecastRepository.get_by_report_date` 方法(约 `financial_full.py:539-569`)之后,类体内新增:

```python
    def get_by_announce_date_range(
        self,
        start: dt.date,
        end: dt.date,
        forecast_type: Optional[str] = None,
        limit: int = 20000,
    ) -> list[StockEarningsForecast]:
        """按公告日期窗口查询(财报季雷达:拉当前预告窗内全部披露)。"""
        with self._db.session_scope() as s:
            stmt = select(StockEarningsForecast).where(
                StockEarningsForecast.announce_date >= start,
                StockEarningsForecast.announce_date <= end,
            )
            if forecast_type is not None:
                stmt = stmt.where(
                    StockEarningsForecast.forecast_type == forecast_type
                )
            stmt = stmt.order_by(
                StockEarningsForecast.change_pct.desc().nullslast()
            ).limit(limit)
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/infra/test_boom_repository.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/infra/database/market/boom.py backend/src/infra/database/market/financial_full.py backend/tests/infra/test_boom_repository.py
git commit -m "feat(boom): 词典/命中/候选三表仓储+预告按公告日范围查询"
```

---

### Task 4: BoomRadarService 核心流水线

**Files:**
- Create: `backend/src/domain/market/boom/service.py`
- Test: `backend/tests/domain/boom/test_service.py`

**Interfaces:**
- Consumes: Task 1/2/3 全部产物;`NewsSyncService.sync_stock_news(symbol, days_back)`;`create_news_repository().find_by_symbol(symbol, days_back, limit)`(返回带 `.title/.content/.publish_time` 的对象)
- Produces:
  - `service.growth_filter(forecasts, min_change_pct) -> list[StockEarningsForecast]`(纯函数:preannounce 需 `forecast_type_label=="预增"` 且 `change_pct>=min`;express 仅 `change_pct>=min`)
  - `service.raw_text(row) -> str`(把 forecast `raw` dict 的所有字符串值拼接为待扫文本)
  - `service.to_prefixed(symbol) -> str`(6→sh,其余→sz)
  - `service.BoomRadarService(repo, forecast_repo, news_sync, news_repo, config: dict)`
    - `run_daily(today: dt.date | None = None) -> dict`
  - `service.build_default_service() -> BoomRadarService`

- [ ] **Step 1: 写失败测试(fake 依赖,不触网/不触库)**

```python
# backend/tests/domain/boom/test_service.py
"""BoomRadarService 流水线测试(fake 依赖)。"""
import datetime as dt
from dataclasses import dataclass, field
from types import SimpleNamespace

from src.domain.market.boom.service import (
    BoomRadarService, growth_filter, raw_text, to_prefixed,
)


# ── 纯函数 ──────────────────────────────────────────────
def _fc(sym, ftype="preannounce", label="预增", pct=60.0, raw=None, ann=None):
    return SimpleNamespace(
        symbol=sym, forecast_type=ftype, report_date=dt.date(2026, 9, 30),
        metric="净利润", company_name="X", announce_date=ann or dt.date(2026, 10, 12),
        change_pct=pct, forecast_type_label=label, raw=raw or {},
    )


def test_growth_filter():
    rows = [
        _fc("600001"),                              # 预增60 → 入池
        _fc("600002", pct=30.0),                    # 预增30 → 出
        _fc("600003", label="预亏", pct=100.0),      # 预亏 → 出
        _fc("600004", pct=None),                    # 预增但无幅度 → 出
        _fc("600005", ftype="express", pct=80.0),   # 快报80 → 入池
        _fc("600006", ftype="express", pct=None),   # 快报无幅度 → 出
    ]
    got = [f.symbol for f in growth_filter(rows, min_change_pct=50.0)]
    assert got == ["600001", "600005"]


def test_raw_text_concatenates_strings():
    row = _fc("600001", raw={"预告类型": "预增", "业绩变动原因说明": "产品供不应求", "数值": 1.2})
    assert "产品供不应求" in raw_text(row)


def test_to_prefixed():
    assert to_prefixed("600519") == "sh600519"
    assert to_prefixed("300750") == "sz300750"


# ── 流水线 ──────────────────────────────────────────────
class FakeRepo:
    def __init__(self):
        self.hits, self.candidates, self.news_synced = [], [], []

    def seed_keywords(self): return 0
    def list_keywords(self, enabled_only=True):
        from src.domain.market.boom.keywords import default_keywords, KeywordDef
        return default_keywords()
    def upsert_hits(self, rows): self.hits.extend(rows); return len(rows)
    def upsert_candidates(self, rows): self.candidates.extend(rows); return len(rows)
    def get_candidates(self, report_date=None, limit=1000): return self.candidates
    def get_candidate(self, symbol, report_date): return None
    def get_hits(self, symbol, report_date=None):
        return [h for h in self.hits if h["symbol"] == symbol]
    def mark_news_synced(self, symbol, report_date): self.news_synced.append(symbol)


class FakeForecastRepo:
    def get_by_announce_date_range(self, start, end, forecast_type=None, limit=20000):
        return [_fc("600001", raw={"业绩变动原因说明": "产品供不应求,行业高景气"}),
                _fc("600002", pct=30.0)]


class FakeNewsSync:
    def __init__(self): self.calls = []
    def sync_stock_news(self, symbol, days_back=7):
        self.calls.append(symbol)
        return SimpleNamespace(saved=3, total=3, duplicates=0, errors=0,
                               duration_seconds=0.1)


@dataclass
class FakeArticle:
    title: str
    content: str
    publish_time: dt.datetime
    symbol: str = "sh600001"


class FakeNewsRepo:
    def find_by_symbol(self, symbol, days_back=7, limit=50):
        return [FakeArticle("满产满销", "公司当前满产满销,订单饱满。",
                            dt.datetime(2026, 10, 10, 9, 0))]


def test_run_daily_off_season_fast_noop():
    svc = BoomRadarService(FakeRepo(), FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0})
    stats = svc.run_daily(today=dt.date(2026, 9, 8))     # 9月非财报季
    assert stats["in_season"] is False
    assert stats["candidates"] == 0


def test_run_daily_in_season_pipeline():
    repo = FakeRepo()
    news_sync = FakeNewsSync()
    svc = BoomRadarService(repo, FakeForecastRepo(), news_sync, FakeNewsRepo(),
                           {"min_change_pct": 50.0})
    stats = svc.run_daily(today=dt.date(2026, 10, 15))
    assert stats["in_season"] is True
    assert stats["pool"] == 1                       # 只有 600001 入池
    assert news_sync.calls == ["sh600001"]          # 新闻同步带前缀
    syms = [c["symbol"] for c in repo.candidates]
    assert syms == ["600001"]
    cats = repo.candidates[0]["categories"]
    assert "supply_tight" in cats and "boom_up" in cats   # raw 文本命中
    assert "demand_strong" in cats                          # 新闻正文命中
    kw_types = {h["source_type"] for h in repo.hits}
    assert kw_types == {"forecast", "news"}
    assert repo.news_synced == ["600001"]


def test_run_daily_idempotent_skip_news_sync():
    repo = FakeRepo()
    news_sync = FakeNewsSync()
    existing = {"symbol": "600001", "report_date": dt.date(2026, 9, 30),
                "forecast_type": "preannounce", "company_name": "X",
                "announce_date": dt.date(2026, 10, 12), "change_pct": 60.0,
                "forecast_type_label": "预增", "categories": [],
                "keyword_count": 0, "news_hit_count": 0}
    repo.candidates.append(existing)
    repo.get_candidate = lambda s, r: SimpleNamespace(**existing)
    svc = BoomRadarService(repo, FakeForecastRepo(), news_sync, FakeNewsRepo(),
                           {"min_change_pct": 50.0})
    svc.run_daily(today=dt.date(2026, 10, 15))
    assert news_sync.calls == []                    # 已同步过 → 跳过
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/boom/test_service.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现 service.py**

```python
# backend/src/domain/market/boom/service.py
"""财报季景气雷达编排:预告入池 → 新闻同步 → 词典扫描 → 命中/候选落库。"""
import datetime as dt
import logging
from typing import Optional

from src.domain.market.boom.keywords import KeywordDef
from src.domain.market.boom.scanner import ScanHit, scan_text, summarize
from src.domain.market.boom.season import announce_window

log = logging.getLogger("boom_radar")

DEFAULT_CONFIG = {"min_change_pct": 50.0, "news_days_back": 7}


def to_prefixed(symbol: str) -> str:
    """纯 6 位 → 带 sh/sz 前缀(news/ohlcv 口径)。"""
    return ("sh" if symbol.startswith(("6", "9", "5")) else "sz") + symbol


def growth_filter(forecasts, min_change_pct: float) -> list:
    """业绩大增过滤:preannounce 需「预增」且幅度达标;express 幅度达标即可。"""
    out = []
    for f in forecasts:
        pct = f.change_pct
        if pct is None or pct < min_change_pct:
            continue
        if f.forecast_type == "preannounce" and f.forecast_type_label != "预增":
            continue
        out.append(f)
    return out


def raw_text(row) -> str:
    """forecast.raw 原始行里的字符串字段拼接为待扫文本。"""
    raw = row.raw if isinstance(row.raw, dict) else {}
    return "。".join(str(v) for v in raw.values() if isinstance(v, str) and v)


class BoomRadarService:
    def __init__(self, repo, forecast_repo, news_sync, news_repo, config: dict):
        self.repo = repo
        self.forecast_repo = forecast_repo
        self.news_sync = news_sync
        self.news_repo = news_repo
        self.config = {**DEFAULT_CONFIG, **config}

    def run_daily(self, today: Optional[dt.date] = None) -> dict:
        today = today or dt.date.today()
        status = announce_window(today)
        if not status.in_season:
            return {"in_season": False, "next_window_start": status.next_window_start,
                    "pool": 0, "news_synced": 0, "hits": 0, "candidates": 0}

        forecasts = self.forecast_repo.get_by_announce_date_range(
            status.window_start, today
        )
        pool = growth_filter(forecasts, self.config["min_change_pct"])

        keywords = [
            KeywordDef(k.category, k.keyword, k.weight)
            for k in self.repo.list_keywords(enabled_only=True)
        ]

        hit_rows: list[dict] = []
        cand_rows: list[dict] = []
        news_synced = 0
        since = dt.datetime.combine(status.window_start, dt.time.min)

        for f in pool:
            prefixed = to_prefixed(f.symbol)
            existing = self.repo.get_candidate(f.symbol, f.report_date)
            if existing is None or not getattr(existing, "news_synced", False):
                try:
                    self.news_sync.sync_stock_news(
                        prefixed, days_back=self.config["news_days_back"]
                    )
                    news_synced += 1
                    self.repo.mark_news_synced(f.symbol, f.report_date)
                except Exception as e:      # 单股失败不阻塞
                    log.warning("news sync %s failed: %s", f.symbol, e)

            hits: list[ScanHit] = []
            # 文本源1:预告 raw 原因文本
            ftext = raw_text(f)
            if ftext:
                hits += scan_text(ftext, keywords)
            hit_rows += [
                {"symbol": f.symbol, "source_type": "forecast",
                 "source_ref": f"{f.symbol}|{f.forecast_type}|{f.report_date}|{f.metric}",
                 "source_date": f.announce_date, "keyword": h.keyword,
                 "category": h.category, "snippet": h.snippet}
                for h in hits
            ]
            # 文本源2:个股新闻正文/标题
            try:
                articles = self.news_repo.find_by_symbol(
                    prefixed, days_back=self.config["news_days_back"] * 5, limit=50
                )
            except Exception:
                articles = []
            news_hits = 0
            for a in articles:
                if a.publish_time and a.publish_time < since:
                    continue
                text = f"{a.title}。{a.content}"
                a_hits = scan_text(text, keywords)
                news_hits += len(a_hits)
                hit_rows += [
                    {"symbol": f.symbol, "source_type": "news",
                     "source_ref": getattr(a, "url", f"{prefixed}|{a.publish_time}"),
                     "source_date": a.publish_time.date() if a.publish_time else None,
                     "keyword": h.keyword, "category": h.category,
                     "snippet": h.snippet}
                    for h in a_hits
                ]
            s = summarize(hits)
            cand_rows.append({
                "symbol": f.symbol, "report_date": f.report_date,
                "forecast_type": f.forecast_type,
                "company_name": f.company_name,
                "announce_date": f.announce_date, "change_pct": f.change_pct,
                "forecast_type_label": f.forecast_type_label,
                "categories": s["categories"], "keyword_count": s["keyword_count"],
                "news_hit_count": news_hits,
            })

        added = self.repo.upsert_hits(hit_rows) if hit_rows else 0
        self.repo.upsert_candidates(cand_rows) if cand_rows else None
        return {"in_season": True, "window_name": status.window_name,
                "report_date": status.report_date, "pool": len(pool),
                "news_synced": news_synced, "hits": added,
                "candidates": len(cand_rows)}


def build_default_service() -> BoomRadarService:
    from conf import app_config
    from src.domain.market.news.sync_service import NewsSyncService
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider
    from src.infra.database.market.boom import create_boom_repository
    from src.infra.database.market.financial_full import (
        create_earnings_forecast_repository,
    )
    from src.infra.database.news_repository import create_news_repository

    cfg = app_config.boom_radar
    news_repo = create_news_repository()
    return BoomRadarService(
        repo=create_boom_repository(),
        forecast_repo=create_earnings_forecast_repository(),
        news_sync=NewsSyncService(AkshareProvider(), news_repo),
        news_repo=news_repo,
        config={"min_change_pct": cfg.min_change_pct,
                "news_days_back": cfg.news_days_back,
                "llm_daily_limit": cfg.llm_daily_limit},
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/boom/test_service.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/boom/service.py backend/tests/domain/boom/test_service.py
git commit -m "feat(boom): 雷达核心流水线——入池/新闻同步/双源扫描/幂等upsert"
```

---

### Task 5: 配置 + scheduler job + main.py 接线

**Files:**
- Modify: `backend/conf/settings.py`(`ScreenerConfig` 定义附近加 `BoomRadarConfig` 类;`AppConfig` 内 `screener: ScreenerConfig = ScreenerConfig()` 行后加字段)
- Modify: `backend/src/infra/scheduler.py`(`_run_financial_earnings_daily` 的 add_job 之后加闭包与注册)
- Modify: `backend/main.py`(router import 区 `watchlist_router` 行后加 boom import;lifespan 模型 import 区加 boom 模型;include_router 区加挂载)

**Interfaces:**
- Consumes: `service.build_default_service()`(Task 4)
- Produces:
  - `conf.settings.BoomRadarConfig(enabled=True, min_change_pct=50.0, news_days_back=7, llm_daily_limit=30)`
  - `app_config.boom_radar: BoomRadarConfig`
  - scheduler job id `boom_radar_daily`(每日 17:30 Asia/Shanghai)
  - `main.py` 挂载 `boom_router`(router 本体在 Task 6 创建,本任务只加 main.py 两行 import/挂载会失败——**因此 main.py 接线放到 Task 6 一起做**;本任务只做 settings + scheduler,scheduler 闭包在服务不存在时会 no-op 之外——闭包内动态 import,Task 6 前手动跑 scheduler 不报错)

**修正:本任务 Files 只改 `conf/settings.py` 与 `src/infra/scheduler.py`;main.py 的 import/挂载归 Task 6。**

- [ ] **Step 1: settings.py 加配置**

在 `ScreenerConfig` 类定义之后(`conf/settings.py` 搜 `class ScreenerConfig` 定位)新增:

```python
class BoomRadarConfig(BaseModel):
    """财报季景气雷达(boom)配置"""
    enabled: bool = True
    min_change_pct: float = 50.0      # 业绩大增阈值 %
    news_days_back: int = 7           # 候选股新闻同步回看天数
    llm_daily_limit: int = 30         # 每日 LLM 深读上限(二期用)
```

在 `AppConfig` 内 `screener: ScreenerConfig = ScreenerConfig()` 行后新增一行:

```python
    boom_radar: BoomRadarConfig = BoomRadarConfig()
```

- [ ] **Step 2: 验证配置加载**

Run: `cd backend && uv run python -c "from conf import app_config; print(app_config.boom_radar.min_change_pct)"`
Expected: 输出 `50.0`

- [ ] **Step 3: scheduler.py 加 job**

在 `_run_financial_earnings_daily` 的 `sched.add_job(...)` 块(约 `scheduler.py:848-864`)之后新增:

```python
    # ── 财报季景气雷达(每日 17:30,预告 job 之后)─────────────────────────
    # 预告窗(1/4/7/10月)内:拉窗口内新披露预告 → 入池 → 新闻同步 → 词典扫描
    # → 候选/命中落库;非财报季秒完。幂等:整窗重扫,hit 唯一约束去重。
    def _run_boom_radar_daily():
        from src.domain.market.boom.service import build_default_service
        try:
            from conf import app_config
            if not app_config.boom_radar.enabled:
                return
            svc = build_default_service()
            svc.run_daily()
        except Exception as e:
            log.error("[BOOM_RADAR_DAILY] failed: %s", e)

    sched.add_job(
        _run_boom_radar_daily,
        CronTrigger(hour=17, minute=30, timezone="Asia/Shanghai"),
        id="boom_radar_daily",
        name="财报季景气雷达每日扫描",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 4: 验证 job 注册**

Run: `cd backend && uv run python -c "from src.infra.scheduler import setup_scheduler" && echo OK`
Expected: 输出 `OK`(import 不报错;不实际启动调度)

再手动跑一次服务快路径(9 月非财报季,不触网):

Run: `cd backend && uv run python -c "
import datetime as dt
from src.domain.market.boom.service import build_default_service
print(build_default_service().run_daily(today=datetime.date(2026, 9, 8)))"`
Expected: 输出含 `'in_season': False`(需本地 DB 可连;若 DB 不可达,记录输出并跳过)

- [ ] **Step 5: Commit**

```bash
git add backend/conf/settings.py backend/src/infra/scheduler.py
git commit -m "feat(boom): BoomRadarConfig 配置+每日17:30雷达job"
```

---

### Task 6: boom_router —— 雷达/下钻/入自选/手动扫描

**Files:**
- Create: `backend/src/api/router/boom_router.py`
- Modify: `backend/main.py`(import 区 `from src.api.router.watchlist_router import ...` 行后加一行;lifespan 模型 import 区加 boom 表 import;include_router 区加一行)
- Test: `backend/tests/api/test_boom_router.py`

**Interfaces:**
- Consumes: `build_default_service()`、`create_boom_repository()`、`watchlist_handler.list_groups/create_group/add_item`
- Produces(全部挂 `/api/v1/boom`):
  - `GET /boom/radar?report_date=&min_change_pct=&categories=` → `{season, report_dates, candidates[{...candidate字段, category_labels, hits_preview[≤5]}], summary{pool, with_hits}}`
  - `GET /boom/radar/{symbol}?report_date=` → `{candidate, hits, category_labels}`
  - `POST /boom/radar/{symbol}/watchlist` body `{report_date}` → `{group, item}`(自动建「财报季雷达」分组)
  - `POST /boom/scan/run` body `{date?}` → run_daily 统计

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/api/test_boom_router.py
"""boom_router 契约测试(service 打桩,不触网/库)。"""
import datetime as dt
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router.boom_router import router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


FAKE_STATS = {"in_season": True, "window_name": "2026Q3预告窗",
              "report_date": "2026-09-30", "pool": 3, "news_synced": 3,
              "hits": 7, "candidates": 3}


def test_radar_list(client):
    with patch("src.api.router.boom_router._radar_data") as fake:
        fake.return_value = {"season": {"in_season": True},
                             "report_dates": ["2026-09-30"],
                             "candidates": [{"symbol": "600519",
                                             "categories": ["supply_tight"],
                                             "hits_preview": []}],
                             "summary": {"pool": 1, "with_hits": 1}}
        r = client.get("/boom/radar")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["candidates"][0]["symbol"] == "600519"


def test_radar_detail_404(client):
    with patch("src.api.router.boom_router._radar_data"):
        with patch("src.api.router.boom_router.create_boom_repository") as rep:
            rep.return_value.get_candidate.return_value = None
            r = client.get("/boom/radar/600000",
                           params={"report_date": "2026-09-30"})
    assert r.status_code == 404


def test_scan_run(client):
    with patch("src.api.router.boom_router.build_default_service") as svc:
        svc.return_value.run_daily.return_value = FAKE_STATS
        r = client.post("/boom/scan/run", json={})
    assert r.status_code == 200
    assert r.json()["data"]["pool"] == 3


def test_watchlist_add(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.get_candidate.return_value = object()
        rep.return_value.set_status.return_value = None
        with patch("src.api.router.boom_router._ensure_watchlist_group") as eg:
            eg.return_value = 99
            with patch("src.api.router.boom_router.watchlist_handler") as wh:
                wh.add_item.return_value = {"code": 0, "data": {"id": 1}}
                r = client.post("/boom/radar/600519/watchlist",
                                json={"report_date": "2026-09-30"})
    assert r.status_code == 200
    wh.add_item.assert_called_once_with(99, {"symbol": "sh600519"})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_boom_router.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现 boom_router.py**

```python
# backend/src/api/router/boom_router.py
"""财报季景气雷达 API。"""
import datetime as dt
import logging

from fastapi import APIRouter, HTTPException

from src.api.handler import watchlist_handler
from src.domain.market.boom.keywords import CATEGORY_LABELS
from src.domain.market.boom.season import announce_window
from src.domain.market.boom.service import (
    build_default_service, to_prefixed,
)
from src.infra.database.market.boom import create_boom_repository

log = logging.getLogger("boom_radar")
router = APIRouter(prefix="/boom", tags=["boom"])

WATCHLIST_GROUP = "财报季雷达"


def _ok(data):
    return {"code": 0, "msg": "ok", "data": data}


def _parse_date(s):
    return dt.date.fromisoformat(s) if s else None


def _candidate_dict(c, hits):
    d = {k: getattr(c, k, None) for k in (
        "symbol", "report_date", "forecast_type", "company_name",
        "announce_date", "change_pct", "forecast_type_label", "categories",
        "keyword_count", "news_hit_count", "llm_score", "llm_verdict",
        "llm_summary", "status")}
    d["category_labels"] = [CATEGORY_LABELS.get(x, x) for x in (c.categories or [])]
    d["hits_preview"] = [
        {"keyword": h.keyword, "category": h.category,
         "category_label": CATEGORY_LABELS.get(h.category, h.category),
         "source_type": h.source_type, "source_date": h.source_date,
         "snippet": h.snippet}
        for h in hits[:5]
    ]
    return d


def _radar_data(report_date, min_change_pct, categories):
    repo = create_boom_repository()
    season = announce_window(dt.date.today())
    rows = repo.get_candidates(report_date=report_date)
    if categories:
        cats = set(categories.split(","))
        rows = [r for r in rows if cats & set(r.categories or [])]
    if min_change_pct is not None:
        rows = [r for r in rows
                if (r.change_pct or 0) >= min_change_pct]
    all_rows = repo.get_candidates(report_date=None, limit=10000)
    report_dates = sorted({str(r.report_date) for r in all_rows}, reverse=True)[:8]
    with_hits = sum(1 for r in rows if r.keyword_count > 0)
    return {
        "season": {
            "in_season": season.in_season, "window_name": season.window_name,
            "window_start": season.window_start,
            "window_end": season.window_end,
            "next_window_start": season.next_window_start,
        },
        "report_dates": report_dates,
        "candidates": [
            _candidate_dict(r, repo.get_hits(r.symbol, r.report_date)) for r in rows
        ],
        "summary": {"pool": len(rows), "with_hits": with_hits},
    }


@router.get("/radar")
def radar(report_date: str = None, min_change_pct: float = None,
          categories: str = None):
    try:
        return _ok(_radar_data(_parse_date(report_date), min_change_pct,
                               categories))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/radar/{symbol}")
def radar_detail(symbol: str, report_date: str = None):
    repo = create_boom_repository()
    rd = _parse_date(report_date)
    if rd is None:
        rows = repo.get_candidates(limit=10000)
        mine = [r for r in rows if r.symbol == symbol]
        if not mine:
            raise HTTPException(404, "candidate not found")
        rd = mine[0].report_date
    c = repo.get_candidate(symbol, rd)
    if c is None:
        raise HTTPException(404, "candidate not found")
    hits = repo.get_hits(symbol, rd)
    data = _candidate_dict(c, hits)
    data["hits"] = data.pop("hits_preview")
    return _ok(data)


def _ensure_watchlist_group() -> int:
    resp = watchlist_handler.list_groups()
    groups = resp.get("data", []) if isinstance(resp, dict) else (resp or [])
    for g in groups:
        if g.get("name") == WATCHLIST_GROUP:
            return g["id"]
    resp = watchlist_handler.create_group({"name": WATCHLIST_GROUP})
    g = resp.get("data") if isinstance(resp, dict) else resp
    return g["id"]


@router.post("/radar/{symbol}/watchlist")
def add_to_watchlist(symbol: str, body: dict):
    rd = _parse_date(body.get("report_date"))
    repo = create_boom_repository()
    c = repo.get_candidate(symbol, rd) if rd else None
    if c is None:
        raise HTTPException(404, "candidate not found")
    gid = _ensure_watchlist_group()
    resp = watchlist_handler.add_item(gid, {"symbol": to_prefixed(symbol)})
    if isinstance(resp, dict) and resp.get("code") not in (0, None):
        raise HTTPException(500, resp.get("msg", "add item failed"))
    repo.set_status(symbol, rd, "added_watchlist")
    return _ok({"group": WATCHLIST_GROUP, "item": (resp or {}).get("data") if isinstance(resp, dict) else resp})


@router.post("/scan/run")
def scan_run(body: dict):
    svc = build_default_service()
    today = _parse_date(body.get("date")) if body and body.get("date") else None
    return _ok(svc.run_daily(today=today))
```

- [ ] **Step 4: main.py 接线**

三处修改:
1. import 区(`main.py:51` watchlist_router 行后)加:

```python
from src.api.router.boom_router import router as boom_router
```

2. lifespan 模型 import 区(`main.py:140` 附近 agent entity import 块后)加:

```python
    # Boom radar: import models so create_all picks up boom_* tables
    from src.infra.database.market.boom import (  # noqa: F401
        BoomCandidateTable, BoomKeywordTable, BoomScanHitTable,
    )
```

3. include_router 区(`app.include_router(watchlist_router, ...)` 行后)加:

```python
    app.include_router(boom_router, prefix="/api/v1")
```

- [ ] **Step 5: 跑测试确认通过 + 手动冒烟**

Run: `cd backend && uv run pytest tests/api/test_boom_router.py -v`
Expected: 4 passed

Run: `cd backend && uv run python -c "
from fastapi import FastAPI
from src.api.router.boom_router import router
app = FastAPI(); app.include_router(router)
print([r.path for r in app.routes if 'boom' in r.path])"`
Expected: 打印 4 条 `/boom/...` 路径

- [ ] **Step 6: Commit**

```bash
git add backend/src/api/router/boom_router.py backend/main.py backend/tests/api/test_boom_router.py
git commit -m "feat(boom): /boom雷达列表/下钻/入自选/手动扫描端点+main接线"
```

---

### Task 7: 词典 CRUD 端点

**Files:**
- Modify: `backend/src/api/router/boom_router.py`(文件末尾追加)
- Test: `backend/tests/api/test_boom_router.py`(追加)

**Interfaces:**
- Produces:
  - `GET /boom/keywords` → `[{id, category, category_label, keyword, weight, enabled}]`
  - `POST /boom/keywords` body `{category, keyword, weight?}` → 新词
  - `PUT /boom/keywords/{kid}` body `{category?, keyword?, weight?, enabled?}`
  - `DELETE /boom/keywords/{kid}`

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 backend/tests/api/test_boom_router.py
def test_keywords_crud(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        kw = type("Kw", (), {"id": 1, "category": "supply_tight", "keyword": "一货难求",
                             "weight": 2, "enabled": True})()
        rep.return_value.list_keywords.return_value = [kw]
        r = client.get("/boom/keywords")
        assert r.status_code == 200
        assert r.json()["data"][0]["category_label"] == "供给紧张"

        rep.return_value.create_keyword.return_value = kw
        r = client.post("/boom/keywords",
                        json={"category": "supply_tight", "keyword": "一货难求",
                              "weight": 2})
        assert r.status_code == 200

        rep.return_value.update_keyword.return_value = kw
        r = client.put("/boom/keywords/1", json={"enabled": False})
        assert r.status_code == 200

        rep.return_value.delete_keyword.return_value = True
        r = client.delete("/boom/keywords/1")
        assert r.status_code == 200


def test_keywords_create_validates_category(client):
    with patch("src.api.router.boom_router.create_boom_repository"):
        r = client.post("/boom/keywords",
                        json={"category": "no_such_cat", "keyword": "x"})
    assert r.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_boom_router.py -v -k keywords`
Expected: FAIL(404 Not Found,路由不存在)

- [ ] **Step 3: 实现端点(boom_router.py 末尾追加)**

```python
@router.get("/keywords")
def keywords_list():
    repo = create_boom_repository()
    return _ok([
        {"id": k.id, "category": k.category,
         "category_label": CATEGORY_LABELS.get(k.category, k.category),
         "keyword": k.keyword, "weight": k.weight, "enabled": k.enabled}
        for k in repo.list_keywords(enabled_only=False)
    ])


@router.post("/keywords")
def keywords_create(body: dict):
    if body.get("category") not in CATEGORY_LABELS:
        raise HTTPException(400, f"category must be one of {list(CATEGORY_LABELS)}")
    repo = create_boom_repository()
    row = repo.create_keyword(body["category"], body["keyword"],
                              int(body.get("weight", 1)))
    return _ok({"id": row.id})


@router.put("/keywords/{kid}")
def keywords_update(kid: int, body: dict):
    repo = create_boom_repository()
    row = repo.update_keyword(kid, **{k: v for k, v in body.items()
                                      if k in ("category", "keyword", "weight", "enabled")})
    if row is None:
        raise HTTPException(404, "keyword not found")
    return _ok({"id": kid})


@router.delete("/keywords/{kid}")
def keywords_delete(kid: int):
    repo = create_boom_repository()
    if not repo.delete_keyword(kid):
        raise HTTPException(404, "keyword not found")
    return _ok({"id": kid})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_boom_router.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/router/boom_router.py backend/tests/api/test_boom_router.py
git commit -m "feat(boom): 景气词典CRUD端点(分类校验)"
```

---

### Task 8: 前端雷达页(一期 MVP UI)

**Files:**
- Create: `frontend/apps/web/src/hooks/useBoomRadar.ts`
- Create: `frontend/apps/web/src/pages/EarningsRadar.tsx`
- Create: `frontend/apps/web/src/pages/EarningsRadar.css`
- Create: `frontend/apps/web/src/components/BoomDrillModal.tsx`
- Modify: `frontend/apps/web/src/App.tsx`(lazy import 区加一行;`/board` Route 后加一行)
- Modify: `frontend/apps/web/src/components/Layout.tsx`(「研究」组 `/screener` 项后加一项)

**Interfaces:**
- Consumes: 后端 `/api/v1/boom/radar`、`/boom/radar/{symbol}`、`/boom/radar/{symbol}/watchlist`;ui 组件 `Button/Card/Tabs/Modal/PageHeader/StateView`;`useIntervalWhenVisible`
- Produces: 路由 `/earnings-radar`;页面组件 `EarningsRadar`;`BoomDrillModal({symbol, reportDate, onClose})`

- [ ] **Step 1: 写 hook**

```typescript
// frontend/apps/web/src/hooks/useBoomRadar.ts
/**
 * 财报季景气雷达数据 hook。
 * GET /boom/radar —— 财报季状态 + 候选池;可见时 60s 轮询。
 */
import {useCallback, useEffect, useState} from 'react';
import {getApiBase} from '../lib/api';
import {useIntervalWhenVisible} from './useIntervalWhenVisible';

const API_BASE = getApiBase();

export interface BoomHit {
  keyword: string;
  category: string;
  category_label: string;
  source_type: string;
  source_date: string | null;
  snippet: string;
}

export interface BoomCandidate {
  symbol: string;
  report_date: string;
  forecast_type: string;
  company_name: string | null;
  announce_date: string | null;
  change_pct: number | null;
  forecast_type_label: string | null;
  categories: string[];
  category_labels: string[];
  keyword_count: number;
  news_hit_count: number;
  llm_score: number | null;
  llm_verdict: string | null;
  llm_summary: string | null;
  status: string;
  hits_preview: BoomHit[];
}

export interface BoomRadarData {
  season: {
    in_season: boolean;
    window_name: string;
    window_start: string;
    window_end: string;
    next_window_start: string;
  };
  report_dates: string[];
  candidates: BoomCandidate[];
  summary: {pool: number; with_hits: number};
}

export function useBoomRadar(params: {reportDate?: string; categories?: string}) {
  const [data, setData] = useState<BoomRadarData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const qs = new URLSearchParams();
    if (params.reportDate) qs.set('report_date', params.reportDate);
    if (params.categories) qs.set('categories', params.categories);
    const url = `${API_BASE}/boom/radar${qs.toString() ? '?' + qs.toString() : ''}`;
    setLoading(true);
    fetch(url)
      .then((r) => r.json())
      .then((json) => {
        if (json.code === 0) {
          setData(json.data);
          setError(null);
        } else {
          setError(json.msg || '请求失败');
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [params.reportDate, params.categories]);

  useEffect(() => {
    load();
  }, [load]);

  useIntervalWhenVisible(load, 60_000);

  return {data, loading, error, reload: load};
}
```

- [ ] **Step 2: 写下钻 Modal**

```tsx
// frontend/apps/web/src/components/BoomDrillModal.tsx
/** 财报雷达候选下钻:命中原文摘录 + LLM 景气分析。 */
import {useEffect, useState} from 'react';
import {getApiBase} from '../lib/api';
import {Button, Modal, StateView} from './ui';
import type {BoomCandidate, BoomHit} from '../hooks/useBoomRadar';

const API_BASE = getApiBase();

interface Detail extends BoomCandidate {
  hits: BoomHit[];
}

interface Props {
  symbol: string;
  reportDate: string;
  onClose: () => void;
}

export function BoomDrillModal({symbol, reportDate, onClose}: Props) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [adding, setAdding] = useState(false);
  const [addMsg, setAddMsg] = useState<string | null>(null);

  useEffect(() => {
    const qs = new URLSearchParams({report_date: reportDate});
    fetch(`${API_BASE}/boom/radar/${symbol}?${qs.toString()}`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0) {
          setDetail(j.data);
          setState('ready');
        } else {
          setState('error');
        }
      })
      .catch(() => setState('error'));
  }, [symbol, reportDate]);

  const addWatchlist = async () => {
    if (adding) return;
    setAdding(true);
    setAddMsg(null);
    try {
      const r = await fetch(`${API_BASE}/boom/radar/${symbol}/watchlist`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({report_date: reportDate}),
      });
      const j = await r.json();
      setAddMsg(j.code === 0 ? '已加入自选「财报季雷达」分组' : j.msg || '添加失败');
    } catch {
      setAddMsg('网络错误');
    } finally {
      setAdding(false);
    }
  };

  const title = detail
    ? `${detail.company_name ?? ''} ${detail.symbol} · ${detail.forecast_type_label ?? ''} ${detail.change_pct != null ? detail.change_pct.toFixed(1) + '%' : ''}`
    : `${symbol} 详情`;

  return (
    <Modal open onClose={onClose} title={title} width={760}>
      {state !== 'ready' ? (
        <StateView state={state === 'error' ? 'error' : 'loading'} onRetry={onClose} />
      ) : detail ? (
        <div className="bdm">
          <div className="bdm-actions">
            <Button variant="secondary" size="sm" onClick={addWatchlist} loading={adding}>
              加入自选
            </Button>
            {addMsg && <span className="bdm-addmsg">{addMsg}</span>}
          </div>
          {detail.llm_score != null && (
            <div className="bdm-section">
              <div className="bdm-section-title">
                LLM 景气分析 · {detail.llm_score} 分 · {detail.llm_verdict}
              </div>
              <p className="bdm-llm">{detail.llm_summary}</p>
            </div>
          )}
          <div className="bdm-section">
            <div className="bdm-section-title">命中明细({detail.hits.length})</div>
            {detail.hits.length === 0 ? (
              <StateView state="empty" text="无关键词命中" />
            ) : (
              detail.hits.map((h, i) => (
                <div className="bdm-hit" key={i}>
                  <span className="bdm-hit-tag">{h.category_label}</span>
                  <span className="bdm-hit-kw">{h.keyword}</span>
                  <span className="bdm-hit-src">
                    {h.source_type === 'forecast' ? '业绩预告' : h.source_type === 'survey' ? '调研' : '新闻'}
                    {h.source_date ? ` · ${h.source_date}` : ''}
                  </span>
                  <p className="bdm-hit-snippet">{h.snippet}</p>
                </div>
              ))
            )}
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
```

- [ ] **Step 3: 写页面 + CSS**

```tsx
// frontend/apps/web/src/pages/EarningsRadar.tsx
/** 财报季景气雷达:业绩大增 × 文本景气信号 候选池。 */
import {useMemo, useState} from 'react';
import {Button, Card, PageHeader, StateView} from '../components/ui';
import {BoomDrillModal} from '../components/BoomDrillModal';
import {useBoomRadar} from '../hooks/useBoomRadar';
import {CATEGORY_LABELS} from './EarningsRadar.categories';

export function EarningsRadar() {
  const [reportDate, setReportDate] = useState<string>('');
  const [activeCats, setActiveCats] = useState<Set<string>>(new Set());
  const [drill, setDrill] = useState<{symbol: string; reportDate: string} | null>(null);

  const params = useMemo(
    () => ({
      reportDate: reportDate || undefined,
      categories: activeCats.size ? Array.from(activeCats).join(',') : undefined,
    }),
    [reportDate, activeCats],
  );
  const {data, loading, error} = useBoomRadar(params);

  const toggleCat = (c: string) => {
    setActiveCats((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  };

  const season = data?.season;
  const rows = data?.candidates ?? [];

  return (
    <div className="er-page">
      <PageHeader title="财报雷达" subtitle="财报季 · 业绩大增 × 景气关键词 候选池" />

      <Card className="er-season">
        {loading && !data ? (
          <StateView state="loading" />
        ) : error ? (
          <StateView state="error" text={error} />
        ) : season ? (
          season.in_season ? (
            <div>
              <span className="er-season-badge er-season-badge--on">财报季</span>
              <b className="er-season-name">{season.window_name}</b>
              <span className="er-season-meta">
                {season.window_start} ~ {season.window_end} · 候选{' '}
                <b className="num">{data!.summary.pool}</b> 只 · 命中景气词{' '}
                <b className="num is-up">{data!.summary.with_hits}</b> 只
              </span>
            </div>
          ) : (
            <div>
              <span className="er-season-badge">休渔期</span>
              <span className="er-season-meta">
                下一预告窗 <b className="num">{season.next_window_start}</b> 开始,到时见
              </span>
            </div>
          )
        ) : null}
      </Card>

      <div className="er-controls">
        <select
          className="er-select"
          value={reportDate}
          onChange={(e) => setReportDate(e.target.value)}
        >
          <option value="">最新报告期</option>
          {(data?.report_dates ?? []).map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        {Object.entries(CATEGORY_LABELS).map(([code, label]) => (
          <button
            key={code}
            className={`er-cat ${activeCats.has(code) ? 'er-cat--on' : ''}`}
            onClick={() => toggleCat(code)}
          >
            {label}
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <StateView state="empty" text="暂无候选(财报季每日 17:30 自动扫描)" />
      ) : (
        <table className="er-table">
          <thead>
            <tr>
              <th>代码</th><th>简称</th><th>类型</th><th>幅度</th>
              <th>景气信号</th><th>命中数</th><th>LLM</th><th>状态</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={`${c.symbol}-${c.report_date}`}
                  onClick={() => setDrill({symbol: c.symbol, reportDate: c.report_date})}>
                <td className="num er-sym">{c.symbol}</td>
                <td>{c.company_name ?? '-'}</td>
                <td>{c.forecast_type === 'express' ? '快报' : '预告'}</td>
                <td className="num is-up">
                  {c.change_pct != null ? `+${c.change_pct.toFixed(1)}%` : '-'}
                </td>
                <td>
                  {c.category_labels?.length
                    ? c.category_labels.map((l) => (
                        <span className="er-tag" key={l}>{l}</span>
                      ))
                    : '-'}
                </td>
                <td className="num">{c.keyword_count}</td>
                <td className="num">
                  {c.llm_score != null ? `${c.llm_score}·${c.llm_verdict}` : '-'}
                </td>
                <td>{c.status === 'added_watchlist' ? '已入自选' : c.status}</td>
                <td>
                  <Button variant="secondary" size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDrill({symbol: c.symbol, reportDate: c.report_date});
                          }}>
                    详情
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {drill && (
        <BoomDrillModal
          symbol={drill.symbol}
          reportDate={drill.reportDate}
          onClose={() => setDrill(null)}
        />
      )}
    </div>
  );
}
```

```typescript
// frontend/apps/web/src/pages/EarningsRadar.categories.ts
/** 景气分类码 → 中文标签(与后端 keywords.CATEGORY_LABELS 对应,展示用副本)。 */
export const CATEGORY_LABELS: Record<string, string> = {
  supply_tight: '供给紧张',
  boom_up: '景气上行',
  beat: '超预期',
  price_up: '价格上行',
  demand_strong: '需求旺盛',
  new_product: '新品放量',
  expand: '拓展替代',
};
```

```css
/* frontend/apps/web/src/pages/EarningsRadar.css */
.er-page {
  padding: 16px;
  max-width: 1200px;
  margin: 0 auto;
}

.er-season {
  margin-bottom: 12px;
}

.er-season-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-bold);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  margin-right: 8px;
}

.er-season-badge--on {
  background: var(--color-up-light);
  color: var(--color-up);
}

.er-season-name {
  margin-right: 10px;
}

.er-season-meta {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.er-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.er-select {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  padding: 4px 8px;
}

.er-cat {
  padding: 3px 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}

.er-cat--on {
  border-color: var(--color-accent);
  background: var(--color-accent);
  color: #fff;
}

.er-table {
  width: 100%;
  font-size: 13px;
  border-collapse: collapse;
}

.er-table th {
  text-align: left;
  padding: 8px 6px;
  border-bottom: 1px solid var(--color-border-strong);
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-semibold);
}

.er-table td {
  padding: 6px;
  border-bottom: 1px solid var(--color-border);
}

.er-table tbody tr {
  cursor: pointer;
}

.er-table tbody tr:hover {
  background: var(--color-surface);
}

.er-sym {
  color: var(--color-accent);
  font-family: monospace;
}

.er-tag {
  display: inline-block;
  font-size: var(--text-xs);
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  background: var(--color-up-light);
  color: var(--color-up);
  margin-right: 4px;
  font-weight: var(--font-weight-semibold);
}

/* BoomDrillModal */
.bdm-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: var(--space-2);
}

.bdm-addmsg {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.bdm-section {
  margin-bottom: var(--space-3);
}

.bdm-section-title {
  font-weight: var(--font-weight-bold);
  margin-bottom: 6px;
}

.bdm-llm {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
}

.bdm-hit {
  padding: 6px 0;
  border-bottom: 1px solid var(--color-border);
}

.bdm-hit-tag {
  font-size: var(--text-xs);
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  background: var(--color-up-light);
  color: var(--color-up);
  margin-right: 6px;
}

.bdm-hit-kw {
  font-weight: var(--font-weight-semibold);
  margin-right: 8px;
}

.bdm-hit-src {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.bdm-hit-snippet {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-text-secondary);
}
```

- [ ] **Step 4: 接线 App.tsx + Layout.tsx**

App.tsx lazy import 区(`/board` 行后)加:

```tsx
const EarningsRadar = lazy(() => import('./pages/EarningsRadar').then(m => ({default: m.EarningsRadar})));
```

`/board` Route 后加:

```tsx
          <Route path="/earnings-radar" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><EarningsRadar /></Suspense>} />
```

Layout.tsx「研究」组 `{path: '/screener', ...}` 项后加:

```tsx
      {path: '/earnings-radar', label: '财报雷达', icon: Icon.analytics},
```

- [ ] **Step 5: 构建验证**

Run: `cd frontend/apps/web && npm run build`
Expected: 构建成功,无 TS 报错(若有 `--noEmit` 检查随 build 跑)

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/hooks/useBoomRadar.ts frontend/apps/web/src/pages/EarningsRadar.tsx frontend/apps/web/src/pages/EarningsRadar.css frontend/apps/web/src/pages/EarningsRadar.categories.ts frontend/apps/web/src/components/BoomDrillModal.tsx frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(boom-web): 财报雷达页——财报季状态条/分类筛选/候选表/下钻/入自选"
```

---

### Task 9: LLM 景气分析师(prompt + JSON 解析)

**Files:**
- Create: `backend/src/domain/market/boom/llm_analyst.py`
- Test: `backend/tests/domain/boom/test_llm_analyst.py`

**Interfaces:**
- Consumes: `render_prompt`/`load_prompt_from_db_or`(`src.domain.market.intel.agents.base`)、`LLMManager.get_provider().complete(prompt, temperature, max_tokens)`
- Produces:
  - `llm_analyst.DEFAULT_BOOM_ANALYST_PROMPT: str`(DB 模板名 `boom_analyst`)
  - `llm_analyst.build_prompt(candidate: dict, hits: list[dict]) -> str`
  - `llm_analyst.parse_boom_json(text: str) -> dict`(容错:剥 markdown 代码栅栏、截取首 `{` 到末 `}`;失败返回 `{"boom_score": None, "verdict": "parse_error", "summary": "", "risks": []}`)
  - `llm_analyst.analyze_candidate(candidate, hits) -> dict`(async;LLM 不可用抛 `RuntimeError`)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/boom/test_llm_analyst.py
"""LLM 景气分析师:prompt 组装 + JSON 容错解析。"""
import pytest

from src.domain.market.boom import llm_analyst
from src.domain.market.boom.llm_analyst import build_prompt, parse_boom_json


def test_build_prompt_contains_facts(monkeypatch):
    # 无 DB prompt 模板时用内置默认,测试不依赖 DB
    monkeypatch.setattr(
        llm_analyst, "load_prompt_from_db_or",
        lambda name, fallback: fallback,
    )
    prompt = build_prompt(
        {"symbol": "600519", "company_name": "贵州茅台",
         "change_pct": 60.0, "forecast_type_label": "预增"},
        [{"keyword": "供不应求", "category_label": "供给紧张",
          "source_type": "业绩预告", "snippet": "产品供不应求"}],
    )
    assert "600519" in prompt and "60.0" in prompt and "供不应求" in prompt


def test_parse_plain_json():
    out = parse_boom_json('{"boom_score": 82, "verdict": "focus", '
                          '"summary": "量价齐升", "risks": ["估值高"]}')
    assert out["boom_score"] == 82
    assert out["verdict"] == "focus"


def test_parse_fenced_json():
    text = '好的,分析如下:\n```json\n{"boom_score": 65, "verdict": "watch", "summary": "s", "risks": []}\n```'
    out = parse_boom_json(text)
    assert out["boom_score"] == 65


def test_parse_garbage_fallback():
    out = parse_boom_json("模型抽风了,没有 JSON")
    assert out["verdict"] == "parse_error"
    assert out["boom_score"] is None


def test_parse_clamps_score():
    out = parse_boom_json('{"boom_score": 150, "verdict": "focus", "summary": "", "risks": []}')
    assert out["boom_score"] == 100


def test_parse_validates_verdict():
    out = parse_boom_json('{"boom_score": 50, "verdict": "强烈买入", "summary": "", "risks": []}')
    assert out["verdict"] == "watch"          # 非法枚举 → watch
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/boom/test_llm_analyst.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现 llm_analyst.py**

```python
# backend/src/domain/market/boom/llm_analyst.py
"""LLM 景气深读:规则命中后的第二道筛(仅候选池,token 可控)。"""
import json
import re
from typing import Any

from src.domain.market.intel.agents.base import (
    load_prompt_from_db_or, render_prompt,
)

VALID_VERDICTS = ("focus", "watch", "exclude")

DEFAULT_BOOM_ANALYST_PROMPT = """你是A股基本面分析师。以下股票在业绩预告/快报中出现大幅预增,且公告/新闻文本命中了景气关键词。请判断其景气信号的成色。

股票: {{ symbol }} {{ company_name }}
预告: {{ forecast_type_label }},变动幅度 {{ change_pct }}%
命中关键词(附摘录):
{% for h in hits %}- [{{ h.category_label }}] {{ h.keyword }}({{ h.source_type }}): {{ h.snippet }}
{% endfor %}
请输出 JSON(不要输出其他内容):
{"boom_score": 0-100整数, "verdict": "focus|watch|exclude", "summary": "80字内景气判断", "risks": ["风险点1", "风险点2"]}
判定标准:多条独立来源互相印证、涉及量价(供给紧张+价格上行)→ focus;单条且语境一般 → watch;否定语境/蹭概念/周期见顶 → exclude。"""


def build_prompt(candidate: dict, hits: list[dict]) -> str:
    return render_prompt(
        load_prompt_from_db_or("boom_analyst", DEFAULT_BOOM_ANALYST_PROMPT),
        symbol=candidate.get("symbol", ""),
        company_name=candidate.get("company_name") or "",
        forecast_type_label=candidate.get("forecast_type_label") or "预增",
        change_pct=candidate.get("change_pct") or 0,
        hits=hits or [],
    )


def parse_boom_json(text: str) -> dict:
    fallback = {"boom_score": None, "verdict": "parse_error",
                "summary": "", "risks": []}
    if not text:
        return fallback
    text = re.sub(r"```(?:json)?", "", text)
    lo, hi = text.find("{"), text.rfind("}")
    if lo < 0 or hi <= lo:
        return {**fallback, "summary": text[:200]}
    try:
        obj = json.loads(text[lo:hi + 1])
    except json.JSONDecodeError:
        return {**fallback, "summary": text[:200]}
    score = obj.get("boom_score")
    score = max(0, min(100, int(score))) if isinstance(score, (int, float)) else None
    verdict = obj.get("verdict")
    verdict = verdict if verdict in VALID_VERDICTS else "watch"
    return {
        "boom_score": score,
        "verdict": verdict,
        "summary": str(obj.get("summary", ""))[:300],
        "risks": [str(r)[:60] for r in (obj.get("risks") or [])][:5],
    }


async def analyze_candidate(candidate: dict, hits: list[dict]) -> dict:
    """调用默认 LLM 分析单个候选;失败上抛,由调用方降级。"""
    from src.infra.llm.manager import LLMManager

    manager = LLMManager()
    provider = manager.get_provider()
    if provider is None:
        raise RuntimeError("LLM provider not configured")
    prompt = build_prompt(candidate, hits)
    result = await provider.complete(prompt, temperature=0.2, max_tokens=512)
    return parse_boom_json(result.content)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/boom/test_llm_analyst.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/boom/llm_analyst.py backend/tests/domain/boom/test_llm_analyst.py
git commit -m "feat(boom): LLM景气深读prompt+容错JSON解析(评分截断/枚举校验)"
```

---

### Task 10: LLM 深读接入 service + 手动分析端点 + job 集成

**Files:**
- Modify: `backend/src/domain/market/boom/service.py`(类内加 `llm_deep_read`;`run_daily` 末尾加钩子)
- Modify: `backend/src/api/router/boom_router.py`(加 `POST /boom/analyze/{symbol}`)
- Modify: `backend/src/infra/scheduler.py`(`_run_boom_radar_daily` 闭包内 run_daily 后加深读)
- Test: `backend/tests/domain/boom/test_service.py`(追加)、`backend/tests/api/test_boom_router.py`(追加)

**Interfaces:**
- Consumes: `llm_analyst.analyze_candidate(candidate: dict, hits: list[dict]) -> dict`(Task 9)
- Produces:
  - `BoomRadarService.llm_deep_read(report_date: dt.date | None, limit: int | None) -> dict` → `{"analyzed": n, "failed": n, "skipped": n}`(只分析 `llm_score IS NULL` 且 `keyword_count>0` 的候选,按 `keyword_count` 降序取前 limit;单股失败计数继续;成功 `mark_llm`)
  - `POST /boom/analyze/{symbol}` body `{report_date}` → 单股重跑深读
  - job:17:30 run_daily 后,若 `candidates>0` 则 `asyncio.run(svc.llm_deep_read())`

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 backend/tests/domain/boom/test_service.py
class FakeRepoWithLLM(FakeRepo):
    def __init__(self):
        super().__init__()
        self.llm_calls = []
        _c = {"symbol": "600001", "report_date": dt.date(2026, 9, 30),
              "forecast_type": "preannounce", "company_name": "X",
              "announce_date": dt.date(2026, 10, 12), "change_pct": 60.0,
              "forecast_type_label": "预增", "categories": ["supply_tight"],
              "keyword_count": 3, "news_hit_count": 1, "llm_score": None,
              "llm_verdict": None, "llm_summary": None}
        self.candidates = [_c]
        self._c = _c

    def get_candidates(self, report_date=None, limit=1000):
        return [type("C", (), self._c)()]

    def mark_llm(self, symbol, report_date, score, verdict, summary):
        self.llm_calls.append((symbol, score, verdict))


def test_llm_deep_read_writes_back(monkeypatch):
    import asyncio
    repo = FakeRepoWithLLM()
    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0})
    async def fake_analyze(candidate, hits):
        return {"boom_score": 82, "verdict": "focus", "summary": "量价齐升",
                "risks": []}
    monkeypatch.setattr("src.domain.market.boom.service.analyze_candidate",
                        fake_analyze)
    stats = asyncio.run(svc.llm_deep_read())
    assert stats["analyzed"] == 1
    assert repo.llm_calls == [("600001", 82, "focus")]


def test_llm_deep_read_degrades_on_error(monkeypatch):
    import asyncio
    repo = FakeRepoWithLLM()
    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0})
    async def boom(candidate, hits):
        raise RuntimeError("llm down")
    monkeypatch.setattr("src.domain.market.boom.service.analyze_candidate", boom)
    stats = asyncio.run(svc.llm_deep_read())
    assert stats["analyzed"] == 0 and stats["failed"] == 1
    assert repo.llm_calls == []                 # 失败不回写
```

```python
# 追加到 backend/tests/api/test_boom_router.py
def test_analyze_endpoint(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        cand = type("C", (), {"symbol": "600519", "report_date": dt.date(2026, 9, 30),
                              "llm_score": None, "keyword_count": 2,
                              "company_name": "X", "change_pct": 60.0,
                              "forecast_type_label": "预增",
                              "forecast_type": "preannounce",
                              "categories": ["supply_tight"],
                              "announce_date": dt.date(2026, 10, 12),
                              "keyword_count": 2, "news_hit_count": 1})()
        rep.return_value.get_candidate.return_value = cand
        rep.return_value.get_hits.return_value = []
        with patch("src.api.router.boom_router._run_analyze") as ra:
            ra.return_value = {"boom_score": 88, "verdict": "focus",
                               "summary": "s", "risks": []}
            r = client.post("/boom/analyze/600519",
                            json={"report_date": "2026-09-30"})
    assert r.status_code == 200
    assert r.json()["data"]["boom_score"] == 88
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/boom/test_service.py tests/api/test_boom_router.py -v -k "llm_deep_read or analyze"`
Expected: FAIL(`AttributeError: llm_deep_read` / 404)

- [ ] **Step 3: 实现(service.py)**

文件头 import 区加:

```python
from src.domain.market.boom.llm_analyst import analyze_candidate
from src.domain.market.boom.keywords import CATEGORY_LABELS
```

`BoomRadarService` 类内(`run_daily` 之后)加:

```python
    async def llm_deep_read(self, report_date=None, limit=None) -> dict:
        """对候选池(有命中、未分析)跑 LLM 深读;失败降级不回写。"""
        limit = limit or self.config.get("llm_daily_limit", 30)
        rows = [r for r in self.repo.get_candidates(report_date=report_date)
                if r.keyword_count > 0 and r.llm_score is None]
        rows.sort(key=lambda r: r.keyword_count, reverse=True)
        rows = rows[:limit]
        analyzed = failed = 0
        for c in rows:
            hits = [
                {"keyword": h.keyword,
                 "category_label": CATEGORY_LABELS.get(h.category, h.category),
                 "source_type": h.source_type, "snippet": h.snippet}
                for h in self.repo.get_hits(c.symbol, c.report_date)
            ]
            cand = {"symbol": c.symbol, "company_name": c.company_name,
                    "change_pct": c.change_pct,
                    "forecast_type_label": c.forecast_type_label}
            try:
                out = await analyze_candidate(cand, hits)
            except Exception as e:
                log.warning("llm deep read %s failed: %s", c.symbol, e)
                failed += 1
                continue
            if out["verdict"] == "parse_error":
                failed += 1
                continue
            self.repo.mark_llm(c.symbol, c.report_date, out["boom_score"],
                               out["verdict"], out["summary"])
            analyzed += 1
        return {"analyzed": analyzed, "failed": failed,
                "skipped": max(0, limit - len(rows))}
```

- [ ] **Step 4: 实现(boom_router.py 末尾追加)**

```python
@router.post("/analyze/{symbol}")
def analyze_symbol(symbol: str, body: dict):
    rd = _parse_date(body.get("report_date"))
    return _ok(_run_analyze(symbol, rd))


def _run_analyze(symbol: str, report_date):
    import asyncio

    repo = create_boom_repository()
    c = repo.get_candidate(symbol, report_date) if report_date else None
    if c is None:
        raise HTTPException(404, "candidate not found")
    from src.domain.market.boom.llm_analyst import analyze_candidate
    from src.domain.market.boom.keywords import CATEGORY_LABELS

    hits = [{"keyword": h.keyword,
             "category_label": CATEGORY_LABELS.get(h.category, h.category),
             "source_type": h.source_type, "snippet": h.snippet}
            for h in repo.get_hits(symbol, report_date)]
    cand = {"symbol": c.symbol, "company_name": c.company_name,
            "change_pct": c.change_pct,
            "forecast_type_label": c.forecast_type_label}
    try:
        out = asyncio.run(analyze_candidate(cand, hits))
    except Exception as e:
        raise HTTPException(503, f"LLM 调用失败: {e}")
    if out["verdict"] != "parse_error":
        repo.mark_llm(symbol, report_date, out["boom_score"], out["verdict"],
                      out["summary"])
    return out
```

- [ ] **Step 5: scheduler 闭包加深读**

`_run_boom_radar_daily` 内 `svc.run_daily()` 改为:

```python
            stats = svc.run_daily()
            if stats.get("candidates"):
                import asyncio
                svc.llm_deep_read()
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/boom/test_service.py tests/api/test_boom_router.py -v`
Expected: 全部 passed(9 + 7)

- [ ] **Step 7: Commit**

```bash
git add backend/src/domain/market/boom/service.py backend/src/api/router/boom_router.py backend/src/infra/scheduler.py backend/tests/domain/boom/test_service.py backend/tests/api/test_boom_router.py
git commit -m "feat(boom): LLM深读接入每日job+单股手动分析端点(失败降级)"
```

---

### Task 11: 调研纪要文本源(探测式接入)

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py`(`fetch_earnings_batch` 方法后新增 `fetch_survey`)
- Modify: `backend/src/domain/market/boom/service.py`(`run_daily` 循环内 news 之后加 survey 扫描)
- Test: `backend/tests/domain/boom/test_service.py`(追加)

**Interfaces:**
- Produces:
  - `AkshareProvider.fetch_survey(symbol: str, months_back: int = 6) -> list[dict]`(每条 `{survey_date: dt.date|None, org_types: str, q_a_text: str}`;接口缺失/失败返回 `[]`,不抛异常)
  - service 扫描 `source_type="survey"` 命中(同步方式:直接调 provider,每日每候选股一次)

- [ ] **Step 1: 探测 akshare 可用接口**

Run: `cd backend && uv run python -c "
import akshare as ak
names = [n for n in dir(ak) if 'survey' in n.lower() or 'diaoyan' in n.lower()]
print(names)"`
Expected: 打印非空列表(东财机构调研系列,如 `stock_survey_*`);**把实际名字填入 Step 2 的 `_SURVEY_FNS` 元组首位**;若为空,本任务改为只提交测试(跳过实现,记入 commit message)。

- [ ] **Step 2: 实现 provider 方法(akshare_provider.py,`fetch_earnings_batch` 后)**

```python
    # ── 机构调研(财报雷达景气文本源)────────────────────────────────
    _SURVEY_FN = "stock_survey_details_em"   # 以 Step 1 探测到的实际接口名为准

    def fetch_survey(self, symbol: str, months_back: int = 6) -> list[dict]:
        """机构调研纪要文本(防御式):接口缺失/列名差异/异常一律返回 []。

        返回 [{survey_date, org_types, q_a_text}]。
        """
        import akshare as ak
        import datetime as dt
        fn = getattr(ak, self._SURVEY_FN, None)
        if fn is None:
            return []
        try:
            df = self._retry_all(lambda: fn(symbol=symbol))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        cutoff = dt.date.today() - dt.timedelta(days=30 * months_back)
        date_cols = [c for c in df.columns if "日期" in str(c)]
        out = []
        for _, r in df.iterrows():
            row = r.to_dict()
            sd = None
            for c in date_cols:
                v = row.get(c)
                if isinstance(v, (dt.date, dt.datetime)):
                    sd = v.date() if isinstance(v, dt.datetime) else v
                    break
            if sd is None or sd < cutoff:
                continue
            text = "。".join(str(v) for v in row.values()
                            if isinstance(v, str) and len(v) > 8)
            org = next((str(v) for k, v in row.items()
                        if "机构" in str(k) and isinstance(v, str)), "")
            out.append({"survey_date": sd, "org_types": org, "q_a_text": text})
        return out
```

- [ ] **Step 3: 追加 service 测试**

```python
# 追加到 backend/tests/domain/boom/test_service.py
def test_survey_source_scanned(monkeypatch):
    repo = FakeRepo()
    news_sync = FakeNewsSync()

    class SurveyProvider:
        def fetch_survey(self, symbol, months_back=6):
            return [{"survey_date": dt.date(2026, 10, 10), "org_types": "基金",
                      "q_a_text": "公司表示当前产品供不应求,新产能Q4释放。"}]

    svc = BoomRadarService(repo, FakeForecastRepo(), news_sync, FakeNewsRepo(),
                           {"min_change_pct": 50.0}, survey_provider=SurveyProvider())
    stats = svc.run_daily(today=dt.date(2026, 10, 15))
    survey_hits = [h for h in repo.hits if h["source_type"] == "survey"]
    assert survey_hits and survey_hits[0]["keyword"] == "供不应求"


def test_survey_provider_failure_degrades(monkeypatch):
    repo = FakeRepo()

    class BadProvider:
        def fetch_survey(self, symbol, months_back=6):
            raise RuntimeError("boom")

    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(), FakeNewsRepo(),
                           {"min_change_pct": 50.0}, survey_provider=BadProvider())
    stats = svc.run_daily(today=dt.date(2026, 10, 15))
    assert stats["in_season"] is True          # 不因调研源崩溃
```

- [ ] **Step 4: 改 service(构造器加参 + 循环内扫描)**

构造器签名改为 `def __init__(self, repo, forecast_repo, news_sync, news_repo, config: dict, survey_provider=None)`,末尾存 `self.survey_provider = survey_provider`。`run_daily` 的 pool 循环内、news 扫描块之后加:

```python
            # 文本源3:调研纪要(二期;provider 未注入则跳过)
            if self.survey_provider is not None:
                try:
                    surveys = self.survey_provider.fetch_survey(f.symbol)
                except Exception:
                    surveys = []
                for sv in surveys:
                    sv_hits = scan_text(sv.get("q_a_text", ""), keywords)
                    hit_rows += [
                        {"symbol": f.symbol, "source_type": "survey",
                         "source_ref": f"{f.symbol}|survey|{sv.get('survey_date')}",
                         "source_date": sv.get("survey_date"),
                         "keyword": h.keyword, "category": h.category,
                         "snippet": h.snippet}
                        for h in sv_hits
                    ]
                    news_hits += len(sv_hits)
```

`build_default_service` 的 `BoomRadarService(...)` 调用加 `survey_provider=AkshareProvider()`。

- [ ] **Step 5: 跑测试 + 手动探测冒烟**

Run: `cd backend && uv run pytest tests/domain/boom/test_service.py -v`
Expected: 全部 passed

Run: `cd backend && uv run python -c "
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
rows = AkshareProvider().fetch_survey('600519')
print(len(rows), rows[0]['survey_date'] if rows else '')"`
Expected: 打印条数(可为 0);无异常

- [ ] **Step 6: Commit**

```bash
git add backend/src/domain/market/sync/providers/akshare_provider.py backend/src/domain/market/boom/service.py backend/tests/domain/boom/test_service.py
git commit -m "feat(boom): 调研纪要文本源防御式接入(缺接口/失败降级空)"
```

---

### Task 12: 正式报表窗候选补充(单季净利同比)

**Files:**
- Modify: `backend/src/infra/database/market/financial_full.py`(`EarningsForecastRepository` 内加 bulk 查询)
- Modify: `backend/src/domain/market/boom/service.py`(`run_daily` 内 formal 分支)
- Test: `backend/tests/domain/boom/test_service.py`(追加)

**Interfaces:**
- Consumes: `season.is_formal_window(today)`
- Produces:
  - `EarningsForecastRepository.get_quarter_yoy_growth(report_date, min_pct) -> list[dict]`(原生 SQL:用累计净利差分出单季,同比 ≥ min_pct 的 symbol 列表;返回 `[{symbol, report_date, q_np, q_np_prev, yoy_pct}]`)
  - service:`run_daily` 在正式窗内追加该来源的候选(`forecast_type="formal"`,`forecast_type_label="单季大增"`,`change_pct=yoy_pct`)

- [ ] **Step 1: 追加失败测试(SQL 打桩,只测编排)**

```python
# 追加到 backend/tests/domain/boom/test_service.py
class FakeForecastRepoFormal(FakeForecastRepo):
    def __init__(self):
        super().__init__()
        self.formal_calls = []

    def get_quarter_yoy_growth(self, report_date, min_pct):
        self.formal_calls.append((report_date, min_pct))
        return [{"symbol": "000333", "report_date": dt.date(2026, 9, 30),
                 "q_np": 1.2e9, "q_np_prev": 5e8, "yoy_pct": 140.0}]


def test_formal_window_adds_candidates():
    repo = FakeRepo()
    fr = FakeForecastRepoFormal()
    svc = BoomRadarService(repo, fr, FakeNewsSync(), FakeNewsRepo(),
                           {"min_change_pct": 50.0})
    stats = svc.run_daily(today=dt.date(2026, 10, 25))   # 10月下旬正式窗
    assert fr.formal_calls                            # 触发了正式报表查询
    formal = [c for c in repo.candidates if c["forecast_type"] == "formal"]
    assert formal and formal[0]["symbol"] == "000333"
    assert formal[0]["forecast_type_label"] == "单季大增"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/boom/test_service.py -v -k formal`
Expected: FAIL(`AttributeError: get_quarter_yoy_growth`)

- [ ] **Step 3: 实现 repo 原生 SQL(financial_full.py 类内)**

```python
    def get_quarter_yoy_growth(
        self, report_date: dt.date, min_pct: float,
    ) -> list[dict]:
        """正式报表窗候选:单季归母净利同比 ≥ min_pct(PG 专用)。

        Q1: 单季=Q1累计,直接比两年 Q1 累计;
        Q2-Q4: 单季=当期累计-上期累计,去年同单季同法差分。
        stock_financial_detail: statement_type='income', market='A'。
        """
        import psycopg2 as _pg
        from psycopg2.extras import RealDictCursor

        prev_month = {6: 3, 9: 6, 12: 9}
        if report_date.month == 3:
            sql = """
            SELECT c.symbol, c.np AS q_np, l.np AS q_np_prev
            FROM (
                SELECT symbol, SUM(net_profit_parent) AS np
                FROM stock_financial_detail
                WHERE report_date = %(rd)s
                  AND statement_type='income' AND market='A'
                GROUP BY symbol
            ) c JOIN (
                SELECT symbol, SUM(net_profit_parent) AS np
                FROM stock_financial_detail
                WHERE report_date = %(rd_ly)s
                  AND statement_type='income' AND market='A'
                GROUP BY symbol
            ) l USING (symbol)
            WHERE l.np > 0 AND c.np >= %(min_ratio)s * l.np
            """
            params = {
                "rd": report_date,
                "rd_ly": report_date.replace(year=report_date.year - 1),
                "min_ratio": 1 + min_pct / 100.0,
            }
        else:
            pm = prev_month[report_date.month]
            pq = dt.date(report_date.year, pm + 1, 1) - dt.timedelta(days=1)
            sql = """
            SELECT c.symbol, c.acc_rd - c.acc_prev AS q_np,
                   l.acc_rd_ly - l.acc_prev_ly AS q_np_prev
            FROM (
                SELECT symbol,
                       SUM(net_profit_parent) FILTER (WHERE report_date = %(rd)s) AS acc_rd,
                       SUM(net_profit_parent) FILTER (WHERE report_date = %(prev_rd)s) AS acc_prev
                FROM stock_financial_detail
                WHERE report_date IN (%(rd)s, %(prev_rd)s)
                  AND statement_type='income' AND market='A'
                GROUP BY symbol
            ) c JOIN (
                SELECT symbol,
                       SUM(net_profit_parent) FILTER (WHERE report_date = %(rd_ly)s) AS acc_rd_ly,
                       SUM(net_profit_parent) FILTER (WHERE report_date = %(prev_rd_ly)s) AS acc_prev_ly
                FROM stock_financial_detail
                WHERE report_date IN (%(rd_ly)s, %(prev_rd_ly)s)
                  AND statement_type='income' AND market='A'
                GROUP BY symbol
            ) l USING (symbol)
            WHERE c.acc_prev > 0 AND l.acc_prev_ly > 0
              AND l.acc_rd_ly - l.acc_prev_ly > 0
              AND (c.acc_rd - c.acc_prev) >= %(min_ratio)s * (l.acc_rd_ly - l.acc_prev_ly)
            """
            params = {
                "rd": report_date, "prev_rd": pq,
                "rd_ly": report_date.replace(year=report_date.year - 1),
                "prev_rd_ly": pq.replace(year=pq.year - 1),
                "min_ratio": 1 + min_pct / 100.0,
            }
        conn = _pg.connect(get_dsn())
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        for r in rows:
            q_np, q_prev = float(r["q_np"]), float(r["q_np_prev"])
            r["yoy_pct"] = round((q_np - q_prev) / abs(q_prev) * 100, 2)
            r["report_date"] = report_date
        return rows
```

- [ ] **Step 4: service 集成(run_daily 内,news 扫描循环之前)**

```python
        # 正式报表窗(3/4/8/10 月下旬):单季净利大增但无预告的公司补充入池
        formal_rows: list[dict] = []
        from src.domain.market.boom.season import is_formal_window
        if is_formal_window(today) and hasattr(
            self.forecast_repo, "get_quarter_yoy_growth"
        ):
            try:
                growth = self.forecast_repo.get_quarter_yoy_growth(
                    status.report_date, self.config["min_change_pct"]
                ) if status.report_date else []
            except Exception as e:
                log.warning("quarter yoy growth query failed: %s", e)
                growth = []
            existing_syms = {f.symbol for f in pool}
            for g in growth:
                if g["symbol"] in existing_syms:
                    continue
                cand_rows.append({
                    "symbol": g["symbol"], "report_date": g["report_date"],
                    "forecast_type": "formal", "company_name": None,
                    "announce_date": None, "change_pct": g["yoy_pct"],
                    "forecast_type_label": "单季大增",
                    "categories": [], "keyword_count": 0, "news_hit_count": 0,
                })
                formal_rows.append(g["symbol"])
```

(FakeRepo 场景下 `cand_rows.append` 的位置在函数体后段——实现时把该块放在 pool 循环之前、`hit_rows` 初始化之后,使其与测试断言一致;`existing_syms` 在循环前计算。)

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/boom/test_service.py -v`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/infra/database/market/financial_full.py backend/src/domain/market/boom/service.py backend/tests/domain/boom/test_service.py
git commit -m "feat(boom): 正式报表窗单季净利同比大增候选补充"
```

---

### Task 13: 回测样本构建 + 前视守卫

**Files:**
- Create: `backend/src/domain/market/boom/backtest.py`
- Test: `backend/tests/domain/boom/test_backtest.py`

**Interfaces:**
- Produces:
  - `backtest.SampleEvent(symbol, report_date, announce_date, change_pct, categories)`(frozen dataclass;`forecast_type` 亦存)
  - `backtest.build_samples(boom_repo, forecast_repo, start_year, end_year, min_change_pct) -> list[SampleEvent]`(events = 窗口内全部业绩大增;`categories` 只取 `source_date <= announce_date` 的命中分类 —— **前视守卫**)
  - `backtest.with_text_only(events) -> list[SampleEvent]`(过滤 `categories` 非空,即「业绩+文本」叠加组)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/boom/test_backtest.py
"""回测样本构建 + 前视守卫测试。"""
import datetime as dt

from src.domain.market.boom.backtest import SampleEvent, build_samples, with_text_only


class FakeBoomRepo:
    def get_hits_as_of(self, symbols, max_source_date):
        # 600001:公告日前命中(有效);600002:公告日后才命中(前视,必须排除)
        rows = []
        if "600001" in symbols:
            rows.append(type("H", (), {"symbol": "600001", "category": "supply_tight",
                                       "keyword": "供不应求",
                                       "source_date": dt.date(2025, 1, 5)})())
        if "600002" in symbols:
            rows.append(type("H", (), {"symbol": "600002", "category": "boom_up",
                                       "keyword": "高景气",
                                       "source_date": dt.date(2025, 1, 20)})())
        return rows


class FakeForecastRepo:
    def get_by_announce_date_range(self, start, end, forecast_type=None, limit=20000):
        def fc(sym, ann, pct):
            return type("F", (), {"symbol": sym, "forecast_type": "preannounce",
                                  "report_date": dt.date(2024, 12, 31),
                                  "announce_date": ann, "change_pct": pct,
                                  "forecast_type_label": "预增"})()
        return [fc("600001", dt.date(2025, 1, 10), 80.0),
                fc("600002", dt.date(2025, 1, 15), 90.0),
                fc("600003", dt.date(2025, 1, 18), 20.0)]   # 幅度不足


def test_build_samples_lookahead_guard():
    events = build_samples(FakeBoomRepo(), FakeForecastRepo(), 2025, 2025, 50.0)
    by_sym = {e.symbol: e for e in events}
    assert set(by_sym) == {"600001", "600002"}     # 600003 被幅度过滤
    assert by_sym["600001"].categories == ["supply_tight"]
    assert by_sym["600002"].categories == []       # 1-20 命中晚于 1-15 公告 → 剔除


def test_with_text_only():
    events = [
        SampleEvent("600001", dt.date(2024, 12, 31), dt.date(2025, 1, 10),
                    80.0, ("supply_tight",), "preannounce"),
        SampleEvent("600002", dt.date(2024, 12, 31), dt.date(2025, 1, 15),
                    90.0, (), "preannounce"),
    ]
    assert [e.symbol for e in with_text_only(events)] == ["600001"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/boom/test_backtest.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现 backtest.py(本任务部分)**

```python
# backend/src/domain/market/boom/backtest.py
"""策略回测:重放「业绩大增(+文本命中)→ T+1 买入持有N月」。

前视守卫:文本信号只取 source_date ≤ announce_date 的命中。
"""
import datetime as dt
from dataclasses import dataclass

from src.domain.market.boom.service import growth_filter


@dataclass(frozen=True)
class SampleEvent:
    symbol: str
    report_date: dt.date
    announce_date: dt.date
    change_pct: float
    categories: tuple[str, ...]
    forecast_type: str


def build_samples(boom_repo, forecast_repo, start_year: int, end_year: int,
                  min_change_pct: float) -> list[SampleEvent]:
    events: list[SampleEvent] = []
    for year in range(start_year, end_year + 1):
        for m in (1, 4, 7, 10):                     # 四个预告窗
            w_start = dt.date(year, m, 1)
            w_end = (dt.date(year, m + 1, 1) - dt.timedelta(days=1)
                     if m < 12 else dt.date(year, 12, 31))
            rows = forecast_repo.get_by_announce_date_range(w_start, w_end)
            pool = growth_filter(rows, min_change_pct)
            if not pool:
                continue
            # 前视守卫:窗口内命中的文本,只承认 source_date ≤ 该股公告日的
            hits = boom_repo.get_hits_as_of([f.symbol for f in pool], w_end)
            by_sym: dict = {}
            for h in hits:
                by_sym.setdefault(h.symbol, []).append(h)
            for f in pool:
                cats = sorted({h.category for h in by_sym.get(f.symbol, [])
                               if h.source_date is not None
                               and h.source_date <= f.announce_date})
                events.append(SampleEvent(
                    f.symbol, f.report_date, f.announce_date,
                    float(f.change_pct or 0), tuple(cats), f.forecast_type,
                ))
    return events


def with_text_only(events: list[SampleEvent]) -> list[SampleEvent]:
    return [e for e in events if e.categories]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/boom/test_backtest.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/boom/backtest.py backend/tests/domain/boom/test_backtest.py
git commit -m "feat(boom): 回测样本构建+前视守卫(source_date≤announce_date)"
```

---

### Task 14: 回测引擎(可注入价格函数)

**Files:**
- Modify: `backend/src/domain/market/boom/backtest.py`(追加)
- Test: `backend/tests/domain/boom/test_backtest.py`(追加)

**Interfaces:**
- Consumes: `SampleEvent`(Task 13)
- Produces:
  - `backtest.run_backtest(events, price_fn, bench_fn, hold_months=3, skip_limit_up=True) -> dict`
    - `price_fn(symbol, start, end) -> list[tuple[dt.date, float, float]]`(date, open, close;升序)
    - `bench_fn(start, end) -> list[tuple[dt.date, float]]`(date, close;升序)
    - 规则:T=announce_date;入场=T 后首个交易日开盘;开盘较 T 收盘 ≥+9.7% 视为一字涨停买不进(skip);出场=入场日起 hold_months 个月后的首个交易日收盘(无数据用最后可得收盘);`mret`、`bret`(区间基准收益)、等权组合为各事件均值
    - 返回 `{"n_events", "n_traded", "n_skipped_limitup", "n_no_data", "avg_ret", "avg_bench_ret", "avg_excess", "hit_rate", "by_year": [{year, n, avg_ret, avg_bench_ret, avg_excess, hit_rate}], "by_category": [{category, n, avg_ret, avg_excess}]}`
  - `backtest._months_after(d, months) -> dt.date`(自然月加法辅助,导出供测试)

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 backend/tests/domain/boom/test_backtest.py
from src.domain.market.boom.backtest import _months_after, run_backtest


def _mk_ev(sym, ann):
    return SampleEvent(sym, dt.date(2024, 12, 31), ann, 80.0,
                       ("supply_tight",), "preannounce")


def test_months_after():
    assert _months_after(dt.date(2025, 1, 31), 3) == dt.date(2025, 4, 30)
    assert _months_after(dt.date(2025, 8, 31), 6) == dt.date(2026, 2, 28)


def test_run_backtest_basic_flow():
    ev = _mk_ev("600001", dt.date(2025, 1, 10))
    bars = [
        (dt.date(2025, 1, 10), 10.0, 10.0),   # T 日收盘 10
        (dt.date(2025, 1, 13), 10.0, 10.5),   # T+1 入场开盘 10
        (dt.date(2025, 4, 14), 11.0, 11.0),   # 3个月后首个交易日,出场收盘 11
    ]
    bench = [(dt.date(2025, 1, 13), 4000.0), (dt.date(2025, 4, 14), 4200.0)]
    out = run_backtest([ev], lambda s, a, b: bars, lambda a, b: bench,
                       hold_months=3)
    assert out["n_traded"] == 1
    assert out["avg_ret"] == pytest.approx(10.0)      # 10→11 = +10%
    assert out["avg_bench_ret"] == pytest.approx(5.0)
    assert out["avg_excess"] == pytest.approx(5.0)
    assert out["hit_rate"] == 1.0
    assert out["by_category"][0]["category"] == "supply_tight"


def test_run_backtest_skips_limit_up_open():
    ev = _mk_ev("600001", dt.date(2025, 1, 10))
    bars = [
        (dt.date(2025, 1, 10), 10.0, 10.0),
        (dt.date(2025, 1, 13), 11.0, 11.0),   # 开盘 +10% ≥ 9.7% → 一字涨停跳过
    ]
    out = run_backtest([ev], lambda s, a, b: bars, lambda a, b: [],
                       hold_months=3)
    assert out["n_traded"] == 0
    assert out["n_skipped_limitup"] == 1


def test_run_backtest_no_data_counts():
    ev = _mk_ev("600001", dt.date(2025, 1, 10))
    out = run_backtest([ev], lambda s, a, b: [], lambda a, b: [], hold_months=3)
    assert out["n_no_data"] == 1 and out["n_traded"] == 0
```

(文件头需补 `import pytest`。)

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/boom/test_backtest.py -v -k "run_backtest or months_after"`
Expected: FAIL(`ImportError: cannot import name 'run_backtest'`)

- [ ] **Step 3: 实现(backtest.py 追加)**

```python
LIMIT_UP_PCT = 9.7      # 入场开盘较 T 收盘涨幅阈值(近似一字/开盘涨停)


def _months_after(d: dt.date, months: int) -> dt.date:
    y, m = d.year + (d.month - 1 + months) // 12, (d.month - 1 + months) % 12 + 1
    day = min(d.day, [31, 29 if _leap(y) else 28, 31, 30, 31, 30,
                      31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day)


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def run_backtest(events, price_fn, bench_fn, hold_months: int = 3,
                 skip_limit_up: bool = True) -> dict:
    trades: list[dict] = []
    n_skipped = n_no_data = 0
    for e in events:
        bars = price_fn(e.symbol, e.announce_date,
                        _months_after(e.announce_date, hold_months) +
                        dt.timedelta(days=15))        # 出场月多给半月找交易日
        if not bars or len(bars) < 2 or bars[0][0] <= e.announce_date:
            n_no_data += 1
            continue
        t_close = bars[0][2]
        entry = next((b for b in bars if b[0] > e.announce_date), None)
        if entry is None:
            n_no_data += 1
            continue
        if skip_limit_up and _pct(entry[1], t_close) >= LIMIT_UP_PCT:
            n_skipped += 1
            continue
        target = _months_after(entry[0], hold_months)
        exits = [b for b in bars if b[0] >= target]
        exit_bar = exits[0] if exits else bars[-1]
        mret = _pct(exit_bar[2], entry[1])
        bbars = bench_fn(entry[0], exit_bar[0])
        bret = _pct(bbars[-1][1], bbars[0][1]) if len(bbars) >= 2 else 0.0
        trades.append({"symbol": e.symbol, "year": entry[0].year,
                       "entry": entry[0], "exit": exit_bar[0],
                       "ret": mret, "bret": bret, "excess": mret - bret,
                       "categories": e.categories})

    def _agg(rows):
        if not rows:
            return {"n": 0, "avg_ret": 0.0, "avg_bench_ret": 0.0,
                    "avg_excess": 0.0, "hit_rate": 0.0}
        return {"n": len(rows),
                "avg_ret": sum(r["ret"] for r in rows) / len(rows),
                "avg_bench_ret": sum(r["bret"] for r in rows) / len(rows),
                "avg_excess": sum(r["excess"] for r in rows) / len(rows),
                "hit_rate": sum(1 for r in rows if r["ret"] > 0) / len(rows)}

    by_year = []
    for y in sorted({t["year"] for t in trades}):
        a = _agg([t for t in trades if t["year"] == y])
        by_year.append({"year": y, **a})
    all_cats = sorted({c for t in trades for c in t["categories"]})
    by_category = []
    for c in all_cats:
        rows = [t for t in trades if c in t["categories"]]
        by_category.append({"category": c, "n": len(rows),
                            "avg_ret": sum(r["ret"] for r in rows) / len(rows),
                            "avg_excess": sum(r["excess"] for r in rows) / len(rows)})
    overall = _agg(trades)
    return {"n_events": len(events), "n_traded": len(trades),
            "n_skipped_limitup": n_skipped, "n_no_data": n_no_data,
            "avg_ret": overall["avg_ret"], "avg_bench_ret": overall["avg_bench_ret"],
            "avg_excess": overall["avg_excess"], "hit_rate": overall["hit_rate"],
            "by_year": by_year, "by_category": by_category}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/boom/test_backtest.py -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/boom/backtest.py backend/tests/domain/boom/test_backtest.py
git commit -m "feat(boom): 回测引擎——T+1开盘入场/涨停跳过/持有N月/分年分分类统计"
```

---

### Task 15: 回测端点 + DB 价格适配器

**Files:**
- Modify: `backend/src/domain/market/boom/backtest.py`(追加 DB 适配器)
- Modify: `backend/src/api/router/boom_router.py`(追加端点)
- Test: `backend/tests/api/test_boom_router.py`(追加)

**Interfaces:**
- Produces:
  - `backtest.make_db_price_fn() -> Callable`(PG 读 `stock_ohlcv`,symbol 转前缀)
  - `backtest.make_db_bench_fn(benchmark="sh000300") -> Callable`(PG 读 `index_ohlcv`)
  - `backtest.run_full_backtest(start_year, end_year, min_change_pct, hold_months, with_text, benchmark) -> dict`(组装 build_samples + 适配器 + run_backtest,附 `meta` 说明口径限制)
  - `POST /boom/backtest` body `{start_year?, end_year?, min_change_pct?, hold_months?, with_text?, benchmark?}` → 报告

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 backend/tests/api/test_boom_router.py
def test_backtest_endpoint(client):
    # 端点函数体内 import,patch 源模块属性即可生效
    with patch("src.domain.market.boom.backtest.run_full_backtest") as rfb:
        rfb.return_value = {"n_events": 10, "n_traded": 8, "avg_excess": 5.0,
                            "by_year": [], "by_category": [], "meta": {}}
        r = client.post("/boom/backtest",
                        json={"start_year": 2024, "end_year": 2025})
    assert r.status_code == 200
    assert r.json()["data"]["n_events"] == 10
    rfb.assert_called_once_with(start_year=2024, end_year=2025,
                                min_change_pct=50.0, hold_months=3,
                                with_text=False, benchmark="sh000300")


def test_backtest_endpoint_validates_span(client):
    r = client.post("/boom/backtest",
                    json={"start_year": 2010, "end_year": 2026})
    assert r.status_code == 400            # 跨度>10年拒绝
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_boom_router.py -v -k backtest`
Expected: FAIL(404)

- [ ] **Step 3: 实现 DB 适配器(backtest.py 追加)**

```python
def _pg_query(sql: str, params: tuple) -> list[tuple]:
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn

    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def make_db_price_fn():
    """stock_ohlcv 适配器:返回 [(trade_date, open, close)] 升序(symbol 带前缀)。"""
    from src.domain.market.boom.service import to_prefixed

    def price_fn(symbol: str, start: dt.date, end: dt.date):
        rows = _pg_query(
            "SELECT trade_date, open_, close_ FROM stock_ohlcv "
            "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
            "ORDER BY trade_date ASC",
            (to_prefixed(symbol), start, end),
        )
        return [(r[0], float(r[1]), float(r[2])) for r in rows if r[1] and r[2]]
    return price_fn


def make_db_bench_fn(benchmark: str = "sh000300"):
    def bench_fn(start: dt.date, end: dt.date):
        rows = _pg_query(
            "SELECT date, close_ FROM index_ohlcv "
            "WHERE symbol = %s AND date BETWEEN %s AND %s "
            "ORDER BY date ASC",
            (benchmark, start, end),
        )
        return [(r[0], float(r[1])) for r in rows if r[1]]
    return bench_fn


META_NOTES = {
    "text_leg": "文本腿受 news_articles 历史深度限制,早年样本 categories 可能为空",
    "disclosure_bias": "业绩预告有强制披露门槛(±50%/亏损/扭亏),创业板不强制,样本存在覆盖偏差",
    "survivorship": "退市股无行情时计入 n_no_data 剔除",
}


def run_full_backtest(start_year: int, end_year: int,
                      min_change_pct: float = 50.0, hold_months: int = 3,
                      with_text: bool = False,
                      benchmark: str = "sh000300") -> dict:
    from src.infra.database.market.boom import create_boom_repository
    from src.infra.database.market.financial_full import (
        create_earnings_forecast_repository,
    )

    all_events = build_samples(create_boom_repository(),
                               create_earnings_forecast_repository(),
                               start_year, end_year, min_change_pct)
    events = with_text_only(all_events) if with_text else all_events
    report = run_backtest(events, make_db_price_fn(),
                          make_db_bench_fn(benchmark), hold_months=hold_months)
    report["meta"] = {
        **META_NOTES,
        "start_year": start_year, "end_year": end_year,
        "min_change_pct": min_change_pct, "hold_months": hold_months,
        "with_text": with_text, "benchmark": benchmark,
        "events_dropped_no_text": len(all_events) - len(events),
    }
    return report
```

- [ ] **Step 4: 实现端点(boom_router.py 追加)**

```python
@router.post("/backtest")
def backtest_run(body: dict):
    from src.domain.market.boom.backtest import run_full_backtest

    start_year = int(body.get("start_year", dt.date.today().year - 3))
    end_year = int(body.get("end_year", dt.date.today().year - 1))
    if end_year - start_year > 10:
        raise HTTPException(400, "时间跨度不能超过 10 年")
    if end_year < start_year:
        raise HTTPException(400, "end_year 必须 >= start_year")
    return _ok(run_full_backtest(
        start_year=start_year, end_year=end_year,
        min_change_pct=float(body.get("min_change_pct", 50.0)),
        hold_months=int(body.get("hold_months", 3)),
        with_text=bool(body.get("with_text", False)),
        benchmark=str(body.get("benchmark", "sh000300")),
    ))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_boom_router.py -v`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/domain/market/boom/backtest.py backend/src/api/router/boom_router.py backend/tests/api/test_boom_router.py
git commit -m "feat(boom): /boom/backtest端点+ohlcv/指数DB适配器(口径限制随报告返回)"
```

---

### Task 16: 前端「策略验证」Tab + 收尾验证

**Files:**
- Modify: `frontend/apps/web/src/pages/EarningsRadar.tsx`(重构为 Tabs:雷达 / 策略验证)
- Create: `frontend/apps/web/src/components/BoomBacktestPanel.tsx`
- Modify: `frontend/apps/web/src/pages/EarningsRadar.css`(追加)
- Modify: `docs/superpowers/specs/2026-09-08-earnings-boom-radar-design.md`(状态行改「已实施」)

**Interfaces:**
- Consumes: `POST /boom/backtest`;ui `Tabs`
- Produces: `BoomBacktestPanel({})`(表单 + 年度表 + 分类表 + 口径说明)

- [ ] **Step 1: 写 BoomBacktestPanel.tsx**

```tsx
// frontend/apps/web/src/components/BoomBacktestPanel.tsx
/** 策略验证:回测「业绩大增(+文本命中)→ T+1 买入持有N月」历史表现。 */
import {useState} from 'react';
import {getApiBase} from '../lib/api';
import {Button, Card, StateView} from './ui';
import {CATEGORY_LABELS} from '../pages/EarningsRadar.categories';

const API_BASE = getApiBase();

interface YearRow { year: number; n: number; avg_ret: number; avg_bench_ret: number; avg_excess: number; hit_rate: number; }
interface CatRow { category: string; n: number; avg_ret: number; avg_excess: number; }
interface Report {
  n_events: number; n_traded: number; n_skipped_limitup: number; n_no_data: number;
  avg_ret: number; avg_bench_ret: number; avg_excess: number; hit_rate: number;
  by_year: YearRow[]; by_category: CatRow[]; meta: Record<string, unknown>;
}

export function BoomBacktestPanel() {
  const thisYear = new Date().getFullYear();
  const [startYear, setStartYear] = useState(thisYear - 3);
  const [endYear, setEndYear] = useState(thisYear - 1);
  const [holdMonths, setHoldMonths] = useState(3);
  const [withText, setWithText] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/boom/backtest`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({start_year: startYear, end_year: endYear,
                              hold_months: holdMonths, with_text: withText}),
      });
      const j = await r.json();
      if (j.code === 0) setReport(j.data);
      else setError(j.msg || '回测失败');
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  const fmt = (v: number) => (v > 0 ? '+' : '') + v.toFixed(2) + '%';

  return (
    <div className="bbp">
      <Card className="bbp-form" padding="compact">
        <label>起年 <input className="bbp-input" type="number" value={startYear}
          onChange={(e) => setStartYear(Number(e.target.value) || 0)} /></label>
        <label>止年 <input className="bbp-input" type="number" value={endYear}
          onChange={(e) => setEndYear(Number(e.target.value) || 0)} /></label>
        <label>持有月 <input className="bbp-input" type="number" min={1} max={12} value={holdMonths}
          onChange={(e) => setHoldMonths(Math.max(1, Math.min(12, Number(e.target.value) || 3)))} /></label>
        <label className="bbp-check">
          <input type="checkbox" checked={withText}
                 onChange={(e) => setWithText(e.target.checked)} />
          仅含文本命中
        </label>
        <Button variant="primary" onClick={run} loading={running}>运行回测</Button>
      </Card>

      {error && <StateView state="error" text={error} />}
      {!report && !error && !running && (
        <StateView state="empty" text="设置年份区间后运行回测" />
      )}

      {report && (
        <>
          <Card className="bbp-summary" padding="compact">
            样本 <b className="num">{report.n_events}</b> · 成交{' '}
            <b className="num">{report.n_traded}</b>(涨停跳过{' '}
            {report.n_skipped_limitup} / 无行情 {report.n_no_data}) ·
            平均收益 <b className={`num ${report.avg_ret >= 0 ? 'is-up' : 'is-down'}`}>
              {fmt(report.avg_ret)}</b> · 基准{' '}
            <b className="num">{fmt(report.avg_bench_ret)}</b> · 超额{' '}
            <b className={`num ${report.avg_excess >= 0 ? 'is-up' : 'is-down'}`}>
              {fmt(report.avg_excess)}</b> · 胜率{' '}
            <b className="num">{(report.hit_rate * 100).toFixed(1)}%</b>
          </Card>

          <table className="er-table">
            <thead><tr><th>年份</th><th>样本</th><th>平均收益</th><th>基准</th><th>超额</th><th>胜率</th></tr></thead>
            <tbody>
              {report.by_year.map((y) => (
                <tr key={y.year}>
                  <td className="num">{y.year}</td>
                  <td className="num">{y.n}</td>
                  <td className={`num ${y.avg_ret >= 0 ? 'is-up' : 'is-down'}`}>{fmt(y.avg_ret)}</td>
                  <td className="num">{fmt(y.avg_bench_ret)}</td>
                  <td className={`num ${y.avg_excess >= 0 ? 'is-up' : 'is-down'}`}>{fmt(y.avg_excess)}</td>
                  <td className="num">{(y.hit_rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>

          {report.by_category.length > 0 && (
            <>
              <div className="bbp-subtitle">分信号分类</div>
              <table className="er-table">
                <thead><tr><th>分类</th><th>样本</th><th>平均收益</th><th>超额</th></tr></thead>
                <tbody>
                  {report.by_category.map((c) => (
                    <tr key={c.category}>
                      <td>{CATEGORY_LABELS[c.category] ?? c.category}</td>
                      <td className="num">{c.n}</td>
                      <td className={`num ${c.avg_ret >= 0 ? 'is-up' : 'is-down'}`}>{fmt(c.avg_ret)}</td>
                      <td className={`num ${c.avg_excess >= 0 ? 'is-up' : 'is-down'}`}>{fmt(c.avg_excess)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <div className="bbp-meta">
            口径说明:{String(report.meta.text_leg ?? '')};
            {String(report.meta.disclosure_bias ?? '')};
            {String(report.meta.survivorship ?? '')}
          </div>
        </>
      )}
    </div>
  );
}
```

(`CATEGORY_LABELS` 复用雷达页的分类码表副本 `pages/EarningsRadar.categories.ts`。)

- [ ] **Step 2: EarningsRadar.tsx 改为双 Tab**

文件头 import 加 `Tabs`(`from '../components/ui'`)与 `BoomBacktestPanel`(`from '../components/BoomBacktestPanel'`)。`EarningsRadar` 组件体内包一层:

```tsx
  const [tab, setTab] = useState<'radar' | 'backtest'>('radar');

  return (
    <div className="er-page">
      <PageHeader title="财报雷达" subtitle="财报季 · 业绩大增 × 景气关键词 候选池" />
      <Tabs
        active={tab}
        onChange={(k) => setTab(k as typeof tab)}
        tabs={[
          {key: 'radar', label: '雷达'},
          {key: 'backtest', label: '策略验证'},
        ]}
      />
      {tab === 'radar' ? <RadarTab /> : <BoomBacktestPanel />}
    </div>
  );
```

原组件 return 的主体(状态条到下钻 Modal)整体移入 `function RadarTab() { ... }` 子组件(与本文件同文件定义,原 state/逻辑不动),`RadarTab` 里不再渲染 `PageHeader`。

- [ ] **Step 3: CSS 追加(EarningsRadar.css 末尾)**

```css
/* BoomBacktestPanel */
.bbp {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.bbp-form {
  display: flex;
  gap: 14px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.bbp-input {
  width: 70px;
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  padding: 3px 6px;
}

.bbp-check {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.bbp-summary {
  font-size: 13px;
}

.bbp-subtitle {
  font-weight: var(--font-weight-bold);
  margin-top: 4px;
}

.bbp-meta {
  font-size: 12px;
  color: var(--color-text-tertiary);
  line-height: 1.6;
}
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend/apps/web && npm run build`
Expected: 构建成功

- [ ] **Step 5: 后端全量 boom 测试回归 + spec 状态更新**

Run: `cd backend && uv run pytest tests/domain/boom tests/infra/test_boom_repository.py tests/api/test_boom_router.py -v`
Expected: 全部 passed(约 30 项)

spec 文件首部 `- 状态:` 行改为 `- 状态:已实施(2026-09)`。

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/pages/EarningsRadar.tsx frontend/apps/web/src/pages/EarningsRadar.css frontend/apps/web/src/components/BoomBacktestPanel.tsx docs/superpowers/specs/2026-09-08-earnings-boom-radar-design.md
git commit -m "feat(boom-web): 策略验证Tab——回测报告/分年/分分类/口径说明"
```

---

## 附:执行注意事项

1. **工作区已有未提交改动**(main.py、scheduler.py、多个 router/pages 处于 modified 状态)——所有 `git add` 必须精确到本计划列出的文件,严禁 `git add -A`。对 `main.py`/`scheduler.py`/`App.tsx`/`Layout.tsx` 等共享文件的修改,commit 前用 `git diff --stat --cached` 复核只含本任务相关 hunk;若这些文件既有未提交改动与本任务改动混在同一文件,只 `git add` 该文件时会把旧改动一起带入——此时改用 `git add -p` 只选本任务 hunk(交互式不可用时,先在 commit message 注明包含既有改动,并停下来向用户确认)。
2. **pytest 基线**:全量回归有 52 个既有失败(见项目记忆),验证只看本计划新增测试文件的结果,勿被无关失败干扰。
3. **Task 11 Step 1 的探测结果是后续步骤的前提**,若 akshare 无调研接口,按该步骤说明降级。
4. **LLM 相关**(Task 9/10):测试全部打桩,不需要真实 API key;冒烟验证可选。
5. **已知低效(接受)**:候选股当日入池时 `mark_news_synced` 先于 upsert 执行是 no-op,次日晚间 job 会对首日候选重复拉一次新闻(akshare 幂等去重,损耗可接受),第三日起不再重拉。
