# Subscription Sources Design

Date: 2026-06-05

## Summary

Add a subscription management system that lets users dynamically subscribe to Bilibili UP hosts (videos and articles) and WeChat public accounts. Content is fetched via RSSHub (already deployed) for Bilibili and WeWe RSS (new Docker container) for WeChat, both producing standard RSS feeds that plug into the existing `RSSProvider`.

## Requirements

- Users can add/remove/enable/disable subscriptions through a frontend UI
- Supported source types: Bilibili UP host videos, Bilibili UP host articles, WeChat public accounts
- Content is collected on a 15-minute schedule via APScheduler
- Users can manually trigger sync from the UI
- Subscribed content flows into the existing `intel_news` table and appears in the Intel page

## Architecture

### Approach: RSSHub Route Direct Connect

- **Bilibili**: Use existing RSSHub instance (port 1200) routes:
  - `/bilibili/user/video/{uid}` for UP host videos
  - `/bilibili/user/article/{uid}` for UP host articles
- **WeChat**: Deploy WeWe RSS Docker container (based on WeRead API), outputs RSS per public account
- All feeds consumed by the existing `RSSProvider` class

### Data Model

New `Subscription` table:

```python
class Subscription(SQLModel, table=True):
    __tablename__ = "subscription"

    id: int | None = Field(default=None, primary_key=True)
    source_type: str          # "bilibili_video" | "bilibili_article" | "wechat"
    source_id: str            # Bilibili UID / WeChat biz ID
    name: str                 # Display name (UP host name / account name)
    category: str             # "finance" | "hotlist" | "future_tech"
    feed_url: str | None      # Auto-generated RSS URL
    is_active: bool = True
    last_fetched_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
```

Feed URL auto-generation:

| source_type | feed_url template |
|---|---|
| `bilibili_video` | `{rsshub_base}/bilibili/user/video/{source_id}` |
| `bilibili_article` | `{rsshub_base}/bilibili/user/article/{source_id}` |
| `wechat` | `{wewe_rss_base}/feed/{source_id}.xml` |

### Backend Layered Design

**Domain layer** (`domain/market/intel/subscription.py`):
- `Subscription` SQLModel entity
- `ISubscriptionRepository` interface with methods:
  - `add_subscription(sub: Subscription) -> Subscription`
  - `remove_subscription(id: int) -> bool`
  - `list_subscriptions(source_type: str | None = None) -> list[Subscription]`
  - `get_active_subscriptions() -> list[Subscription]`
  - `update_subscription_status(id: int, is_active: bool) -> Subscription`
  - `update_fetch_result(id: int, error: str | None = None) -> Subscription`

**Infrastructure layer** (`infra/database/impl/subscription_db.py`):
- `SubscriptionRepository(ISubscriptionRepository)` using SQLModel + `DBConnection.session_scope()`
- `create_subscription_repository()` factory function

**Application layer** (`application/intel/use_cases/subscription_use_case.py`):
- `SubscriptionUseCase`:
  - `add_subscription(source_type, source_id, name, category) -> Subscription` — validates input, generates feed_url, saves to DB
  - `remove_subscription(id: int) -> bool`
  - `list_subscriptions(source_type: str | None = None) -> list[Subscription]`
  - `toggle_subscription(id: int) -> Subscription`
  - `sync_subscriptions(repository: IIntelRepository | None = None) -> dict` — reads active subscriptions, builds dynamic `RSSProvider` instances, runs collection

**API layer** (`api/router/subscription_router.py`):
- `GET /api/v1/subscriptions` — list all subscriptions (optional `?source_type=` filter)
- `POST /api/v1/subscriptions` — add subscription (body: `{source_type, source_id, name, category}`)
- `DELETE /api/v1/subscriptions/{id}` — remove subscription
- `PUT /api/v1/subscriptions/{id}/toggle` — enable/disable subscription
- `POST /api/v1/subscriptions/sync` — manually trigger sync

### Collection Flow

```
APScheduler (every 15 min)
  -> subscription_use_case.sync_subscriptions()
    -> get_active_subscriptions() from DB
    -> for each subscription:
         build RSSProvider(name=sub.name, category=sub.category, feed_urls=[sub.feed_url])
    -> NewsCollectorService(providers=dynamic_providers).collect(repository=intel_repo)
    -> dedup by URL, persist to intel_news table
```

### Frontend UI

**New page**: `/subscriptions` — Subscription Management

Layout:
- Header: page title + "Add Subscription" button
- Filter bar: tabs for All / Bilibili Video / Bilibili Article / WeChat
- Subscription cards: each showing name, source type, category, status (active/inactive), last fetch time, action buttons (toggle, delete)

**Add Subscription modal**:
- Source type dropdown: Bilibili Video / Bilibili Article / WeChat
- Source ID input: Bilibili UID or WeChat account ID
- Display name input
- Category dropdown: Finance / Hotlist / Future Tech
- Submit generates feed_url preview based on source_type

**Sidebar**: Add "Subscription Management" entry below Intel in the Layout sidebar.

**Styling**: Dark theme, card-based layout consistent with Intel page, BEM-like CSS naming.

### Docker & Configuration

**docker-compose.yml** — add WeWe RSS service:

```yaml
wewe-rss:
  image: cooderl/wewe-rss:latest
  container_name: wewe-rss
  ports:
    - "4000:4000"
  environment:
    - MAX_REQUEST_PER_MINUTE=60
    - FEED_MODE=fulltext
    - DATABASE_TYPE=sqlite
  volumes:
    - ./wewe-rss-data:/app/data
  restart: unless-stopped
```

**config.yaml** — add subscription section:

```yaml
intel:
  subscription:
    rsshub_base: "http://localhost:1200"
    wewe_rss_base: "http://localhost:4000"
    sync_interval_minutes: 15
```

**settings.py** — add Pydantic model:

```python
class SubscriptionConfig(BaseModel):
    rsshub_base: str = "http://localhost:1200"
    wewe_rss_base: str = "http://localhost:4000"
    sync_interval_minutes: int = 15
```

**scheduler.py** — add subscription sync job:

```python
# Every 15 minutes
scheduler.add_job(sync_subscriptions_job, 'cron', minute='*/15', id='subscription_sync')
```

### File Changes Summary

| Action | File | Description |
|--------|------|-------------|
| New | `backend/src/domain/market/intel/subscription.py` | Subscription entity + repository interface |
| New | `backend/src/infra/database/impl/subscription_db.py` | SQLModel repository implementation |
| New | `backend/src/application/intel/use_cases/subscription_use_case.py` | Use case logic |
| New | `backend/src/api/router/subscription_router.py` | HTTP endpoints |
| Modify | `backend/main.py` | Register subscription router |
| Modify | `backend/conf/settings.py` | Add SubscriptionConfig |
| Modify | `backend/conf/config.yaml` | Add subscription config section |
| Modify | `backend/src/infra/scheduler.py` | Add subscription sync job |
| Modify | `docker/docker-compose.yml` | Add WeWe RSS service |
| New | `frontend/apps/web/src/pages/Subscriptions.tsx` | Subscription management page |
| New | `frontend/apps/web/src/pages/Subscriptions.css` | Page styles |
| Modify | `frontend/apps/web/src/App.tsx` | Add /subscriptions route |
| Modify | `frontend/apps/web/src/components/Layout.tsx` | Add sidebar entry |

### Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| WeWe RSS account ban | WeChat feeds stop updating | Rate-limit requests, log errors, surface in UI |
| RSSHub Bilibili routes break | Bilibili feeds stop updating | Monitor health, fallback to bilibili-api package |
| Subscription table grows unbounded | Slow queries | Add index on `(source_type, is_active)`, keep table small (personal use) |
| WeWe RSS initial setup requires WeChat login | One-time friction | Document setup steps clearly |
