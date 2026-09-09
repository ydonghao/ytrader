# 自选股（Watchlist）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做一个带分组的自选股页面——标签页切换分组，看每只股票的行情+估值，分组有概览（平均涨跌/涨跌平家数/总市值），支持分组 CRUD/排序、组内股票增删/备注/拖拽排序/跨组移动，行情 30s 轮询。

**Architecture:** 方案 A。后端新建独立 `watchlist` 模块（`models` + `repository` + `handler` + `router`，只管"成员关系"，纯持久化），并在 `market_router` 加一个通用 `POST /market/quotes`（行情+估值，可复用）。前端一个 `Watchlist.tsx` 页面（跟随 Macro 的 fetch+CSS 模式），复用 `StockSelect`、`@ytrader/common-components` 的 Table/Modal/Tabs/PnlBadge。

**Tech Stack:** 后端 FastAPI + SQLModel + PostgreSQL（测试用 sqlite 内存库做仓储单测，集成测试打本地 PG）；前端 React 18 + react-router v7 + Rsbuild，共享包 `@ytrader/common-components` / `@ytrader/arch-utils`。

## Global Constraints

- 后端响应封装 `{code,msg,data}`，`code===0` 为成功；成功/业务失败均 HTTP 200（`responses.success` / `responses.fail`），参考 `src/pkg/responses/__init__.py`。
- watchlist 表**单用户/全局**，不带 `user_id`（个人工具）。
- 新 SQLModel 表必须在 `backend/main.py` 的 `lifespan` 里 import，否则 `create_all` 看不到（参考 portfolio 模型注册）。
- 标的 symbol 体系：A 股 `sh600000`/`sz000001`、ETF `sh510300`/`sz159934`、指数 `sh000300`、港股 `02800`。
- 行情读 `stock_ohlcv`（列 `symbol, trade_date, open_, close_, high_, low_, volume, amount, market`，PK `(trade_date,symbol)`），估值读 `stock_valuation`（列 `pe, pe_ttm, pb, dv_ratio, dv_ttm, total_mv`），名称读 `stock_info`（PK `symbol`）。港股数据可能缺失→对应字段返回 `null`、前端显示「—」。
- 前端 JSON 字段用 **snake_case**（与 perm_portfolio handler 一致，前端 TS 类型同形）。
- 前端不引新依赖；拖拽用原生 HTML5 DnD。
- 前端无测试框架；验证靠 `pnpm --filter web build`（含 TS 检查）+ 手动冒烟。

## File Structure

**后端（新建）**
- `backend/src/infra/database/watchlist/__init__.py` — 空包初始化。
- `backend/src/infra/database/watchlist/models.py` — `WatchlistGroup` + `WatchlistItem` 两张 SQLModel 表。
- `backend/src/infra/database/watchlist/repository.py` — `WatchlistRepository` + 工厂 `create_watchlist_repository()` + `DuplicateWatchlistItem` 异常。**纯 group/item CRUD，不碰 stock_info**（保持可 hermetic 单测）。
- `backend/src/api/handler/watchlist_handler.py` — 校验 + `responses.success/fail`。
- `backend/src/api/router/watchlist_router.py` — `APIRouter(prefix="/watchlist")` 薄包装。
- `backend/tests/infra/database/watchlist/test_repository.py` — hermetic sqlite 仓储单测。

**后端（修改）**
- `backend/main.py` — import watchlist 模型（lifespan）+ 注册路由。
- `backend/src/api/router/market_router.py` — 新增 `POST /market/quotes` + SQL 常量 + `_to_float`。

**前端（新建）**
- `frontend/apps/web/src/pages/Watchlist.tsx` — 自选股页面（单文件，跟随 Macro 风格）。
- `frontend/apps/web/src/pages/Watchlist.css` — 同目录样式（用 `styles/global.css` token）。

**前端（修改）**
- `frontend/apps/web/src/App.tsx` — 加 `<Route path="/watchlist">`。
- `frontend/apps/web/src/components/Layout.tsx` — `Overview` 组加「自选股」导航项（`Icons.star`）。

---

## Task 1: 后端 — 数据模型 + 分组仓储（hermetic TDD）

**Files:**
- Create: `backend/src/infra/database/watchlist/__init__.py`
- Create: `backend/src/infra/database/watchlist/models.py`
- Create: `backend/src/infra/database/watchlist/repository.py`（本任务先写分组相关方法 + 工厂骨架）
- Test: `backend/tests/infra/database/watchlist/test_repository.py`

**Interfaces:**
- Produces: `WatchlistGroup`、`WatchlistItem` 模型；`WatchlistRepository(db).list_groups() -> list[WatchlistGroup]`、`.get_group(id)`、`.create_group(name, sort_index=None)`、`.rename_group(id, name)`、`.delete_group(id) -> bool`、`.reorder_groups([ids])`、`.count_items_by_group() -> dict[int,int]`；工厂 `create_watchlist_repository(db=None)`。

- [ ] **Step 1: 建空包**

`backend/src/infra/database/watchlist/__init__.py`:
```python
```
（空文件）

- [ ] **Step 2: 写模型 `models.py`**

```python
"""自选股(分组) SQLModel 表定义。

两张表:
- WatchlistGroup: 分组(如 高股息 / 科技ETF / 港股通)
- WatchlistItem:  组内股票(symbol + 备注 + 排序)

通过 SQLModel.metadata.create_all 自动建表。
注意: 本模块必须在 main.py 启动时被 import, 否则主服务进程的
create_all 看不到这些表(参考 portfolio.models 的注册方式)。
"""
from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, UniqueConstraint


class WatchlistGroup(SQLModel, table=True):
    """自选股分组。单用户/全局(无 user_id)。"""

    __tablename__ = "watchlist_group"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    sort_index: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint("name", name="uq_watchlist_group_name"),
    )


class WatchlistItem(SQLModel, table=True):
    """组内股票。同组 (group_id, symbol) 唯一; 跨组可重复。"""

    __tablename__ = "watchlist_item"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="watchlist_group.id", index=True)
    symbol: str = Field(index=True)
    note: Optional[str] = None
    sort_index: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "group_id", "symbol", name="uq_watchlist_item_group_symbol"
        ),
    )
```

- [ ] **Step 3: 写仓储 `repository.py`（分组方法 + 工厂；成员方法在 Task 2 补）**

```python
"""自选股 repository 实现。

职责:
- 分组 CRUD + 排序 (WatchlistGroup)
- 组内成员 CRUD + 备注 + 排序 + 跨组移动 (WatchlistItem)

遵循项目 Repository Pattern: 工厂 + session_scope(参考 portfolio.repository)。
"""
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlmodel import select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

from .models import WatchlistGroup, WatchlistItem


class DuplicateWatchlistItem(Exception):
    """同组内已存在该 symbol。"""


class WatchlistRepository:
    """自选股数据访问层。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 分组 ─────────────────────────────────────────────────────

    def list_groups(self) -> list[WatchlistGroup]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(WatchlistGroup).order_by(
                        WatchlistGroup.sort_index, WatchlistGroup.id
                    )
                ).all()
            )

    def get_group(self, group_id: int) -> Optional[WatchlistGroup]:
        with self._db.session_scope() as s:
            return s.get(WatchlistGroup, group_id)

    def create_group(
        self, name: str, sort_index: Optional[int] = None
    ) -> WatchlistGroup:
        with self._db.session_scope() as s:
            if sort_index is None:
                row = s.execute(
                    text(
                        "SELECT COALESCE(MAX(sort_index), -1) "
                        "FROM watchlist_group"
                    )
                ).first()
                sort_index = (row[0] if row else -1) + 1
            now = datetime.now()
            g = WatchlistGroup(
                name=name, sort_index=sort_index, created_at=now, updated_at=now
            )
            s.add(g)
            s.commit()
            s.refresh(g)
            return g

    def rename_group(
        self, group_id: int, name: str
    ) -> Optional[WatchlistGroup]:
        with self._db.session_scope() as s:
            g = s.get(WatchlistGroup, group_id)
            if not g:
                return None
            g.name = name
            g.updated_at = datetime.now()
            s.add(g)
            s.commit()
            s.refresh(g)
            return g

    def delete_group(self, group_id: int) -> bool:
        """删除分组及其成员(显式级联, 兼容 sqlite/PG)。"""
        with self._db.session_scope() as s:
            s.execute(
                text("DELETE FROM watchlist_item WHERE group_id = :gid"),
                {"gid": group_id},
            )
            g = s.get(WatchlistGroup, group_id)
            if g:
                s.delete(g)
            s.commit()
            return True

    def reorder_groups(self, ordered_ids: list[int]) -> None:
        with self._db.session_scope() as s:
            for pos, gid in enumerate(ordered_ids):
                g = s.get(WatchlistGroup, gid)
                if g:
                    g.sort_index = pos
                    g.updated_at = datetime.now()
                    s.add(g)
            s.commit()

    def count_items_by_group(self) -> dict[int, int]:
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT group_id, COUNT(*) FROM watchlist_item "
                    "GROUP BY group_id"
                )
            ).all()
            return {r[0]: r[1] for r in rows}


# ======== 工厂函数(遵循项目约定: 单例 + 工厂) ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_watchlist_repository(
    db_connection: DBConnection | None = None,
) -> WatchlistRepository:
    """创建自选股仓储实例。"""
    return WatchlistRepository(db_connection or _get_db_connection())
```

- [ ] **Step 4: 写分组仓储测试（hermetic sqlite，镜像 `tests/infra/database/market/test_fx_rate.py` 的 `_FakeDb`）**

`backend/tests/infra/database/watchlist/test_repository.py`:
```python
"""自选股仓储测试 — sqlite in-memory，不依赖真实 PG。"""
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from src.infra.database.watchlist.models import (
    WatchlistGroup,
    WatchlistItem,
)
from src.infra.database.watchlist.repository import WatchlistRepository


class _FakeDb:
    """模拟 DBConnection，session_scope 返回 sqlite session。"""

    def __init__(self, engine):
        self._engine = engine

    @contextmanager
    def session_scope(self):
        with Session(self._engine) as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise


def _make_repo() -> WatchlistRepository:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(
        engine,
        tables=[WatchlistGroup.__table__, WatchlistItem.__table__],
    )
    return WatchlistRepository(_FakeDb(engine))


# ── 分组 ──

def test_create_and_list_groups_orders_by_sort_index():
    repo = _make_repo()
    g1 = repo.create_group(name="高股息")
    g2 = repo.create_group(name="科技ETF")
    assert g1.sort_index == 0
    assert g2.sort_index == 1
    names = [g.name for g in repo.list_groups()]
    assert names == ["高股息", "科技ETF"]


def test_rename_group():
    repo = _make_repo()
    g = repo.create_group(name="旧名")
    updated = repo.rename_group(g.id, "新名")
    assert updated is not None and updated.name == "新名"
    assert repo.get_group(g.id).name == "新名"


def test_rename_missing_group_returns_none():
    repo = _make_repo()
    assert repo.rename_group(9999, "x") is None


def test_reorder_groups():
    repo = _make_repo()
    a = repo.create_group("A")
    b = repo.create_group("B")
    c = repo.create_group("C")
    repo.reorder_groups([c.id, a.id, b.id])
    ordered = [g.id for g in repo.list_groups()]
    assert ordered == [c.id, a.id, b.id]


def test_count_items_by_group_empty():
    repo = _make_repo()
    assert repo.count_items_by_group() == {}
```

- [ ] **Step 5: 跑测试，确认通过**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
.venv/bin/python -m pytest tests/infra/database/watchlist/test_repository.py -v
```
Expected: 5 passed。

- [ ] **Step 6: 提交**

```bash
git add backend/src/infra/database/watchlist/ backend/tests/infra/database/watchlist/
git commit -m "feat(watchlist): 数据模型 + 分组仓储(sqlite 单测)"
```

---

## Task 2: 后端 — 成员仓储（CRUD + 排序 + 跨组移动 + 级联，hermetic TDD）

**Files:**
- Modify: `backend/src/infra/database/watchlist/repository.py`（追加成员方法）
- Test: `backend/tests/infra/database/watchlist/test_repository.py`（追加成员测试）

**Interfaces:**
- Consumes: `WatchlistGroup`/`WatchlistItem`（Task 1）。
- Produces: `WatchlistRepository.list_items(group_id)`、`.add_item(group_id, symbol, note=None, sort_index=None)`（重复抛 `DuplicateWatchlistItem`）、`.get_item(id)`、`.update_item_note(id, note)`、`.delete_item(id) -> bool`、`.move_item(id, to_group_id, sort_index=None)`（目标组重复抛 `DuplicateWatchlistItem`）、`.reorder_items(group_id, [ids])`。

- [ ] **Step 1: 追加成员测试（先写失败测试）**

在 `test_repository.py` 末尾追加：
```python
# ── 成员 ──

def test_add_item_auto_sort_index_and_list_ordered():
    repo = _make_repo()
    g = repo.create_group("G")
    a = repo.add_item(g.id, "sh600519")
    b = repo.add_item(g.id, "sz000001", note="观察")
    assert a.sort_index == 0 and b.sort_index == 1
    items = repo.list_items(g.id)
    assert [it.symbol for it in items] == ["sh600519", "sz000001"]
    assert items[1].note == "观察"


def test_add_item_duplicate_in_same_group_raises():
    from src.infra.database.watchlist.repository import DuplicateWatchlistItem
    repo = _make_repo()
    g = repo.create_group("G")
    repo.add_item(g.id, "sh600519")
    try:
        repo.add_item(g.id, "sh600519")
        assert False, "应抛 DuplicateWatchlistItem"
    except DuplicateWatchlistItem:
        pass


def test_same_symbol_allowed_in_different_groups():
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    repo.add_item(g1.id, "sh600519")
    repo.add_item(g2.id, "sh600519")  # 跨组不报错
    assert len(repo.list_items(g1.id)) == 1
    assert len(repo.list_items(g2.id)) == 1


def test_update_item_note():
    repo = _make_repo()
    g = repo.create_group("G")
    it = repo.add_item(g.id, "sh600519")
    updated = repo.update_item_note(it.id, "等回踩60日线")
    assert updated.note == "等回踩60日线"


def test_delete_item():
    repo = _make_repo()
    g = repo.create_group("G")
    it = repo.add_item(g.id, "sh600519")
    assert repo.delete_item(it.id) is True
    assert repo.get_item(it.id) is None
    assert repo.delete_item(9999) is False


def test_move_item_to_other_group():
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    it = repo.add_item(g1.id, "sh600519")
    moved = repo.move_item(it.id, g2.id)
    assert moved.group_id == g2.id
    assert len(repo.list_items(g1.id)) == 0
    assert len(repo.list_items(g2.id)) == 1


def test_move_item_duplicate_in_target_raises():
    from src.infra.database.watchlist.repository import DuplicateWatchlistItem
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    it = repo.add_item(g1.id, "sh600519")
    repo.add_item(g2.id, "sh600519")
    try:
        repo.move_item(it.id, g2.id)
        assert False, "应抛 DuplicateWatchlistItem"
    except DuplicateWatchlistItem:
        pass


def test_reorder_items():
    repo = _make_repo()
    g = repo.create_group("G")
    a = repo.add_item(g.id, "sh600519")
    b = repo.add_item(g.id, "sz000001")
    c = repo.add_item(g.id, "sh510300")
    repo.reorder_items(g.id, [c.id, a.id, b.id])
    assert [it.id for it in repo.list_items(g.id)] == [c.id, a.id, b.id]


def test_delete_group_cascades_items():
    repo = _make_repo()
    g = repo.create_group("G")
    repo.add_item(g.id, "sh600519")
    repo.add_item(g.id, "sz000001")
    assert repo.delete_group(g.id) is True
    assert repo.get_group(g.id) is None
    assert repo.list_items(g.id) == []
    # count 不应残留
    assert repo.count_items_by_group() == {}


def test_count_items_by_group():
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    repo.add_item(g1.id, "sh600519")
    repo.add_item(g1.id, "sz000001")
    repo.add_item(g2.id, "sh510300")
    assert repo.count_items_by_group() == {g1.id: 2, g2.id: 1}
```

- [ ] **Step 2: 跑测试，确认新测试失败**

```bash
.venv/bin/python -m pytest tests/infra/database/watchlist/test_repository.py -v
```
Expected: 新增成员测试 FAIL（`AttributeError: ...has no attribute 'add_item'` 之类）。

- [ ] **Step 3: 在 `WatchlistRepository` 追加成员方法**

在 `count_items_by_group` 方法之后、`# ======== 工厂函数` 之前插入：
```python
    # ── 成员 ─────────────────────────────────────────────────────

    def list_items(self, group_id: int) -> list[WatchlistItem]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(WatchlistItem)
                    .where(WatchlistItem.group_id == group_id)
                    .order_by(WatchlistItem.sort_index, WatchlistItem.id)
                ).all()
            )

    def add_item(
        self,
        group_id: int,
        symbol: str,
        note: Optional[str] = None,
        sort_index: Optional[int] = None,
    ) -> WatchlistItem:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(WatchlistItem).where(
                    WatchlistItem.group_id == group_id,
                    WatchlistItem.symbol == symbol,
                )
            ).first()
            if existing:
                raise DuplicateWatchlistItem(symbol)
            if sort_index is None:
                row = s.execute(
                    text(
                        "SELECT COALESCE(MAX(sort_index), -1) "
                        "FROM watchlist_item WHERE group_id = :gid"
                    ),
                    {"gid": group_id},
                ).first()
                sort_index = (row[0] if row else -1) + 1
            now = datetime.now()
            it = WatchlistItem(
                group_id=group_id,
                symbol=symbol,
                note=note,
                sort_index=sort_index,
                created_at=now,
                updated_at=now,
            )
            s.add(it)
            s.commit()
            s.refresh(it)
            return it

    def get_item(self, item_id: int) -> Optional[WatchlistItem]:
        with self._db.session_scope() as s:
            return s.get(WatchlistItem, item_id)

    def update_item_note(
        self, item_id: int, note: Optional[str]
    ) -> Optional[WatchlistItem]:
        with self._db.session_scope() as s:
            it = s.get(WatchlistItem, item_id)
            if not it:
                return None
            it.note = note
            it.updated_at = datetime.now()
            s.add(it)
            s.commit()
            s.refresh(it)
            return it

    def delete_item(self, item_id: int) -> bool:
        with self._db.session_scope() as s:
            it = s.get(WatchlistItem, item_id)
            if it:
                s.delete(it)
                s.commit()
                return True
            return False

    def move_item(
        self,
        item_id: int,
        to_group_id: int,
        sort_index: Optional[int] = None,
    ) -> Optional[WatchlistItem]:
        with self._db.session_scope() as s:
            it = s.get(WatchlistItem, item_id)
            if not it:
                return None
            dup = s.exec(
                select(WatchlistItem).where(
                    WatchlistItem.group_id == to_group_id,
                    WatchlistItem.symbol == it.symbol,
                    WatchlistItem.id != item_id,
                )
            ).first()
            if dup:
                raise DuplicateWatchlistItem(it.symbol)
            it.group_id = to_group_id
            if sort_index is None:
                row = s.execute(
                    text(
                        "SELECT COALESCE(MAX(sort_index), -1) "
                        "FROM watchlist_item WHERE group_id = :gid"
                    ),
                    {"gid": to_group_id},
                ).first()
                sort_index = (row[0] if row else -1) + 1
            it.sort_index = sort_index
            it.updated_at = datetime.now()
            s.add(it)
            s.commit()
            s.refresh(it)
            return it

    def reorder_items(self, group_id: int, ordered_ids: list[int]) -> None:
        with self._db.session_scope() as s:
            for pos, iid in enumerate(ordered_ids):
                it = s.get(WatchlistItem, iid)
                if it:
                    it.sort_index = pos
                    it.updated_at = datetime.now()
                    s.add(it)
            s.commit()
```

- [ ] **Step 4: 跑全部仓储测试，确认通过**

```bash
.venv/bin/python -m pytest tests/infra/database/watchlist/test_repository.py -v
```
Expected: 全部 passed（分组 5 + 成员 11 = 16）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/infra/database/watchlist/repository.py backend/tests/infra/database/watchlist/test_repository.py
git commit -m "feat(watchlist): 成员仓储 CRUD/排序/跨组移动/级联(sqlite 单测)"
```

---

## Task 3: 后端 — handler + router + main.py 装配（集成测试打本地 PG）

**Files:**
- Create: `backend/src/api/handler/watchlist_handler.py`
- Create: `backend/src/api/router/watchlist_router.py`
- Modify: `backend/main.py`（import 模型 + 注册路由）
- Test: `backend/tests/api/test_watchlist_router.py`（Pattern B：`TestClient(create_app())` 打本地 PG，自带清理）

**Interfaces:**
- Consumes: `WatchlistRepository` 全部方法（Task 1/2）。
- Produces: `/api/v1/watchlist/*` 端点（见下），返回 `{code,msg,data}`。

**端点契约：**
| 方法 | 路径 | body | 返回 data |
|---|---|---|---|
| GET | `/watchlist/groups` | — | `[{id,name,sort_index,item_count}]` |
| POST | `/watchlist/groups` | `{name}` | `{id,name,sort_index,item_count}` |
| PUT | `/watchlist/groups/order` | `{ids:[...]}` | `{ids}` |
| PUT | `/watchlist/groups/{id}` | `{name}` | `{id,name,sort_index,item_count}` |
| DELETE | `/watchlist/groups/{id}` | — | `{id,deleted}` |
| GET | `/watchlist/groups/{id}/items` | — | `[{id,group_id,symbol,note,sort_index}]` |
| POST | `/watchlist/groups/{id}/items` | `{symbol,note?}` | `{id,group_id,symbol,note,sort_index}` |
| PUT | `/watchlist/groups/{id}/items/order` | `{ids:[...]}` | `{ids}` |
| DELETE | `/watchlist/items/{item_id}` | — | `{id,deleted}` |
| PUT | `/watchlist/items/{item_id}` | `{note}` | `{id,group_id,symbol,note,sort_index}` |
| POST | `/watchlist/items/move` | `{item_id,to_group_id,sort_index?}` | `{id,group_id,symbol,note,sort_index}` |

> **路由顺序陷阱**：FastAPI 按声明顺序匹配。`PUT /groups/order` 必须声明在 `PUT /groups/{group_id}` **之前**，否则 `order` 会被当成 `group_id`（int 转换 422）。下面 router 已按此顺序排。

- [ ] **Step 1: 写 handler**

`backend/src/api/handler/watchlist_handler.py`:
```python
"""自选股(分组) API handler。

遵循项目约定:
- repository 在函数体内延迟 import + 工厂创建
- 返回 responses.success(data) / responses.fail(msg=...)
"""
from typing import Any

from src.pkg import responses


def _repo():
    from src.infra.database.watchlist.repository import (
        create_watchlist_repository,
    )
    return create_watchlist_repository()


def _group_dict(g, item_count: int = 0) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "sort_index": g.sort_index,
        "item_count": item_count,
    }


def _item_dict(it) -> dict:
    return {
        "id": it.id,
        "group_id": it.group_id,
        "symbol": it.symbol,
        "note": it.note,
        "sort_index": it.sort_index,
    }


# ── 分组 ──

def list_groups() -> Any:
    repo = _repo()
    groups = repo.list_groups()
    counts = repo.count_items_by_group()
    return responses.success(
        [_group_dict(g, counts.get(g.id, 0)) for g in groups]
    )


def create_group(body: dict) -> Any:
    name = (body.get("name") or "").strip()
    if not name:
        return responses.fail(msg="缺少 name")
    repo = _repo()
    if any(g.name == name for g in repo.list_groups()):
        return responses.fail(msg="分组名已存在")
    g = repo.create_group(name=name)
    return responses.success(_group_dict(g, 0))


def update_group(group_id: int, body: dict) -> Any:
    name = (body.get("name") or "").strip()
    if not name:
        return responses.fail(msg="缺少 name")
    repo = _repo()
    if any(g.id != group_id and g.name == name for g in repo.list_groups()):
        return responses.fail(msg="分组名已存在")
    g = repo.rename_group(group_id, name)
    if not g:
        return responses.fail(msg="分组不存在")
    counts = repo.count_items_by_group()
    return responses.success(_group_dict(g, counts.get(g.id, 0)))


def delete_group(group_id: int) -> Any:
    repo = _repo()
    repo.delete_group(group_id)
    return responses.success({"id": group_id, "deleted": True})


def reorder_groups(body: dict) -> Any:
    ids = body.get("ids") or []
    if not isinstance(ids, list):
        return responses.fail(msg="ids 必须为数组")
    repo = _repo()
    repo.reorder_groups([int(i) for i in ids])
    return responses.success({"ids": ids})


# ── 成员 ──

def list_items(group_id: int) -> Any:
    repo = _repo()
    return responses.success([_item_dict(it) for it in repo.list_items(group_id)])


def add_item(group_id: int, body: dict) -> Any:
    symbol = (body.get("symbol") or "").strip()
    if not symbol:
        return responses.fail(msg="缺少 symbol")
    note = (body.get("note") or "").strip() or None
    repo = _repo()
    if repo.get_group(group_id) is None:
        return responses.fail(msg="分组不存在")
    from src.infra.database.watchlist.repository import DuplicateWatchlistItem
    try:
        it = repo.add_item(group_id=group_id, symbol=symbol, note=note)
    except DuplicateWatchlistItem:
        return responses.fail(msg="该股票已在分组内")
    return responses.success(_item_dict(it))


def delete_item(item_id: int) -> Any:
    repo = _repo()
    ok = repo.delete_item(item_id)
    if not ok:
        return responses.fail(msg="成员不存在")
    return responses.success({"id": item_id, "deleted": True})


def update_item(item_id: int, body: dict) -> Any:
    note = body.get("note")
    note = note.strip() if isinstance(note, str) else note
    repo = _repo()
    it = repo.update_item_note(item_id, note if note else None)
    if not it:
        return responses.fail(msg="成员不存在")
    return responses.success(_item_dict(it))


def reorder_items(group_id: int, body: dict) -> Any:
    ids = body.get("ids") or []
    if not isinstance(ids, list):
        return responses.fail(msg="ids 必须为数组")
    repo = _repo()
    repo.reorder_items(group_id, [int(i) for i in ids])
    return responses.success({"ids": ids})


def move_item(body: dict) -> Any:
    item_id = body.get("item_id")
    to_group_id = body.get("to_group_id")
    if item_id is None or to_group_id is None:
        return responses.fail(msg="缺少 item_id 或 to_group_id")
    sort_index = body.get("sort_index")
    repo = _repo()
    from src.infra.database.watchlist.repository import DuplicateWatchlistItem
    try:
        it = repo.move_item(
            int(item_id),
            int(to_group_id),
            int(sort_index) if sort_index is not None else None,
        )
    except DuplicateWatchlistItem:
        return responses.fail(msg="目标分组已存在该股票")
    if not it:
        return responses.fail(msg="成员不存在")
    return responses.success(_item_dict(it))
```

- [ ] **Step 2: 写 router（注意路由顺序）**

`backend/src/api/router/watchlist_router.py`:
```python
"""自选股(分组) API — 分组管理 + 组内成员管理。"""
from fastapi import APIRouter

from src.api.handler.watchlist_handler import (
    add_item,
    create_group,
    delete_group,
    delete_item,
    list_groups,
    list_items,
    move_item,
    reorder_groups,
    reorder_items,
    update_group,
    update_item,
)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("/groups")
def _list_groups():
    return list_groups()


@router.post("/groups")
def _create_group(body: dict):
    return create_group(body)


# 注意: /groups/order 必须在 /groups/{group_id} 之前声明
@router.put("/groups/order")
def _reorder_groups(body: dict):
    return reorder_groups(body)


@router.put("/groups/{group_id}")
def _update_group(group_id: int, body: dict):
    return update_group(group_id, body)


@router.delete("/groups/{group_id}")
def _delete_group(group_id: int):
    return delete_group(group_id)


@router.get("/groups/{group_id}/items")
def _list_items(group_id: int):
    return list_items(group_id)


@router.post("/groups/{group_id}/items")
def _add_item(group_id: int, body: dict):
    return add_item(group_id, body)


@router.put("/groups/{group_id}/items/order")
def _reorder_items(group_id: int, body: dict):
    return reorder_items(group_id, body)


@router.delete("/items/{item_id}")
def _delete_item(item_id: int):
    return delete_item(item_id)


@router.put("/items/{item_id}")
def _update_item(item_id: int, body: dict):
    return update_item(item_id, body)


@router.post("/items/move")
def _move_item(body: dict):
    return move_item(body)
```

- [ ] **Step 3: 装配到 `main.py`**

三处编辑（用 Edit 工具，按现有 import/注册区附近锚点）：

(a) 路由 import —— 紧跟 `perm_portfolio_router` 的 import 那一行之后加：
```python
from src.api.router.watchlist_router import router as watchlist_router
```

(b) `lifespan` 里 portfolio 模型 import 块之后，加 watchlist 模型 import（让 `create_all` 建表）：
```python
        # Import watchlist models so create_all picks up watchlist_group /
        # watchlist_item tables on first connection.
        from src.infra.database.watchlist.models import (  # noqa: F401
            WatchlistGroup,
            WatchlistItem,
        )
```

(c) 路由注册区（`app.include_router(...)` 列表里，紧跟 perm_portfolio 那行之后）加：
```python
    app.include_router(watchlist_router, prefix="/api/v1")  # /api/v1/watchlist
```

- [ ] **Step 4: 写集成测试（Pattern B，自带清理；需要本地 PG）**

`backend/tests/api/test_watchlist_router.py`:
```python
"""自选股 router 集成测试 — TestClient 打本地 PG，自带清理。

依赖本地 Postgres(见 tests/conftest.py 默认 db_dsn)。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app
    return TestClient(create_app())


def _cleanup(client, prefix="/api/v1/watchlist"):
    r = client.get(f"{prefix}/groups")
    for g in r.json().get("data", []) or []:
        client.delete(f"{prefix}/groups/{g['id']}")


class TestWatchlistRouter:
    PREFIX = "/api/v1/watchlist"

    def test_group_and_item_lifecycle(self, client):
        try:
            # 建分组
            r = client.post(f"{self.PREFIX}/groups", json={"name": "TS_G1"})
            assert r.status_code == 200 and r.json()["code"] == 0, r.text
            gid = r.json()["data"]["id"]

            # 重名拒绝
            r = client.post(f"{self.PREFIX}/groups", json={"name": "TS_G1"})
            assert r.json()["code"] != 0

            # 列分组带 item_count
            r = client.get(f"{self.PREFIX}/groups")
            g = next(x for x in r.json()["data"] if x["id"] == gid)
            assert g["item_count"] == 0

            # 加成员
            r = client.post(
                f"{self.PREFIX}/groups/{gid}/items",
                json={"symbol": "sh600519", "note": "x"},
            )
            assert r.json()["code"] == 0
            iid = r.json()["data"]["id"]

            # 重复加同 symbol 拒绝
            r = client.post(
                f"{self.PREFIX}/groups/{gid}/items",
                json={"symbol": "sh600519"},
            )
            assert r.json()["code"] != 0

            # 改备注
            r = client.put(f"{self.PREFIX}/items/{iid}", json={"note": "y"})
            assert r.json()["code"] == 0 and r.json()["data"]["note"] == "y"

            # 列成员
            r = client.get(f"{self.PREFIX}/groups/{gid}/items")
            assert len(r.json()["data"]) == 1

            # 跨组移动
            r = client.post(f"{self.PREFIX}/groups", json={"name": "TS_G2"})
            gid2 = r.json()["data"]["id"]
            r = client.post(
                f"{self.PREFIX}/items/move",
                json={"item_id": iid, "to_group_id": gid2},
            )
            assert r.json()["code"] == 0 and r.json()["data"]["group_id"] == gid2

            # 删分组级联
            client.delete(f"{self.PREFIX}/groups/{gid2}")
            r = client.get(f"{self.PREFIX}/groups/{gid2}/items")
            assert r.json()["data"] == []
        finally:
            _cleanup(client)
```

- [ ] **Step 5: 跑集成测试**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
.venv/bin/python -m pytest tests/api/test_watchlist_router.py -v
```
Expected: 1 passed（需本地 PG 在跑）。若 PG 不可用，先确保仓储单测（Task 1/2）通过即可；集成测试待 PG 可用时再验。

- [ ] **Step 6: 提交**

```bash
git add backend/src/api/handler/watchlist_handler.py backend/src/api/router/watchlist_router.py backend/main.py backend/tests/api/test_watchlist_router.py
git commit -m "feat(watchlist): handler+router+main 装配(集成测试)"
```

---

## Task 4: 后端 — 通用批量报价 `POST /market/quotes`

**Files:**
- Modify: `backend/src/api/router/market_router.py`（加端点 + SQL 常量 + `_to_float`）
- Test: `backend/tests/api/test_market_quotes.py`（Pattern B，打本地 PG）

**Interfaces:**
- Produces: `POST /api/v1/market/quotes`，body `{symbols:[...]}`，返回 `{"code":0,"msg":"ok","data":[{"symbol","name","price","change","change_pct","pe","pe_ttm","pb","dv_ratio","dv_ttm","total_mv"}]}`。缺失字段 `null`；无行情的 symbol 略过。遵循 market_router 本地风格（psycopg2 + 原始 dict 返回 + `HTTPException`）。

> 说明：不复用 `_latest_sql`（它用 `.format()` 拼 `where`，无法安全参数化用户 symbol 列表）。这里写一条干净、参数化（`symbol = ANY(%s)`）的窗口查询。

- [ ] **Step 1: 在 `market_router.py` 加 SQL 常量 + helper + 端点**

在文件中（建议紧跟 `search` 端点之后，`_latest_sql` 之前的位置）插入：

```python
# ── 批量报价(自选股等复用) ───────────────────────────────────────

_QUOTES_OHLCV_SQL = """
    WITH ranked AS (
        SELECT symbol, close_, trade_date,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn
        FROM stock_ohlcv
        WHERE symbol = ANY(%s) AND trade_date >= current_date - interval '40 days'
    )
    SELECT t.symbol, t.close_, p.close_ AS prev,
           COALESCE(i.name, t.symbol) AS name
    FROM ranked t
    LEFT JOIN ranked p ON p.symbol = t.symbol AND p.rn = 2
    LEFT JOIN stock_info i ON i.symbol = t.symbol
    WHERE t.rn = 1
"""

_QUOTES_VAL_SQL = """
    WITH ranked AS (
        SELECT symbol, pe, pe_ttm, pb, dv_ratio, dv_ttm, total_mv,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn
        FROM stock_valuation
        WHERE symbol = ANY(%s)
    )
    SELECT symbol, pe, pe_ttm, pb, dv_ratio, dv_ttm, total_mv
    FROM ranked WHERE rn = 1
"""


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


@router.post("/quotes")
def batch_quotes(body: dict):
    """批量查询多个 symbol 的最新行情 + 估值。

    body: {"symbols": ["sh600519", ...]}
    缺失数据返回 null; 无行情的 symbol 从结果略过。
    """
    symbols = body.get("symbols") or []
    if not isinstance(symbols, list) or not symbols:
        return {"code": 0, "msg": "ok", "data": []}
    # 去重保序
    seen = set()
    uniq = []
    for s in symbols:
        s = str(s)
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    try:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(_QUOTES_OHLCV_SQL, (uniq,))
                ohlcv = {r["symbol"]: dict(r) for r in cur.fetchall()}
                cur.execute(_QUOTES_VAL_SQL, (uniq,))
                val = {r["symbol"]: dict(r) for r in cur.fetchall()}
            data = []
            for s in uniq:
                o = ohlcv.get(s)
                if not o:
                    continue  # 无行情略过
                close = float(o.get("close_") or 0)
                prev = o.get("prev")
                prev = float(prev) if prev is not None else None
                change = round(close - prev, 4) if prev is not None else None
                change_pct = (
                    round((close / prev - 1) * 100, 2) if prev else 0.0
                )
                v = val.get(s, {})
                data.append(
                    {
                        "symbol": s,
                        "name": o.get("name") or s,
                        "price": close,
                        "change": change,
                        "change_pct": change_pct,
                        "pe": _to_float(v.get("pe")),
                        "pe_ttm": _to_float(v.get("pe_ttm")),
                        "pb": _to_float(v.get("pb")),
                        "dv_ratio": _to_float(v.get("dv_ratio")),
                        "dv_ttm": _to_float(v.get("dv_ttm")),
                        "total_mv": _to_float(v.get("total_mv")),
                    }
                )
            return {"code": 0, "msg": "ok", "data": data}
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

> 前置确认：`market_router.py` 顶部已 import `get_conn`、`RealDictCursor`、`HTTPException`、`router`（`search_symbols`/`search` 端点已用到，无需新增 import）。若 `get_conn` 未在该文件定义而是 import 来的，同样可用。

- [ ] **Step 2: 写集成测试（需本地 PG 且有 sh600519 数据）**

`backend/tests/api/test_market_quotes.py`:
```python
"""POST /market/quotes 集成测试(本地 PG)。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app
    return TestClient(create_app())


class TestMarketQuotes:
    def test_known_and_unknown_symbols(self, client):
        r = client.post(
            "/api/v1/market/quotes",
            json={"symbols": ["sh600519", "THIS_DOES_NOT_EXIST_xxx"]},
        )
        assert r.status_code == 200
        j = r.json()
        assert j["code"] == 0
        data = j["data"]
        syms = {d["symbol"] for d in data}
        assert "sh600519" in syms
        assert "THIS_DOES_NOT_EXIST_xxx" not in syms  # 无行情略过
        row = next(d for d in data if d["symbol"] == "sh600519")
        assert isinstance(row["price"], (int, float))
        assert isinstance(row["change_pct"], (int, float))
        # 估值字段允许为 null, 但键必须存在
        for k in ("pe", "pb", "dv_ttm", "total_mv"):
            assert k in row

    def test_empty_symbols_returns_empty(self, client):
        r = client.post("/api/v1/market/quotes", json={"symbols": []})
        assert r.json() == {"code": 0, "msg": "ok", "data": []}
```

- [ ] **Step 3: 跑测试**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
.venv/bin/python -m pytest tests/api/test_market_quotes.py -v
```
Expected: 2 passed（需本地 PG + 已回填 sh600519 行情/估值）。

- [ ] **Step 4: 提交**

```bash
git add backend/src/api/router/market_router.py backend/tests/api/test_market_quotes.py
git commit -m "feat(market): 通用批量报价 POST /market/quotes(行情+估值)"
```

---

## Task 5: 前端 — 页面骨架 + 分组管理（创建/改名/删除/排序/Tabs）+ 路由/导航/CSS

**Files:**
- Create: `frontend/apps/web/src/pages/Watchlist.tsx`
- Create: `frontend/apps/web/src/pages/Watchlist.css`
- Modify: `frontend/apps/web/src/App.tsx`（加 route）
- Modify: `frontend/apps/web/src/components/Layout.tsx`（加导航项）

**Interfaces:**
- Consumes: `/api/v1/watchlist/groups` 系列（Task 3）。本任务先实现分组管理 + 内容区占位；股票层（表格/报价/增删/拖拽/移动）在 Task 6 填充占位块。
- Produces: `/watchlist` 页面，可创建/改名/删除/排序分组并切换。

> 验证无前端测试框架：每个 Step 用 `pnpm --filter web build`（在 `frontend/` 下）做 TS 编译检查，并在 `pnpm --filter web dev` 下手动冒烟。

- [ ] **Step 1: 写 `Watchlist.tsx`（分组管理完整版；股票内容区留 `STOCKS_CONTENT_PLACEHOLDER` 占位，Task 6 替换）**

`frontend/apps/web/src/pages/Watchlist.tsx`:
```tsx
import React, {useCallback, useEffect, useState} from 'react';
import {getApiBase} from '../lib/api';
import {
  Button,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  ModalTitle,
  Tabs,
  Tab,
  TabList,
} from '@ytrader/common-components';
import './Watchlist.css';

const API_BASE = getApiBase();

interface Group {
  id: number;
  name: string;
  sort_index: number;
  item_count: number;
}
interface Item {
  id: number;
  group_id: number;
  symbol: string;
  note: string | null;
  sort_index: number;
}

// ── fetch helpers ({code,msg,data}, code===0 成功) ──
const jget = (u: string) => fetch(u).then((r) => r.json());
const jpost = (u: string, b?: unknown) =>
  fetch(u, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: b ? JSON.stringify(b) : undefined,
  }).then((r) => r.json());
const jput = (u: string, b: unknown) =>
  fetch(u, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(b),
  }).then((r) => r.json());
const jdel = (u: string) => fetch(u, {method: 'DELETE'}).then((r) => r.json());

export const Watchlist: React.FC = () => {
  const [groups, setGroups] = useState<Group[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // 分组管理弹窗
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [renaming, setRenaming] = useState<Group | null>(null);
  const [renameVal, setRenameVal] = useState('');
  const [deleting, setDeleting] = useState<Group | null>(null);

  const fetchGroups = useCallback(async () => {
    setLoading(true);
    try {
      const j = await jget(`${API_BASE}/watchlist/groups`);
      const list: Group[] = j.code === 0 ? j.data || [] : [];
      setGroups(list);
      setActiveId((cur) => {
        if (cur != null && list.some((g) => g.id === cur)) return cur;
        return list.length ? list[0].id : null;
      });
      setErr(j.code === 0 ? null : j.msg || '加载分组失败');
    } catch (e) {
      setErr('加载分组失败：' + e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  const activeGroup = groups.find((g) => g.id === activeId) || null;

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    const j = await jpost(`${API_BASE}/watchlist/groups`, {name});
    if (j.code === 0) {
      setCreating(false);
      setNewName('');
      await fetchGroups();
      setActiveId(j.data.id);
    } else {
      alert(j.msg || '创建失败');
    }
  };

  const handleRename = async () => {
    if (!renaming) return;
    const name = renameVal.trim();
    if (!name) return;
    const j = await jput(`${API_BASE}/watchlist/groups/${renaming.id}`, {name});
    if (j.code === 0) {
      setRenaming(null);
      await fetchGroups();
    } else {
      alert(j.msg || '改名失败');
    }
  };

  const handleDelete = async () => {
    if (!deleting) return;
    const j = await jdel(`${API_BASE}/watchlist/groups/${deleting.id}`);
    if (j.code === 0) {
      setDeleting(null);
      await fetchGroups();
    } else {
      alert(j.msg || '删除失败');
    }
  };

  return (
    <div className="watchlist">
      <header className="watchlist__header">
        <h1 className="watchlist__title">自选股</h1>
      </header>

      {/* 分组 Tabs + 操作 */}
      <div className="watchlist__tabs">
        {groups.length === 0 && !loading ? (
          <span className="watchlist__tabs-empty">还没有分组，点「+ 新建分组」</span>
        ) : (
          <Tabs
            value={activeId != null ? String(activeId) : undefined}
            onChange={(v) => setActiveId(Number(v))}
          >
            <TabList>
              {groups.map((g) => (
                <Tab key={g.id} value={String(g.id)}>
                  {g.name} <span className="watchlist__count">({g.item_count})</span>
                </Tab>
              ))}
            </TabList>
          </Tabs>
        )}
        <div className="watchlist__tabs-actions">
          <Button size="sm" variant="ghost" onClick={() => setCreating(true)}>
            + 新建分组
          </Button>
          {activeGroup && (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setRenaming(activeGroup);
                  setRenameVal(activeGroup.name);
                }}
              >
                改名
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDeleting(activeGroup)}
              >
                删除
              </Button>
            </>
          )}
        </div>
      </div>

      {err && <div className="watchlist__error">{err}</div>}

      {/* 内容区：分组管理先行；股票层在 Task 6 填充 */}
      {/* STOCKS_CONTENT_PLACEHOLDER */}
      {!activeGroup ? (
        <div className="watchlist__empty">
          {loading ? '加载中…' : '选择或新建一个分组开始管理自选股。'}
        </div>
      ) : (
        <div className="watchlist__empty">（股票内容区待实现）</div>
      )}

      {/* 新建分组 */}
      <Modal open={creating} onClose={() => setCreating(false)} size="sm">
        <ModalHeader>
          <ModalTitle>新建分组</ModalTitle>
        </ModalHeader>
        <ModalBody>
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="如：高股息 / 科技ETF / 港股通"
            autoFocus
          />
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" onClick={() => setCreating(false)}>
            取消
          </Button>
          <Button variant="primary" onClick={handleCreate}>
            创建
          </Button>
        </ModalFooter>
      </Modal>

      {/* 改名 */}
      <Modal open={!!renaming} onClose={() => setRenaming(null)} size="sm">
        <ModalHeader>
          <ModalTitle>重命名分组</ModalTitle>
        </ModalHeader>
        <ModalBody>
          <Input
            value={renameVal}
            onChange={(e) => setRenameVal(e.target.value)}
            autoFocus
          />
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" onClick={() => setRenaming(null)}>
            取消
          </Button>
          <Button variant="primary" onClick={handleRename}>
            保存
          </Button>
        </ModalFooter>
      </Modal>

      {/* 删除确认 */}
      <Modal open={!!deleting} onClose={() => setDeleting(null)} size="sm">
        <ModalHeader>
          <ModalTitle>删除分组</ModalTitle>
        </ModalHeader>
        <ModalBody>
          确定删除分组「{deleting?.name}」？组内所有股票会一并删除，且不可恢复。
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" onClick={() => setDeleting(null)}>
            取消
          </Button>
          <Button variant="danger" onClick={handleDelete}>
            删除
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};
```

- [ ] **Step 2: 写 `Watchlist.css`（基础布局 + 占位样式；Task 6 追加表格等）**

`frontend/apps/web/src/pages/Watchlist.css`:
```css
.watchlist {
  padding: var(--space-6);
  max-width: 1200px;
  margin: 0 auto;
}
.watchlist__header {
  margin-bottom: var(--space-4);
}
.watchlist__title {
  font-size: var(--text-2xl);
  font-weight: 600;
  color: var(--color-text);
  margin: 0;
}
.watchlist__tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  border-bottom: 1px solid var(--color-border);
  padding-bottom: var(--space-2);
}
.watchlist__tabs-actions {
  display: flex;
  gap: var(--space-2);
}
.watchlist__count {
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}
.watchlist__tabs-empty {
  color: var(--color-text-tertiary);
  font-size: var(--text-sm);
}
.watchlist__error {
  color: var(--color-danger);
  background: rgba(255, 69, 58, 0.1);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  margin: var(--space-3) 0;
}
.watchlist__empty {
  color: var(--color-text-tertiary);
  text-align: center;
  padding: var(--space-16) var(--space-4);
  font-size: var(--text-sm);
}
```

- [ ] **Step 3: 接路由 `App.tsx`**

在 import 区（其它 `import {X} from './pages/X';` 附近）加：
```tsx
import {Watchlist} from './pages/Watchlist';
```
在 `<Routes>` 内（如 `<Route path="/macro" .../>` 之后）加：
```tsx
          <Route path="/watchlist" element={<Watchlist />} />
```

- [ ] **Step 4: 接导航 `Layout.tsx`**

在 `Overview` 组 `items` 里（如 `{path: '/macro', ...}` 之后）加：
```tsx
      {path: '/watchlist', label: '自选股', icon: Icon.star},
```

- [ ] **Step 5: 构建 + 冒烟**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend
pnpm --filter web build
```
Expected: 构建通过（无 TS 错误）。然后 `pnpm --filter web dev` 打开 `/watchlist`：能新建/改名/删除分组，Tab 切换，侧栏「自选股」高亮。

- [ ] **Step 6: 提交**

```bash
git add frontend/apps/web/src/pages/Watchlist.tsx frontend/apps/web/src/pages/Watchlist.css frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(watchlist): 前端页面骨架 + 分组管理(Tabs/CRUD/路由/导航)"
```

---

## Task 6: 前端 — 股票层（表格 + 批量报价 + 估值 + 概览条 + 轮询 + 增删/备注/拖拽/跨组移动）

**Files:**
- Modify: `frontend/apps/web/src/pages/Watchlist.tsx`（替换 `STOCKS_CONTENT_PLACEHOLDER` 占位块为股票层实现，并补 import 与 state）
- Modify: `frontend/apps/web/src/pages/Watchlist.css`（追加表格/概览条/添加栏/拖拽样式）

**Interfaces:**
- Consumes: `/watchlist/groups/{id}/items`、`/watchlist/items/*`、`/market/quotes`（Task 3/4）；复用 `StockSelect`（`components/MarketPage/StockSelect.tsx`，props `{value, onChange, market?}`）；`Table/PnlBadge`（`@ytrader/common-components`）。

- [ ] **Step 1: 在 `Watchlist.tsx` 顶部补 import + 类型 + 格式化 helper**

把文件顶部 import 区改为（增加 `useMemo/useRef`、`Table` 系列、`PnlBadge`、`StockSelect`）：
```tsx
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {getApiBase} from '../lib/api';
import {StockSelect} from '../components/MarketPage/StockSelect';
import {
  Button,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  ModalTitle,
  Tabs,
  Tab,
  TabList,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableHeaderCell,
  TableCell,
  PnlBadge,
} from '@ytrader/common-components';
import './Watchlist.css';
```

在 `Item` 接口之后追加 `Quote` 类型与格式化函数：
```tsx
interface Quote {
  symbol: string;
  name: string;
  price: number;
  change: number | null;
  change_pct: number;
  pe: number | null;
  pe_ttm: number | null;
  pb: number | null;
  dv_ratio: number | null;
  dv_ttm: number | null;
  total_mv: number | null;
}

const nf = (v: number | null | undefined, d = 2) =>
  v == null || Number.isNaN(v) ? '—' : v.toFixed(d);
const fmtMv = (v: number | null) => {
  if (v == null) return '—';
  if (v >= 1e12) return (v / 1e12).toFixed(2) + '万亿';
  return (v / 1e8).toFixed(2) + '亿';
};
```

- [ ] **Step 2: 在组件内补股票层 state + 数据获取（在 `activeGroup` 定义之后）**

```tsx
  const [items, setItems] = useState<Item[]>([]);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [itemsLoading, setItemsLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 添加股票
  const [addSym, setAddSym] = useState('');
  const [addNote, setAddNote] = useState('');
  // 备注 inline 编辑
  const [editNoteId, setEditNoteId] = useState<number | null>(null);
  const [editNoteVal, setEditNoteVal] = useState('');
  // 跨组移动
  const [movingItem, setMovingItem] = useState<Item | null>(null);
  // 拖拽排序
  const dragId = useRef<number | null>(null);

  const fetchQuotes = useCallback(async (syms: string[]) => {
    if (!syms.length) {
      setQuotes({});
      return;
    }
    try {
      const j = await jpost(`${API_BASE}/market/quotes`, {symbols: syms});
      if (j.code === 0) {
        const m: Record<string, Quote> = {};
        for (const q of j.data || []) m[q.symbol] = q;
        setQuotes(m);
      }
    } catch {
      /* 轮询失败静默, 保留上次数据 */
    }
  }, []);

  const fetchItems = useCallback(
    async (gid: number) => {
      setItemsLoading(true);
      try {
        const j = await jget(`${API_BASE}/watchlist/groups/${gid}/items`);
        const list: Item[] = j.code === 0 ? j.data || [] : [];
        setItems(list);
        await fetchQuotes(list.map((it) => it.symbol));
      } finally {
        setItemsLoading(false);
      }
    },
    [fetchQuotes],
  );

  // 切组时拉成员 + 报价
  useEffect(() => {
    setItems([]);
    setQuotes({});
    if (activeId != null) fetchItems(activeId);
  }, [activeId, fetchItems]);

  // 30s 轮询(仅当前组), 页面隐藏时暂停
  useEffect(() => {
    if (activeId == null) return;
    const tick = () => {
      if (document.hidden) return;
      fetchQuotes(items.map((it) => it.symbol));
    };
    pollRef.current = setInterval(tick, 30000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [activeId, items, fetchQuotes]);

  const handleAdd = async () => {
    const symbol = addSym.trim();
    if (!symbol || activeId == null) return;
    const j = await jpost(`${API_BASE}/watchlist/groups/${activeId}/items`, {
      symbol,
      note: addNote.trim() || undefined,
    });
    if (j.code === 0) {
      setAddSym('');
      setAddNote('');
      await fetchItems(activeId);
      await fetchGroups(); // 刷新 Tab 上的 item_count
    } else {
      alert(j.msg || '添加失败');
    }
  };

  const handleRemove = async (it: Item) => {
    if (activeId == null) return;
    const j = await jdel(`${API_BASE}/watchlist/items/${it.id}`);
    if (j.code === 0) {
      await fetchItems(activeId);
      await fetchGroups();
    } else {
      alert(j.msg || '删除失败');
    }
  };

  const saveNote = async (it: Item) => {
    const j = await jput(`${API_BASE}/watchlist/items/${it.id}`, {
      note: editNoteVal.trim(),
    });
    setEditNoteId(null);
    if (j.code === 0) {
      setItems((prev) =>
        prev.map((x) =>
          x.id === it.id ? {...x, note: editNoteVal.trim() || null} : x,
        ),
      );
    }
  };

  const handleMove = async (toGroupId: number) => {
    if (!movingItem) return;
    const j = await jpost(`${API_BASE}/watchlist/items/move`, {
      item_id: movingItem.id,
      to_group_id: toGroupId,
    });
    setMovingItem(null);
    if (j.code === 0) {
      if (activeId != null) await fetchItems(activeId);
      await fetchGroups();
    } else {
      alert(j.msg || '移动失败');
    }
  };

  // 拖拽排序：原生 HTML5 DnD
  const onDragStart = (id: number) => () => {
    dragId.current = id;
  };
  const onDrop = (targetId: number) => () => {
    const src = dragId.current;
    dragId.current = null;
    if (src == null || src === targetId || activeId == null) return;
    const ordered = items.map((it) => it.id);
    const from = ordered.indexOf(src);
    const to = ordered.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ordered.splice(from, 1);
    ordered.splice(to, 0, src);
    // 乐观更新
    const byId = new Map(items.map((it) => [it.id, it]));
    setItems(ordered.map((id) => byId.get(id)!));
    jput(`${API_BASE}/watchlist/groups/${activeId}/items/order`, {ids: ordered});
  };

  // 概览条统计
  const summary = useMemo(() => {
    const vals = items
      .map((it) => quotes[it.symbol]?.change_pct)
      .filter((v): v is number => v != null);
    const up = vals.filter((v) => v > 0).length;
    const down = vals.filter((v) => v < 0).length;
    const flat = vals.length - up - down;
    const avg = vals.length
      ? vals.reduce((a, b) => a + b, 0) / vals.length
      : null;
    const totalMv = items.reduce(
      (s, it) => s + (quotes[it.symbol]?.total_mv || 0),
      0,
    );
    return {avg, up, down, flat, has: vals.length > 0, totalMv};
  }, [items, quotes]);

  const otherGroups = groups.filter((g) => g.id !== movingItem?.group_id);
```

- [ ] **Step 3: 用股票层替换占位块**

把 Task 5 里的占位段：
```tsx
      {/* 内容区：分组管理先行；股票层在 Task 6 填充 */}
      {/* STOCKS_CONTENT_PLACEHOLDER */}
      {!activeGroup ? (
        <div className="watchlist__empty">
          {loading ? '加载中…' : '选择或新建一个分组开始管理自选股。'}
        </div>
      ) : (
        <div className="watchlist__empty">（股票内容区待实现）</div>
      )}
```
替换为：
```tsx
      {activeGroup && (
        <>
          {/* 分组概览条 */}
          <div className="watchlist__summary">
            <span className="watchlist__summary-item">
              平均涨幅{' '}
              <b
                className={
                  summary.avg == null
                    ? ''
                    : summary.avg > 0
                      ? 'is-up'
                      : summary.avg < 0
                        ? 'is-down'
                        : ''
                }>
                {summary.avg == null ? '—' : (summary.avg > 0 ? '+' : '') + summary.avg.toFixed(2) + '%'}
              </b>
            </span>
            <span className="watchlist__summary-item">
              涨 <b className="is-up">{summary.up}</b> / 跌{' '}
              <b className="is-down">{summary.down}</b> / 平 {summary.flat}
            </span>
            <span className="watchlist__summary-item">
              总市值 <b>{fmtMv(summary.has ? summary.totalMv : null)}</b>
            </span>
          </div>

          {/* 添加股票 */}
          <div className="watchlist__addbar">
            <div className="watchlist__addbar-select">
              <StockSelect value={addSym} onChange={setAddSym} market="A" />
            </div>
            <Input
              value={addNote}
              onChange={(e) => setAddNote(e.target.value)}
              placeholder="备注(可选)"
            />
            <Button variant="primary" onClick={handleAdd}>
              加入
            </Button>
          </div>

          {/* 成员表 */}
          {items.length === 0 ? (
            <div className="watchlist__empty">
              {itemsLoading ? '加载中…' : '该分组还没有股票，用上方搜索框添加。'}
            </div>
          ) : (
            <Table variant="striped" className="watchlist__table">
              <TableHead>
                <TableRow>
                  <TableHeaderCell>⠿</TableHeaderCell>
                  <TableHeaderCell>名称 / 代码</TableHeaderCell>
                  <TableHeaderCell numeric>现价</TableHeaderCell>
                  <TableHeaderCell numeric>涨跌额</TableHeaderCell>
                  <TableHeaderCell numeric>涨跌幅</TableHeaderCell>
                  <TableHeaderCell numeric>PE</TableHeaderCell>
                  <TableHeaderCell numeric>PB</TableHeaderCell>
                  <TableHeaderCell numeric>股息率</TableHeaderCell>
                  <TableHeaderCell numeric>总市值</TableHeaderCell>
                  <TableHeaderCell>备注</TableHeaderCell>
                  <TableHeaderCell>操作</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((it) => {
                  const q = quotes[it.symbol];
                  return (
                    <TableRow
                      key={it.id}
                      draggable
                      onDragStart={onDragStart(it.id)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={onDrop(it.id)}
                      className="watchlist__row">
                      <TableCell>
                        <span className="watchlist__drag" title="拖拽排序">
                          ⠿
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="watchlist__sym">
                          <span className="watchlist__sym-name">
                            {q?.name || it.symbol}
                          </span>
                          <span className="watchlist__sym-code">{it.symbol}</span>
                        </div>
                      </TableCell>
                      <TableCell numeric>{nf(q?.price)}</TableCell>
                      <TableCell numeric>{nf(q?.change)}</TableCell>
                      <TableCell numeric>
                        {q ? <PnlBadge value={q.change_pct} /> : '—'}
                      </TableCell>
                      <TableCell numeric>{nf(q?.pe_ttm ?? q?.pe)}</TableCell>
                      <TableCell numeric>{nf(q?.pb)}</TableCell>
                      <TableCell numeric>
                        {q?.dv_ttm != null ? nf(q.dv_ttm) + '%' : '—'}
                      </TableCell>
                      <TableCell numeric>{fmtMv(q?.total_mv || null)}</TableCell>
                      <TableCell>
                        {editNoteId === it.id ? (
                          <input
                            className="watchlist__note-input"
                            value={editNoteVal}
                            autoFocus
                            onChange={(e) => setEditNoteVal(e.target.value)}
                            onBlur={() => saveNote(it)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') saveNote(it);
                              if (e.key === 'Escape') setEditNoteId(null);
                            }}
                          />
                        ) : (
                          <span
                            className="watchlist__note"
                            onClick={() => {
                              setEditNoteId(it.id);
                              setEditNoteVal(it.note || '');
                            }}>
                            {it.note || <em>添加备注</em>}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="watchlist__row-actions">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setMovingItem(it)}>
                            移到
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleRemove(it)}>
                            删除
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </>
      )}
      {!activeGroup && !loading && (
        <div className="watchlist__empty">选择或新建一个分组开始管理自选股。</div>
      )}

      {/* 跨组移动 */}
      <Modal open={!!movingItem} onClose={() => setMovingItem(null)} size="sm">
        <ModalHeader>
          <ModalTitle>移动「{quotes[movingItem?.symbol || '']?.name || movingItem?.symbol}」到</ModalTitle>
        </ModalHeader>
        <ModalBody>
          <div className="watchlist__move-list">
            {otherGroups.map((g) => (
              <Button
                key={g.id}
                variant="secondary"
                fullWidth
                onClick={() => handleMove(g.id)}>
                {g.name} ({g.item_count})
              </Button>
            ))}
            {otherGroups.length === 0 && (
              <span className="watchlist__empty">没有其它分组</span>
            )}
          </div>
        </ModalBody>
      </Modal>
```

- [ ] **Step 4: 追加 CSS（概览条/添加栏/表格/拖拽/备注）**

在 `Watchlist.css` 末尾追加：
```css
.watchlist__summary {
  display: flex;
  gap: var(--space-6);
  flex-wrap: wrap;
  padding: var(--space-3) var(--space-4);
  margin: var(--space-3) 0;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.watchlist__summary-item b {
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}
.is-up {
  color: var(--color-danger);
}
.is-down {
  color: var(--color-success);
}
.watchlist__addbar {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  margin: var(--space-3) 0;
  flex-wrap: wrap;
}
.watchlist__addbar-select {
  min-width: 280px;
}
.watchlist__addbar .input-wrap,
.watchlist__addbar input {
  flex: 1 1 160px;
}
.watchlist__table {
  width: 100%;
}
.watchlist__row {
  cursor: default;
}
.watchlist__drag {
  color: var(--color-text-tertiary);
  cursor: grab;
  user-select: none;
}
.watchlist__sym {
  display: flex;
  flex-direction: column;
}
.watchlist__sym-name {
  color: var(--color-text);
}
.watchlist__sym-code {
  color: var(--color-text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}
.watchlist__note {
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: var(--text-sm);
}
.watchlist__note em {
  color: var(--color-text-tertiary);
  font-style: normal;
}
.watchlist__note-input {
  width: 100%;
  background: var(--color-surface-elevated);
  border: 1px solid var(--color-accent);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  padding: 2px 6px;
  font-size: var(--text-sm);
}
.watchlist__row-actions {
  display: flex;
  gap: var(--space-1);
}
.watchlist__move-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
```

> 涨跌色：A 股惯例红涨绿跌，故 `.is-up`(涨)用 `--color-danger`(红)、`.is-down`(跌)用 `--color-success`(绿)。`PnlBadge` 自身的配色由组件内置（其内部同样按正负着色）；若与本地惯例不一致，后续可在 CSS 覆盖，本次保持组件默认。

- [ ] **Step 5: 构建 + 冒烟**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend
pnpm --filter web build
```
Expected: 构建通过。`pnpm --filter web dev` → `/watchlist`：
- 切分组看到成员表（现价/涨跌/PE/PB/股息率/总市值）、概览条（平均涨幅/涨跌平/总市值）。
- 搜索加股票、删除、点备注可编辑（回车保存/Esc 取消）。
- 拖拽行重排（刷新后顺序保留）。
- 「移到」跨组移动。
- 停留 30s 看到行情自动刷新（切到其它浏览器 Tab 时不刷新）。
- 港股/无数据股票对应格显示「—」。

- [ ] **Step 6: 提交**

```bash
git add frontend/apps/web/src/pages/Watchlist.tsx frontend/apps/web/src/pages/Watchlist.css
git commit -m "feat(watchlist): 股票层(表格/报价/估值/概览/轮询/增删/备注/拖拽/跨组移动)"
```

---

## 收尾冒烟清单（全部完成后）

- 后端：`cd backend && .venv/bin/python -m pytest tests/infra/database/watchlist/ tests/api/test_watchlist_router.py tests/api/test_market_quotes.py -v` 全绿。
- 前端：`cd frontend && pnpm --filter web build` 通过。
- 端到端：`/watchlist` 完整跑一遍「建分组→加股票→看行情/估值/概览→改备注→拖拽→跨组移动→删股票→删分组」。

## 不做（YAGNI，参考 spec §7）

实时 WebSocket、价格提醒、多用户、导入导出、前端自动化测试。
