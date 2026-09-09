# CCTV News Collection & Analysis Design

Date: 2026-06-05

## Overview

Add CCTV News (央视新闻) as a new intel category with full data collection and analysis pipeline: AI-powered summarization, statistical dashboards, event detection/hot topic tracking, and news-market correlation analysis.

## Architecture: Independent Provider + Analysis Layer (Option B)

Build on existing intel infrastructure (BaseNewsProvider, Collector, Repository, Scheduler) while adding a dedicated CCTVNewsProvider and an `analysis/` submodule for the three analytical capabilities.

## Section 1: Data Model & Collection

### New Category

Add `cctv_news` to `NewsCategory` enum alongside `future_tech`, `finance`, `hotlist`.

### NewsItem Extension

Add `metadata: dict` field to `NewsItem` dataclass to carry CCTV-specific data without modifying existing consumers:

- `channel`: Feed source — domestic / world / finance / tech
- `program`: Show name (e.g. 新闻联播, 焦点访谈)
- `video_url`: Video link if available

### Database Changes

- Add `metadata` JSONB column to `intel_news` table
- Add composite index `(category, published_at)` for category-scoped time queries

### CCTVNewsProvider

```
class CCTVNewsProvider(BaseNewsProvider):
    name = "cctv_news"
    source_type = "rss"

    def __init__(self, feeds: list[FeedConfig]):
        self.feeds = feeds

    def fetch_latest(self, limit: int) -> list[NewsItem]:
        # Iterate feeds, parse with feedparser
        # Extract channel metadata, video links
        # Return NewsItem list with metadata populated
```

### Configuration

```yaml
intel:
  rss:
    cctv_news:
      - name: "央视国内新闻"
        url: "http://localhost:1200/cctv/domestic"
        channel: "domestic"
      - name: "央视国际新闻"
        url: "http://localhost:1200/cctv/world"
        channel: "world"
      - name: "央视财经"
        url: "http://localhost:1200/cctv/finance"
        channel: "finance"
      - name: "央视科技"
        url: "http://localhost:1200/cctv/tech"
        channel: "tech"
```

### Schedule

New cron job in `scheduler.py`: collect CCTV news every 30 minutes (longer interval than finance's 15min due to lower update frequency).

## Section 2: Data Analysis Module

New submodule at `domain/market/intel/analysis/` containing three independent services.

### 2.1 StatsService — Statistical Reports

Dimensions:
- **Time distribution**: Daily/weekly/monthly news count trends
- **Sentiment distribution**: Positive/neutral/negative ratio over time
- **Top tags**: High-frequency keywords Top N, trend changes per time window
- **Channel distribution**: Domestic/world/finance/tech proportion

```python
@dataclass
class NewsStats:
    period: str                     # "7d", "30d"
    total_count: int
    by_channel: dict[str, int]      # {"domestic": 120, "world": 85, ...}
    by_sentiment: dict[str, int]    # {"positive": 60, "neutral": 120, "negative": 25}
    sentiment_trend: list[dict]     # [{date, positive, neutral, negative}, ...]
    top_tags: list[dict]            # [{tag, count, trend}, ...]
    daily_counts: list[dict]        # [{date, count}, ...]
```

API: `GET /api/v1/intel/cctv/stats?period=7d&granularity=day`

### 2.2 EventDetectionService — Hot Topic Tracking

Algorithm:
1. **Burst detection**: Monitor short time windows (2 hours) for abnormal volume growth; flag when count exceeds mean + 2σ
2. **Topic clustering**: Group same-day news by tag similarity into "hot events"
3. **Event tracking**: Cross-day tracking via tag overlap, generating event lifecycle

```python
@dataclass
class NewsEvent:
    id: str
    title: str                     # Event summary title
    keywords: list[str]            # Core keywords
    news_ids: list[str]            # Associated news IDs
    start_time: datetime
    last_seen: datetime
    heat_score: float              # 0-1 heat level
    trend: str                     # "rising", "stable", "declining"
```

Storage: New `intel_events` table.

API:
- `GET /api/v1/intel/cctv/events` — Active hot events
- `GET /api/v1/intel/cctv/events/{id}` — Event detail + associated news

### 2.3 MarketCorrelationService — News-Market Linkage

Analysis:
1. **Time-window correlation**: Within N hours after news publish (default 4h), match sector/index price changes
2. **Sentiment-direction correlation**: Correlation coefficient between news sentiment and market movement
3. **Event impact**: Burst event news volume vs market volatility correlation

```python
@dataclass
class MarketCorrelation:
    news_id: str
    related_stocks: list[dict]     # [{code, name, change_pct, volume_ratio}]
    sector_impact: dict            # {sector: avg_change}
    correlation_score: float       # -1 to 1
```

Dependencies: Uses existing `domain/market/sync/` for historical price data.

Storage: New `intel_market_correlations` table, batch-computed on schedule.

API:
- `GET /api/v1/intel/cctv/market-impact` — Overview of recent news-market correlations
- `GET /api/v1/intel/cctv/market-impact/{news_id}` — Single news market impact detail

### Storage Strategy

| Data | Strategy |
|------|----------|
| Statistics | Real-time computation + optional materialized cache (TTL 1h) |
| Events | Persisted in `intel_events` table, updated by scheduled job |
| Market correlations | Persisted in `intel_market_correlations`, batch-computed every 30min |

## Section 3: AI Processing & Frontend

### 3.1 AI Processing Enhancement

Existing `NewsProcessorService` LLM pipeline extended with CCTV-specific prompt fields:

- `event_type`: Policy / Economy / Society / Tech / Military / Diplomacy
- `market_impact`: High / Medium / Low / None
- `related_sectors`: Predicted affected industry sectors

These fields stored in `metadata` JSONB for downstream analysis services.

### 3.2 Frontend — New Tab in Intel Page

Add 4th tab "央视新闻" to `Intel.tsx` with this layout (top to bottom):

1. **Stats overview bar** — Total count, sentiment pie chart, channel distribution bar chart, time range selector (7d/30d/90d)
2. **Hot event cards** — Collapsible section, each card: title, heat indicator, news count, trend arrow. Click to expand for associated news and correlated stocks
3. **News list** — Each item: title, time, channel tag, sentiment color block, AI summary. Click to expand: full summary, tags, related sectors, market impact. Filters: channel, sentiment, time range
4. **Market correlation chart** — Timeline overlay of major news events vs sector price changes

Styling: Follow existing dark theme with CSS variables and BEM naming (`intel-cctv__stats`, `intel-cctv__event-card`).

### 3.3 API Endpoints Summary

| Endpoint | Method | Status | Description |
|----------|--------|--------|-------------|
| `/intel/cctv/stats` | GET | New | Statistical report |
| `/intel/cctv/events` | GET | New | Hot events list |
| `/intel/cctv/events/{id}` | GET | New | Event detail |
| `/intel/cctv/market-impact` | GET | New | Market impact overview |
| `/intel/cctv/market-impact/{news_id}` | GET | New | Single news correlation |
| `/intel/news?category=cctv_news` | GET | Existing | News list (reused) |
| `/intel/collect` | POST | Existing | Trigger collection (reused) |

## File Changes Summary

### Backend — New Files
- `src/domain/market/intel/providers/cctv_provider.py` — CCTVNewsProvider
- `src/domain/market/intel/analysis/__init__.py`
- `src/domain/market/intel/analysis/stats_service.py`
- `src/domain/market/intel/analysis/event_service.py`
- `src/domain/market/intel/analysis/market_correlation_service.py`
- `src/infra/database/impl/intel_analysis_db.py` — Repository for events & correlations
- `src/api/router/intel_cctv_router.py` — CCTV-specific API endpoints
- `src/api/handler/intel_cctv_handler.py`

### Backend — Modified Files
- `src/domain/market/intel/models.py` — Add `cctv_news` category, `metadata` field
- `src/domain/market/intel/collector.py` — Register CCTVNewsProvider in `build_providers_from_config()`
- `src/domain/market/intel/processor.py` — CCTV-specific prompt and metadata extraction
- `src/infra/database/impl/intel_db.py` — Add `metadata` JSONB column, new indexes
- `src/infra/scheduler.py` — Add CCTV collection and analysis cron jobs
- `conf/config.yaml` — Add CCTV RSS feeds config
- `main.py` — Register new router

### Frontend — Modified Files
- `apps/web/src/pages/Intel.tsx` — Add 4th tab "央视新闻"
- `apps/web/src/pages/Intel.css` — CCTV-specific styles
