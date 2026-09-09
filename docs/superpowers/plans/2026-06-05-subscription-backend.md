# Subscription Sources — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the backend for the subscription management system — domain model, repository, use case, API router, config, scheduler integration, and router registration.

**Architecture:** DDD layered — domain entity + interface in `domain/market/intel/`, repository impl in `infra/database/impl/`, use case in `application/intel/use_cases/`, API router in `api/router/`. Reuses existing `RSSProvider` and `NewsCollectorService` for content collection.

**Tech Stack:** Python 3.12, SQLModel ORM, FastAPI, APScheduler, feedparser

**Spec:** `docs/superpowers/specs/2026-06-05-subscription-sources-design.md`

---

### Task 1: Domain Entity + Repository Interface

**Files:**
- Create: `backend/src/domain/market/intel/subscription.py`

- [ ] **Step 1: Create the subscription domain file**

```python
"""
Subscription domain entity and repository interface.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Column, Text
from sqlalchemy import Index


# ── Entity ──────────────────────────────────────────────────────

class Subscription(SQLModel, table=True):
    """RSS subscription to a Bilibili UP host or WeChat public account."""
    __tablename__ = "subscription"
    __table_args__ = (
        Index("idx_subscription_type_active", "source_type", "is_active"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source_type: str = Field(max_length=30)   # "bilibili_video" | "bilibili_article" | "wechat"
    source_id: str = Field(max_length=200)     # Bilibili UID / WeChat biz ID
    name: str = Field(max_length=200)          # Display name (UP host name / account name)
    category: str = Field(max_length=30)       # "finance" | "hotlist" | "future_tech"
    feed_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    is_active: bool = Field(default=True)
    last_fetched_at: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.now)


# ── Repository Interface ───────────────────────────────────────

class ISubscriptionRepository(ABC):

    @abstractmethod
    def add_subscription(self, sub: Subscription) -> Subscription: ...

    @abstractmethod
    def remove_subscription(self, id: int) -> bool: ...

    @abstractmethod
    def list_subscriptions(self, source_type: str | None = None) -> list[Subscription]: ...

    @abstractmethod
    def get_active_subscriptions(self) -> list[Subscription]: ...

    @abstractmethod
    def get_by_id(self, id: int) -> Subscription | None: ...

    @abstractmethod
    def update_subscription_status(self, id: int, is_active: bool) -> Subscription | None: ...

    @abstractmethod
    def update_fetch_result(self, id: int, error: str | None = None) -> Subscription | None: ...
```

- [ ] **Step 2: Verify file imports cleanly**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.domain.market.intel.subscription import Subscription, ISubscriptionRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/domain/market/intel/subscription.py
git commit -m "feat(subscription): add Subscription entity and ISubscriptionRepository interface"
```

---

### Task 2: Repository Implementation

**Files:**
- Create: `backend/src/infra/database/impl/subscription_db.py`

- [ ] **Step 1: Create the repository implementation**

```python
"""
Subscription repository implementation using SQLModel ORM.
"""
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select
from loguru import logger

from src.domain.market.intel.subscription import (
    Subscription,
    ISubscriptionRepository,
)
from src.infra.database.db_helper import DBConnection, create_db_connection


# ── Singleton DB connection ────────────────────────────────────

_db_connection: Optional[DBConnection] = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection()
                _db_connection.create_tables([Subscription])
    return _db_connection


# ── Repository ─────────────────────────────────────────────────

class SubscriptionRepository(ISubscriptionRepository):
    """SQLModel-backed subscription repository."""

    def __init__(self, db_connection: DBConnection):
        self._db = db_connection

    def add_subscription(self, sub: Subscription) -> Subscription:
        with self._db.session_scope() as session:
            session.add(sub)
            session.commit()
            session.refresh(sub)
            return sub

    def remove_subscription(self, id: int) -> bool:
        with self._db.session_scope() as session:
            sub = session.get(Subscription, id)
            if sub is None:
                return False
            session.delete(sub)
            session.commit()
            return True

    def list_subscriptions(
        self, source_type: str | None = None,
    ) -> list[Subscription]:
        with self._db.session_scope() as session:
            if source_type:
                stmt = select(Subscription).where(
                    Subscription.source_type == source_type
                ).order_by(Subscription.created_at.desc())
            else:
                stmt = select(Subscription).order_by(
                    Subscription.created_at.desc()
                )
            return list(session.exec(stmt).all())

    def get_active_subscriptions(self) -> list[Subscription]:
        with self._db.session_scope() as session:
            stmt = select(Subscription).where(
                Subscription.is_active == True  # noqa: E712
            ).order_by(Subscription.created_at.desc())
            return list(session.exec(stmt).all())

    def get_by_id(self, id: int) -> Subscription | None:
        with self._db.session_scope() as session:
            return session.get(Subscription, id)

    def update_subscription_status(
        self, id: int, is_active: bool,
    ) -> Subscription | None:
        with self._db.session_scope() as session:
            sub = session.get(Subscription, id)
            if sub is None:
                return None
            sub.is_active = is_active
            session.commit()
            session.refresh(sub)
            return sub

    def update_fetch_result(
        self, id: int, error: str | None = None,
    ) -> Subscription | None:
        with self._db.session_scope() as session:
            sub = session.get(Subscription, id)
            if sub is None:
                return None
            sub.last_fetched_at = datetime.now(timezone.utc)
            sub.last_error = error
            session.commit()
            session.refresh(sub)
            return sub


# ── Factory ────────────────────────────────────────────────────

def create_subscription_repository(
    db_connection: DBConnection | None = None,
) -> SubscriptionRepository:
    conn = db_connection or _get_db_connection()
    return SubscriptionRepository(conn)
```

- [ ] **Step 2: Verify file imports cleanly**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.infra.database.impl.subscription_db import create_subscription_repository; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/database/impl/subscription_db.py
git commit -m "feat(subscription): add SubscriptionRepository with SQLModel impl"
```

---

### Task 3: Use Case

**Files:**
- Create: `backend/src/application/intel/use_cases/subscription_use_case.py`

- [ ] **Step 1: Create the use case**

```python
"""
Subscription management use case.
Orchestrates CRUD + sync for subscription sources.
"""
import logging

from src.domain.market.intel.subscription import (
    Subscription,
    ISubscriptionRepository,
)
from src.infra.database.impl.subscription_db import create_subscription_repository
from src.domain.market.intel.providers.rss_provider import RSSProvider
from src.domain.market.intel.collector import NewsCollectorService
from src.domain.market.intel.repository_interface import IIntelRepository
from src.infra.database.impl.intel_db import create_intel_repository

log = logging.getLogger(__name__)

# ── Feed URL templates ─────────────────────────────────────────

_FEED_URL_TEMPLATES = {
    "bilibili_video": "{rsshub_base}/bilibili/user/video/{source_id}",
    "bilibili_article": "{rsshub_base}/bilibili/user/article/{source_id}",
    "wechat": "{wewe_rss_base}/feed/{source_id}.xml",
}

_VALID_SOURCE_TYPES = {"bilibili_video", "bilibili_article", "wechat"}
_VALID_CATEGORIES = {"finance", "hotlist", "future_tech"}


class SubscriptionUseCase:
    """Business logic for subscription management."""

    def __init__(
        self,
        repo: ISubscriptionRepository | None = None,
        intel_repo: IIntelRepository | None = None,
    ):
        self.repo = repo or create_subscription_repository()
        self.intel_repo = intel_repo or create_intel_repository()

    def _get_config(self):
        """Load subscription config from app_config."""
        try:
            from conf import app_config
            sub_conf = getattr(
                getattr(app_config, 'intel', None), 'subscription', None)
            if sub_conf:
                return sub_conf
        except Exception:
            pass
        # Defaults
        from types import SimpleNamespace
        return SimpleNamespace(
            rsshub_base="http://localhost:1200",
            wewe_rss_base="http://localhost:4000",
        )

    def _build_feed_url(self, source_type: str, source_id: str) -> str:
        """Generate RSS feed URL from source type and ID."""
        config = self._get_config()
        template = _FEED_URL_TEMPLATES.get(source_type)
        if not template:
            raise ValueError(f"Unknown source_type: {source_type}")

        if source_type.startswith("bilibili"):
            base = getattr(config, 'rsshub_base', 'http://localhost:1200')
            return template.format(rsshub_base=base, source_id=source_id)
        else:
            base = getattr(config, 'wewe_rss_base', 'http://localhost:4000')
            return template.format(wewe_rss_base=base, source_id=source_id)

    # ── CRUD ───────────────────────────────────────────────────

    def add_subscription(
        self, source_type: str, source_id: str,
        name: str, category: str,
    ) -> Subscription:
        """Validate input, generate feed_url, save subscription."""
        if source_type not in _VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type '{source_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_SOURCE_TYPES))}"
            )
        if category not in _VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. "
                f"Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}"
            )
        if not source_id.strip():
            raise ValueError("source_id cannot be empty")
        if not name.strip():
            raise ValueError("name cannot be empty")

        feed_url = self._build_feed_url(source_type, source_id.strip())

        sub = Subscription(
            source_type=source_type,
            source_id=source_id.strip(),
            name=name.strip(),
            category=category,
            feed_url=feed_url,
        )
        return self.repo.add_subscription(sub)

    def remove_subscription(self, id: int) -> bool:
        """Delete a subscription by ID."""
        return self.repo.remove_subscription(id)

    def list_subscriptions(
        self, source_type: str | None = None,
    ) -> list[dict]:
        """List all subscriptions, optionally filtered by source type."""
        subs = self.repo.list_subscriptions(source_type=source_type)
        return [self._to_dict(s) for s in subs]

    def toggle_subscription(self, id: int) -> Subscription | None:
        """Toggle subscription active/inactive state."""
        sub = self.repo.get_by_id(id)
        if sub is None:
            return None
        return self.repo.update_subscription_status(id, not sub.is_active)

    # ── Sync ───────────────────────────────────────────────────

    def sync_subscriptions(self) -> dict:
        """Fetch content from all active subscriptions."""
        subs = self.repo.get_active_subscriptions()
        if not subs:
            return {"synced": 0, "fetched": 0, "inserted": 0, "errors": []}

        providers = []
        for sub in subs:
            providers.append(RSSProvider(
                name=sub.name,
                category=sub.category,
                feed_urls=[sub.feed_url],
                language="zh",
            ))

        service = NewsCollectorService(providers=providers)
        result = service.collect(repository=self.intel_repo)

        # Update fetch timestamps
        now_errors = {}
        if result.get("errors"):
            for err in result["errors"]:
                # errors are "provider_name: error_msg"
                parts = err.split(": ", 1)
                if len(parts) == 2:
                    now_errors[parts[0]] = parts[1]

        for sub in subs:
            error = now_errors.get(sub.name)
            try:
                self.repo.update_fetch_result(sub.id, error=error)
            except Exception as e:
                log.error(
                    "[Subscription] update_fetch_result failed "
                    "for id=%d: %s", sub.id, e)

        return {
            "synced": len(subs),
            "fetched": result.get("fetched", 0),
            "inserted": result.get("inserted", 0),
            "errors": result.get("errors", []),
        }

    # ── Serializer ─────────────────────────────────────────────

    @staticmethod
    def _to_dict(sub: Subscription) -> dict:
        return {
            "id": sub.id,
            "source_type": sub.source_type,
            "source_id": sub.source_id,
            "name": sub.name,
            "category": sub.category,
            "feed_url": sub.feed_url,
            "is_active": sub.is_active,
            "last_fetched_at": (
                sub.last_fetched_at.isoformat()
                if sub.last_fetched_at else None
            ),
            "last_error": sub.last_error,
            "created_at": (
                sub.created_at.isoformat()
                if sub.created_at else None
            ),
        }
```

- [ ] **Step 2: Verify file imports cleanly**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.application.intel.use_cases.subscription_use_case import SubscriptionUseCase; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/application/intel/use_cases/subscription_use_case.py
git commit -m "feat(subscription): add SubscriptionUseCase with CRUD and sync logic"
```

---

### Task 4: API Router

**Files:**
- Create: `backend/src/api/router/subscription_router.py`

- [ ] **Step 1: Create the subscription router**

```python
"""
Subscription Management Router
===============================
GET    /subscriptions              → list all (optional ?source_type= filter)
POST   /subscriptions              → add subscription
DELETE /subscriptions/{id}         → remove subscription
PUT    /subscriptions/{id}/toggle  → enable/disable subscription
POST   /subscriptions/sync         → manually trigger sync
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from src.application.intel.use_cases.subscription_use_case import SubscriptionUseCase

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
log = logging.getLogger(__name__)


# ── Pydantic Models ────────────────────────────────────────────

class SubscriptionCreate(BaseModel):
    source_type: str   # "bilibili_video" | "bilibili_article" | "wechat"
    source_id: str     # Bilibili UID / WeChat biz ID
    name: str          # Display name
    category: str      # "finance" | "hotlist" | "future_tech"

    @field_validator("source_type")
    @classmethod
    def source_type_valid(cls, v: str) -> str:
        valid = {"bilibili_video", "bilibili_article", "wechat"}
        if v not in valid:
            raise ValueError(f"source_type must be one of: {', '.join(sorted(valid))}")
        return v

    @field_validator("source_id")
    @classmethod
    def source_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source_id cannot be empty")
        return v.strip()

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name cannot be empty")
        return v.strip()

    @field_validator("category")
    @classmethod
    def category_valid(cls, v: str) -> str:
        valid = {"finance", "hotlist", "future_tech"}
        if v not in valid:
            raise ValueError(f"category must be one of: {', '.join(sorted(valid))}")
        return v


# ── API Endpoints ──────────────────────────────────────────────

@router.get("")
def list_subscriptions(
    source_type: Optional[str] = Query(
        None, description="Filter by source_type: bilibili_video, bilibili_article, wechat"),
):
    """List all subscriptions, optionally filtered by source type."""
    try:
        use_case = SubscriptionUseCase()
        data = use_case.list_subscriptions(source_type=source_type)
        return {"code": 0, "msg": "ok", "data": data}
    except Exception as e:
        log.error("list_subscriptions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
def create_subscription(body: SubscriptionCreate):
    """Add a new subscription."""
    try:
        use_case = SubscriptionUseCase()
        sub = use_case.add_subscription(
            source_type=body.source_type,
            source_id=body.source_id,
            name=body.name,
            category=body.category,
        )
        data = SubscriptionUseCase._to_dict(sub)
        return {"code": 0, "msg": "ok", "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("create_subscription error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{sub_id}")
def delete_subscription(sub_id: int):
    """Remove a subscription."""
    try:
        use_case = SubscriptionUseCase()
        removed = use_case.remove_subscription(sub_id)
        if not removed:
            raise HTTPException(
                status_code=404, detail=f"Subscription {sub_id} not found")
        return {"code": 0, "msg": "ok", "data": {"id": sub_id}}
    except HTTPException:
        raise
    except Exception as e:
        log.error("delete_subscription error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{sub_id}/toggle")
def toggle_subscription(sub_id: int):
    """Toggle subscription active/inactive state."""
    try:
        use_case = SubscriptionUseCase()
        sub = use_case.toggle_subscription(sub_id)
        if sub is None:
            raise HTTPException(
                status_code=404, detail=f"Subscription {sub_id} not found")
        data = SubscriptionUseCase._to_dict(sub)
        return {"code": 0, "msg": "ok", "data": data}
    except HTTPException:
        raise
    except Exception as e:
        log.error("toggle_subscription error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
def sync_subscriptions():
    """Manually trigger sync for all active subscriptions."""
    try:
        use_case = SubscriptionUseCase()
        result = use_case.sync_subscriptions()
        return {"code": 0, "msg": "ok", "data": result}
    except Exception as e:
        log.error("sync_subscriptions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 2: Verify file imports cleanly**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.api.router.subscription_router import router; print('OK, routes:', len(router.routes))"`
Expected: `OK, routes: 5`

- [ ] **Step 3: Commit**

```bash
git add backend/src/api/router/subscription_router.py
git commit -m "feat(subscription): add subscription API router with 5 endpoints"
```

---

### Task 5: Configuration (settings.py + config.yaml)

**Files:**
- Modify: `backend/conf/settings.py:97-101` (add SubscriptionConfig, update IntelConfig)
- Modify: `backend/conf/config.yaml` (add subscription section under intel)

- [ ] **Step 1: Add SubscriptionConfig to settings.py**

Add the new config class after `IntelAIProcessingConfig` (around line 96) and update `IntelConfig`:

```python
class SubscriptionConfig(BaseModel):
    rsshub_base: str = "http://localhost:1200"
    wewe_rss_base: str = "http://localhost:4000"
    sync_interval_minutes: int = 15


class IntelConfig(BaseModel):
    rss: Optional[dict[str, list[IntelRSSSourceConfig]]] = None
    api: Optional[IntelAPIConfig] = None
    ai_processing: Optional[IntelAIProcessingConfig] = None
    subscription: Optional[SubscriptionConfig] = None
```

- [ ] **Step 2: Add subscription section to config.yaml**

Add under the `intel:` section, after `rss:`:

```yaml
  subscription:
    rsshub_base: "http://localhost:1200"
    wewe_rss_base: "http://localhost:4000"
    sync_interval_minutes: 15
```

- [ ] **Step 3: Verify config loads correctly**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from conf.settings import ConfigCenter; cc = ConfigCenter(); cc.load(); print('subscription:', cc.get().intel.subscription)"`
Expected: `subscription: rsshub_base='http://localhost:1200' wewe_rss_base='http://localhost:4000' sync_interval_minutes=15`

- [ ] **Step 4: Commit**

```bash
git add backend/conf/settings.py backend/conf/config.yaml
git commit -m "feat(subscription): add SubscriptionConfig to settings and config.yaml"
```

---

### Task 6: Scheduler Integration

**Files:**
- Modify: `backend/src/infra/scheduler.py:256` (add subscription sync job after blog generation job)

- [ ] **Step 1: Add subscription sync job to scheduler.py**

Insert the following after the blog generation job block (after line ~255, before `return sched`):

```python
    # ── 订阅源同步（每15分钟）───────────────────────────────────
    def _run_subscription_sync():
        from src.application.intel.use_cases.subscription_use_case import (
            SubscriptionUseCase,
        )
        try:
            use_case = SubscriptionUseCase()
            result = use_case.sync_subscriptions()
            if result.get("synced", 0) > 0:
                log.info(
                    "[SUBSCRIPTION] synced=%d fetched=%d inserted=%d",
                    result["synced"], result.get("fetched", 0),
                    result.get("inserted", 0))
        except Exception as e:
            log.error("[SUBSCRIPTION] sync failed: %s", e)

    sched.add_job(
        _run_subscription_sync,
        CronTrigger(minute="*/15", timezone="Asia/Shanghai"),
        id="subscription_sync",
        name="订阅源同步",
        replace_existing=True,
        misfire_grace_time=600,
    )
```

- [ ] **Step 2: Verify scheduler still loads**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.infra.scheduler import setup_scheduler; s = setup_scheduler(); jobs = [j.id for j in s.get_jobs()]; print('subscription_sync' in jobs, jobs)"`
Expected: `True [...]` (list containing `subscription_sync`)

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/scheduler.py
git commit -m "feat(subscription): add subscription sync job to APScheduler (every 15 min)"
```

---

### Task 7: Register Router in main.py

**Files:**
- Modify: `backend/main.py:43` (add import and registration)

- [ ] **Step 1: Add subscription router import**

After the existing blog_router import (line 43), add:

```python
from src.api.router.subscription_router import router as subscription_router
```

- [ ] **Step 2: Register subscription router**

After the blog_router registration (line 259), add:

```python
app.include_router(subscription_router, prefix="/api/v1")  # /api/v1/subscriptions
```

- [ ] **Step 3: Verify the app starts**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && timeout 5 .venv/bin/python -c "from main import create_app; app = create_app(); routes = [r.path for r in app.routes if hasattr(r, 'path')]; subs = [r for r in routes if 'subscription' in r]; print('subscription routes:', subs)"`
Expected: `subscription routes: ['/api/v1/subscriptions', '/api/v1/subscriptions/{sub_id}', ...]` (5 routes)

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(subscription): register subscription router in main.py"
```

---

### Task 8: End-to-End Smoke Test

**Files:** None (manual testing)

- [ ] **Step 1: Start the backend**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python main.py`

Wait for startup logs to show `[Scheduler] started` and `App startup complete.`

- [ ] **Step 2: Test CREATE subscription**

Run in another terminal:
```bash
curl -s -X POST http://localhost:12100/api/v1/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"source_type":"bilibili_video","source_id":"546195","name":"半佛仙人","category":"finance"}' | python3 -m json.tool
```

Expected: `{"code": 0, "msg": "ok", "data": {"id": 1, "source_type": "bilibili_video", "source_id": "546195", "name": "半佛仙人", ...}}`

- [ ] **Step 3: Test LIST subscriptions**

```bash
curl -s http://localhost:12100/api/v1/subscriptions | python3 -m json.tool
```

Expected: `{"code": 0, "msg": "ok", "data": [...]}` containing the subscription just created.

- [ ] **Step 4: Test TOGGLE subscription**

```bash
curl -s -X PUT http://localhost:12100/api/v1/subscriptions/1/toggle | python3 -m json.tool
```

Expected: `{"code": 0, "msg": "ok", "data": {"id": 1, "is_active": false, ...}}`

- [ ] **Step 5: Test SYNC subscriptions**

```bash
curl -s -X POST http://localhost:12100/api/v1/subscriptions/sync | python3 -m json.tool
```

Expected: `{"code": 0, "msg": "ok", "data": {"synced": N, "fetched": N, "inserted": N, "errors": [...]}}`

- [ ] **Step 6: Test DELETE subscription**

```bash
curl -s -X DELETE http://localhost:12100/api/v1/subscriptions/1 | python3 -m json.tool
```

Expected: `{"code": 0, "msg": "ok", "data": {"id": 1}}`
