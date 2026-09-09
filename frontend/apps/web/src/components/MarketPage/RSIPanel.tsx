/**
 * RSI Panel - RSI(14) line chart with 30/70 reference lines
 */
import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { CHART_COLORS, axisProps } from '../../lib/chartTheme';
import type { ProcessedBar } from './types';

interface RSIPanelProps {
  data: ProcessedBar[];
  height?: number;
}

export const RSIPanel: React.FC<RSIPanelProps> = ({ data, height = 120 }) => {
  if (!data || data.length === 0) {
    return (
      <div className="rsi-panel rsi-panel--empty" style={{ height }}>
        <span>暂无RSI数据</span>
      </div>
    );
  }

  // Filter to only bars with valid RSI
  const rsiData = data
    .filter((d) => d.rsi !== null)
    .map((d) => ({
      ...d,
      localTime: d.localTime,
      rsi: d.rsi!,
    }));

  if (rsiData.length === 0) {
    return (
      <div className="rsi-panel rsi-panel--empty" style={{ height }}>
        <span>数据不足无法计算RSI</span>
      </div>
    );
  }

  // Sample if too many points
  const sampled = rsiData.length > 200
    ? rsiData.filter((_, i) => i % Math.ceil(rsiData.length / 200) === 0)
    : rsiData;

  return (
    <div className="rsi-panel">
      <div className="rsi-panel__header">
        <span className="rsi-panel__title">RSI(14)</span>
      </div>
      <ResponsiveContainer width="100%" height={height - 28}>
        <LineChart data={sampled} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <XAxis
            dataKey="localTime"
            tickFormatter={(d) => {
              const date = new Date(d);
              return `${date.getMonth() + 1}/${date.getDate()}`;
            }}
            {...axisProps}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={30}
          />
          <YAxis
            domain={[0, 100]}
            tickValues={[0, 30, 70, 100]}
            {...axisProps}
            axisLine={false}
            width={28}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload || !payload.length) return null;
              const bar = payload[0].payload as ProcessedBar;
              return (
                <div className="chart-tooltip">
                  <div className="chart-tooltip__time">
                    {bar.localTime.toLocaleDateString('zh-CN')}
                  </div>
                  <div>RSI(14): {bar.rsi?.toFixed(2)}</div>
                </div>
              );
            }}
          />
          {/* Reference lines at 30 and 70 */}
          <ReferenceLine y={30} stroke={CHART_COLORS[1]} strokeDasharray="3 3" strokeOpacity={0.6} />
          <ReferenceLine y={70} stroke={CHART_COLORS[5]} strokeDasharray="3 3" strokeOpacity={0.6} />
          {/* RSI line */}
          <Line
            type="monotone"
            dataKey="rsi"
            stroke={CHART_COLORS[3]}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: CHART_COLORS[3] }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};
