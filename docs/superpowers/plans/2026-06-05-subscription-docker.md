# Subscription Sources — Docker Infrastructure Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WeWe RSS Docker service to docker-compose.yml for WeChat public account RSS feed generation.

**Architecture:** Standalone Docker container (`cooderl/wewe-rss`) that provides RSS feeds for WeChat public accounts. The subscription backend calls WeWe RSS's HTTP API to fetch feeds.

**Tech Stack:** Docker Compose, WeWe RSS (https://github.com/cooderl/wewe-rss)

**Spec:** `docs/superpowers/specs/2026-06-05-subscription-sources-design.md`

---

### Task 1: Add WeWe RSS Service to docker-compose.yml

**Files:**
- Modify: `docker/docker-compose.yml`

- [ ] **Step 1: Add WeWe RSS service**

Add the following service block after the `miniflux` service (around line 102, before `volumes:`):

```yaml
  # 5. WeWe RSS - WeChat public account RSS generator
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
      - wewe_rss_data:/app/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
```

Also add the new volume to the `volumes:` section at the bottom:

```yaml
  wewe_rss_data:
```

The complete `volumes:` section should now be:

```yaml
volumes:
  newsnow_data:
  trendradar_output:
  wewe_rss_data:
```

- [ ] **Step 2: Verify docker-compose.yml is valid**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/docker && docker compose config --quiet && echo "OK"`
Expected: `OK`

- [ ] **Step 3: Start the WeWe RSS container**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/docker && docker compose up -d wewe-rss`

Expected: Container starts, `docker compose ps wewe-rss` shows status "Up".

- [ ] **Step 4: Verify WeWe RSS is responding**

Run: `sleep 10 && curl -s -o /dev/null -w "%{http_code}" http://localhost:4000`
Expected: HTTP 200 or 302 (the WeWe RSS web UI loads).

- [ ] **Step 5: Commit**

```bash
git add docker/docker-compose.yml
git commit -m "feat(subscription): add WeWe RSS Docker service for WeChat feeds"
```

---

### Task 2: WeWe RSS Initial Setup Documentation

**Files:** None (documentation notes only)

- [ ] **Step 1: Access WeWe RSS web UI**

Open `http://localhost:4000` in a browser.

Follow the initial setup:
1. The first visit may prompt for a WeChat login/cookie to initialize the service
2. Add WeChat public accounts via the UI to generate RSS feed URLs
3. The feed URL format is: `http://localhost:4000/feed/{account_id}.xml`

- [ ] **Step 2: Verify feed URL format works**

After adding a test account in WeWe RSS UI, verify the feed URL returns valid RSS XML:

```bash
curl -s http://localhost:4000/feed/{account_id}.xml | head -5
```

Expected: Valid XML starting with `<?xml version="1.0" encoding="UTF-8"?>` containing RSS `<rss>` or `<feed>` elements.

> **Note:** WeWe RSS setup requires a one-time WeChat login to obtain session cookies. This is a manual step documented here for reference. The subscription system's WeChat integration depends on accounts being registered in WeWe RSS first.
