/**
 * Alerts page — price alert management
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, CardHeader, CardTitle, CardContent,
  Button, Input, Select, Badge,
} from '@ytrader/common-components';
import { getApiBase } from '../lib/api';
import { PageHeader, StateView } from '../components/ui';
import './Alerts.css';

const API_BASE = getApiBase();

// ── Types ────────────────────────────────────────────────────────────────────

interface Alert {
  id: number;
  symbol: string;
  target_price: number;
  direction: 'above' | 'below';
  status: 'active' | 'triggered' | 'cancelled';
  message?: string;
  triggered_at?: string;
  created_at: string;
}

interface CheckResult {
  symbol: string;
  current_price: number | null;
  triggered_alerts: Alert[];
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatDateTime(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
}

function StatusBadge({ status }: { status: Alert['status'] }) {
  const map: Record<string, { label: string; variant: string }> = {
    active: { label: 'Active', variant: 'info' },
    triggered: { label: 'Triggered', variant: 'success' },
    cancelled: { label: 'Cancelled', variant: 'default' },
  };
  const { label, variant } = map[status] || { label: status, variant: 'default' };
  return <Badge variant={variant as 'success' | 'info' | 'default'}>{label}</Badge>;
}

// ── Main Component ────────────────────────────────────────────────────────────

export const Alerts: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');

  // Create form
  const [symbol, setSymbol] = useState('');
  const [targetPrice, setTargetPrice] = useState('');
  const [direction, setDirection] = useState<'above' | 'below'>('above');
  const [message, setMessage] = useState('');
  const [creating, setCreating] = useState(false);
  const [createMsg, setCreateMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Check result
  const [checkResult, setCheckResult] = useState<CheckResult | null>(null);
  const [checking, setChecking] = useState(false);

  const [error, setError] = useState<string | null>(null);

  // ── P1b 指标告警状态 ──────────────────────────────────────────────
  interface MetricAlert {
    id: number;
    symbol: string;
    metric_kind: string;
    threshold: number;
    direction: 'above' | 'below';
    status: 'active' | 'triggered' | 'cancelled';
    message?: string;
    triggered_at?: string;
    created_at: string;
  }
  const [metricAlerts, setMetricAlerts] = useState<MetricAlert[]>([]);
  const [mSymbol, setMSymbol] = useState('');
  const [mMetric, setMMetric] = useState('pe_ttm');
  const [mThreshold, setMThreshold] = useState('');
  const [mDirection, setMDirection] = useState<'above' | 'below'>('below');
  const [mMessage, setMMessage] = useState('');
  const [mCreating, setMCreating] = useState(false);
  const [metricCheckResult, setMetricCheckResult] = useState<{ symbol: string; triggered_alerts: any[]; current_values: Record<string, number | null> } | null>(null);
  const [mChecking, setMChecking] = useState(false);

  const METRIC_OPTIONS = [
    { value: 'pe_ttm', label: 'PE_TTM' },
    { value: 'pb', label: 'PB' },
    { value: 'ps_ttm', label: 'PS_TTM' },
    { value: 'dv_ttm', label: '股息率%' },
    { value: 'roe', label: 'ROE%' },
  ];

  const loadMetricAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/alerts/metrics`);
      const json = await res.json();
      if (json.code === 0) setMetricAlerts(json.data || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadMetricAlerts(); }, [loadMetricAlerts]);

  const handleCreateMetric = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mSymbol.trim() || !mThreshold) return;
    setMCreating(true);
    try {
      await fetch(`${API_BASE}/alerts/metrics`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: mSymbol.trim().toLowerCase(),
          metric_kind: mMetric,
          threshold: parseFloat(mThreshold),
          direction: mDirection,
          message: mMessage.trim() || undefined,
        }),
      });
      setMSymbol(''); setMThreshold(''); setMMessage('');
      loadMetricAlerts();
    } finally { setMCreating(false); }
  };

  const handleDeleteMetric = async (id: number) => {
    await fetch(`${API_BASE}/alerts/metrics/${id}`, { method: 'DELETE' });
    setMetricAlerts((prev) => prev.filter((a) => a.id !== id));
  };

  const handleCheckMetrics = async (sym: string) => {
    if (!sym.trim()) return;
    setMChecking(true);
    setMetricCheckResult(null);
    try {
      const res = await fetch(`${API_BASE}/alerts/metrics/check/${sym.trim().toLowerCase()}`);
      const json = await res.json();
      if (json.code === 0) setMetricCheckResult(json.data);
    } finally { setMChecking(false); }
  };

  const loadAlerts = useCallback(async (silent = false) => {
    // 首次加载显示 loading；创建后的刷新静默进行，避免整屏 spinner 闪烁。
    if (!silent) setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/alerts`);
      const json = await res.json();
      if (json.code === 0) setAlerts(json.data || []);
      else setError(json.msg || '加载告警失败');
    } catch {
      setError('网络错误，加载告警失败');
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol.trim()) {
      setCreateMsg({ type: 'error', text: 'Symbol is required' });
      return;
    }
    if (!targetPrice || parseFloat(targetPrice) <= 0) {
      setCreateMsg({ type: 'error', text: 'Target price must be > 0' });
      return;
    }
    setCreating(true);
    setCreateMsg(null);
    try {
      const res = await fetch(`${API_BASE}/alerts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol.trim().toLowerCase(),
          target_price: parseFloat(targetPrice),
          direction,
          message: message.trim() || undefined,
        }),
      });
      const json = await res.json();
      if (json.code !== 0) throw new Error(json.detail || 'Failed to create alert');
      setCreateMsg({ type: 'success', text: 'Alert created successfully!' });
      setSymbol('');
      setTargetPrice('');
      setMessage('');
      loadAlerts(true);
    } catch (err: any) {
      setCreateMsg({ type: 'error', text: err.message || 'Failed to create alert' });
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/alerts/${id}`, { method: 'DELETE' });
      const json = await res.json();
      if (json.code !== 0) throw new Error(json.detail || 'Failed to delete alert');
      setAlerts((prev) => prev.filter((a) => a.id !== id));
    } catch (err: any) {
      console.error(err);
    }
  };

  const handleCheck = async (sym: string) => {
    if (!sym.trim()) return;
    setChecking(true);
    setCheckResult(null);
    try {
      const res = await fetch(`${API_BASE}/alerts/check/${sym.trim().toLowerCase()}`);
      const json = await res.json();
      if (json.code === 0) setCheckResult(json.data);
    } catch {
      // ignore
    } finally {
      setChecking(false);
    }
  };

  const filteredAlerts = filter === 'all'
    ? alerts
    : alerts.filter((a) => a.status === filter);

  const activeAlerts = alerts.filter((a) => a.status === 'active');
  const triggeredAlerts = alerts.filter((a) => a.status === 'triggered');

  return (
    <div className="alerts-page">
      <PageHeader
        title="价格告警"
        subtitle="当价格到达目标时获得通知"
        actions={<Button variant="secondary" size="sm" onClick={loadAlerts}>刷新</Button>}
      />

      {/* ── Quick Check ─────────────────────────────────────────────────── */}
      <section className="alerts-page__section">
        <Card>
          <CardHeader>
            <CardTitle>Check Price</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="alerts-page__check-row">
              <Input
                placeholder="Symbol (e.g. sh600000)"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCheck(symbol)}
              />
              <Button variant="secondary" onClick={() => handleCheck(symbol)} disabled={checking}>
                {checking ? 'Checking...' : 'Check'}
              </Button>
            </div>
            {checkResult && (
              <div className="alerts-page__check-result">
                <div className="alerts-page__check-price">
                  <span className="alerts-page__check-label">
                    {checkResult.symbol.toUpperCase()} current price:
                  </span>
                  <span className="alerts-page__check-value num">
                    {checkResult.current_price != null
                      ? `¥${checkResult.current_price.toFixed(2)}`
                      : 'No data'}
                  </span>
                </div>
                {checkResult.triggered_alerts.length > 0 && (
                  <div className="alerts-page__triggered">
                    <strong>{checkResult.triggered_alerts.length} 条告警已触发！</strong>
                    {checkResult.triggered_alerts.map((a) => (
                      <div key={a.id}>
                        #{a.id} {a.direction === 'above' ? '≥' : '≤'} ¥{a.target_price}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      {/* ── Create Alert ────────────────────────────────────────────────── */}
      <section className="alerts-page__section">
        <Card>
          <CardHeader>
            <CardTitle>Create Alert</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="alerts-page__form" onSubmit={handleCreate}>
              <div className="alerts-page__form-row">
                <Input
                  label="Symbol"
                  placeholder="sh600000"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                />
                <Input
                  label="Target Price"
                  type="number"
                  placeholder="12.50"
                  value={targetPrice}
                  onChange={(e) => setTargetPrice(e.target.value)}
                />
                <div className="alerts-page__direction-select">
                  <label className="alerts-page__field-label">Direction</label>
                  <div className="alerts-page__direction-toggle">
                    <button
                      type="button"
                      className={`alerts-page__dir-btn ${direction === 'above' ? 'alerts-page__dir-btn--active-up' : ''}`}
                      onClick={() => setDirection('above')}
                    >
                      ↑ Above
                    </button>
                    <button
                      type="button"
                      className={`alerts-page__dir-btn ${direction === 'below' ? 'alerts-page__dir-btn--active-down' : ''}`}
                      onClick={() => setDirection('below')}
                    >
                      ↓ Below
                    </button>
                  </div>
                </div>
              </div>
              <div className="alerts-page__form-row">
                <Input
                  label="Note (optional)"
                  placeholder="My personal alert note..."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                />
              </div>
              {createMsg && (
                <div className={`alerts-page__feedback alerts-page__feedback--${createMsg.type}`}>
                  {createMsg.text}
                </div>
              )}
              <Button type="submit" variant="primary" disabled={creating}>
                {creating ? 'Creating...' : 'Create Alert'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </section>

      {/* ── Alert List ──────────────────────────────────────────────────── */}
      <section className="alerts-page__section">
        <div className="alerts-page__list-header">
          <h2 className="alerts-page__section-title">
            Alerts ({filteredAlerts.length})
          </h2>
          <div className="alerts-page__filter">
            {['all', 'active', 'triggered', 'cancelled'].map((f) => (
              <button
                key={f}
                className={`alerts-page__filter-btn ${filter === f ? 'alerts-page__filter-btn--active' : ''}`}
                onClick={() => setFilter(f)}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <StateView state="loading" />
        ) : error ? (
          <StateView state="error" text={error} onRetry={() => loadAlerts()} />
        ) : filteredAlerts.length === 0 ? (
          <StateView state="empty" text="暂无告警，可在上方创建" />
        ) : (
          <div className="alerts-page__list">
            {filteredAlerts.map((alert) => (
              <Card key={alert.id} className="alerts-page__alert-card">
                <CardContent>
                  <div className="alerts-page__alert-row">
                    <div className="alerts-page__alert-info">
                      <div className="alerts-page__alert-symbol">
                        <span className="alerts-page__alert-num">#{alert.id}</span>
                        <strong>{alert.symbol.toUpperCase()}</strong>
                        <span className="alerts-page__alert-condition num">
                          {alert.direction === 'above' ? '≥' : '≤'} ¥{alert.target_price.toFixed(2)}
                        </span>
                        <StatusBadge status={alert.status} />
                      </div>
                      {alert.message && (
                        <div className="alerts-page__alert-note">{alert.message}</div>
                      )}
                      <div className="alerts-page__alert-meta">
                        Created: {formatDateTime(alert.created_at)}
                        {alert.triggered_at && (
                          <> · Triggered: {formatDateTime(alert.triggered_at)}</>
                        )}
                      </div>
                    </div>
                    <div className="alerts-page__alert-actions">
                      {alert.status === 'active' && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleCheck(alert.symbol)}
                          disabled={checking}
                        >
                          Check
                        </Button>
                      )}
                      {alert.status !== 'cancelled' && (
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => handleDelete(alert.id)}
                        >
                          Delete
                        </Button>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* ── P1b 指标告警 ─────────────────────────────────────────────── */}
      <section className="alerts-page__section">
        <Card>
          <CardHeader>
            <CardTitle>指标告警（PE/PB/股息率/ROE）</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreateMetric} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <label style={{ fontSize: 11, color: '#888' }}>Symbol</label>
                <Input placeholder="sh600000" value={mSymbol} onChange={(e) => setMSymbol(e.target.value)} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <label style={{ fontSize: 11, color: '#888' }}>指标</label>
                <select value={mMetric} onChange={(e) => setMMetric(e.target.value)}
                  style={{ padding: '6px 8px', background: 'var(--color-background)', border: '1px solid #333', borderRadius: 4, color: '#e0e0e0' }}>
                  {METRIC_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <label style={{ fontSize: 11, color: '#888' }}>阈值</label>
                <Input type="number" placeholder="6.0" value={mThreshold} onChange={(e) => setMThreshold(e.target.value)} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <label style={{ fontSize: 11, color: '#888' }}>方向</label>
                <div style={{ display: 'flex', gap: 4 }}>
                  <button type="button" onClick={() => setMDirection('above')}
                    style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid', borderColor: mDirection === 'above' ? 'var(--color-success)' : '#444', background: mDirection === 'above' ? 'var(--color-success)' : 'transparent', color: '#fff', cursor: 'pointer' }}>≥ 阈值</button>
                  <button type="button" onClick={() => setMDirection('below')}
                    style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid', borderColor: mDirection === 'below' ? 'var(--color-danger)' : '#444', background: mDirection === 'below' ? 'var(--color-danger)' : 'transparent', color: '#fff', cursor: 'pointer' }}>≤ 阈值</button>
                </div>
              </div>
              <Button type="submit" variant="primary" disabled={mCreating}>{mCreating ? '创建中…' : '创建'}</Button>
            </form>

            <div style={{ marginTop: 16, marginBottom: 8 }}>
              <Button variant="secondary" size="sm" onClick={() => handleCheckMetrics(mSymbol)} disabled={mChecking || !mSymbol.trim()}>
                {mChecking ? '检查中…' : '检查当前指标值'}
              </Button>
            </div>
            {metricCheckResult && (
              <div style={{ fontSize: 13, color: '#aaa', marginBottom: 12 }}>
                {metricCheckResult.symbol.toUpperCase()} 当前：
                {Object.entries(metricCheckResult.current_values).map(([k, v]) => (
                  <span key={k} style={{ marginLeft: 12 }}>{k}={v != null ? v.toFixed(2) : '—'}</span>
                ))}
                {metricCheckResult.triggered_alerts.length > 0 && (
                  <span style={{ color: 'var(--color-success)', marginLeft: 12 }}>触发 {metricCheckResult.triggered_alerts.length} 条</span>
                )}
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
              {metricAlerts.length === 0 ? (
                <StateView state="empty" text="暂无指标告警" />
              ) : metricAlerts.map((a) => (
                <div key={a.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'var(--color-background)', borderRadius: 6, border: '1px solid #2a2a2a' }}>
                  <div>
                    <strong style={{ fontFamily: 'monospace', color: '#5b9dff' }}>{a.symbol.toUpperCase()}</strong>
                    <span style={{ marginLeft: 12, color: '#ccc' }}>
                      {METRIC_OPTIONS.find((o) => o.value === a.metric_kind)?.label || a.metric_kind}
                      {' '}{a.direction === 'above' ? '≥' : '≤'}{' '}{a.threshold}
                    </span>
                    {a.message && <span style={{ marginLeft: 12, color: '#888' }}>{a.message}</span>}
                    <span style={{ marginLeft: 12 }}>
                      <StatusBadge status={a.status} />
                    </span>
                  </div>
                  {a.status !== 'cancelled' && (
                    <Button variant="danger" size="sm" onClick={() => handleDeleteMetric(a.id)}>删除</Button>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── Summary ─────────────────────────────────────────────────────── */}
      <section className="alerts-page__section">
        <div className="alerts-page__summary">
          <div className="alerts-page__summary-item">
            <span className="alerts-page__summary-num num">{activeAlerts.length}</span>
            <span className="alerts-page__summary-label">Active</span>
          </div>
          <div className="alerts-page__summary-item">
            <span className="alerts-page__summary-num num">{triggeredAlerts.length}</span>
            <span className="alerts-page__summary-label">Triggered</span>
          </div>
          <div className="alerts-page__summary-item">
            <span className="alerts-page__summary-num num">{alerts.length}</span>
            <span className="alerts-page__summary-label">Total</span>
          </div>
        </div>
      </section>
    </div>
  );
};
