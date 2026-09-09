/**
 * RatiosPanel —— 比率分析（Ratio Analysis）面板。
 *
 * 14 个核心财务比率四分组矩阵（行=比率、列=报告期，最新期在前），
 * 附"Δ较上期"变动列；点击比率行查看该比率趋势图。
 * 比率无 A股涨跌语义，Δ 用中性色（升蓝/降灰）。
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
import { useRatios } from '../hooks/useRatios';
import type { RatioMeta, RatioUnit } from '../hooks/useRatios';
import {
  CHART_COLORS,
  axisProps,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';

const fmtVal = (v: number | null | undefined, unit: RatioUnit) => {
  if (v == null) return '—';
  if (unit === 'pct') return `${v.toFixed(1)}%`;
  if (unit === 'growth') return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
  if (unit === 'day') return `${v.toFixed(0)}天`;
  if (unit === 'yi') return `${(v / 1e8).toFixed(2)}亿`;
  return v.toFixed(2);
};

const fmtDelta = (d: number | null, unit: RatioUnit) => {
  if (d == null) return '—';
  if (unit === 'x') return `${d > 0 ? '+' : ''}${d.toFixed(2)}`;
  if (unit === 'day') return `${d > 0 ? '+' : ''}${d.toFixed(0)}天`;
  if (unit === 'yi') return `${d > 0 ? '+' : ''}${(d / 1e8).toFixed(2)}亿`;
  return `${d > 0 ? '+' : ''}${d.toFixed(1)}pp`;
};

export const RatiosPanel: React.FC<{ symbol: string | null }> = ({ symbol }) => {
  const [periodMode, setPeriodMode] = useState<'month' | 'year'>('month');
  const [selected, setSelected] = useState<string | null>(null);
  const { data, loading, error } = useRatios(symbol, periodMode);

  const dates = useMemo(
    () => (data?.periods ?? []).map((p) => p.report_date),
    [data],
  );
  const metaByKey = useMemo(() => {
    const m = new Map<string, RatioMeta>();
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
    return <StateView state="empty" text={data?.note || '暂无比率分析数据'} />;

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
          {([['month', '累计'], ['year', '年报']] as const).map(([k, l]) => (
            <button
              key={k}
              className={`fin-period-switcher__btn ${periodMode === k ? 'is-active' : ''}`}
              onClick={() => setPeriodMode(k)}
            >
              {l}
            </button>
          ))}
        </div>
        <span style={{ fontSize: 12, color: '#a1a1a6' }}>
          口径：报告期累计未年化；ROE/ROA/周转率分母=(期初+期末)÷2
        </span>
      </div>

      <div className="fin-table-wrap">
        <table className="fin-table">
          <thead>
            <tr>
              <th>比率（{data.periods.length} 期）</th>
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
            {selMeta.unit === 'x' ? '' : selMeta.unit === 'day' ? '（天）' : selMeta.unit === 'yi' ? '（亿）' : '（%）'}
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={chartData}
              margin={{ top: 10, right: 10, left: 0, bottom: 5 }}
            >
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" />
              <YAxis
                {...axisProps}
                tickFormatter={(v: number) =>
                  selMeta.unit === 'x' || selMeta.unit === 'day'
                    ? String(v)
                    : selMeta.unit === 'yi'
                      ? `${(v / 1e8).toFixed(0)}亿`
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
