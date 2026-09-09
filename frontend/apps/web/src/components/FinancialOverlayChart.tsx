/**
 * FinancialOverlayChart —— 财务趋势图 + 可折叠叠加层（双 Y 轴）。
 *
 * 在基础财务指标图（柱/线）之上，叠加可开关的：
 *   - 股价（右轴 Line）
 *   - 行业指数（右轴 Line）
 *   - 个股 PE / PB / PS（右轴 Line）
 * 并画行业 PE/PB 当天快照参考虚线。
 *
 * 左轴：财务指标（亿 / %）。
 * 右轴：叠加层（价格元 / 指数点 / 估值倍数）—— 三种量纲不同，右轴只作
 *       大致参考；优先看趋势对齐而非绝对值。
 */
import React from 'react';
import {
  Bar,
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
import type {
  IndustrySnapshot,
  OverlayData,
  OverlayKey,
} from '../hooks/useFinancialOverlays';
import { minMaxNormalize } from '../lib/normalize';
import { CHART_COLORS, axisProps, colorOrange, gridProps, tooltipProps } from '../lib/chartTheme';

export interface MetricDef {
  key: string;
  label: string;
  color: string;
  isPercent?: boolean;
}

interface Props {
  title: string;
  /** 财务主数据（每条含 label + 各 metric 字段 + reportDate） */
  data: Array<Record<string, unknown>>;
  /** 可选财务指标定义（chip 行） */
  metrics: MetricDef[];
  chartType: 'bar' | 'line';
  selectedKeys: string[];
  onToggleMetric: (key: string) => void;
  /** 叠加层数据（key = reportDate） */
  overlayData?: OverlayData;
  /** 行业快照（画参考虚线） */
  industrySnapshot?: IndustrySnapshot | null;
  /** 当前开启的叠加项 */
  overlaySelection: OverlayKey[];
  onToggleOverlay: (key: OverlayKey) => void;
  /** data 中 reportDate 字段名（默认 'reportDate'） */
  reportDateField?: string;
}

const OVERLAY_DEFS: Array<{
  key: OverlayKey;
  label: string;
  color: string;
}> = [
  { key: 'stock_price', label: '股价', color: CHART_COLORS[5] },
  { key: 'industry_index', label: '行业指数', color: '#bc8cff' },
  { key: 'pe', label: 'PE', color: colorOrange },
  { key: 'pb', label: 'PB', color: '#56d364' },
  { key: 'ps', label: 'PS', color: '#79c0ff' },
];

export const FinancialOverlayChart: React.FC<Props> = ({
  title,
  data,
  metrics,
  chartType,
  selectedKeys,
  onToggleMetric,
  overlayData,
  industrySnapshot,
  overlaySelection,
  onToggleOverlay,
  reportDateField = 'reportDate',
}) => {
  const selectedMetrics = metrics.filter((m) =>
    selectedKeys.includes(m.key),
  );
  const isPercent = selectedMetrics.some((m) => m.isPercent);

  // P3: 归一化模式开关（把各叠加层各自 min-max 到 0-100，便于跨量纲对比趋势）
  const [normalize, setNormalize] = React.useState(false);

  // 合并叠加数据到 chart data（按 reportDate 查 overlayData）
  // P3: 归一化模式下，对每个叠加项独立 min-max 归一化
  const merged = React.useMemo(() => {
    const base = data.map((row) => {
      const rd = String(row[reportDateField] || '');
      const ov = overlayData?.[rd];
      return { ...row, ...(ov || {}) };
    });
    if (!normalize || overlaySelection.length === 0) return base;
    // 对每个叠加项独立归一化，写到 `${k}__norm` 字段
    const normed = base.map((r) => ({ ...r }));
    for (const k of overlaySelection) {
      const vals = base
        .map((r) => r[k])
        .filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
      if (vals.length < 2) continue;
      const out = minMaxNormalize(
        base.map((r) => (typeof r[k] === 'number' ? (r[k] as number) : NaN)),
      );
      out.forEach((nv, i) => {
        if (Number.isFinite(nv)) normed[i][`${k}__norm`] = nv;
      });
    }
    return normed;
  }, [data, overlayData, reportDateField, normalize, overlaySelection]);

  // 右轴是否显示（有任意叠加开启时）
  const hasOverlay = overlaySelection.length > 0;

  // 右轴 domain：归一化模式固定 [0,100]；否则从开启的叠加项取 min/max
  const rightDomain = React.useMemo(() => {
    if (!hasOverlay) return undefined;
    if (normalize) return [0, 100];
    const vals: number[] = [];
    for (const row of merged) {
      for (const k of overlaySelection) {
        const v = row[k];
        if (typeof v === 'number' && Number.isFinite(v))
          vals.push(v);
      }
    }
    if (!vals.length) return undefined;
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const pad = (hi - lo) * 0.1 || 1;
    return [lo - pad, hi + pad];
  }, [merged, overlaySelection, hasOverlay, normalize]);

  const yFormatter = isPercent
    ? (v: number) => `${v}%`
    : (v: number) => `${v}亿`;

  return (
    <div className="fin-chart-card">
      <h3 className="fin-chart-card__title">{title}</h3>
      {/* 财务指标 chip 行 */}
      {metrics.length > 0 && (
        <div className="fin-metric-chips">
          {metrics.map((m) => (
            <button
              key={m.key}
              className={`fin-metric-chip ${
                selectedKeys.includes(m.key) ? 'is-active' : ''
              }`}
              style={
                selectedKeys.includes(m.key)
                  ? { borderColor: m.color, color: m.color }
                  : undefined
              }
              onClick={() => onToggleMetric(m.key)}
            >
              <span
                className="fin-metric-chip__dot"
                style={{
                  background: selectedKeys.includes(m.key)
                    ? m.color
                    : '#484f58',
                }}
              />
              {m.label}
            </button>
          ))}
        </div>
      )}

      {/* 叠加层 chip 行（可折叠） */}
      {overlayData && (
        <div className="fin-overlay-chips">
          <span className="fin-overlay-chips__label">叠加：</span>
          {OVERLAY_DEFS.map((o) => {
            const active = overlaySelection.includes(o.key);
            // 无数据的叠加项禁用
            const hasData = merged.some((row) => {
              const v = row[o.key];
              return typeof v === 'number';
            });
            return (
              <button
                key={o.key}
                className={`fin-overlay-chip ${active ? 'is-active' : ''} ${
                  !hasData ? 'is-disabled' : ''
                }`}
                style={
                  active
                    ? { borderColor: o.color, color: o.color }
                    : undefined
                }
                disabled={!hasData}
                onClick={() => onToggleOverlay(o.key)}
              >
                <span
                  className="fin-metric-chip__dot"
                  style={{ background: active ? o.color : '#484f58' }}
                />
                {o.label}
              </button>
            );
          })}
          {/* P3: 归一化切换（开启时各叠加项各自 min-max 到 0-100，跨量纲对比趋势） */}
          {overlaySelection.length >= 2 && (
            <button
              className={`fin-overlay-chip ${normalize ? 'is-active' : ''}`}
              style={normalize ? {borderColor: 'var(--color-accent)', color: 'var(--color-accent)'} : undefined}
              onClick={() => setNormalize((v) => !v)}
              title="把各叠加项各自归一化到 0-100，对比趋势而非绝对值"
            >
              归一化
            </button>
          )}
        </div>
      )}

      {/* 行业快照标注 */}
      {industrySnapshot && (
        <div className="fin-overlay-snapshot">
          行业快照({industrySnapshot.as_of})：PE_TTM=
          {industrySnapshot.pe_ttm ?? '—'} PB=
          {industrySnapshot.pb ?? '—'} 股息率=
          {industrySnapshot.dividend_yield ?? '—'}%
        </div>
      )}

      {data.length > 0 && selectedMetrics.length > 0 ? (
        <ResponsiveContainer width="100%" height={360}>
          <ComposedChart
            data={merged}
            margin={{ top: 10, right: hasOverlay ? 50 : 10, left: 0, bottom: 5 }}
          >
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" />
            <YAxis yAxisId="primary" {...axisProps} tickFormatter={yFormatter} />
            {hasOverlay && (
              <YAxis
                yAxisId="overlay"
                orientation="right"
                domain={rightDomain}
                {...axisProps}
              />
            )}
            <Tooltip
              {...tooltipProps}
              formatter={(value: number, name: string) => {
                if (typeof value !== 'number') return [value, name];
                return [value.toFixed(2), name];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {chartType === 'bar'
              ? selectedMetrics.map((m) => (
                  <Bar
                    key={m.key}
                    yAxisId="primary"
                    dataKey={m.key}
                    name={m.label}
                    fill={m.color}
                    opacity={0.75}
                    radius={[3, 3, 0, 0]}
                  />
                ))
              : selectedMetrics.map((m) => (
                  <Line
                    key={m.key}
                    yAxisId="primary"
                    type="monotone"
                    dataKey={m.key}
                    name={m.label}
                    stroke={m.color}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                ))}
            {/* 叠加层 Line（右轴）。归一化模式下读 `${k}__norm` 字段 */}
            {overlaySelection.map((k) => {
              const def = OVERLAY_DEFS.find((o) => o.key === k);
              if (!def) return null;
              return (
                <Line
                  key={k}
                  yAxisId="overlay"
                  type="monotone"
                  dataKey={normalize ? `${k}__norm` : k}
                  name={normalize ? `${def.label}(归一化)` : def.label}
                  stroke={def.color}
                  strokeWidth={1.5}
                  strokeDasharray="4 2"
                  dot={false}
                />
              );
            })}
            {/* 行业 PE/PB 参考虚线（归一化模式下隐藏，因量纲已变） */}
            {!normalize && industrySnapshot &&
              overlaySelection.includes('pe') &&
              industrySnapshot.pe_ttm != null && (
                <ReferenceLine
                  yAxisId="overlay"
                  y={industrySnapshot.pe_ttm}
                  stroke={colorOrange}
                  strokeDasharray="2 2"
                  opacity={0.4}
                  label={{
                    value: `行业PE ${industrySnapshot.pe_ttm}`,
                    fill: colorOrange,
                    fontSize: 10,
                    position: 'insideTopRight',
                  }}
                />
              )}
            {!normalize && industrySnapshot &&
              overlaySelection.includes('pb') &&
              industrySnapshot.pb != null && (
                <ReferenceLine
                  yAxisId="overlay"
                  y={industrySnapshot.pb}
                  stroke={colorDown}
                  strokeDasharray="2 2"
                  opacity={0.4}
                  label={{
                    value: `行业PB ${industrySnapshot.pb}`,
                    fill: '#56d364',
                    fontSize: 10,
                    position: 'insideBottomRight',
                  }}
                />
              )}
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <div className="fin-empty">暂无数据</div>
      )}
    </div>
  );
};
