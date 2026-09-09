/**
 * MonthlyHeatmap — market monthly returns heatmap
 * Fetches data from GET /market/monthly-heatmap and renders
 * a GitHub-contribution-grid-style heatmap with color intensity
 * showing avg daily return and market breadth (gainer %).
 */
import React, { useState, useEffect, useCallback } from 'react';
import { getApiBase } from '../lib/api';
import './MonthlyHeatmap.css';

interface HeatmapRow {
  year: number;
  month: number;
  month_label: string;
  avg_return_pct: number | null;
  gainer_pct: number | null;
  stock_count: number;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function getColor(value: number | null): string {
  if (value === null || value === undefined) return 'var(--heatmap-empty, #1a1a2e)';
  // value is avg daily return in percent
  // Map to color: red for negative, green for positive
  const abs = Math.min(Math.abs(value) * 20, 1); // scale factor for intensity
  if (value > 0) {
    const g = Math.round(100 + 155 * abs);
    const r = Math.round(50 * (1 - abs));
    return `rgb(${r}, ${g}, 80)`;
  } else if (value < 0) {
    const r = Math.round(180 + 75 * abs);
    const g = Math.round(30 * (1 - abs));
    return `rgb(${r}, ${g}, 60)`;
  }
  return 'var(--heatmap-flat, #2a2a3e)';
}

function getTextColor(value: number | null): string {
  if (value === null) return '#555';
  const abs = Math.abs(value);
  return abs > 0.15 ? '#fff' : '#ccc';
}

function formatReturn(value: number | null): string {
  if (value === null) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function gainerLabel(gainerPct: number | null): string {
  if (gainerPct === null) return '—';
  return `${gainerPct.toFixed(0)}% ↑`;
}

interface MonthlyHeatmapProps {
  apiBase?: string;
}

export const MonthlyHeatmap: React.FC<MonthlyHeatmapProps> = ({ apiBase }) => {
  const [data, setData] = useState<HeatmapRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ row: HeatmapRow; x: number; y: number } | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const base = apiBase || getApiBase();
      const res = await fetch(`${base}/market/monthly-heatmap?months=24`);
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
  }, [apiBase]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <div className="monthly-heatmap__loading">加载月度热力图...</div>;
  if (error) return <div className="monthly-heatmap__error">{error}</div>;
  if (!data.length) return null;

  // Group by year
  const years = [...new Set(data.map(d => d.year))].sort();

  return (
    <div className="monthly-heatmap">
      <div className="monthly-heatmap__header">
        <div className="monthly-heatmap__title">月度市场收益热力图</div>
        <div className="monthly-heatmap__subtitle">最近24个月 · 平均日收益率 · 颜色越深幅度越大</div>
      </div>

      <div className="monthly-heatmap__legend">
        <span className="heatmap-legend__item">
          <span className="heatmap-legend__swatch" style={{ background: 'rgb(255,80,80)' }} />
          下跌
        </span>
        <span className="heatmap-legend__mid">+0%</span>
        <span className="heatmap-legend__item">
          <span className="heatmap-legend__swatch" style={{ background: 'rgb(50,255,80)' }} />
          上涨
        </span>
      </div>

      <div className="monthly-heatmap__grid">
        {/* Month labels */}
        <div className="heatmap-grid__months">
          <div className="heatmap-grid__year-col" />
          {MONTHS.map(m => (
            <div key={m} className="heatmap-grid__month-label">{m}</div>
          ))}
        </div>

        {/* Year rows */}
        {years.map(year => (
          <div key={year} className="heatmap-grid__row">
            <div className="heatmap-grid__year-label">{year}</div>
            {MONTHS.map((_, mi) => {
              const row = data.find(d => d.year === year && d.month === mi + 1);
              const val = row?.avg_return_pct ?? null;
              const gainer = row?.gainer_pct ?? null;
              return (
                <div
                  key={mi}
                  className={`heatmap-grid__cell ${val === null ? 'heatmap-grid__cell--null' : ''}`}
                  style={{ background: getColor(val) }}
                  onMouseEnter={(e) => {
                    if (row) setTooltip({ row, x: e.clientX, y: e.clientY });
                  }}
                  onMouseLeave={() => setTooltip(null)}
                  title={row ? `${row.month_label}: ${formatReturn(val)} (${gainerLabel(gainer)})` : `${year}-${mi + 1}`}
                >
                  {val !== null && (
                    <span className="heatmap-grid__cell-value" style={{ color: getTextColor(val) }}>
                      {val >= 0 ? '+' : ''}{val.toFixed(2)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {tooltip && (
        <div
          className="heatmap-tooltip"
          style={{ left: tooltip.x + 12, top: tooltip.y - 40, position: 'fixed' }}
        >
          <div className="heatmap-tooltip__title">{tooltip.row.month_label}</div>
          <div className="heatmap-tooltip__row">
            <span>平均日收益</span>
            <span className={tooltip.row.avg_return_pct !== null && tooltip.row.avg_return_pct >= 0 ? 'positive' : 'negative'}>
              {formatReturn(tooltip.row.avg_return_pct)}
            </span>
          </div>
          <div className="heatmap-tooltip__row">
            <span>上涨家数</span>
            <span>{gainerLabel(tooltip.row.gainer_pct)}</span>
          </div>
          <div className="heatmap-tooltip__row">
            <span>股票数</span>
            <span>{tooltip.row.stock_count.toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  );
};
