/**
 * 看板数据模型 — 布局 JSON(version 1)的前端类型与纯函数。
 *
 * 网格:12 列 × 32px 行;x/y/w/h 为网格单位,允许小数(Alt 自由定位的
 * 产物);默认拖拽/缩放吸附 = 坐标四舍五入取整。
 */

export type PresetKey = '3m' | '6m' | '1y' | '3y' | '5y' | 'all' | 'custom';

export interface TimeRangeState {
  preset: PresetKey;
  start: string | null;  // 'YYYY-MM-DD',仅 custom 使用
  end: string | null;
}

export interface DateRange {
  start: string | null;
  end: string | null;
}

export type CardType = 'kline' | 'financial_trend' | 'metric' | 'index_pe';

export interface CardBase {
  id: string;
  title: string;
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
  opacity: number;  // 0.15 ~ 1
}

/** K线卡技术指标配置(⋯菜单勾选+参数弹窗写入,随布局自动保存) */
export interface KlineIndicatorConfig {
  indicators: { macd: boolean; rsi: boolean; boll: boolean };
  params: {
    macd: { fast: number; slow: number; signal: number };
    rsi: { period: number };
    boll: { period: number; stdDev: number };
  };
}

/** 工厂函数(非共享常量,防调用方就地修改污染默认值) */
export function defaultKlineConfig(): KlineIndicatorConfig {
  return {
    indicators: {macd: false, rsi: false, boll: false},
    params: {
      macd: {fast: 12, slow: 26, signal: 9},
      rsi: {period: 14},
      boll: {period: 20, stdDev: 2},
    },
  };
}

const clampInt = (v: unknown, dflt: number): number => {
  const n = Number(v);
  return Number.isInteger(n) && n >= 2 && n <= 250 ? n : dflt;
};

/** GET 回来的 kline config 兜底:非法/缺字段回默认 */
export function normalizeKlineConfig(raw: unknown): KlineIndicatorConfig {
  const o = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const obj = (v: unknown): Record<string, unknown> =>
    v && typeof v === 'object' ? (v as Record<string, unknown>) : {};
  const ind = obj(o.indicators);
  const prm = obj(o.params);
  const macdP = obj(prm.macd);
  const rsiP = obj(prm.rsi);
  const bollP = obj(prm.boll);
  const d = defaultKlineConfig();
  let fast = clampInt(macdP.fast, d.params.macd.fast);
  let slow = clampInt(macdP.slow, d.params.macd.slow);
  if (fast >= slow) { fast = d.params.macd.fast; slow = d.params.macd.slow; }
  const sd = Number(bollP.stdDev);
  return {
    indicators: {
      macd: ind.macd === true,
      rsi: ind.rsi === true,
      boll: ind.boll === true,
    },
    params: {
      macd: {fast, slow, signal: clampInt(macdP.signal, d.params.macd.signal)},
      rsi: {period: clampInt(rsiP.period, d.params.rsi.period)},
      boll: {
        period: clampInt(bollP.period, d.params.boll.period),
        stdDev: isFinite(sd) && sd >= 0.5 && sd <= 5 ? sd : d.params.boll.stdDev,
      },
    },
  };
}

export interface KlineCardData extends CardBase {
  type: 'kline';
  symbol: string;
  config: KlineIndicatorConfig;
}

export interface FinancialTrendCardData extends CardBase {
  type: 'financial_trend';
  symbol: string;
  config: { metrics: string[] };  // FINANCIAL_METRICS key 列表
}

export interface MetricCardData extends CardBase {
  type: 'metric';
  symbol: string;
  config: { metric: string };
}

export interface IndexPeCardData extends CardBase {
  type: 'index_pe';
  symbol: null;
  config: { code: string };  // 如 '000300'
}

export type BoardCard =
  | KlineCardData
  | FinancialTrendCardData
  | MetricCardData
  | IndexPeCardData;

export interface BoardLayout {
  version: 1;
  timeRange: TimeRangeState;
  maxZ: number;
  cards: BoardCard[];
}

export const GRID_COLS = 12;
export const GRID_ROW_PX = 32;
export const MIN_W = 2;
export const MIN_H = 3;

/** 卡片 id:randomUUID 仅安全上下文(https/localhost)可用,HTTP+IP 访问走 getRandomValues 兜底 */
export function uuid(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export const EMPTY_LAYOUT: BoardLayout = {
  version: 1,
  timeRange: {preset: '1y', start: null, end: null},
  maxZ: 0,
  cards: [],
};

export const DEFAULT_SIZE: Record<CardType, {w: number; h: number}> = {
  kline: {w: 6, h: 14},
  financial_trend: {w: 6, h: 14},
  metric: {w: 2, h: 3},
  index_pe: {w: 6, h: 14},
};

export const PRESET_OPTIONS: {key: PresetKey; label: string}[] = [
  {key: '3m', label: '近3月'},
  {key: '6m', label: '近6月'},
  {key: '1y', label: '近1年'},
  {key: '3y', label: '近3年'},
  {key: '5y', label: '近5年'},
  {key: 'all', label: '全部'},
  {key: 'custom', label: '自定义'},
];

const PRESET_MONTHS: Record<'3m' | '6m' | '1y' | '3y' | '5y', number> = {
  '3m': 3, '6m': 6, '1y': 12, '3y': 36, '5y': 60,
};

/** 全局时间范围 → 具体起止日期(preset start 锚定请求日本地日,end=null 即今天) */
export function resolveDateRange(tr: TimeRangeState): DateRange {
  if (tr.preset === 'custom') return {start: tr.start, end: tr.end};
  if (tr.preset === 'all') return {start: null, end: null};
  const d = new Date();
  d.setDate(1);  // 先落到1号再减月,避免 8-31 减 6 月溢出到 3-03
  d.setMonth(d.getMonth() - PRESET_MONTHS[tr.preset]);
  const fmt = (x: Date) =>
    `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  return {start: fmt(d), end: null};
}

/** index-pe 端点只收整年数:月份跨度向上取整换算,全部=0 */
export function rangeToYears(range: DateRange): number {
  if (!range.start) return 0;
  const ms = Date.now() - new Date(range.start + 'T00:00:00').getTime();
  const months = ms / (1000 * 86400 * 30.44);
  return Math.max(1, Math.ceil(months / 12));
}

/** 首个空网格位(按整格占用的包围盒求交;自由摆放的小数卡取 floor/ceil) */
export function findFreeSlot(
  cards: BoardCard[],
  w: number,
  h: number,
): {x: number; y: number} {
  const rects = cards.map((c) => ({
    x1: Math.floor(c.x),
    y1: Math.floor(c.y),
    x2: Math.ceil(c.x + c.w),
    y2: Math.ceil(c.y + c.h),
  }));
  const hit = (x: number, y: number) =>
    rects.some((r) => x < r.x2 && x + w > r.x1 && y < r.y2 && y + h > r.y1);
  for (let y = 0; y <= 500; y++) {
    for (let x = 0; x + w <= GRID_COLS; x++) {
      if (!hit(x, y)) return {x, y};
    }
  }
  return {x: 0, y: 0};
}

/** 财务指标池(/financial/detail series 实有字段,无 roe) */
export interface FinancialMetricDef {
  key: string;
  label: string;
  unit: 'yuan' | 'pct';
}

export const FINANCIAL_METRICS: FinancialMetricDef[] = [
  {key: 'revenue', label: '营业收入', unit: 'yuan'},
  {key: 'net_profit_parent', label: '归母净利润', unit: 'yuan'},
  {key: 'gross_margin', label: '毛利率', unit: 'pct'},
  {key: 'net_margin', label: '净利率', unit: 'pct'},
  {key: 'ocf', label: '经营现金流', unit: 'yuan'},
];

export const DEFAULT_TREND_METRICS = ['revenue', 'net_profit_parent'];

/** 指数 PE 卡可选宽基(与 Indices 页 MCG_INDICES 同源) */
export const INDEX_PE_LIST = [
  {code: '000300', name: '沪深300'},
  {code: '000016', name: '上证50'},
  {code: '000905', name: '中证500'},
  {code: '000852', name: '中证1000'},
  {code: '932000', name: '中证2000'},
  {code: '000903', name: '中证100'},
  {code: '000010', name: '上证180'},
  {code: '000985', name: '中证全指'},
  {code: '000688', name: '科创50'},
];

/** K线卡标的搜索兜底:核心指数(stock_info 搜索可能不含指数) */
export const CORE_INDEX_SYMBOLS = [
  {symbol: 'sh000001', name: '上证指数'},
  {symbol: 'sz399001', name: '深证成指'},
  {symbol: 'sh000300', name: '沪深300'},
  {symbol: 'sz399006', name: '创业板指'},
];

const PRESETS: readonly string[] = PRESET_OPTIONS.map((p) => p.key);

const CARD_TYPES: readonly string[] = ['kline', 'financial_trend', 'metric', 'index_pe'];

/** GET 回来的 layout 兜底:缺字段/非法值填默认(按卡片类型),无法渲染的卡丢弃,不白屏 */
export function normalizeLayout(raw: unknown): BoardLayout {
  const obj =
    raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const rawCards = Array.isArray(obj.cards) ? obj.cards : [];
  const cards: BoardCard[] = [];
  for (const c of rawCards) {
    if (!c || typeof c !== 'object' || typeof (c as Record<string, unknown>).id !== 'string') {
      continue;
    }
    const o = c as Record<string, unknown>;
    const known = CARD_TYPES.includes(String(o.type));
    const type = o.type as CardType;
    const size = known ? DEFAULT_SIZE[type] : {w: 6, h: 14};
    const num = (v: unknown, dflt: number) =>
      typeof v === 'number' && isFinite(v) ? v : dflt;
    const cfg =
      o.config && typeof o.config === 'object'
        ? (o.config as Record<string, unknown>)
        : {};
    const validMetrics = (ms: unknown) =>
      Array.isArray(ms)
        ? (ms as unknown[]).filter((m): m is string =>
            typeof m === 'string' &&
            FINANCIAL_METRICS.some((f) => f.key === m),
          )
        : [];
    const base = {
      id: o.id as string,
      title: typeof o.title === 'string' && o.title ? o.title : '未命名卡片',
      x: Math.max(0, num(o.x, 0)),
      y: Math.max(0, num(o.y, 0)),
      w: num(o.w, size.w),
      h: num(o.h, size.h),
      z: num(o.z, 0),
      opacity: Math.min(1, Math.max(0.15, num(o.opacity, 1))),
    };
    if (!known) {
      // 未知类型(未来版本/手改库): 原样保留,渲染层占位展示,PUT 不丢卡
      cards.push({
        ...base,
        type,
        symbol: typeof o.symbol === 'string' ? o.symbol : null,
        config: cfg,
      } as unknown as BoardCard);
    } else if (type === 'index_pe') {
      cards.push({
        ...base,
        type,
        symbol: null,
        config: {
          code:
            typeof cfg.code === 'string' && cfg.code
              ? cfg.code
              : INDEX_PE_LIST[0].code,
        },
      });
    } else if (type === 'kline') {
      cards.push({
        ...base,
        type,
        symbol: typeof o.symbol === 'string' ? o.symbol : '',
        config: normalizeKlineConfig(o.config),
      });
    } else if (type === 'financial_trend') {
      const ms = validMetrics(cfg.metrics);
      cards.push({
        ...base,
        type,
        symbol: typeof o.symbol === 'string' ? o.symbol : '',
        config: {metrics: ms.length > 0 ? ms : DEFAULT_TREND_METRICS},
      });
    } else {
      const metric =
        typeof cfg.metric === 'string' &&
        FINANCIAL_METRICS.some((f) => f.key === cfg.metric)
          ? cfg.metric
          : DEFAULT_TREND_METRICS[0];
      cards.push({
        ...base,
        type,
        symbol: typeof o.symbol === 'string' ? o.symbol : '',
        config: {metric},
      });
    }
  }
  const tr =
    obj.timeRange && typeof obj.timeRange === 'object'
      ? (obj.timeRange as Record<string, unknown>)
      : {};
  const preset = PRESETS.includes(String(tr.preset))
    ? (tr.preset as PresetKey)
    : '1y';
  return {
    version: 1,
    timeRange: {
      preset,
      start: typeof tr.start === 'string' ? tr.start : null,
      end: typeof tr.end === 'string' ? tr.end : null,
    },
    maxZ:
      typeof obj.maxZ === 'number'
        ? obj.maxZ
        : cards.reduce((m, c) => Math.max(m, c.z || 0), 0),
    cards,
  };
}

/** 元 → 万/亿/万亿(两位小数,负值按绝对值档位) */
export function fmtYuan(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + '万亿';
  if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (v / 1e4).toFixed(2) + '万';
  return v.toFixed(0);
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—';
  return v.toFixed(2) + '%';
}
