/**
 * Indices page — A-share index overview (broad-based + SW industry)
 *
 * Data: GET /market/indices   (market_index + sw_index, latest close & chg)
 *       GET /market/kline/{symbol}?interval=1d   (single index daily kline,
 *           _resolve_kline_table routes sh/sz/sw to index_ohlcv)
 *
 * Layout: core-index cards strip · list+chart split · full ranking table
 */
import React, { useEffect, useState, useCallback, useMemo } from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  CartesianGrid,
  Cell,
} from 'recharts';
import { getApiBase } from '../lib/api';
import { axisProps, colorDown, colorUp, gridProps } from '../lib/chartTheme';
import { PageHeader, StateView } from '../components/ui';
import { MarketCapGrowthChart } from '../components/MarketCapGrowthChart';
import { useMarketCapGrowth } from '../hooks/useMarketCapGrowth';
import { IndexPeChart } from '../components/IndexPeChart';
import { useIndexPe } from '../hooks/useIndexPe';
import './Indices.css';

const API_BASE = getApiBase();

// ── Types ────────────────────────────────────────────────────────────────────
interface IndexQuote {
  symbol: string;
  name: string;
  close: number;
  change_pct: number;
}

interface KlineBar {
  trade_date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
}

// Core indices shown as headline cards
const CORE_SYMBOLS = ['sh000001', 'sz399001', 'sh000300', 'sz399006'];

// 市值与业绩增长趋势区块支持的宽基指数（后端 quant_universe.index_constituents 对应）
const MCG_INDICES = [
  { code: '000300', name: '沪深300' },
  { code: '000016', name: '上证50' },
  { code: '000905', name: '中证500' },
  { code: '000852', name: '中证1000' },
  { code: '932000', name: '中证2000' },
  { code: '000903', name: '中证100' },
  { code: '000010', name: '上证180' },
  { code: '000985', name: '中证全指' },
  { code: '000688', name: '科创50' },
];

// 市盈率趋势窗口（years=0 → 全部，对齐后端 /financial/index-pe 语义）
const PE_WINDOWS: Array<[number, string]> = [
  [3, '近3年'], [5, '近5年'], [8, '近8年'], [10, '近10年'], [0, '全部'],
];

// ── 时间预设 ──────────────────────────────────────────────────────────────────
type PresetKey = 'today' | '1m' | '3m' | '6m' | '1y' | 'ytd' | 'custom';

interface DateRange {
  start: string;  // 'YYYY-MM-DD' 或空串（空=不传给后端）
  end: string;
}

const PRESETS: { key: PresetKey; label: string }[] = [
  { key: 'today', label: '今日' },
  { key: '1m', label: '近1月' },
  { key: '3m', label: '近3月' },
  { key: '6m', label: '近6月' },
  { key: '1y', label: '近1年' },
  { key: 'ytd', label: '今年' },
  { key: 'custom', label: '自定义' },
];

/** 预设 → 日期范围。today = 都空（等价无参 = 现状）；其余 end 始终为空（= 最新交易日）。 */
const presetToRange = (preset: PresetKey): DateRange => {
  const now = new Date();
  const fmt = (d: Date) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  };
  const daysAgo = (n: number) => { const d = new Date(now); d.setDate(d.getDate() - n); return d; };
  switch (preset) {
    case 'today':  return { start: '', end: '' };
    case '1m':     return { start: fmt(daysAgo(30)),  end: '' };
    case '3m':     return { start: fmt(daysAgo(90)),  end: '' };
    case '6m':     return { start: fmt(daysAgo(180)), end: '' };
    case '1y':     return { start: fmt(daysAgo(365)), end: '' };
    case 'ytd':    return { start: fmt(new Date(now.getFullYear(), 0, 1)), end: '' };
    case 'custom': return { start: '', end: '' };
  }
};

// ── Helpers ──────────────────────────────────────────────────────────────────
const fmtNum = (n: number, digits = 2) =>
  n == null || Number.isNaN(n) ? '-' : n.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

const fmtVol = (v: number) => {
  if (v == null || Number.isNaN(v)) return '-';
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
  return v.toFixed(0);
};

const fmtPct = (p: number) =>
  p == null || Number.isNaN(p) ? '-' : `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`;

const trendClass = (p: number) =>
  p > 0 ? 'is-up' : p < 0 ? 'is-down' : 'is-flat';

// ── Custom candlestick for recharts 2.x (no Candlestick primitive) ───────────
type CandleDatum = KlineBar & {
  wick: [number, number];   // [low, high]
  body: [number, number];   // [min(open,close), max(open,close)]
  isUp: boolean;
};

const toCandleData = (bars: KlineBar[]): CandleDatum[] =>
  bars.map((b) => ({
    ...b,
    wick: [b.low, b.high],
    body: [Math.min(b.open, b.close), Math.max(b.open, b.close)],
    isUp: b.close >= b.open,
  }));

// Renders a single candlestick: thin wick line + rectangular body.
// recharts passes x/width/y/height of the bar slot in pixels; because the Bar
// uses dataKey="wick" = [low, high], the slot spans the full high-low range,
// letting us place wick AND body accurately within one shape.
const CandleShape: React.FC<any> = (props) => {
  const { x, width, y, height, payload } = props;
  if (!payload) return null;
  const { open, close, low, high } = payload;
  const up = close >= open;
  const color = up ? colorUp : colorDown; // A-share: red up, green down
  const w = Math.max(width, 1);
  const cx = x + w / 2;
  // Slot maps [low, high] → [y+height, y]
  const yScale = (val: number) => {
    if (high === low) return y;
    return (y + height) - ((val - low) / (high - low)) * height;
  };
  const yOpen = yScale(open);
  const yClose = yScale(close);
  const yHigh = yScale(high);
  const yLow = yScale(low);
  const bodyTop = Math.min(yOpen, yClose);
  const bodyH = Math.max(Math.abs(yClose - yOpen), 1);
  return (
    <g>
      <line x1={cx} x2={cx} y1={yHigh} y2={yLow} stroke={color} strokeWidth={1} />
      <rect
        x={x + w * 0.3}
        y={bodyTop}
        width={w * 0.4}
        height={bodyH}
        fill={color}
        stroke={color}
      />
    </g>
  );
};

const ChartTooltip: React.FC<{ active?: boolean; payload?: any[] }> = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as CandleDatum;
  if (!d) return null;
  const up = d.isUp;
  const cls = up ? 'is-up' : 'is-down';
  return (
    <div className="indices__tooltip">
      <div className="indices__tooltip-date">{d.trade_date}</div>
      <div>开 <span className={cls}>{fmtNum(d.open)}</span></div>
      <div>收 <span className={cls}>{fmtNum(d.close)}</span></div>
      <div>高 <span className="is-up">{fmtNum(d.high)}</span></div>
      <div>低 <span className="is-down">{fmtNum(d.low)}</span></div>
      <div>量 <span>{fmtVol(d.volume)}</span></div>
    </div>
  );
};

// ── Page ─────────────────────────────────────────────────────────────────────
export const Indices: React.FC = () => {
  const [quotes, setQuotes] = useState<IndexQuote[]>([]);
  const [selected, setSelected] = useState<string>('sh000300');
  const [bars, setBars] = useState<KlineBar[]>([]);
  const [loadingQuotes, setLoadingQuotes] = useState(true);
  const [loadingBars, setLoadingBars] = useState(false);

  // ── 筛选条件 state ──
  const [category, setCategory] = useState<'all' | 'index' | 'sw'>('all');
  const [query, setQuery] = useState('');
  const [preset, setPreset] = useState<PresetKey>('today');
  const [customRange, setCustomRange] = useState<DateRange>({ start: '', end: '' });
  const [direction, setDirection] = useState<'all' | 'up' | 'down'>('all');

  const [mcgCode, setMcgCode] = useState('000300');
  const { data: mcgData, loading: mcgLoading, error: mcgError } =
    useMarketCapGrowth('index', mcgCode);
  const mcgName =
    MCG_INDICES.find((i) => i.code === mcgCode)?.name ?? mcgCode;

  const [peCode, setPeCode] = useState('000300');
  const [peYears, setPeYears] = useState(8);
  const { data: peData, loading: peLoading, error: peError } =
    useIndexPe(peCode, peYears);
  const peName = MCG_INDICES.find((i) => i.code === peCode)?.name ?? peCode;

  // 实际驱动请求的范围：custom 时取 customRange，否则按 preset 推导。
  // 必须 useMemo：presetToRange 每次调用返回新对象，而 quotes/kline 两个
  // effect 依赖 range——身份不稳会 fetch→setState→重渲染→再 fetch 死循环
  // （实测约 97 请求/秒）。
  const range: DateRange = useMemo(
    () => (preset === 'custom' ? customRange : presetToRange(preset)),
    [preset, customRange],
  );

  // Fetch all index quotes (merge market_index + sw_index from /market/indices)
  const fetchQuotes = useCallback(async (r: DateRange) => {
    setLoadingQuotes(true);
    try {
      const qs = new URLSearchParams();
      if (r.start) qs.set('start', r.start);
      if (r.end) qs.set('end', r.end);
      const suffix = qs.toString() ? `?${qs.toString()}` : '';
      const res = await fetch(`${API_BASE}/market/indices${suffix}`);
      const json = await res.json();
      const d = json.data || {};
      setQuotes([...(d.market_index || []), ...(d.sw_index || [])]);
    } catch {
      setQuotes([]);
    } finally {
      setLoadingQuotes(false);
    }
  }, []);

  // Fetch kline for selected index (generic /market/kline routes to index_ohlcv)
  const fetchBars = useCallback(async (symbol: string, r: DateRange) => {
    setLoadingBars(true);
    try {
      const qs = new URLSearchParams({ interval: '1d' });
      if (r.start) qs.set('start', r.start);
      if (r.end) qs.set('end', r.end);
      // 有范围时不限 limit（让后端按日期裁剪）；无范围时保留 400 根默认行为
      if (!r.start && !r.end) qs.set('limit', '400');
      const res = await fetch(`${API_BASE}/market/kline/${symbol}?${qs.toString()}`);
      const json = await res.json();
      setBars(json.data?.bars || []);
    } catch {
      setBars([]);
    } finally {
      setLoadingBars(false);
    }
  }, []);

  useEffect(() => {
    fetchQuotes(range);
  }, [range, fetchQuotes]);

  useEffect(() => {
    fetchBars(selected, range);
  }, [selected, range, fetchBars]);

  const coreQuotes = quotes.filter((q) => CORE_SYMBOLS.includes(q.symbol));
  const selectedQuote = quotes.find((q) => q.symbol === selected);

  // P0b: 宽基指数 PE_TTM 10y 分位（key = 去前缀的指数代码）
  const [idxPct, setIdxPct] = useState<Record<string, number | null>>({});
  useEffect(() => {
    // sh000300 → 000300（匹配 index_valuation_daily.symbol）
    const codeMap: Record<string, string> = {
      'sh000300': '000300', 'sh000016': '000016',
      'sh000905': '000905', 'sz399006': '399006',
    };
    const entries = Object.entries(codeMap);
    let cancelled = false;
    Promise.all(entries.map(([sym, code]) =>
      fetch(`${API_BASE}/financial/index-valuation-percentile?scope=index&code=${code}&window=10y&metrics=pe_ttm`)
        .then((r) => r.json())
        .then((j) => [sym, j.data?.metrics?.pe_ttm?.stats?.percentile ?? null] as [string, number | null])
        .catch(() => [sym, null] as [string, number | null])
    )).then((pairs) => {
      if (cancelled) return;
      const m: Record<string, number | null> = {};
      for (const [sym, pct] of pairs) m[sym] = pct;
      setIdxPct(m);
    });
    return () => { cancelled = true; };
  }, []);

  // 应用 category + query + direction 三道前端过滤（range 在请求层已生效）
  const filtered = useMemo(() => {
    return quotes.filter((q) => {
      if (category === 'index' && !/^(sh|sz)\d/i.test(q.symbol)) return false;
      if (category === 'sw' && !q.symbol.toLowerCase().startsWith('sw')) return false;
      if (query) {
        const k = query.toLowerCase();
        if (!q.name.toLowerCase().includes(k) && !q.symbol.toLowerCase().includes(k)) return false;
      }
      if (direction === 'up' && q.change_pct <= 0) return false;
      if (direction === 'down' && q.change_pct >= 0) return false;
      return true;
    });
  }, [quotes, category, query, direction]);

  const sortedQuotes = useMemo(
    () => [...filtered].sort((a, b) => b.change_pct - a.change_pct),
    [filtered],
  );
  const chartData = useMemo(() => toCandleData(bars), [bars]);
  // Price Y-axis domain: pad the [min low, max high] range slightly for headroom
  const priceDomain: [number | string, number | string] = useMemo(() => {
    if (!chartData.length) return ['auto', 'auto'];
    // 用循环而非 Math.min/max(...bigArray)，避免大数组时的调用栈与重复计算开销。
    let lo = Infinity, hi = -Infinity;
    for (const d of chartData) {
      if (d.low < lo) lo = d.low;
      if (d.high > hi) hi = d.high;
    }
    const pad = (hi - lo) * 0.05 || hi * 0.01;
    return [lo - pad, hi + pad];
  }, [chartData]);

  return (
    <div className="indices">
      <PageHeader title="指数行情" subtitle="A 股核心宽基 / 行业 / 主题指数" />

      {/* ── 筛选条 ── */}
      <section className="indices__filters">
        {/* 分类切换 */}
        <div className="indices__filter-group">
          <span className="indices__filter-label">分类</span>
          {([
            { k: 'all', label: '全部' },
            { k: 'index', label: '宽基' },
            { k: 'sw', label: '申万行业' },
          ] as const).map((t) => (
            <button
              key={t.k}
              type="button"
              className={`indices__pill ${category === t.k ? 'indices__pill--active' : ''}`}
              onClick={() => setCategory(t.k)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* 搜索框 */}
        <div className="indices__filter-group">
          <input
            className="indices__search"
            type="text"
            placeholder="搜索指数名称 / 代码"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        {/* 时间预设 */}
        <div className="indices__filter-group">
          <span className="indices__filter-label">周期</span>
          {PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              className={`indices__pill ${preset === p.key ? 'indices__pill--active' : ''}`}
              onClick={() => setPreset(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* 自定义日期（preset=custom 时展开） */}
        <div className={`indices__custom-range ${preset === 'custom' ? 'indices__custom-range--show' : ''}`}>
          <input
            className="indices__date-input"
            type="date"
            value={customRange.start}
            onChange={(e) => setCustomRange((r) => ({ ...r, start: e.target.value }))}
          />
          <span className="indices__filter-label">至</span>
          <input
            className="indices__date-input"
            type="date"
            value={customRange.end}
            onChange={(e) => setCustomRange((r) => ({ ...r, end: e.target.value }))}
          />
        </div>

        {/* 方向筛选 */}
        <div className="indices__filter-group">
          <span className="indices__filter-label">方向</span>
          {([
            { k: 'all', label: '全部' },
            { k: 'up', label: '仅涨' },
            { k: 'down', label: '仅跌' },
          ] as const).map((t) => (
            <button
              key={t.k}
              type="button"
              className={`indices__pill ${direction === t.k ? 'indices__pill--active' : ''}`}
              onClick={() => setDirection(t.k)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </section>

      {/* ── Core index cards ── */}
      <section className="indices__cards">
        {loadingQuotes
          ? [0, 1, 2, 3].map((i) => (
              <div key={i} className="index-card skeleton" style={{ height: 110 }} />
            ))
          : coreQuotes.map((q) => {
              const cls = trendClass(q.change_pct);
              return (
                <div
                  key={q.symbol}
                  className={`index-card ${selected === q.symbol ? 'index-card--active' : ''}`}
                  onClick={() => setSelected(q.symbol)}
                >
                  <div className="index-card__name">
                    {q.name} <span className="index-card__symbol">{q.symbol}</span>
                  </div>
                  <div className={`num index-card__price ${cls}`}>{fmtNum(q.close)}</div>
                  <div className={`num index-card__change ${cls}`}>
                    {fmtPct(q.change_pct)}
                  </div>
                  {idxPct[q.symbol] !== undefined && idxPct[q.symbol] !== null && (
                    <div style={{
                      marginTop: 4,
                      fontSize: 11,
                      color: idxPct[q.symbol]! < 0.2 ? 'var(--color-success)'
                        : idxPct[q.symbol]! > 0.8 ? 'var(--color-danger)'
                        : 'var(--color-warning)',
                    }}>
                      PE 10y: {(idxPct[q.symbol]! * 100).toFixed(0)}%
                    </div>
                  )}
                </div>
              );
            })}
      </section>

      {/* ── List + chart split ── */}
      <section className="indices__main">
        {/* Index list */}
        <div className="indices__list">
          {loadingQuotes
            ? [0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="indices__list-item skeleton" style={{ height: 48 }} />
              ))
            : filtered.length === 0 ? (
              <StateView state="empty" text="无匹配结果" />
            ) : filtered.map((q) => {
                const cls = trendClass(q.change_pct);
                return (
                  <button
                    key={q.symbol}
                    type="button"
                    className={`indices__list-item ${selected === q.symbol ? 'indices__list-item--active' : ''}`}
                    onClick={() => setSelected(q.symbol)}
                  >
                    <div className="indices__list-info">
                      <span className="indices__list-name">{q.name}</span>
                      <span className="indices__list-symbol">{q.symbol}</span>
                    </div>
                    <div className="indices__list-quote">
                      <span className="num indices__list-close">{fmtNum(q.close)}</span>
                      <span className={`num indices__list-chg ${cls}`}>{fmtPct(q.change_pct)}</span>
                    </div>
                  </button>
                );
              })}
        </div>

        {/* Chart */}
        <div className="indices__chart-panel">
          <div className="indices__chart-header">
            <div className="indices__chart-title">
              {selectedQuote?.name || selected}
              <small>{selected}</small>
            </div>
            {selectedQuote && (
              <div className="indices__chart-quote">
                <span className={`num indices__chart-close ${trendClass(selectedQuote.change_pct)}`}>
                  {fmtNum(selectedQuote.close)}
                </span>
                <span className={`num indices__chart-change ${trendClass(selectedQuote.change_pct)}`}>
                  {fmtPct(selectedQuote.change_pct)}
                </span>
              </div>
            )}
          </div>
          <div className="indices__chart-body">
            {loadingBars ? (
              <StateView state="loading" />
            ) : chartData.length === 0 ? (
              <StateView state="empty" text="暂无 K 线数据" />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid {...gridProps} />
                  <XAxis
                    dataKey="trade_date"
                    {...axisProps}
                    minTickGap={40}
                  />
                  <YAxis
                    yAxisId="price"
                    orientation="right"
                    {...axisProps}
                    axisLine={false}
                    domain={priceDomain}
                  />
                  <YAxis
                    yAxisId="vol"
                    orientation="left"
                    hide
                    domain={[0, 'auto']}
                  />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar
                    yAxisId="vol"
                    dataKey="volume"
                    fill="rgba(255,255,255,0.10)"
                    isAnimationActive={false}
                  />
                  <Bar
                    yAxisId="price"
                    dataKey="wick"
                    shape={<CandleShape />}
                    isAnimationActive={false}
                  >
                    {chartData.map((d, i) => (
                      <Cell key={i} fill={d.isUp ? colorUp : colorDown} />
                    ))}
                  </Bar>
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </section>

      {/* ── 市值与业绩增长趋势 ── */}
      <section className="indices__mcg">
        <div className="indices__mcg-header">
          <h2 className="indices__mcg-title">市值与业绩增长趋势</h2>
          <div className="indices__mcg-switch">
            {MCG_INDICES.map((i) => (
              <button
                key={i.code}
                className={`indices__mcg-btn ${
                  mcgCode === i.code ? 'is-active' : ''
                }`}
                onClick={() => setMcgCode(i.code)}
              >
                {i.name}
              </button>
            ))}
          </div>
        </div>
        <div className="indices__mcg-body">
          <MarketCapGrowthChart
            title={`${mcgName}市值与业绩增长趋势`}
            data={mcgData}
            loading={mcgLoading}
            error={mcgError}
          />
        </div>
      </section>

      {/* ── 市盈率趋势（整体法） ── */}
      <section className="indices__mcg">
        <div className="indices__mcg-header">
          <h2 className="indices__mcg-title">市盈率趋势</h2>
          <div className="indices__mcg-switch">
            {PE_WINDOWS.map(([y, l]) => (
              <button
                key={y}
                className={`indices__mcg-btn ${
                  peYears === y ? 'is-active' : ''
                }`}
                onClick={() => setPeYears(y)}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <div className="indices__mcg-switch" style={{ marginBottom: 10 }}>
          {MCG_INDICES.map((i) => (
            <button
              key={i.code}
              className={`indices__mcg-btn ${
                peCode === i.code ? 'is-active' : ''
              }`}
              onClick={() => setPeCode(i.code)}
            >
              {i.name}
            </button>
          ))}
        </div>
        <div className="indices__mcg-body">
          <IndexPeChart
            title={`${peName}市盈率趋势`}
            subtitle={PE_WINDOWS.find(([y]) => y === peYears)?.[1] ?? ''}
            data={peData}
            loading={peLoading}
            error={peError}
          />
        </div>
      </section>

      {/* ── Ranking table ── */}
      <section className="indices__ranking">
        <h2 className="indices__ranking-title">涨跌幅排行</h2>
        <table className="indices__table">
          <thead>
            <tr>
              <th>指数</th>
              <th>代码</th>
              <th className="num">收盘</th>
              <th className="num">涨跌幅</th>
            </tr>
          </thead>
          <tbody>
            {sortedQuotes.length === 0 ? (
              <tr><td colSpan={4} className="indices__table-empty">无匹配结果</td></tr>
            ) : sortedQuotes.map((q) => (
              <tr key={q.symbol} onClick={() => setSelected(q.symbol)}>
                <td>{q.name}</td>
                <td className="indices__table-sym">{q.symbol}</td>
                <td className="num">{fmtNum(q.close)}</td>
                <td className={`num ${trendClass(q.change_pct)}`}>{fmtPct(q.change_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
};
