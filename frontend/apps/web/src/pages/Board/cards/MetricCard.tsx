/**
 * 指标数值卡片 — 范围内最新一期值 + 与去年同季(单季口径)同比。
 * A股惯例:增长为红(上箭头)、下降为绿。
 */
import React, {useMemo} from 'react';
import {StateView} from '../../../components/ui';
import {colorDown, colorUp} from '../../../lib/chartTheme';
import {
  DateRange,
  FINANCIAL_METRICS,
  fmtPct,
  fmtYuan,
} from '../boardTypes';
import {useFinancialDetail} from './useFinancialDetail';

export interface MetricCardProps {
  symbol: string;
  config: {metric: string};
  range: DateRange;
  refreshKey: number;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  symbol, config, range, refreshKey,
}) => {
  // 同比需要去年同季数据,取数窗口向前扩 15 个月(仅补旧数据点,不影响最新期)
  const yoyRange = useMemo<DateRange>(() => {
    if (!range.start) return range;
    const d = new Date(range.start + 'T00:00:00');
    d.setDate(1);
    d.setMonth(d.getMonth() - 15);
    const fmt = (x: Date) =>
      `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
    return {...range, start: fmt(d)};
  }, [range]);
  const {series, loading, error} = useFinancialDetail(symbol, yoyRange, refreshKey);
  const def = FINANCIAL_METRICS.find((m) => m.key === config.metric);

  if (loading || error || series.length === 0) {
    return (
      <div className="board-chart">
        <StateView
          state={loading ? 'loading' : error ? 'error' : 'empty'}
          text={error ? error : series.length === 0 && !loading ? '无财务数据' : undefined}
        />
      </div>
    );
  }

  const latest = series[series.length - 1];
  const yoyDate = latest.report_date
    ? latest.report_date.replace(/^(\d{4})/, (y) => String(Number(y) - 1))
    : null;
  const prev = series.find((p) => p.report_date === yoyDate) || null;
  const v = latest[config.metric];
  const pv = prev ? prev[config.metric] : null;
  const value = typeof v === 'number' ? v : null;
  const prevValue = typeof pv === 'number' ? pv : null;
  const yoy =
    value != null && prevValue != null && prevValue !== 0
      ? ((value - prevValue) / Math.abs(prevValue)) * 100
      : null;

  return (
    <div className="board-metric">
      <div className="board-metric__label">{def?.label || config.metric}</div>
      <div className="board-metric__value">
        {def?.unit === 'pct' ? fmtPct(value) : fmtYuan(value)}
      </div>
      <div className="board-metric__sub">
        {yoy != null ? (
          <span style={{color: yoy >= 0 ? colorUp : colorDown}}>
            {yoy >= 0 ? '↑' : '↓'} {Math.abs(yoy).toFixed(1)}%
          </span>
        ) : (
          <span style={{color: colorDown, opacity: 0}}>—</span>
        )}
        <span className="board-metric__date">
          {(latest.report_date || '').slice(0, 10)}
        </span>
      </div>
    </div>
  );
};
