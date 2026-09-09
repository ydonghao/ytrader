/**
 * Financial Analysis Page（真实数据版）
 *
 * 数据源：
 *   GET /financial/detail/{symbol}?statement_type=income|balance|cashflow|abstract
 *   GET /financial/forecast?report_date=&type=preannounce|express
 *
 * Layout: 股票选择器(顶) · 6 Tab（摘要/利润表/资产负债表/现金流/业绩预告/对比）
 *
 * 数据来自 stock_financial_detail（akshare 同花顺三大报表，5200+ 只 A 股）
 * 和 stock_earnings_forecast（业绩预告/快报）。
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, LineChart, Line, ComposedChart,
  PieChart, Pie, Cell,
} from 'recharts';
import { getApiBase } from '../lib/api';
import { PeriodSwitcher } from '../components/PeriodSwitcher';
import type { Period } from '../components/PeriodSwitcher';
import { ValuationHub } from '../components/ValuationHub';
import { CommonSizePanel } from '../components/CommonSizePanel';
import { RatiosPanel } from '../components/RatiosPanel';
import { FiveForcesPanel } from '../components/FiveForcesPanel';
import { MarketCapGrowthPanel } from '../components/MarketCapGrowthPanel';
import { CashflowAnalysisPanel } from '../components/CashflowAnalysisPanel';
import { FundamentalReportPanel } from '../components/FundamentalReportPanel';
import { FinancialOverlayChart } from '../components/FinancialOverlayChart';
import type { MetricDef } from '../components/FinancialOverlayChart';
import {
  useStockValuationHistory,
  usePriceOverlays,
  useIndustryValuationSnapshot,
  buildOverlayData,
} from '../hooks/useFinancialOverlays';
import type { OverlayKey } from '../hooks/useFinancialOverlays';
import './Financial.css';
import { Button, PageHeader, StateView, Tabs } from '../components/ui';
import { CHART_COLORS, axisProps, chartBorder, chartTextSecondary, colorOrange, gridProps, tooltipProps } from '../lib/chartTheme';

const API_BASE = getApiBase();

// ── Types ────────────────────────────────────────────────────────────────────

/** 三大报表单期数据（固定列 + detail JSONB） */
interface StatementRow {
  report_date: string;
  // 利润表
  revenue: number | null;
  operating_cost: number | null;
  gross_profit: number | null;
  sell_expense: number | null;
  admin_expense: number | null;
  rd_expense: number | null;
  fin_expense: number | null;
  operating_profit: number | null;
  net_profit: number | null;
  net_profit_parent: number | null;
  net_profit_deduct: number | null;
  basic_eps: number | null;
  // 资产负债表
  monetary_funds: number | null;
  accounts_receivable: number | null;
  inventory: number | null;
  fixed_assets: number | null;
  goodwill: number | null;
  total_assets: number | null;
  total_liabilities: number | null;
  equity: number | null;
  equity_parent: number | null;
  short_loan: number | null;
  long_loan: number | null;
  // 现金流量表
  ocf: number | null;
  icf: number | null;
  fcf: number | null;
  cash_end: number | null;
  // 派生指标
  gross_margin: number | null;
  net_margin: number | null;
  debt_ratio: number | null;
  // 全科目明细
  detail: Record<string, number | null> | null;
}

interface DetailResponse {
  symbol: string;
  statement_type: string;
  market: string;
  latest_date: string | null;
  total_periods: number;
  series: StatementRow[];
}

interface ForecastItem {
  symbol: string;
  company_name: string | null;
  forecast_type: string;
  report_date: string | null;
  announce_date: string | null;
  metric: string;
  forecast_value: number | null;
  change_pct: number | null;
  prev_value: number | null;
  forecast_type_label: string | null;
  revenue: number | null;
  net_profit: number | null;
  roe: number | null;
  eps: number | null;
}

interface ForecastResponse {
  report_date: string | null;
  count: number;
  items: ForecastItem[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtYuan(v?: number | null, decimals = 2): string {
  if (v == null) return '—';
  if (Math.abs(v) >= 1e12) return (v / 1e12).toFixed(decimals) + '万亿';
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(decimals) + '亿';
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(decimals) + '万';
  return v.toFixed(decimals);
}

function fmtPct(v?: number | null): string {
  if (v == null) return '—';
  return v.toFixed(2) + '%';
}

function fmtNum(v?: number | null, decimals = 2): string {
  if (v == null) return '—';
  return v.toLocaleString('en-US', { maximumFractionDigits: decimals });
}

function reportLabel(dateStr: string): string {
  if (!dateStr) return '—';
  const d = dateStr.slice(0, 10);
  const [y, m] = d.split('-');
  const qi: Record<string, string> = { '03': 'Q1', '06': 'H1', '09': 'Q3', '12': '年报' };
  return `${y}${qi[m] || 'Q' + (Number(m) / 3 | 0)}`;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function MetricCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: 'green' | 'red' | 'default' }) {
  return (
    <div className={`fin-metric-card ${color ? `fin-metric-card--${color}` : ''}`}>
      <div className="fin-metric-card__label">{label}</div>
      <div className="fin-metric-card__value">{value}</div>
      {sub && <div className="fin-metric-card__sub">{sub}</div>}
    </div>
  );
}

function FinTable({ headers, rows }: { headers: string[]; rows: (string | number | null | React.ReactNode)[][] }) {
  return (
    <div className="fin-table-wrap">
      <table className="fin-table">
        <thead>
          <tr>{headers.map((h, i) => <th key={i}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? 'fin-table__row--alt' : ''}>
              {row.map((cell, ci) => <td key={ci}>{cell != null ? (cell as React.ReactNode) : '—'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Stock Search Input ────────────────────────────────────────────────────────

function StockSearch({ value, onSelect }: { value: string; onSelect: (sym: string) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<{ symbol: string; name: string }[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const reqIdRef = useRef(0);

  const search = useCallback(async (q: string) => {
    if (q.trim().length < 1) { setResults([]); setLoading(false); return; }
    const reqId = ++reqIdRef.current;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/market/search?q=${encodeURIComponent(q)}&limit=10`);
      const json = await res.json();
      // 丢弃过期响应（用户又按了键）
      if (reqId !== reqIdRef.current) return;
      if (json.code === 0 && json.data) {
        setResults(json.data.map((s: any) => ({ symbol: s.symbol, name: s.name || s.symbol })));
      }
    } catch { /* ignore */ }
    if (reqId === reqIdRef.current) setLoading(false);
  }, []);

  // 防抖：输入变化后 200ms 才发请求，避免连续按键打满后端
  useEffect(() => {
    const q = query;
    const t = setTimeout(() => search(q), 200);
    return () => clearTimeout(t);
  }, [query, search]);

  return (
    <div className="fin-search">
      <input
        className="fin-search__input"
        placeholder="搜索股票代码/名称（如 600519 或 茅台）"
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
      />
      {open && results.length > 0 && (
        <div className="fin-search__dropdown">
          {results.map(r => (
            <div
              key={r.symbol}
              className="fin-search__item"
              onClick={() => { onSelect(r.symbol); setQuery(`${r.symbol} ${r.name}`); setOpen(false); }}
            >
              <span className="fin-search__symbol">{r.symbol}</span>
              <span className="fin-search__name">{r.name}</span>
            </div>
          ))}
        </div>
      )}
      {open && !loading && results.length === 0 && query.length >= 1 && (
        <div className="fin-search__dropdown"><div className="fin-search__empty">无匹配结果</div></div>
      )}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

type TabType = 'summary' | 'income' | 'balance' | 'cashflow' | 'commonsize' | 'ratios' | 'fiveforces' | 'cashflowanalysis' | 'forecast' | 'compare' | 'valuation' | 'marketcapgrowth' | 'fundamental';

const POPULAR_SYMBOLS = ['sh600519', 'sh600036', 'sh600000', 'sz000001', 'sh601318'];

// ── 可选指标图表（模块级定义，避免随父组件每次渲染重新创建组件身份导致全量重挂载）──
// MetricDef 类型从 FinancialOverlayChart 导入，避免重复定义。

const SERIES_COLORS = [CHART_COLORS[1], CHART_COLORS[0], colorOrange, CHART_COLORS[5], '#bc8cff', '#ff7b72', '#79c0ff', '#56d364'];

const SelectableChart: React.FC<{
  chartId: string;
  title: string;
  data: any[];
  metrics: MetricDef[];
  type: 'bar' | 'line';
  selectedKeys: string[];
  onToggleMetric: (chartId: string, metricKey: string) => void;
}> = React.memo(({chartId, title, data, metrics, type, selectedKeys, onToggleMetric}) => {
  const selected = selectedKeys;
  const selectedMetrics = metrics.filter(m => selected.includes(m.key));
  const isPercent = selectedMetrics.some(m => m.isPercent);
  const yFormatter = isPercent ? (v: number) => `${v}%` : (v: number) => `${v}亿`;
  const tooltipFormatter = isPercent
    ? (v: number, n: string) => [`${v?.toFixed(2)}%`, n]
    : (v: number, n: string) => [`${v?.toFixed(2)}亿`, n];

  return (
    <div className="fin-chart-card">
      <h3 className="fin-chart-card__title">{title}</h3>
      {/* 指标选择器 */}
      <div className="fin-metric-chips">
        {metrics.map(m => (
          <button
            key={m.key}
            className={`fin-metric-chip ${selected.includes(m.key) ? 'is-active' : ''}`}
            style={selected.includes(m.key) ? {borderColor: m.color, color: m.color} : undefined}
            onClick={() => onToggleMetric(chartId, m.key)}
          >
            <span className="fin-metric-chip__dot" style={{background: selected.includes(m.key) ? m.color : '#484f58'}} />
            {m.label}
          </button>
        ))}
      </div>
      {data.length > 0 && selectedMetrics.length > 0 ? (
        <ResponsiveContainer width="100%" height={300}>
          {type === 'bar' ? (
            <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" />
              <YAxis {...axisProps} tickFormatter={yFormatter} />
              <Tooltip {...tooltipProps} formatter={tooltipFormatter} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {selectedMetrics.map(m => (
                <Bar key={m.key} dataKey={m.key} name={m.label} fill={m.color} opacity={0.75} radius={[3, 3, 0, 0]} />
              ))}
            </BarChart>
          ) : (
            <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" />
              <YAxis {...axisProps} tickFormatter={yFormatter} />
              <Tooltip {...tooltipProps} formatter={tooltipFormatter} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {selectedMetrics.map(m => (
                <Line key={m.key} type="monotone" dataKey={m.key} name={m.label} stroke={m.color} strokeWidth={2} dot={{ r: 3 }} />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      ) : <StateView state="empty" text="暂无数据" />}
    </div>
  );
});
SelectableChart.displayName = 'SelectableChart';

// 三大报表可选指标定义（模块级常量）
const INCOME_METRICS: MetricDef[] = [
  {key: 'revenue', label: '营业收入', color: CHART_COLORS[1]},
  {key: 'netProfit', label: '净利润', color: CHART_COLORS[0]},
  {key: 'operatingCost', label: '营业成本', color: CHART_COLORS[5]},
  {key: 'grossProfit', label: '毛利润', color: colorOrange},
  {key: 'sellExpense', label: '销售费用', color: '#bc8cff'},
  {key: 'adminExpense', label: '管理费用', color: '#ff7b72'},
  {key: 'rdExpense', label: '研发费用', color: '#79c0ff'},
  {key: 'operatingProfit', label: '营业利润', color: '#56d364'},
  {key: 'grossMargin', label: '毛利率', color: CHART_COLORS[1], isPercent: true},
  {key: 'netMargin', label: '净利率', color: colorOrange, isPercent: true},
];
const BALANCE_METRICS: MetricDef[] = [
  {key: 'totalAssets', label: '总资产', color: CHART_COLORS[1]},
  {key: 'totalLiab', label: '总负债', color: CHART_COLORS[5]},
  {key: 'equity', label: '所有者权益', color: CHART_COLORS[0]},
  {key: 'monetaryFunds', label: '货币资金', color: colorOrange},
  {key: 'inventory', label: '存货', color: '#bc8cff'},
  {key: 'fixedAssets', label: '固定资产', color: '#ff7b72'},
  {key: 'accountsRec', label: '应收账款', color: '#79c0ff'},
  {key: 'debtRatio', label: '资产负债率', color: CHART_COLORS[0], isPercent: true},
];
const CASHFLOW_METRICS: MetricDef[] = [
  {key: 'ocf', label: '经营现金流', color: CHART_COLORS[1]},
  {key: 'icf', label: '投资现金流', color: CHART_COLORS[0]},
  {key: 'fcf', label: '筹资现金流', color: colorOrange},
  {key: 'cashEnd', label: '期末现金', color: CHART_COLORS[5]},
];
// 摘要 Tab 三张叠加图指标（模块级常量，避免每次渲染新数组触发 recharts 全量重算）
const SUMMARY_VALUATION_METRICS: MetricDef[] = [
  {key: 'stock_price', label: '股价', color: CHART_COLORS[5]},
  {key: 'industry_index', label: '行业指数', color: '#bc8cff'},
];
const SUMMARY_REV_METRICS: MetricDef[] = [
  {key: 'revenue', label: '营业收入', color: CHART_COLORS[1]},
  {key: 'netProfit', label: '净利润', color: CHART_COLORS[0]},
];
const SUMMARY_MARGIN_METRICS: MetricDef[] = [
  {key: 'grossMargin', label: '毛利率', color: CHART_COLORS[1], isPercent: true},
  {key: 'netMargin', label: '净利率', color: colorOrange, isPercent: true},
];

export const Financial: React.FC = () => {
  // 支持从 URL query 预填 symbol（如 Market 页跳转 /financial?symbol=00700）
  const initialSymbol = (() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const s = params.get('symbol');
      return s || 'sh600519';
    } catch { return 'sh600519'; }
  })();
  const [symbol, setSymbol] = useState(initialSymbol);
  const [activeTab, setActiveTab] = useState<TabType>('summary');
  const [showAllPeriods, setShowAllPeriods] = useState(false);
  // 图表选中指标（每张图独立，key = chartId）
  const [chartSelections, setChartSelections] = useState<Record<string, string[]>>({});

  // 周期 + 叠加层状态
  const [period, setPeriod] = useState<Period>('quarter');
  const [overlaySelection, setOverlaySelection] = useState<OverlayKey[]>([]);
  const [industrySwCode, setIndustrySwCode] = useState<string | null>(null);

  const toggleOverlay = useCallback((k: OverlayKey) => {
    setOverlaySelection((prev) =>
      prev.includes(k)
        ? prev.filter((x) => x !== k)
        : [...prev, k],
    );
  }, []);

  const toggleChartMetric = useCallback((chartId: string, metricKey: string) => {
    setChartSelections(prev => {
      const current = prev[chartId] || [];
      const next = current.includes(metricKey)
        ? current.filter(k => k !== metricKey)
        : [...current, metricKey];
      return {...prev, [chartId]: next.length > 0 ? next : current}; // 至少保留1个
    });
  }, []);

  // 取某图的选中指标：未设置时默认取前 3 个。
  const sel = (chartId: string, metrics: MetricDef[]) =>
    chartSelections[chartId] || metrics.slice(0, 3).map(m => m.key);

  // 时间范围：起止日期 + 快捷模式
  const today = new Date().toISOString().slice(0, 10);
  const [startDate, setStartDate] = useState('');   // 空=不限（从最早开始）
  const [endDate, setEndDate] = useState('');       // 空=不限（到最新）

  // 各报表数据（独立请求）
  const [incomeData, setIncomeData] = useState<StatementRow[]>([]);
  const [balanceData, setBalanceData] = useState<StatementRow[]>([]);
  const [cashflowData, setCashflowData] = useState<StatementRow[]>([]);
  const [forecastData, setForecastData] = useState<ForecastItem[]>([]);
  const [forecastDate, setForecastDate] = useState<string>('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 股票基本信息（抬头展示）
  const [profile, setProfile] = useState<{
    name?: string; market?: string; total_mv?: number; pe_ttm?: number;
    pb?: number; industry?: string; report_periods?: number;
    latest_report?: string; business_scope?: string; list_date?: string;
  } | null>(null);

  // 对比数据
  const [compareInput, setCompareInput] = useState('sh600519,sh600036');
  const [compareData, setCompareData] = useState<{ symbol: string; latest: StatementRow | null }[]>([]);

  // 构建 API 查询参数（日期范围 or limit）
  const buildQuery = useCallback(() => {
    const params = new URLSearchParams();
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    // 无日期范围时用 limit 兜底（拉全量）
    if (!startDate && !endDate) params.set('limit', '200');
    return params.toString();
  }, [startDate, endDate]);

  // 拉取三大表数据
  const fetchStatements = useCallback(async (sym: string, qs: string, p: Period) => {
    setLoading(true);
    setError(null);
    try {
      const [inc, bal, cf] = await Promise.all([
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=income&period=${p}&${qs}`).then(r => r.json()),
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=balance&period=${p}&${qs}`).then(r => r.json()),
        fetch(`${API_BASE}/financial/detail/${sym}?statement_type=cashflow&period=${p}&${qs}`).then(r => r.json()),
      ]);
      if (inc.code === 0 && inc.data) setIncomeData(inc.data.series || []);
      else setIncomeData([]);
      if (bal.code === 0 && bal.data) setBalanceData(bal.data.series || []);
      else setBalanceData([]);
      if (cf.code === 0 && cf.data) setCashflowData(cf.data.series || []);
      else setCashflowData([]);
    } catch (e: any) {
      setError(e.message || '数据加载失败');
      setIncomeData([]); setBalanceData([]); setCashflowData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // 拉取业绩预告/快报（切到该 Tab 时才拉）
  const fetchForecast = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/financial/forecast?type=preannounce&limit=50`);
      const json = await res.json();
      if (json.code === 0 && json.data) {
        setForecastData(json.data.items || []);
        setForecastDate(json.data.report_date || '');
      }
    } catch { /* ignore */ }
  }, []);

  // 拉取股票基本信息
  const fetchProfile = useCallback(async (sym: string) => {
    try {
      const res = await fetch(`${API_BASE}/financial/profile/${sym}`);
      const json = await res.json();
      if (json.code === 0 && json.data) {
        setProfile(json.data);
      } else {
        setProfile(null);
      }
    } catch { setProfile(null); }
  }, []);

  // 拉取对比数据
  const fetchCompare = useCallback(async (input: string) => {
    const syms = input.split(',').map(s => s.trim()).filter(s => s).slice(0, 4);
    const results = await Promise.all(
      syms.map(async sym => {
        try {
          const res = await fetch(`${API_BASE}/financial/detail/${sym}?statement_type=income&limit=1`);
          const json = await res.json();
          if (json.code === 0 && json.data?.series?.length) {
            return { symbol: sym, latest: json.data.series[0] };
          }
        } catch { /* ignore */ }
        return { symbol: sym, latest: null };
      })
    );
    setCompareData(results);
  }, []);

  useEffect(() => {
    fetchStatements(symbol, buildQuery(), period);
    fetchProfile(symbol);
  }, [symbol, buildQuery, fetchStatements, fetchProfile, period]);

  useEffect(() => {
    if (activeTab === 'forecast' && forecastData.length === 0) {
      fetchForecast();
    }
  }, [activeTab, forecastData.length, fetchForecast]);

  // 对比输入防抖：切到 compare Tab 立即拉一次，之后每次按键 300ms 内只触发一次请求
  useEffect(() => {
    if (activeTab !== 'compare') return;
    const timer = setTimeout(() => fetchCompare(compareInput), 300);
    return () => clearTimeout(timer);
  }, [activeTab, compareInput, fetchCompare]);

  // 图表数据：营收/净利趋势（按选中的时间范围）
  const trendData = useMemo(() => {
    return incomeData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      reportDate: r.report_date?.slice(0, 10) || '',
      revenue: r.revenue ? r.revenue / 1e8 : null,
      netProfit: r.net_profit ? r.net_profit / 1e8 : null,
      grossMargin: r.gross_margin,
      netMargin: r.net_margin,
    }));
  }, [incomeData]);

  // 利润表趋势数据（柱状+折线用，升序）
  const incomeTrend = useMemo(() => {
    return incomeData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      revenue: r.revenue ? r.revenue / 1e8 : null,
      netProfit: r.net_profit ? r.net_profit / 1e8 : null,
      grossMargin: r.gross_margin,
      netMargin: r.net_margin,
    }));
  }, [incomeData]);

  // 利润表最新期费用构成（饼图用）
  const incomePie = useMemo(() => {
    if (!incomeData[0]) return [];
    const r = incomeData[0];
    return [
      { name: '营业成本', value: r.operating_cost || 0 },
      { name: '销售费用', value: r.sell_expense || 0 },
      { name: '管理费用', value: r.admin_expense || 0 },
      { name: '研发费用', value: r.rd_expense || 0 },
      { name: '财务费用', value: r.fin_expense || 0 },
    ].filter(d => d.value > 0);
  }, [incomeData]);

  // 资产负债表趋势数据
  const balanceTrend = useMemo(() => {
    return balanceData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      totalAssets: r.total_assets ? r.total_assets / 1e8 : null,
      totalLiab: r.total_liabilities ? r.total_liabilities / 1e8 : null,
      debtRatio: r.debt_ratio,
    }));
  }, [balanceData]);

  // 资产负债表最新期资产构成（饼图用）
  const balancePie = useMemo(() => {
    if (!balanceData[0]) return [];
    const r = balanceData[0];
    return [
      { name: '货币资金', value: r.monetary_funds || 0 },
      { name: '应收账款', value: r.accounts_receivable || 0 },
      { name: '存货', value: r.inventory || 0 },
      { name: '固定资产', value: r.fixed_assets || 0 },
      { name: '商誉', value: r.goodwill || 0 },
    ].filter(d => d.value > 0);
  }, [balanceData]);

  // 现金流量表趋势数据
  const cashflowTrend = useMemo(() => {
    return cashflowData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      ocf: r.ocf ? r.ocf / 1e8 : null,
      icf: r.icf ? r.icf / 1e8 : null,
      fcf: r.fcf ? r.fcf / 1e8 : null,
    }));
  }, [cashflowData]);

  // 现金流量表最新期构成（饼图用，取绝对值避免负值）
  const cashflowPie = useMemo(() => {
    if (!cashflowData[0]) return [];
    const r = cashflowData[0];
    return [
      { name: '期末现金余额', value: r.cash_end || 0 },
      { name: '经营现金流', value: Math.abs(r.ocf || 0) },
      { name: '投资现金流', value: Math.abs(r.icf || 0) },
      { name: '筹资现金流', value: Math.abs(r.fcf || 0) },
    ].filter(d => d.value > 0);
  }, [cashflowData]);

  // 对比雷达图数据
  const radarData = useMemo(() => {
    const metrics = [
      { key: '毛利率', get: (r: StatementRow) => r.gross_margin },
      { key: '净利率', get: (r: StatementRow) => r.net_margin },
      { key: '营收(亿)', get: (r: StatementRow) => r.revenue ? r.revenue / 1e8 : 0 },
      { key: '净利(亿)', get: (r: StatementRow) => r.net_profit ? r.net_profit / 1e8 : 0 },
    ];
    return metrics.map(m => {
      const entry: Record<string, string | number> = { metric: m.key };
      compareData.forEach(c => {
        entry[c.symbol] = c.latest ? (m.get(c.latest) || 0) : 0;
      });
      return entry;
    });
  }, [compareData]);

  const latest = incomeData[0];

  // ── 叠加层数据 ──
  const reportDates = useMemo(
    () => incomeData.map((r) => r.report_date?.slice(0, 10) || '').filter(Boolean),
    [incomeData],
  );
  const earliestDate = reportDates[reportDates.length - 1] || '';
  const latestDate = reportDates[0] || '';

  const { data: valMap } = useStockValuationHistory(symbol, reportDates);
  const { data: priceMap } = usePriceOverlays(
    symbol, industrySwCode, reportDates, earliestDate, latestDate,
  );
  const { data: industrySnap, list: industryList } =
    useIndustryValuationSnapshot(industrySwCode);

  // 估值分位状态与渲染已迁移至 ValuationHub（五法估值 Tab 内的「⑤ 乘数历史」）

  const overlayData = useMemo(
    () => buildOverlayData(valMap, priceMap, reportDates),
    [valMap, priceMap, reportDates],
  );

  // 摘要 Tab 估值卡只允许 pe/pb/ps 三层叠加（稳定引用，避免图表重渲染）
  const summaryOverlaySelection = useMemo(
    () => overlaySelection.filter((k) => ['pe', 'pb', 'ps'].includes(k)),
    [overlaySelection],
  );

  // 月报可见性：检查是否存在非季末非年末的报告期
  const hasMonthly = useMemo(() => {
    return incomeData.some((r) => {
      const m = r.report_date?.slice(5, 7);
      return m && !['03', '06', '09', '12'].includes(m);
    });
  }, [incomeData]);

  // 自动从 profile 设置默认行业（首次加载）
  useEffect(() => {
    if (industrySwCode === null && profile?.industry && industryList.length) {
      const found = industryList.find((it) => it.industry === profile.industry);
      if (found) setIndustrySwCode(found.sw_code);
    }
  }, [profile?.industry, industryList, industrySwCode]);

  // ── Render Summary Tab ───────────────────────────────────────────────────────
  function renderSummary() {
    if (loading && incomeData.length === 0) return <StateView state="loading" />;
    if (incomeData.length === 0) return <StateView state="empty" text="该股票暂无财务数据，请尝试其他代码" />;
    return (
      <div className="fin-summary">
        <div className="fin-summary__cards">
          <MetricCard label="营业收入" value={fmtYuan(latest?.revenue)} sub={latest ? reportLabel(latest.report_date) : ''} />
          <MetricCard label="净利润" value={fmtYuan(latest?.net_profit)} sub={latest ? reportLabel(latest.report_date) : ''} />
          <MetricCard label="毛利率" value={fmtPct(latest?.gross_margin)} color="green" />
          <MetricCard label="净利率" value={fmtPct(latest?.net_margin)} color="green" />
          <MetricCard label="每股收益" value={fmtNum(latest?.basic_eps)} sub="元" />
          <MetricCard label="报告期数" value={String(incomeData.length)} sub="期历史" />
        </div>

        {/* 方案 A：估值与市场表现卡片 */}
        <div className="fin-valuation-card">
          <div className="fin-valuation-card__header">
            <h3 className="fin-valuation-card__title">估值与市场表现</h3>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <span style={{ color: 'var(--color-text-secondary)', fontSize: 13 }}>行业：</span>
              <select
                className="fin-industry-select"
                value={industrySwCode || ''}
                onChange={(e) => setIndustrySwCode(e.target.value || null)}
              >
                <option value="">（未选择）</option>
                {industryList.map((it) => (
                  <option key={it.sw_code} value={it.sw_code}>
                    {it.industry}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <FinancialOverlayChart
            title="估值与市场表现（双轴）"
            data={trendData}
            metrics={SUMMARY_VALUATION_METRICS}
            chartType="line"
            selectedKeys={chartSelections['summary-valuation'] || ['stock_price', 'industry_index']}
            onToggleMetric={(k) => toggleChartMetric('summary-valuation', k)}
            overlayData={overlayData}
            industrySnapshot={industrySnap}
            overlaySelection={summaryOverlaySelection}
            onToggleOverlay={toggleOverlay}
          />
        </div>

        <div className="fin-summary__charts">
          {/* 方案 B：营收与净利润趋势（带叠加层） */}
          <FinancialOverlayChart
            title={`营收与净利润趋势（${incomeData.length} 期）`}
            data={trendData}
            metrics={SUMMARY_REV_METRICS}
            chartType="bar"
            selectedKeys={chartSelections['summary-rev'] || ['revenue', 'netProfit']}
            onToggleMetric={(k) => toggleChartMetric('summary-rev', k)}
            overlayData={overlayData}
            industrySnapshot={industrySnap}
            overlaySelection={overlaySelection}
            onToggleOverlay={toggleOverlay}
          />

          <FinancialOverlayChart
            title="利润率趋势（%）"
            data={trendData}
            metrics={SUMMARY_MARGIN_METRICS}
            chartType="line"
            selectedKeys={chartSelections['summary-margin'] || ['grossMargin', 'netMargin']}
            onToggleMetric={(k) => toggleChartMetric('summary-margin', k)}
            overlayData={overlayData}
            industrySnapshot={industrySnap}
            overlaySelection={overlaySelection}
            onToggleOverlay={toggleOverlay}
          />
        </div>

        <div className="fin-summary__link">
          <a href="/macro" className="fin-macro-link">查看宏观经济政策与指标 →</a>
        </div>
      </div>
    );
  }

  // ── Render Income Statement Tab ───────────────────────────────────────────────
  function renderStatementTable(data: StatementRow[], title: string, metrics: [string, (r: StatementRow) => number | null][]) {
    if (loading && data.length === 0) return <StateView state="loading" />;
    if (data.length === 0) return <StateView state="empty" text="暂无数据" />;
    // 日期范围已筛过，这里只做显示折叠：超过 12 列时默认折叠为最近 12 期
    const MAX_DEFAULT = 12;
    const needFold = data.length > MAX_DEFAULT;
    const displayData = needFold && !showAllPeriods ? data.slice(0, MAX_DEFAULT) : data;
    const headers = ['指标', ...displayData.map(r => reportLabel(r.report_date))];
    const rows = metrics.map(([label, getter]) => [label, ...displayData.map(r => fmtYuan(getter(r)))]);
    return (
      <div>
        <div className="fin-tab__info">
          {title} · 共 {data.length} 期 · 最新 {data[0] ? reportLabel(data[0].report_date) : '—'}
          {needFold && (
            <button className="fin-periods-toggle" onClick={() => setShowAllPeriods(!showAllPeriods)}>
              {showAllPeriods ? `收起（显示最近${MAX_DEFAULT}期）` : `展开全部 ${data.length} 期 →`}
            </button>
          )}
        </div>
        <FinTable headers={headers} rows={rows} />
      </div>
    );
  }

  // SelectableChart / MetricDef / *_METRICS 已提升到模块作用域（见文件顶部），
  // 避免随父组件每次渲染重新创建组件身份导致图表全量重挂载。

  const INCOME_TREND_FULL = useMemo(() => {
    return incomeData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      reportDate: r.report_date?.slice(0, 10) || '',
      revenue: r.revenue ? r.revenue / 1e8 : null,
      netProfit: r.net_profit ? r.net_profit / 1e8 : null,
      operatingCost: r.operating_cost ? r.operating_cost / 1e8 : null,
      grossProfit: r.gross_profit ? r.gross_profit / 1e8 : null,
      sellExpense: r.sell_expense ? r.sell_expense / 1e8 : null,
      adminExpense: r.admin_expense ? r.admin_expense / 1e8 : null,
      rdExpense: r.rd_expense ? r.rd_expense / 1e8 : null,
      operatingProfit: r.operating_profit ? r.operating_profit / 1e8 : null,
      grossMargin: r.gross_margin,
      netMargin: r.net_margin,
    }));
  }, [incomeData]);

  const BALANCE_TREND_FULL = useMemo(() => {
    return balanceData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      reportDate: r.report_date?.slice(0, 10) || '',
      totalAssets: r.total_assets ? r.total_assets / 1e8 : null,
      totalLiab: r.total_liabilities ? r.total_liabilities / 1e8 : null,
      equity: r.equity ? r.equity / 1e8 : null,
      monetaryFunds: r.monetary_funds ? r.monetary_funds / 1e8 : null,
      inventory: r.inventory ? r.inventory / 1e8 : null,
      fixedAssets: r.fixed_assets ? r.fixed_assets / 1e8 : null,
      accountsRec: r.accounts_receivable ? r.accounts_receivable / 1e8 : null,
      debtRatio: r.debt_ratio,
    }));
  }, [balanceData]);

  const CASHFLOW_TREND_FULL = useMemo(() => {
    return cashflowData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      reportDate: r.report_date?.slice(0, 10) || '',
      ocf: r.ocf ? r.ocf / 1e8 : null,
      icf: r.icf ? r.icf / 1e8 : null,
      fcf: r.fcf ? r.fcf / 1e8 : null,
      cashEnd: r.cash_end ? r.cash_end / 1e8 : null,
    }));
  }, [cashflowData]);

  function renderIncome() {
    return (
      <div>
        <div className="fin-statement-charts">
          <FinancialOverlayChart title="利润表指标趋势（柱状）" data={INCOME_TREND_FULL} metrics={INCOME_METRICS} chartType="bar" selectedKeys={sel('income-bar', INCOME_METRICS)} onToggleMetric={(k) => toggleChartMetric('income-bar', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          <FinancialOverlayChart title="利润表指标趋势（折线）" data={INCOME_TREND_FULL} metrics={INCOME_METRICS} chartType="line" selectedKeys={sel('income-line', INCOME_METRICS)} onToggleMetric={(k) => toggleChartMetric('income-line', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          {/* 饼图：最新期费用构成 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">费用构成（最新期）</h3>
            {incomePie.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie data={incomePie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={({ name, percent }) => `${name} ${(percent! * 100).toFixed(0)}%`}>
                    {incomePie.map((_, i) => (
                      <Cell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip {...tooltipProps} formatter={(v: number) => fmtYuan(v * 1e8)} />
                </PieChart>
              </ResponsiveContainer>
            ) : <StateView state="empty" text="暂无数据" />}
          </div>
        </div>
        {renderStatementTable(incomeData, '利润表', [
          ['营业总收入', r => r.revenue],
          ['营业成本', r => r.operating_cost],
          ['毛利润', r => r.gross_profit],
          ['销售费用', r => r.sell_expense],
          ['管理费用', r => r.admin_expense],
          ['研发费用', r => r.rd_expense],
          ['财务费用', r => r.fin_expense],
          ['营业利润', r => r.operating_profit],
          ['净利润', r => r.net_profit],
          ['归母净利润', r => r.net_profit_parent],
          ['扣非净利润', r => r.net_profit_deduct],
          ['基本每股收益(元)', r => r.basic_eps],
          ['毛利率(%)', r => r.gross_margin],
          ['净利率(%)', r => r.net_margin],
        ])}
      </div>
    );
  }

  function renderBalance() {
    return (
      <div>
        <div className="fin-statement-charts">
          <FinancialOverlayChart title="资产负债表指标趋势（柱状）" data={BALANCE_TREND_FULL} metrics={BALANCE_METRICS} chartType="bar" selectedKeys={sel('balance-bar', BALANCE_METRICS)} onToggleMetric={(k) => toggleChartMetric('balance-bar', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          <FinancialOverlayChart title="资产负债表指标趋势（折线）" data={BALANCE_TREND_FULL} metrics={BALANCE_METRICS} chartType="line" selectedKeys={sel('balance-line', BALANCE_METRICS)} onToggleMetric={(k) => toggleChartMetric('balance-line', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          {/* 饼图：最新期资产构成 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">资产构成（最新期）</h3>
            {balancePie.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie data={balancePie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={({ name, percent }) => `${name} ${(percent! * 100).toFixed(0)}%`}>
                    {balancePie.map((_, i) => (
                      <Cell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip {...tooltipProps} formatter={(v: number) => fmtYuan(v * 1e8)} />
                </PieChart>
              </ResponsiveContainer>
            ) : <StateView state="empty" text="暂无数据" />}
          </div>
        </div>
        {renderStatementTable(balanceData, '资产负债表', [
          ['货币资金', r => r.monetary_funds],
          ['应收账款', r => r.accounts_receivable],
          ['存货', r => r.inventory],
          ['固定资产合计', r => r.fixed_assets],
          ['商誉', r => r.goodwill],
          ['短期借款', r => r.short_loan],
          ['长期借款', r => r.long_loan],
          ['资产合计', r => r.total_assets],
          ['负债合计', r => r.total_liabilities],
          ['所有者权益', r => r.equity],
          ['归母权益', r => r.equity_parent],
          ['资产负债率(%)', r => r.debt_ratio],
        ])}
      </div>
    );
  }

  function renderCashflow() {
    return (
      <div>
        <div className="fin-statement-charts">
          <FinancialOverlayChart title="现金流量表指标趋势（柱状）" data={CASHFLOW_TREND_FULL} metrics={CASHFLOW_METRICS} chartType="bar" selectedKeys={sel('cashflow-bar', CASHFLOW_METRICS)} onToggleMetric={(k) => toggleChartMetric('cashflow-bar', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          <FinancialOverlayChart title="现金流量表指标趋势（折线）" data={CASHFLOW_TREND_FULL} metrics={CASHFLOW_METRICS} chartType="line" selectedKeys={sel('cashflow-line', CASHFLOW_METRICS)} onToggleMetric={(k) => toggleChartMetric('cashflow-line', k)} overlayData={overlayData} industrySnapshot={industrySnap} overlaySelection={overlaySelection} onToggleOverlay={toggleOverlay} />
          {/* 饼图：最新期现金构成 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">现金构成（最新期）</h3>
            {cashflowPie.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie data={cashflowPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={({ name, percent }) => `${name} ${(percent! * 100).toFixed(0)}%`}>
                    {cashflowPie.map((_, i) => (
                      <Cell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip {...tooltipProps} formatter={(v: number) => fmtYuan(v * 1e8)} />
                </PieChart>
              </ResponsiveContainer>
            ) : <StateView state="empty" text="暂无数据" />}
          </div>
        </div>
        {renderStatementTable(cashflowData, '现金流量表', [
          ['经营活动现金流净额', r => r.ocf],
          ['投资活动现金流净额', r => r.icf],
          ['筹资活动现金流净额', r => r.fcf],
          ['期末现金余额', r => r.cash_end],
        ])}
      </div>
    );
  }

  // ── Render Forecast Tab ──────────────────────────────────────────────────────
  function renderForecast() {
    if (forecastData.length === 0) return <StateView state="loading" />;
    const headers = ['股票', '公司', '预测指标', '预测数值', '变动幅度', '预告类型', '公告日期'];
    const rows: (string | number | null | React.ReactNode)[][] = forecastData.map(f => [
      f.symbol,
      f.company_name || '—',
      f.metric || '—',
      fmtYuan(f.forecast_value),
      <span className={`num ${f.change_pct != null && f.change_pct >= 0 ? 'fin-positive' : 'fin-negative'}`}>
        {f.change_pct != null ? (f.change_pct > 0 ? '+' : '') + f.change_pct.toFixed(2) + '%' : '—'}
      </span>,
      <span className={`fin-badge ${f.forecast_type_label?.includes('增') || f.forecast_type_label?.includes('盈') ? 'fin-badge--green' : 'fin-badge--red'}`}>
        {f.forecast_type_label || '—'}
      </span>,
      f.announce_date || '—',
    ]);
    return (
      <div>
        <div className="fin-tab__info">
          业绩预告 · 报告期 {forecastDate || '—'} · 共 {forecastData.length} 条
          <Button size="sm" onClick={fetchForecast}>刷新</Button>
        </div>
        <FinTable headers={headers} rows={rows} />
      </div>
    );
  }

  // ── Render Compare Tab ───────────────────────────────────────────────────────
  function renderCompare() {
    return (
      <div>
        <div className="fin-compare__input-row">
          <input
            className="fin-compare__input"
            value={compareInput}
            onChange={e => setCompareInput(e.target.value)}
            placeholder="输入股票代码，逗号分隔（如 sh600519,sh600036）"
          />
          <Button variant="primary" size="sm" onClick={() => fetchCompare(compareInput)}>对比</Button>
        </div>
        <div className="fin-chart-card">
          <h3 className="fin-chart-card__title">盈利能力对比（最新一期）</h3>
          {compareData.length > 1 && compareData.some(c => c.latest) ? (
            <ResponsiveContainer width="100%" height={320}>
              <RadarChart data={radarData}>
                <PolarGrid stroke={chartBorder} />
                <PolarAngleAxis dataKey="metric" tick={{ fill: chartTextSecondary, fontSize: 11 }} />
                <PolarRadiusAxis tick={{ fill: chartTextSecondary, fontSize: 10 }} />
                {compareData.map((c, i) => (
                  <Radar
                    key={c.symbol}
                    name={c.symbol}
                    dataKey={c.symbol}
                    stroke={[CHART_COLORS[1], CHART_COLORS[0], colorOrange, CHART_COLORS[5]][i % 4]}
                    fill={[CHART_COLORS[1], CHART_COLORS[0], colorOrange, CHART_COLORS[5]][i % 4]}
                    fillOpacity={0.15}
                  />
                ))}
                <Legend wrapperStyle={{ color: 'var(--color-text-secondary)' }} />
                <Tooltip {...tooltipProps} />
              </RadarChart>
            </ResponsiveContainer>
          ) : <StateView state="empty" text="请输入至少 2 个股票代码" />}
        </div>

        {compareData.some(c => c.latest) && (
          <FinTable
            headers={['指标', ...compareData.map(c => c.symbol)]}
            rows={[
              ['营业收入', ...compareData.map(c => fmtYuan(c.latest?.revenue))],
              ['净利润', ...compareData.map(c => fmtYuan(c.latest?.net_profit))],
              ['毛利率(%)', ...compareData.map(c => fmtPct(c.latest?.gross_margin))],
              ['净利率(%)', ...compareData.map(c => fmtPct(c.latest?.net_margin))],
              ['总资产', ...compareData.map(c => fmtYuan(c.latest?.total_assets))],
              ['负债率(%)', ...compareData.map(c => fmtPct(c.latest?.debt_ratio))],
              ['每股收益', ...compareData.map(c => fmtNum(c.latest?.basic_eps))],
            ]}
          />
        )}
      </div>
    );
  }

  // renderValuation 已迁移至 ValuationHub（五法估值：总览 + DCF/DDM/净资产/类比/乘数历史）

  // ── Render ───────────────────────────────────────────────────────────────────
  const tabs: { key: TabType; label: string }[] = [
    { key: 'summary', label: '摘要' },
    { key: 'balance', label: '资产负债表' },
    { key: 'income', label: '利润表' },
    { key: 'cashflow', label: '现金流量表' },
    { key: 'commonsize', label: '同型分析' },
    { key: 'ratios', label: '比率分析' },
    { key: 'fiveforces', label: '五力分析' },
    { key: 'cashflowanalysis', label: '现金流分析' },
    { key: 'forecast', label: '业绩预告' },
    { key: 'compare', label: '对比' },
    { key: 'valuation', label: '估值' },
    { key: 'marketcapgrowth', label: '市值业绩' },
    { key: 'fundamental', label: 'AI基本面' },
  ];

  return (
    <div className="fin-page">
      <PageHeader
        title="财务分析"
        actions={
          <div className="fin-header__search">
            <StockSearch value={symbol} onSelect={setSymbol} />
          </div>
        }
      />

      {/* 股票基本信息栏 */}
      <div className="fin-profile">
        <div className="fin-profile__main">
          <span className="fin-profile__symbol">{symbol}</span>
          {profile?.name && <span className="fin-profile__name">{profile.name}</span>}
          {profile?.market && <span className="fin-profile__badge">{profile.market}股</span>}
          {profile?.industry && <span className="fin-profile__badge">{profile.industry}</span>}
        </div>
        <div className="fin-profile__stats">
          {profile?.total_mv != null && (
            <div className="fin-profile__stat">
              <span className="fin-profile__stat-label">总市值</span>
              <span className="num fin-profile__stat-value">{fmtYuan(profile.total_mv)}</span>
            </div>
          )}
          {profile?.pe_ttm != null && (
            <div className="fin-profile__stat">
              <span className="fin-profile__stat-label">PE(TTM)</span>
              <span className="num fin-profile__stat-value">{fmtNum(profile.pe_ttm)}</span>
            </div>
          )}
          {profile?.pb != null && (
            <div className="fin-profile__stat">
              <span className="fin-profile__stat-label">PB</span>
              <span className="num fin-profile__stat-value">{fmtNum(profile.pb)}</span>
            </div>
          )}
          {profile?.report_periods != null && (
            <div className="fin-profile__stat">
              <span className="fin-profile__stat-label">财报期数</span>
              <span className="fin-profile__stat-value">{profile.report_periods}</span>
            </div>
          )}
          {profile?.latest_report && (
            <div className="fin-profile__stat">
              <span className="fin-profile__stat-label">最新报告期</span>
              <span className="fin-profile__stat-value">{profile.latest_report}</span>
            </div>
          )}
          {profile?.list_date && (
            <div className="fin-profile__stat">
              <span className="fin-profile__stat-label">上市日期</span>
              <span className="fin-profile__stat-value">{profile.list_date}</span>
            </div>
          )}
        </div>
        {profile?.business_scope && (
          <div className="fin-profile__business">
            <span className="fin-profile__business-label">经营范围：</span>
            <span className="fin-profile__business-text">{profile.business_scope}</span>
          </div>
        )}
        {/* 快捷股票 */}
        <div className="fin-header__popular">
          {POPULAR_SYMBOLS.map(s => (
            <button key={s} className={`fin-chip ${symbol === s ? 'fin-chip--active' : ''}`} onClick={() => setSymbol(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="fin-error">{error}</div>}

      <div className="fin-tabs">
        <Tabs
          active={activeTab}
          onChange={(k) => setActiveTab(k as TabType)}
          tabs={tabs.map(t => ({key: t.key, label: t.label}))}
        />
        {/* 时间范围选择器（业绩预告/对比 Tab 不需要，隐藏）*/}
        {activeTab !== 'forecast' && activeTab !== 'compare' && activeTab !== 'valuation' && (
          <div className="fin-daterange">
            {/* 快捷范围 */}
            <div className="fin-daterange__quick">
              {[
                { label: '近1年', y: 1 },
                { label: '近3年', y: 3 },
                { label: '近5年', y: 5 },
                { label: '近10年', y: 10 },
              ].map(q => {
                const y = new Date();
                y.setFullYear(y.getFullYear() - q.y);
                const qs = y.toISOString().slice(0, 10);
                const active = startDate === qs && !endDate;
                return (
                  <button
                    key={q.y}
                    className={`fin-chip ${active ? 'fin-chip--active' : ''}`}
                    onClick={() => { setStartDate(qs); setEndDate(''); setShowAllPeriods(false); }}
                  >
                    {q.label}
                  </button>
                );
              })}
              <button
                className={`fin-chip ${!startDate && !endDate ? 'fin-chip--active' : ''}`}
                onClick={() => { setStartDate(''); setEndDate(''); setShowAllPeriods(false); }}
              >
                全部
              </button>
            </div>
            {/* 周期切换器（月/季/年，月按钮按需隐藏）*/}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 12 }}>
              <span style={{ color: 'var(--color-text-secondary)', fontSize: 13 }}>周期：</span>
              <PeriodSwitcher value={period} onChange={setPeriod} hasMonthly={hasMonthly} />
            </div>
            {/* 自定义日期 */}
            <div className="fin-daterange__custom">
              <input
                type="date"
                className="fin-date-input"
                value={startDate}
                onChange={e => setStartDate(e.target.value)}
                title="起始报告期"
              />
              <span className="fin-daterange__sep">~</span>
              <input
                type="date"
                className="fin-date-input"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                title="截止报告期"
              />
            </div>
          </div>
        )}
      </div>

      <div className="fin-content">
        {activeTab === 'summary' && renderSummary()}
        {activeTab === 'income' && renderIncome()}
        {activeTab === 'balance' && renderBalance()}
        {activeTab === 'cashflow' && renderCashflow()}
        {activeTab === 'commonsize' && <CommonSizePanel symbol={symbol} />}
        {activeTab === 'ratios' && <RatiosPanel symbol={symbol} />}
        {activeTab === 'fiveforces' && <FiveForcesPanel symbol={symbol} />}
        {activeTab === 'cashflowanalysis' && (
          <CashflowAnalysisPanel symbol={symbol} />
        )}
        {activeTab === 'forecast' && renderForecast()}
        {activeTab === 'compare' && renderCompare()}
        {activeTab === 'valuation' && <ValuationHub symbol={symbol} />}
        {activeTab === 'marketcapgrowth' && <MarketCapGrowthPanel symbol={symbol} />}
        {activeTab === 'fundamental' && <FundamentalReportPanel symbol={symbol} />}
      </div>
    </div>
  );
};
