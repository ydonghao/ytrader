/**
 * CashflowAnalysisPanel —— 现金流分析（Cashflow Analysis）面板。
 *
 * 11 个现金流指标三分组矩阵（行=指标、列=报告期，最新期在前），
 * 附"Δ较上期"变动列；点击指标行查看该指标趋势图。
 * 指标无 A股涨跌语义，Δ 用中性色（升蓝/降灰）。
 * 绝对额（yi 单位）API 传原始元、显示层转亿。
 */
import React, { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { StateView } from './ui';
import { useCashflowAnalysis } from '../hooks/useCashflowAnalysis';
import type {
  CashflowMeta,
  CashflowUnit,
} from '../hooks/useCashflowAnalysis';
import {
  CHART_COLORS,
  axisProps,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';

const fmtVal = (v: number | null | undefined, unit: CashflowUnit) => {
  if (v == null) return '—';
  if (unit === 'yi') return `${(v / 1e8).toFixed(2)}亿`;
  if (unit === 'pct') return `${v.toFixed(1)}%`;
  if (unit === 'growth') return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
  return v.toFixed(2);
};

const fmtDelta = (d: number | null, unit: CashflowUnit) => {
  if (d == null) return '—';
  if (unit === 'yi') return `${d > 0 ? '+' : ''}${(d / 1e8).toFixed(2)}亿`;
  if (unit === 'x') return `${d > 0 ? '+' : ''}${d.toFixed(2)}`;
  return `${d > 0 ? '+' : ''}${d.toFixed(1)}pp`;
};

export const CashflowAnalysisPanel: React.FC<{
  symbol: string | null;
}> = ({ symbol }) => {
  const [periodMode, setPeriodMode] = useState<'month' | 'year'>('month');
  const [selected, setSelected] = useState<string | null>(null);
  const { data, loading, error } = useCashflowAnalysis(symbol, periodMode);

  const dates = useMemo(
    () => (data?.periods ?? []).map((p) => p.report_date),
    [data],
  );
  const metaByKey = useMemo(() => {
    const m = new Map<string, CashflowMeta>();
    for (const g of data?.groups ?? []) {
      for (const r of g.ratios) m.set(r.key, r);
    }
    return m;
  }, [data]);

  // 趋势图数据：时间升序（从最早到最新）
  const chartData = useMemo(() => {
    if (!selected || !data) return [];
    return data.periods
      .slice()
      .reverse()
      .map((p) => ({
        label: p.report_date.slice(2, 7),
        value: p.ratios[selected] ?? null,
      }));
  }, [data, selected]);

  const selMeta = selected ? metaByKey.get(selected) : undefined;

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="error" text={error} />;
  // periods 缺失（如响应形状不符）时降级为空态，而非渲染崩溃
  if (!data || !data.periods?.length)
    return (
      <StateView state="empty" text={data?.note || '暂无现金流分析数据'} />
    );

  return (
    <div className="fin-chart-card">
      <div
        style={{
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          flexWrap: 'wrap',
          marginBottom: 12,
        }}
      >
        <div className="fin-period-switcher">
          {([['month', '累计'], ['year', '年报']] as const).map(
            ([k, l]) => (
              <button
                key={k}
                className={`fin-period-switcher__btn ${periodMode === k ? 'is-active' : ''}`}
                onClick={() => setPeriodMode(k)}
              >
                {l}
              </button>
            ),
          )}
        </div>
        <span style={{ fontSize: 12, color: '#a1a1a6' }}>
          口径：报告期累计未年化；FCF=经营净额-|资本开支|；筹资净额≠自由现金流
        </span>
      </div>

      {data.note && (
        <div style={{ fontSize: 12, color: '#a1a1a6', marginBottom: 8 }}>
          {data.note}
        </div>
      )}

      <div className="fin-table-wrap">
        <table className="fin-table">
          <thead>
            <tr>
              <th>指标（{data.periods.length} 期）</th>
              {dates.map((d) => (
                <th key={d}>{d.slice(2)}</th>
              ))}
              <th>Δ较上期</th>
            </tr>
          </thead>
          <tbody>
            {data.groups.map((g) => (
              <React.Fragment key={g.key}>
                <tr>
                  <td
                    colSpan={dates.length + 2}
                    style={{
                      fontWeight: 600,
                      color: '#79c0ff',
                      background: 'rgba(121,192,255,0.06)',
                    }}
                  >
                    {g.label}
                  </td>
                </tr>
                {g.ratios.map((m) => {
                  const vals = data.periods.map(
                    (p) => p.ratios[m.key] ?? null,
                  );
                  const delta =
                    vals[0] != null && vals[1] != null
                      ? vals[0]! - vals[1]!
                      : null;
                  return (
                    <tr
                      key={m.key}
                      style={{ cursor: 'pointer' }}
                      title={m.formula}
                      onClick={() =>
                        setSelected(selected === m.key ? null : m.key)
                      }
                    >
                      <td style={{ paddingLeft: 24 }}>{m.label}</td>
                      {vals.map((v, i) => (
                        <td key={i}>{fmtVal(v, m.unit)}</td>
                      ))}
                      <td
                        style={{
                          color:
                            delta == null
                              ? undefined
                              : delta >= 0
                                ? '#79c0ff'
                                : '#a1a1a6',
                        }}
                      >
                        {fmtDelta(delta, m.unit)}
                      </td>
                    </tr>
                  );
                })}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {selected && chartData.length > 0 && selMeta && (
        <div style={{ marginTop: 16 }}>
          <h3 className="fin-chart-card__title">
            {selMeta.label} · 趋势
            {selMeta.unit === 'yi'
              ? '（亿元）'
              : selMeta.unit === 'x'
                ? ''
                : '（%）'}
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={chartData}
              margin={{ top: 10, right: 10, left: 0, bottom: 5 }}
            >
              <CartesianGrid {...gridProps} />
              <XAxis
                dataKey="label"
                {...axisProps}
                interval="preserveStartEnd"
              />
              <YAxis
                {...axisProps}
                tickFormatter={(v: number) =>
                  selMeta.unit === 'yi'
                    ? `${(v / 1e8).toFixed(0)}亿`
                    : selMeta.unit === 'x'
                      ? String(v)
                      : `${v}%`
                }
              />
              <Tooltip
                {...tooltipProps}
                formatter={(v: number) => [
                  fmtVal(v, selMeta.unit),
                  selMeta.label,
                ]}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="value"
                name={selMeta.label}
                stroke={CHART_COLORS[1]}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
};
