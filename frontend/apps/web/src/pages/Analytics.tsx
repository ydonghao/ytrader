/**
 * Analytics page — comprehensive trading performance analytics
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, CardHeader, CardTitle, CardContent,
  Badge, Button,
} from '@ytrader/common-components';
import { createChart, IChartApi, ISeriesApi, LineData, HistogramData, Time } from 'lightweight-charts';
import { formatCurrency, formatPercent } from '@ytrader/arch-utils';
import { MonthlyHeatmap } from '../components/MonthlyHeatmap';
import { AttributionChart } from '../components/AttributionChart';
import { getApiBase } from '../lib/api';
import { useIntervalWhenVisible } from '../hooks/useIntervalWhenVisible';
import { PageHeader, StateView } from '../components/ui';
import './Analytics.css';
import { CHART_COLORS, chartTextSecondary } from '../lib/chartTheme';

const API_BASE = getApiBase();

// ── Types ────────────────────────────────────────────────────────────────────

interface AccountMetrics {
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

interface Position {
  id: number;
  symbol: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  updated_at: string;
}

interface BacktestSummary {
  id: number;
  strategy_name: string;
  status: string;
  total_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  final_capital: number;
  initial_capital: number;
  created_at: string;
}

interface MarketCoverage {
  market: string;
  symbols: number;
  bars: number;
  earliest: string | null;
  latest: string | null;
}

interface SchedulerStatus {
  running: boolean;
  jobs: Array<{ id: string; next_run: string }>;
  last_run: string | null;
  last_run_ok: boolean;
  last_error: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function MetricCard({ label, value, sub, trend }: {
  label: string;
  value: string;
  sub?: string;
  trend?: 'up' | 'down' | 'neutral';
}) {
  return (
    <div className={`analytics-metric analytics-metric--${trend || 'neutral'}`}>
      <div className="analytics-metric__label">{label}</div>
      <div className="analytics-metric__value">{value}</div>
      {sub && <div className="analytics-metric__sub">{sub}</div>}
    </div>
  );
}

function PnlBadge({ value }: { value: number }) {
  const isPositive = value > 0;
  const isNeutral = value === 0;
  return (
    <span className={`pnl-badge pnl-badge--${isNeutral ? 'neutral' : isPositive ? 'positive' : 'negative'}`}>
      {isPositive ? '+' : ''}{formatCurrency(value)}
    </span>
  );
}

// ── Equity Curve Chart ────────────────────────────────────────────────────────

function EquityCurveChart({ backtests }: { backtests: BacktestSummary[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const completed = backtests.filter((b) => b.status === 'completed');
    if (completed.length === 0) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: chartTextSecondary,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(161, 161, 166, 0.15)' },
        horzLines: { color: 'rgba(161, 161, 166, 0.15)' },
      },
      rightPriceScale: { borderColor: 'rgba(161, 161, 166, 0.2)' },
      timeScale: {
        borderColor: 'rgba(161, 161, 166, 0.2)',
        timeVisible: true,
      },
      height: 220,
    });
    chartRef.current = chart;

    // Build cumulative equity curve from all completed backtests
    const allSeries: { time: Time; value: number }[] = [];
    completed.forEach((bt) => {
      const returnPct = bt.total_return / 100; // convert percent to ratio
      const initial = bt.initial_capital || 1_000_000;
      const final = initial * (1 + returnPct);
      // approximate time points
      const startMs = new Date(bt.created_at).getTime();
      const endMs = Date.now();
      allSeries.push({ time: (startMs / 1000) as Time, value: initial });
      allSeries.push({ time: (endMs / 1000) as Time, value: final });
    });

    allSeries.sort((a, b) => Number(a.time) - Number(b.time));

    if (allSeries.length === 0) return;

    const series = chart.addLineSeries({
      color: CHART_COLORS[0],
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(allSeries as LineData[]);
    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [backtests]);

  return <div ref={containerRef} className="analytics-chart__container" />;
}

// ── Drawdown Chart ────────────────────────────────────────────────────────────

function DrawdownChart({ backtests }: { backtests: BacktestSummary[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const completed = backtests.filter((b) => b.status === 'completed');
    if (completed.length === 0) return;

    const maxDD = Math.max(...completed.map((b) => Math.abs(b.max_drawdown || 0)));
    if (maxDD === 0) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: chartTextSecondary,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(161, 161, 166, 0.15)' },
        horzLines: { color: 'rgba(161, 161, 166, 0.15)' },
      },
      rightPriceScale: { borderColor: 'rgba(161, 161, 166, 0.2)' },
      timeScale: {
        borderColor: 'rgba(161, 161, 166, 0.2)',
        timeVisible: true,
      },
      height: 160,
    });

    const data: HistogramData[] = completed.map((bt) => ({
      time: (new Date(bt.created_at).getTime() / 1000) as Time,
      value: -(bt.max_drawdown || 0),
      color: 'rgba(255, 69, 58, 0.6)',
    }));

    const series = chart.addHistogramSeries({
      color: 'rgba(255, 69, 58, 0.6)',
      priceFormat: { type: 'percent' },
    });
    series.setData(data);
    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [backtests]);

  return <div ref={containerRef} className="analytics-chart__container analytics-chart__container--sm" />;
}

// ── Main Component ────────────────────────────────────────────────────────────

export const Analytics: React.FC = () => {
  const [account, setAccount] = useState<AccountMetrics | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [backtests, setBacktests] = useState<BacktestSummary[]>([]);
  const [coverage, setCoverage] = useState<MarketCoverage[]>([]);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  const load = useCallback(async (silent = false) => {
    // 首次加载才翻转全屏 loading；定时轮询静默刷新，避免 30s 一次的全屏闪烁。
    if (!silent) setLoading(true);
    try {
      // 五路并行（回测历史原本串行在 Promise.all 之后，白等一轮 RTT）
      const [accRes, posRes, schedRes, sysRes, btJson] = await Promise.all([
        fetch(`${API_BASE}/trade/account`).then((r) => r.json()),
        fetch(`${API_BASE}/trade/positions`).then((r) => r.json()),
        fetch(`${API_BASE}/system/scheduler`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/system/status`).then((r) => r.json()),
        // backtest history optional，失败不拖垮其余数据
        fetch(`${API_BASE}/strategy/backtest_results?limit=10`)
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null),
      ]);

      if (accRes.code === 0) setAccount(accRes.data);
      if (posRes.code === 0) setPositions(posRes.data || []);
      if (schedRes && schedRes.code === 0) setScheduler(schedRes.data);
      if (sysRes.code === 0) {
        setCoverage(sysRes.data?.data?.markets || []);
      }
      if (btJson && btJson.code === 0) {
        // 列表接口返回 {data:{items:[...]}}，取 items 为数组
        const items = btJson.data?.items || btJson.data || [];
        setBacktests(Array.isArray(items) ? items : []);
      }
    } catch (e) {
      console.error('Analytics load error:', e);
    } finally {
      setLoading(false);
      setLastUpdate(new Date());
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // 30s 静默轮询；页面隐藏时暂停
  useIntervalWhenVisible(() => load(true), 30000);

  if (loading) {
    return (
      <div className="analytics">
        <PageHeader title="数据分析" />
        <StateView state="loading" text="正在加载分析数据…" />
      </div>
    );
  }

  const completedBacktests = backtests.filter((b) => b.status === 'completed');
  const totalTrades = completedBacktests.reduce((sum, b) => sum + (b.total_trades || 0), 0);
  const avgWinRate = completedBacktests.length > 0
    ? completedBacktests.reduce((sum, b) => sum + (b.win_rate || 0), 0) / completedBacktests.length
    : 0;
  const avgSharpe = completedBacktests.length > 0
    ? completedBacktests.reduce((sum, b) => sum + (b.sharpe_ratio || 0), 0) / completedBacktests.length
    : 0;
  const avgMaxDD = completedBacktests.length > 0
    ? completedBacktests.reduce((sum, b) => sum + (b.max_drawdown || 0), 0) / completedBacktests.length
    : 0;

  return (
    <div className="analytics">
      <PageHeader
        title="数据分析"
        subtitle={`交易绩效总览 · 更新于 ${lastUpdate.toLocaleTimeString()}`}
        actions={<Button variant="secondary" size="sm" onClick={load}>刷新</Button>}
      />

      {/* ── Account Metrics ─────────────────────────────────────────────── */}
      <section className="analytics__section">
        <h2 className="analytics__section-title">Account Overview</h2>
        <div className="analytics-metrics">
          <MetricCard
            label="Total Assets"
            value={account ? formatCurrency(account.total_assets) : '—'}
            sub={account ? `${formatCurrency(account.cash)} cash` : undefined}
            trend={account && account.total_profit > 0 ? 'up' : account && account.total_profit < 0 ? 'down' : 'neutral'}
          />
          <MetricCard
            label="Total P&L"
            value={account ? `${account.total_profit >= 0 ? '+' : ''}${formatCurrency(account.total_profit)}` : '—'}
            sub={account ? `${account.total_profit_pct >= 0 ? '+' : ''}${account.total_profit_pct.toFixed(2)}%` : undefined}
            trend={account && account.total_profit > 0 ? 'up' : 'down'}
          />
          <MetricCard
            label="Positions"
            value={String(positions.length)}
            sub={account ? `${formatCurrency(account.positions_value)} invested` : undefined}
          />
          <MetricCard
            label="Unrealized P&L"
            value={account ? `${account.total_profit >= 0 ? '+' : ''}${formatCurrency(account.total_profit)}` : '—'}
            sub="Live positions"
            trend={account && account.total_profit > 0 ? 'up' : 'down'}
          />
        </div>
      </section>

      {/* ── Monthly Market Heatmap ──────────────────────────────────────── */}
      <section className="analytics__section">
        <MonthlyHeatmap />
      </section>

      {/* ── Portfolio Attribution ─────────────────────────────────────── */}
      <section className="analytics__section">
        <AttributionChart />
      </section>

      {/* ── Strategy Performance ────────────────────────────────────────── */}
      <section className="analytics__section">
        <h2 className="analytics__section-title">Strategy Performance</h2>
        {completedBacktests.length === 0 ? (
          <Card>
          <CardContent>
            <StateView state="empty" text="暂无已完成的回测，可先在策略页运行回测" />
          </CardContent>
          </Card>
        ) : (
          <>
            <div className="analytics-metrics">
              <MetricCard
                label="Backtests"
                value={String(completedBacktests.length)}
                sub={`${totalTrades} total trades`}
              />
              <MetricCard
                label="Avg Sharpe"
                value={avgSharpe.toFixed(2)}
                sub="Risk-adjusted return"
                trend={avgSharpe > 1 ? 'up' : avgSharpe < 0 ? 'down' : 'neutral'}
              />
              <MetricCard
                label="Avg Win Rate"
                value={`${avgWinRate.toFixed(1)}%`}
                sub="Win rate across strategies"
                trend={avgWinRate > 50 ? 'up' : 'down'}
              />
              <MetricCard
                label="Avg Max Drawdown"
                value={`${avgMaxDD.toFixed(2)}%`}
                sub="Average peak-to-trough"
                trend={avgMaxDD < 10 ? 'up' : 'down'}
              />
            </div>

            {/* Equity Curve */}
            <Card className="analytics-chart-card">
              <CardHeader>
                <CardTitle>Equity Curve</CardTitle>
              </CardHeader>
              <CardContent>
                <EquityCurveChart backtests={completedBacktests} />
              </CardContent>
            </Card>

            {/* Drawdown */}
            <Card className="analytics-chart-card">
              <CardHeader>
                <CardTitle>Max Drawdown per Backtest</CardTitle>
              </CardHeader>
              <CardContent>
                <DrawdownChart backtests={completedBacktests} />
              </CardContent>
            </Card>

            {/* Backtest History Table */}
            <Card>
              <CardHeader>
                <CardTitle>Backtest History</CardTitle>
              </CardHeader>
              <CardContent>
                <table className="analytics-table">
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th>Date</th>
                      <th>Trades</th>
                      <th>Return</th>
                      <th>Sharpe</th>
                      <th>Max DD</th>
                      <th>Win Rate</th>
                      <th>Final Capital</th>
                    </tr>
                  </thead>
                  <tbody>
                    {completedBacktests.map((bt) => (
                      <tr key={bt.id}>
                        <td>{bt.strategy_name}</td>
                        <td>{new Date(bt.created_at).toLocaleDateString()}</td>
                        <td>{bt.total_trades}</td>
                        <td>
                          <span className={`num ${bt.total_return >= 0 ? 'text-positive' : 'text-negative'}`}>
                            {bt.total_return >= 0 ? '+' : ''}{bt.total_return.toFixed(2)}%
                          </span>
                        </td>
                        <td>{bt.sharpe_ratio.toFixed(2)}</td>
                        <td className="num text-negative">{bt.max_drawdown.toFixed(2)}%</td>
                        <td>{(bt.win_rate || 0).toFixed(1)}%</td>
                        <td>{formatCurrency(bt.final_capital)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </>
        )}
      </section>

      {/* ── Market Data Coverage ───────────────────────────────────────── */}
      <section className="analytics__section">
        <h2 className="analytics__section-title">Market Data Coverage</h2>
        <div className="analytics-metrics">
          {coverage.map((m) => (
            <MetricCard
              key={m.market}
              label={m.market.toUpperCase()}
              value={String(m.symbols)}
              sub={`${m.bars.toLocaleString()} bars · ${m.latest || 'N/A'}`}
            />
          ))}
          {scheduler && (
            <MetricCard
              label="Scheduler"
              value={scheduler.running ? 'Active' : 'Stopped'}
              sub={scheduler.jobs?.[0]?.next_run ? `Next: ${scheduler.jobs[0].next_run.split('+')[0]}` : undefined}
              trend={scheduler.running ? 'up' : 'down'}
            />
          )}
        </div>
      </section>

      {/* ── Open Positions ──────────────────────────────────────────────── */}
      {positions.length > 0 && (
        <section className="analytics__section">
          <h2 className="analytics__section-title">Open Positions ({positions.length})</h2>
          <Card>
            <CardContent>
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Qty</th>
                    <th>Avg Price</th>
                    <th>Current</th>
                    <th>Unrealized P&L</th>
                    <th>P&L %</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const pnlPct = p.avg_price > 0 ? ((p.current_price - p.avg_price) / p.avg_price * 100) : 0;
                    return (
                      <tr key={p.id}>
                        <td>{p.symbol}</td>
                        <td>{p.quantity}</td>
                        <td>{formatCurrency(p.avg_price)}</td>
                        <td>{formatCurrency(p.current_price)}</td>
                        <td><PnlBadge value={p.unrealized_pnl} /></td>
                        <td className={`num ${pnlPct >= 0 ? 'text-positive' : 'text-negative'}`}>
                          {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </section>
      )}
    </div>
  );
};
