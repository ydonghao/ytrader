# 时光机模拟驾驶舱 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/replay` 时光机模拟炒股：盲盒训练（未来数据后端截断遮蔽）逐日推进 + 拟真成交规则 + 揭晓复盘，前端驱动引擎、后端 as-of 数据切片与存档。

**Architecture:** 前端 zustand 状态机驱动旅程（成交/净值纯函数引擎），后端新增 replay 模块：SQLModel 两张存档表 + psycopg2 裸 SQL 的 as-of 行情切片端点（kline/advance/valuation/board），选股器直接复用现有 `/screener/screen`（自带 as_of）。

**Tech Stack:** Python 3.13 / FastAPI / SQLModel / psycopg2 / pytest+TestClient（真实 PG）；React 18 / rsbuild / zustand v5 / lightweight-charts v5 / recharts / vitest（新引入，仅测引擎纯函数）。

**设计文档:** `docs/superpowers/specs/2026-09-14-time-machine-replay-design.md`（含 §12 spike 结论）。

## Global Constraints

- 后端响应协议 `{code, msg, data}`，`code==0` 成功；用 `src.pkg.responses.success/fail`。
- 后端代码 black 风格 line-length=79；提交信息用中文 conventional commit（参照 `git log`）。
- 行情切片一律 psycopg2 裸 SQL（`stock_ohlcv`/`index_ohlcv` 非 SQLModel 表）；replay 自有表走 SQLModel repository。
- **新 SQLModel 表必须在 `main.py` lifespan 的模型 import 块注册**（否则生产进程不建表）。
- 价格口径：`stock_ohlcv` 原样（真实历史成交价），不模拟分红/送转现金流。
- **Symbol 格式（Task 1 实测）**：库内统一小写带市场前缀——指数 `sh000001`/`sh000300`、A 股 `sh600519`/`sz000001`、北交 `bj830799`。SQL 侧 `.lower()` 归一直传；前端 `priceLimitRatio` 先剥离 2 位字母前缀再判板块；`CALENDAR_SYMBOL="sh000001"`、默认基准 `"sh000300"`。
- 财报 as-of 口径 = `report_date ≤ asof − 60 天`（`FINANCIAL_LAG_DAYS`，库无披露日列），UI 如实标注。
- A 股配色：红涨 `#ff453a` / 绿跌 `#30d158`（`src/lib/chartTheme.ts`）。
- 前端不改 `packages/` 共享包、不改既有页面文件（仅 App.tsx/Layout.tsx 注册新页）。
- 后端测试：`TestClient(create_app())` 打真实本地 PG，`try/finally` 清理；**只跑新增测试文件**（全量有 52 项既有失败，与本次无关）。
- 前端测试：vitest 仅测 `src/pages/replay/engine/` 与 `store.ts` 纯逻辑；UI 手动验收。
- 防未来函数红线：所有行情/估值/榜单 SQL 必须带 `≤ asof` 过滤；选股器调用必须传 `as_of`。

---

### Task 1: 后端 — 数据格式验证 + replay 表模型注册

**Files:**
- Create: `backend/src/infra/database/replay/__init__.py`（空文件）
- Create: `backend/src/infra/database/replay/models.py`
- Modify: `backend/main.py`（lifespan 模型 import 块，L139-142 watchlist 块之后）
- Test: `backend/tests/api/test_replay_router.py`（本任务先建骨架，后续任务持续追加）

**Interfaces:**
- Produces: 表 `replay_session` / `replay_trade`；模型类 `ReplaySession` / `ReplayTrade`（Task 2 的 repository 依赖）。

- [ ] **Step 1: 只读验证库内 symbol 格式（决定 CALENDAR_SYMBOL / 默认基准的写法）**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
python -c "from conf import app_config; print(app_config.database.url)"
# 用输出的 DSN 连 psql，执行：
#   SELECT symbol FROM index_ohlcv WHERE symbol ILIKE '%000001%' OR symbol ILIKE '%000300%' LIMIT 10;
#   SELECT symbol FROM stock_ohlcv LIMIT 3;
#   SELECT COUNT(*) FROM stock_dividend;
```

Expected: 确认指数 symbol 是 `SH000001`/`SH000300` 大写格式、股票是 6 位数字。**若实际格式不同，后续所有任务里的 `CALENDAR_SYMBOL`/`SH000300` 以实测为准**（下文均按大写格式书写）。

- [ ] **Step 2: 写表模型**

`backend/src/infra/database/replay/__init__.py` 为空文件。`models.py`：

```python
"""时光机模拟驾驶舱 — 旅程会话与成交记录表。

本模块必须在 main.py 启动时被 import，否则主服务进程的 create_all
看不到这些表（参考 watchlist.models 的注册方式）。
"""
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ReplaySession(SQLModel, table=True):
    """一次时光机旅程。单用户/全局（无 user_id，同 watchlist）。"""

    __tablename__ = "replay_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    status: str = "active"  # active | revealed
    start_date: date
    current_date: date
    end_date: Optional[date] = None
    initial_capital: float
    cash: float  # 冗余快照，列表页展示用
    benchmark_symbol: str = "sh000300"
    # {pool: [symbol], positions: [{symbol,shares,cost_price,buy_date}],
    #  nav: [{date, value}]}
    state: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ReplayTrade(SQLModel, table=True):
    """旅程内一笔成交（当日收盘价撮合）。"""

    __tablename__ = "replay_trade"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="replay_session.id", index=True)
    trade_date: date
    symbol: str
    side: str  # buy | sell
    price: float  # stock_ohlcv 原样口径
    shares: int
    fee: float  # 佣金
    tax: float = 0.0  # 印花税（卖出）
    note: Optional[str] = None  # 下单理由，复盘回看
    created_at: datetime = Field(default_factory=datetime.now)
```

- [ ] **Step 3: main.py lifespan 注册模型**

`backend/main.py` L139-142 watchlist import 块之后追加（缩进与该块对齐）：

```python
            # Import replay models so create_all picks up replay_session /
            # replay_trade tables on first connection.
            from src.infra.database.replay.models import (  # noqa: F401
                ReplaySession,
                ReplayTrade,
            )
```

- [ ] **Step 4: 验证建表**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
python -c "
from main import create_app
from fastapi.testclient import TestClient
with TestClient(create_app()) as c:
    pass  # lifespan 触发 create_all
"
# psql 确认：
#   \d replay_session
#   \d replay_trade
```

Expected: 两张表存在，列与 Step 2 一致。

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/infra/database/replay backend/main.py
git commit -m "feat(replay): replay_session/replay_trade 两张存档表+main lifespan注册"
```

---

### Task 2: 后端 — 会话与成交 CRUD API

**Files:**
- Create: `backend/src/infra/database/replay/repository.py`
- Create: `backend/src/api/handler/replay_handler.py`
- Create: `backend/src/api/router/replay_router.py`
- Modify: `backend/main.py`（router import L36 附近 + include_router L326 附近）
- Test: `backend/tests/api/test_replay_router.py`

**Interfaces:**
- Consumes: Task 1 的 `ReplaySession`/`ReplayTrade`。
- Produces（Task 3/4 复用本任务的 helper）：
  - `replay_handler._conn() -> psycopg2 connection`
  - `replay_handler._repo() -> ReplayRepository`
  - `replay_handler.CALENDAR_SYMBOL = "sh000001"`
  - `replay_handler._bar(r: dict) -> dict`（date→iso、数值→float/int 转换）
  - 端点：`POST/GET /replay/sessions`、`GET/PUT/DELETE /replay/sessions/{id}`、`POST /replay/sessions/{id}/reveal`、`POST/GET /replay/sessions/{id}/trades`

- [ ] **Step 1: 写 repository**

`backend/src/infra/database/replay/repository.py`：

```python
"""replay 会话/成交的 SQLModel 仓储（惯例同 watchlist.repository）。"""
import threading
from datetime import date, datetime
from typing import Optional

from sqlmodel import select

from src.infra.database.replay.models import ReplaySession, ReplayTrade
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_replay_repository(
    db_connection: DBConnection | None = None,
) -> "ReplayRepository":
    return ReplayRepository(db_connection or _get_db_connection())


class ReplayRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def create(self, s: ReplaySession) -> ReplaySession:
        with self._db.session_scope() as sess:
            sess.add(s)
            sess.flush()
            sess.refresh(s)
            return s

    def list(self) -> list[ReplaySession]:
        with self._db.session_scope() as sess:
            return list(
                sess.exec(
                    select(ReplaySession).order_by(ReplaySession.id.desc())
                ).all()
            )

    def get(self, session_id: int) -> Optional[ReplaySession]:
        with self._db.session_scope() as sess:
            return sess.get(ReplaySession, session_id)

    def save_state(
        self,
        session_id: int,
        current_date: date,
        cash: float,
        state: dict,
    ) -> bool:
        with self._db.session_scope() as sess:
            row = sess.get(ReplaySession, session_id)
            if row is None:
                return False
            row.current_date = current_date
            row.cash = cash
            row.state = state  # 整体赋值（JSONB 原地 mutate 不会被跟踪）
            row.updated_at = datetime.now()
            sess.add(row)
            return True

    def set_status(self, session_id: int, status: str) -> bool:
        with self._db.session_scope() as sess:
            row = sess.get(ReplaySession, session_id)
            if row is None:
                return False
            row.status = status
            row.updated_at = datetime.now()
            sess.add(row)
            return True

    def delete(self, session_id: int) -> None:
        with self._db.session_scope() as sess:
            trades = sess.exec(
                select(ReplayTrade).where(
                    ReplayTrade.session_id == session_id
                )
            ).all()
            for t in trades:
                sess.delete(t)
            row = sess.get(ReplaySession, session_id)
            if row is not None:
                sess.delete(row)

    def add_trade(self, t: ReplayTrade) -> ReplayTrade:
        with self._db.session_scope() as sess:
            sess.add(t)
            sess.flush()
            sess.refresh(t)
            return t

    def list_trades(self, session_id: int) -> list[ReplayTrade]:
        with self._db.session_scope() as sess:
            return list(
                sess.exec(
                    select(ReplayTrade)
                    .where(ReplayTrade.session_id == session_id)
                    .order_by(ReplayTrade.trade_date, ReplayTrade.id)
                ).all()
            )
```

- [ ] **Step 1b: models.py 默认基准改实测格式**

Task 1 实测库内 symbol 为小写带前缀。`backend/src/infra/database/replay/models.py` 中：

```python
    benchmark_symbol: str = "sh000300"
```

（原 `"SH000300"` 改掉；Task 1 按当时 brief 原样落地，本步修正。）

- [ ] **Step 2: 写 handler 的会话/成交部分（行情切片在 Task 3/4 追加）**

`backend/src/api/handler/replay_handler.py`：

```python
"""时光机 handler：会话 CRUD + 成交存档 + as-of 行情切片。

状态权威在前端引擎（设计文档 §3/§5），后端只做数据截断供给与存档。
"""
from datetime import date
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from src.infra.database.replay.models import ReplaySession, ReplayTrade
from src.infra.database.sql_engine.dsn import get_dsn
from src.pkg import responses

CALENDAR_SYMBOL = "sh000001"  # 上证指数日线 = 交易日历


def _conn():
    return psycopg2.connect(get_dsn())


def _repo():
    from src.infra.database.replay.repository import (
        create_replay_repository,
    )
    return create_replay_repository()


def _bar(r: dict) -> dict:
    """裸 SQL 行 → 前端 ReplayBar（date→iso，数值转原生类型）。"""
    return {
        "trade_date": r["trade_date"].isoformat(),
        "open": float(r["open"]),
        "close": float(r["close"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "volume": int(r["volume"] or 0),
        "amount": float(r["amount"] or 0),
    }


def _parse_day(s: Optional[str], field: str):
    if not s:
        return None, responses.fail(f"{field} 必填")
    try:
        return date.fromisoformat(s), None
    except ValueError:
        return None, responses.fail(f"{field} 格式应为 YYYY-MM-DD")


def _next_trading_day(d: date) -> Optional[date]:
    """>= d 的第一个交易日（以指数日线为历）。"""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(trade_date::date) FROM index_ohlcv "
            "WHERE symbol = %s AND trade_date::date >= %s",
            (CALENDAR_SYMBOL, d),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _session_dict(s: ReplaySession, with_state: bool = True) -> dict:
    out = {
        "id": s.id,
        "name": s.name,
        "status": s.status,
        "start_date": s.start_date.isoformat(),
        "current_date": s.current_date.isoformat(),
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "initial_capital": s.initial_capital,
        "cash": s.cash,
        "benchmark_symbol": s.benchmark_symbol,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }
    if with_state:
        out["state"] = s.state or {"pool": [], "positions": [], "nav": []}
    return out


def _trade_dict(t: ReplayTrade) -> dict:
    return {
        "id": t.id,
        "session_id": t.session_id,
        "trade_date": t.trade_date.isoformat(),
        "symbol": t.symbol,
        "side": t.side,
        "price": t.price,
        "shares": t.shares,
        "fee": t.fee,
        "tax": t.tax,
        "note": t.note,
    }


# ── 会话 CRUD ──


def create_session(body: dict):
    name = (body.get("name") or "").strip()
    capital = body.get("initial_capital")
    d, err = _parse_day(body.get("start_date"), "start_date")
    if err:
        return err
    if not name:
        return responses.fail("name 必填")
    try:
        capital = float(capital)
    except (TypeError, ValueError):
        return responses.fail("initial_capital 应为正数")
    if capital <= 0:
        return responses.fail("initial_capital 应为正数")
    if d >= date.today():
        return responses.fail("起始日期必须早于今天")
    first = _next_trading_day(d)
    if first is None:
        return responses.fail("起始日期之后没有交易日数据")
    end_d, err = _parse_day(body.get("end_date"), "end_date") \
        if body.get("end_date") else (None, None)
    if err:
        return err
    if end_d is not None and end_d <= first:
        return responses.fail("end_date 必须晚于起始交易日")
    s = ReplaySession(
        name=name,
        start_date=first,
        current_date=first,
        end_date=end_d,
        initial_capital=capital,
        cash=capital,
        benchmark_symbol=body.get("benchmark_symbol") or "sh000300",
        state={"pool": [], "positions": [], "nav": []},
    )
    return responses.success(_session_dict(_repo().create(s)))


def list_sessions():
    rows = _repo().list()
    return responses.success([_session_dict(s, with_state=False)
                              for s in rows])


def get_session(session_id: int):
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    return responses.success(_session_dict(s))


def save_state(session_id: int, body: dict):
    d, err = _parse_day(body.get("current_date"), "current_date")
    if err:
        return err
    state = body.get("state")
    if not isinstance(state, dict):
        return responses.fail("state 应为对象")
    try:
        cash = float(body.get("cash"))
    except (TypeError, ValueError):
        return responses.fail("cash 应为数字")
    ok = _repo().save_state(session_id, d, cash, state)
    return responses.success({"id": session_id}) if ok \
        else responses.fail("会话不存在")


def reveal(session_id: int):
    ok = _repo().set_status(session_id, "revealed")
    return responses.success({"id": session_id, "status": "revealed"}) \
        if ok else responses.fail("会话不存在")


def delete_session(session_id: int):
    _repo().delete(session_id)
    return responses.success({"id": session_id})


# ── 成交存档 ──


def add_trade(session_id: int, body: dict):
    repo = _repo()
    s = repo.get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if s.status != "active":
        return responses.fail("会话已揭晓，不能再记成交")
    d, err = _parse_day(body.get("trade_date"), "trade_date")
    if err:
        return err
    side = body.get("side")
    if side not in ("buy", "sell"):
        return responses.fail("side 应为 buy|sell")
    try:
        t = ReplayTrade(
            session_id=session_id,
            trade_date=d,
            symbol=str(body["symbol"]),
            side=side,
            price=float(body["price"]),
            shares=int(body["shares"]),
            fee=float(body.get("fee") or 0),
            tax=float(body.get("tax") or 0),
            note=body.get("note") or None,
        )
    except (KeyError, TypeError, ValueError):
        return responses.fail("symbol/price/shares 必填且为数字")
    return responses.success(_trade_dict(repo.add_trade(t)))


def list_trades(session_id: int):
    rows = _repo().list_trades(session_id)
    return responses.success([_trade_dict(t) for t in rows])
```

- [ ] **Step 3: 写 router**

`backend/src/api/router/replay_router.py`：

```python
"""时光机模拟驾驶舱 API — 会话存档 + as-of 行情切片。"""
from fastapi import APIRouter, Query

from src.api.handler import replay_handler as h

router = APIRouter(prefix="/replay", tags=["replay"])


@router.post("/sessions")
def _create_session(body: dict):
    return h.create_session(body)


@router.get("/sessions")
def _list_sessions():
    return h.list_sessions()


@router.get("/sessions/{session_id}")
def _get_session(session_id: int):
    return h.get_session(session_id)


@router.put("/sessions/{session_id}/state")
def _save_state(session_id: int, body: dict):
    return h.save_state(session_id, body)


@router.post("/sessions/{session_id}/reveal")
def _reveal(session_id: int):
    return h.reveal(session_id)


@router.delete("/sessions/{session_id}")
def _delete_session(session_id: int):
    return h.delete_session(session_id)


@router.post("/sessions/{session_id}/trades")
def _add_trade(session_id: int, body: dict):
    return h.add_trade(session_id, body)


@router.get("/sessions/{session_id}/trades")
def _list_trades(session_id: int):
    return h.list_trades(session_id)


@router.get("/kline/{symbol}")
def _kline(symbol: str, asof: str = Query(...), limit: int = Query(300)):
    return h.kline(symbol, asof, limit)


@router.get("/advance")
def _advance(session_id: int = Query(...), days: int = Query(1)):
    return h.advance(session_id, days)


@router.get("/valuation/{symbol}")
def _valuation(symbol: str, asof: str = Query(...)):
    return h.valuation(symbol, asof)


@router.get("/board")
def _board(
    asof: str = Query(...),
    type: str = Query("gainers"),
    limit: int = Query(50),
):
    return h.board(asof, type, limit)
```

（`h.kline`/`h.advance`/`h.valuation`/`h.board` 在 Task 3/4 实现，本任务 router 先引全，测试只覆盖会话部分。）

- [ ] **Step 4: main.py 接线**

import 块（L36 `from src.api.router.watchlist_router import ...` 之后）：

```python
from src.api.router.replay_router import router as replay_router
```

`create_app()` 内（L326 watchlist include 之后）：

```python
app.include_router(replay_router, prefix="/api/v1")  # /api/v1/replay
```

- [ ] **Step 5: 写失败测试**

`backend/tests/api/test_replay_router.py`：

```python
"""时光机 replay router 集成测试 — TestClient 打本地 PG，自带清理。

依赖本地 Postgres（见 tests/conftest.py）。只跑本文件：
python -m pytest tests/api/test_replay_router.py -v
"""
import datetime as dt

import psycopg2
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app
    return TestClient(create_app())


def _create(client, **kw):
    body = {
        "name": "TS_旅程",
        "start_date": "2020-03-13",
        "initial_capital": 1_000_000,
    }
    body.update(kw)
    return client.post("/api/v1/replay/sessions", json=body)


def _cleanup(client, sid):
    client.delete(f"/api/v1/replay/sessions/{sid}")


class TestReplaySession:
    def test_session_lifecycle(self, client):
        sid = None
        try:
            r = _create(client)
            assert r.status_code == 200 and r.json()["code"] == 0, r.text
            data = r.json()["data"]
            sid = data["id"]
            # 2020-03-13 是交易日，不 snap
            assert data["current_date"] == "2020-03-13"
            assert data["status"] == "active"
            assert data["state"] == {"pool": [], "positions": [], "nav": []}

            r = client.get("/api/v1/replay/sessions")
            assert any(s["id"] == sid for s in r.json()["data"])
            # 列表不带 state
            assert "state" not in next(
                s for s in r.json()["data"] if s["id"] == sid)

            # 存档往返
            r = client.put(
                f"/api/v1/replay/sessions/{sid}/state",
                json={
                    "current_date": "2020-03-16",
                    "cash": 900000.5,
                    "state": {
                        "pool": ["600519"],
                        "positions": [{
                            "symbol": "600519", "shares": 100,
                            "cost_price": 996.0, "buy_date": "2020-03-13",
                        }],
                        "nav": [{"date": "2020-03-16", "value": 999000.5}],
                    },
                },
            )
            assert r.json()["code"] == 0, r.text
            r = client.get(f"/api/v1/replay/sessions/{sid}")
            got = r.json()["data"]
            assert got["current_date"] == "2020-03-16"
            assert got["cash"] == 900000.5
            assert got["state"]["pool"] == ["600519"]
            assert got["state"]["positions"][0]["shares"] == 100

            # 成交记录
            r = client.post(
                f"/api/v1/replay/sessions/{sid}/trades",
                json={
                    "trade_date": "2020-03-13", "symbol": "600519",
                    "side": "buy", "price": 996.0, "shares": 100,
                    "fee": 24.9, "tax": 0, "note": "TS_理由",
                },
            )
            assert r.json()["code"] == 0, r.text
            r = client.get(f"/api/v1/replay/sessions/{sid}/trades")
            trades = r.json()["data"]
            assert len(trades) == 1
            assert trades[0]["note"] == "TS_理由"
            assert trades[0]["side"] == "buy"

            # 揭晓不可逆 + 揭晓后拒绝记成交
            r = client.post(f"/api/v1/replay/sessions/{sid}/reveal")
            assert r.json()["data"]["status"] == "revealed"
            r = client.post(
                f"/api/v1/replay/sessions/{sid}/trades",
                json={
                    "trade_date": "2020-03-16", "symbol": "600519",
                    "side": "sell", "price": 1000.0, "shares": 100,
                    "fee": 25.0, "tax": 50.0,
                },
            )
            assert r.json()["code"] != 0
        finally:
            if sid is not None:
                _cleanup(client, sid)
        r = client.get(f"/api/v1/replay/sessions/{sid}")
        assert r.json()["code"] != 0

    def test_create_validation(self, client):
        # 起始日不能是今天/未来
        today = dt.date.today().isoformat()
        assert _create(client, start_date=today).json()["code"] != 0
        # 非交易日 snap 到下一交易日：2020-03-14(周六) → 2020-03-16(周一)
        sid = None
        try:
            r = _create(client, name="TS_snap", start_date="2020-03-14")
            assert r.json()["code"] == 0, r.text
            data = r.json()["data"]
            sid = data["id"]
            assert data["current_date"] >= "2020-03-14"
            assert data["start_date"] == data["current_date"]
        finally:
            if sid is not None:
                _cleanup(client, sid)
        # 非法参数
        assert _create(client, initial_capital=0).json()["code"] != 0
        assert _create(client, name="").json()["code"] != 0
```

- [ ] **Step 6: 跑测试确认前 4 个端点可用、kline/advance 等报 500/404（未实现）**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
python -m pytest tests/api/test_replay_router.py::TestReplaySession -v
```

Expected: `test_session_lifecycle` 与 `test_create_validation` **PASS**（会话部分已实现）；若因 router 引了未实现的 `h.kline` 导致 import 失败，属预期——Task 3 补齐。

> 注：若 import 阻塞了会话测试，可先在 handler 末尾加 4 个桩函数 `def kline(...): return responses.fail("未实现")`，Task 3/4 替换为真实现。

- [ ] **Step 7: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/infra/database/replay/repository.py \
        backend/src/api/handler/replay_handler.py \
        backend/src/api/router/replay_router.py \
        backend/main.py backend/tests/api/test_replay_router.py
git commit -m "feat(replay): 会话CRUD+成交存档API——state快照往返/揭晓拒单/起始日snap"
```

---

### Task 3: 后端 — K 线切片与推进（advance）端点

**Files:**
- Modify: `backend/src/api/handler/replay_handler.py`（追加 `kline`/`advance`）
- Test: `backend/tests/api/test_replay_router.py`（追加 `TestReplaySlicing`）

**Interfaces:**
- Consumes: Task 2 的 `_conn/_bar/CALENDAR_SYMBOL/_parse_day/_repo`；`ReplaySession.state["pool"]`。
- Produces:
  - `GET /replay/kline/{symbol}?asof&limit` → `data: {symbol, bars: [ReplayBar]}`，bars 升序、全部 `trade_date ≤ asof`
  - `GET /replay/advance?session_id&days` → `data: {dates: [str], bars: {symbol: [ReplayBar]}, benchmark: [ReplayBar]}`；dates 为 current_date 之后（不含）的 N 个交易日；池内标的停牌则该日无其 bar
  - 前端对应类型：`AdvanceResp`（Task 7 types.ts）

- [ ] **Step 1: 写失败测试（追加到 test_replay_router.py）**

```python
@pytest.fixture(scope="module")
def dyn_symbol():
    """动态选一只 2019-06 前就有数据的 A 股，避免硬编码依赖。"""
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol FROM stock_ohlcv "
                "WHERE trade_date::date < '2019-06-01' "
                "GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT 1"
            )
            row = cur.fetchone()
            assert row, "stock_ohlcv 无 2019-06 之前的数据"
            return row[0]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def trade_day():
    """≤2020-03-13 的最近一个交易日（动态，防硬编码）。"""
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(trade_date::date) FROM index_ohlcv "
                "WHERE symbol = 'sh000001' "
                "AND trade_date::date <= '2020-03-13'"
            )
            d = cur.fetchone()[0]
            assert d is not None
            return d.isoformat()
    finally:
        conn.close()


class TestReplaySlicing:
    def test_kline_asof_cutoff(self, client, dyn_symbol, trade_day):
        r = client.get(
            f"/api/v1/replay/kline/{dyn_symbol}",
            params={"asof": trade_day, "limit": 10},
        )
        assert r.json()["code"] == 0, r.text
        bars = r.json()["data"]["bars"]
        assert 0 < len(bars) <= 10
        assert all(b["trade_date"] <= trade_day for b in bars)
        assert [b["trade_date"] for b in bars] == sorted(
            b["trade_date"] for b in bars)
        assert {"open", "close", "high", "low",
                "volume", "amount"} <= set(bars[0])

    def test_kline_reject_future_asof(self, client, dyn_symbol):
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        r = client.get(
            f"/api/v1/replay/kline/{dyn_symbol}",
            params={"asof": tomorrow},
        )
        assert r.json()["code"] != 0

    def test_advance(self, client, dyn_symbol, trade_day):
        sid = None
        try:
            r = _create(client, name="TS_adv", start_date=trade_day)
            assert r.json()["code"] == 0, r.text
            sid = r.json()["data"]["id"]
            assert r.json()["data"]["current_date"] == trade_day
            client.put(
                f"/api/v1/replay/sessions/{sid}/state",
                json={
                    "current_date": trade_day, "cash": 1e6,
                    "state": {"pool": [dyn_symbol],
                              "positions": [], "nav": []},
                },
            )
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "days": 3})
            assert r.json()["code"] == 0, r.text
            data = r.json()["data"]
            assert len(data["dates"]) == 3
            assert data["dates"] == sorted(data["dates"])
            assert all(d > trade_day for d in data["dates"])
            # 池内标的 bar 只落在 dates 内
            for d in (b["trade_date"]
                      for b in data["bars"].get(dyn_symbol, [])):
                assert d in data["dates"]
            assert len(data["benchmark"]) >= 1
        finally:
            if sid is not None:
                _cleanup(client, sid)

    def test_advance_unknown_session(self, client):
        r = client.get("/api/v1/replay/advance",
                       params={"session_id": 99999999, "days": 1})
        assert r.json()["code"] != 0
```

- [ ] **Step 2: 跑测试确认 FAIL（h.kline/h.advance 不存在或桩返回"未实现"）**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
python -m pytest tests/api/test_replay_router.py::TestReplaySlicing -v
```

Expected: FAIL（AttributeError 或 code != 0）。

- [ ] **Step 3: 实现 `kline` / `advance`（追加到 replay_handler.py）**

```python
# ── 行情切片（Task 3） ──

_BAR_COLS = (
    "trade_date::date AS trade_date, open_ AS open, close_ AS close, "
    "high_ AS high, low_ AS low, volume, amount"
)


def _table_for(symbol: str) -> str:
    """replay 只处理日线：指数走 index_ohlcv，其余走 stock_ohlcv。"""
    s = symbol.lower()  # 库内统一小写带前缀（sh000300/sh600519）
    if s.startswith(("sh000", "sz399", "sw")):
        return "index_ohlcv"
    return "stock_ohlcv"


def kline(symbol: str, asof: str, limit: int = 300):
    d, err = _parse_day(asof, "asof")
    if err:
        return err
    if d > date.today():
        return responses.fail("asof 不能晚于今天")
    limit = max(1, min(limit, 3000))
    table = _table_for(symbol)
    sym = symbol.lower()  # 库内统一小写
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f'SELECT {_BAR_COLS} FROM "{table}" '
            "WHERE symbol = %s AND trade_date::date <= %s "
            "ORDER BY trade_date DESC LIMIT %s",
            (sym, d, limit),
        )
        rows = [_bar(r) for r in reversed(cur.fetchall())]
    return responses.success({"symbol": symbol, "bars": rows})


def advance(session_id: int, days: int = 1):
    """油门端点：会话 current_date 之后 N 个交易日的池内 bar + 基准。"""
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    days = max(1, min(days, 60))
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT trade_date::date AS d FROM index_ohlcv "
            "WHERE symbol = %s AND trade_date::date > %s "
            "ORDER BY trade_date LIMIT %s",
            (CALENDAR_SYMBOL, s.current_date, days),
        )
        dates = [r["d"] for r in cur.fetchall()]
        if not dates:
            return responses.success(
                {"dates": [], "bars": {}, "benchmark": []})
        d0, d1 = dates[0], dates[-1]
        pool = (s.state or {}).get("pool") or []
        bars: dict[str, list] = {}
        if pool:
            cur.execute(
                f"SELECT symbol, {_BAR_COLS} FROM stock_ohlcv "
                "WHERE symbol = ANY(%s) "
                "AND trade_date::date >= %s AND trade_date::date <= %s "
                "ORDER BY symbol, trade_date",
                (pool, d0, d1),
            )
            for r in cur.fetchall():
                sym = r.pop("symbol")
                bars.setdefault(sym, []).append(_bar(r))
        cur.execute(
            f"SELECT {_BAR_COLS} FROM index_ohlcv "
            "WHERE symbol = %s "
            "AND trade_date::date >= %s AND trade_date::date <= %s "
            "ORDER BY trade_date",
            (s.benchmark_symbol, d0, d1),
        )
        bench = [_bar(r) for r in cur.fetchall()]
    return responses.success({
        "dates": [d.isoformat() for d in dates],
        "bars": bars,
        "benchmark": bench,
    })
```

- [ ] **Step 4: 跑测试确认 PASS**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
python -m pytest tests/api/test_replay_router.py -v
```

Expected: 全部 PASS（含 Task 2 的 2 个）。

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/api/handler/replay_handler.py backend/tests/api/test_replay_router.py
git commit -m "feat(replay): kline截断+advance油门端点——交易日历/停牌缺日/基准指数"
```

---

### Task 4: 后端 — 估值分位 + 当日榜单端点

**Files:**
- Modify: `backend/src/api/handler/replay_handler.py`（追加 `valuation`/`board`）
- Test: `backend/tests/api/test_replay_router.py`（追加 `TestReplayValuationBoard`）

**Interfaces:**
- Consumes: `_conn/_parse_day`；`stock_valuation`（列 pe/pe_ttm/pb/ps/ps_ttm/dv_ratio/dv_ttm/total_mv，主键 symbol+trade_date）；`stock_info`（symbol/name）。
- Produces:
  - `GET /replay/valuation/{symbol}?asof` → `data: {as_of, pe_ttm: {value, percentile, window}|null, pb: {…}|null}`（分位窗口 10 年、剔负值、样本 <30 分位为 null——与 `percentile.py` 的 `SAMPLE_MIN=30` 一致）
  - `GET /replay/board?asof&type=gainers|amount&limit` → `data: [{symbol, name, close, pct_chg, amount}]`，gainers 按 pct_chg 降序、amount 按 amount 降序
  - 前端对应类型：`ValuationInfo`/`BoardRow`（Task 7 types.ts）

- [ ] **Step 1: 写失败测试**

```python
class TestReplayValuationBoard:
    def test_valuation(self, client, dyn_symbol, trade_day):
        r = client.get(
            f"/api/v1/replay/valuation/{dyn_symbol}",
            params={"asof": trade_day},
        )
        assert r.json()["code"] == 0, r.text
        data = r.json()["data"]
        assert data["as_of"] == trade_day
        assert set(data) >= {"pe_ttm", "pb"}
        for key in ("pe_ttm", "pb"):
            v = data[key]
            if v is not None:
                assert v["value"] > 0
                assert v["window"] == "10y"
                if v["percentile"] is not None:
                    assert 0 <= v["percentile"] <= 1

    def test_board_gainers(self, client, trade_day):
        r = client.get("/api/v1/replay/board",
                       params={"asof": trade_day, "type": "gainers"})
        assert r.json()["code"] == 0, r.text
        rows = r.json()["data"]
        assert len(rows) > 1
        pcts = [x["pct_chg"] for x in rows]
        assert pcts == sorted(pcts, reverse=True)
        assert {"symbol", "name", "close",
                "pct_chg", "amount"} <= set(rows[0])

    def test_board_amount(self, client, trade_day):
        r = client.get("/api/v1/replay/board",
                       params={"asof": trade_day, "type": "amount"})
        assert r.json()["code"] == 0, r.text
        amts = [x["amount"] for x in r.json()["data"]]
        assert amts == sorted(amts, reverse=True)

    def test_board_bad_type(self, client, trade_day):
        r = client.get("/api/v1/replay/board",
                       params={"asof": trade_day, "type": "hack"})
        assert r.json()["code"] != 0
```

- [ ] **Step 2: 跑测试确认 FAIL**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
python -m pytest tests/api/test_replay_router.py::TestReplayValuationBoard -v
```

Expected: FAIL（未实现）。

- [ ] **Step 3: 实现（追加到 replay_handler.py）**

```python
# ── 估值分位 / 当日榜单（Task 4） ──

_SAMPLE_MIN = 30  # 与 fundamental/percentile.py 的 SAMPLE_MIN 一致


def valuation(symbol: str, asof: str):
    d, err = _parse_day(asof, "asof")
    if err:
        return err
    if d > date.today():
        return responses.fail("asof 不能晚于今天")
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT pe_ttm, pb FROM stock_valuation "
            "WHERE symbol = %s AND trade_date <= %s "
            "ORDER BY trade_date DESC LIMIT 1",
            (symbol, d),
        )
        row = cur.fetchone()
        if row is None:
            return responses.fail("该日期之前无估值数据")
        out = {"as_of": d.isoformat(), "pe_ttm": None, "pb": None}
        for key in ("pe_ttm", "pb"):
            curv = row[key]
            if curv is None or curv <= 0:
                continue
            cur.execute(
                f"SELECT COUNT(*) AS n, "
                f"COUNT(*) FILTER (WHERE {key} <= %s) AS le "
                "FROM stock_valuation "
                "WHERE symbol = %s AND trade_date <= %s "
                "AND trade_date > %s::date - INTERVAL '10 years' "
                f"AND {key} IS NOT NULL AND {key} > 0",
                (float(curv), symbol, d, d),
            )
            agg = cur.fetchone()
            pct = None
            if agg and agg["n"] and agg["n"] >= _SAMPLE_MIN:
                pct = round(agg["le"] / agg["n"], 4)
            out[key] = {
                "value": float(curv),
                "percentile": pct,
                "window": "10y",
            }
    return responses.success(out)


def board(asof: str, type: str = "gainers", limit: int = 50):
    d, err = _parse_day(asof, "asof")
    if err:
        return err
    if d > date.today():
        return responses.fail("asof 不能晚于今天")
    if type not in ("gainers", "amount"):
        return responses.fail("type 应为 gainers|amount")
    order = "pct DESC" if type == "gainers" else "a.amount DESC"
    limit = max(1, min(limit, 200))
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT MAX(trade_date::date) FROM index_ohlcv "
            "WHERE symbol = %s AND trade_date::date < %s",
            (CALENDAR_SYMBOL, d),
        )
        prev = cur.fetchone()[0]
        if prev is None:
            return responses.fail("asof 之前无交易日")
        cur.execute(
            "SELECT a.symbol, a.close_ AS close, "
            "(a.close_ / NULLIF(p.close_, 0) - 1) * 100 AS pct, "
            "a.amount "
            "FROM stock_ohlcv a "
            "JOIN stock_ohlcv p ON p.symbol = a.symbol "
            "AND p.trade_date::date = %s "
            "WHERE a.trade_date::date = %s "
            f"ORDER BY {order} LIMIT %s",
            (prev, d, limit),
        )
        rows = cur.fetchall()
        symbols = [r["symbol"] for r in rows]
        names: dict[str, str] = {}
        if symbols:
            cur.execute(
                "SELECT symbol, name FROM stock_info "
                "WHERE symbol = ANY(%s)",
                (symbols,),
            )
            names = {r["symbol"]: r["name"] for r in cur.fetchall()}
    data = [{
        "symbol": r["symbol"],
        "name": names.get(r["symbol"], ""),
        "close": float(r["close"]),
        "pct_chg": round(float(r["pct"] or 0), 2),
        "amount": float(r["amount"] or 0),
    } for r in rows]
    return responses.success(data)
```

- [ ] **Step 4: 跑测试确认 PASS（本文件全量）**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
python -m pytest tests/api/test_replay_router.py -v
```

Expected: 6 个测试类全部 PASS。

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/api/handler/replay_handler.py backend/tests/api/test_replay_router.py
git commit -m "feat(replay): valuation十年分位+board当日榜单——asof截断/样本门控30"
```

---

### Task 5: 前端 — vitest 基建 + 类型 + 成交引擎 fill.ts

**Files:**
- Modify: `frontend/apps/web/package.json`（devDependencies + scripts）
- Create: `frontend/apps/web/vitest.config.ts`
- Create: `frontend/apps/web/src/pages/replay/types.ts`
- Create: `frontend/apps/web/src/pages/replay/engine/fill.ts`
- Test: `frontend/apps/web/src/pages/replay/engine/__tests__/fill.test.ts`

**Interfaces:**
- Produces（后续全部前端任务依赖）：
  - 类型：`ReplayBar/SessionMeta/SessionFull/Position/Trade/NavPoint/AccountState/OrderReq/AdvanceResp/ValuationInfo/BoardRow`
  - `priceLimitRatio(symbol, name?): number`（主板 .1 / 300·301·688·689 → .2 / 8·4·92 开头 → .3 / 名称含 ST → .05）
  - `round2/limitPrices/commission/stampTax`（印花税率：date ≥ 2023-08-28 → 0.0005，否则 0.001）
  - `tryFill(acct, req, ctx): FillResult`——收盘价成交、涨停拒买/跌停拒卖、整手 100、T+1（`buy_date < ctx.date` 才可卖）、资金/持仓校验

- [ ] **Step 1: vitest 基建**

`frontend/apps/web/package.json` 的 `devDependencies` 加 `"vitest": "^2.1.9"`，`scripts` 加 `"test": "vitest run"`。然后：

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend
rush update   # rush 管理依赖；若失败回退 pnpm install
```

`frontend/apps/web/vitest.config.ts`：

```ts
import {defineConfig} from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
});
```

- [ ] **Step 2: 写类型**

`frontend/apps/web/src/pages/replay/types.ts`：

```ts
/** 时光机 — 与后端 replay 端点/data 形状一一对应。 */
export interface ReplayBar {
  trade_date: string; // "2020-03-13"
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
}

export interface SessionMeta {
  id: number;
  name: string;
  status: 'active' | 'revealed';
  start_date: string;
  current_date: string;
  end_date: string | null;
  initial_capital: number;
  cash: number;
  benchmark_symbol: string;
}

export interface Position {
  symbol: string;
  shares: number;
  cost_price: number;
  buy_date: string;
}

export interface NavPoint {
  date: string;
  value: number;
}

export interface SessionState {
  pool: string[];
  positions: Position[];
  nav: NavPoint[];
}

export interface SessionFull extends SessionMeta {
  state: SessionState;
}

export interface Trade {
  id?: number;
  trade_date: string;
  symbol: string;
  side: 'buy' | 'sell';
  price: number;
  shares: number;
  fee: number;
  tax: number;
  note?: string | null;
}

export interface AccountState {
  cash: number;
  positions: Position[];
}

export interface OrderReq {
  symbol: string;
  side: 'buy' | 'sell';
  shares: number;
  note?: string;
}

export interface AdvanceResp {
  dates: string[];
  bars: Record<string, ReplayBar[]>;
  benchmark: ReplayBar[];
}

export interface ValuationMetric {
  value: number;
  percentile: number | null;
  window: string;
}

export interface ValuationInfo {
  as_of: string;
  pe_ttm: ValuationMetric | null;
  pb: ValuationMetric | null;
}

export interface BoardRow {
  symbol: string;
  name: string;
  close: number;
  pct_chg: number;
  amount: number;
}

export interface ApiResp<T> {
  code: number;
  msg: string;
  data: T;
}
```

- [ ] **Step 3: 写失败测试**

`frontend/apps/web/src/pages/replay/engine/__tests__/fill.test.ts`：

```ts
import {describe, expect, it} from 'vitest';
import {commission, priceLimitRatio, stampTax, tryFill} from '../fill';
import type {AccountState} from '../../types';

const acct = (cash: number, positions: AccountState['positions'] = []): AccountState => ({cash, positions});

describe('priceLimitRatio', () => {
  it('按板块分档', () => {
    expect(priceLimitRatio('600519')).toBe(0.1);
    expect(priceLimitRatio('sh600519')).toBe(0.1); // 带库内前缀
    expect(priceLimitRatio('sz300750')).toBe(0.2);
    expect(priceLimitRatio('bj830799')).toBe(0.3);
    expect(priceLimitRatio('000001')).toBe(0.1);
    expect(priceLimitRatio('300750')).toBe(0.2);
    expect(priceLimitRatio('688981')).toBe(0.2);
    expect(priceLimitRatio('830799')).toBe(0.3);
    expect(priceLimitRatio('600519', 'ST茅台')).toBe(0.05);
  });
});

describe('费用', () => {
  it('佣金万2.5最低5元', () => {
    expect(commission(1000)).toBe(5);
    expect(commission(100000)).toBe(25);
  });
  it('印花税按日期换挡', () => {
    expect(stampTax(100000, '2020-01-06')).toBe(100);
    expect(stampTax(100000, '2024-01-02')).toBe(50);
  });
});

describe('tryFill 买入', () => {
  const ctx = {date: '2020-03-13', close: 11, prevClose: 10};
  it('涨停拒买（主板10%）', () => {
    const r = tryFill(acct(1e6), {symbol: '600519', side: 'buy', shares: 100}, ctx);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('涨停');
  });
  it('创业板20%：同价可买', () => {
    const r = tryFill(acct(1e6), {symbol: '300750', side: 'buy', shares: 100}, ctx);
    expect(r.ok).toBe(true);
  });
  it('非整手拒单', () => {
    const r = tryFill(acct(1e6), {symbol: '600519', side: 'buy', shares: 50}, {...ctx, close: 10.5});
    expect(r.ok).toBe(false);
  });
  it('资金不足拒单（含佣金）', () => {
    const r = tryFill(acct(1000), {symbol: '600519', side: 'buy', shares: 100}, {...ctx, close: 10.5});
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('资金不足');
  });
  it('买入成功：扣款=金额+佣金，持仓新增', () => {
    const r = tryFill(acct(1e6), {symbol: '600519', side: 'buy', shares: 100, note: '便宜'}, {...ctx, close: 10.5});
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.cash).toBe(1e6 - 1050 - 5);
      expect(r.positions).toEqual([{symbol: '600519', shares: 100, cost_price: 10.5, buy_date: '2020-03-13'}]);
      expect(r.trade).toMatchObject({side: 'buy', price: 10.5, shares: 100, fee: 5, tax: 0, note: '便宜'});
    }
  });
});

describe('tryFill 卖出', () => {
  const pos = [{symbol: '600519', shares: 200, cost_price: 10, buy_date: '2020-03-12'}];
  it('T+1：买入当日不可卖', () => {
    const r = tryFill(acct(0, [{...pos[0], buy_date: '2020-03-13'}]),
      {symbol: '600519', side: 'sell', shares: 100},
      {date: '2020-03-13', close: 10.5, prevClose: 10});
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('T+1');
  });
  it('跌停拒卖', () => {
    const r = tryFill(acct(0, pos), {symbol: '600519', side: 'sell', shares: 100},
      {date: '2020-03-13', close: 9, prevClose: 10});
    expect(r.ok).toBe(false);
  });
  it('持仓不足拒卖', () => {
    const r = tryFill(acct(0, pos), {symbol: '600519', side: 'sell', shares: 300},
      {date: '2020-03-13', close: 10.5, prevClose: 10});
    expect(r.ok).toBe(false);
  });
  it('卖出成功：回款=金额-佣金-印花税(2020年千1)', () => {
    const r = tryFill(acct(0, pos), {symbol: '600519', side: 'sell', shares: 100},
      {date: '2020-03-13', close: 10.5, prevClose: 10});
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.cash).toBe(1050 - 5 - 1.05);
      expect(r.positions).toEqual([{symbol: '600519', shares: 100, cost_price: 10, buy_date: '2020-03-12'}]);
      expect(r.trade.tax).toBe(1.05);
    }
  });
  it('清仓后持仓移除', () => {
    const r = tryFill(acct(0, pos), {symbol: '600519', side: 'sell', shares: 200},
      {date: '2020-03-13', close: 10.5, prevClose: 10});
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.positions).toEqual([]);
  });
});
```

- [ ] **Step 4: 跑测试确认 FAIL**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
npx vitest run src/pages/replay/engine/__tests__/fill.test.ts
```

Expected: FAIL（`../fill` 不存在）。

- [ ] **Step 5: 实现 fill.ts**

`frontend/apps/web/src/pages/replay/engine/fill.ts`：

```ts
import type {AccountState, OrderReq, Position, Trade} from '../types';

export interface FillCtx {
  date: string;
  close: number;
  prevClose: number;
  name?: string; // 用于识别 ST
}

export type FillResult =
  | {ok: true; cash: number; positions: Position[]; trade: Trade}
  | {ok: false; error: string};

export function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

/** 涨跌停幅度：ST 5% / 创业·科创 20% / 北交 30% / 主板 10%。 */
export function priceLimitRatio(symbol: string, name?: string): number {
  if (name && name.toUpperCase().includes('ST')) return 0.05;
  const code = symbol.replace(/^[a-z]{2}/i, ''); // 剥离 sh/sz/bj 前缀
  if (/^(300|301|688|689)/.test(code)) return 0.2;
  if (/^(8|4|92)/.test(code)) return 0.3;
  return 0.1;
}

export function limitPrices(prevClose: number, ratio: number): {up: number; down: number} {
  return {up: round2(prevClose * (1 + ratio)), down: round2(prevClose * (1 - ratio))};
}

export function commission(amount: number): number {
  return Math.max(5, round2(amount * 0.00025));
}

/** 印花税（仅卖出）：2023-08-28 起 0.05%，此前 0.1%。 */
export function stampTax(amount: number, date: string): number {
  const rate = date >= '2023-08-28' ? 0.0005 : 0.001;
  return round2(amount * rate);
}

export function tryFill(acct: AccountState, req: OrderReq, ctx: FillCtx): FillResult {
  const {date, close, prevClose} = ctx;
  if (!Number.isInteger(req.shares) || req.shares <= 0) {
    return {ok: false, error: '股数须为正整数'};
  }
  // 买入须 100 整数倍；卖出允许零股（实盘口径，Task 6 实测修正）
  const {up, down} = limitPrices(prevClose, priceLimitRatio(req.symbol, ctx.name));
  const amount = round2(close * req.shares);

  if (req.side === 'buy') {
    if (req.shares % 100 !== 0) return {ok: false, error: '买入须为100的整数倍'};
    if (close >= up) return {ok: false, error: '涨停，无法买入'};
    const fee = commission(amount);
    const cost = round2(amount + fee);
    if (cost > acct.cash) return {ok: false, error: '资金不足'};
    const positions = [...acct.positions];
    const i = positions.findIndex((p) => p.symbol === req.symbol);
    if (i >= 0) {
      const p = positions[i];
      const shares = p.shares + req.shares;
      // 加仓：成本加权；buy_date 保留首次（T+1 口径宽松，文档记录）
      const cost_price = round2((p.cost_price * p.shares + close * req.shares) / shares);
      positions[i] = {...p, shares, cost_price};
    } else {
      positions.push({symbol: req.symbol, shares: req.shares, cost_price: close, buy_date: date});
    }
    return {
      ok: true,
      cash: round2(acct.cash - cost),
      positions,
      trade: {trade_date: date, symbol: req.symbol, side: 'buy', price: close, shares: req.shares, fee, tax: 0, note: req.note ?? null},
    };
  }

  // sell
  if (close <= down) return {ok: false, error: '跌停，无法卖出'};
  const i = acct.positions.findIndex((p) => p.symbol === req.symbol);
  if (i < 0) return {ok: false, error: '无持仓'};
  const p = acct.positions[i];
  if (p.shares < req.shares) return {ok: false, error: '持仓不足'};
  if (p.buy_date >= date) return {ok: false, error: 'T+1：今日买入明日才可卖出'};
  const fee = commission(amount);
  const tax = stampTax(amount, date);
  const positions = [...acct.positions];
  if (p.shares === req.shares) positions.splice(i, 1);
  else positions[i] = {...p, shares: p.shares - req.shares};
  return {
    ok: true,
    cash: round2(acct.cash + amount - fee - tax),
    positions,
    trade: {trade_date: date, symbol: req.symbol, side: 'sell', price: close, shares: req.shares, fee, tax, note: req.note ?? null},
  };
}
```

- [ ] **Step 6: 跑测试确认 PASS**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
npx vitest run src/pages/replay
```

Expected: 全部 PASS。

- [ ] **Step 7: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/package.json frontend/apps/web/vitest.config.ts \
        frontend/apps/web/src/pages/replay/types.ts \
        frontend/apps/web/src/pages/replay/engine/fill.ts \
        frontend/apps/web/src/pages/replay/engine/__tests__/fill.test.ts \
        frontend/pnpm-lock.yaml frontend/rush.json 2>/dev/null || true
git add -A frontend/apps/web frontend/pnpm-lock.yaml
git commit -m "feat(replay): 前端vitest基建+成交引擎——涨跌停分档/T+1/整手/佣金印花税换挡"
```

---

### Task 6: 前端 — 指标 indicators.ts + 净值 nav.ts

**Files:**
- Create: `frontend/apps/web/src/pages/replay/engine/indicators.ts`
- Create: `frontend/apps/web/src/pages/replay/engine/nav.ts`
- Test: `frontend/apps/web/src/pages/replay/engine/__tests__/indicators.test.ts`、`.../__tests__/nav.test.ts`

**Interfaces:**
- Consumes: `src/pages/Board/indicators.ts` 的 `ema/macd/rsiWilder`（已存在，与后端对齐；类型 `Series = (number|null)[]`、`MacdResult{dif,dea,hist}`）。
- Produces:
  - `sma(values: number[], n: number): (number|null)[]`
  - `kdj(bars: {high,low,close}[], n=9): {k,d,j: number|null}[]`（K/D 初值 50，1/3-2/3 平滑）
  - re-export：`ema, macd, rsiWilder`
  - `computeNav(cash, positions, closeOf: (symbol) => number|null): number`
  - `maxDrawdown(nav: NavPoint[]): number`（0~1 正数）
  - `annualizedReturn(initial, final, tradeDays): number`
  - `roundTrips(trades: Trade[]): {symbol, pnl}[]`（FIFO 配对，卖出盈亏含费用）
  - `winRate(trades): number|null`

- [ ] **Step 1: 写失败测试**

`indicators.test.ts`：

```ts
import {describe, expect, it} from 'vitest';
import {kdj, macd, rsiWilder, sma} from '../indicators';

describe('sma', () => {
  it('手算小序列', () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });
  it('n=1 原样返回', () => {
    expect(sma([7, 8], 1)).toEqual([7, 8]);
  });
});

describe('kdj', () => {
  const bars = Array.from({length: 12}, (_, i) => ({
    high: 10 + i, low: 8 + i, close: 9 + i,
  }));
  it('前 n-1 个为 null，之后有值且 K/D 在 0~100', () => {
    const out = kdj(bars, 9);
    expect(out).toHaveLength(12);
    expect(out[7].k).toBeNull();
    expect(out[8].k).not.toBeNull();
    for (const p of out.slice(8)) {
      expect(p.k!).toBeGreaterThanOrEqual(0);
      expect(p.k!).toBeLessThanOrEqual(100);
      expect(p.d!).toBeGreaterThanOrEqual(0);
      expect(p.d!).toBeLessThanOrEqual(100);
      expect(p.j!).toBeCloseTo(3 * p.k! - 2 * p.d!, 6);
    }
  });
  it('单边上涨 RSV=100 → K 单调上升', () => {
    const out = kdj(bars, 9).slice(8);
    for (let i = 1; i < out.length; i++) {
      expect(out[i].k!).toBeGreaterThanOrEqual(out[i - 1].k!);
    }
  });
});

describe('复用 Board 指标', () => {
  it('macd 输出等长且 hist=dif-dea', () => {
    const closes = Array.from({length: 40}, (_, i) => 10 + Math.sin(i / 3));
    const {dif, dea, hist} = macd(closes, 12, 26, 9);
    expect(dif).toHaveLength(40);
    const i = 39;
    if (dif[i] != null && dea[i] != null) {
      expect(hist[i]!).toBeCloseTo(dif[i]! - dea[i]!, 6);
    }
  });
  it('rsiWilder 值域 0~100', () => {
    const closes = Array.from({length: 30}, (_, i) => 10 + i * 0.1);
    const r = rsiWilder(closes, 14);
    const last = r[r.length - 1];
    expect(last).not.toBeNull();
    expect(last!).toBeGreaterThan(50); // 单边上涨
    expect(last!).toBeLessThanOrEqual(100);
  });
});
```

`nav.test.ts`：

```ts
import {describe, expect, it} from 'vitest';
import {annualizedReturn, computeNav, maxDrawdown, roundTrips, winRate} from '../nav';
import {tryFill} from '../fill';
import type {AccountState, Trade} from '../../types';

describe('computeNav', () => {
  it('现金+持仓市值；无行情的标的按 0 跳过', () => {
    const v = computeNav(1000, [
      {symbol: '600519', shares: 100, cost_price: 10, buy_date: '2020-01-01'},
      {symbol: '000001', shares: 100, cost_price: 5, buy_date: '2020-01-01'},
    ], (s) => (s === '600519' ? 20 : null));
    expect(v).toBe(3000);
  });
});

describe('maxDrawdown', () => {
  it('120→90 回撤 25%', () => {
    const nav = [100, 120, 90, 130].map((v, i) => ({date: `2020-01-0${i + 1}`, value: v}));
    expect(maxDrawdown(nav)).toBeCloseTo(0.25, 6);
  });
  it('单调不降为 0', () => {
    expect(maxDrawdown([{date: 'a', value: 1}, {date: 'b', value: 2}])).toBe(0);
  });
});

describe('annualizedReturn', () => {
  it('252 天翻倍 → +100%', () => {
    expect(annualizedReturn(100, 200, 252)).toBeCloseTo(1, 6);
  });
  it('非法输入为 0', () => {
    expect(annualizedReturn(0, 200, 252)).toBe(0);
    expect(annualizedReturn(100, 200, 0)).toBe(0);
  });
});

describe('roundTrips/winRate（用 tryFill 造真实成交）', () => {
  const mk = () => {
    let acct: AccountState = {cash: 1e6, positions: []};
    const trades: Trade[] = [];
    const fill = (side: 'buy' | 'sell', price: number, shares: number, date: string, prev: number) => {
      const r = tryFill(acct, {symbol: '600519', side, shares}, {date, close: price, prevClose: prev});
      if (!r.ok) throw new Error(r.error);
      acct = {cash: r.cash, positions: r.positions};
      trades.push(r.trade);
    };
    fill('buy', 10, 100, '2020-01-02', 9.9);
    fill('buy', 20, 100, '2020-01-03', 19.9);
    fill('sell', 25, 150, '2020-01-06', 24.9); // FIFO 吃掉 100@10 + 50@20
    return trades;
  };
  it('FIFO 配对一笔盈利 round-trip', () => {
    const trips = roundTrips(mk());
    expect(trips).toHaveLength(1);
    // proceeds=3750-5-3.75=3741.25；cost=1005+0.5*2005=2007.5
    expect(trips[0].pnl).toBeCloseTo(3741.25 - 2007.5, 2);
    expect(winRate(mk())).toBe(1);
  });
  it('无卖出 → winRate 为 null', () => {
    expect(winRate([])).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认 FAIL**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
npx vitest run src/pages/replay/engine/__tests__/
```

Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 indicators.ts**

`frontend/apps/web/src/pages/replay/engine/indicators.ts`：

```ts
/** 时光机指标：sma/kdj 本地实现；ema/macd/rsiWilder 复用 Board
 *  （与后端 strategy/indicators.py 逐条对齐的那套）。 */

export function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= n) sum -= values[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

export interface KdjPoint {
  k: number | null;
  d: number | null;
  j: number | null;
}

/** KDJ（9,3,3）：K/D 初值 50，K = 2/3·K' + 1/3·RSV。 */
export function kdj(
  bars: {high: number; low: number; close: number}[],
  n = 9,
): KdjPoint[] {
  const out: KdjPoint[] = [];
  let prevK = 50;
  let prevD = 50;
  for (let i = 0; i < bars.length; i++) {
    if (i < n - 1) {
      out.push({k: null, d: null, j: null});
      continue;
    }
    let hh = -Infinity;
    let ll = Infinity;
    for (let m = i - n + 1; m <= i; m++) {
      hh = Math.max(hh, bars[m].high);
      ll = Math.min(ll, bars[m].low);
    }
    const rsv = hh === ll ? 50 : ((bars[i].close - ll) / (hh - ll)) * 100;
    const k = (2 / 3) * prevK + (1 / 3) * rsv;
    const d = (2 / 3) * prevD + (1 / 3) * k;
    out.push({k, d, j: 3 * k - 2 * d});
    prevK = k;
    prevD = d;
  }
  return out;
}

export {ema, macd, rsiWilder} from '../../Board/indicators';
export type {MacdResult, Series} from '../../Board/indicators';
```

> 若 `../../Board/indicators` 没有导出 `MacdResult`/`Series` 类型，删掉最后一行 type re-export，仅保留值导出。

- [ ] **Step 4: 实现 nav.ts**

`frontend/apps/web/src/pages/replay/engine/nav.ts`：

```ts
import type {NavPoint, Position, Trade} from '../types';

const round2 = (v: number) => Math.round(v * 100) / 100;

/** 净值 = 现金 + Σ(持仓股数 × 最近已知收盘价)；无行情的标的跳过。 */
export function computeNav(
  cash: number,
  positions: Position[],
  closeOf: (symbol: string) => number | null,
): number {
  let v = cash;
  for (const p of positions) {
    const c = closeOf(p.symbol);
    if (c != null) v += c * p.shares;
  }
  return round2(v);
}

/** 最大回撤（0~1 正数）。 */
export function maxDrawdown(nav: NavPoint[]): number {
  let peak = -Infinity;
  let mdd = 0;
  for (const p of nav) {
    peak = Math.max(peak, p.value);
    if (peak > 0) mdd = Math.max(mdd, (peak - p.value) / peak);
  }
  return mdd;
}

/** 年化（按 252 个交易日）。 */
export function annualizedReturn(
  initial: number,
  final: number,
  tradeDays: number,
): number {
  if (initial <= 0 || tradeDays <= 0) return 0;
  return Math.pow(final / initial, 252 / tradeDays) - 1;
}

export interface RoundTrip {
  symbol: string;
  pnl: number;
}

/** FIFO 配对：卖出按先进先出结转买入成本（含佣金），得每次平仓盈亏。 */
export function roundTrips(trades: Trade[]): RoundTrip[] {
  const lots = new Map<string, {shares: number; cost: number}[]>();
  const trips: RoundTrip[] = [];
  for (const t of trades) {
    const q = lots.get(t.symbol) ?? [];
    if (t.side === 'buy') {
      q.push({shares: t.shares, cost: t.price * t.shares + t.fee});
    } else {
      let remain = t.shares;
      let costOut = 0;
      while (remain > 0 && q.length > 0) {
        const lot = q[0];
        const take = Math.min(remain, lot.shares);
        const ratio = take / lot.shares;
        costOut += lot.cost * ratio;
        lot.shares -= take;
        lot.cost *= 1 - ratio;
        if (lot.shares <= 0) q.shift();
        remain -= take;
      }
      const proceeds = t.price * t.shares - t.fee - t.tax;
      trips.push({symbol: t.symbol, pnl: round2(proceeds - costOut)});
    }
    lots.set(t.symbol, q);
  }
  return trips;
}

/** 胜率 = 盈利平仓次数 / 总平仓次数；无平仓返回 null。 */
export function winRate(trades: Trade[]): number | null {
  const trips = roundTrips(trades);
  if (trips.length === 0) return null;
  return trips.filter((t) => t.pnl > 0).length / trips.length;
}
```

- [ ] **Step 5: 跑测试确认 PASS**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
npx vitest run src/pages/replay/engine/__tests__/
```

Expected: 全部 PASS（若 Board/indicators 的 macd 参数签名与 `(values, fast, slow, signal)` 不符，以真实签名为准调整测试与调用）。

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/replay/engine/
git commit -m "feat(replay): 指标(sma/kdj+复用Board三件套)与净值引擎(回撤/年化/FIFO胜率)"
```

---

### Task 7: 前端 — API 模块 + zustand 旅程状态机

**Files:**
- Create: `frontend/apps/web/src/pages/replay/api.ts`
- Create: `frontend/apps/web/src/pages/replay/store.ts`
- Test: `frontend/apps/web/src/pages/replay/__tests__/store.test.ts`

**Interfaces:**
- Consumes: `types.ts`（Task 5）、`tryFill`/`computeNav`（Task 5/6）、`getApiBase()`（`src/lib/api.ts`）。
- Produces（Task 8-12 的 UI 全部依赖）：
  - `useReplayStore`（zustand），字段：`session, phase('sailing'|'review'), dates, cursor, pool, names, barsBySymbol, benchmarkBars, cash, positions, trades, nav, selectedSymbol, playing, speed, error, advancing`
  - actions：`openSession(id), closeSession(), addSymbol(symbol, name?), selectSymbol(s), advance(), stepBack(), play(), pause(), setSpeed(s), placeOrder(side, shares, note?), reveal(), saveNow()`
  - 选择器 helper：`viewDate(s)` = `s.dates[s.cursor]`，`lastClose(s, symbol)`、`visibleBars(s, symbol)`（截到视角日）
  - api 函数：`listSessions/createSession/getSession/saveState/revealSession/deleteSession/addTrade/listTrades/fetchKline/fetchAdvance/fetchValuation/fetchBoard/runScreener/searchSymbols/listWatchGroups/listWatchItems`

**关键语义（实现与测试都以此为准）：**
- `dates` = 已走过的交易日（升序）；`cursor` 是视角位置。`cursor < dates.length-1` = 回看态，禁止交易。
- `advance()`：回看态 → `cursor+1`（不发请求）；最新态 → `fetchAdvance(session_id, days)`，把新 dates/bars 追加进缓存、`cursor+1`、用各标的最新已知 close 追加一个 `nav` 点、触发防抖存档。返回 dates 为空 → 暂停播放并提示已到终点。
- `placeOrder`：取当前视角标的在 `dates[cursor]` 的 bar（无 bar → "停牌"拒单）与前一 bar（prevClose），调 `tryFill`；成功 → 更新 cash/positions/trades → `addTrade` 落库 → 防抖存档。
- 存档内容：`{current_date: dates.at(-1), cash, state: {pool, positions, nav}}`（存的是最新态，不是回看视角）。

- [ ] **Step 1: 写 api.ts**

`frontend/apps/web/src/pages/replay/api.ts`：

```ts
import {getApiBase} from '../../lib/api';
import type {
  AdvanceResp, ApiResp, BoardRow, ReplayBar, SessionFull,
  SessionMeta, Trade, ValuationInfo,
} from './types';

const API = getApiBase();

const jget = <T>(u: string): Promise<ApiResp<T>> =>
  fetch(u).then((r) => r.json());
const jpost = <T>(u: string, b?: unknown): Promise<ApiResp<T>> =>
  fetch(u, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(b ?? {}),
  }).then((r) => r.json());
const jput = <T>(u: string, b: unknown): Promise<ApiResp<T>> =>
  fetch(u, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(b),
  }).then((r) => r.json());
const jdel = <T>(u: string): Promise<ApiResp<T>> =>
  fetch(u, {method: 'DELETE'}).then((r) => r.json());

// ── 会话 ──
export const listSessions = () => jget<SessionMeta[]>(`${API}/replay/sessions`);
export const createSession = (body: {
  name: string; start_date: string; initial_capital: number; end_date?: string;
}) => jpost<SessionFull>(`${API}/replay/sessions`, body);
export const getSession = (id: number) =>
  jget<SessionFull>(`${API}/replay/sessions/${id}`);
export const saveState = (id: number, body: {
  current_date: string; cash: number; state: SessionFull['state'];
}) => jput<{id: number}>(`${API}/replay/sessions/${id}/state`, body);
export const revealSession = (id: number) =>
  jpost<{id: number; status: string}>(`${API}/replay/sessions/${id}/reveal`);
export const deleteSession = (id: number) =>
  jdel<{id: number}>(`${API}/replay/sessions/${id}`);

// ── 成交 ──
export const addTrade = (id: number, t: Trade) =>
  jpost<Trade>(`${API}/replay/sessions/${id}/trades`, t);
export const listTrades = (id: number) =>
  jget<Trade[]>(`${API}/replay/sessions/${id}/trades`);

// ── 行情切片 ──
export const fetchKline = (symbol: string, asof: string, limit = 3000) =>
  jget<{symbol: string; bars: ReplayBar[]}>(
    `${API}/replay/kline/${symbol}?asof=${asof}&limit=${limit}`);
export const fetchAdvance = (sessionId: number, days: number) =>
  jget<AdvanceResp>(`${API}/replay/advance?session_id=${sessionId}&days=${days}`);
export const fetchValuation = (symbol: string, asof: string) =>
  jget<ValuationInfo>(`${API}/replay/valuation/${symbol}?asof=${asof}`);
export const fetchBoard = (asof: string, type: 'gainers' | 'amount') =>
  jget<BoardRow[]>(`${API}/replay/board?asof=${asof}&type=${type}`);

// ── 选股复用（现有端点，as_of 即旅程当前日） ──
export const runScreener = (mode: string, topN: number, asOf: string) =>
  jpost<{ranked_list: Record<string, unknown>[]}>(
    `${API}/screener/screen`, {mode, top_n: topN, as_of: asOf});
export const searchSymbols = (q: string) =>
  jget<{symbol: string; name: string; market: string}[]>(
    `${API}/market/search?q=${encodeURIComponent(q)}&market=A`);
export const listWatchGroups = () =>
  jget<{id: number; name: string}[]>(`${API}/watchlist/groups`);
export const listWatchItems = (gid: number) =>
  jget<{id: number; symbol: string; note?: string}[]>(
    `${API}/watchlist/groups/${gid}/items`);
```

- [ ] **Step 2: 写失败测试**

`frontend/apps/web/src/pages/replay/__tests__/store.test.ts`：

```ts
import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.mock('../api', () => ({
  getSession: vi.fn(),
  fetchKline: vi.fn(),
  fetchAdvance: vi.fn(),
  addTrade: vi.fn().mockResolvedValue({code: 0, data: {}}),
  saveState: vi.fn().mockResolvedValue({code: 0, data: {}}),
  listTrades: vi.fn().mockResolvedValue({code: 0, data: []}),
  revealSession: vi.fn().mockResolvedValue({code: 0, data: {status: 'revealed'}}),
}));

import * as api from '../api';
import {useReplayStore} from '../store';

const bar = (d: string, close: number) => ({
  trade_date: d, open: close, close, high: close, low: close, volume: 1, amount: 1,
});

const seedSession = {
  id: 7, name: 'T', status: 'active' as const,
  start_date: '2020-03-13', current_date: '2020-03-13',
  end_date: null, initial_capital: 1e6, cash: 1e6,
  benchmark_symbol: 'sh000300',
  state: {pool: [], positions: [], nav: []},
};

beforeEach(() => {
  vi.clearAllMocks();
  useReplayStore.getState().closeSession();
  vi.mocked(api.getSession).mockResolvedValue({code: 0, msg: 'ok', data: seedSession});
  vi.mocked(api.fetchKline).mockImplementation(async (symbol: string) => ({
    code: 0, msg: 'ok',
    data: {symbol, bars: symbol === 'sh000300'
      ? [bar('2020-03-13', 4000)]
      : [bar('2020-03-13', 10)]},
  }));
});

describe('openSession/advance', () => {
  it('开仓恢复：dates 从基准日历重建，视角在最新日', async () => {
    await useReplayStore.getState().openSession(7);
    const s = useReplayStore.getState();
    expect(s.session?.id).toBe(7);
    expect(s.dates).toEqual(['2020-03-13']);
    expect(s.cursor).toBe(0);
    expect(s.cash).toBe(1e6);
  });

  it('advance 追加新日 bar 与净值点；走到数据尽头自动停', async () => {
    vi.mocked(api.fetchAdvance)
      .mockResolvedValueOnce({code: 0, msg: 'ok', data: {
        dates: ['2020-03-16'],
        bars: {'600519': [bar('2020-03-16', 10.4)]},
        benchmark: [bar('2020-03-16', 4050)],
      }})
      .mockResolvedValueOnce({code: 0, msg: 'ok',
        data: {dates: [], bars: {}, benchmark: []}});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519', '贵州茅台');
    await useReplayStore.getState().advance();
    let s = useReplayStore.getState();
    expect(s.dates).toEqual(['2020-03-13', '2020-03-16']);
    expect(s.barsBySymbol['600519'].map((b) => b.trade_date))
      .toEqual(['2020-03-13', '2020-03-16']);
    expect(s.nav[s.nav.length - 1].date).toBe('2020-03-16');
    await useReplayStore.getState().advance();
    s = useReplayStore.getState();
    expect(s.dates).toHaveLength(2); // 不再前进
    expect(s.error).toContain('终点');
  });

  it('回看态 advance 只移动视角不发请求，且禁止交易', async () => {
    vi.mocked(api.fetchAdvance).mockResolvedValue({code: 0, msg: 'ok', data: {
      dates: ['2020-03-16'], bars: {'600519': [bar('2020-03-16', 10.4)]},
      benchmark: [bar('2020-03-16', 4050)],
    }});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519');
    await useReplayStore.getState().advance();
    useReplayStore.getState().stepBack();
    expect(useReplayStore.getState().cursor).toBe(0);
    vi.mocked(api.fetchAdvance).mockClear();
    await useReplayStore.getState().advance(); // 回看→前进，不发请求
    expect(api.fetchAdvance).not.toHaveBeenCalled();
    expect(useReplayStore.getState().cursor).toBe(1);
  });
});

describe('placeOrder', () => {
  it('收盘价成交：扣款、持仓、成交落库、自动存档', async () => {
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519', '贵州茅台');
    useReplayStore.getState().selectSymbol('600519');
    const ok = await useReplayStore.getState().placeOrder('buy', 100, '便宜');
    expect(ok).toBe(true);
    const s = useReplayStore.getState();
    expect(s.cash).toBe(1e6 - 1000 - 5);
    expect(s.positions[0]).toMatchObject({symbol: '600519', shares: 100});
    expect(api.addTrade).toHaveBeenCalledWith(7,
      expect.objectContaining({side: 'buy', price: 10, shares: 100}));
    expect(api.saveState).toHaveBeenCalled();
  });

  it('涨停拒买且不落库', async () => {
    vi.mocked(api.fetchKline).mockImplementation(async (symbol: string) => ({
      code: 0, msg: 'ok',
      data: {symbol, bars: symbol === 'sh000300'
        ? [bar('2020-03-13', 4000)]
        : [bar('2020-03-12', 10), bar('2020-03-13', 11)]},
    }));
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519', '贵州茅台');
    useReplayStore.getState().selectSymbol('600519');
    const ok = await useReplayStore.getState().placeOrder('buy', 100);
    expect(ok).toBe(false);
    expect(useReplayStore.getState().error).toContain('涨停');
    expect(api.addTrade).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: 跑测试确认 FAIL**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
npx vitest run src/pages/replay/__tests__/store.test.ts
```

Expected: FAIL（`../store` 不存在）。

- [ ] **Step 4: 实现 store.ts**

`frontend/apps/web/src/pages/replay/store.ts`：

```ts
import {create} from 'zustand';
import * as api from './api';
import {tryFill} from './engine/fill';
import {computeNav} from './engine/nav';
import type {
  NavPoint, Position, ReplayBar, SessionMeta, Trade,
} from './types';

export type Phase = 'sailing' | 'review';
export type Speed = 1 | 2 | 4;

interface ReplayStore {
  session: SessionMeta | null;
  phase: Phase;
  dates: string[]; // 已走过的交易日（升序）
  cursor: number; // 视角位置；cursor < dates.length-1 为回看态
  pool: string[];
  names: Record<string, string>;
  barsBySymbol: Record<string, ReplayBar[]>; // ≤ 最新走过日期
  benchmarkBars: ReplayBar[];
  cash: number;
  positions: Position[];
  trades: Trade[];
  nav: NavPoint[];
  selectedSymbol: string | null;
  playing: boolean;
  speed: Speed;
  error: string | null;
  advancing: boolean;

  openSession: (id: number) => Promise<void>;
  closeSession: () => void;
  addSymbol: (symbol: string, name?: string) => Promise<void>;
  selectSymbol: (symbol: string) => void;
  advance: () => Promise<void>;
  stepBack: () => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: Speed) => void;
  placeOrder: (side: 'buy' | 'sell', shares: number, note?: string) => Promise<boolean>;
  reveal: () => Promise<void>;
  saveNow: () => Promise<void>;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

export const useReplayStore = create<ReplayStore>()((set, get) => {
  const scheduleSave = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => void get().saveNow(), 800);
  };

  const lastClose = (symbol: string): number | null => {
    const bars = get().barsBySymbol[symbol];
    return bars && bars.length ? bars[bars.length - 1].close : null;
  };

  return {
    session: null,
    phase: 'sailing',
    dates: [],
    cursor: 0,
    pool: [],
    names: {},
    barsBySymbol: {},
    benchmarkBars: [],
    cash: 0,
    positions: [],
    trades: [],
    nav: [],
    selectedSymbol: null,
    playing: false,
    speed: 1,
    error: null,
    advancing: false,

    openSession: async (id) => {
      const sj = await api.getSession(id);
      if (sj.code !== 0) {
        set({error: sj.msg || '会话加载失败'});
        return;
      }
      const sess = sj.data;
      // 交易日历从基准 K 线重建（start → current）
      const cal = await api.fetchKline(sess.benchmark_symbol, sess.current_date);
      const calBars = cal.code === 0 ? cal.data.bars : [];
      const dates = calBars
        .map((b) => b.trade_date)
        .filter((d) => d >= sess.start_date && d <= sess.current_date);
      const barsBySymbol: Record<string, ReplayBar[]> = {};
      for (const sym of sess.state.pool) {
        const kj = await api.fetchKline(sym, sess.current_date);
        if (kj.code === 0) barsBySymbol[sym] = kj.data.bars;
      }
      const tj = await api.listTrades(id);
      set({
        session: sess,
        phase: sess.status === 'revealed' ? 'review' : 'sailing',
        dates,
        cursor: Math.max(0, dates.length - 1),
        pool: sess.state.pool,
        barsBySymbol,
        benchmarkBars: calBars,
        cash: sess.cash,
        positions: sess.state.positions,
        trades: tj.code === 0 ? tj.data : [],
        nav: sess.state.nav,
        selectedSymbol: sess.state.pool[0] ?? null,
        error: null,
      });
      if (sess.status === 'revealed') await get().reveal();
    },

    closeSession: () => {
      if (saveTimer) clearTimeout(saveTimer);
      set({
        session: null, phase: 'sailing', dates: [], cursor: 0,
        pool: [], names: {}, barsBySymbol: {}, benchmarkBars: [],
        cash: 0, positions: [], trades: [], nav: [],
        selectedSymbol: null, playing: false, error: null,
        advancing: false,
      });
    },

    addSymbol: async (symbol, name) => {
      const s = get();
      if (s.pool.includes(symbol)) {
        set({selectedSymbol: symbol});
        return;
      }
      const asof = s.dates[s.dates.length - 1];
      const kj = await api.fetchKline(symbol, asof);
      if (kj.code !== 0 || kj.data.bars.length === 0) {
        set({error: kj.msg || `${symbol} 在 ${asof} 之前无行情数据`});
        return;
      }
      set((st) => ({
        pool: [...st.pool, symbol],
        names: name ? {...st.names, [symbol]: name} : st.names,
        barsBySymbol: {...st.barsBySymbol, [symbol]: kj.data.bars},
        selectedSymbol: symbol,
        error: null,
      }));
      scheduleSave();
    },

    selectSymbol: (symbol) => set({selectedSymbol: symbol}),

    advance: async () => {
      const s = get();
      if (!s.session || s.advancing || s.phase !== 'sailing') return;
      if (s.cursor < s.dates.length - 1) {
        set({cursor: s.cursor + 1}); // 回看态：只移动视角
        return;
      }
      set({advancing: true});
      try {
        const r = await api.fetchAdvance(s.session.id, 1);
        if (r.code !== 0) {
          set({error: r.msg || '推进失败', playing: false});
          return;
        }
        if (r.data.dates.length === 0) {
          set({playing: false, error: '已到数据终点，可揭晓复盘'});
          return;
        }
        const st = get();
        const barsBySymbol = {...st.barsBySymbol};
        for (const [sym, bars] of Object.entries(r.data.bars)) {
          barsBySymbol[sym] = [...(barsBySymbol[sym] ?? []), ...bars];
        }
        const date = r.data.dates[r.data.dates.length - 1];
        const closeOf = (sym: string) => {
          const bars = barsBySymbol[sym];
          return bars && bars.length ? bars[bars.length - 1].close : null;
        };
        const nav = [
          ...st.nav,
          {date, value: computeNav(st.cash, st.positions, closeOf)},
        ];
        set({
          dates: [...st.dates, ...r.data.dates],
          cursor: st.cursor + r.data.dates.length,
          barsBySymbol,
          benchmarkBars: [...st.benchmarkBars, ...r.data.benchmark],
          nav,
          error: null,
        });
        scheduleSave();
      } finally {
        set({advancing: false});
      }
    },

    stepBack: () => {
      const s = get();
      if (s.cursor > 0) set({cursor: s.cursor - 1, playing: false});
    },

    play: () => set({playing: true}),
    pause: () => set({playing: false}),
    setSpeed: (speed) => set({speed}),

    placeOrder: async (side, shares, note) => {
      const s = get();
      const symbol = s.selectedSymbol;
      if (!s.session || !symbol) return false;
      const date = s.dates[s.cursor];
      if (s.cursor < s.dates.length - 1) {
        set({error: '回看状态不能交易'});
        return false;
      }
      const bars = s.barsBySymbol[symbol] ?? [];
      const i = bars.findIndex((b) => b.trade_date === date);
      if (i < 0) {
        set({error: '当日停牌，无法成交'});
        return false;
      }
      const prevClose = i > 0 ? bars[i - 1].close : bars[i].open;
      const r = tryFill(
        {cash: s.cash, positions: s.positions},
        {symbol, side, shares, note},
        {date, close: bars[i].close, prevClose, name: s.names[symbol]},
      );
      if (!r.ok) {
        set({error: r.error});
        return false;
      }
      set({cash: r.cash, positions: r.positions,
           trades: [...s.trades, r.trade], error: null});
      await api.addTrade(s.session.id, r.trade);
      await get().saveNow(); // 成交即存档（不走防抖，防崩丢单）
      return true;
    },

    reveal: async () => {
      const s = get();
      if (!s.session) return;
      if (s.session.status !== 'revealed') {
        const r = await api.revealSession(s.session.id);
        if (r.code !== 0) {
          set({error: r.msg || '揭晓失败'});
          return;
        }
      }
      // 揭晓：拉全量 K 线（到 end_date 或今天）
      const st = get();
      const asof = st.session!.end_date ??
        new Date().toISOString().slice(0, 10);
      const barsBySymbol: Record<string, ReplayBar[]> = {};
      for (const sym of st.pool) {
        const kj = await api.fetchKline(sym, asof);
        if (kj.code === 0) barsBySymbol[sym] = kj.data.bars;
      }
      const bj = await api.fetchKline(st.session!.benchmark_symbol, asof);
      set({
        phase: 'review',
        playing: false,
        session: {...st.session!, status: 'revealed'},
        barsBySymbol,
        benchmarkBars: bj.code === 0 ? bj.data.bars : st.benchmarkBars,
      });
    },

    saveNow: async () => {
      const s = get();
      if (!s.session || s.dates.length === 0) return;
      await api.saveState(s.session.id, {
        current_date: s.dates[s.dates.length - 1],
        cash: s.cash,
        state: {pool: s.pool, positions: s.positions, nav: s.nav},
      });
    },
  };
});

// ── 选择器 helper ──
export const viewDate = (s: ReplayStore): string | null =>
  s.dates[s.cursor] ?? null;

export const visibleBars = (s: ReplayStore, symbol: string): ReplayBar[] => {
  const vd = viewDate(s);
  if (!vd) return [];
  return (s.barsBySymbol[symbol] ?? []).filter((b) => b.trade_date <= vd);
};
```

- [ ] **Step 5: 跑测试确认 PASS**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
npx vitest run src/pages/replay/
```

Expected: 全部 PASS（含 engine 既有用例）。

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/replay/api.ts \
        frontend/apps/web/src/pages/replay/store.ts \
        frontend/apps/web/src/pages/replay/__tests__/store.test.ts
git commit -m "feat(replay): API模块+zustand旅程状态机——推进/回看/下单落库/防抖存档"
```

---

### Task 8: 前端 — ReplayKlineChart 受控 K 线组件

**Files:**
- Create: `frontend/apps/web/src/pages/replay/ReplayKlineChart.tsx`
- Test: 无单测（UI 组件，手动验收；依赖的 `sma` 已在 Task 6 测过）

**Interfaces:**
- Consumes: `ReplayBar`/`Trade`（types.ts）、`sma`（engine/indicators.ts）、chartTheme 常量（`src/lib/chartTheme.ts`）、`lightweight-charts@^5`。
- Produces: `<ReplayKlineChart bars trades? height? />`——bars 变化时：仅多 1 根走 `series.update` 增量，否则整包 `setData`；trades → B/S 箭头 marker；MA5/10/20/60 副线 + 成交量副图。Task 10/12 使用。

- [ ] **Step 1: 实现组件**

`frontend/apps/web/src/pages/replay/ReplayKlineChart.tsx`：

```tsx
import {useEffect, useRef} from 'react';
import {
  CandlestickSeries, HistogramSeries, LineSeries, createChart,
  createSeriesMarkers,
  type IChartApi, type ISeriesApi, type UTCTimestamp,
} from 'lightweight-charts';
import {
  chartBorder, chartTextSecondary, colorDown, colorUp,
} from '../../lib/chartTheme';
import {sma} from './engine/indicators';
import type {ReplayBar, Trade} from './types';

const toTime = (d: string): UTCTimestamp =>
  Math.floor(new Date(`${d}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;

const MA_COLORS = ['#f5c542', '#64d2ff', '#bf5af2', '#a1a1a6'];
const MA_NS = [5, 10, 20, 60];

export interface ReplayKlineChartProps {
  bars: ReplayBar[];
  trades?: Trade[]; // 复盘模式标注买卖点
  height?: number;
}

export const ReplayKlineChart: React.FC<ReplayKlineChartProps> = ({
  bars, trades = [], height = 420,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const maRefs = useRef<ISeriesApi<'Line'>[]>([]);
  const markersRef = useRef<{setMarkers: (m: unknown[]) => void} | null>(null);
  const lenRef = useRef(0);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height,
      layout: {
        background: {color: 'transparent'},
        textColor: chartTextSecondary,
      },
      grid: {
        vertLines: {color: chartBorder},
        horzLines: {color: chartBorder},
      },
      rightPriceScale: {borderColor: chartBorder},
      timeScale: {borderColor: chartBorder},
    });
    chartRef.current = chart;
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: colorUp, downColor: colorDown, borderVisible: false,
      wickUpColor: colorUp, wickDownColor: colorDown,
    });
    volRef.current = chart.addSeries(HistogramSeries, {
      priceFormat: {type: 'volume'}, priceScaleId: '',
    });
    chart.priceScale('').applyOptions({scaleMargins: {top: 0.8, bottom: 0}});
    maRefs.current = MA_COLORS.map((color) =>
      chart.addSeries(LineSeries, {
        color, lineWidth: 1, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false,
      }));
    markersRef.current = createSeriesMarkers(candleRef.current, []);
    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({width: ref.current.clientWidth});
    });
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volRef.current = null;
      maRefs.current = [];
      markersRef.current = null;
      lenRef.current = 0;
    };
  }, [height]);

  useEffect(() => {
    const candle = candleRef.current;
    if (!candle) return;
    const cd = bars.map((b) => ({
      time: toTime(b.trade_date),
      open: b.open, high: b.high, low: b.low, close: b.close,
    }));
    const vd = bars.map((b) => ({
      time: toTime(b.trade_date), value: b.volume,
      color: b.close >= b.open ? colorUp : colorDown,
    }));
    const closes = bars.map((b) => b.close);
    const mas = MA_NS.map((n) => sma(closes, n));
    if (bars.length === lenRef.current + 1 && lenRef.current > 0) {
      // 增量：推进一根
      const i = bars.length - 1;
      candle.update(cd[i]);
      volRef.current?.update(vd[i]);
      maRefs.current.forEach((s, k) => {
        const v = mas[k][i];
        if (v != null) s.update({time: cd[i].time, value: v});
      });
    } else {
      candle.setData(cd);
      volRef.current?.setData(vd);
      maRefs.current.forEach((s, k) => {
        s.setData(
          mas[k]
            .map((v, i) => (v == null ? null : {time: cd[i].time, value: v}))
            .filter((x): x is {time: UTCTimestamp; value: number} => x != null),
        );
      });
    }
    lenRef.current = bars.length;
  }, [bars]);

  useEffect(() => {
    markersRef.current?.setMarkers(
      trades.map((t) => ({
        time: toTime(t.trade_date),
        position: (t.side === 'buy' ? 'belowBar' : 'aboveBar') as const,
        color: t.side === 'buy' ? colorUp : colorDown,
        shape: (t.side === 'buy' ? 'arrowUp' : 'arrowDown') as const,
        text: t.side === 'buy' ? 'B' : 'S',
      })),
    );
  }, [trades]);

  return <div ref={ref} style={{height}} />;
};
```

- [ ] **Step 2: 类型检查 + 构建验证**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
npx tsc --noEmit -p tsconfig.json 2>&1 | head -20 || true
```

Expected: 无 replay 相关报错（若 `createSeriesMarkers` 返回类型与 `setMarkers` 不符，按 v5 实际类型调整 markersRef 声明；若项目无 tsc 脚本可跳过，Task 12 统一 build 验收）。

- [ ] **Step 3: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/replay/ReplayKlineChart.tsx
git commit -m "feat(replay): 受控K线组件——增量推进/MA副线/成交量/B-S买卖点标注"
```

---

### Task 9: 前端 — 页面骨架：ReplayPage + 旅程主页 SessionHome

**Files:**
- Create: `frontend/apps/web/src/pages/replay/ReplayPage.tsx`
- Create: `frontend/apps/web/src/pages/replay/SessionHome.tsx`
- Create: `frontend/apps/web/src/pages/replay/Replay.css`
- Test: 无（UI，手动验收）

**Interfaces:**
- Consumes: `useReplayStore`（Task 7）、`api.listSessions/createSession/deleteSession/revealSession`、UI 组件 `Card/StateView`（`src/components/ui`，具名导出）。
- Produces: `ReplayPage`（具名导出，Task 12 路由注册用）：无会话 → `SessionHome`；`sailing` → `Cockpit`（Task 10 占位引用）；`review` → `ReviewView`（Task 12 占位引用）。**本任务 Cockpit/ReviewView 先用同目录占位组件，Task 10/12 替换实现。**

- [ ] **Step 1: 写 Replay.css（三栏网格 + 全部样式骨架）**

`frontend/apps/web/src/pages/replay/Replay.css`：

```css
.replay-page { padding: 12px; height: 100%; box-sizing: border-box; }
.replay-top {
  display: flex; align-items: center; gap: 18px;
  padding: 8px 14px; margin-bottom: 10px;
  border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
  background: #1d1d1f; font-size: 13px; flex-wrap: wrap;
}
.replay-top .stat { color: #a1a1a6; }
.replay-top .stat b { color: #f5f5f7; margin-left: 4px; }
.replay-top .is-up { color: #ff453a; }
.replay-top .is-down { color: #30d158; }
.replay-cockpit {
  display: grid; gap: 10px;
  grid-template-columns: 280px minmax(0,1fr) 320px;
  height: calc(100vh - 170px); min-height: 480px;
}
.replay-panel {
  border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
  background: #1d1d1f; padding: 10px; overflow: auto; font-size: 13px;
}
.replay-panel h4 {
  margin: 0 0 8px; font-size: 12px; color: #86868b;
  text-transform: uppercase; letter-spacing: 0.06em;
}
.replay-center { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.replay-center .replay-panel.chart { flex: 1; overflow: hidden; }
.replay-pool-item {
  display: flex; justify-content: space-between; padding: 6px 8px;
  border-radius: 6px; cursor: pointer;
}
.replay-pool-item:hover { background: #2c2c2e; }
.replay-pool-item.active { background: #2c2c2e; outline: 1px solid rgba(255,255,255,0.14); }
.replay-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.replay-table th, .replay-table td {
  padding: 5px 6px; text-align: right;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.replay-table th:first-child, .replay-table td:first-child { text-align: left; }
.replay-table th { color: #86868b; font-weight: normal; }
.replay-btn {
  border: 1px solid rgba(255,255,255,0.14); background: #2c2c2e;
  color: #f5f5f7; border-radius: 6px; padding: 5px 12px;
  cursor: pointer; font-size: 13px;
}
.replay-btn:hover { background: #3a3a3c; }
.replay-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.replay-btn.buy { border-color: #ff453a; color: #ff453a; }
.replay-btn.sell { border-color: #30d158; color: #30d158; }
.replay-btn.primary { background: #0a84ff; border-color: #0a84ff; color: #fff; }
.replay-controls { display: flex; gap: 8px; align-items: center; justify-content: center; }
.replay-error {
  color: #ff9f0a; font-size: 12px; padding: 4px 8px;
  background: rgba(255,159,10,0.1); border-radius: 6px; margin-top: 6px;
}
.replay-gauges { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.replay-gauge {
  border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;
  padding: 6px 8px; font-size: 12px;
}
.replay-gauge .label { color: #86868b; display: block; margin-bottom: 2px; }
.replay-gauge .value { color: #f5f5f7; font-variant-numeric: tabular-nums; }
.replay-pct-bar { height: 4px; background: #2c2c2e; border-radius: 2px; margin-top: 4px; }
.replay-pct-bar i { display: block; height: 100%; background: #0a84ff; border-radius: 2px; }
.replay-input {
  width: 100%; box-sizing: border-box; background: #2c2c2e;
  border: 1px solid rgba(255,255,255,0.14); color: #f5f5f7;
  border-radius: 6px; padding: 6px 8px; font-size: 13px; margin-bottom: 8px;
}
.replay-modal-mask {
  position: fixed; inset: 0; background: rgba(0,0,0,0.55);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.replay-modal {
  width: 640px; max-height: 76vh; overflow: auto;
  background: #1d1d1f; border: 1px solid rgba(255,255,255,0.14);
  border-radius: 12px; padding: 16px;
}
.replay-tabs { display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }
.replay-stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 10px; }
.replay-hint { color: #86868b; font-size: 12px; }
```

- [ ] **Step 2: 写占位 Cockpit / ReviewView（Task 10/12 替换）**

`frontend/apps/web/src/pages/replay/Cockpit.tsx`：

```tsx
export const Cockpit: React.FC = () => (
  <div className="replay-panel">驾驶舱（Task 10 实现）</div>
);
```

`frontend/apps/web/src/pages/replay/ReviewView.tsx`：

```tsx
export const ReviewView: React.FC = () => (
  <div className="replay-panel">复盘视图（Task 12 实现）</div>
);
```

- [ ] **Step 3: 写 SessionHome**

`frontend/apps/web/src/pages/replay/SessionHome.tsx`：

```tsx
import {useCallback, useEffect, useState} from 'react';
import {StateView} from '../../components/ui';
import * as api from './api';
import {useReplayStore} from './store';
import type {SessionMeta} from './types';

const fmtMoney = (v: number) =>
  v.toLocaleString('zh-CN', {maximumFractionDigits: 0});

export const SessionHome: React.FC = () => {
  const openSession = useReplayStore((s) => s.openSession);
  const [list, setList] = useState<SessionMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [startDate, setStartDate] = useState('2020-01-02');
  const [endDate, setEndDate] = useState('');
  const [capital, setCapital] = useState(1000000);

  const refresh = useCallback(async () => {
    const r = await api.listSessions();
    if (r.code === 0) setList(r.data);
    else setError(r.msg || '加载失败');
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = async () => {
    if (!name.trim()) {
      setError('给旅程起个名字');
      return;
    }
    const r = await api.createSession({
      name: name.trim(),
      start_date: startDate,
      initial_capital: capital,
      ...(endDate ? {end_date: endDate} : {}),
    });
    if (r.code !== 0) {
      setError(r.msg || '创建失败');
      return;
    }
    setError(null);
    await openSession(r.data.id);
  };

  const remove = async (id: number) => {
    if (!window.confirm('删除这段旅程？不可恢复。')) return;
    await api.deleteSession(id);
    await refresh();
  };

  return (
    <div className="replay-page">
      <h3 style={{marginTop: 0}}>✈ 时光机 · 选择或开启一段旅程</h3>
      <div className="replay-panel" style={{marginBottom: 10}}>
        <h4>开启新旅程</h4>
        <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
          <input className="replay-input" style={{width: 180}}
            placeholder="旅程名称" value={name}
            onChange={(e) => setName(e.target.value)} />
          <input className="replay-input" style={{width: 150}}
            type="date" value={startDate}
            onChange={(e) => setStartDate(e.target.value)} />
          <input className="replay-input" style={{width: 150}}
            type="date" value={endDate} placeholder="终点(可选)"
            onChange={(e) => setEndDate(e.target.value)} />
          <input className="replay-input" style={{width: 130}}
            type="number" step={100000} value={capital}
            onChange={(e) => setCapital(Number(e.target.value))} />
          <button className="replay-btn primary" onClick={() => void create()}>
            起飞 ▶
          </button>
        </div>
        <div className="replay-hint">
          起始日非交易日会自动顺延到下一交易日；终点留空则一路开到数据尽头。
        </div>
        {error && <div className="replay-error">{error}</div>}
      </div>
      <div className="replay-panel">
        <h4>历史旅程</h4>
        {list === null ? (
          <StateView state="loading" />
        ) : list.length === 0 ? (
          <StateView state="empty" />
        ) : (
          <table className="replay-table">
            <thead>
              <tr>
                <th>名称</th><th>起始</th><th>当前</th><th>初始资金</th>
                <th>现金</th><th>状态</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.start_date}</td>
                  <td>{s.current_date}</td>
                  <td>{fmtMoney(s.initial_capital)}</td>
                  <td>{fmtMoney(s.cash)}</td>
                  <td>{s.status === 'revealed' ? '已揭晓' : '航行中'}</td>
                  <td>
                    <button className="replay-btn"
                      onClick={() => void openSession(s.id)}>
                      {s.status === 'revealed' ? '查看复盘' : '继续'}
                    </button>{' '}
                    <button className="replay-btn"
                      onClick={() => void remove(s.id)}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
```

- [ ] **Step 4: 写 ReplayPage**

`frontend/apps/web/src/pages/replay/ReplayPage.tsx`：

```tsx
import {Cockpit} from './Cockpit';
import {ReviewView} from './ReviewView';
import {SessionHome} from './SessionHome';
import {useReplayStore} from './store';
import './Replay.css';

export const ReplayPage: React.FC = () => {
  const session = useReplayStore((s) => s.session);
  const phase = useReplayStore((s) => s.phase);
  if (!session) return <SessionHome />;
  return (
    <div className="replay-page">
      {phase === 'review' ? <ReviewView /> : <Cockpit />}
    </div>
  );
};
```

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/replay/ReplayPage.tsx \
        frontend/apps/web/src/pages/replay/SessionHome.tsx \
        frontend/apps/web/src/pages/replay/Cockpit.tsx \
        frontend/apps/web/src/pages/replay/ReviewView.tsx \
        frontend/apps/web/src/pages/replay/Replay.css
git commit -m "feat(replay): 页面骨架——旅程主页(创建/继续/删除)+双模式分发+样式令牌"
```

---

### Task 10: 前端 — 驾驶舱三栏：顶栏/股票池/播放控制/下单台

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/Cockpit.tsx`（替换占位）
- Create: `frontend/apps/web/src/pages/replay/TopBar.tsx`、`PoolPanel.tsx`、`PlayControls.tsx`、`OrderTicket.tsx`
- Test: 无（UI，Task 12 手动验收）

**Interfaces:**
- Consumes: `useReplayStore` + `viewDate/visibleBars`（Task 7）、`ReplayKlineChart`（Task 8）。
- Produces: `Cockpit` 完整三栏。`OrderTicket` 引用 Task 11 的 `AddStockModal`？——否，加股入口在 `PoolPanel`（Task 11 替换其占位按钮的 onClick 逻辑；本任务 PoolPanel 的 [+ 加股] 先用 `prompt('输入股票代码')` 兜底调 `addSymbol`，Task 11 换成弹层）。

- [ ] **Step 1: TopBar**

`frontend/apps/web/src/pages/replay/TopBar.tsx`：

```tsx
import {useReplayStore, viewDate} from './store';

const fmt = (v: number) =>
  v.toLocaleString('zh-CN', {maximumFractionDigits: 0});

export const TopBar: React.FC = () => {
  const session = useReplayStore((s) => s.session);
  const cursor = useReplayStore((s) => s.cursor);
  const datesLen = useReplayStore((s) => s.dates.length);
  const vd = useReplayStore(viewDate);
  const cash = useReplayStore((s) => s.cash);
  const nav = useReplayStore((s) => s.nav);
  const error = useReplayStore((s) => s.error);
  const closeSession = useReplayStore((s) => s.closeSession);
  const reveal = useReplayStore((s) => s.reveal);
  if (!session) return null;
  const total = nav.length ? nav[nav.length - 1].value : session.initial_capital;
  const ret = total / session.initial_capital - 1;
  const retCls = ret >= 0 ? 'is-up' : 'is-down';
  return (
    <div className="replay-top">
      <b>✈ {session.name}</b>
      <span className="stat">日期<b>{vd}</b></span>
      <span className="stat">第<b>{cursor + 1}</b>/{datesLen} 个交易日</span>
      <span className="stat">现金<b>{fmt(cash)}</b></span>
      <span className="stat">总资产<b>{fmt(total)}</b></span>
      <span className="stat">收益
        <b className={retCls}>{(ret * 100).toFixed(2)}%</b>
      </span>
      <span style={{flex: 1}} />
      {error && <span className="replay-error">{error}</span>}
      <button className="replay-btn" onClick={() => void reveal()}>
        揭晓复盘
      </button>
      <button className="replay-btn"
        onClick={() => { void useReplayStore.getState().saveNow(); closeSession(); }}>
        离舱
      </button>
    </div>
  );
};
```

- [ ] **Step 2: PlayControls（含自动播放）**

`frontend/apps/web/src/pages/replay/PlayControls.tsx`：

```tsx
import {useEffect} from 'react';
import {useReplayStore} from './store';

export const PlayControls: React.FC = () => {
  const playing = useReplayStore((s) => s.playing);
  const speed = useReplayStore((s) => s.speed);
  const cursor = useReplayStore((s) => s.cursor);
  const datesLen = useReplayStore((s) => s.dates.length);
  const {advance, stepBack, play, pause, setSpeed} = useReplayStore.getState();

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      void useReplayStore.getState().advance();
    }, 1000 / speed);
    return () => clearInterval(t);
  }, [playing, speed]);

  const atReview = cursor < datesLen - 1;
  return (
    <div className="replay-panel replay-controls">
      <button className="replay-btn" disabled={cursor <= 0}
        onClick={stepBack} title="回看一天（只看不许交易）">
        ◀
      </button>
      <button className="replay-btn primary"
        onClick={() => void advance()}>
        下一天 ▶
      </button>
      <button className="replay-btn"
        onClick={() => (playing ? pause() : play())}>
        {playing ? '⏸ 暂停' : '▶ 自动'}
      </button>
      {([1, 2, 4] as const).map((v) => (
        <button key={v}
          className={`replay-btn${speed === v ? ' primary' : ''}`}
          onClick={() => setSpeed(v)}>
          {v}x
        </button>
      ))}
      {atReview && <span className="replay-hint">回看中（不可交易）</span>}
    </div>
  );
};
```

- [ ] **Step 3: PoolPanel（股票池 + 持仓）**

`frontend/apps/web/src/pages/replay/PoolPanel.tsx`：

```tsx
import {useState} from 'react';
import {useReplayStore, viewDate} from './store';

const pct = (bars: {close: number}[], vd: string | null) => {
  const vis = bars.filter((b: any) => !vd || b.trade_date <= vd);
  if (vis.length < 2) return null;
  const a = vis[vis.length - 2].close;
  const b = vis[vis.length - 1].close;
  return a > 0 ? (b / a - 1) * 100 : null;
};

export const PoolPanel: React.FC = () => {
  const pool = useReplayStore((s) => s.pool);
  const names = useReplayStore((s) => s.names);
  const barsBySymbol = useReplayStore((s) => s.barsBySymbol);
  const positions = useReplayStore((s) => s.positions);
  const selected = useReplayStore((s) => s.selectedSymbol);
  const vd = useReplayStore(viewDate);
  const selectSymbol = useReplayStore((s) => s.selectSymbol);
  const addSymbol = useReplayStore((s) => s.addSymbol);
  const [busy, setBusy] = useState(false);

  const add = async () => {
    const code = window.prompt('输入股票代码（如 600519）');
    if (!code) return;
    setBusy(true);
    await addSymbol(code.trim());
    setBusy(false);
  };

  return (
    <div className="replay-panel">
      <h4>
        股票池{' '}
        <button className="replay-btn" style={{float: 'right'}}
          disabled={busy} onClick={() => void add()}>
          + 加股
          {/* Task 11 替换为 AddStockModal 弹层 */}
        </button>
      </h4>
      {pool.length === 0 && (
        <div className="replay-hint">池子还空着，点「+ 加股」开始。</div>
      )}
      {pool.map((sym) => {
        const p = pct(barsBySymbol[sym] ?? [], vd);
        return (
          <div key={sym}
            className={`replay-pool-item${sym === selected ? ' active' : ''}`}
            onClick={() => selectSymbol(sym)}>
            <span>{names[sym] ? `${names[sym]} ` : ''}{sym}</span>
            <span className={p == null ? '' : p >= 0 ? 'is-up' : 'is-down'}>
              {p == null ? '—' : `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`}
            </span>
          </div>
        );
      })}
      <h4 style={{marginTop: 14}}>持仓</h4>
      {positions.length === 0 ? (
        <div className="replay-hint">空仓</div>
      ) : (
        <table className="replay-table">
          <thead>
            <tr><th>标的</th><th>股数</th><th>成本</th><th>现价</th><th>浮盈</th></tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              // 防未来泄漏：持仓现价/浮盈也必须按视角日截断（Task 10 审查发现）
              const bars = (barsBySymbol[p.symbol] ?? []).filter(
                (b) => !vd || b.trade_date <= vd);
              const last = bars.length ? bars[bars.length - 1].close : null;
              const pnl = last == null || p.shares === 0
                ? null : (last / p.cost_price - 1) * 100;
              return (
                <tr key={p.symbol} style={{cursor: 'pointer'}}
                  onClick={() => selectSymbol(p.symbol)}>
                  <td>{p.symbol}</td>
                  <td>{p.shares}</td>
                  <td>{p.cost_price.toFixed(2)}</td>
                  <td>{last == null ? '—' : last.toFixed(2)}</td>
                  <td className={pnl == null ? '' : pnl >= 0 ? 'is-up' : 'is-down'}>
                    {pnl == null ? '—' : `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
};
```

- [ ] **Step 4: OrderTicket（下单台）**

`frontend/apps/web/src/pages/replay/OrderTicket.tsx`：

```tsx
import {useMemo, useState} from 'react';
import {useReplayStore, viewDate, visibleBars} from './store';

export const OrderTicket: React.FC = () => {
  const symbol = useReplayStore((s) => s.selectedSymbol);
  const names = useReplayStore((s) => s.names);
  const cash = useReplayStore((s) => s.cash);
  const positions = useReplayStore((s) => s.positions);
  const bars = useReplayStore((s) =>
    s.selectedSymbol ? s.barsBySymbol[s.selectedSymbol] ?? [] : []);
  const vd = useReplayStore(viewDate);
  const atLatest = useReplayStore((s) => s.cursor === s.dates.length - 1);
  const placeOrder = useReplayStore((s) => s.placeOrder);
  const [shares, setShares] = useState(100);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  const today = vis.length && vis[vis.length - 1].trade_date === vd
    ? vis[vis.length - 1] : null;
  const pos = positions.find((p) => p.symbol === symbol);
  const sellable = pos && vd && pos.buy_date < vd ? pos.shares : 0;
  const maxBuy = today ? Math.floor(cash / (today.close * 100)) * 100 : 0;

  const submit = async (side: 'buy' | 'sell') => {
    setBusy(true);
    const ok = await placeOrder(side, shares, note || undefined);
    if (ok) setNote('');
    setBusy(false);
  };

  if (!symbol) {
    return (
      <div className="replay-panel">
        <h4>下单台</h4>
        <div className="replay-hint">先在左侧选一只股票。</div>
      </div>
    );
  }
  return (
    <div className="replay-panel">
      <h4>下单台 · {names[symbol] ?? ''} {symbol}</h4>
      <div className="replay-hint" style={{marginBottom: 8}}>
        {today
          ? `${vd} 收盘价 ¥${today.close.toFixed(2)}（尾盘价成交）`
          : `${vd} 停牌/无数据`}
      </div>
      <input className="replay-input" type="number" min={100} step={100}
        value={shares} onChange={(e) => setShares(Number(e.target.value))}
        placeholder="股数（100 的整数倍）" />
      <input className="replay-input" value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="下单理由（复盘时回看，可空）" />
      <div className="replay-hint" style={{marginBottom: 8}}>
        可买 {maxBuy} 股 · 可卖 {sellable} 股（T+1）
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <button className="replay-btn buy" style={{flex: 1}}
          disabled={busy || !atLatest || !today}
          onClick={() => void submit('buy')}>
          买入
        </button>
        <button className="replay-btn sell" style={{flex: 1}}
          disabled={busy || !atLatest || !today || sellable === 0}
          onClick={() => void submit('sell')}>
          卖出
        </button>
      </div>
      {!atLatest && (
        <div className="replay-hint" style={{marginTop: 6}}>
          回看中，回到最新一天才能交易。
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 5: Cockpit 组装（替换占位）**

`frontend/apps/web/src/pages/replay/Cockpit.tsx`：

```tsx
import {useMemo} from 'react';
import {OrderTicket} from './OrderTicket';
import {PlayControls} from './PlayControls';
import {PoolPanel} from './PoolPanel';
import {ReplayKlineChart} from './ReplayKlineChart';
import {TopBar} from './TopBar';
import {useReplayStore, viewDate} from './store';

export const Cockpit: React.FC = () => {
  const symbol = useReplayStore((s) => s.selectedSymbol);
  const bars = useReplayStore((s) =>
    s.selectedSymbol ? s.barsBySymbol[s.selectedSymbol] ?? [] : []);
  const vd = useReplayStore(viewDate);
  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  return (
    <>
      <TopBar />
      <div className="replay-cockpit">
        <PoolPanel />
        <div className="replay-center">
          <div className="replay-panel chart">
            {symbol
              ? <ReplayKlineChart bars={vis} height={460} />
              : <div className="replay-hint" style={{padding: 20}}>
                  从左侧股票池选一只标的，K 线风挡在这里展开。
                </div>}
          </div>
          <PlayControls />
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0, overflow: 'auto'}}>
          <OrderTicket />
          {/* Task 11 追加 GaugePanel / ValuationPanel */}
        </div>
      </div>
    </>
  );
};
```

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/replay/Cockpit.tsx \
        frontend/apps/web/src/pages/replay/TopBar.tsx \
        frontend/apps/web/src/pages/replay/PoolPanel.tsx \
        frontend/apps/web/src/pages/replay/PlayControls.tsx \
        frontend/apps/web/src/pages/replay/OrderTicket.tsx
git commit -m "feat(replay): 驾驶舱三栏——顶栏/股票池/播放控制台/下单台(T+1可卖计算)"
```

---

### Task 11: 前端 — 加股弹层（4 页签）+ 指标仪表 + 估值面板

**Files:**
- Create: `frontend/apps/web/src/pages/replay/AddStockModal.tsx`、`GaugePanel.tsx`、`ValuationPanel.tsx`
- Modify: `frontend/apps/web/src/pages/replay/PoolPanel.tsx`（[+] 换弹层）、`Cockpit.tsx`（右栏追加两面板）
- Test: 无（UI，Task 12 手动验收）

**Interfaces:**
- Consumes: `api.runScreener/searchSymbols/listWatchGroups/listWatchItems/fetchBoard`（Task 7）、`engine/indicators`（Task 6）、`store.addSymbol`。
- Produces: `<AddStockModal open onClose />`（内部直接调 `addSymbol`）；`<GaugePanel />`、`<ValuationPanel />`（自取自渲染，挂右栏）。

- [ ] **Step 1: AddStockModal**

`frontend/apps/web/src/pages/replay/AddStockModal.tsx`：

```tsx
import {useEffect, useState} from 'react';
import * as api from './api';
import {useReplayStore, viewDate} from './store';
import type {BoardRow} from './types';

type TabKey = 'search' | 'screener' | 'watchlist' | 'board';

const SCREENER_MODES: {key: string; label: string}[] = [
  {key: 'magic_formula', label: '神奇公式'},
  {key: 'dividend', label: '红利'},
  {key: 'fscore', label: 'F-Score'},
  {key: 'dividend_value', label: '红利低估'},
  {key: 'quality', label: '质量'},
];

export const AddStockModal: React.FC<{open: boolean; onClose: () => void}> = ({
  open, onClose,
}) => {
  const vd = useReplayStore(viewDate);
  const addSymbol = useReplayStore((s) => s.addSymbol);
  const [tab, setTab] = useState<TabKey>('search');
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<{symbol: string; name: string}[]>([]);
  const [mode, setMode] = useState('dividend_value');
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [groups, setGroups] = useState<{id: number; name: string}[]>([]);
  const [items, setItems] = useState<{symbol: string}[]>([]);
  const [boardRows, setBoardRows] = useState<BoardRow[]>([]);
  const [boardType, setBoardType] = useState<'gainers' | 'amount'>('gainers');
  const [hint, setHint] = useState<string | null>(null);

  const add = async (symbol: string, name?: string) => {
    await addSymbol(symbol, name);
    setHint(null);
    onClose();
  };

  useEffect(() => {
    if (!open || tab !== 'watchlist') return;
    void api.listWatchGroups().then((r) => {
      if (r.code === 0) setGroups(r.data);
    });
  }, [open, tab]);

  useEffect(() => {
    if (!open || tab !== 'board' || !vd) return;
    void api.fetchBoard(vd, boardType).then((r) => {
      if (r.code === 0) setBoardRows(r.data);
      else setHint(r.msg);
    });
  }, [open, tab, boardType, vd]);

  if (!open) return null;

  const doSearch = async () => {
    if (!q.trim()) return;
    const r = await api.searchSymbols(q.trim());
    if (r.code === 0) setHits(r.data);
  };

  const doScreen = async () => {
    if (!vd) return;
    setHint('以当日口径筛选中（财报为报告期滞后60天近似）…');
    const r = await api.runScreener(mode, 30, vd);
    if (r.code === 0) {
      setRows(r.data.ranked_list ?? []);
      setHint(null);
    } else setHint(r.msg || '筛选失败');
  };

  return (
    <div className="replay-modal-mask" onClick={onClose}>
      <div className="replay-modal" onClick={(e) => e.stopPropagation()}>
        <div className="replay-tabs">
          {([['search', '搜索'], ['screener', '当时选股器'],
             ['watchlist', '自选股导入'], ['board', '当日榜单']] as const)
            .map(([k, label]) => (
              <button key={k}
                className={`replay-btn${tab === k ? ' primary' : ''}`}
                onClick={() => setTab(k)}>
                {label}
              </button>
            ))}
          <span style={{flex: 1}} />
          <button className="replay-btn" onClick={onClose}>关闭</button>
        </div>
        <div className="replay-hint" style={{marginBottom: 8}}>
          当前日期 {vd}：只使用这一天真实可得的信息。
          {tab === 'watchlist' && ' ⚠ 自选股是你“现在”的收藏，含轻微未来泄漏。'}
          {tab === 'screener' && ' 财报口径：报告期 ≤ 当日−60天（库无披露日列）。'}
        </div>
        {hint && <div className="replay-error">{hint}</div>}

        {tab === 'search' && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8}}>
              <input className="replay-input" style={{marginBottom: 0}}
                placeholder="代码 / 名称" value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void doSearch()} />
              <button className="replay-btn primary"
                onClick={() => void doSearch()}>搜索</button>
            </div>
            {hits.map((x) => (
              <div key={x.symbol} className="replay-pool-item"
                onClick={() => void add(x.symbol, x.name)}>
                <span>{x.name} {x.symbol}</span>
                <span className="replay-hint">加入 →</span>
              </div>
            ))}
          </>
        )}

        {tab === 'screener' && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8}}>
              <select className="replay-input" style={{width: 160, marginBottom: 0}}
                value={mode} onChange={(e) => setMode(e.target.value)}>
                {SCREENER_MODES.map((m) => (
                  <option key={m.key} value={m.key}>{m.label}</option>
                ))}
              </select>
              <button className="replay-btn primary"
                onClick={() => void doScreen()}>运行</button>
            </div>
            <table className="replay-table">
              <thead>
                <tr><th>标的</th><th>评分</th><th>PE_TTM</th><th>ROE</th><th /></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={String(r.symbol)}>
                    <td>{String(r.symbol)}</td>
                    <td>{typeof r.score === 'number' ? r.score.toFixed(1) : '—'}</td>
                    <td>{typeof r.pe_ttm === 'number' ? r.pe_ttm.toFixed(1) : '—'}</td>
                    <td>{typeof r.roe === 'number' ? `${(r.roe * 100).toFixed(1)}%` : '—'}</td>
                    <td>
                      <button className="replay-btn"
                        onClick={() => void add(String(r.symbol))}>
                        加入
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {tab === 'watchlist' && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap'}}>
              {groups.map((g) => (
                <button key={g.id} className="replay-btn"
                  onClick={() => void api.listWatchItems(g.id).then((r) => {
                    if (r.code === 0) setItems(r.data);
                  })}>
                  {g.name}
                </button>
              ))}
            </div>
            {items.map((it) => (
              <div key={it.symbol} className="replay-pool-item"
                onClick={() => void add(it.symbol)}>
                <span>{it.symbol}</span>
                <span className="replay-hint">加入 →</span>
              </div>
            ))}
          </>
        )}

        {tab === 'board' && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8}}>
              {(['gainers', 'amount'] as const).map((t) => (
                <button key={t}
                  className={`replay-btn${boardType === t ? ' primary' : ''}`}
                  onClick={() => setBoardType(t)}>
                  {t === 'gainers' ? '涨幅榜' : '成交额榜'}
                </button>
              ))}
            </div>
            <table className="replay-table">
              <thead>
                <tr><th>标的</th><th>名称</th><th>收盘</th><th>涨幅</th><th /></tr>
              </thead>
              <tbody>
                {boardRows.map((r) => (
                  <tr key={r.symbol}>
                    <td>{r.symbol}</td>
                    <td>{r.name}</td>
                    <td>{r.close.toFixed(2)}</td>
                    <td className={r.pct_chg >= 0 ? 'is-up' : 'is-down'}>
                      {r.pct_chg >= 0 ? '+' : ''}{r.pct_chg.toFixed(2)}%
                    </td>
                    <td>
                      <button className="replay-btn"
                        onClick={() => void add(r.symbol, r.name)}>
                        加入
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
};
```

- [ ] **Step 2: GaugePanel（指标仪表）**

`frontend/apps/web/src/pages/replay/GaugePanel.tsx`：

```tsx
import {useMemo} from 'react';
import {kdj, macd, rsiWilder, sma} from './engine/indicators';
import {useReplayStore, viewDate} from './store';

const last = <T,>(arr: (T | null)[]): T | null => {
  for (let i = arr.length - 1; i >= 0; i--) if (arr[i] != null) return arr[i];
  return null;
};

export const GaugePanel: React.FC = () => {
  const bars = useReplayStore((s) =>
    s.selectedSymbol ? s.barsBySymbol[s.selectedSymbol] ?? [] : []);
  const vd = useReplayStore(viewDate);
  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  if (vis.length < 2) {
    return (
      <div className="replay-panel">
        <h4>指标仪表</h4>
        <div className="replay-hint">数据不足。</div>
      </div>
    );
  }
  const closes = vis.map((b) => b.close);
  const {dif, dea, hist} = macd(closes, 12, 26, 9);
  const rsi = rsiWilder(closes, 14);
  const kd = kdj(vis);
  const gauges: [string, string][] = [
    ['MA5', last(sma(closes, 5))?.toFixed(2) ?? '—'],
    ['MA20', last(sma(closes, 20))?.toFixed(2) ?? '—'],
    ['MA60', last(sma(closes, 60))?.toFixed(2) ?? '—'],
    ['DIF', last(dif)?.toFixed(3) ?? '—'],
    ['DEA', last(dea)?.toFixed(3) ?? '—'],
    ['MACD柱', last(hist)?.toFixed(3) ?? '—'],
    ['RSI14', last(rsi)?.toFixed(1) ?? '—'],
    ['K / D / J', kd.length && kd[kd.length - 1].k != null
      ? `${kd[kd.length - 1].k!.toFixed(1)} / ${kd[kd.length - 1].d!.toFixed(1)} / ${kd[kd.length - 1].j!.toFixed(1)}`
      : '—'],
  ];
  return (
    <div className="replay-panel">
      <h4>指标仪表（{vd} 口径）</h4>
      <div className="replay-gauges">
        {gauges.map(([label, value]) => (
          <div key={label} className="replay-gauge">
            <span className="label">{label}</span>
            <span className="value">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
```

- [ ] **Step 3: ValuationPanel（估值分位）**

`frontend/apps/web/src/pages/replay/ValuationPanel.tsx`：

```tsx
import {useEffect, useState} from 'react';
import * as api from './api';
import {useReplayStore, viewDate} from './store';
import type {ValuationInfo, ValuationMetric} from './types';

const Row: React.FC<{label: string; m: ValuationMetric | null}> = ({label, m}) => (
  <div className="replay-gauge" style={{gridColumn: '1 / -1'}}>
    <span className="label">{label}</span>
    {m ? (
      <>
        <span className="value">
          {m.value.toFixed(2)} · 十年分位{' '}
          {m.percentile == null ? '样本不足' : `${(m.percentile * 100).toFixed(0)}%`}
        </span>
        {m.percentile != null && (
          <div className="replay-pct-bar">
            <i style={{width: `${m.percentile * 100}%`}} />
          </div>
        )}
      </>
    ) : (
      <span className="value">—</span>
    )}
  </div>
);

export const ValuationPanel: React.FC = () => {
  const symbol = useReplayStore((s) => s.selectedSymbol);
  const vd = useReplayStore(viewDate);
  const [info, setInfo] = useState<ValuationInfo | null>(null);
  useEffect(() => {
    if (!symbol || !vd) return;
    setInfo(null);
    void api.fetchValuation(symbol, vd).then((r) => {
      if (r.code === 0) setInfo(r.data);
    });
  }, [symbol, vd]);
  return (
    <div className="replay-panel">
      <h4>估值（截至 {vd}）</h4>
      <div className="replay-gauges">
        <Row label="PE(TTM)" m={info?.pe_ttm ?? null} />
        <Row label="PB" m={info?.pb ?? null} />
      </div>
    </div>
  );
};
```

- [ ] **Step 4: 接线 PoolPanel + Cockpit**

`PoolPanel.tsx`：顶部 import `AddStockModal`，加 state `const [showAdd, setShowAdd] = useState(false);`，[+] 按钮改为 `onClick={() => setShowAdd(true)}`、删除 `add` 函数与 `busy`，组件末尾渲染 `<AddStockModal open={showAdd} onClose={() => setShowAdd(false)} />`。删除不再用的 `addSymbol` 引用。

`Cockpit.tsx`：右栏容器内 `<OrderTicket />` 之后追加 `<GaugePanel />` 和 `<ValuationPanel />`（import 对应组件），删除 Step 5 的占位注释。

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/replay/AddStockModal.tsx \
        frontend/apps/web/src/pages/replay/GaugePanel.tsx \
        frontend/apps/web/src/pages/replay/ValuationPanel.tsx \
        frontend/apps/web/src/pages/replay/PoolPanel.tsx \
        frontend/apps/web/src/pages/replay/Cockpit.tsx
git commit -m "feat(replay): 加股四页签弹层(搜索/当时选股器/自选/榜单)+指标仪表+估值分位面板"
```

---

### Task 12: 前端 — 揭晓复盘视图 + 路由/导航注册 + 全链路验收

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/ReviewView.tsx`（替换占位）
- Modify: `frontend/apps/web/src/App.tsx`（lazy import + Route）
- Modify: `frontend/apps/web/src/components/Layout.tsx`（导航项）
- Test: 全量回归（见 Step 4/5/6）

**Interfaces:**
- Consumes: 全部 store/api/engine/K线组件；recharts（`LineChart`）；`annualizedReturn/maxDrawdown/winRate`（nav.ts）。
- Produces: `/replay` 可用页面 + 导航入口「时光机」。

- [ ] **Step 1: ReviewView（替换占位）**

`frontend/apps/web/src/pages/replay/ReviewView.tsx`：

```tsx
import {useMemo} from 'react';
import {
  Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  axisProps, colorDown, colorUp, tooltipProps,
} from '../../lib/chartTheme';
import {ReplayKlineChart} from './ReplayKlineChart';
import {
  annualizedReturn, maxDrawdown, roundTrips, winRate,
} from './engine/nav';
import {useReplayStore} from './store';

const pctFmt = (v: number | null) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;

export const ReviewView: React.FC = () => {
  const session = useReplayStore((s) => s.session);
  const pool = useReplayStore((s) => s.pool);
  const names = useReplayStore((s) => s.names);
  const barsBySymbol = useReplayStore((s) => s.barsBySymbol);
  const benchmarkBars = useReplayStore((s) => s.benchmarkBars);
  const nav = useReplayStore((s) => s.nav);
  const trades = useReplayStore((s) => s.trades);
  const selected = useReplayStore((s) => s.selectedSymbol);
  const selectSymbol = useReplayStore((s) => s.selectSymbol);
  const closeSession = useReplayStore((s) => s.closeSession);

  const stats = useMemo(() => {
    if (!session || nav.length === 0) return null;
    const initial = session.initial_capital;
    const final = nav[nav.length - 1].value;
    const total = final / initial - 1;
    const days = nav.length;
    const b0 = benchmarkBars.find((b) => b.trade_date >= session.start_date);
    const b1 = benchmarkBars[benchmarkBars.length - 1];
    const benchRet = b0 && b1 ? b1.close / b0.close - 1 : null;
    return {
      total,
      annualized: annualizedReturn(initial, final, days),
      mdd: maxDrawdown(nav),
      winRate: winRate(trades),
      trips: roundTrips(trades).length,
      benchRet,
      excess: benchRet == null ? null : total - benchRet,
    };
  }, [session, nav, trades, benchmarkBars]);

  const curve = useMemo(() => {
    if (!session) return [];
    const initial = session.initial_capital;
    const b0 = benchmarkBars.find(
      (b) => b.trade_date >= session.start_date);
    const bClose = new Map(benchmarkBars.map((b) => [b.trade_date, b.close]));
    return nav.map((p) => {
      const bc = b0 ? bClose.get(p.date) : undefined;
      return {
        date: p.date,
        nav: +(p.value / initial).toFixed(4),
        benchmark: b0 && bc != null ? +(bc / b0.close).toFixed(4) : null,
      };
    });
  }, [session, nav, benchmarkBars]);

  if (!session) return null;
  const symbolTrades = trades.filter((t) => t.symbol === selected);
  return (
    <>
      <div className="replay-top">
        <b>✈ {session.name} · 复盘</b>
        <span className="stat">
          区间<b>{session.start_date} ~ {nav[nav.length - 1]?.date}</b>
        </span>
        <span style={{flex: 1}} />
        <button className="replay-btn" onClick={closeSession}>
          返回旅程列表
        </button>
      </div>
      {stats && (
        <div className="replay-stats">
          {([
            ['总收益', pctFmt(stats.total),
              stats.total >= 0 ? colorUp : colorDown],
            ['年化', pctFmt(stats.annualized), undefined],
            ['最大回撤', `-${(stats.mdd * 100).toFixed(2)}%`, colorDown],
            ['胜率(平仓)', stats.winRate == null
              ? '—' : `${(stats.winRate * 100).toFixed(0)}% (${stats.trips}次)`,
              undefined],
            ['超额(vs 基准)', pctFmt(stats.excess), undefined],
          ] as const).map(([label, value, color]) => (
            <div key={label} className="replay-gauge">
              <span className="label">{label}</span>
              <span className="value" style={{color}}>{value}</span>
            </div>
          ))}
        </div>
      )}
      <div className="replay-panel" style={{marginBottom: 10, height: 220}}>
        <h4>净值 vs 基准（归一）</h4>
        <ResponsiveContainer width="100%" height={170}>
          <LineChart data={curve}>
            <XAxis dataKey="date" {...axisProps} minTickGap={60} />
            <YAxis {...axisProps} domain={['auto', 'auto']} />
            <Tooltip {...tooltipProps} />
            <Line type="monotone" dataKey="nav" name="本组合"
              stroke="#0a84ff" dot={false} strokeWidth={1.5} />
            <Line type="monotone" dataKey="benchmark" name="基准"
              stroke="#a1a1a6" dot={false} strokeWidth={1}
              strokeDasharray="4 3" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="replay-panel" style={{marginBottom: 10}}>
        <h4>
          买卖点回顾{' '}
          <select className="replay-input"
            style={{width: 220, display: 'inline-block', marginBottom: 0}}
            value={selected ?? ''}
            onChange={(e) => selectSymbol(e.target.value)}>
            {pool.map((s) => (
              <option key={s} value={s}>{names[s] ?? ''} {s}</option>
            ))}
          </select>
        </h4>
        {selected && (
          <ReplayKlineChart
            bars={barsBySymbol[selected] ?? []}
            trades={symbolTrades}
            height={380}
          />
        )}
      </div>
      <div className="replay-panel">
        <h4>成交清单（含下单理由）</h4>
        <table className="replay-table">
          <thead>
            <tr>
              <th>日期</th><th>标的</th><th>方向</th><th>价格</th>
              <th>股数</th><th>佣金</th><th>印花税</th><th>理由</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={t.id ?? i}>
                <td>{t.trade_date}</td>
                <td>{t.symbol}</td>
                <td className={t.side === 'buy' ? 'is-up' : 'is-down'}>
                  {t.side === 'buy' ? '买入' : '卖出'}
                </td>
                <td>{t.price.toFixed(2)}</td>
                <td>{t.shares}</td>
                <td>{t.fee.toFixed(2)}</td>
                <td>{t.tax.toFixed(2)}</td>
                <td style={{textAlign: 'left'}}>{t.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
};
```

- [ ] **Step 2: App.tsx 注册路由**

`frontend/apps/web/src/App.tsx`：lazy 声明块（L27-32 PermPortfolio 之后）加：

```tsx
const Replay = lazy(() => import('./pages/replay/ReplayPage').then(m => ({default: m.ReplayPage})));
```

`<Routes>` 内（L68-69 perm-portfolio Route 之后）加：

```tsx
<Route path="/replay" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><Replay /></Suspense>} />
```

- [ ] **Step 3: Layout.tsx 导航**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
grep -n "lt-backtest" src/components/Layout.tsx
```

在含 `/lt-backtest` 的那个 NavGroup 的 items 里追加：

```tsx
{path: '/replay', label: '时光机', icon: Icon.star},
```

- [ ] **Step 4: 前端测试 + 构建**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web
npx vitest run src/pages/replay/
npx tsc --noEmit 2>&1 | grep -i replay || echo "replay 无类型错误"
rushx build 2>&1 | tail -5
```

Expected: vitest 全 PASS；tsc 无 replay 报错；`rushx build` 成功。

- [ ] **Step 5: 后端测试回归**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
python -m pytest tests/api/test_replay_router.py -v
```

Expected: 全部 PASS（会话 2 + 切片 4 + 估值榜单 4，共 10 个）。

- [ ] **Step 6: 手动端到端验收**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
./dev-start.sh   # 按输出打开前端
```

验收清单（逐项过）：
1. 导航出现「时光机」，进入 `/replay` → 旅程主页
2. 创建旅程「茅台 2020」：起始 2020-03-13、资金 100 万 → 自动进舱，顶栏日期 2020-03-13
3. [+ 加股] → 搜索"茅台"加入 → K 线只到 2020-03-13，右侧无未来数据
4. 加股弹层四页签：当时选股器（红利低估，as_of 当日）出结果可加入；自选股导入可用；当日榜单（涨幅/成交额）出数
5. 下单台买入 100 股 → 现金减少、持仓出现；当日再卖 → 提示 T+1；点「下一天」→ K 线推进一根，可卖恢复
6. 自动播放 2x 连走 10 天 → 净值/浮盈/指标/估值分位逐日刷新
7. ◀ 回看 3 天 → 下单台禁用提示；▶ 回到最新
8. 离舱 → 旅程列表「继续」→ 状态完整恢复（现金/持仓/日期/K线）
9. 揭晓复盘 → 完整 K 线 + B/S 标注 + 净值 vs 沪深300 曲线 + 5 项战绩 + 含理由的成交清单
10. 揭晓后回到列表，状态显示「已揭晓」

- [ ] **Step 7: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/replay/ReviewView.tsx \
        frontend/apps/web/src/App.tsx \
        frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(replay): 揭晓复盘视图(买卖点标注/净值vs基准/战绩)+路由导航注册"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计 §2 七项决策 → Task 1-12 全覆盖；§6.1/6.2 端点（screen 复用现有 screener，无新端点）→ Task 2-4 + Task 11；§6.3 两表 → Task 1；§4 布局 → Task 10；§5 规则 → Task 5；§7 引擎/选股/复盘 → Task 7/11/12；§8 边界 → advance 停牌缺日（Task 3）、asof>今天 400（Task 3/4）、退市沿用最后价（computeNav 用最近已知 close，Task 7）；§9 测试 → 各 Task + Task 12 回归。
- **类型一致性**：`ReplayBar/Trade/Position/NavPoint/SessionState` 前后端字段一一对应（snake_case 贯穿）；`AdvanceResp` 对应 advance 返回；`ValuationInfo` 对应 valuation 返回。
- **占位符扫描**：Cockpit/ReviewView 占位组件在 Task 10/12 显式替换；Board indicators 的签名差异已留"以真实签名为准"的适配说明（Task 6 Step 5）。

## 终审修复记录（2026-09-14 全分支终审）

- **C1 时序缺陷**：`advance` 原设计游标依赖防抖存档回写，2x/4x 播放或连点时防抖不落库导致重复推进同一天。修复：后端 advance 算出 dates 即调 `bump_current_date` 推进服务端日历游标（不碰 cash/state），前端再按 `> 当前末日期` 去重兜底。**教训：服务端游标必须随请求自洽推进，防抖存档只负责资金/持仓快照。**
- **I1**：揭晓复盘加 window.confirm（不可逆操作）。
- **I2**：create_session 拒绝 end_date > 今天；UI 明示"终点只限定复盘范围，不自动揭晓"。
- **I3(R40)**：复盘超额收益的基准窗口钳到 nav 末日期。
