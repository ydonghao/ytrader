/**
 * IndexPeChart —— 指数整体法市盈率趋势。
 * 蓝 PE 折线（月末点，TTM 断档断线）+ 黄均值虚线 + 红/绿 mean±σ 参考线。
 * 参考用户自研产品截图形态（"沪深300市盈率趋势/近八年"）。
 */
import React, { useMemo } from 'react';
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { StateView } from './ui';
import {
  CHART_COLORS,
  axisProps,
  colorDown,
  colorUp,
  colorWarning,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';
import type { IndexPeData } from '../hooks/useIndexPe';

const refLabel = (text: string, color: string) => ({
  value: text,
  position: 'right' as const,
  fill: color,
  fontSize: 11,
});

interface Props {
  title?: string;
  subtitle?: string;
  data: IndexPeData | null;
  loading: boolean;
  error: string | null;
}

export function IndexPeChart({
  title,
  subtitle,
  data,
  loading,
  error,
}: Props) {
  const rows = useMemo(
    () =>
      (data?.series ?? []).map((p) => ({
        date: p.date.slice(0, 7),   // 月度粒度 → YYYY-MM 刻度
        pe: p.pe,
      })),
    [data],
  );

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="error" text={error} />;
  if (!data || rows.length === 0)
    return (
      <StateView
        state="empty"
        text={data?.note || '暂无市盈率数据（等待周度任务回填 pe_ttm）'}
      />
    );

  const s = data.stats;
  return (
    <div>
      {(title || data?.current?.pe != null) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            margin: '0 0 10px',
          }}
        >
          {title && (
            <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>
              {title}
              {subtitle && (
                <small
                  style={{
                    fontSize: 12,
                    fontWeight: 400,
                    color: '#a1a1a6',
                    marginLeft: 8,
                  }}
                >
                  {subtitle}
                </small>
              )}
            </h3>
          )}
          {data?.current?.pe != null && (
            <span style={{ fontSize: 12, color: '#a1a1a6' }}>
              最新市盈率{' '}
              <span style={{ color: '#f5f5f7', fontWeight: 600 }}>
                {data.current.pe.toFixed(2)}
              </span>
              （{data.current.date.slice(0, 7)}）
            </span>
          )}
        </div>
      )}
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart
          data={rows}
          margin={{ top: 5, right: 56, bottom: 0, left: 0 }}
        >
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="date" {...axisProps} minTickGap={30} />
          <YAxis
            {...axisProps}
            width={44}
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => Number(v).toFixed(1)}
          />
          <Tooltip
            {...tooltipProps}
            formatter={(v: number, name: string) => [
              v == null ? '-' : Number(v).toFixed(2),
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {s && (
            <>
              <ReferenceLine
                y={s.mean}
                stroke={colorWarning}
                strokeDasharray="6 4"
                label={refLabel(`均值 ${s.mean.toFixed(1)}`, colorWarning)}
                ifOverflow="extendDomain"
              />
              <ReferenceLine
                y={s.high}
                stroke={colorUp}
                strokeDasharray="6 4"
                label={refLabel(`高估 ${s.high.toFixed(1)}`, colorUp)}
                ifOverflow="extendDomain"
              />
              <ReferenceLine
                y={s.low}
                stroke={colorDown}
                strokeDasharray="6 4"
                label={refLabel(`低估 ${s.low.toFixed(1)}`, colorDown)}
                ifOverflow="extendDomain"
              />
            </>
          )}
          <Line
            type="monotone"
            dataKey="pe"
            name="市盈率"
            stroke={CHART_COLORS[0]}
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      {data.note && (
        <div style={{ fontSize: 11, color: '#86868b', marginTop: 6 }}>
          {data.note}
        </div>
      )}
      <div style={{ fontSize: 11, color: '#86868b', marginTop: 4 }}>
        整体法：成分股总市值和 ÷ TTM归母净利和；月度采样；当前成分近似历史成分
      </div>
    </div>
  );
}
