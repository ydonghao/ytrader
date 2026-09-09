/**
 * FiveForcesPanel —— 波特五力分析面板。
 *
 * 雷达图（五轴=五力得分，domain [0,100]，score None 按 0 绘制）+
 * 总分徽章 + 五张证据卡（力名/分数/证据：metric、value(+unit)、
 * trend 数值序列、interpretation）。
 * score None 的力卡片标"数据不足"；backend note 作小字 caption 展示。
 */
import React, { useMemo } from 'react';
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';
import { StateView } from './ui';
import { useFiveForces } from '../hooks/useFiveForces';
import type { Force, ForceEvidence } from '../hooks/useFiveForces';
import {
  CHART_COLORS,
  chartBorder,
  chartTextSecondary,
  chartTextTertiary,
  tooltipProps,
} from '../lib/chartTheme';

const fmtVal = (v: number | null | undefined, unit?: string) => {
  if (v == null) return '—';
  if (unit === 'pct') return `${v.toFixed(1)}%`;
  if (unit === 'day') return `${v.toFixed(0)}天`;
  if (unit === 'x') return v.toFixed(2);
  return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
};

const fmtTrend = (trend: (number | null)[], unit?: string) =>
  trend
    .map((v) => {
      if (v == null) return '—';
      if (unit === 'pct' || unit === 'x') return v.toFixed(1);
      if (unit === 'day') return v.toFixed(0);
      return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
    })
    .join(' → ');

const EvidenceList: React.FC<{ evidence: ForceEvidence[] }> = ({
  evidence,
}) => (
  <ul
    style={{
      listStyle: 'none',
      margin: '0.8rem 0 0',
      padding: 0,
      display: 'flex',
      flexDirection: 'column',
      gap: '0.8rem',
    }}
  >
    {evidence.map((e, i) => (
      <li
        key={i}
        style={{
          borderTop: '1px solid var(--color-border)',
          paddingTop: '0.6rem',
        }}
      >
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text)' }}>
          {e.metric}
          <span
            className="num"
            style={{ marginLeft: 8, fontWeight: 600 }}
          >
            {fmtVal(e.value, e.unit)}
          </span>
        </div>
        {e.trend && e.trend.length > 0 && (
          <div
            className="num"
            style={{
              fontSize: 'var(--text-xs)',
              color: 'var(--color-text-tertiary)',
              marginTop: 2,
            }}
          >
            {fmtTrend(e.trend, e.unit)}
          </div>
        )}
        <div
          style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-secondary)',
            marginTop: 2,
          }}
        >
          {e.interpretation}
        </div>
      </li>
    ))}
  </ul>
);

const ForceCard: React.FC<{ force: Force }> = ({ force }) => (
  <div className="fin-metric-card">
    <div className="fin-metric-card__label">{force.label}</div>
    {force.score != null ? (
      <div className="fin-metric-card__value">
        {force.score.toFixed(1)}
        <span
          style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-tertiary)',
            fontWeight: 400,
          }}
        >
          {' '}
          / 100
        </span>
      </div>
    ) : (
      <div
        className="fin-metric-card__value"
        style={{
          fontSize: 'var(--text-base)',
          color: 'var(--color-text-tertiary)',
        }}
      >
        数据不足
      </div>
    )}
    <EvidenceList evidence={force.evidence ?? []} />
  </div>
);

export const FiveForcesPanel: React.FC<{ symbol: string | null }> = ({
  symbol,
}) => {
  const { data, loading, error } = useFiveForces(symbol);

  // 雷达图数据：score None → 0（缺数据的力不破坏多边形闭合）
  const radarData = useMemo(
    () =>
      (data?.forces ?? []).map((f) => ({
        label: f.label,
        score: f.score ?? 0,
      })),
    [data],
  );

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="error" text={error} />;
  // forces 缺失（如响应形状不符）时降级为空态，而非渲染崩溃
  if (!data || !data.forces?.length)
    return <StateView state="empty" text={data?.note || '暂无五力分析数据'} />;

  return (
    <div>
      <div className="fin-chart-card">
        <div
          style={{
            display: 'flex',
            gap: 16,
            alignItems: 'center',
            flexWrap: 'wrap',
            marginBottom: 12,
          }}
        >
          <h3
            className="fin-chart-card__title"
            style={{ margin: 0, padding: 0, border: 'none' }}
          >
            波特五力评分
          </h3>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: chartTextSecondary }}>
            综合总分
          </span>
          <span
            className="num"
            style={{
              fontSize: 24,
              fontWeight: 700,
              color:
                data.total_score != null ? CHART_COLORS[0] : chartTextTertiary,
            }}
          >
            {data.total_score != null
              ? data.total_score.toFixed(1)
              : '数据不足'}
          </span>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <RadarChart data={radarData}>
            <PolarGrid stroke={chartBorder} />
            <PolarAngleAxis
              dataKey="label"
              tick={{ fill: chartTextSecondary, fontSize: 11 }}
            />
            <PolarRadiusAxis
              domain={[0, 100]}
              tick={{ fill: chartTextSecondary, fontSize: 10 }}
            />
            <Radar
              name="五力得分"
              dataKey="score"
              stroke={CHART_COLORS[0]}
              fill={CHART_COLORS[0]}
              fillOpacity={0.2}
            />
            <Tooltip
              {...tooltipProps}
              formatter={(v: number) => [`${Number(v).toFixed(1)} 分`, '得分']}
            />
          </RadarChart>
        </ResponsiveContainer>
        {data.note && (
          <div
            style={{
              fontSize: 12,
              color: chartTextTertiary,
              marginTop: 8,
            }}
          >
            {data.note}
          </div>
        )}
      </div>

      <div
        className="fin-summary__cards"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}
      >
        {data.forces.map((f) => (
          <ForceCard key={f.key} force={f} />
        ))}
      </div>
    </div>
  );
};
