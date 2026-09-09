/**
 * Reports Page
 * Displays daily/weekly reports with generation controls and Feishu delivery.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { getApiBase } from '../lib/api';
import { useIntervalWhenVisible } from '../hooks/useIntervalWhenVisible';
import {PageHeader, Button, StateView} from '../components/ui';
import './Reports.css';

const API_BASE = getApiBase();

interface Report {
  id: number;
  report_type: 'daily' | 'weekly';
  generated_at: string;
  period_start: string | null;
  period_end: string | null;
  sent_to_feishu: boolean;
  created_at: string;
  portfolio: {
    total_value: number;
    daily_return_pct: number;
    positions_count: number;
    cash_ratio: number;
  };
  performance: {
    total_return_ytd: number;
    total_return_mtd: number;
    sharpe_ratio: number;
    max_drawdown: number;
  };
  trading: {
    orders_today: number;
    filled_today: number;
    pending_today: number;
    canceled_today: number;
  };
  signals: {
    new_signals: number;
    pending_signals: number;
    executed_signals: number;
  };
  market: {
    index_change: string;
    top_gainer: { symbol: string; change: string };
    top_loser: { symbol: string; change: string };
    market_breadth: { advancing: number; declining: number };
  };
  alerts: {
    active_count: number;
    triggered_today: number;
  };
  ai_insight: string;
  recent_backtests: Array<{
    id: number;
    strategy_name: string;
    total_return: number;
    sharpe_ratio: number;
    max_drawdown: number;
    created_at: string;
  }>;
}

interface LatestReports {
  daily: Report | null;
  weekly: Report | null;
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function formatDateShort(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function ReturnBadge({ value }: { value: number }) {
  const isPositive = value >= 0;
  const sign = isPositive ? '+' : '';
  const cls = isPositive ? 'report-metric--positive' : 'report-metric--negative';
  return <span className={`report-metric num ${cls}`}>{sign}{value.toFixed(2)}%</span>;
}

function MetricBox({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="report-metric-box">
      <div className="report-metric-box__label">{label}</div>
      <div className="report-metric-box__value">{value}</div>
      {sub && <div className="report-metric-box__sub">{sub}</div>}
    </div>
  );
}

function ReportCard({ report }: { report: Report }) {
  const {
    report_type,
    generated_at,
    portfolio,
    performance,
    trading,
    signals,
    market,
    alerts,
    ai_insight,
    sent_to_feishu,
    recent_backtests,
  } = report;

  const periodLabel = report_type === 'daily' ? '每日报告' : '每周报告';
  const dateStr = formatDateShort(report.period_end);
  const titleDate = dateStr !== '—' ? dateStr : formatDate(generated_at);

  return (
    <div className="report-card">
      <div className="report-card__header">
        <span className="report-card__title">
          {periodLabel} — {titleDate}
        </span>
        <span className={`report-card__feishu ${sent_to_feishu ? 'report-card__feishu--sent' : ''}`}>
          {sent_to_feishu ? '已发送' : '未发送'}
        </span>
      </div>

      {/* 4 metric boxes */}
      <div className="report-card__metrics">
        <MetricBox
          label="总资产"
          value={`¥${(portfolio?.total_value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
        />
        <MetricBox
          label={report_type === 'daily' ? '日收益' : '周收益'}
          value={<ReturnBadge value={portfolio?.daily_return_pct || 0} />}
        />
        <MetricBox
          label="持仓数"
          value={portfolio?.positions_count ?? 0}
        />
        <MetricBox
          label="新信号"
          value={signals?.new_signals ?? 0}
        />
      </div>

      <div className="report-card__sections">
        {/* Portfolio */}
        <div className="report-section">
          <div className="report-section__title">账户概况</div>
          <div className="report-section__grid">
            <span>总资产</span><span>¥{(portfolio?.total_value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</span>
            <span>{report_type === 'daily' ? '日收益' : '周收益'}</span>
            <ReturnBadge value={portfolio?.daily_return_pct || 0} />
            <span>持仓数</span><span>{portfolio?.positions_count ?? 0}</span>
            <span>现金占比</span><span>{((portfolio?.cash_ratio || 0) * 100).toFixed(0)}%</span>
          </div>
        </div>

        {/* Performance */}
        <div className="report-section">
          <div className="report-section__title">业绩表现</div>
          <div className="report-section__grid">
            <span>年化收益</span><ReturnBadge value={performance?.total_return_ytd || 0} />
            <span>本月收益</span><ReturnBadge value={performance?.total_return_mtd || 0} />
            <span>夏普比率</span><span>{(performance?.sharpe_ratio || 0).toFixed(2)}</span>
            <span>最大回撤</span><ReturnBadge value={performance?.max_drawdown || 0} />
          </div>
        </div>

        {/* Trading */}
        <div className="report-section">
          <div className="report-section__title">交易概况</div>
          <div className="report-section__grid">
            <span>今日下单</span><span>{trading?.orders_today ?? 0}</span>
            <span>成交</span><span>{trading?.filled_today ?? 0}</span>
            <span>待成交</span><span>{trading?.pending_today ?? 0}</span>
            <span>撤单</span><span>{trading?.canceled_today ?? 0}</span>
          </div>
        </div>

        {/* Market */}
        <div className="report-section">
          <div className="report-section__title">市场概况</div>
          <div className="report-section__text">{market?.index_change || '—'}</div>
          <div className="report-section__grid">
            <span>涨幅最大</span>
            <span className="report-positive">
              {market?.top_gainer?.symbol || '—'} ({market?.top_gainer?.change || '—'})
            </span>
            <span>跌幅最大</span>
            <span className="report-negative">
              {market?.top_loser?.symbol || '—'} ({market?.top_loser?.change || '—'})
            </span>
            <span>上涨家数</span><span>{market?.market_breadth?.advancing ?? 0}</span>
            <span>下跌家数</span><span>{market?.market_breadth?.declining ?? 0}</span>
          </div>
        </div>

        {/* Signals + Alerts */}
        <div className="report-section">
          <div className="report-section__title">信号与告警</div>
          <div className="report-section__grid">
            <span>新信号</span><span>{signals?.new_signals ?? 0}</span>
            <span>待执行</span><span>{signals?.pending_signals ?? 0}</span>
            <span>已执行</span><span>{signals?.executed_signals ?? 0}</span>
            <span>活跃告警</span><span>{alerts?.active_count ?? 0}</span>
            <span>今日触发</span><span>{alerts?.triggered_today ?? 0}</span>
          </div>
        </div>

        {/* AI Insight */}
        {ai_insight && (
          <div className="report-section report-section--insight">
            <div className="report-section__title">AI 简评</div>
            <div className="report-section__insight">{ai_insight}</div>
          </div>
        )}

        {/* Recent Backtests */}
        {recent_backtests && recent_backtests.length > 0 && (
          <div className="report-section">
            <div className="report-section__title">最近回测</div>
            {recent_backtests.slice(0, 3).map((bt) => (
              <div key={bt.id} className="report-backtest">
                <span className="report-backtest__name">{bt.strategy_name}</span>
                <ReturnBadge value={bt.total_return} />
                <span className="report-backtest__sharpe">夏普 {bt.sharpe_ratio.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="report-card__footer">
        生成时间: {formatDate(generated_at)}
      </div>
    </div>
  );
}

function EmptyCard({ type, onGenerate, loading }: { type: 'daily' | 'weekly'; onGenerate: () => void; loading: boolean }) {
  return (
    <div className="report-empty">
      <StateView state="empty" text={`暂无${type === 'daily' ? '每日' : '每周'}报告`} />
      <Button variant="primary" size="sm" onClick={onGenerate} loading={loading}>
        {loading ? '生成中...' : `生成${type === 'daily' ? '日' : '周'}报`}
      </Button>
    </div>
  );
}

export function Reports() {
  const [latest, setLatest] = useState<LatestReports>({ daily: null, weekly: null });
  const [history, setHistory] = useState<Report[]>([]);
  const [loadingDaily, setLoadingDaily] = useState(false);
  const [loadingWeekly, setLoadingWeekly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchLatest = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/report/latest`);
      const json = await resp.json();
      if (json.code === 0) {
        setLatest(json.data || { daily: null, weekly: null });
      }
    } catch (e) {
      console.error('fetch latest error', e);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/report/list`);
      const json = await resp.json();
      if (json.code === 0) {
        setHistory(json.data || []);
      }
    } catch (e) {
      console.error('fetch history error', e);
    }
  }, []);

  const generateReport = async (type: 'daily' | 'weekly', sendToFeishu: boolean) => {
    setError(null);
    if (type === 'daily') setLoadingDaily(true);
    else setLoadingWeekly(true);
    try {
      const resp = await fetch(`${API_BASE}/report/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_type: type, send_to_feishu: sendToFeishu }),
      });
      const json = await resp.json();
      if (json.code === 0) {
        await Promise.all([fetchLatest(), fetchHistory()]);
      } else {
        setError(json.msg || '生成失败');
      }
    } catch (e: any) {
      setError(e.message || '网络错误');
    } finally {
      if (type === 'daily') setLoadingDaily(false);
      else setLoadingWeekly(false);
    }
  };

  useEffect(() => {
    fetchLatest();
    fetchHistory();
  }, [fetchLatest, fetchHistory]);

  // 5 分钟轮询；页面隐藏时暂停
  useIntervalWhenVisible(() => {
    fetchLatest();
    fetchHistory();
  }, 5 * 60 * 1000);

  const historyReports = history.filter(
    (r) => r.id !== latest.daily?.id && r.id !== latest.weekly?.id
  );

  return (
    <div className="reports-page">
      <PageHeader
        title="报告中心"
        actions={
          <div className="reports-page__actions">
            <Button variant="primary" size="sm" onClick={() => generateReport('daily', false)} loading={loadingDaily}>
              {loadingDaily ? '生成中...' : '生成日报'}
            </Button>
            <Button variant="primary" size="sm" onClick={() => generateReport('weekly', false)} loading={loadingWeekly}>
              {loadingWeekly ? '生成中...' : '生成周报'}
            </Button>
          </div>
        }
      />

      {error && <div className="reports-page__error">{error}</div>}

      {/* Latest Reports */}
      <div className="reports-latest">
        <h2 className="reports-section__title">最新报告</h2>
        <div className="reports-latest__grid">
          {latest.daily ? (
            <ReportCard report={latest.daily} />
          ) : (
            <EmptyCard type="daily" onGenerate={() => generateReport('daily', false)} loading={loadingDaily} />
          )}
          {latest.weekly ? (
            <ReportCard report={latest.weekly} />
          ) : (
            <EmptyCard type="weekly" onGenerate={() => generateReport('weekly', false)} loading={loadingWeekly} />
          )}
        </div>
      </div>

      {/* History */}
      {historyReports.length > 0 && (
        <div className="reports-history">
          <h2 className="reports-section__title">历史报告</h2>
          <div className="reports-history__list">
            {historyReports.map((r) => (
              <ReportCard key={r.id} report={r} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
