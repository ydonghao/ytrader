# Intelligence News Collection System Design

## Overview

A pluggable news collection system integrated into ytrader, focused on reliable international sources for AI, political, and investment news. Supports investment decision-making for global affairs, A-shares, and US stocks.

## Architecture: Plugin-based Provider Pattern

### Data Source Plan

| Category | Sources | Method | Frequency |
|----------|---------|--------|-----------|
| World News | Reuters RSS, BBC RSS, AP News RSS | RSS | 15min |
| Finance/Investment | FinnHub API, Yahoo Finance RSS, CNBC RSS, WSJ RSS | API + RSS | 15min |
| AI/Tech | TechCrunch RSS, The Verge RSS, MIT Tech Review RSS, Ars Technica RSS | RSS | 30min |
| Politics/Geopolitics | Foreign Affairs RSS, The Economist RSS, Foreign Policy RSS | RSS | 30min |
| Chinese Finance | AkShare (East Money), newsnow API (Wall Street CN, CLS, 36kr) | API | 15min |

### Provider Interface

```python
class BaseNewsProvider(ABC):
    name: str
    category: NewsCategory  # WORLD, FINANCE, TECH_AI, POLITICS, CN_FINANCE

    async def fetch_latest(self, limit: int = 50) -> list[NewsItem]:
        """Fetch latest news items"""

    async def health_check(self) -> bool:
        """Check if data source is reachable"""
```

Two generic implementations:
- `RSSProvider` — accepts feed URL list, parses with `feedparser`. Zero-code onboarding for any RSS source.
- `RESTAPIProvider` — accepts endpoint + parser function for APIs like FinnHub.

Adding a new source requires only: a config entry (RSS) or a small parser function (API).

### Unified NewsItem Model

```python
class NewsItem:
    title: str
    content: str           # Full text or excerpt
    url: str               # Original article URL (dedup key)
    source: str            # Source name (Reuters, BBC, etc.)
    source_type: str       # rss / api
    category: str          # world / finance / tech_ai / politics / cn_finance
    tags: list[str]        # AI-extracted keywords
    sentiment: float       # -1.0 ~ 1.0
    importance: float      # 0.0 ~ 1.0
    published_at: datetime
    fetched_at: datetime
    language: str          # en / zh
```

## Data Flow

```
[Scheduler (APScheduler)]
    |
    +-- Every 15min: world/finance/cn_finance providers
    +-- Every 30min: tech_ai/politics providers
    |
    v
[NewsCollectorService]
    |  Iterate active providers
    |  Concurrent fetch -> dedup (by URL) -> persist
    v
[PostgreSQL: intel_news table]
    |
    +-- [AI Processor] (async, triggered after insert)
    |     +-- Summary generation (long articles -> Chinese summary)
    |     +-- Sentiment analysis (-1 to 1)
    |     +-- Keyword/tag extraction
    |     +-- Importance scoring
    |
    v
[FastAPI REST API]
    |  GET /api/v1/intel/news          -- Paginated query
    |  GET /api/v1/intel/news/trending  -- Trending topics
    |  GET /api/v1/intel/news/search    -- Full-text search
    |  GET /api/v1/intel/sources        -- Source health status
    |  GET /api/v1/intel/summary        -- Daily summary
    v
[Frontend: /intel page]
```

## Database Schema

```sql
CREATE TABLE intel_news (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    content         TEXT,
    summary         TEXT,
    url             TEXT UNIQUE,
    source          VARCHAR(100),
    source_type     VARCHAR(20),
    category        VARCHAR(20),
    tags            TEXT[],
    sentiment       FLOAT,
    importance      FLOAT,
    language        VARCHAR(5),
    published_at    TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    processed       BOOLEAN DEFAULT FALSE
);

CREATE TABLE intel_sources (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) UNIQUE,
    provider_type   VARCHAR(20),
    category        VARCHAR(20),
    config          JSONB,
    is_active       BOOLEAN DEFAULT TRUE,
    last_fetched_at TIMESTAMPTZ,
    last_error      TEXT,
    fetch_count     INT DEFAULT 0,
    error_count     INT DEFAULT 0
);

CREATE INDEX idx_intel_news_category ON intel_news(category);
CREATE INDEX idx_intel_news_published ON intel_news(published_at DESC);
CREATE INDEX idx_intel_news_importance ON intel_news(importance DESC);
CREATE INDEX idx_intel_news_tags ON intel_news USING GIN(tags);
```

## Backend Directory Structure

```
backend/src/
  domain/market/intel/
    providers/
      base.py               # BaseNewsProvider abstract class
      rss_provider.py       # Generic RSS parser (feedparser)
      finnhub_provider.py   # FinnHub REST API
      newsnow_provider.py   # newsnow aggregator (Chinese hot news)
      akshare_provider.py   # Migrated from existing news module
    models.py               # NewsItem, IntelSource Pydantic models
    collector.py            # NewsCollectorService orchestration
    processor.py            # AI summary/sentiment/tag processing
  api/router/
    intel_router.py         # New API endpoints
```

## Frontend: /intel Page

Layout:
- Left sidebar: category filters (All, World, Finance, AI/Tech, Politics, Chinese) + source health status
- Main area: news card list sorted by time or importance
- Each card shows: title, source, time, AI summary, sentiment indicator, importance rating, tags
- Top search bar: full-text search across title + summary
- Daily summary view: AI-generated highlights per category

Implementation:
- New route `/intel` registered in existing React Router setup
- API hooks via `@ytrader/arch-api` createApiHook pattern
- Zustand store for filter state management
- Reuses existing UI component patterns from `/news` page

## Scheduler Configuration

Added to existing `scheduler.py`:

```python
# News collection
scheduler.add_job(collect_intel_news, 'interval', minutes=15,
    id='intel_collect_finance',
    kwargs={'categories': ['finance', 'world', 'cn_finance']})
scheduler.add_job(collect_intel_news, 'interval', minutes=30,
    id='intel_collect_other',
    kwargs={'categories': ['tech_ai', 'politics']})
# AI processing
scheduler.add_job(process_intel_news, 'interval', minutes=5,
    id='intel_ai_process')
# Daily summary
scheduler.add_job(generate_daily_summary, 'cron',
    hour=20, minute=0, id='intel_daily_summary')
```

## Configuration (config.yaml addition)

```yaml
intel:
  rss:
    world:
      - name: Reuters
        url: https://www.reutersagency.com/feed/
        language: en
      - name: BBC
        url: http://feeds.bbci.co.uk/news/rss.xml
        language: en
      - name: AP News
        url: https://rsshub.app/apnews/topics/apf-topnews
        language: en
    finance:
      - name: Yahoo Finance
        url: https://finance.yahoo.com/news/rssindex
        language: en
      - name: CNBC
        url: https://search.cnbc.com/rs/search/combinedcms/view.xml
        language: en
      - name: WSJ
        url: https://feeds.content.dowjones.io/public/rss/mw_topstories
        language: en
    tech_ai:
      - name: TechCrunch AI
        url: https://techcrunch.com/category/artificial-intelligence/feed/
        language: en
      - name: The Verge
        url: https://www.theverge.com/rss/index.xml
        language: en
      - name: MIT Tech Review
        url: https://www.technologyreview.com/feed/
        language: en
      - name: Ars Technica
        url: https://feeds.arstechnica.com/arstechnica/index
        language: en
    politics:
      - name: Foreign Affairs
        url: https://www.foreignaffairs.com/rss.xml
        language: en
      - name: The Economist
        url: https://www.economist.com/rss
        language: en
  api:
    finnhub:
      enabled: true
      api_key: ${FINNHUB_API_KEY}
    newsnow:
      enabled: true
      base_url: https://newsnow.busiyi.world/api/s
      platforms: [wallstreetcn-hot, cls-hot, 36kr, ithome]
  ai_processing:
    enabled: true
    batch_size: 20
    summary_language: zh
```

## Dependencies

- `feedparser` — RSS/Atom feed parsing
- `httpx` — Async HTTP client (if not already present, otherwise reuse existing `requests`)
- Existing: `psycopg2`, `fastapi`, `apscheduler`, existing LLM client

## Success Criteria

1. System collects news from 15+ sources across 5 categories
2. RSS sources work with zero-code configuration
3. News is persisted and searchable with filters
4. AI processing generates Chinese summaries and sentiment scores
5. Frontend page displays news with category filtering and source status
6. System runs stably on schedule without manual intervention
