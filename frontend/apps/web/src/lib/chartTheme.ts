/**
 * 图表主题 — 全站唯一图表色板/样式来源。
 * 值与 styles/global.css 令牌保持同步（canvas 渲染无法使用 CSS var）。
 */
export const CHART_COLORS = [
  '#0a84ff', '#30d158', '#ff9f0a', '#bf5af2',
  '#64d2ff', '#ff453a', '#ffd60a', '#5e5ce6',
] as const;

export const colorUp = '#ff453a';    // A股红涨
export const colorDown = '#30d158';  // A股绿跌
export const colorFlat = '#a1a1a6';
/** 以下常量值与 styles/global.css 令牌同步（canvas 渲染无法使用 CSS var） */
export const colorWarning = '#ffd60a'; // --color-warning
export const colorOrange = '#ff9f0a';  // --color-orange（CHART_COLORS[2]）
export const chartText = '#f5f5f7';             // --color-text
export const chartTextSecondary = '#a1a1a6';   // --color-text-secondary
export const chartTextTertiary = '#86868b';    // --color-text-tertiary
export const chartTextQuaternary = '#6e6e73';  // --color-text-quaternary
export const chartBorder = 'rgba(255,255,255,0.08)';       // --color-border
export const chartBorderStrong = 'rgba(255,255,255,0.14)'; // --color-border-strong
export const chartSurface = '#2c2c2e';          // --color-surface
export const chartBackground = '#1d1d1f';       // --color-background

/** 热力图暖色刻度（低→高，值同 --chart 系列） */
export const HEAT_SCALE = ['#ffd60a', '#ff9f0a', '#ff453a'] as const;

/** recharts XAxis/YAxis 统一属性 */
export const axisProps = {
  tick: {fill: '#a1a1a6', fontSize: 11},
  stroke: 'rgba(255,255,255,0.14)',
  tickLine: false,
} as const;

/** recharts CartesianGrid 统一属性 */
export const gridProps = {
  stroke: 'rgba(255,255,255,0.06)',
  strokeDasharray: '3 3',
  vertical: false,
} as const;

/** recharts Tooltip 统一内容样式 */
export const tooltipProps = {
  contentStyle: {
    background: '#2c2c2e',
    border: '1px solid rgba(255,255,255,0.14)',
    borderRadius: 10,
    fontSize: 12,
    color: '#f5f5f7',
  },
  labelStyle: {color: '#a1a1a6'},
} as const;

/** 按序取系列色（超过 8 个循环） */
export const seriesColor = (i: number): string => CHART_COLORS[i % CHART_COLORS.length];
