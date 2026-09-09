/**
 * Market Heatmap — visualizes top movers as a color-coded grid
 */
import React, { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@ytrader/common-components';
import { formatPrice, formatPercent } from '@ytrader/arch-utils';
import './HeatmapChart.css';

const getApiBase = () => localStorage.getItem('ytrader_api_base') || 'http://localhost:8001/api/v1';
const API_BASE = getApiBase();

interface HeatmapStock {
  symbol: string;
  name: string;
  change_pct: number;
  close: number;
  volume: number;
}

interface HeatmapData {
  date: string;
  total_stocks: number;
  gainers: number;
  losers: number;
  flat: number;
  breadth_pct: number;
  top_gainers: HeatmapStock[];
  top_losers: HeatmapStock[];
}

interface HeatmapChartProps {
  height?: number;
}

function StockCell({ stock, side }: { stock: HeatmapStock; side: 'gain' | 'lose' }) {
  const pct = stock.change_pct;
  const intensity = Math.min(Math.abs(pct) / 10, 1); // 0-1, maxes at ±10%

  const bgAlpha = 0.15 + intensity * 0.55; // 0.15 to 0.70
  const bg = side === 'gain'
    ? `rgba(255, 69, 58, ${bgAlpha})`   // 红涨
    : `rgba(48, 209, 88, ${bgAlpha})`;   // 绿跌

  const border = side === 'gain'
    ? `1px solid rgba(255, 69, 58, ${0.3 + intensity * 0.5})`
    : `1px solid rgba(48, 209, 88, ${0.3 + intensity * 0.5})`;

  return (
    <div
      className="heatmap-cell"
      style={{ background: bg, border }}
      title={`${stock.name} (${stock.symbol})\n收盘价: ${formatPrice(stock.close)}\n涨跌: ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`}
    >
      <span className="heatmap-cell__symbol">{stock.symbol.replace(/^(sh|sz|hk)/i, '')}</span>
      <span className="heatmap-cell__name" title={stock.name}>
        {stock.name.length > 4 ? stock.name.slice(0, 3) + '…' : stock.name}
      </span>
      <span className="heatmap-cell__pct" style={{ color: side === 'gain' ? 'var(--color-up)' : 'var(--color-down)' }}>
        {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
      </span>
    </div>
  );
}

export const HeatmapChart: React.FC<HeatmapChartProps> = ({ height = 300 }) => {
  const [data, setData] = useState<HeatmapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);

    fetch(`${API_BASE}/market/heatmap?limit=30`, { signal: controller.signal })
      .then((r) => { if (!r.ok) throw new Error('Heatmap fetch failed'); return r.json(); })
      .then((json) => {
        if (!cancelled) { setData(json.data); setLoading(false); }
      })
      .catch((e) => {
        if (cancelled || e.name === 'AbortError') return;
        if (!cancelled) { setError(e.message || 'Failed to load heatmap'); setLoading(false); }
      })
      .finally(() => clearTimeout(timeout));

    return () => { cancelled = true; clearTimeout(timeout); };
  }, []);

  if (loading) {
    return (
      <Card className="heatmap">
        <CardContent>
          <div className="heatmap__loading">
            <div className="spinner" />
            <p>Loading market heatmap...</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card className="heatmap">
        <CardContent>
          <div className="heatmap__error">
            <p>⚠️ {error || 'No heatmap data available'}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const { date, total_stocks, gainers, losers, breadth_pct, top_gainers, top_losers } = data;
  const advanceRate = breadth_pct;

  return (
    <Card className="heatmap">
      <CardHeader>
        <CardTitle>市场热力图</CardTitle>
        <span className="heatmap__date">{date} · {total_stocks.toLocaleString()} 只股票</span>
      </CardHeader>
      <CardContent>
        {/* Market breadth bar */}
        <div className="heatmap__breadth">
          <div className="heatmap__breadth-label">
            <span className="heatmap__breadth-gainers">▲ {gainers} 涨</span>
            <span className="heatmap__breadth-pct" style={{ color: advanceRate >= 50 ? 'var(--color-up)' : 'var(--color-down)' }}>
              {advanceRate.toFixed(1)}%
            </span>
            <span className="heatmap__breadth-losers">▼ {losers} 跌</span>
          </div>
          <div className="heatmap__breadth-bar">
            <div
              className="heatmap__breadth-bar__gainers"
              style={{ width: `${advanceRate}%` }}
            />
            <div
              className="heatmap__breadth-bar__losers"
              style={{ width: `${100 - advanceRate}%` }}
            />
          </div>
        </div>

        {/* Gainers */}
        {top_gainers.length > 0 && (
          <div className="heatmap__section">
            <h4 className="heatmap__section-title heatmap__section-title--gain">
              涨幅榜 ▲
            </h4>
            <div className="heatmap__grid">
              {top_gainers.map((stock) => (
                <StockCell key={stock.symbol} stock={stock} side="gain" />
              ))}
            </div>
          </div>
        )}

        {/* Losers */}
        {top_losers.length > 0 && (
          <div className="heatmap__section">
            <h4 className="heatmap__section-title heatmap__section-title--lose">
              跌幅榜 ▼
            </h4>
            <div className="heatmap__grid">
              {top_losers.map((stock) => (
                <StockCell key={stock.symbol} stock={stock} side="lose" />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
