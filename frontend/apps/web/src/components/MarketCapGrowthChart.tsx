/**
 * MarketCapGrowthChart —— 市值与业绩增长趋势（指数/个股共用）。
 * 左轴柱=业绩指标（营收/归母净利润 × 单季/累计/TTM），
 * 右轴折线=总市值（报告期末对齐，亿）。参考直播截图双轴形态。
 */
import React, { useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { StateView } from './ui';
import {
  CHART_COLORS,
  axisProps,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';
import type { McgData } from '../hooks/useMarketCapGrowth';

type MetricKey = 'revenue' | 'net_profit';
type PeriodKey = 'quarter' | 'cumulative' | 'ttm';

const METRICS: Array<[MetricKey, string]> = [
  ['revenue', '营收'],
  ['net_profit', '归母净利润'],
];
const PERIODS: Array<[PeriodKey, string]> = [
  ['quarter', '单季'],
  ['cumulative', '累计'],
  ['ttm', 'TTM'],
];

const chipStyle = (active: boolean): React.CSSProperties => ({
  padding: '3px 10px',
  fontSize: 12,
  borderRadius: 999,
  cursor: 'pointer',
  border: `1px solid ${
    active ? 'rgba(10,132,255,0.55)' : 'rgba(255,255,255,0.14)'
  }`,
  background: active ? 'rgba(10,132,255,0.15)' : 'transparent',
  color: active ? '#0a84ff' : '#a1a1a6',
});

interface Props {
  title?: string;
  data: McgData | null;
  loading: boolean;
  error: string | null;
}

export function MarketCapGrowthChart({ title, data, loading, error }: Props) {
  const [metric, setMetric] = useState<MetricKey>('revenue');
  const [period, setPeriod] = useState<PeriodKey>('quarter');

  const rows = useMemo(() => {
    if (!data?.bars) return [];
    const mvMap = new Map(
      (data.mv_series ?? []).map((p) => [p.report_date, p.total_mv]),
    );
    return (data.bars[period] ?? []).map((b) => ({
      label: b.report_date.slice(2, 7),
      metric: b[metric],
      total_mv: mvMap.get(b.report_date) ?? null,
    }));
  }, [data, metric, period]);

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="error" text={error} />;
  if (!data || rows.length === 0)
    return <StateView state="empty" text={data?.note || '暂无市值与业绩数据'} />;

  const metricLabel = METRICS.find(([k]) => k === metric)![1];
  const periodLabel = PERIODS.find(([k]) => k === period)![1];
  // 样本数取最后可见期：最新期可能因披露率不足被隐藏（revenue/net_profit 全 null）
  const lastCount = (() => {
    const sc = data.sample_count ?? [];
    for (let i = sc.length - 1; i >= 0; i--) {
      const b = (data.bars.quarter ?? []).find(
        (x) => x.report_date === sc[i].report_date,
      );
      if (b && (b.revenue != null || b.net_profit != null)) return sc[i].count;
    }
    return null;
  })();

  return (
    <div>
      {title && (
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>
          {title}
        </h3>
      )}
      <div
        style={{
          display: 'flex',
          gap: 8,
          flexWrap: 'wrap',
          marginBottom: 10,
          alignItems: 'center',
        }}
      >
        {METRICS.map(([k, l]) => (
          <button
            key={k}
            style={chipStyle(metric === k)}
            onClick={() => setMetric(k)}
          >
            {l}
          </button>
        ))}
        <span style={{ width: 8 }} />
        {PERIODS.map(([k, l]) => (
          <button
            key={k}
            style={chipStyle(period === k)}
            onClick={() => setPeriod(k)}
          >
            {l}
          </button>
        ))}
        {lastCount != null && (
          <span
            style={{
              fontSize: 11,
              color: '#86868b',
              marginLeft: 'auto',
            }}
          >
            成分股 {lastCount} 只
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart
          data={rows}
          margin={{ top: 5, right: 10, bottom: 0, left: 0 }}
        >
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" {...axisProps} minTickGap={30} />
          <YAxis
            yAxisId="left"
            {...axisProps}
            width={56}
            tickFormatter={(v: number) => `${v}亿`}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            {...axisProps}
            width={56}
            tickFormatter={(v: number) => `${v}亿`}
          />
          <Tooltip
            {...tooltipProps}
            formatter={(v: number, name: string) => [
              `${Number(v).toFixed(1)}亿`,
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar
            yAxisId="left"
            dataKey="metric"
            name={`${metricLabel}(${periodLabel})`}
            fill={CHART_COLORS[0]}
            opacity={0.6}
            isAnimationActive={false}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="total_mv"
            name="总市值"
            stroke={CHART_COLORS[2]}
            strokeWidth={2}
            dot={{ r: 2 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
