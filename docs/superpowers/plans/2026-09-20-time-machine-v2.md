# 时光机 v2（指数带/时代背景/股票信息/组合回测联动）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 时光机 `/replay` v2：顶栏固定四大指数带 + 时代背景条（策划大事件 + as-of 新闻 + 历史回填）、股票名称/行业持久化展示、选股器批量入池 + AI 建组合提案（复用 course-portfolio）+ 一键丢回测实验室；前置 Phase 0 合并 feat/buy-checklist。

**Architecture:** 前端驱动不变；后端 replay 模块增量扩展（advance 响应加 `indices`、新增 `instrument`/`news` 两个只读 as-of 端点、新闻回填脚本）；组合提案直接调既有 `POST /course-portfolio/generate`（无副作用、支持 as_of）；回测跳转走 URL query 预填。

**Tech Stack:** 不变（FastAPI/psycopg2/SQLModel + React18/zustand/lightweight-charts/vitest）；新增 akshare `news_cctv`/`news_economic_baidu` 作为回填源。

**Spec:** `docs/superpowers/specs/2026-09-20-time-machine-v2-design.md`

## Global Constraints

- **防未来函数红线**：一切行情/新闻 SQL 必须 `≤ asof`；新闻端点测试必须含"asof 之后的行不可见"泄漏断言。
- Symbol 小写带前缀（`sh600519`/`sz399006`）；指数固定集 `INDEX_SYMBOLS = ("sh000001","sz399001","sz399006","sh000300")`（中文名：上证指数/深证成指/创业板指/沪深300）。
- 响应协议 `{code,msg,data}`，`code==0` 成功；psycopg2 裸 SQL 惯例同 replay_handler（表名白名单、参数化）。
- **zustand 选择器引用稳定**（NO_BARS 模式，不返回新建数组/对象）；`visibleBars` 只当普通函数配 useMemo。
- 前端 2 空格缩进、单引号；后端 black line-length=79（中文注释超宽属既有风格）；git 只定向 add；中文 conventional commit。
- 后端测试只跑本特性相关文件（全量有既有失败）；真实 PG + try/finally 清理；TDD RED→GREEN。
- 旧旅程 state 兼容：无 `names`/`industries` 字段容错（显示代码），不迁移。
- **执行环境**：worktree `.worktrees/feat-time-machine-v2`（从 main 分支）；`backend/conf/config.local.yaml` 需复制进 worktree；后端 `uv run pytest`、前端 `pnpm install --frozen-lockfile` 后 `npx vitest run`；类型验收用独立 strict tsc 探针（项目全量 tsc 形同虚设）。
- **文档规约**：本计划与 spec 已在 feat/buy-checklist 分支上（随 Phase 0 合并进入 main 系），后续文档提交随 worktree 分支走。

---

### Task 1: Phase 0 — 合并 feat/buy-checklist 进 v2 分支（独立验证门）

**Files:**
- Create: worktree `.worktrees/feat-time-machine-v2`（含 merge commit）
- 无新源码文件；产物 = merge commit + 双侧测试全绿证明

**Interfaces:**
- Produces: worktree 分支 `feat/time-machine-v2`，其上含 course-portfolio（`POST /api/v1/course-portfolio/generate` 等端点）与 checklist 全部代码，Task 7 依赖。

- [ ] **Step 1: 建 worktree 并复制配置**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git worktree add .worktrees/feat-time-machine-v2 -b feat/time-machine-v2 main
cp backend/conf/config.local.yaml .worktrees/feat-time-machine-v2/backend/conf/config.local.yaml
```

Expected: worktree 就绪（main == merge-base，`git merge-tree main feat/buy-checklist` 已预演零冲突）。

- [ ] **Step 2: 合并（保留显式 merge commit）**

```bash
cd .worktrees/feat-time-machine-v2
git merge --no-ff feat/buy-checklist -m "merge: feat/buy-checklist(自动建组合+买入体检)并入——时光机v2 Phase0"
```

Expected: 零冲突合并成功（v2 spec/plan 文档随分支带入）。

- [ ] **Step 3: 后端双侧测试**

```bash
cd backend && uv sync --quiet
uv run pytest tests/api/test_course_portfolio_router.py tests/domain/test_course_builder.py \
  tests/domain/test_course_review.py tests/domain/market/fundamental/test_checklist_status.py \
  tests/domain/market/fundamental/test_kline_trend.py tests/api/test_replay_router.py -q
```

Expected: 65（分支）+ 12（replay）= **77 passed**。

- [ ] **Step 4: 前端全量 vitest + 依赖**

```bash
cd ../frontend && pnpm install --frozen-lockfile
cd apps/web && npx vitest run
```

Expected: replay 32 + coursePortfolio 4 + checklistHelpers 10 = **46 passed**（4 files + 既有 store.test 属 replay 计数内）。

- [ ] **Step 5: 冒烟探活**

```bash
cd ../../backend && uv run uvicorn main:create_app --factory --port 12102 &
sleep 8
curl -s -m 5 http://127.0.0.1:12102/api/v1/replay/sessions | head -c 60; echo
curl -s -m 30 -X POST http://127.0.0.1:12102/api/v1/course-portfolio/generate \
  -H 'Content-Type: application/json' \
  -d '{"total_capital":1000000,"risk_profile":"balanced","stock_count":6,"as_of":"2020-03-13"}' | head -c 200; echo
kill %1
```

Expected: 两个端点都 `code:0`；generate 的响应含 `as_of` 字段与 `legs`。

- [ ] **Step 6: Commit（merge commit 已在 Step 2 产生；本步确认树干净）**

```bash
git status --short   # 应仅 config.local.yaml 未跟踪(不提交)
```

---

### Task 2: 后端 — advance 扩展 indices（四大指数随油门返回）

**Files:**
- Modify: `backend/src/api/handler/replay_handler.py`
- Test: `backend/tests/api/test_replay_router.py`（追加）

**Interfaces:**
- Consumes: 既有 `advance(session_id, days)`（L267-313）、`_bar/_BAR_COLS/_conn`。
- Produces: `advance` 响应 data 新增 `indices: {"sh000001": [ReplayBar], "sz399001": [...], "sz399006": [...], "sh000300": [...]}`；模块常量 `INDEX_SYMBOLS`。前端 Task 5 消费（`AdvanceResp.indices`）。

- [ ] **Step 1: 写失败测试（追加到 TestReplaySlicing）**

```python
    def test_advance_indices(self, client, trade_day):
        sid = None
        try:
            r = _create(client, name="TS_idx", start_date=trade_day)
            assert r.json()["code"] == 0, r.text
            sid = r.json()["data"]["id"]
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "days": 3})
            assert r.json()["code"] == 0, r.text
            data = r.json()["data"]
            idx = data["indices"]
            assert set(idx) == {"sh000001", "sz399001",
                                "sz399006", "sh000300"}
            for sym, bars in idx.items():
                assert len(bars) >= 1
                for b in bars:
                    assert b["trade_date"] in data["dates"]
        finally:
            if sid is not None:
                _cleanup(client, sid)
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd backend && uv run pytest tests/api/test_replay_router.py::TestReplaySlicing::test_advance_indices -v`
Expected: FAIL（`indices` 键不存在）。

- [ ] **Step 3: 实现**

`replay_handler.py` 顶部常量区（`CALENDAR_SYMBOL` 之后）：

```python
# 指数带固定四指数（数据实测全覆盖；sh932000 无数据已剔除）
INDEX_SYMBOLS = ("sh000001", "sz399001", "sz399006", "sh000300")
```

`advance()` 内基准查询块之后、bump 之前追加（import 区 `from datetime import date` 补 `timedelta`——Task 3 也会用到）：

```python
        cur.execute(
            f"SELECT symbol, {_BAR_COLS} FROM index_ohlcv "
            "WHERE symbol = ANY(%s) "
            "AND trade_date::date >= %s AND trade_date::date <= %s "
            "ORDER BY symbol, trade_date",
            (list(INDEX_SYMBOLS), d0, d1),
        )
        indices: dict[str, list] = {}
        for r in cur.fetchall():
            sym = r.pop("symbol")
            indices.setdefault(sym, []).append(_bar(r))
```

返回 dict 增加 `"indices": indices`（与 benchmark 平级）。

- [ ] **Step 4: 跑全文件确认 PASS（13 个）**

Run: `cd backend && uv run pytest tests/api/test_replay_router.py -q`
Expected: 13 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/handler/replay_handler.py backend/tests/api/test_replay_router.py
git commit -m "feat(replay): advance响应扩展indices四指数带——单查询ANY一次带回"
```

---

### Task 3: 后端 — instrument + news 两个 as-of 只读端点

**Files:**
- Modify: `backend/src/api/handler/replay_handler.py`、`backend/src/api/router/replay_router.py`
- Test: `backend/tests/api/test_replay_router.py`（追加）

**Interfaces:**
- Consumes: `_conn/_parse_day`；`stock_info(symbol,name)`；`sw_industry_member(symbol,sw_name_l1)`；`intel_news(title,source,published_at,importance,url,category)`。
- Produces:
  - `GET /replay/instrument/{symbol}` → `data: {symbol, name, industry}`（industry 可 null；名称/行业为当前快照口径，无 asof 参数——spec §6 的 `?asof=` 简化掉，口径注记在 docstring）
  - `GET /replay/news?asof=&days=3&limit=20` → `data: [{title, source, published_at, importance, url}]`；红线 `published_at::date <= asof`；category 限 `finance|cctv_news`
  - 前端 Task 5/6 消费（`fetchInstrument/fetchNews`）

- [ ] **Step 1: 写失败测试（追加 TestReplayInfo 節，含泄漏断言）**

```python
class TestReplayInfo:
    def test_instrument(self, client, dyn_symbol):
        r = client.get(f"/api/v1/replay/instrument/{dyn_symbol}")
        assert r.json()["code"] == 0, r.text
        data = r.json()["data"]
        assert data["symbol"] == dyn_symbol.lower()
        assert data["name"]  # 非空
        assert data["industry"] is None or isinstance(data["industry"], str)

    def test_instrument_unknown(self, client):
        r = client.get("/api/v1/replay/instrument/sh999999")
        assert r.json()["code"] != 0

    def test_news_asof_and_leakage(self, client, trade_day):
        """红线：asof 之后的新闻绝不可见。"""
        from src.infra.database.sql_engine.dsn import get_dsn
        conn = psycopg2.connect(get_dsn())
        tag = f"TS_NEWS_{dt.date.today().isoformat()}"
        urls = []
        try:
            with conn.cursor() as cur:
                for i, day in enumerate(["2020-03-12", "2020-03-14"]):
                    url = f"{tag}-{i}"
                    urls.append(url)
                    cur.execute(
                        "INSERT INTO intel_news (title, url, source, "
                        "source_type, category, importance, published_at, "
                        "fetched_at) VALUES (%s,%s,'TS','backfill',"
                        "'finance',%s,%s,now())",
                        (f"{tag} 头条{i}", url, 5 - i,
                         f"{day} 09:00:00+08"),
                    )
            conn.commit()
        finally:
            pass
        try:
            r = client.get("/api/v1/replay/news",
                           params={"asof": "2020-03-13", "days": 3})
            assert r.json()["code"] == 0, r.text
            titles = [x["title"] for x in r.json()["data"]]
            assert f"{tag} 头条0" in titles   # asof 前一天,可见
            assert f"{tag} 头条1" not in titles  # asof 后一天,必须不可见
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM intel_news WHERE url LIKE %s",
                            (tag + "%",))
            conn.commit()
            conn.close()

    def test_news_reject_future(self, client):
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        r = client.get("/api/v1/replay/news",
                       params={"asof": tomorrow})
        assert r.json()["code"] != 0
```

- [ ] **Step 2: 跑测试确认 FAIL**

Run: `cd backend && uv run pytest tests/api/test_replay_router.py::TestReplayInfo -v`
Expected: FAIL（端点不存在）。

- [ ] **Step 3: 实现 handler（追加到 replay_handler.py；import 补 timedelta）**

```python
# ── 标的信息 / as-of 新闻（Task 3, v2） ──


def instrument(symbol: str):
    """标的名称+申万一级行业(当前快照口径,无历史维度,如实标注)。"""
    sym = symbol.lower()
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT si.name AS name, m.sw_name_l1 AS industry "
            "FROM (SELECT %s AS s) q "
            "LEFT JOIN stock_info si ON si.symbol = q.s "
            "LEFT JOIN sw_industry_member m ON m.symbol = q.s",
            (sym,),
        )
        row = cur.fetchone()
    if row is None or not row["name"]:
        return responses.fail("未找到该标的")
    return responses.success({
        "symbol": sym,
        "name": row["name"],
        "industry": row["industry"],
    })


def news(asof: str, days: int = 3, limit: int = 20):
    """as-of 新闻头条: intel_news 里 published_at <= asof 的近 N 天。

    覆盖密度受回填进度限制(2026 年密度高,更早年份稀疏)。
    """
    d, err = _parse_day(asof, "asof")
    if err:
        return err
    if d > date.today():
        return responses.fail("asof 不能晚于今天")
    days = max(1, min(days, 14))
    limit = max(1, min(limit, 50))
    start = d - timedelta(days=days)
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT title, source, published_at, importance, url "
            "FROM intel_news "
            "WHERE published_at::date <= %s "
            "AND published_at::date >= %s "
            "AND category = ANY(%s) "
            "ORDER BY importance DESC NULLS LAST, "
            "published_at DESC LIMIT %s",
            (d, start, ["finance", "cctv_news"], limit),
        )
        rows = cur.fetchall()
    return responses.success([{
        "title": r["title"],
        "source": r["source"],
        "published_at": r["published_at"].isoformat(),
        "importance": r["importance"],
        "url": r["url"],
    } for r in rows])
```

router 追加：

```python
@router.get("/instrument/{symbol}")
def _instrument(symbol: str):
    return h.instrument(symbol)


@router.get("/news")
def _news(
    asof: str = Query(...),
    days: int = Query(3),
    limit: int = Query(20),
):
    return h.news(asof, days, limit)
```

- [ ] **Step 4: 跑全文件 PASS（17 个）+ Commit**

Run: `cd backend && uv run pytest tests/api/test_replay_router.py -q` → Expected: 17 passed。

```bash
git add backend/src/api/handler/replay_handler.py \
        backend/src/api/router/replay_router.py \
        backend/tests/api/test_replay_router.py
git commit -m "feat(replay): instrument名称行业+news as-of端点——published_at<=asof红线含泄漏断言"
```

---

### Task 4: 后端 — 历史新闻回填脚本（akshare spike + dry-run + 落库）

**Files:**
- Create: `backend/scripts/replay_news_backfill.py`
- Create: `backend/.replay_news_backfill_progress.json`（运行产物，不提交——确认 .gitignore 覆盖 `.json` 进度文件或加行）
- Test: `backend/tests/scripts/test_replay_news_backfill.py`（纯函数部分）

**Interfaces:**
- Consumes: akshare `news_cctv(date="YYYYMMDD")`（央视新闻联播按日，历史纵深最好）、`news_economic_baidu(date="YYYYMMDD")`（经济日历事件）；`intel_news(url 唯一)`。
- Produces: `python scripts/replay_news_backfill.py --start 2020-01-01 --end 2020-03-31 [--dry-run] [--source cctv|economic|both]`；upsert 惯例 `source_type='backfill'`、`category='cctv_news'`(cctv)/`'finance'`(economic)、`url=f"bk:{source}:{date}:{abs(hash(title))}"`；进度文件 `{source: {oldest_ok, newest_ok, done_days, failed_days}}`。Task 6 的 news 端点直接受益（无需改动）。

- [ ] **Step 1: spike——探测两接口真实历史深度与列名**

```bash
cd backend && uv run python -c "
import akshare as ak
for d in ['20140101','20160104','20200102','20200313']:
    try:
        df = ak.news_cctv(date=d)
        print('cctv', d, len(df), list(df.columns)[:6])
    except Exception as e:
        print('cctv', d, 'ERR', str(e)[:60])
    try:
        df2 = ak.news_economic_baidu(date=d)
        print('econ', d, len(df2), list(df2.columns)[:8])
    except Exception as e:
        print('econ', d, 'ERR', str(e)[:60])
" 2>&1 | grep -v "INFO\|DEBUG"
```

Expected: 记录每个日期的可达性与列名（cctv 预期列含 `标题/日期`；econ 预期含 `日期/国家/事件` 类）。**以实测列名修正 Step 3 的映射**；把最老可达日期写进报告（决定默认回填下限）。

- [ ] **Step 2: 写纯函数测试**

`tests/scripts/test_replay_news_backfill.py`：

```python
"""回填脚本纯函数测试 —— 行映射/URL 构造/去重。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from replay_news_backfill import rows_from_cctv, rows_from_economic, \
    make_url  # noqa: E402


def test_make_url_stable():
    assert make_url("cctv", "2020-03-13", "标题A") == \
        make_url("cctv", "2020-03-13", "标题A")
    assert make_url("cctv", "2020-03-13", "标题A") != \
        make_url("cctv", "2020-03-13", "标题B")


def test_rows_from_cctv():
    df_rows = [{"标题": "联播头条", "日期": "2020-03-13 19:00"}]
    out = rows_from_cctv("2020-03-13", df_rows)
    assert len(out) == 1
    r = out[0]
    assert r["title"] == "联播头条"
    assert r["url"] == make_url("cctv", "2020-03-13", "联播头条")
    assert r["category"] == "cctv_news"
    assert r["published_at"].startswith("2020-03-13")


def test_rows_from_economic_skips_empty_title():
    df_rows = [{"日期": "2020-03-13", "事件": "美联储降息"},
               {"日期": "2020-03-13", "事件": ""}]
    out = rows_from_economic("2020-03-13", df_rows)
    assert len(out) == 1
    assert out[0]["category"] == "finance"
```

（`rows_from_*` 的入参用 `list[dict]` 而非 DataFrame——脚本里先 `df.to_dict("records")`，纯函数不吃 pandas 类型。）

- [ ] **Step 3: 实现脚本**

`scripts/replay_news_backfill.py`（骨架，列名以 Step 1 实测为准）：

```python
"""时光机历史新闻回填 —— akshare 新闻联播/经济日历 → intel_news。

用法:
  uv run python scripts/replay_news_backfill.py \
      --start 2020-01-01 --end 2020-03-31 [--dry-run] \
      [--source cctv|economic|both]
进度: backend/.replay_news_backfill_progress.json
"""
import argparse
import hashlib
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from src.infra.database.sql_engine.dsn import get_dsn

PROGRESS = Path(__file__).resolve().parent / \
    ".replay_news_backfill_progress.json"
RATE_LIMIT_SEC = 0.6


def make_url(source: str, day: str, title: str) -> str:
    h = hashlib.md5(title.encode("utf-8")).hexdigest()[:16]
    return f"bk:{source}:{day}:{h}"


def _to_iso_ts(day: str, hhmm: str = "09:00") -> str:
    return f"{day} {hhmm}:00+08"


def rows_from_cctv(day: str, records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        title = (r.get("标题") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "url": make_url("cctv", day, title),
            "source": "央视新闻联播",
            "source_type": "backfill",
            "category": "cctv_news",
            "published_at": _to_iso_ts(day, "19:30"),
        })
    return out


def rows_from_economic(day: str, records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        title = (r.get("事件") or r.get("标题") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "url": make_url("economic", day, title),
            "source": "百度经济日历",
            "source_type": "backfill",
            "category": "finance",
            "published_at": _to_iso_ts(day, "08:00"),
        })
    return out


def _upsert(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO intel_news (title, url, source, source_type,
                                    category, published_at, fetched_at)
            VALUES %s
            ON CONFLICT (url) DO NOTHING
        """, [(r["title"], r["url"], r["source"], r["source_type"],
               r["category"], r["published_at"], datetime.now()) 
              for r in rows])
    return cur.rowcount


def backfill(start: date, end: date, source: str, dry: bool):
    import akshare as ak
    conn = psycopg2.connect(get_dsn())
    prog = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    stats = {"ok": 0, "empty": 0, "err": 0, "rows": 0}
    d = start
    try:
        while d <= end:
            ds = d.strftime("%Y%m%d")
            for name, fetch, mapper in (
                ("cctv", ak.news_cctv, rows_from_cctv),
                ("economic", ak.news_economic_baidu,
                 rows_from_economic),
            ):
                if source not in ("both", name):
                    continue
                try:
                    df = fetch(date=ds)
                    rows = mapper(d.isoformat(),
                                  df.to_dict("records"))
                    if not dry:
                        stats["rows"] += _upsert(conn, rows)
                        conn.commit()
                    stats["ok" if rows else "empty"] += 1
                except Exception:
                    stats["err"] += 1
                time.sleep(RATE_LIMIT_SEC)
            d += timedelta(days=1)
        prog[source] = {"start": start.isoformat(),
                        "end": end.isoformat(), **stats,
                        "dry_run": dry}
        if not dry:
            PROGRESS.write_text(json.dumps(prog, ensure_ascii=False,
                                           indent=2))
        print(f"[{source}] {start}..{end} => {stats}"
              + (" (dry-run)" if dry else ""))
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--source", default="both",
                    choices=["cctv", "economic", "both"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    backfill(date.fromisoformat(a.start), date.fromisoformat(a.end),
             a.source, a.dry_run)
```

- [ ] **Step 4: 验证**

```bash
uv run pytest tests/scripts/test_replay_news_backfill.py -q
uv run python scripts/replay_news_backfill.py --start 2020-03-10 --end 2020-03-13 --dry-run
# 真实小窗落库 + 端点可见性验证:
uv run python scripts/replay_news_backfill.py --start 2020-03-10 --end 2020-03-13 --source cctv
uv run python -c "
import psycopg2
from src.infra.database.sql_engine.dsn import get_dsn
conn = psycopg2.connect(get_dsn())
with conn.cursor() as cur:
    cur.execute(\"SELECT COUNT(*) FROM intel_news WHERE source_type='backfill'\")
    print('backfill rows:', cur.fetchone()[0])
conn.close()"
# 清理测试窗口(可选,保留亦可):
# DELETE FROM intel_news WHERE source_type='backfill' AND published_at::date BETWEEN '2020-03-10' AND '2020-03-13';
```

Expected: 测试 3 passed；dry-run 输出统计；真实落库后 backfill 行数>0；`GET /replay/news?asof=2020-03-13` 能看到回填头条（手动 curl 验一次）。

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/replay_news_backfill.py backend/tests/scripts/test_replay_news_backfill.py
# 若 .gitignore 未覆盖进度文件,追加一行 backend/.replay_news_backfill_progress.json
git commit -m "feat(replay): 历史新闻回填脚本——news_cctv/经济日历→intel_news,md5去重ON CONFLICT,dry-run+进度"
```

---

### Task 5: 前端 — types/api/store v2（多指数/名称行业持久化/批量入池）

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/types.ts`、`api.ts`、`store.ts`
- Test: `frontend/apps/web/src/pages/replay/__tests__/store.test.ts`（追加 describe）

**Interfaces:**
- Consumes: Task 2 `AdvanceResp.indices`；Task 3 `instrument/news` 端点。
- Produces（Task 6/7 消费）:
  - types: `AdvanceResp` 加 `indices: Record<string, ReplayBar[]>`；`SessionState` 加 `names: Record<string,string>`、`industries: Record<string,string>`（旧 state 缺字段容错）；新增 `InstrumentInfo{symbol,name,industry}`、`NewsItem{title,source,published_at,importance,url}`
  - api: `fetchInstrument(symbol)`、`fetchNews(asof, days?)`、`generatePortfolio(body)`
  - store 新字段: `indexBars: Record<string, ReplayBar[]>`、`industries: Record<string,string>`；新 action: `addSymbols(symbols: string[]): Promise<{added:number; failed:string[]}>`（并发 6 一批，逐只 fetchKline+fetchInstrument 富化）
  - `addSymbol` 改为 kline+instrument 并发富化；`saveNow` state 含 names/industries；`openSession` 恢复 names/industries 并初始化 4 指数 indexBars；`advance` 合并 indices（同 bars 去重口径）
  - 常量 `INDEX_SYMBOLS`/`INDEX_NAMES`（store.ts 导出）

- [ ] **Step 1: 类型与 api 增量**

types.ts 对应块改为：

```ts
export interface AdvanceResp {
  dates: string[];
  bars: Record<string, ReplayBar[]>;
  benchmark: ReplayBar[];
  indices: Record<string, ReplayBar[]>;
}

export interface SessionState {
  pool: string[];
  positions: Position[];
  nav: NavPoint[];
  names?: Record<string, string>;       // v2: 旧旅程可缺省
  industries?: Record<string, string>;
}

export interface InstrumentInfo {
  symbol: string;
  name: string;
  industry: string | null;
}

export interface NewsItem {
  title: string;
  source: string;
  published_at: string;
  importance: number | null;
  url: string;
}
```

api.ts 追加：

```ts
export const fetchInstrument = (symbol: string) =>
  jget<InstrumentInfo>(`${API}/replay/instrument/${symbol}`);
export const fetchNews = (asof: string, days = 3) =>
  jget<NewsItem[]>(`${API}/replay/news?asof=${asof}&days=${days}`);
export const generatePortfolio = (body: {
  total_capital: number; risk_profile: string;
  stock_count: number; as_of: string;
}) => jpost<{
  risk_profile: string; total_capital: number;
  investable_capital: number;
  legs: {symbol: string; name: string; category: string;
         target_weight: number; current_price: number;
         pe_band: {state: string} | null}[];
  warnings: string[];
}>(`${API}/course-portfolio/generate`, body);
```

（import 类型行同步补 `InstrumentInfo, NewsItem`。）

- [ ] **Step 2: 写失败测试（store.test.ts 追加；mock 需补 fetchInstrument/fetchNews/generatePortfolio）**

```ts
  it('addSymbol 富化名称行业并随 saveNow 持久化', async () => {
    vi.mocked(api.fetchInstrument).mockResolvedValue({code: 0, msg: 'ok',
      data: {symbol: '600519', name: '贵州茅台', industry: '食品饮料'}});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519');
    useReplayStore.getState().selectSymbol('600519');
    await useReplayStore.getState().placeOrder('buy', 100);
    const body = vi.mocked(api.saveState).mock.calls.at(-1)?.[1];
    expect(body?.state.names?.['600519']).toBe('贵州茅台');
    expect(body?.state.industries?.['600519']).toBe('食品饮料');
  });

  it('advance 合并 indices 四指数且去重', async () => {
    const idx = {'sh000001': [bar('2020-03-16', 2890)]};
    vi.mocked(api.fetchAdvance).mockResolvedValue({code: 0, msg: 'ok', data: {
      dates: ['2020-03-16'], bars: {}, benchmark: [bar('2020-03-16', 4050)],
      indices: idx,
    }});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().advance();
    await useReplayStore.getState().advance(); // 重复返回同一天,去重
    const s = useReplayStore.getState();
    expect(s.indexBars['sh000001'].map((b) => b.trade_date))
      .toEqual(['2020-03-16']);
  });

  it('addSymbols 批量入池统计成败', async () => {
    vi.mocked(api.fetchKline).mockImplementation(async (symbol: string) => ({
      code: 0, msg: 'ok',
      data: {symbol, bars: symbol === 'sz000001'
        ? [] : [bar('2020-03-13', 10)]},   // sz000001 模拟无数据
    }));
    await useReplayStore.getState().openSession(7);
    const r = await useReplayStore.getState()
      .addSymbols(['600519', 'sz000001']);
    expect(r.added).toBe(1);
    expect(r.failed).toEqual(['sz000001']);
  });
```

（mock 顶部的 `fetchAdvance` 返回值需补 `indices: {}`；`openSession` 的基准 mock 不变。）

- [ ] **Step 3: 跑测试确认 FAIL → 实现 store 增量 → PASS**

store.ts 关键增量（与既有风格一致）：

```ts
export const INDEX_SYMBOLS = ['sh000001', 'sz399001',
  'sz399006', 'sh000300'] as const;
export const INDEX_NAMES: Record<string, string> = {
  sh000001: '上证指数', sz399001: '深证成指',
  sz399006: '创业板指', sh000300: '沪深300',
};
```

- state 加 `indexBars: Record<string, ReplayBar[]>`（初值 `{}`）与 `industries: Record<string,string>`；closeSession 重置。
- `openSession`：恢复 `names: sess.state.names ?? {}`、`industries: sess.state.industries ?? {}`；基准 kline 后并发：

```ts
      const idxArr = await Promise.all(INDEX_SYMBOLS.map(
        (s) => api.fetchKline(s, sess.current_date)));
      const indexBars: Record<string, ReplayBar[]> = {};
      INDEX_SYMBOLS.forEach((s, i) => {
        if (idxArr[i].code === 0) indexBars[s] = idxArr[i].data.bars;
      });
```

- `advance`：与 bars 同口径合并 `r.data.indices`（按 `inNew(trade_date)` 过滤后 push）；reveal 重拉阶段同样并发补 4 指数全量。
- `addSymbol`：`Promise.all([api.fetchKline(...), api.fetchInstrument(symbol)])`；instrument 成功则写 names（显式 name 参数优先）与 industries。
- 新 action `addSymbols`：6 只一批并发调内部 addSymbol 逻辑（复用 addSymbol 并收集结果，失败记 symbol 不中断）。
- `saveNow`：`state: {pool, positions, nav, names, industries}`。

Run: `cd frontend/apps/web && npx vitest run src/pages/replay/`
Expected: 既有 32 + 新 3 = 35 passed。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/pages/replay/types.ts \
        frontend/apps/web/src/pages/replay/api.ts \
        frontend/apps/web/src/pages/replay/store.ts \
        frontend/apps/web/src/pages/replay/__tests__/store.test.ts
git commit -m "feat(replay): store v2——indexBars四指数/names+industries持久化/addSymbols批量富化入池"
```

---

### Task 6: 前端 — 指数带 + 时代背景条 + 名称行业展示

**Files:**
- Create: `frontend/apps/web/src/pages/replay/IndexStrip.tsx`、`EraBar.tsx`
- Modify: `Cockpit.tsx`、`PoolPanel.tsx`、`OrderTicket.tsx`、`ReviewView.tsx`、`Replay.css`

**Interfaces:**
- Consumes: Task 5 的 `indexBars/INDEX_NAMES/INDEX_SYMBOLS/names/industries`、`viewDate`、`api.fetchNews`；现成 `GET /macro/events`（`data: [{date,title,desc}]`）。
- Produces: 驾驶舱顶栏下两条固定展示带 + 全列表名称行业展示。Task 8 验收。

- [ ] **Step 1: CSS 追加（Replay.css 末尾）**

```css
.replay-indices { display: flex; gap: 14px; padding: 6px 14px;
  border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
  background: #1d1d1f; font-size: 12px; margin-bottom: 10px;
  flex-wrap: wrap; }
.replay-indices .idx { display: flex; gap: 6px; align-items: baseline; }
.replay-indices .idx b { color: #f5f5f7; font-weight: 500; }
.replay-era { display: flex; gap: 8px; padding: 6px 14px;
  border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
  background: #1d1d1f; font-size: 12px; margin-bottom: 10px;
  align-items: center; flex-wrap: wrap; }
.replay-chip { border: 1px solid rgba(255,159,10,0.45);
  color: #ff9f0a; border-radius: 999px; padding: 2px 10px; }
.replay-chip.today { background: rgba(255,159,10,0.15); }
.replay-ind-tag { color: #86868b; font-size: 11px;
  border: 1px solid rgba(255,255,255,0.1); border-radius: 4px;
  padding: 0 4px; margin-left: 6px; }
.replay-era-news { color: #a1a1a6; max-height: 72px; overflow: auto; }
.replay-era-news li { list-style: none; padding: 1px 0; }
```

- [ ] **Step 2: IndexStrip.tsx**

```tsx
import {INDEX_NAMES, INDEX_SYMBOLS, useReplayStore, viewDate} from './store';
import type {ReplayBar} from './types';

const NO_IDX: ReplayBar[] = [];  // 引用稳定,防无限重渲染

const pctOf = (bars: {close: number}[], vd: string | null) => {
  const vis = bars.filter((b) => !vd || b.trade_date <= vd);
  if (vis.length < 2) return null;
  const a = vis[vis.length - 2].close;
  const b = vis[vis.length - 1].close;
  return a > 0 ? (b / a - 1) * 100 : null;
};

export const IndexStrip: React.FC = () => {
  const indexBars = useReplayStore((s) => s.indexBars);
  const vd = useReplayStore(viewDate);
  return (
    <div className="replay-indices">
      {INDEX_SYMBOLS.map((sym) => {
        const bars = indexBars[sym] ?? NO_IDX;
        const vis = bars.filter((b) => !vd || b.trade_date <= vd);
        const close = vis.length ? vis[vis.length - 1].close : null;
        const p = pctOf(bars, vd);
        return (
          <span className="idx" key={sym}>
            <span style={{color: '#86868b'}}>{INDEX_NAMES[sym]}</span>
            <b>{close == null ? '—' : close.toFixed(2)}</b>
            <span className={p == null ? '' : p >= 0 ? 'is-up' : 'is-down'}>
              {p == null ? '—' : `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`}
            </span>
          </span>
        );
      })}
    </div>
  );
};
```

（`viewDateHelper`/`NO_IDX` 参照既有 `viewDate` 选择器与 NO_BARS 模式落位：`viewDate` 直接从 store 导入使用；`const NO_IDX: ReplayBar[] = [];` 模块级常量。）

- [ ] **Step 3: EraBar.tsx（macro events 一次拉取 + as-of 新闻）**

```tsx
import {useEffect, useState} from 'react';
import * as api from './api';
import {useReplayStore, viewDate} from './store';
import type {NewsItem} from './types';

interface MacroEvent { date: string; title: string; desc: string; }

let eventsCache: MacroEvent[] | null = null;  // 12 条静态,模块级缓存

const daysBefore = (iso: string, n: number): string => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
};

const mmdd = (iso: string): string => iso.slice(5, 10);

export const EraBar: React.FC = () => {
  const vd = useReplayStore(viewDate);
  const [events, setEvents] = useState<MacroEvent[]>(eventsCache ?? []);
  const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
  const [showNews, setShowNews] = useState(false);

  useEffect(() => {
    if (eventsCache) return;
    void api.fetchMacroEvents().then((r) => {
      if (r.code === 0) { eventsCache = r.data; setEvents(r.data); }
    });
  }, []);

  useEffect(() => {
    if (!vd) return;
    let off = false;
    setNewsItems([]);
    void api.fetchNews(vd, 3).then((r) => {
      if (!off && r.code === 0) setNewsItems(r.data);
    });
    return () => { off = true; };
  }, [vd]);

  if (!vd) return null;
  const cutoff = daysBefore(vd, 60);
  const recent = events
    .filter((e) => e.date <= vd && e.date >= cutoff)
    .sort((a, b) => (a.date < b.date ? 1 : -1))
    .slice(0, 3);
  return (
    <div className="replay-era">
      <span style={{color: '#86868b'}}>时代背景</span>
      {recent.map((e) => (
        <span key={e.date} title={e.desc}
          className={`replay-chip${e.date === vd ? ' today' : ''}`}>
          {e.date} {e.title}
        </span>
      ))}
      {recent.length === 0 && newsItems.length === 0 && (
        <span className="replay-hint">近 60 天无策划大事件</span>
      )}
      <button className="replay-btn"
        style={{padding: '1px 8px', fontSize: 12}}
        disabled={newsItems.length === 0}
        onClick={() => setShowNews(!showNews)}>
        📰 近3日头条({newsItems.length})
      </button>
      {showNews && (
        <ul className="replay-era-news">
          {newsItems.map((n) => (
            <li key={n.url}>
              {n.title}
              <span style={{color: '#6e6e73'}}> — {n.source} {mmdd(n.published_at)}</span>
            </li>
          ))}
        </ul>
      )}
      {newsItems.length === 0 && (
        <span className="replay-hint">该时段暂无新闻存档</span>
      )}
    </div>
  );
};
```

（`api.fetchMacroEvents` 在 api.ts 追加：`export const fetchMacroEvents = () => jget<{date:string,title:string,desc:string}[]>(`${API}/macro/events`);`——注意 api.ts 的 `API` 常量名以此前文件实际为准。）

- [ ] **Step 4: Cockpit 组装 + 名称行业展示**

- `Cockpit.tsx`：`<TopBar />` 之后插 `<IndexStrip />` 与 `<EraBar />`（import 对应组件）。
- `PoolPanel.tsx` 池列表行：名称行业常量来自 store（`names`/`industries` 选择器），行内追加 `<span className="replay-ind-tag">{industries[sym]}</span>`（无则不渲染）；持仓表首列显示 `names[p.symbol] ?? p.symbol`。
- `OrderTicket.tsx` 标题：`{names[symbol] ?? ''} {symbol}` 后追加行业 tag（同款）。
- `ReviewView.tsx` 成交清单加"名称"列：`{names[t.symbol] ?? ''}`（th/td 各加一格，列宽窄）。

- [ ] **Step 5: 验证三连 + Commit**

```bash
cd frontend/apps/web
npx vitest run src/pages/replay/     # 35 passed(不回归)
pnpm build                            # 成功
# strict tsc 探针(新/改 tsx): 0 replay 错误
```

```bash
git add frontend/apps/web/src/pages/replay/IndexStrip.tsx \
        frontend/apps/web/src/pages/replay/EraBar.tsx \
        frontend/apps/web/src/pages/replay/Cockpit.tsx \
        frontend/apps/web/src/pages/replay/PoolPanel.tsx \
        frontend/apps/web/src/pages/replay/OrderTicket.tsx \
        frontend/apps/web/src/pages/replay/ReviewView.tsx \
        frontend/apps/web/src/pages/replay/Replay.css
git commit -m "feat(replay): 指数带+时代背景条(策划事件60天窗+as-of新闻)+名称行业全列表展示"
```

---

### Task 7: 前端 — 批量入池 + AI 建组合提案弹层

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/AddStockModal.tsx`、`api.ts`（generatePortfolio 已在 Task 5 加）
- Test: 无新单测（UI 组装；store.addSymbols 已在 Task 5 测过）

**Interfaces:**
- Consumes: Task 5 `addSymbols`/`generatePortfolio`/`cash`；`POST /course-portfolio/generate` 请求 `{total_capital, risk_profile, stock_count, as_of}`。
- Produces: 选股器页签「一键入池 Top10」；新页签 `portfolio`（AI 建组合：档位/只数/资金 → 生成提案 → 勾选入池）。Task 8 验收。

- [ ] **Step 1: screener 页签加批量按钮**

tab 类型加 `'portfolio'`；tab 数组追加 `['portfolio', 'AI建组合']`。screener 结果表头区（运行按钮旁）加：

```tsx
<button className="replay-btn primary"
  disabled={!rows.length}
  onClick={() => void (async () => {
    const syms = rows.slice(0, 10).map((r) => String(r.symbol));
    const r = await addSymbolsBatch(syms);
    setHint(`已入池 ${r.added} 只${r.failed.length
      ? `,失败 ${r.failed.length} 只(${r.failed.join(',')})` : ''}`);
  })()}>
  一键入池 Top10
</button>
```

（`addSymbolsBatch` = `useReplayStore((s) => s.addSymbols)`；弹层保持打开，不 onClose。）

- [ ] **Step 2: AI 建组合页签**

```tsx
const PROFILES: [string, string][] = [
  ['defensive', '防御(股息70/蓝筹30)'],
  ['balanced', '均衡(50/40/10)'],
  ['aggressive', '进取(30/50/20)'],
  ['radical', '激进(成长70)'],
];
```

页签状态：`profile='balanced'`、`count=6`、`capital`(默认 store cash,本地 state 初始化一次)、`plan: GenerateResp|null`、`picked: Set<string>`。生成按钮调 `api.generatePortfolio({total_capital: capital, risk_profile: profile, stock_count: count, as_of: vd})`；响应存 plan、picked 默认全选。提案表：勾选框 / `symbol+name` / category 中文映射(股息/蓝筹/成长) / `target_weight%` / `pe_band?.state ?? '—'`（中文映射 oversaled→低估…按 state 原值展示即可，不强翻译）。底部「勾选入池 (N)」→ `addSymbols([...picked])` → hint 结果，弹层不关。

**红线核验步（必做）**：生成后抽查 `plan.legs[0].current_price` 与该股 `GET /replay/kline?asof=vd` 末根 close 一致（curl 或前端 console 皆可，记录在任务报告）。若不一致说明 generate 内部价格/PE 用了今天（`_load_pe_series` 硬编码 `date.today()` 嫌疑），**修法**：`course_portfolio_router.py` 的 `_load_pe_series` 与相关调用加 `as_of` 参数贯通（默认今天，generate 传请求里的 as_of），重跑本核验。

- [ ] **Step 3: 验证 + Commit**

```bash
cd frontend/apps/web && npx vitest run src/pages/replay/ && pnpm build
```

```bash
git add frontend/apps/web/src/pages/replay/AddStockModal.tsx
# 若触发红线核验修复,一并 add course_portfolio_router.py
git commit -m "feat(replay): 选股器一键入池Top10+AI建组合提案页签(as_of口径,勾选入池)"
```

---

### Task 8: 前端 — 回测跳转 + 全链路验收

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/Cockpit.tsx`、`ReviewView.tsx`、`frontend/apps/web/src/pages/LongTermBacktest.tsx`

**Interfaces:**
- Consumes: store `pool/start_date/viewDate/nav`。
- Produces: 舱内与复盘页「丢给回测实验室」按钮；`/lt-backtest?symbols=&start=&end=` 预填。

- [ ] **Step 1: LongTermBacktest 预填（L124-128 改造）**

```ts
const qp = new URLSearchParams(window.location.search);
const [symbols, setSymbols] = useState(qp.get('symbols') || 'sh000300');
const [benchmark, setBenchmark] = useState('sh000300');
const [startDate, setStartDate] = useState(qp.get('start') || '2020-01-01');
const [endDate, setEndDate] = useState(qp.get('end') || '2025-12-31');
```

（仅改这三个初始化行；`topTab` 的 L117 读取保留。）

- [ ] **Step 2: 两处跳转按钮**

Cockpit（PlayControls 同行或 TopBar 右侧）与 ReviewView 顶栏各加：

```tsx
<button className="replay-btn" disabled={!pool.length}
  onClick={() => {
    const end = /* Cockpit: viewDate; Review: nav.at(-1)?.date ?? session.start_date */;
    window.open(`/lt-backtest?symbols=${
      encodeURIComponent(pool.join(','))}&start=${
      session!.start_date}&end=${end}`, '_blank');
  }}>
  丢给回测实验室
</button>
```

- [ ] **Step 3: 全链路验证**

```bash
# 前端
cd frontend/apps/web && npx vitest run && pnpm build
# 后端
cd ../../../backend && uv run pytest tests/api/test_replay_router.py -q   # 17
# 起服务(worktree 端口 12102/另起前端 12001)做 curl 冒烟:
# 1) POST /replay/sessions → advance days=3 断言 indices 四键
# 2) GET /replay/instrument/sh600519 → name=贵州茅台
# 3) GET /replay/news?asof=2020-03-13(若 Task4 已回填该窗) → 含回填头条
# 4) POST /course-portfolio/generate as_of=2020-03-13 → legs 非空且 current_price 与 kline 末根一致
# 5) 浏览器手动清单(留用户): 指数带随播放刷新/回看时指数回退/时代背景条事件chips/名称行业显示/一键入池/AI建组合/丢回测预填
```

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/pages/replay/Cockpit.tsx \
        frontend/apps/web/src/pages/replay/ReviewView.tsx \
        frontend/apps/web/src/pages/LongTermBacktest.tsx
git commit -m "feat(replay): 一键丢给回测实验室——URL query预填symbols/区间,舱内+复盘双入口"
```

---

## Self-Review 记录

- **Spec 覆盖**：§3 Phase0→Task1；§4 指数带→Task2/5/6；§5 三层大事件→Task3(news端点)/4(回填)/6(背景条,macro events 复用)；§6 名称行业→Task3(instrument)/5(持久化)/6(展示)；§7 批量入池/组合提案/回测跳转→Task7/8；§8 红线与兼容→Task3 泄漏断言/Task5 旧 state 容错；§9 分解与任务一一对应。
- **占位符**：已清除——EraBar/IndexStrip 均为完整组件实现；akshare 列名映射唯一的外部依赖点，明确"以 Step1 实测为准修正"。
- **类型一致性**：`AdvanceResp.indices`/`SessionState.names|industries`/`InstrumentInfo`/`NewsItem` 前后端字段一一对应；`addSymbols` 返回 `{added, failed}` 在 Task5 定义、Task7 消费；`INDEX_SYMBOLS/INDEX_NAMES` store 导出供 IndexStrip 使用。
- **已知风险内嵌**：generate 的 as_of 纯度核验（Task7 Step2 红线步）；intel_news 实体与实库索引漂移不影响 news 端点（走 `idx_intel_news_published`）。
