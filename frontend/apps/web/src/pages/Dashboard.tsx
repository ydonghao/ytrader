/**
 * Dashboard page — real account data + equity curve
 */
import React, { useState, useEffect, useRef } from 'react';
import { Card, CardHeader, CardTitle, CardContent, PnlBadge } from '@ytrader/common-components';
import { PageHeader, StateView } from '../components/ui';
import { formatCurrency, formatPercent } from '@ytrader/arch-utils';
import { createChart, IChartApi, ISeriesApi, LineData, Time, LineSeries } from 'lightweight-charts';
import { HeatmapChart } from '@ytrader/trading-market-data';
import './Dashboard.css';

import { getApiBase } from '../lib/api';
import { CHART_COLORS, chartTextTertiary } from '../lib/chartTheme';
const API_BASE = getApiBase();

// ── Types ────────────────────────────────────────────────────────────────────

interface BackendAccount {
  account_id: string;
  total_assets: number;
  cash: number;
  positions_value: number;
  total_profit: number;
  total_profit_pct: number;
  frozen_cash: number;
  margin_used: number;
  status: string;
}

interface BackendPosition {
  id: number;
  symbol: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  updated_at: string;
}

interface BacktestResult {
  id: number;
  strategy_id: string | null;
  strategy_name: string;
  status: string;
  initial_capital: number;
  final_capital: number;
  total_return: number;
  total_return_percent: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  equity_curve: Array<{ timestamp: number; value: number }>;
  trades: Array<unknown>;
  created_at: string;
}

interface MarketOverviewData {
  markets: Array<{
    market: string;
    stocks: number;
    bars: number;
    earliest: string;
    latest: string;
  }>;
  minute: Array<{ interval: string; stocks: number; bars: number }>;
}

interface SystemStatus {
  db: {
    connected: boolean;
    version: string;
    total_tables: number;
  };
  data: {
    markets: Array<{
      market: string;
      symbols: number;
      bars: number;
      earliest: string;
      latest: string;
    }>;
    minute_intervals: string[];
  };
  backfill: {
    last_backfill_time: string | null;
    symbols_covered: number;
    total_symbols: number;
    coverage_pct: number;
  };
  timestamp: string;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function timestampToTime(ts: number): Time {
  return ts as Time;
}

// ── Metric Card (small, inline) ──────────────────────────────────────────────

const MetricCard: React.FC<{
  label: string;
  value: string;
  sub?: string;
  loading?: boolean;
  muted?: boolean;
  accent?: 'default' | 'positive' | 'negative' | 'neutral';
}> = ({ label, value, sub, loading, muted, accent = 'default' }) => (
  <div className={`metric-card${muted ? ' metric-card--muted' : ''}`}>
    <span className="metric-card__label">{label}</span>
    {loading ? (
      <span className="metric-card__value metric-card__value--loading">
        <span className="skeleton" style={{ width: '60%', height: '1.75rem', display: 'inline-block' }} />
      </span>
    ) : (
      <span className={`num metric-card__value metric-card__value--${accent}`}>{value}</span>
    )}
    {sub && <span className="metric-card__sub">{sub}</span>}
  </div>
);

// ── Equity Curve Chart ───────────────────────────────────────────────────────

interface EquityChartProps {
  results: BacktestResult[];
}

const EquityChart: React.FC<EquityChartProps> = ({ results }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const hasResults = results.length > 0;

  // 图表只创建一次（hasResults 变 true 时容器才挂载）；
  // 数据刷新只走 setData——整图重建会闪烁并丢失用户缩放/平移状态
  useEffect(() => {
    if (!hasResults || !containerRef.current) return;
    chartRef.current = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 240,
      layout: {
        background: { color: 'transparent' },
        textColor: chartTextTertiary,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: false },
      crosshair: { mode: 0 },
    });
    seriesRef.current = chartRef.current.addSeries(LineSeries, {
      color: CHART_COLORS[1],
      lineWidth: 1.5,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    const observer = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [hasResults]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const pointsMap = new Map<number, number>();
    for (const r of results) {
      if (!r.equity_curve || r.equity_curve.length === 0) continue;
      for (const pt of r.equity_curve) {
        const ts = pt.timestamp;
        if (!ts) continue;
        const time = (typeof ts === 'number' && ts > 1e12) ? Math.floor(ts / 1000) : (ts as number);
        pointsMap.set(time, pt.value);
      }
    }
    const allPoints: LineData[] = Array.from(pointsMap.entries())
      .sort(([a], [b]) => a - b)
      .map(([time, value]) => ({ time: time as Time, value }));
    series.setData(allPoints);
    if (allPoints.length > 0) {
      chartRef.current?.timeScale().fitContent();
    }
  }, [results]);

  if (results.length === 0) {
    return (
      <StateView state="empty" text="暂无回测结果，运行回测后在此展示权益曲线" />
    );
  }

  return <div ref={containerRef} className="equity-chart" />;
};

// ── Dashboard ────────────────────────────────────────────────────────────────

export const Dashboard: React.FC = () => {
  const [account, setAccount] = useState<BackendAccount | null>(null);
  const [positions, setPositions] = useState<BackendPosition[]>([]);
  const [strategies, setStrategies] = useState<Array<{ id: number; name: string; status: string }>>([]);
  const [backtestResults, setBacktestResults] = useState<BacktestResult[]>([]);

  const [overview, setOverview] = useState<MarketOverviewData | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  const [accountLoading, setAccountLoading] = useState(true);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [systemLoading, setSystemLoading] = useState(true);
  const [pageReady, setPageReady] = useState(false);

  // ── Data fetching ─────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    setAccountLoading(true);
    Promise.all([
      fetch(`${API_BASE}/trade/account`)
        .then((r) => { if (!r.ok) throw new Error('Account unavailable'); return r.json(); })
        .then((j) => j.data)
        .catch(() => null),
      fetch(`${API_BASE}/trade/positions`)
        .then((r) => { if (!r.ok) throw new Error('Positions unavailable'); return r.json(); })
        .then((j) => j.data || [])
        .catch(() => []),
    ]).then(([acc, pos]) => {
      if (!cancelled) { setAccount(acc); setPositions(pos); setAccountLoading(false); }
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/strategy/strategies`)
      .then((r) => { if (!r.ok) return []; return r.json(); })
      .then((j) => { if (!cancelled) setStrategies(j.data || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    // 用列表接口一次性取回最近 10 条（含 equity_curve），替代原先按序号 1..10 的 N+1 抓取。
    fetch(`${API_BASE}/strategy/backtest_results?limit=10`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (cancelled || !j) return;
        const items: any[] = j.data?.items || [];
        const completed = items
          .filter((it) => it?.status === 'completed')
          .map((it) => ({
            ...it,
            final_capital: it.final_equity,
            total_return_percent: it.total_return,
          })) as BacktestResult[];
        setBacktestResults(completed);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    setOverviewLoading(true);
    fetch(`${API_BASE}/market/overview`, { signal: controller.signal })
      .then((r) => r.json())
      .then((json) => {
        if (!cancelled) { setOverview(json.data || null); setOverviewLoading(false); }
      })
      .catch((e) => { if (cancelled || e.name === 'AbortError') return; if (!cancelled) setOverviewLoading(false); })
      .finally(() => clearTimeout(timeout));
    return () => { cancelled = true; clearTimeout(timeout); controller.abort(); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSystemLoading(true);
    fetch(`${API_BASE}/system/status`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((json) => { if (!cancelled) setSystemStatus(json.data || null); })
      .catch(() => { if (!cancelled) setSystemStatus(null); })
      .finally(() => { if (!cancelled) setSystemLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Stagger page entry
  useEffect(() => {
    const t = setTimeout(() => setPageReady(true), 80);
    return () => clearTimeout(t);
  }, []);

  // ── Derived values ───────────────────────────────────────────────────────

  const aShare = overview?.markets?.find((m) => m.market === 'A');
  const totalBars = overview?.markets?.reduce((sum, m) => sum + (m.bars || 0), 0) ?? 0;
  const latestDate = overview?.markets?.[0]?.latest ?? null;
  const progress = systemStatus?.backfill?.coverage_pct ?? 0;
  const completedSyms = systemStatus?.backfill?.symbols_covered ?? 0;
  const totalSyms = systemStatus?.backfill?.total_symbols ?? 0;
  const activeStrategies = strategies.filter((s) => s.status === 'active').length;
  const totalPnlPct = account ? account.total_profit_pct : 0;
  const unrealizedPnlPct = account && account.positions_value > 0
    ? (account.total_profit / account.positions_value) * 100
    : 0;
  const progressTier = progress >= 90 ? 'complete' : progress >= 50 ? 'partial' : 'early';
  const dbConnected = systemStatus?.db?.connected ?? false;
  const dbVersion = systemStatus?.db?.version ?? '';

  return (
    <div className={`dashboard${pageReady ? ' dashboard--ready' : ''}`}>
      {/* Header */}
      <PageHeader
        title="工作台"
        subtitle={
          dbConnected ? (
            <><span className="status-dot status-dot--live" />系统在线</>
          ) : (
            '量化交易平台'
          )
        }
        actions={dbConnected ? <span className="dashboard__db-badge">{dbVersion}</span> : undefined}
      />

      {/* ── Primary metrics (bento, mixed spans) ──────────────────────────── */}
      <section className="dashboard__grid">
        {/* Total Equity — span 2 */}
        <Card className="dashboard__card dashboard__card--span-2 dashboard__card--hero">
          <CardContent>
            <MetricCard
              label="Total Equity"
              value={account ? formatCurrency(account.total_assets) : '-'}
              sub={account ? `${formatCurrency(account.cash)} cash · ${formatCurrency(account.positions_value)} positions` : undefined}
              loading={accountLoading}
              muted={!account}
            />
          </CardContent>
        </Card>

        {/* Total P&L — span 1 */}
        <Card className="dashboard__card dashboard__card--pnl">
          <CardContent>
            <span className="metric-card__label">Total P&L</span>
            {accountLoading ? (
              <span className="metric-card__value metric-card__value--loading">
                <span className="skeleton" style={{ width: '50%', height: '1.75rem', display: 'inline-block' }} />
              </span>
            ) : account ? (
              <>
                <span className={`metric-card__value metric-card__value--${totalPnlPct >= 0 ? 'positive' : 'negative'}`}>
                  <PnlBadge value={totalPnlPct} />
                </span>
                <span className="num metric-card__sub">
                  {account.total_profit >= 0 ? '+' : ''}{formatCurrency(account.total_profit)}
                </span>
              </>
            ) : (
              <span className="metric-card__value metric-card__value--muted">-</span>
            )}
          </CardContent>
        </Card>

        {/* Unrealized P&L — span 1 */}
        <Card className="dashboard__card">
          <CardContent>
            <span className="metric-card__label">Unrealized</span>
            {accountLoading ? (
              <span className="metric-card__value metric-card__value--loading">
                <span className="skeleton" style={{ width: '50%', height: '1.75rem', display: 'inline-block' }} />
              </span>
            ) : account && account.positions_value > 0 ? (
              <>
                <span className={`metric-card__value metric-card__value--${unrealizedPnlPct >= 0 ? 'positive' : 'negative'}`}>
                  <PnlBadge value={unrealizedPnlPct} />
                </span>
                <span className="metric-card__sub">Position value {formatCurrency(account.positions_value)}</span>
              </>
            ) : (
              <>
                <span className="metric-card__value metric-card__value--muted">-</span>
                {account && <span className="metric-card__sub">No open positions</span>}
              </>
            )}
          </CardContent>
        </Card>

        {/* Open Positions */}
        <Card className="dashboard__card">
          <CardContent>
            <MetricCard
              label="Open Positions"
              value={accountLoading ? '...' : String(positions.length)}
              sub={positions.length > 0 ? positions.map((p) => p.symbol).join('  ') : undefined}
              loading={accountLoading}
            />
          </CardContent>
        </Card>

        {/* Active Strategies */}
        <Card className="dashboard__card">
          <CardContent>
            <MetricCard
              label="Strategies"
              value={String(activeStrategies)}
              sub={`${strategies.length} total`}
            />
          </CardContent>
        </Card>

        {/* A-Share Stocks */}
        <Card className="dashboard__card">
          <CardContent>
            <MetricCard
              label="A-Share Stocks"
              value={overviewLoading ? '...' : aShare ? (aShare.stocks ?? 0).toLocaleString() : '-'}
              sub={aShare ? `${(aShare.bars ?? 0).toLocaleString()} daily bars` : undefined}
              loading={overviewLoading}
              muted={!aShare}
            />
          </CardContent>
        </Card>

        {/* Total Bars */}
        <Card className="dashboard__card">
          <CardContent>
            <MetricCard
              label="K-Line Bars"
              value={overviewLoading ? '...' : totalBars > 0 ? totalBars.toLocaleString() : '-'}
              sub={latestDate ? `Latest ${latestDate}` : undefined}
              loading={overviewLoading}
              muted={totalBars === 0}
            />
          </CardContent>
        </Card>

        {/* Data backfill — span 2 */}
        <Card className="dashboard__card dashboard__card--span-2">
          <CardContent>
            <span className="metric-card__label">Data Backfill</span>
            {systemLoading ? (
              <span className="metric-card__value metric-card__value--loading">
                <span className="skeleton" style={{ width: '40%', height: '1.75rem', display: 'inline-block' }} />
              </span>
            ) : systemStatus ? (
              <>
                <span className="metric-card__value">{progress.toFixed(1)}%</span>
                <div className={`progress-bar progress-bar--${progressTier}`}>
                  <div
                    className="progress-bar__fill"
                    style={{ width: `${Math.max(progress, 2)}%` }}
                  />
                </div>
                <span className="metric-card__sub">
                  {completedSyms.toLocaleString()} / {totalSyms.toLocaleString()} symbols
                </span>
              </>
            ) : (
              <span className="metric-card__value metric-card__value--muted">-</span>
            )}
          </CardContent>
        </Card>
      </section>

      {/* ── Charts ────────────────────────────────────────────────────────── */}
      <section className="dashboard__charts">
        <Card className="dashboard__card--chart">
          <CardContent>
            <HeatmapChart />
          </CardContent>
        </Card>

        <Card className="dashboard__card--chart">
          <CardHeader>
            <CardTitle>Equity Curve</CardTitle>
          </CardHeader>
          <CardContent>
            <EquityChart results={backtestResults} />
          </CardContent>
        </Card>
      </section>
    </div>
  );
};
