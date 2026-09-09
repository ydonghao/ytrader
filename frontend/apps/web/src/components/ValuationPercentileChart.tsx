/**
 * 单指标估值分位图。
 *
 * 画法：历史绝对值轨迹（Line）+ 当前窗口的 p25/p50/p75 水平参考线。
 * 右上角徽章显示当前分位百分比 + 状态色。
 *
 * 参考 spec：历史值轨迹 + 当前窗口统计参考线（不做滚动分位曲线）。
 */
import React, { useMemo } from 'react';
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
} from 'recharts';
import type { PercentileMetric } from '../hooks/useValuationPercentile';
import { CHART_COLORS, axisProps, chartBorderStrong, gridProps, tooltipProps } from '../lib/chartTheme';

interface Props {
  title: string;
  unit?: string;
  metric: PercentileMetric | null;
  windowKey: string; // "3y" | "5y" | "10y" | "15y" | "20y" | "all"
  color?: string;
  /** 叠加股价（右轴） */
  showPrice?: boolean;
  /** series 日期 → 收盘价（useKlineCloseMap 对齐结果） */
  priceMap?: Map<string, number>;
}

/** 窗口 key → 徽章/按钮显示文案。 */
export function windowLabel(key: string): string {
  return key === 'all' ? '全部' : key;
}

export function percentileColor(pct: number | null): string {
  if (pct === null) return 'var(--color-text-tertiary)';
  if (pct < 0.2) return 'var(--color-success)'; // 低估 — 机会
  if (pct > 0.8) return 'var(--color-danger)'; // 高估 — 风险
  return 'var(--color-warning)'; // 正常
}

/** memo：父组件切窗口/开关股价时，未受影响的指标图不重算 series、不重渲染。 */
export const ValuationPercentileChart = React.memo(function ValuationPercentileChart({
  title,
  unit = '',
  metric,
  windowKey,
  color = CHART_COLORS[0],
  showPrice = false,
  priceMap,
}: Props) {
  // series 可达数千点 ×4 指标，必须 memo（窗口/开关切换时父组件高频重渲染）
  const series = useMemo(
    () =>
      (metric?.series || []).map((p) => ({
        date: p.date,
        value: p.value,
        price: showPrice ? priceMap?.get(p.date) : undefined,
      })),
    [metric, showPrice, priceMap],
  );

  if (!metric || !metric.windows[windowKey]) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: '#888' }}>
        {title}：数据不足
      </div>
    );
  }

  const stats = metric.windows[windowKey]!;
  const hasPrice = series.some((p) => p.price !== undefined);

  const pct = stats.percentile;
  const pctText = pct !== null ? `${(pct * 100).toFixed(0)}%` : '—';
  const badgeColor = percentileColor(pct);

  return (
    <div
      style={{
        border: '1px solid #2a2a2a',
        borderRadius: 8,
        padding: 12,
        background: 'var(--color-background)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
        }}
      >
        <strong>{title}</strong>
        <span
          style={{
            padding: '2px 10px',
            borderRadius: 12,
            color: '#fff',
            background: badgeColor,
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {windowLabel(windowKey)} 分位 {pctText}
        </span>
      </div>
      <div style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>
        当前 {stats.current?.toFixed(2) ?? '—'} {unit}　|　区间{' '}
        {stats.min?.toFixed(2)} ~ {stats.max?.toFixed(2)}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={series} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="date" {...axisProps} minTickGap={40} />
          <YAxis yAxisId="left" {...axisProps} width={45} />
          {hasPrice && (
            <YAxis
              yAxisId="right"
              orientation="right"
              {...axisProps}
              width={52}
              tick={{ ...axisProps.tick, fill: CHART_COLORS[5] }}
            />
          )}
          <Tooltip {...tooltipProps} />
          {stats.p25 !== null && stats.p75 !== null && (
            <ReferenceArea
              yAxisId="left"
              y1={stats.p25}
              y2={stats.p75}
              fill={color}
              fillOpacity={0.06}
            />
          )}
          <ReferenceLine
            yAxisId="left"
            y={stats.p50}
            stroke={chartBorderStrong}
            strokeDasharray="4 4"
          />
          {hasPrice && (
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="price"
              name="股价"
              stroke={CHART_COLORS[5]}
              strokeWidth={1}
              strokeOpacity={0.85}
              dot={false}
              connectNulls
            />
          )}
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="value"
            name={title}
            stroke={color}
            dot={false}
            strokeWidth={1.5}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
});
