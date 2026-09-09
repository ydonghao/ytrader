/**
 * 财务趋势卡片 — 多指标折线(金额指标左轴亿元、比率指标右轴%)。
 * 报告期落在全局时间范围内;recharts + chartTheme 统一样式。
 */
import React from 'react';
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {StateView} from '../../../components/ui';
import {
  axisProps,
  gridProps,
  seriesColor,
  tooltipProps,
} from '../../../lib/chartTheme';
import {
  DateRange,
  FINANCIAL_METRICS,
  fmtYuan,
} from '../boardTypes';
import {FinDetailPoint, useFinancialDetail} from './useFinancialDetail';

export interface FinancialTrendCardProps {
  symbol: string;
  config: {metrics: string[]};
  range: DateRange;
  refreshKey: number;
}

const labelOf = (key: string) =>
  FINANCIAL_METRICS.find((m) => m.key === key)?.label || key;

export const FinancialTrendCard: React.FC<FinancialTrendCardProps> = ({
  symbol, config, range, refreshKey,
}) => {
  const {series, loading, error} = useFinancialDetail(symbol, range, refreshKey);

  if (loading || error || series.length === 0) {
    return (
      <div className="board-chart">
        <StateView
          state={loading ? 'loading' : error ? 'error' : 'empty'}
          text={error ? error : series.length === 0 && !loading ? '该区间无财务数据' : undefined}
        />
      </div>
    );
  }

  const data = series.map((s) => {
    const row: Record<string, string | number | null> = {
      date: (s.report_date || '').slice(0, 7),
    };
    config.metrics.forEach((k) => {
      const v = s[k];
      row[k] = typeof v === 'number' ? v : null;
    });
    return row;
  });

  const hasPct = config.metrics.some(
    (k) => FINANCIAL_METRICS.find((m) => m.key === k)?.unit === 'pct',
  );
  const hasYuan = config.metrics.some(
    (k) => FINANCIAL_METRICS.find((m) => m.key === k)?.unit === 'yuan',
  );

  return (
    <div className="board-chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{top: 24, right: 12, bottom: 4, left: 4}}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="date" {...axisProps} />
          {hasYuan && (
            <YAxis yAxisId="left" {...axisProps} width={62}
              tickFormatter={(v: number) => fmtYuan(v)} />
          )}
          {hasPct && (
            <YAxis yAxisId="right" orientation="right" {...axisProps} width={44}
              tickFormatter={(v: number) => `${v}%`} />
          )}
          <Tooltip
            {...tooltipProps}
            formatter={(value: unknown, name: unknown) => {
              const def = FINANCIAL_METRICS.find((m) => m.label === name);
              const num = typeof value === 'number' ? value : null;
              const text = def?.unit === 'pct'
                ? (num?.toFixed(2) ?? '—') + '%'
                : fmtYuan(num);
              return [text, String(name)];
            }}
          />
          <Legend wrapperStyle={{fontSize: 11}} />
          {config.metrics.map((k, i) => {
            const unit = FINANCIAL_METRICS.find((m) => m.key === k)?.unit;
            return (
              <Line
                key={k}
                yAxisId={unit === 'pct' ? 'right' : 'left'}
                type="monotone"
                dataKey={k}
                name={labelOf(k)}
                stroke={seriesColor(i)}
                dot={false}
                strokeWidth={1.5}
                connectNulls
              />
            );
          })}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};
