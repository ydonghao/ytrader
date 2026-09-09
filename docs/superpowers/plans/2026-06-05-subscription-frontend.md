# Subscription Sources — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frontend for the subscription management system — Subscriptions page with full CRUD UI, CSS styling, route registration, and sidebar navigation entry.

**Architecture:** React functional component with hooks, card-based dark theme layout consistent with the Intel page. Uses `getApiBase()` for API calls, BEM-like CSS naming.

**Tech Stack:** React 18, TypeScript, CSS (no UI library)

**Spec:** `docs/superpowers/specs/2026-06-05-subscription-sources-design.md`

---

### Task 1: Subscriptions Page Component

**Files:**
- Create: `frontend/apps/web/src/pages/Subscriptions.tsx`

- [ ] **Step 1: Create the Subscriptions page**

```tsx
/**
 * Subscriptions — Manage Bilibili and WeChat RSS subscriptions
 */
import React, {useState, useEffect, useCallback} from 'react';
import './Subscriptions.css';
import {getApiBase} from '../lib/api';

const API_BASE = getApiBase();

// ── Types ──────────────────────────────────────────────
interface Subscription {
  id: number;
  source_type: string;
  source_id: string;
  name: string;
  category: string;
  feed_url: string | null;
  is_active: boolean;
  last_fetched_at: string | null;
  last_error: string | null;
  created_at: string | null;
}

interface SyncResult {
  synced: number;
  fetched: number;
  inserted: number;
  errors: string[];
}

// ── Constants ──────────────────────────────────────────
const SOURCE_TABS = [
  {key: '', label: 'All'},
  {key: 'bilibili_video', label: 'Bilibili Video'},
  {key: 'bilibili_article', label: 'Bilibili Article'},
  {key: 'wechat', label: 'WeChat'},
] as const;

const SOURCE_TYPES = [
  {value: 'bilibili_video', label: 'Bilibili Video'},
  {value: 'bilibili_article', label: 'Bilibili Article'},
  {value: 'wechat', label: 'WeChat'},
] as const;

const CATEGORIES = [
  {value: 'finance', label: 'Finance'},
  {value: 'hotlist', label: 'Hotlist'},
  {value: 'future_tech', label: 'Future Tech'},
] as const;

const SOURCE_TYPE_LABELS: Record<string, string> = {
  bilibili_video: 'Bilibili Video',
  bilibili_article: 'Bilibili Article',
  wechat: 'WeChat',
};

const CATEGORY_LABELS: Record<string, string> = {
  finance: 'Finance',
  hotlist: 'Hotlist',
  future_tech: 'Future Tech',
};

// ── Helpers ────────────────────────────────────────────
function timeAgo(dateStr: string | null): string {
  if (!dateStr) return 'Never';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ── Sub-components ─────────────────────────────────────

function SubscriptionCard({
  sub,
  onToggle,
  onDelete,
}: {
  sub: Subscription;
  onToggle: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!window.confirm(`Delete "${sub.name}"?`)) return;
    setDeleting(true);
    onDelete(sub.id);
  };

  return (
    <div className={`sub-card ${!sub.is_active ? 'sub-card--inactive' : ''}`}>
      <div className="sub-card__header">
        <div className="sub-card__info">
          <span className="sub-card__name">{sub.name}</span>
          <span
            className={`sub-card__type-badge sub-card__type-badge--${sub.source_type}`}
          >
            {SOURCE_TYPE_LABELS[sub.source_type] || sub.source_type}
          </span>
          <span className="sub-card__category-badge">{CATEGORY_LABELS[sub.category] || sub.category}</span>
        </div>
        <div className="sub-card__actions">
          <button
            className={`sub-card__btn sub-card__btn--toggle ${sub.is_active ? 'sub-card__btn--active' : 'sub-card__btn--inactive'}`}
            onClick={() => onToggle(sub.id)}
            title={sub.is_active ? 'Disable' : 'Enable'}
          >
            {sub.is_active ? 'Active' : 'Inactive'}
          </button>
          <button
            className="sub-card__btn sub-card__btn--delete"
            onClick={handleDelete}
            disabled={deleting}
            title="Delete"
          >
            {deleting ? '...' : 'Delete'}
          </button>
        </div>
      </div>
      <div className="sub-card__meta">
        <span className="sub-card__id">ID: {sub.source_id}</span>
        <span className="sub-card__fetch-time">
          Last sync: {timeAgo(sub.last_fetched_at)}
        </span>
        {sub.last_error && (
          <span className="sub-card__error" title={sub.last_error}>
            Error: {sub.last_error.slice(0, 60)}
            {sub.last_error.length > 60 ? '...' : ''}
          </span>
        )}
      </div>
      {sub.feed_url && (
        <div className="sub-card__feed-url" title={sub.feed_url}>
          {sub.feed_url}
        </div>
      )}
    </div>
  );
}

function AddSubscriptionModal({
  open,
  onClose,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [sourceType, setSourceType] = useState('bilibili_video');
  const [sourceId, setSourceId] = useState('');
  const [name, setName] = useState('');
  const [category, setCategory] = useState('finance');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);

    try {
      const resp = await fetch(`${API_BASE}/subscriptions`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          source_type: sourceType,
          source_id: sourceId,
          name,
          category,
        }),
      });
      const json = await resp.json();
      if (json.code === 0) {
        setSourceId('');
        setName('');
        setError('');
        onAdded();
        onClose();
      } else {
        setError(json.msg || 'Failed to add subscription');
      }
    } catch (err: any) {
      setError(err.message || 'Network error');
    } finally {
      setSubmitting(false);
    }
  };

  const sourceIdPlaceholder =
    sourceType === 'wechat'
      ? 'WeChat account biz ID'
      : 'Bilibili UID (e.g. 546195)';

  // Feed URL preview
  let feedPreview = '';
  if (sourceId.trim()) {
    if (sourceType === 'bilibili_video') {
      feedPreview = `http://localhost:1200/bilibili/user/video/${sourceId.trim()}`;
    } else if (sourceType === 'bilibili_article') {
      feedPreview = `http://localhost:1200/bilibili/user/article/${sourceId.trim()}`;
    } else {
      feedPreview = `http://localhost:4000/feed/${sourceId.trim()}.xml`;
    }
  }

  return (
    <div className="sub-modal-overlay" onClick={onClose}>
      <div className="sub-modal" onClick={(e) => e.stopPropagation()}>
        <div className="sub-modal__header">
          <h3 className="sub-modal__title">Add Subscription</h3>
          <button className="sub-modal__close" onClick={onClose}>&times;</button>
        </div>
        <form className="sub-modal__form" onSubmit={handleSubmit}>
          <div className="sub-modal__field">
            <label className="sub-modal__label">Source Type</label>
            <select
              className="sub-modal__select"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
            >
              {SOURCE_TYPES.map((st) => (
                <option key={st.value} value={st.value}>
                  {st.label}
                </option>
              ))}
            </select>
          </div>
          <div className="sub-modal__field">
            <label className="sub-modal__label">Source ID</label>
            <input
              className="sub-modal__input"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              placeholder={sourceIdPlaceholder}
              required
            />
          </div>
          <div className="sub-modal__field">
            <label className="sub-modal__label">Display Name</label>
            <input
              className="sub-modal__input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. 半佛仙人"
              required
            />
          </div>
          <div className="sub-modal__field">
            <label className="sub-modal__label">Category</label>
            <select
              className="sub-modal__select"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          {feedPreview && (
            <div className="sub-modal__preview">
              <span className="sub-modal__preview-label">Feed URL:</span>
              <span className="sub-modal__preview-url">{feedPreview}</span>
            </div>
          )}
          {error && <div className="sub-modal__error">{error}</div>}
          <div className="sub-modal__actions">
            <button
              type="button"
              className="sub-modal__btn sub-modal__btn--cancel"
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="sub-modal__btn sub-modal__btn--submit"
              disabled={submitting || !sourceId.trim() || !name.trim()}
            >
              {submitting ? 'Adding...' : 'Add Subscription'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────

export function Subscriptions() {
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);

  const fetchSubs = useCallback(async () => {
    setLoading(true);
    try {
      const url = activeTab
        ? `${API_BASE}/subscriptions?source_type=${activeTab}`
        : `${API_BASE}/subscriptions`;
      const resp = await fetch(url);
      const json = await resp.json();
      if (json.code === 0) {
        setSubs(json.data || []);
      }
    } catch (err) {
      console.error('Failed to fetch subscriptions:', err);
    } finally {
      setLoading(false);
    }
  }, [activeTab]);

  useEffect(() => {
    fetchSubs();
  }, [fetchSubs]);

  const handleToggle = async (id: number) => {
    try {
      const resp = await fetch(`${API_BASE}/subscriptions/${id}/toggle`, {
        method: 'PUT',
      });
      const json = await resp.json();
      if (json.code === 0) {
        fetchSubs();
      }
    } catch (err) {
      console.error('Toggle failed:', err);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const resp = await fetch(`${API_BASE}/subscriptions/${id}`, {
        method: 'DELETE',
      });
      const json = await resp.json();
      if (json.code === 0) {
        fetchSubs();
      }
    } catch (err) {
      console.error('Delete failed:', err);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const resp = await fetch(`${API_BASE}/subscriptions/sync`, {
        method: 'POST',
      });
      const json = await resp.json();
      if (json.code === 0) {
        setSyncResult(json.data);
        fetchSubs();
      }
    } catch (err) {
      console.error('Sync failed:', err);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="sub-page">
      <div className="sub-header">
        <div className="sub-header__left">
          <h2 className="sub-header__title">Subscriptions</h2>
          <span className="sub-header__count">{subs.length} sources</span>
        </div>
        <div className="sub-header__right">
          <button
            className="sub-header__btn sub-header__btn--sync"
            onClick={handleSync}
            disabled={syncing}
          >
            {syncing ? 'Syncing...' : 'Sync Now'}
          </button>
          <button
            className="sub-header__btn sub-header__btn--add"
            onClick={() => setShowAddModal(true)}
          >
            + Add Subscription
          </button>
        </div>
      </div>

      {/* Sync Result Banner */}
      {syncResult && (
        <div className="sub-sync-result">
          Synced {syncResult.synced} sources: {syncResult.fetched} fetched,{' '}
          {syncResult.inserted} inserted
          {syncResult.errors.length > 0 && (
            <span className="sub-sync-result__errors">
              {' '}({syncResult.errors.length} errors)
            </span>
          )}
          <button
            className="sub-sync-result__close"
            onClick={() => setSyncResult(null)}
          >
            &times;
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="sub-tabs">
        {SOURCE_TABS.map((tab) => (
          <button
            key={tab.key}
            className={`sub-tab ${activeTab === tab.key ? 'sub-tab--active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="sub-content">
        {loading ? (
          <div className="sub-empty">Loading...</div>
        ) : subs.length === 0 ? (
          <div className="sub-empty">
            <p>No subscriptions yet.</p>
            <p>Click "Add Subscription" to get started.</p>
          </div>
        ) : (
          <div className="sub-grid">
            {subs.map((sub) => (
              <SubscriptionCard
                key={sub.id}
                sub={sub}
                onToggle={handleToggle}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>

      {/* Add Modal */}
      <AddSubscriptionModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onAdded={fetchSubs}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify file compiles**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm --filter web exec tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to Subscriptions.tsx (other pre-existing errors are OK)

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/pages/Subscriptions.tsx
git commit -m "feat(subscription): add Subscriptions page component"
```

---

### Task 2: Subscriptions CSS

**Files:**
- Create: `frontend/apps/web/src/pages/Subscriptions.css`

- [ ] **Step 1: Create the Subscriptions CSS file**

```css
/* Subscriptions Page — Dark Theme (matches Intel page) */
.sub-page {
  min-height: 100vh;
  background: #0a0a14;
  color: #e2e8f0;
  font-size: 14px;
}

/* Header */
.sub-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: rgba(30, 30, 50, 0.9);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.sub-header__left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.sub-header__title {
  color: #60a5fa;
  font-weight: bold;
  font-size: 16px;
  margin: 0;
}
.sub-header__count {
  color: #9ca3af;
  font-size: 13px;
}
.sub-header__right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sub-header__btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}
.sub-header__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.sub-header__btn--sync {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  border-color: rgba(59, 130, 246, 0.3);
}
.sub-header__btn--sync:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.25);
}
.sub-header__btn--add {
  background: rgba(139, 92, 246, 0.15);
  color: #a78bfa;
  border-color: rgba(139, 92, 246, 0.3);
}
.sub-header__btn--add:hover {
  background: rgba(139, 92, 246, 0.25);
}

/* Sync Result Banner */
.sub-sync-result {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  background: rgba(59, 130, 246, 0.1);
  border-bottom: 1px solid rgba(59, 130, 246, 0.2);
  font-size: 13px;
  color: #93c5fd;
}
.sub-sync-result__errors {
  color: #f87171;
}
.sub-sync-result__close {
  margin-left: auto;
  background: none;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  font-size: 16px;
  padding: 0 4px;
}

/* Tabs */
.sub-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 20px 0;
}
.sub-tab {
  background: transparent;
  color: #9ca3af;
  border: 1px solid transparent;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}
.sub-tab:hover {
  color: #e2e8f0;
  background: rgba(255, 255, 255, 0.05);
}
.sub-tab--active {
  color: #a78bfa;
  background: rgba(139, 92, 246, 0.15);
  border-color: rgba(139, 92, 246, 0.3);
}

/* Content */
.sub-content {
  padding: 16px 20px;
}
.sub-empty {
  text-align: center;
  padding: 60px 20px;
  color: #6b7280;
}
.sub-empty p {
  margin: 4px 0;
}

/* Grid */
.sub-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 12px;
}

/* Card */
.sub-card {
  background: rgba(15, 15, 30, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 14px 16px;
  transition: all 0.2s;
}
.sub-card:hover {
  border-color: rgba(139, 92, 246, 0.2);
  background: rgba(20, 20, 40, 0.7);
}
.sub-card--inactive {
  opacity: 0.6;
}

.sub-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.sub-card__info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.sub-card__name {
  font-weight: 600;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}
.sub-card__type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}
.sub-card__type-badge--bilibili_video {
  background: rgba(251, 114, 153, 0.15);
  color: #fb7299;
  border: 1px solid rgba(251, 114, 153, 0.3);
}
.sub-card__type-badge--bilibili_article {
  background: rgba(251, 191, 36, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.3);
}
.sub-card__type-badge--wechat {
  background: rgba(74, 222, 128, 0.15);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, 0.3);
}
.sub-card__category-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(96, 165, 250, 0.1);
  color: #60a5fa;
  border: 1px solid rgba(96, 165, 250, 0.2);
}

.sub-card__actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.sub-card__btn {
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
  background: transparent;
}
.sub-card__btn--active {
  color: #4ade80;
  border-color: rgba(74, 222, 128, 0.3);
}
.sub-card__btn--inactive {
  color: #9ca3af;
  border-color: rgba(255, 255, 255, 0.1);
}
.sub-card__btn--delete {
  color: #f87171;
}
.sub-card__btn--delete:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.1);
}

.sub-card__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  font-size: 12px;
  color: #6b7280;
}
.sub-card__error {
  color: #f87171;
}
.sub-card__feed-url {
  margin-top: 6px;
  font-size: 11px;
  color: #4b5563;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Modal ──────────────────────────────────────────── */
.sub-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.sub-modal {
  background: #1a1a2e;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  width: 480px;
  max-width: 90vw;
  max-height: 90vh;
  overflow-y: auto;
}
.sub-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.sub-modal__title {
  margin: 0;
  font-size: 16px;
  color: #e2e8f0;
}
.sub-modal__close {
  background: none;
  border: none;
  color: #9ca3af;
  font-size: 20px;
  cursor: pointer;
  padding: 0 4px;
}
.sub-modal__close:hover {
  color: #e2e8f0;
}
.sub-modal__form {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.sub-modal__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sub-modal__label {
  font-size: 13px;
  color: #9ca3af;
}
.sub-modal__input,
.sub-modal__select {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
}
.sub-modal__input:focus,
.sub-modal__select:focus {
  border-color: rgba(139, 92, 246, 0.5);
}
.sub-modal__select option {
  background: #1a1a2e;
  color: #e2e8f0;
}
.sub-modal__preview {
  padding: 8px 12px;
  background: rgba(139, 92, 246, 0.05);
  border: 1px solid rgba(139, 92, 246, 0.15);
  border-radius: 6px;
  font-size: 12px;
}
.sub-modal__preview-label {
  color: #9ca3af;
  margin-right: 4px;
}
.sub-modal__preview-url {
  color: #a78bfa;
  word-break: break-all;
}
.sub-modal__error {
  color: #f87171;
  font-size: 13px;
}
.sub-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
.sub-modal__btn {
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}
.sub-modal__btn--cancel {
  background: transparent;
  color: #9ca3af;
}
.sub-modal__btn--cancel:hover {
  color: #e2e8f0;
}
.sub-modal__btn--submit {
  background: rgba(139, 92, 246, 0.2);
  color: #a78bfa;
  border-color: rgba(139, 92, 246, 0.3);
}
.sub-modal__btn--submit:hover:not(:disabled) {
  background: rgba(139, 92, 246, 0.3);
}
.sub-modal__btn--submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/apps/web/src/pages/Subscriptions.css
git commit -m "feat(subscription): add Subscriptions page CSS (dark theme)"
```

---

### Task 3: Route Registration (App.tsx)

**Files:**
- Modify: `frontend/apps/web/src/App.tsx`

- [ ] **Step 1: Add Subscriptions import**

After the `BlogDraft` import (line 27), add:

```tsx
import {Subscriptions} from './pages/Subscriptions';
```

- [ ] **Step 2: Add route**

After the `/blog` route (line 61), add:

```tsx
        <Route path="/subscriptions" element={<Subscriptions />} />
```

- [ ] **Step 3: Verify compilation**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm --filter web exec tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to App.tsx or Subscriptions

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/App.tsx
git commit -m "feat(subscription): add /subscriptions route in App.tsx"
```

---

### Task 4: Sidebar Entry (Layout.tsx)

**Files:**
- Modify: `frontend/apps/web/src/components/Layout.tsx`

- [ ] **Step 1: Add subscriptions icon**

After the `blog` icon definition (around line 112), add:

```tsx
  subscriptions: (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4h12M2 8h12M2 12h8" />
      <circle cx="13.5" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  ),
```

- [ ] **Step 2: Add sidebar nav item**

In the `navGroups` array, in the `Research` group (around line 191), add after the `blog` entry:

```tsx
      {path: '/subscriptions', label: 'Subscriptions', icon: Icon.subscriptions},
```

- [ ] **Step 3: Verify the dev server renders**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm --filter web dev`

Open `http://localhost:12000` in a browser. Verify:
1. "Subscriptions" appears in the sidebar under "Research"
2. Clicking it navigates to `/subscriptions`
3. The page shows "Subscriptions" header with "Add Subscription" button and empty state

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(subscription): add Subscriptions entry in sidebar navigation"
```

---

### Task 5: End-to-End UI Test

**Files:** None (manual testing with backend running)

- [ ] **Step 1: Start both backend and frontend**

Terminal 1:
```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python main.py
```

Terminal 2:
```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm --filter web dev
```

- [ ] **Step 2: Navigate to Subscriptions page**

Open `http://localhost:12000/subscriptions`

Expected: Page shows "Subscriptions" header, "Add Subscription" and "Sync Now" buttons, tab bar, and empty state text.

- [ ] **Step 3: Add a subscription**

Click "Add Subscription", fill in:
- Source Type: Bilibili Video
- Source ID: `546195`
- Display Name: `半佛仙人`
- Category: Finance

Click "Add Subscription".

Expected: Modal closes, card appears with name "半佛仙人", "Bilibili Video" badge, "Active" status.

- [ ] **Step 4: Toggle subscription**

Click "Inactive" button on the card.

Expected: Button changes to "Active", card opacity dims.

- [ ] **Step 5: Delete subscription**

Click "Delete" on the card, confirm in dialog.

Expected: Card disappears.

- [ ] **Step 6: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix(subscription): frontend adjustments from testing"
```
