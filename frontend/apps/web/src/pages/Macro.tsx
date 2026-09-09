/**
 * Macro page — 宏观经济（专业版）
 *
 * 布局：
 *   全局控制条（Tab + 时间范围，sticky）
 *   指标紧凑卡片网格（点击手风琴展开详情，一次一个）
 *   判断与验证 tab（快照 / 人记录 / 历史验证对照）
 *
 * Data:
 *   GET /macro/dashboard            聚合视图（指标 + 最新快照 + 命中率）
 *   GET /macro/indicators/{code}    单指标时序（支持 start/end/limit）
 *   GET /macro/views                历史快照列表
 *   GET /macro/views/{id}/track     预测期内指数 K 线
 *   GET /macro/events               历史事件
 *   POST /macro/views/generate      手动生成快照
 */
import React, {useEffect, useState, useCallback, useMemo} from 'react';
import {
  LineChart, Line, ComposedChart, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import {getApiBase} from '../lib/api';
import {Button, PageHeader, StateView, Tabs} from '../components/ui';
import './Macro.css';
import { CHART_COLORS, axisProps, chartTextTertiary, colorWarning, gridProps, tooltipProps } from '../lib/chartTheme';

const API_BASE = getApiBase();

// ── Types ────────────────────────────────────────────────────────────────────
interface IndicatorMeta {
  code: string;
  name: string;
  unit: string;
  freq: string;
  category: string;
  group: string;            // growth/inflation/employment/monetary/realestate/global
  threshold_high: number | null;
  threshold_low: number | null;
  direction: string;       // high_good / low_good / neutral
  sort_order: number;
  description: string;
  explanation: string;
  doc_url: string;
  range_low: number | null;
  range_high: number | null;
  reference_lines: RefLine[];
}

interface RefLine {
  value: number;
  label: string;
  severity: string;  // normal / warning / danger / boom
}

interface IndicatorValue {
  indicator_code: string;
  report_date: string;
  value: number;
  unit: string;
  source: string;
  source_url: string;
  meta: IndicatorMeta;
  data_start?: string;
}

interface MacroJudgment {
  dimension: string;
  stance: string;
  confidence: number;
  rationale: string;
}

interface AssetPrediction {
  symbol: string;
  name: string;
  predicted: string;
  rationale: string;
  asset_class: string;
}

interface ValidationItem {
  dimension?: string;
  symbol?: string;
  predicted: string;
  actual_value?: number | null;
  actual_dir?: string | null;
  actual_return?: number | null;
  hit: boolean | null;
  note?: string;
}

interface MacroView {
  id: number;
  author: string;
  snapshot_date: string;
  horizon_days: number;
  objective_reading: string;
  macro_judgments: MacroJudgment[];
  regime_quadrant: string;
  overall_stance: string;
  confidence: number;
  summary: string;
  signals: Record<string, any>;
  asset_predictions: AssetPrediction[];
  macro_validation: ValidationItem[];
  asset_validation: ValidationItem[];
  macro_accuracy: number | null;
  asset_accuracy: number | null;
  status: string;
  validated_at: string | null;
  llm_run_id: string | null;
}

interface Dashboard {
  indicators: IndicatorValue[];
  latest_view: MacroView | null;
  hit_rate: {
    macro_avg: number | null;
    asset_avg: number | null;
    scored_count: number;
  };
}

interface MacroEvent {
  date: string;
  title: string;
  desc: string;
}

interface SeriesPoint { report_date: string; value: number; }

// ── Helpers ──────────────────────────────────────────────────────────────────
const DIM_LABEL: Record<string, string> = {
  growth: '增长', inflation: '通胀', liquidity: '流动性',
  leverage: '杠杆', regime: '周期象限', recession_risk: '衰退风险',
};
const STANCE_LABEL: Record<string, string> = {
  up: '↑', down: '↓', flat: '→',
  recovery: '复苏', expansion: '扩张', overheating: '过热',
  stagflation: '滞胀', recession: '衰退',
  bullish: '偏多', bearish: '偏空', neutral: '中性',
};
const STANCE_COLOR: Record<string, string> = {
  up: 'is-up', down: 'is-down', flat: 'is-flat',
  bullish: 'is-up', bearish: 'is-down', neutral: 'is-flat',
};

const fmtNum = (n: number | null | undefined, digits = 2) =>
  n == null || Number.isNaN(n) ? '-' : n.toLocaleString('en-US', {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });

const fmtPct = (n: number | null | undefined) =>
  n == null ? '-' : `${(n * 100).toFixed(1)}%`;

// 指标当前值显示位数
const fmtVal = (v: number) => fmtNum(v, Math.abs(v) < 10 ? 1 : 0);

// 指标状态徽章：超阈值用方向判断偏热/偏冷
const badgeFor = (v: IndicatorValue): {text: string; cls: string} | null => {
  const {meta, value} = v;
  if (meta.threshold_high == null && meta.threshold_low == null) return null;
  const th = meta.threshold_high;
  if (th != null && meta.direction === 'high_good') {
    return value >= th
      ? {text: '扩张/利好', cls: 'is-up'}
      : {text: '收缩/承压', cls: 'is-down'};
  }
  if (th != null && meta.direction === 'low_good') {
    return value > th
      ? {text: '偏高/承压', cls: 'is-down'}
      : {text: '温和/利好', cls: 'is-up'};
  }
  return null;
};

// 分界线颜色：按语义严重度
const refLineColor = (severity: string): string => {
  switch (severity) {
    case 'danger': return CHART_COLORS[5];
    case 'warning': return colorWarning;
    case 'boom': return CHART_COLORS[1];
    default: return '#8e8e93';
  }
};

// 有长历史版本的指标映射：标准 code → 长历史 code
const LONG_HISTORY_MAP: Record<string, string> = {
  'cn_cpi_yoy': 'cn_cpi_yoy_long',
  'cn_ppi_yoy': 'cn_ppi_yoy_long',
  'cn_m2_yoy': 'cn_m2_yoy_long',
  'cn_pmi': 'cn_pmi_long',
};

// ── 月/年粒度与年聚合口径 ─────────────────────────────────────────────────────
type Granularity = 'month' | 'year';
type YearAgg = 'sum' | 'avg' | 'last';

// 流量/增量类：年度 = 各月加总（社融分项、贷款增量、销售、贸易）
const AGG_SUM = new Set([
  'cn_sf', 'cn_sf_rmb_loan', 'cn_sf_entrust_loan', 'cn_sf_trust_loan',
  'cn_sf_undiscounted_ba', 'cn_sf_corp_bond', 'cn_sf_govbond', 'cn_sf_equity',
  'cn_loan_enterprise', 'cn_loan_household',
  'cn_house_sales_amt', 'cn_house_sales_area', 'cn_trade_us_amt',
]);
// 时点/存量类：年度 = 年末值（LPR、存款结构占比、非农总就业；cn_birth 本身年频）
const AGG_LAST = new Set([
  'cn_lpr_1y', 'cn_deposit_demand_ratio', 'cn_deposit_term_ratio', 'cn_birth',
  'us_nfp',
]);
// 其余（同比 / 比率 / 指数类）：年度 = 月均

const AGG_LABEL: Record<YearAgg, string> = {
  sum: '年度合计', avg: '年度均值', last: '年末值',
};

const yearAggFor = (code: string): YearAgg =>
  AGG_SUM.has(code) ? 'sum' : AGG_LAST.has(code) ? 'last' : 'avg';

// 月/日频序列 → 年度序列。report_date 保留该年最后一条（时间轴连续），
// 当年数据未满一年（YTD）时打 ytd 标记，提醒该点不可与完整年度直接比。
interface YearPoint extends SeriesPoint { ytd?: boolean }

const aggregateYearly = (
  series: SeriesPoint[], agg: YearAgg,
): YearPoint[] => {
  const curYear = new Date().getFullYear();
  const byYear = new Map<number, SeriesPoint[]>();
  for (const p of series) {
    const y = Number(p.report_date.slice(0, 4));
    if (!y) continue;
    const arr = byYear.get(y);
    if (arr) arr.push(p); else byYear.set(y, [p]);
  }
  const out: YearPoint[] = [];
  for (const [y, pts] of byYear) {
    let value: number;
    if (agg === 'sum') {
      value = pts.reduce((a, p) => a + p.value, 0);
    } else if (agg === 'last') {
      value = pts[pts.length - 1].value;
    } else {
      value = pts.reduce((a, p) => a + p.value, 0) / pts.length;
    }
    const last = pts[pts.length - 1];
    const ytd = y === curYear && Number(last.report_date.slice(5, 7)) < 12;
    out.push({report_date: last.report_date, value, ytd});
  }
  return out.sort((a, b) => a.report_date.localeCompare(b.report_date));
};

// ── 时间范围 ──────────────────────────────────────────────────────────────────
interface TimeRange {
  key: string;
  label: string;
  years: number | null;   // null = 全部
}

const TIME_RANGES: TimeRange[] = [
  {key: '1y', label: '近1年', years: 1},
  {key: '3y', label: '近3年', years: 3},
  {key: '5y', label: '近5年', years: 5},
  {key: '10y', label: '近10年', years: 10},
  {key: '20y', label: '近20年', years: 20},
  {key: 'all', label: '全部', years: null},
];

const quickStart = (years: number): string => {
  const d = new Date();
  d.setFullYear(d.getFullYear() - years);
  return d.toISOString().slice(0, 10);
};

// ── 叠加指数清单（与 index_ohlcv 表 symbol 一致）──────────────────────────────
// 注：中证2000(sh932000) 为 2023 年新发布指数，仅东财有数据，本环境东财端点被
// 阻断（RemoteDisconnected），暂无数据；勾选后若无数据则不画曲线。中证全指
// (sh000985) 走腾讯源兜底，已回填 2011 至今。
interface OverlayIndex {
  symbol: string;
  name: string;
  color: string;
}
// 注：色板刻意避开蓝色系——主指标线用 Apple 蓝 var(--color-accent)，
// 叠加指数走暖色/绿/紫/洋红，靠色相 + 线宽（主线 2.5 / 指数线 1.5）双重区分。
const BROAD_INDICES: OverlayIndex[] = [
  {symbol: 'sh000300', name: '沪深300', color: '#ff6b3d'},
  {symbol: 'sh000016', name: '上证50', color: '#ffc53d'},
  {symbol: 'sh000905', name: '中证500', color: '#36cfc9'},
  {symbol: 'sh000852', name: '中证1000', color: '#f759ab'},
  {symbol: 'sh932000', name: '中证2000', color: '#b37feb'},
  {symbol: 'sh000985', name: '中证全指', color: '#ff9c6e'},
  {symbol: 'sh000001', name: '上证指数', color: '#73d13d'},
  {symbol: 'sz399006', name: '创业板指', color: '#ff4d4f'},
];
// 申万一级行业指数（sw801xxx，数据自 2016 起）。行业色板用半透明暖色系，
// 与宽基的饱和色区分：行业曲线更"次要"，视觉上退后一步。
const SW_INDICES: OverlayIndex[] = [
  {symbol: 'sw801120', name: '食品饮料', color: '#d4a373'},
  {symbol: 'sw801010', name: '农林牧渔', color: '#a3b18a'},
  {symbol: 'sw801200', name: '商贸零售', color: '#e9c46a'},
  {symbol: 'sw801210', name: '社会服务', color: '#efb0a3'},
  {symbol: 'sw801110', name: '家用电器', color: '#b08968'},
  {symbol: 'sw801130', name: '纺织服饰', color: '#cbc0d3'},
  {symbol: 'sw801980', name: '美容护理', color: '#f4a4c0'},
  {symbol: 'sw801180', name: '房地产',   color: '#a98467'},
  {symbol: 'sw801710', name: '建筑材料', color: '#b8b8b8'},
  {symbol: 'sw801720', name: '建筑装饰', color: '#9c9c9c'},
  {symbol: 'sw801040', name: '钢铁',     color: '#7d7d7d'},
  {symbol: 'sw801050', name: '有色金属', color: '#c9a227'},
  {symbol: 'sw801030', name: '化工',     color: '#bc6c25'},
  {symbol: 'sw801890', name: '机械设备', color: '#8a817c'},
  {symbol: 'sw801880', name: '汽车',     color: '#dda15e'},
  {symbol: 'sw801080', name: '电子',     color: '#a5a58d'},
  {symbol: 'sw801750', name: '计算机',   color: '#94a3b8'},
  {symbol: 'sw801760', name: '传媒',     color: '#c08497'},
  {symbol: 'sw801730', name: '电力设备', color: '#7f9c5c'},
  {symbol: 'sw801150', name: '医药生物', color: '#e76f51'},
  {symbol: 'sw801780', name: '银行',     color: '#6b705c'},
  {symbol: 'sw801790', name: '非银金融', color: '#8b6d8b'},
  {symbol: 'sw801740', name: '国防军工', color: '#5c6b73'},
  {symbol: 'sw801770', name: '通信',     color: '#7b8fa1'},
  {symbol: 'sw801160', name: '公用事业', color: '#8fa987'},
  {symbol: 'sw801170', name: '交通运输', color: '#a8957b'},
  {symbol: 'sw801140', name: '轻工制造', color: '#b5b682'},
  {symbol: 'sw801960', name: '石油石化', color: '#6f6a5f'},
  {symbol: 'sw801950', name: '煤炭',     color: '#4a4e4e'},
  {symbol: 'sw801970', name: '环保',     color: '#7fb069'},
  {symbol: 'sw801230', name: '综合',     color: '#9e9e9e'},
];
const OVERLAY_INDICES = [...BROAD_INDICES, ...SW_INDICES];
const OVERLAY_BY_SYMBOL = new Map(OVERLAY_INDICES.map((o) => [o.symbol, o]));

// ── 指标 → 相关行业指数推荐映射 ───────────────────────────────────────────────
// 展开某个指标详情时，自动勾选这些"经济逻辑相关"的行业指数（覆盖全局默认）。
// 映射依据：CPI食品→食品饮料/农业；社零→商贸/社服/家电；房地产→地产/家电/建材；
// PMI/工业利润→周期品（有色/化工/机械）；货币社融→银行/非银金融。
const INDICATOR_RELATED: Record<string, string[]> = {
  cn_cpi_food:      ['sw801120', 'sw801010'],                  // CPI食品→食品饮料/农林牧渔
  cn_cpi_consumer:  ['sw801200', 'sw801130', 'sw801980'],      // CPI消费品→商贸/纺服/美容
  cn_cpi_yoy:       ['sw801120', 'sw801200'],                  // CPI同比→食品饮料/商贸
  cn_cpi_yoy_long:  ['sw801120', 'sw801200'],
  cn_retail_yoy:    ['sw801200', 'sw801210', 'sw801110'],      // 社零→商贸/社服/家电
  cn_disp_income_median_yoy: ['sw801120', 'sw801110', 'sw801200'], // 可支配收入→食饮/家电/商贸
  cn_loan_household: ['sw801180', 'sw801110'],                 // 住户贷款→地产/家电
  cn_house_sales_amt:  ['sw801180', 'sw801110', 'sw801710'],   // 商品房销售额→地产/家电/建材
  cn_house_sales_area: ['sw801180', 'sw801110', 'sw801710'],
  cn_realestate_inv_yoy: ['sw801180', 'sw801710', 'sw801040'], // 房地产投资→地产/建材/钢铁
  cn_industrial_profit_yoy: ['sw801050', 'sw801030', 'sw801890'], // 工业利润→有色/化工/机械
  cn_pmi:           ['sw801050', 'sw801030', 'sw801890', 'sw801880'], // PMI→有色/化工/机械/汽车
  cn_pmi_long:      ['sw801050', 'sw801030', 'sw801890'],
  cn_m2_yoy:        ['sw801780', 'sw801790'],                  // M2→银行/非银
  cn_m2_yoy_long:   ['sw801780', 'sw801790'],
  cn_sf:            ['sw801780', 'sw801790'],                  // 社融→银行/非银
  cn_lpr_1y:        ['sw801780', 'sw801180'],                  // LPR→银行/地产
};

// ── Tab 配置 ──────────────────────────────────────────────────────────────────
interface TabConfig {
  key: string;
  label: string;
  filter: (ind: IndicatorValue) => boolean;
}

const INDICATOR_TABS: TabConfig[] = [
  {key: 'inflation', label: '通胀',
    filter: (i) => i.meta?.group === 'inflation' && i.meta?.category !== 'us'},
  {key: 'growth', label: '增长·就业',
    filter: (i) => ['growth', 'employment'].includes(i.meta?.group || '')
              && i.meta?.category !== 'us'},
  {key: 'monetary', label: '货币·社融',
    filter: (i) => i.meta?.group === 'monetary' && i.meta?.category !== 'us'},
  {key: 'realestate', label: '房地产',
    filter: (i) => i.meta?.group === 'realestate'},
  {key: 'global', label: '贸易',
    filter: (i) => i.meta?.group === 'global'},
  {key: 'us', label: '美国',
    filter: (i) => i.meta?.category === 'us'},
];

// ── 指标时序获取 hook ─────────────────────────────────────────────────────────
const useIndicatorSeries = (
  code: string, start: string, end: string,
): {series: SeriesPoint[]; loading: boolean} => {
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!code) { setSeries([]); return; }
    let alive = true;
    setLoading(true);
    const params = new URLSearchParams();
    if (start) params.set('start', start);
    if (end) params.set('end', end);
    if (!start && !end) params.set('limit', '600');
    fetch(`${API_BASE}/macro/indicators/${code}?${params.toString()}`)
      .then((r) => r.json())
      .then((j) => { if (alive) setSeries(j.data?.series || []); })
      .catch(() => { if (alive) setSeries([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [code, start, end]);

  return {series, loading};
};

// ── 叠加指数日线获取 hook ─────────────────────────────────────────────────────
// 并发拉取多个指数的日线 close 序列（走通用 /market/kline/{symbol}）。
// 返回 Map<symbol, {ts:number, close:number}[]>（ts 为毫秒，便于与指标序列对齐）。
const useIndexOverlays = (
  symbols: string[], start: string, end: string,
): {data: Map<string, {ts: number; close: number}[]>; loading: boolean} => {
  const [data, setData] = useState<Map<string, {ts: number; close: number}[]>>(
    () => new Map());
  const [loading, setLoading] = useState(false);

  const key = symbols.slice().sort().join(',') + '|' + start + '|' + end;
  useEffect(() => {
    if (!symbols.length) { setData(new Map()); return; }
    let alive = true;
    setLoading(true);
    Promise.all(symbols.map(async (sym) => {
      const params = new URLSearchParams();
      params.set('interval', '1d');
      params.set('limit', '8000');
      if (start) params.set('start', start);
      if (end) params.set('end', end);
      try {
        const r = await fetch(`${API_BASE}/market/kline/${sym}?${params}`);
        const j = await r.json();
        const bars: any[] = j.data?.bars || [];
        const arr = bars.map((b) => ({
          ts: new Date(b.trade_date).getTime(),
          close: Number(b.close),
        })).filter((p) => Number.isFinite(p.ts) && Number.isFinite(p.close))
          .sort((a, b) => a.ts - b.ts);
        return [sym, arr] as const;
      } catch {
        return [sym, []] as const;
      }
    })).then((entries) => {
      if (!alive) return;
      setData(new Map(entries as any));
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return {data, loading};
};


const InfoTip: React.FC<{meta: IndicatorMeta}> = ({meta}) => {
  if (!meta?.explanation && !meta?.doc_url) return null;
  return (
    <span className="macro__indicator-info" tabIndex={0}
          onClick={(e) => e.stopPropagation()}>
      ⓘ
      <span className="macro__indicator-tip">
        {meta.explanation && (
          <span className="macro__indicator-tip-text">{meta.explanation}</span>
        )}
        {meta.doc_url && (
          <a className="macro__indicator-tip-link" href={meta.doc_url}
             target="_blank" rel="noopener noreferrer">
            了解更多 →
          </a>
        )}
      </span>
    </span>
  );
};

// ── 紧凑指标卡片 ─────────────────────────────────────────────────────────────
const IndicatorCard: React.FC<{
  ind: IndicatorValue;
  start: string;
  end: string;
  granularity: Granularity;
  expanded: boolean;
  onToggle: () => void;
  events: MacroEvent[];
  overlaySymbols: string[];
  onToggleOverlay: (symbol: string) => void;
}> = ({ind, start, end, granularity, expanded, onToggle, events, overlaySymbols, onToggleOverlay}) => {
  const sparkCode = LONG_HISTORY_MAP[ind.indicator_code] || ind.indicator_code;
  const {series, loading} = useIndicatorSeries(sparkCode, start, end);
  const badge = badgeFor(ind);
  const unit = ind.meta?.unit || '';
  const agg = yearAggFor(ind.indicator_code);

  // 按当前粒度呈现的序列（年 = 聚合）
  const view = useMemo<SeriesPoint[]>(
    () => granularity === 'year' ? aggregateYearly(series, agg) : series,
    [series, granularity, agg]);

  // 区间变化（首末点差值）；对专业人士用中性色 + 箭头，不暗示好坏
  const delta = useMemo(() => {
    if (view.length < 2) return null;
    return view[view.length - 1].value - view[0].value;
  }, [view]);

  // 年模式下大数值与日期也切换到年度视角（最新年度聚合点）
  const latestPt = granularity === 'year' && view.length
    ? (view[view.length - 1] as YearPoint) : null;

  return (
    <>
      <div
        className={`macro__card ${expanded ? 'is-expanded' : ''}`}
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') onToggle(); }}
      >
        <div className="macro__card-top">
          <span className="macro__card-name">
            {ind.meta?.name || ind.indicator_code}
            <InfoTip meta={ind.meta} />
          </span>
          {badge && (
            <span className={`macro__card-badge ${badge.cls}`}>{badge.text}</span>
          )}
        </div>

        <div className="macro__card-value">
          {fmtVal(latestPt ? latestPt.value : ind.value)}
          <span className="macro__card-unit">
            {unit}
            {latestPt ? ` · ${AGG_LABEL[agg]}` : ''}
          </span>
        </div>

        <div className="macro__card-spark">
          {loading ? (
            <div className="macro__card-spark-empty">…</div>
          ) : view.length >= 2 ? (
            <ResponsiveContainer width="100%" height={52}>
              <LineChart data={view}
                         margin={{top: 4, right: 2, bottom: 0, left: 2}}>
                <Tooltip
                  {...tooltipProps}
                  labelFormatter={(_, payload) => {
                    const p = payload?.[0]?.payload as YearPoint | undefined;
                    if (!p) return '';
                    return granularity === 'year'
                      ? `${p.report_date.slice(0, 4)} 年${p.ytd ? '（YTD）' : ''}`
                      : p.report_date;
                  }}
                  formatter={(v: number) => [
                    `${fmtVal(v)}${unit}`, ind.meta?.name || '']}
                />
                <Line type="monotone" dataKey="value"
                      stroke={CHART_COLORS[0]} strokeWidth={1.5}
                      dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="macro__card-spark-empty">该区间数据不足</div>
          )}
        </div>

        <div className="macro__card-foot">
          <span className="macro__card-date">
            {latestPt
              ? `${latestPt.report_date.slice(0, 4)} 年${
                  latestPt.ytd ? '（YTD）' : ''}`
              : ind.report_date}
          </span>
          {ind.data_start && (
            <span className={`macro__card-start ${
              Number(ind.data_start.slice(0, 4)) >= 2010 ? 'is-late' : ''}`}
              title={`该指标数据始于 ${ind.data_start.slice(0, 7)}`}>
              起 {ind.data_start.slice(0, 4)}
            </span>
          )}
          {delta != null && (
            <span className="macro__card-delta">
              {delta > 0 ? '▲' : delta < 0 ? '▼' : '—'}
              {' '}{delta > 0 ? '+' : ''}{fmtNum(delta, Math.abs(delta) < 10 ? 2 : 0)}
              {unit === '%' ? 'pct' : unit}
            </span>
          )}
          <span className="macro__card-more">{expanded ? '收起 ▴' : '详情 ▾'}</span>
        </div>
      </div>

      {expanded && (
        <IndicatorDetail
          ind={ind}
          start={start}
          end={end}
          granularity={granularity}
          events={events}
          mainSeries={view}
          overlaySymbols={overlaySymbols}
          onToggleOverlay={onToggleOverlay}
        />
      )}
    </>
  );
};

// ── 指标详情面板（手风琴展开，占满整行）──────────────────────────────────────
const IndicatorDetail: React.FC<{
  ind: IndicatorValue;
  start: string;
  end: string;
  granularity: Granularity;
  events: MacroEvent[];
  mainSeries: SeriesPoint[];
  overlaySymbols: string[];
  onToggleOverlay: (symbol: string) => void;
}> = ({ind, start, end, granularity, events = [], mainSeries, overlaySymbols, onToggleOverlay}) => {
  const longCode = LONG_HISTORY_MAP[ind.indicator_code];
  const [useLong, setUseLong] = useState(true);
  const needAlt = !!longCode && !useLong;
  const alt = useIndicatorSeries(
    needAlt ? ind.indicator_code : '', start, end);
  const agg = yearAggFor(ind.indicator_code);

  // 备用（标准频率）序列同样按当前粒度聚合
  const altView = useMemo<SeriesPoint[]>(
    () => granularity === 'year'
      ? aggregateYearly(alt.series, agg) : alt.series,
    [alt.series, granularity, agg]);

  const series = needAlt ? altView : mainSeries;
  const loading = needAlt ? alt.loading : false;
  const meta = ind.meta;
  const unit = meta?.unit || '';
  const badge = badgeFor(ind);

  // 行业指数折叠展开（默认展开——若有行业推荐，让用户直接看到）
  const relatedSectors = INDICATOR_RELATED[ind.indicator_code] || [];
  const [showSectors, setShowSectors] = useState(true);

  // 区间统计
  const stats = useMemo(() => {
    if (!series.length) return null;
    const vals = series.map((s) => s.value);
    const first = vals[0];
    const last = vals[vals.length - 1];
    return {
      latest: last,
      hi: Math.max(...vals),
      lo: Math.min(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
      chg: last - first,
    };
  }, [series]);

  // Y 轴区间（圆整到 1 位小数，避免浮点尾巴撑爆刻度标签）
  const {yLow, yHigh} = useMemo(() => {
    if (!series.length) return {yLow: 0, yHigh: 1};
    let lo = Infinity, hi = -Infinity;
    for (const s of series) {
      if (s.value < lo) lo = s.value;
      if (s.value > hi) hi = s.value;
    }
    const low = meta?.range_low ?? (lo - (hi - lo) * 0.1);
    const high = meta?.range_high ?? (hi + (hi - lo) * 0.1);
    const r1 = (v: number) => {
      const av = Math.abs(v);
      const p = av >= 100 ? 0 : av >= 10 ? 1 : 2;
      return Number(v.toFixed(p));
    };
    return {yLow: r1(low), yHigh: r1(high)};
  }, [series, meta]);

  const chartData = useMemo(
    () => series.map((s) => ({
      ...s, ts: new Date(s.report_date).getTime(),
    })),
    [series]);

  // ── 叠加指数：拉取日线 close，并按"最近邻前值"对齐到指标时间轴 ──
  const {data: overlayData} = useIndexOverlays(overlaySymbols, start, end);
  const activeOverlays = useMemo(
    () => OVERLAY_INDICES.filter((o) =>
      overlaySymbols.includes(o.symbol) && (overlayData.get(o.symbol)?.length ?? 0) > 0),
    [overlaySymbols, overlayData]);

  // 把每个指数的 close 对齐到 chartData 的 ts：找该 ts 之前最近一个交易日
  const mergedData = useMemo(() => {
    if (!activeOverlays.length) return chartData;
    return chartData.map((pt) => {
      const enriched: any = {...pt};
      for (const ov of activeOverlays) {
        const arr = overlayData.get(ov.symbol) || [];
        // 二分找 <= pt.ts 的最后一个
        let lo = 0, hi = arr.length - 1, hit = -1;
        while (lo <= hi) {
          const mid = (lo + hi) >> 1;
          if (arr[mid].ts <= pt.ts) { hit = mid; lo = mid + 1; }
          else hi = mid - 1;
        }
        if (hit >= 0) enriched[ov.symbol] = arr[hit].close;
      }
      return enriched;
    });
  }, [chartData, activeOverlays, overlayData]);

  // 叠加指数的右轴区间（取所有选中指数 close 的全局 min/max，留 5% 余量）
  const indexDomain = useMemo<[number, number]>(() => {
    let lo = Infinity, hi = -Infinity;
    for (const ov of activeOverlays) {
      for (const p of (overlayData.get(ov.symbol) || [])) {
        if (p.close < lo) lo = p.close;
        if (p.close > hi) hi = p.close;
      }
    }
    if (!Number.isFinite(lo)) return [0, 1];
    const pad = (hi - lo) * 0.05 || hi * 0.05 || 1;
    return [Math.floor(lo - pad), Math.ceil(hi + pad)];
  }, [activeOverlays, overlayData]);

  const tableRows = useMemo(
    () => [...series].reverse().slice(0, 12), [series]);

  return (
    <div className="macro__panel" onClick={(e) => e.stopPropagation()}>
      {/* 统计条 */}
      {stats && (
        <div className="macro__stats">
          <div className="macro__stat">
            <span className="macro__stat-label">
              最新{granularity === 'year' ? `（${AGG_LABEL[agg]}）` : ''}
            </span>
            <span className="macro__stat-val">
              {fmtVal(stats.latest)}{unit}
            </span>
          </div>
          <div className="macro__stat">
            <span className="macro__stat-label">区间最高</span>
            <span className="macro__stat-val">{fmtVal(stats.hi)}{unit}</span>
          </div>
          <div className="macro__stat">
            <span className="macro__stat-label">区间最低</span>
            <span className="macro__stat-val">{fmtVal(stats.lo)}{unit}</span>
          </div>
          <div className="macro__stat">
            <span className="macro__stat-label">区间均值</span>
            <span className="macro__stat-val">
              {fmtNum(stats.avg, Math.abs(stats.avg) < 10 ? 2 : 0)}{unit}
            </span>
          </div>
          <div className="macro__stat">
            <span className="macro__stat-label">区间变化</span>
            <span className="macro__stat-val">
              {stats.chg > 0 ? '+' : ''}
              {fmtNum(stats.chg, Math.abs(stats.chg) < 10 ? 2 : 0)}
              {unit === '%' ? 'pct' : unit}
            </span>
          </div>
          {badge && (
            <div className="macro__stat">
              <span className="macro__stat-label">状态</span>
              <span className={`macro__stat-val ${badge.cls}`}>
                {badge.text}
              </span>
            </div>
          )}
        </div>
      )}

      {/* 频率切换（仅有长历史版本的指标显示） */}
      {longCode && (
        <div className="macro__panel-freq">
          <button
            className={`macro__freq-btn ${!useLong ? 'is-active' : ''}`}
            onClick={() => setUseLong(false)}
          >
            标准（{meta?.freq === 'day' ? '日频' : '月度'}）
          </button>
          <button
            className={`macro__freq-btn ${useLong ? 'is-active' : ''}`}
            onClick={() => setUseLong(true)}
          >
            长历史
          </button>
        </div>
      )}

      {/* 完整区间折线图（可叠加指数行情，双 Y 轴）*/}
      <div className="macro__panel-chart">
        {/* 单指标叠加勾选（在图表上方）：宽基 + 行业（推荐勾选相关行业）*/}
        <div className="macro__overlay-row">
          <span className="macro__overlay-row-label">宽基：</span>
          {BROAD_INDICES.map((idx) => {
            const on = overlaySymbols.includes(idx.symbol);
            return (
              <button
                key={idx.symbol}
                type="button"
                className={`macro__overlay-chip sm ${on ? 'is-active' : ''}`}
                style={on ? {borderColor: idx.color, color: idx.color} : undefined}
                onClick={() => onToggleOverlay(idx.symbol)}
              >
                <span className="macro__overlay-dot"
                      style={{background: on ? idx.color : 'transparent',
                              borderColor: idx.color}} />
                {idx.name}
              </button>
            );
          })}
        </div>
        {relatedSectors.length > 0 && (
          <div className="macro__overlay-hint">
            该指标与以下行业强相关，已默认勾选
          </div>
        )}
        <div className="macro__overlay-row">
          <span className="macro__overlay-row-label">
            行业：
            <button type="button"
                    className="macro__overlay-toggle"
                    onClick={() => setShowSectors((v) => !v)}>
              {showSectors ? '收起' : `展开 (${SW_INDICES.length})`}
            </button>
          </span>
          {showSectors && SW_INDICES.map((idx) => {
            const on = overlaySymbols.includes(idx.symbol);
            const recommended = relatedSectors.includes(idx.symbol);
            return (
              <button
                key={idx.symbol}
                type="button"
                className={`macro__overlay-chip sm sector ${on ? 'is-active' : ''} ${recommended ? 'is-rec' : ''}`}
                style={on ? {borderColor: idx.color, color: idx.color} : undefined}
                onClick={() => onToggleOverlay(idx.symbol)}
                title={recommended ? `${idx.name}（与该指标相关）` : idx.name}
              >
                <span className="macro__overlay-dot"
                      style={{background: on ? idx.color : 'transparent',
                              borderColor: idx.color}} />
                {idx.name}
                {recommended && <span className="macro__overlay-rec">荐</span>}
              </button>
            );
          })}
        </div>
        {loading ? (
          <StateView state="loading" />
        ) : series.length < 2 ? (
          <StateView state="empty" text={`该时间范围内数据不足（${series.length} 条）`} />
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <ComposedChart data={mergedData}
                       margin={{top: 10, right: activeOverlays.length ? 56 : 20, bottom: 10, left: 10}}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="ts" type="number" scale="time"
                     domain={['dataMin', 'dataMax']}
                     {...axisProps}
                     tickFormatter={(v: number) => {
                       const d = new Date(v);
                       if (granularity === 'year') {
                         return String(d.getFullYear());
                       }
                       return `${d.getFullYear()}-${String(d.getMonth() + 1)
                         .padStart(2, '0')}`;
                     }} />
              <YAxis yAxisId="primary" domain={[yLow, yHigh]}
                     {...axisProps}
                     tickFormatter={(v: number) =>
                       fmtNum(v, Math.abs(v) < 10 ? 1 : 0)}
                     width={48} />
              {activeOverlays.length > 0 && (
                <YAxis yAxisId="index" orientation="right"
                       domain={indexDomain}
                       {...axisProps}
                       tickFormatter={(v: number) => fmtNum(v, 0)}
                       width={48} />
              )}
              <Tooltip
                {...tooltipProps}
                labelFormatter={(v: number, payload) => {
                  const d = new Date(v);
                  if (granularity === 'year') {
                    const p = payload?.[0]?.payload as YearPoint | undefined;
                    return `${d.getFullYear()} 年${p?.ytd ? '（YTD）' : ''}`;
                  }
                  return `${d.getFullYear()}-${String(d.getMonth() + 1)
                    .padStart(2, '0')}`;
                }}
                formatter={(v: number, name: string) => {
                  // 主指标线 name 为指标名；指数线 name 为 symbol（被覆盖为指数名）
                  if (name === meta?.name || name === 'value') {
                    return [`${fmtVal(v)}${unit}`, meta?.name || '指标'];
                  }
                  const ov = OVERLAY_BY_SYMBOL.get(name);
                  return [fmtNum(v, 0), ov?.name || name];
                }}
              />
              {(meta?.reference_lines || []).map((rl, i) => (
                <ReferenceLine
                  key={i}
                  yAxisId="primary"
                  y={rl.value}
                  stroke={refLineColor(rl.severity)}
                  strokeDasharray="4 3"
                  label={{value: rl.label, fill: refLineColor(rl.severity),
                          fontSize: 10, position: 'insideTopLeft'}}
                />
              ))}
              {events.map((evt) => (
                <ReferenceLine
                  key={`evt-${evt.date}`}
                  yAxisId="primary"
                  x={new Date(evt.date).getTime()}
                  stroke={chartTextTertiary}
                  strokeDasharray="2 4"
                  strokeWidth={1}
                  label={{
                    value: evt.title,
                    fill: chartTextTertiary,
                    fontSize: 9,
                    position: 'top',
                    angle: -90,
                  }}
                />
              ))}
              <Line yAxisId="primary" type="monotone" dataKey="value"
                    name={meta?.name || 'value'}
                    stroke={CHART_COLORS[0]} strokeWidth={2.5}
                    dot={{r: 2.5, fill: CHART_COLORS[0]}}
                    activeDot={{r: 4}}
                    isAnimationActive={false} />
              {activeOverlays.map((ov) => (
                <Line key={ov.symbol} yAxisId="index" type="monotone"
                      dataKey={ov.symbol} name={ov.symbol}
                      stroke={ov.color} strokeWidth={1.5}
                      strokeDasharray="5 2"
                      dot={false} connectNulls
                      isAnimationActive={false} />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* 解释 + 溯源 + 数据表 */}
      <div className="macro__panel-bottom">
        {(meta?.explanation || meta?.doc_url || ind.source) && (
          <div className="macro__panel-explain">
            {meta?.explanation && (
              <p className="macro__panel-explain-text">{meta.explanation}</p>
            )}
            <div className="macro__panel-explain-links">
              {meta?.doc_url && (
                <a href={meta.doc_url} target="_blank"
                   rel="noopener noreferrer">了解更多 →</a>
              )}
              {ind.source && (
                <span className="macro__panel-source">
                  数据源：
                  {ind.source_url ? (
                    <a href={ind.source_url} target="_blank"
                       rel="noopener noreferrer">{ind.source} ↗</a>
                  ) : ind.source}
                </span>
              )}
            </div>
          </div>
        )}

        {tableRows.length > 0 && (
          <div className="macro__panel-table-wrap">
            <table className="macro__panel-table">
              <thead>
                <tr>
                  <th>{granularity === 'year'
                    ? `年份（${AGG_LABEL[agg]}）` : '报告日期'}</th>
                  <th>数值</th><th>单位</th>
                </tr>
              </thead>
              <tbody>
                {tableRows.map((row) => (
                  <tr key={row.report_date}>
                    <td>
                      {granularity === 'year'
                        ? `${row.report_date.slice(0, 4)}${
                            (row as YearPoint).ytd ? '（YTD）' : ''}`
                        : row.report_date}
                    </td>
                    <td className="num">{fmtNum(row.value, Math.abs(row.value) < 10 ? 2 : 0)}</td>
                    <td>{unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

// ── Page ─────────────────────────────────────────────────────────────────────
export const Macro: React.FC = () => {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [views, setViews] = useState<MacroView[]>([]);
  const [events, setEvents] = useState<MacroEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [selectedView, setSelectedView] = useState<MacroView | null>(null);
  const [trackData, setTrackData] = useState<any>(null);
  const [trackLoading, setTrackLoading] = useState(false);
  const [showRecord, setShowRecord] = useState(false);
  const [recordForm, setRecordForm] = useState({
    overall_stance: 'neutral',
    confidence: 5,
    summary: '',
  });
  const [recording, setRecording] = useState(false);
  const [activeTab, setActiveTab] = useState('inflation');
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  // 全局时间范围
  const [rangeKey, setRangeKey] = useState('3y');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  // 全局粒度：月 / 年
  const [granularity, setGranularity] = useState<Granularity>('month');

  // 指数叠加：全局默认（宽基）+ 每个指标可独立调整
  const [globalOverlays, setGlobalOverlays] = useState<string[]>(['sh000300']);
  const [perIndicatorOverlays, setPerIndicatorOverlays] = useState<
    Record<string, string[]>>({});

  // 取某指标当前生效的叠加清单：
  // 1. 用户曾手动调整过 → 用调整后的
  // 2. 否则有行业推荐 → 用推荐（自动勾选相关行业指数）
  // 3. 否则 → 回退全局宽基默认
  const getOverlayFor = (code: string): string[] => {
    if (perIndicatorOverlays[code]) return perIndicatorOverlays[code];
    const related = INDICATOR_RELATED[code];
    return related && related.length ? related : globalOverlays;
  };

  const toggleOverlay = (code: string, symbol: string) => {
    setPerIndicatorOverlays((prev) => {
      const base = prev[code] ?? getOverlayFor(code);
      const next = base.includes(symbol)
        ? base.filter((s) => s !== symbol)
        : [...base, symbol];
      return {...prev, [code]: next};
    });
  };

  const toggleGlobalOverlay = (symbol: string) => {
    setGlobalOverlays((prev) =>
      prev.includes(symbol)
        ? prev.filter((s) => s !== symbol)
        : [...prev, symbol]);
    // 已自定义的指标不受全局变更影响
  };

  const {start, end} = useMemo(() => {
    if (customStart || customEnd) {
      return {start: customStart, end: customEnd};
    }
    const cfg = TIME_RANGES.find((r) => r.key === rangeKey);
    return {
      start: cfg?.years ? quickStart(cfg.years) : '',
      end: '',
    };
  }, [rangeKey, customStart, customEnd]);

  const handleRecord = async () => {
    if (!recordForm.summary.trim()) {
      alert('请填写判断理由');
      return;
    }
    setRecording(true);
    try {
      const res = await fetch(`${API_BASE}/macro/views/record`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(recordForm),
      });
      const j = await res.json();
      if (j.code === 0) {
        setShowRecord(false);
        setRecordForm({overall_stance: 'neutral', confidence: 5, summary: ''});
        await fetchDashboard();
      } else {
        alert(j.msg || '记录失败');
      }
    } catch (e) {
      alert('记录失败：' + e);
    } finally {
      setRecording(false);
    }
  };

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const [dRes, vRes, eRes] = await Promise.all([
        fetch(`${API_BASE}/macro/dashboard`),
        fetch(`${API_BASE}/macro/views?limit=50`),
        fetch(`${API_BASE}/macro/events`),
      ]);
      const dj = await dRes.json();
      const vj = await vRes.json();
      const ej = await eRes.json();
      setDash(dj.data || null);
      setViews(vj.data || []);
      setEvents(ej.data || []);
    } catch {
      setDash(null);
      setViews([]);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/macro/views/generate`,
                              {method: 'POST'});
      const j = await res.json();
      if (j.code === 0) {
        await fetchDashboard();
      } else {
        alert(j.msg || '生成失败');
      }
    } catch (e) {
      alert('生成失败：' + e);
    } finally {
      setGenerating(false);
    }
  };

  const openView = async (v: MacroView) => {
    setSelectedView(v);
    setTrackData(null);
    setTrackLoading(true);
    try {
      const res = await fetch(`${API_BASE}/macro/views/${v.id}/track`);
      const j = await res.json();
      setTrackData(j.data || null);
    } catch {
      setTrackData(null);
    } finally {
      setTrackLoading(false);
    }
  };

  const indicators = dash?.indicators || [];
  const latestView = dash?.latest_view || null;
  const hitRate = dash?.hit_rate;
  const isJudgmentTab = activeTab === 'judgment';

  const tabConfig = INDICATOR_TABS.find((t) => t.key === activeTab);
  const tabIndicators = tabConfig ? indicators.filter(tabConfig.filter) : [];

  return (
    <div className="macro">
      <PageHeader
        title="宏观经济"
        subtitle="宏观状态判断 · 美林时钟定位 · 回看验证判断准确性"
      />

      {/* ── 全局控制条（Tab + 时间范围，吸顶）── */}
      <div className="macro__controls">
        <nav className="macro__tabs">
          <Tabs
            active={activeTab}
            onChange={(k) => { setActiveTab(k); setExpandedCode(null); }}
            tabs={[
              ...INDICATOR_TABS.map((tab) => {
                const count = indicators.filter(tab.filter).length;
                return {
                  key: tab.key,
                  label: (
                    <>
                      {tab.label}
                      {count > 0 && (
                        <span className="macro__tab-count">{count}</span>
                      )}
                    </>
                  ),
                };
              }),
              {key: 'judgment', label: '判断与验证'},
            ]}
          />
        </nav>

        {!isJudgmentTab && (
          <div className="macro__range">
            <div className="macro__range-quick" title="数据粒度">
              <button
                className={`macro__range-btn ${
                  granularity === 'month' ? 'is-active' : ''}`}
                onClick={() => setGranularity('month')}
              >
                月
              </button>
              <button
                className={`macro__range-btn ${
                  granularity === 'year' ? 'is-active' : ''}`}
                onClick={() => setGranularity('year')}
              >
                年
              </button>
            </div>
            <span className="macro__range-divider" />
            <div className="macro__range-quick">
              {TIME_RANGES.map((r) => (
                <button
                  key={r.key}
                  className={`macro__range-btn ${
                    rangeKey === r.key && !customStart && !customEnd
                      ? 'is-active' : ''}`}
                  onClick={() => {
                    setRangeKey(r.key);
                    setCustomStart('');
                    setCustomEnd('');
                  }}
                >
                  {r.label}
                </button>
              ))}
            </div>
            <div className="macro__range-dates">
              <input
                type="date"
                className="macro__range-input"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
              />
              <span className="macro__range-sep">~</span>
              <input
                type="date"
                className="macro__range-input"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
              />
              {(customStart || customEnd) && (
                <button
                  className="macro__range-clear"
                  onClick={() => { setCustomStart(''); setCustomEnd(''); }}
                >
                  清除
                </button>
              )}
            </div>
            <span className="macro__range-divider" />
            <div className="macro__overlay-chips" title="默认叠加的宽基指数（无行业推荐的指标会用此项；展开后可单独调整）">
              <span className="macro__overlay-label">叠加宽基：</span>
              {BROAD_INDICES.map((idx) => {
                const on = globalOverlays.includes(idx.symbol);
                return (
                  <button
                    key={idx.symbol}
                    type="button"
                    className={`macro__overlay-chip ${on ? 'is-active' : ''}`}
                    style={on ? {borderColor: idx.color, color: idx.color} : undefined}
                    onClick={() => toggleGlobalOverlay(idx.symbol)}
                  >
                    <span className="macro__overlay-dot"
                          style={{background: on ? idx.color : 'transparent',
                                  borderColor: idx.color}} />
                    {idx.name}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* ── 指标卡片网格（非判断 tab）── */}
      {!isJudgmentTab && (
        <section className="macro__section">
          {loading ? (
            <div className="macro__cards">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="macro__card skeleton"
                     style={{height: 150}} />
              ))}
            </div>
          ) : tabIndicators.length === 0 ? (
            <StateView state="empty" text="该分类暂无指标数据" />
          ) : (
            <div className="macro__cards">
              {tabIndicators.map((ind) => (
                <IndicatorCard
                  key={ind.indicator_code}
                  ind={ind}
                  start={start}
                  end={end}
                  granularity={granularity}
                  expanded={expandedCode === ind.indicator_code}
                  onToggle={() =>
                    setExpandedCode(
                      expandedCode === ind.indicator_code
                        ? null : ind.indicator_code)}
                  events={events}
                  overlaySymbols={getOverlayFor(ind.indicator_code)}
                  onToggleOverlay={(sym) => toggleOverlay(ind.indicator_code, sym)}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── 判断与验证 tab ── */}
      {isJudgmentTab && (
        <>
          <div className="macro__judgment-actions">
            <Button
              variant="primary"
              onClick={handleGenerate}
              disabled={generating}
            >
              {generating ? '生成中…' : '+ 生成判断快照'}
            </Button>
          </div>

          <section className="macro__section">
            <h2 className="macro__section-title">最新判断快照</h2>
            {latestView ? (
              <div className="macro__snapshot">
                <div className="macro__snapshot-header">
                  <div className="macro__snapshot-regime">
                    <span className="macro__snapshot-label">周期象限</span>
                    <span className={`macro__snapshot-regime-val ${STANCE_COLOR[latestView.regime_quadrant] || 'is-flat'}`}>
                      {STANCE_LABEL[latestView.regime_quadrant] || latestView.regime_quadrant}
                    </span>
                  </div>
                  <div className="macro__snapshot-regime">
                    <span className="macro__snapshot-label">综合立场</span>
                    <span className={`macro__snapshot-regime-val ${STANCE_COLOR[latestView.overall_stance] || 'is-flat'}`}>
                      {STANCE_LABEL[latestView.overall_stance] || latestView.overall_stance}
                    </span>
                  </div>
                  <div className="macro__snapshot-regime">
                    <span className="macro__snapshot-label">置信度</span>
                    <span className="macro__snapshot-regime-val">
                      {latestView.confidence.toFixed(1)} / 10
                    </span>
                  </div>
                  <div className="macro__snapshot-regime">
                    <span className="macro__snapshot-label">日期</span>
                    <span className="macro__snapshot-regime-val">{latestView.snapshot_date}</span>
                  </div>
                </div>

                {latestView.objective_reading && (
                  <div className="macro__reading">
                    <div className="macro__reading-label">客观解读</div>
                    <div className="macro__reading-body">{latestView.objective_reading}</div>
                  </div>
                )}

                <details className="macro__stance">
                  <summary className="macro__stance-summary">
                    <span className="macro__reading-label">AI 立场</span>
                    <span className={`macro__snapshot-regime-val ${STANCE_COLOR[latestView.overall_stance] || 'is-flat'}`}>
                      {STANCE_LABEL[latestView.overall_stance] || latestView.overall_stance} · {latestView.confidence.toFixed(1)}/10
                    </span>
                  </summary>
                  <div className="macro__stance-body">
                    <p className="macro__stance-reason">{latestView.summary}</p>
                    <div className="macro__snapshot-cols">
                      <div className="macro__snapshot-col">
                        <h3 className="macro__snapshot-col-title">宏观状态判断<small>用下季度宏观数据验证</small></h3>
                        {latestView.macro_judgments.map((j, i) => (
                          <div key={i} className="macro__judgment">
                            <div className="macro__judgment-head">
                              <span className="macro__judgment-dim">{DIM_LABEL[j.dimension] || j.dimension}</span>
                              <span className={`macro__judgment-stance ${STANCE_COLOR[j.stance] || 'is-flat'}`}>
                                {STANCE_LABEL[j.stance] || j.stance} · {j.confidence.toFixed(0)}
                              </span>
                            </div>
                            <p className="macro__judgment-rationale">{j.rationale}</p>
                          </div>
                        ))}
                      </div>
                      <div className="macro__snapshot-col">
                        <h3 className="macro__snapshot-col-title">资产方向预测<small>用走势验证</small></h3>
                        {latestView.asset_predictions.map((p, i) => (
                          <div key={i} className="macro__judgment">
                            <div className="macro__judgment-head">
                              <span className="macro__judgment-dim">{p.name} <small>{p.symbol}</small></span>
                              <span className={`macro__judgment-stance ${STANCE_COLOR[p.predicted] || 'is-flat'}`}>
                                {STANCE_LABEL[p.predicted] || p.predicted}
                              </span>
                            </div>
                            <p className="macro__judgment-rationale">{p.rationale}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </details>
              </div>
            ) : loading ? (
              <StateView state="loading" />
            ) : (
              <StateView state="empty" text="暂无快照。点击上方「生成判断快照」创建第一条。" />
            )}
          </section>

          <section className="macro__section macro__record-section">
            {!showRecord ? (
              <Button variant="secondary" onClick={() => setShowRecord(true)}>
                我记一笔判断
              </Button>
            ) : (
              <div className="macro__record-form">
                <h3 className="macro__record-title">记下你的宏观判断</h3>
                <div className="macro__record-row">
                  <label>你的立场</label>
                  <div className="macro__record-stances">
                    {(['bullish', 'bearish', 'neutral'] as const).map((s) => (
                      <label key={s} className={`macro__record-stance ${recordForm.overall_stance === s ? 'is-active' : ''}`}>
                        <input
                          type="radio"
                          name="stance"
                          value={s}
                          checked={recordForm.overall_stance === s}
                          onChange={(e) => setRecordForm({...recordForm, overall_stance: e.target.value})}
                        />
                        {STANCE_LABEL[s]}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="macro__record-row">
                  <label>置信度：{recordForm.confidence}/10</label>
                  <input
                    type="range" min="0" max="10" step="1"
                    value={recordForm.confidence}
                    onChange={(e) => setRecordForm({...recordForm, confidence: Number(e.target.value)})}
                  />
                </div>
                <div className="macro__record-row">
                  <label>理由</label>
                  <textarea
                    className="macro__record-textarea"
                    placeholder="写下你的判断依据（可长可短）"
                    value={recordForm.summary}
                    onChange={(e) => setRecordForm({...recordForm, summary: e.target.value})}
                    rows={3}
                  />
                </div>
                <div className="macro__record-actions">
                  <Button variant="ghost" onClick={() => setShowRecord(false)}>取消</Button>
                  <Button variant="primary" onClick={handleRecord} disabled={recording}>
                    {recording ? '保存中…' : '保存'}
                  </Button>
                </div>
              </div>
            )}
          </section>

          <section className="macro__section">
            <h2 className="macro__section-title">
              历史判断与验证对照
              {hitRate && hitRate.scored_count > 0 && (
                <span className="macro__hitrate">
                  已验证 {hitRate.scored_count} 条 · 宏观命中率{' '}
                  <strong className={hitRate.macro_avg == null ? 'num is-flat' : (hitRate.macro_avg >= 0.5 ? 'num is-up' : 'num is-down')}>
                    {hitRate.macro_avg == null ? '-' : fmtPct(hitRate.macro_avg)}
                  </strong>
                  {' · 资产命中率 '}
                  <strong className={hitRate.asset_avg == null ? 'num is-flat' : (hitRate.asset_avg >= 0.5 ? 'num is-up' : 'num is-down')}>
                    {hitRate.asset_avg == null ? '-' : fmtPct(hitRate.asset_avg)}
                  </strong>
                </span>
              )}
            </h2>
            {views.length === 0 ? (
              <StateView state={loading ? 'loading' : 'empty'} text={loading ? undefined : '暂无历史快照'} />
            ) : (
              <div className="macro__views-table">
                <div className="macro__views-row macro__views-row--head">
                  <span>日期</span>
                  <span>来源</span>
                  <span>象限</span>
                  <span>立场</span>
                  <span>宏观命中</span>
                  <span>资产命中</span>
                  <span>状态</span>
                  <span></span>
                </div>
                {views.map((v) => (
                  <div
                    key={v.id}
                    className={`macro__views-row ${selectedView?.id === v.id ? 'macro__views-row--active' : ''}`}
                    onClick={() => openView(v)}
                  >
                    <span className="macro__views-date">{v.snapshot_date}</span>
                    <span className={`macro__views-author macro__views-author--${v.author}`}>
                      {v.author === 'user' ? '我' : 'AI'}
                    </span>
                    <span className={STANCE_COLOR[v.regime_quadrant] || 'is-flat'}>
                      {STANCE_LABEL[v.regime_quadrant] || v.regime_quadrant || '-'}
                    </span>
                    <span className={STANCE_COLOR[v.overall_stance] || 'is-flat'}>
                      {STANCE_LABEL[v.overall_stance] || v.overall_stance}
                    </span>
                    <span className={v.macro_accuracy == null ? 'is-flat' : (v.macro_accuracy >= 0.5 ? 'is-up' : 'is-down')}>
                      {v.macro_accuracy == null ? '—' : fmtPct(v.macro_accuracy)}
                    </span>
                    <span className={v.asset_accuracy == null ? 'is-flat' : (v.asset_accuracy >= 0.5 ? 'is-up' : 'is-down')}>
                      {v.asset_accuracy == null ? '—' : fmtPct(v.asset_accuracy)}
                    </span>
                    <span className={`macro__views-status macro__views-status--${v.status}`}>
                      {v.status === 'pending' ? '待验证' : v.status === 'scored' ? '已验证' : '部分'}
                    </span>
                    <span className="macro__views-arrow">›</span>
                  </div>
                ))}
              </div>
            )}

            {selectedView && (
              <ViewDetail
                view={selectedView}
                trackData={trackData}
                trackLoading={trackLoading}
                onClose={() => setSelectedView(null)}
              />
            )}
          </section>
        </>
      )}
    </div>
  );
};

// ── 快照详情 + K 线对照组件 ──────────────────────────────────────────────────
const ViewDetail: React.FC<{
  view: MacroView;
  trackData: any;
  trackLoading: boolean;
  onClose: () => void;
}> = ({view, trackData, trackLoading, onClose}) => {
  const macroValMap: Record<string, ValidationItem> = {};
  view.macro_validation.forEach((v) => {
    if (v.dimension) macroValMap[v.dimension] = v;
  });
  const assetValMap: Record<string, ValidationItem> = {};
  view.asset_validation.forEach((v) => {
    if (v.symbol) assetValMap[v.symbol] = v;
  });

  return (
    <div className="macro__detail-overlay" onClick={onClose}>
      <div className="macro__detail" onClick={(e) => e.stopPropagation()}>
        <div className="macro__detail-head">
          <h3>
            快照 #{view.id} · {view.snapshot_date}
            <span className={`macro__detail-status macro__detail-status--${view.status}`}>
              {view.status === 'pending' ? '待验证' : view.status === 'scored' ? '已验证' : '部分'}
            </span>
          </h3>
          <button className="macro__detail-close" onClick={onClose}>×</button>
        </div>

        <div className="macro__detail-summary">{view.summary}</div>

        <h4 className="macro__detail-subtitle">
          宏观状态验证
          {view.macro_accuracy != null && (
            <span className={view.macro_accuracy >= 0.5 ? 'is-up' : 'is-down'}>
              命中率 {fmtPct(view.macro_accuracy)}
            </span>
          )}
        </h4>
        <div className="macro__detail-grid">
          {view.macro_judgments.map((j, i) => {
            const val = macroValMap[j.dimension];
            return (
              <div key={i} className="macro__val-card">
                <div className="macro__val-dim">{DIM_LABEL[j.dimension] || j.dimension}</div>
                <div className="macro__val-row">
                  <span>预测</span>
                  <span className={STANCE_COLOR[j.stance] || 'is-flat'}>
                    {STANCE_LABEL[j.stance] || j.stance}
                  </span>
                </div>
                <div className="macro__val-row">
                  <span>实际</span>
                  {val?.actual_dir ? (
                    <span className={STANCE_COLOR[val.actual_dir] || 'is-flat'}>
                      {STANCE_LABEL[val.actual_dir] || val.actual_dir}
                      {val.actual_value != null && ` (${fmtNum(val.actual_value, 1)})`}
                    </span>
                  ) : (
                    <span className="is-flat">{val?.note || '—'}</span>
                  )}
                </div>
                <div className={`macro__val-hit ${val?.hit == null ? 'is-flat' : (val.hit ? 'is-up' : 'is-down')}`}>
                  {val?.hit == null ? '—' : val.hit ? '命中' : '未中'}
                </div>
              </div>
            );
          })}
        </div>

        <h4 className="macro__detail-subtitle">
          资产方向验证
          {view.asset_accuracy != null && (
            <span className={view.asset_accuracy >= 0.5 ? 'num is-up' : 'num is-down'}>
              命中率 {fmtPct(view.asset_accuracy)}
            </span>
          )}
        </h4>
        <div className="macro__detail-grid">
          {view.asset_predictions.map((p, i) => {
            const val = assetValMap[p.symbol];
            return (
              <div key={i} className="macro__val-card">
                <div className="macro__val-dim">{p.name}</div>
                <div className="macro__val-row">
                  <span>预测</span>
                  <span className={STANCE_COLOR[p.predicted] || 'is-flat'}>
                    {STANCE_LABEL[p.predicted] || p.predicted}
                  </span>
                </div>
                <div className="macro__val-row">
                  <span>实际</span>
                  {val?.actual_dir ? (
                    <span className={STANCE_COLOR[val.actual_dir] || 'is-flat'}>
                      {STANCE_LABEL[val.actual_dir] || val.actual_dir}
                      {val.actual_return != null && ` (${val.actual_return > 0 ? '+' : ''}${val.actual_return}%)`}
                    </span>
                  ) : (
                    <span className="is-flat">{val?.note || '—'}</span>
                  )}
                </div>
                <div className={`macro__val-hit ${val?.hit == null ? 'is-flat' : (val.hit ? 'is-up' : 'is-down')}`}>
                  {val?.hit == null ? '—' : val.hit ? '命中' : '未中'}
                </div>
              </div>
            );
          })}
        </div>

        <h4 className="macro__detail-subtitle">预测期内指数走势（判断点 → 验证点）</h4>
        {trackLoading ? (
          <StateView state="loading" text="加载走势中…" />
        ) : trackData && trackData.tracks?.length ? (
          <div className="macro__tracks">
            {trackData.tracks.slice(0, 6).map((t: any) => (
              <TrackChart key={t.symbol} track={t} snapshotDate={trackData.snapshot_point} />
            ))}
          </div>
        ) : (
          <StateView state="empty" text="暂无走势数据" />
        )}
      </div>
    </div>
  );
};

const TrackChart: React.FC<{track: any; snapshotDate: string}> = ({track, snapshotDate}) => {
  const bars = (track.bars || []).map((b: any) => ({date: b.date, close: b.close}));
  return (
    <div className="macro__track">
      <div className="macro__track-head">
        <span className="macro__track-name">{track.name}</span>
        <span className={`macro__track-pred ${STANCE_COLOR[track.predicted] || 'is-flat'}`}>
          预测 {STANCE_LABEL[track.predicted] || track.predicted}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={bars} margin={{top: 5, right: 5, bottom: 0, left: 0}}>
          <XAxis dataKey="date" hide />
          <YAxis domain={['auto', 'auto']} hide />
          <Tooltip {...tooltipProps} />
          <Line
            type="monotone" dataKey="close" stroke={CHART_COLORS[0]}
            strokeWidth={1.5} dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};
