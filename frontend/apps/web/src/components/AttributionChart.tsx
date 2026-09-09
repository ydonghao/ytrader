/**
 * AttributionChart — Portfolio attribution analysis visualization
 * Fetches from GET /api/v1/portfolio/attribution
 * Shows: Top Contributors, Sector Allocation, Attribution Summary Table
 */
import React, { useState, useEffect, useCallback } from 'react';
import { getApiBase } from '../lib/api';
import './AttributionChart.css';

interface PositionAttribution {
  symbol: string;
  name: string;
  sector: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  market_value: number;
  weight: number;
  daily_return_pct: number;
  pnl_contribution: number;
  unrealized_pnl: number;
}

interface SectorAttribution {
  sector: string;
  total_weight: number;
  avg_return_pct: number;
  pnl_contribution: number;
  allocation_effect: number;
  selection_effect: number;
  position_count: number;
}

interface AttributionData {
  total_value: number;
  daily_pnl_pct: number;
  benchmark_return: number;
  positions: PositionAttribution[];
  sectors: SectorAttribution[];
  top_contributors: PositionAttribution[];
  top_detractors: PositionAttribution[];
  is_demo: boolean;
}

function formatCurrency(v: number): string {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPct(v: number, decimals = 2): string {
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(decimals)}%`;
}

function fmtContrib(v: number): string {
  return v >= 0 ? `+${(v * 100).toFixed(3)}%` : `${(v * 100).toFixed(3)}%`;
}

function BarRow({ label, value, maxAbs, colorClass }: {
  label: string;
  value: number;
  maxAbs: number;
  colorClass: string;
}) {
  const pct = maxAbs > 0 ? Math.abs(value) / maxAbs : 0;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: '0.35rem 0' }}>
      <span style={{ width: '70px', fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={label}>
        {label}
      </span>
      <div style={{ flex: 1, background: '#222', borderRadius: '3px', height: '16px', position: 'relative', overflow: 'hidden' }}>
        <div
          style={{
            width: `${pct * 100}%`,
            background: colorClass,
            borderRadius: '3px',
            height: '100%',
            transition: 'width 0.3s ease',
          }}
        />
      </div>
      <span style={{ width: '55px', fontSize: '0.7rem', textAlign: 'right', color: value >= 0 ? 'var(--color-up)' : 'var(--color-down)' }}>
        {value >= 0 ? '+' : ''}{value.toFixed(2)}%
      </span>
    </div>
  );
}

function SectorBarRow({ sector, weight, pnlContrib }: {
  sector: string;
  weight: number;
  pnlContrib: number;
}) {
  const barColor = pnlContrib >= 0 ? 'var(--color-up)' : 'var(--color-down)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: '0.35rem 0' }}>
      <span style={{ width: '130px', fontSize: '0.68rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={sector}>
        {sector}
      </span>
      <div style={{ flex: 1, background: '#222', borderRadius: '3px', height: '16px', position: 'relative' }}>
        <div
          style={{
            width: `${Math.min(weight * 100, 100)}%`,
            background: barColor,
            borderRadius: '3px',
            height: '100%',
            opacity: 0.7,
            transition: 'width 0.3s ease',
          }}
        />
      </div>
      <span style={{ width: '55px', fontSize: '0.7rem', textAlign: 'right' }}>
        {(weight * 100).toFixed(1)}%
      </span>
    </div>
  );
}

function AttributionTable({ sectors }: { sectors: SectorAttribution[] }) {
  return (
    <table className="attribution-table">
      <thead>
        <tr>
          <th>Sector</th>
          <th>Weight</th>
          <th>Return</th>
          <th>Allocation</th>
          <th>Selection</th>
          <th>Contribution</th>
        </tr>
      </thead>
      <tbody>
        {sectors.map((s) => (
          <tr key={s.sector}>
            <td>{s.sector}</td>
            <td>{(s.total_weight * 100).toFixed(1)}%</td>
            <td className={s.avg_return_pct >= 0 ? 'text-positive' : 'text-negative'}>
              {formatPct(s.avg_return_pct, 2)}
            </td>
            <td className={s.allocation_effect >= 0 ? 'text-positive' : 'text-negative'}>
              {fmtContrib(s.allocation_effect)}
            </td>
            <td className={s.selection_effect >= 0 ? 'text-positive' : 'text-negative'}>
              {fmtContrib(s.selection_effect)}
            </td>
            <td className={s.pnl_contribution >= 0 ? 'text-positive' : 'text-negative'}>
              {fmtContrib(s.pnl_contribution)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export const AttributionChart: React.FC = () => {
  const [data, setData] = useState<AttributionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const base = getApiBase();
      const res = await fetch(`${base}/portfolio/attribution`);
      const json = await res.json();
      if (json.code === 0) {
        setData(json.data);
      } else {
        setError(json.msg || 'Failed to load');
      }
    } catch (e: any) {
      setError(e.message || 'Network error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <div className="attribution__loading">加载归因分析...</div>;
  if (error) return <div className="attribution__error">{error}</div>;
  if (!data) return null;

  const { total_value, daily_pnl_pct, benchmark_return, sectors, top_contributors, top_detractors, is_demo } = data;

  const maxContrib = Math.max(
    ...top_contributors.map((p) => Math.abs(p.daily_return_pct)),
    ...top_detractors.map((p) => Math.abs(p.daily_return_pct)),
    0.01,
  );

  return (
    <div className="attribution">
      {is_demo && (
        <div className="attribution__demo-note">示例数据（当前无真实持仓）</div>
      )}

      {/* Header summary */}
      <div className="attribution__summary">
        <div className="attribution__summary-item">
          <span className="attribution__summary-label">总市值</span>
          <span className="attribution__summary-value">¥{formatCurrency(total_value)}</span>
        </div>
        <div className="attribution__summary-item">
          <span className="attribution__summary-label">今日盈亏</span>
          <span className={`attribution__summary-value ${daily_pnl_pct >= 0 ? 'text-positive' : 'text-negative'}`}>
            {formatPct(daily_pnl_pct * 100, 3)}
          </span>
        </div>
        <div className="attribution__summary-item">
          <span className="attribution__summary-label">基准收益</span>
          <span className="attribution__summary-value">{formatPct(benchmark_return, 3)}</span>
        </div>
        <div className="attribution__summary-item">
          <span className="attribution__summary-label">超额收益</span>
          <span className={`attribution__summary-value ${(daily_pnl_pct - benchmark_return) >= 0 ? 'text-positive' : 'text-negative'}`}>
            {formatPct((daily_pnl_pct - benchmark_return) * 100, 3)}
          </span>
        </div>
      </div>

      <div className="attribution__grid">
        {/* Top Contributors */}
        <div className="attribution__panel">
          <div className="attribution__panel-title">Top Contributors</div>
          {top_contributors.length === 0 ? (
            <div className="attribution__empty">暂无正贡献</div>
          ) : (
            top_contributors.map((p) => (
              <BarRow
                key={p.symbol}
                label={p.symbol}
                value={p.daily_return_pct}
                maxAbs={maxContrib}
                colorClass="bar-positive"
              />
            ))
          )}
        </div>

        {/* Top Detractors */}
        <div className="attribution__panel">
          <div className="attribution__panel-title">Top Detractors</div>
          {top_detractors.filter(p => p.daily_return_pct < 0).length === 0 ? (
            <div className="attribution__empty">暂无负贡献</div>
          ) : (
            top_detractors
              .filter((p) => p.daily_return_pct < 0)
              .map((p) => (
                <BarRow
                  key={p.symbol}
                  label={p.symbol}
                  value={p.daily_return_pct}
                  maxAbs={maxContrib}
                  colorClass="bar-negative"
                />
              ))
          )}
        </div>

        {/* Sector Allocation */}
        <div className="attribution__panel attribution__panel--wide">
          <div className="attribution__panel-title">Sector Allocation</div>
          {sectors.map((s) => (
            <SectorBarRow
              key={s.sector}
              sector={s.sector}
              weight={s.total_weight}
              pnlContrib={s.pnl_contribution}
            />
          ))}
        </div>
      </div>

      {/* Attribution Summary Table */}
      <div className="attribution__panel attribution__panel--full">
        <div className="attribution__panel-title">Attribution Summary</div>
        <AttributionTable sectors={sectors} />
      </div>
    </div>
  );
};
