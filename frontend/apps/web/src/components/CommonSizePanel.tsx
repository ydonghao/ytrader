/**
 * CommonSizePanel —— 同型分析（Common-Size / 垂直分析）面板。
 *
 * 三大报表全科目 ÷ 基准值 → 结构百分比矩阵（行=科目按报表顺序缩进、
 * 列=报告期，最新期在前），附"Δ较上期"变动列；点击科目行查看占比趋势图。
 * 结构占比无 A股涨跌语义，Δ 用中性色（升蓝/降灰）。
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
import { useCommonSize } from '../hooks/useCommonSize';
import type { CommonSizeStatement } from '../hooks/useCommonSize';
import {
  CHART_COLORS,
  axisProps,
  gridProps,
  tooltipProps,
} from '../lib/chartTheme';

const STATEMENTS: { key: CommonSizeStatement; label: string }[] = [
  { key: 'balance', label: '资产负债表' },
  { key: 'income', label: '利润表' },
  { key: 'cashflow', label: '现金流量表' },
];

const fmtPct = (v: number | null | undefined) =>
  v == null ? '—' : `${v.toFixed(1)}%`;

const fmtDelta = (d: number | null) =>
  d == null ? '—' : `${d > 0 ? '+' : ''}${d.toFixed(1)}pp`;

const fmtYi = (v: number | null | undefined) =>
  v == null ? '—' : `${(v / 1e8).toFixed(2)}亿`;

export const CommonSizePanel: React.FC<{ symbol: string | null }> = ({ symbol }) => {
  const [statement, setStatement] = useState<CommonSizeStatement>('balance');
  const [periodMode, setPeriodMode] = useState<'month' | 'year'>('month');
  const [selected, setSelected] = useState<string | null>(null);
  const { data, loading, error } = useCommonSize(symbol, statement, periodMode);

  // 行序 = 期次顺序（最新期科目顺序优先），pcts[i] 对应 dates[i]
  const { rows, dates } = useMemo(() => {
    const periods = data?.periods ?? [];
    const dates = periods.map((p) => p.report_date);
    const order: string[] = [];
    const levels = new Map<string, number>();
    for (const p of periods) {
      for (const it of p.items) {
        if (!levels.has(it.name)) {
          order.push(it.name);
          levels.set(it.name, it.level);
        }
      }
    }
    const lookup = periods.map((p) => {
      const m = new Map<string, number | null>();
      for (const it of p.items) m.set(it.name, it.pct);
      return m;
    });
    const rows = order.map((name) => ({
      name,
      level: levels.get(name) ?? 1,
      pcts: lookup.map((m) => m.get(name) ?? null),
    }));
    return { rows, dates };
  }, [data]);

  // 趋势图数据：时间升序（从最早到最新）
  const chartData = useMemo(() => {
    if (!selected || !data) return [];
    return data.periods
      .slice()
      .reverse()
      .map((p) => ({
        label: p.report_date.slice(2, 7),
        value: p.items.find((it) => it.name === selected)?.pct ?? null,
      }));
  }, [data, selected]);

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="error" text={error} />;
  if (!data || data.periods.length === 0)
    return <StateView state="empty" text={data?.note || '暂无同型分析数据'} />;

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
          {STATEMENTS.map((s) => (
            <button
              key={s.key}
              className={`fin-period-switcher__btn ${statement === s.key ? 'is-active' : ''}`}
              onClick={() => {
                setStatement(s.key);
                setSelected(null);
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
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
        {data.base_name && (
          <span style={{ fontSize: 12, color: '#a1a1a6' }}>
            基准：{data.base_name} = {fmtYi(data.periods[0].base_value)}
          </span>
        )}
      </div>

      <div className="fin-table-wrap">
        <table className="fin-table">
          <thead>
            <tr>
              <th>科目（占基准 %）</th>
              {dates.map((d) => (
                <th key={d}>{d.slice(2)}</th>
              ))}
              <th>Δ较上期</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const delta =
                r.pcts[0] != null && r.pcts[1] != null
                  ? r.pcts[0]! - r.pcts[1]!
                  : null;
              return (
                <tr
                  key={r.name}
                  style={{ cursor: 'pointer' }}
                  onClick={() => setSelected(selected === r.name ? null : r.name)}
                >
                  <td style={{ paddingLeft: 8 + r.level * 16 }}>{r.name}</td>
                  {r.pcts.map((p, i) => (
                    <td key={i}>{fmtPct(p)}</td>
                  ))}
                  <td
                    style={{
                      color:
                        delta == null ? undefined : delta >= 0 ? '#79c0ff' : '#a1a1a6',
                    }}
                  >
                    {fmtDelta(delta)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {selected && chartData.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3 className="fin-chart-card__title">{selected} · 占比趋势（%）</h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" />
              <YAxis {...axisProps} tickFormatter={(v: number) => `${v}%`} />
              <Tooltip
                {...tooltipProps}
                formatter={(v: number) => [`${v?.toFixed(2)}%`, '占比']}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="value"
                name={selected}
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
