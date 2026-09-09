/**
 * NationalTeam page — 国家队动向监控
 *
 * 两个 Tab:
 *   1. 每日动向  — 盘后宽基 ETF 放量+抗跌信号(今天可见)
 *   2. 历年持仓  — 2015 至今季报前十大流通股东快照 + 4 视图对比
 *
 * 口径说明:每日动向是"行为信号",历年持仓是"权威快照(季度颗粒度)"。
 */
import React, {useState, useEffect, useMemo} from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ComposedChart, Area, BarChart, Bar,
} from 'recharts';
import {getApiBase} from '../lib/api';
import {NationalTeamLive, NationalTeamEtf} from './ntLive/LiveTabs';
import {Button, Modal, PageHeader, StateView, Tabs} from '../components/ui';
import './NationalTeam.css';
import { CHART_COLORS, axisProps, chartTextSecondary, colorOrange, gridProps, tooltipProps } from '../lib/chartTheme';

const API_BASE = getApiBase();

const CATEGORY_COLORS: Record<string, string> = {
  huijin: CHART_COLORS[0],
  zhengjin: CHART_COLORS[5],
  safe: CHART_COLORS[1],
  social_security: colorOrange,
};
const CATEGORY_LABEL: Record<string, string> = {
  huijin: '汇金', zhengjin: '证金', safe: '外管局', social_security: '社保',
};

const fmtYi = (v: number) => Number((v / 1e8).toFixed(1));  // 元 → 亿(number,供 recharts)

interface EtfSignal {
  etf_code: string;
  etf_name: string;
  as_of_date: string;
  vol_ratio: number;
  etf_chg_pct: number;
  index_chg_pct: number;
  defend_flag: boolean;
  strength: 'strong' | 'suspect' | 'none' | 'error';
}
interface Heatmap20d {
  dates: string[];
  cells: Record<string, Record<string, string>>;  // etf_code -> {date: strength}
}
interface DailyData {
  as_of: string;
  summary: {strong: number; suspect: number; none: number; error: number};
  signals: EtfSignal[];
  heatmap_20d: Heatmap20d;
}

type TabKey = 'daily' | 'holdings' | 'panorama' | 'etf';

const strengthLabel: Record<string, string> = {
  strong: '强护盘', suspect: '疑似护盘', none: '无明显信号', error: '数据异常',
};
const strengthClass = (s: string) =>
  s === 'strong' ? 'signal-strong' : s === 'suspect' ? 'signal-suspect' : 'signal-none';

const Heatmap20dView: React.FC<{signals: EtfSignal[]; heatmap: Heatmap20d | undefined}> = ({signals, heatmap}) => {
  const dates = heatmap?.dates || [];
  const cells = heatmap?.cells || {};
  if (dates.length === 0 || signals.length === 0) return null;
  // 按当日 vol_ratio 降序排列行,与表格口径一致
  const rows = [...signals].sort((a, b) => b.vol_ratio - a.vol_ratio);
  const shortDate = (d: string) => d ? d.slice(5) : '';  // MM-DD
  const cellClass = (strength?: string) => {
    if (strength === 'strong') return 'nt-heat-cell nt-heat-cell--strong';
    if (strength === 'suspect') return 'nt-heat-cell nt-heat-cell--suspect';
    return 'nt-heat-cell nt-heat-cell--none';
  };
  return (
    <div className="nt-heatmap-wrap">
      <div className="nt-chart-title">近 20 日护盘强度热力(红=强,橙=疑似,灰=无)</div>
      <div className="nt-heatmap-scroll">
        <table className="nt-heatmap">
          <thead>
            <tr>
              <th className="nt-heatmap-rowhead">ETF</th>
              {dates.map(d => <th key={d} title={d}>{shortDate(d)}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(s => (
              <tr key={s.etf_code}>
                <td className="nt-heatmap-rowhead" title={s.etf_name}>{s.etf_code}</td>
                {dates.map(d => (
                  <td key={d}>
                    <div className={cellClass(cells[s.etf_code]?.[d])} title={`${s.etf_code} ${d}: ${cells[s.etf_code]?.[d] || '无'}`} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="nt-heatmap-legend">
        <span className="nt-heat-cell nt-heat-cell--strong" /> 强护盘
        <span className="nt-heat-cell nt-heat-cell--suspect" /> 疑似护盘
        <span className="nt-heat-cell nt-heat-cell--none" /> 无明显信号
      </div>
    </div>
  );
};

const DAY_PRESETS: {label: string; days: number}[] = [
  {label: '20天', days: 20},
  {label: '60天', days: 60},
  {label: '120天', days: 120},
  {label: '全部', days: 250},
];

const DailyTab: React.FC = () => {
  const [data, setData] = useState<DailyData | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 时间范围:days 为后端窗口大小(交易日近似),customStart 非空表示用自定义起算日
  const [days, setDays] = useState(20);
  const [customStart, setCustomStart] = useState('');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API_BASE}/national-team/daily-signals?days=${days}`)
      .then(r => r.json())
      .then(j => { if (alive) setData(j.data || null); })
      .catch(() => { if (alive) setErr('加载失败'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [days]);

  // 选了自定义起始日 → 用日历天数近似换算成 days 窗口
  const onCustomStart = (val: string) => {
    setCustomStart(val);
    if (!val) return;
    const diff = Math.ceil((Date.now() - new Date(val).getTime()) / 86400000);
    setDays(diff < 1 ? 1 : diff);
  };

  if (loading && !data) return <StateView state="loading" />;
  if (err) return <StateView state="error" text={err} />;
  if (!data) return <StateView state="empty" />;

  const sorted = [...data.signals].sort((a, b) => b.vol_ratio - a.vol_ratio);
  const usingCustom = customStart !== '';

  return (
    <div className="nt-daily">
      <div className="nt-rangebar">
        <span className="nt-rangebar-label">时间范围:</span>
        {DAY_PRESETS.map(p => (
          <button
            key={p.label}
            className={`nt-range-btn ${!usingCustom && days === p.days ? 'nt-range-btn--active' : ''}`}
            onClick={() => { setCustomStart(''); setDays(p.days); }}
          >
            {p.label}
          </button>
        ))}
        <span className="nt-rangebar-label">自定义起:</span>
        <input
          type="date"
          className={`nt-date-input ${usingCustom ? 'nt-date-input--active' : ''}`}
          value={customStart}
          max={new Date().toISOString().slice(0, 10)}
          onChange={e => onCustomStart(e.target.value)}
        />
      </div>
      <div className="nt-summary">
        <div className="nt-stat signal-strong">强护盘 {data.summary.strong}</div>
        <div className="nt-stat signal-suspect">疑似护盘 {data.summary.suspect}</div>
        <div className="nt-stat signal-none">无明显信号 {data.summary.none}</div>
        <div className="nt-stat nt-asof">数据时点 {data.as_of || '-'}</div>
      </div>
      <Heatmap20dView signals={data.signals} heatmap={data.heatmap_20d} />
      <div className="nt-table-wrap">
        <table className="nt-table">
          <thead>
            <tr>
              <th>ETF代码</th><th>名称</th><th>放量倍数</th>
              <th>ETF涨跌%</th><th>指数涨跌%</th><th>抗跌</th><th>信号强度</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(s => (
              <tr key={s.etf_code}>
                <td>{s.etf_code}</td>
                <td>{s.etf_name}</td>
                <td>{s.vol_ratio.toFixed(1)}x</td>
                <td className={s.etf_chg_pct >= 0 ? 'num is-up' : 'num is-down'}>
                  {s.etf_chg_pct >= 0 ? '+' : ''}{s.etf_chg_pct.toFixed(2)}
                </td>
                <td className={s.index_chg_pct >= 0 ? 'num is-up' : 'num is-down'}>
                  {s.index_chg_pct >= 0 ? '+' : ''}{s.index_chg_pct.toFixed(2)}
                </td>
                <td>{s.defend_flag ? '是' : ''}</td>
                <td><span className={`nt-strength ${strengthClass(s.strength)}`}>
                  {strengthLabel[s.strength] || s.strength}
                </span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const CATEGORY_KEYS = ['huijin', 'zhengjin', 'safe', 'social_security'] as const;

const SymbolSearch: React.FC<{onPick: (symbol: string, name: string) => void}> = ({onPick}) => {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<{symbol:string; company_name:string; latest_value:number}[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  // 防抖搜索(输入停 250ms 后查)
  useEffect(() => {
    const query = q.trim();
    if (!query) { setResults([]); return; }
    setLoading(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      fetch(`${API_BASE}/national-team/holdings/search?q=${encodeURIComponent(query)}&limit=10`)
        .then(r => r.json())
        .then(j => { setResults(j.data?.rows || []); setOpen(true); })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 250);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [q]);

  const pick = (r: {symbol:string; company_name:string}) => {
    onPick(r.symbol, r.company_name);
    setQ(''); setResults([]); setOpen(false);
  };

  return (
    <div className="nt-search">
      <input
        className="nt-search-input"
        placeholder="搜索个股(代码/名称,如 601398 或 茅台)"
        value={q}
        onChange={e => setQ(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}  // 延迟关闭让点击生效
      />
      {open && results.length > 0 && (
        <div className="nt-search-dropdown">
          {results.map(r => (
            <div key={r.symbol} className="nt-search-item" onMouseDown={()=>pick(r)}>
              <span className="nt-search-name">{r.company_name}</span>
              <span className="nt-search-code">{r.symbol}</span>
              <span className="nt-search-val">{r.latest_value ? (r.latest_value/1e8).toFixed(0)+'亿' : ''}</span>
            </div>
          ))}
        </div>
      )}
      {open && !loading && q.trim() && results.length === 0 && (
        <div className="nt-search-dropdown"><div className="nt-search-empty">无匹配个股</div></div>
      )}
    </div>
  );
};

// ── 行业资金流向 ──
// 接口:/holdings/sector-flow,返回 {quarters, sectors, series}。
// series 每项:{report_date, sector, shares(股), value(元)}。
// 单次拉取 → useMemo 透视成 byDateSector,4 个模块共用,切换两期对比不重新请求。
interface SectorFlowPoint { shares: number; value: number; }
interface SectorFlowResp {
  quarters: string[];
  sectors: string[];
  series: { report_date: string; sector: string; shares: number; value: number }[];
}

const FLOW_PALETTE = [CHART_COLORS[5], CHART_COLORS[0], CHART_COLORS[1], colorOrange, '#a06bd9', '#3aa6b9', '#d94f8e', '#8b9e3a'];

// 颜色:deltaPct 落在 [-50,50] 内按绝对值映射成不透明度;>0 红(增持),<0 绿(减持),~0 灰。
const heatColor = (delta: number | null): string => {
  if (delta === null) return 'rgba(255,255,255,0.10)';  // NEW
  if (!isFinite(delta)) return 'rgba(255,255,255,0.10)';
  const mag = Math.min(Math.abs(delta), 50) / 50;  // 0..1
  if (mag < 0.02) return 'rgba(255,255,255,0.06)';  // ~0
  return delta > 0
    ? `rgba(229,77,77,${(0.15 + mag * 0.75).toFixed(3)})`  // 红
    : `rgba(46,184,114,${(0.15 + mag * 0.75).toFixed(3)})`; // 绿
};

const fmtYiGu = (shares: number) => (shares / 1e8).toFixed(1);   // 股 → 亿股(字符串)

// 行业→个股下钻弹窗:列出某行业在某报告期被国家队持有的个股。
// 点击个股行 → 由父组件打开既有的 SymbolDrill(单只个股历史曲线)。
// 使用统一 Modal 组件(点遮罩/关闭按钮关)。
const SectorStocksModal: React.FC<{
  sector: string;
  period: string | null;        // null/空 → 后端取最新
  onClose: () => void;
  onPickStock: (symbol: string, name: string) => void;
}> = ({sector, period, onClose, onPickStock}) => {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // hooks 必须无条件先跑完,再做任何条件渲染(loading/err/empty 全部在 JSX 里处理,无 early return)。
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setErr(null);
    const url = `${API_BASE}/national-team/holdings/sector-stocks?sector=${encodeURIComponent(sector)}&period=${period || ''}`;
    fetch(url)
      .then(r => r.json())
      .then(j => { if (alive) setRows(j.data?.rows || []); })
      .catch(() => { if (alive) setErr('加载失败'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [sector, period]);

  return (
    <Modal
      open
      title={`${sector} · 国家队持仓个股 (报告期 ${period || '最新'})`}
      onClose={onClose}
      width={560}
      footer={<Button size="sm" onClick={onClose}>关闭</Button>}
    >
      {loading ? <StateView state="loading" /> :
       err ? <StateView state="error" text={err} /> :
       rows.length === 0 ? <StateView state="empty" text="该行业暂无国家队持仓个股" /> :
       <>
         <div className="nt-top-head">共 <b>{rows.length}</b> 只个股</div>
         <table className="nt-table">
           <thead>
             <tr>
               <th>#</th>
               <th>股票</th>
               <th>持股市值(亿)</th>
               <th>持股数(亿股)</th>
               <th>环比变动</th>
               <th>国家队成员</th>
             </tr>
           </thead>
           <tbody>
             {rows.map((r, i) => {
               const delta = r.delta_shares != null ? r.delta_shares : null;
               const deltaYi = delta != null ? delta / 1e8 : null;  // 股 → 亿股
               return (
                 <tr key={r.symbol} className="nt-clickable" onClick={() => onPickStock(r.symbol, r.company_name)}>
                   <td>{i + 1}</td>
                   <td>{r.company_name}({r.symbol})</td>
                   <td className="num is-up">{fmtYi(r.total_value)}</td>
                   <td>{fmtYiGu(r.total_shares)}</td>
                   <td>
                     {r.is_new ? <span className="nt-tag nt-tag--new">新进</span> :
                      deltaYi == null ? '-' :
                      deltaYi >= 0
                        ? <span className="num is-up">+{deltaYi.toFixed(2)}亿股{r.delta_pct != null ? ` (+${r.delta_pct}%)` : ''}</span>
                        : <span className="num is-down">{deltaYi.toFixed(2)}亿股{r.delta_pct != null ? ` (${r.delta_pct}%)` : ''}</span>}
                   </td>
                   <td>{(r.holders || []).map((h: any) => CATEGORY_LABEL[h.holder_category] || h.holder_category).join('、')}</td>
                 </tr>
               );
             })}
           </tbody>
         </table>
       </>}
    </Modal>
  );
};

const SectorFlowView: React.FC = () => {
  const [resp, setResp] = useState<SectorFlowResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 行业→个股下钻(必须在 early return 之前声明,保证 hooks 顺序稳定):
  //   sectorDrill → 打开 SectorStocksModal;点其中个股 → 切到 stockDrill → 打开 SymbolDrill。
  const [sectorDrill, setSectorDrill] = useState<{sector: string; period: string | null} | null>(null);
  const [stockDrill, setStockDrill] = useState<{symbol: string; name: string} | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API_BASE}/national-team/holdings/sector-flow`)
      .then(r => r.json())
      .then(j => { if (alive) setResp(j.data || null); })
      .catch(() => { if (alive) setErr('加载失败'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  // ── 单次透视:byDateSector + 每期总量 + 占比 + 环比 delta ──
  const derived = useMemo(() => {
    if (!resp) return null;
    const {quarters, series} = resp;

    // byDateSector[date][sector] = {shares, value}
    const byDateSector: Record<string, Record<string, SectorFlowPoint>> = {};
    for (const s of series) {
      const d = byDateSector[s.report_date] || {};
      d[s.sector] = {shares: s.shares, value: s.value};
      byDateSector[s.report_date] = d;
    }
    // 每期总 shares
    const totalByDate: Record<string, number> = {};
    for (const q of quarters) {
      const sec = byDateSector[q] || {};
      totalByDate[q] = Object.values(sec).reduce((a, b) => a + b.shares, 0);
    }
    // 全部出现过的行业(用 resp.sectors,保持稳定顺序)
    const allSectors = resp.sectors;
    // 行业按最新季度 shares 降序(大行业在上)
    const lastQ = quarters[quarters.length - 1];
    const lastMap = byDateSector[lastQ] || {};
    const sectorsSorted = [...allSectors].sort((a, b) =>
      (lastMap[b]?.shares || 0) - (lastMap[a]?.shares || 0));

    // 环比 deltaPct(按 sector 在 quarters 序列里前后比)
    // deltaOf[sector][date] = number | null
    //   - number: (本期-上一有持仓期)/上一有持仓期 * 100
    //   - null:   真正的"首次新进"(历史上第一次出现持仓);本期无持仓则空格(0 当占位)
    // 关键:与"最近一个有数据的季度"比,而非严格相邻季度;中间退出再回来不算 NEW
    // (只在整个历史第一次出现时才标 NEW),避免数据稀疏导致满屏"新"。
    const deltaOf: Record<string, Record<string, number | null>> = {};
    for (const sec of allSectors) {
      const row: Record<string, number | null> = {};
      let prevShares = 0;       // 最近一次有持仓的股数
      let everHeld = false;     // 历史上是否出现过持仓
      for (const q of quarters) {
        const cur = byDateSector[q]?.[sec]?.shares || 0;
        if (cur > 0) {
          if (!everHeld) {
            row[q] = null;            // 真正的首次新进
          } else if (prevShares > 0) {
            row[q] = (cur - prevShares) / prevShares * 100;
          } else {
            row[q] = null;            // 极少见:历史有但最近无参照,保守标 null
          }
          prevShares = cur;
          everHeld = true;
        } else {
          row[q] = 0;                 // 本期无持仓 → 空格(灰),不推进 prevShares
        }
      }
      deltaOf[sec] = row;
    }

    return {byDateSector, totalByDate, sectorsSorted, deltaOf};
  }, [resp]);

  // 两期对比的状态
  const quarters = resp?.quarters || [];
  const [period, setPeriod] = useState<string>('');
  const [vsPeriod, setVsPeriod] = useState<string>('');
  const [showAll, setShowAll] = useState(false);  // 模块 3 全部/Top5 切换

  // quarters 到位后设默认值(只在首次有值时设)
  useEffect(() => {
    if (quarters.length >= 2 && !period && !vsPeriod) {
      setPeriod(quarters[quarters.length - 1]);
      setVsPeriod(quarters[quarters.length - 2]);
    }
  }, [quarters, period, vsPeriod]);

  // ── 模块 3:占比趋势数据(每期每个行业 pct)──
  // 必须在 early return 之前调用(所有 hooks 不能条件化)。
  const trendData = useMemo(() => {
    if (!derived) return [];
    return quarters.map(q => {
      const total = derived.totalByDate[q] || 0;
      const row: Record<string, number | string> = {report_date: q};
      for (const sec of derived.sectorsSorted) {
        const s = derived.byDateSector[q]?.[sec]?.shares || 0;
        row[sec] = total > 0 ? Number((s / total * 100).toFixed(2)) : 0;
      }
      return row;
    });
  }, [quarters, derived]);

  if (loading && !resp) return <StateView state="loading" />;
  if (err) return <StateView state="error" text={err} />;
  if (!resp || !derived) return <StateView state="empty" />;

  const {byDateSector, sectorsSorted, deltaOf} = derived;
  const lastQ = quarters[quarters.length - 1];

  // ── 模块 2:两期对比行(从透视数据现算,无新请求)──
  const cmpRows = (() => {
    if (!period || !vsPeriod) return [];
    const curMap = byDateSector[period] || {};
    const vsMap = byDateSector[vsPeriod] || {};
    const allSecs = new Set([...Object.keys(curMap), ...Object.keys(vsMap)]);
    const rows = [...allSecs].map(sec => {
      const cur = curMap[sec];
      const vs = vsMap[sec];
      const curShares = cur?.shares || 0;
      const vsShares = vs?.shares || 0;
      const curValue = cur?.value || 0;
      const vsValue = vs?.value || 0;
      const isNew = !vs && !!cur;
      return {
        sector: sec,
        curShares, vsShares,
        changeShares: curShares - vsShares,
        changePct: vsShares > 0 ? (curShares - vsShares) / vsShares * 100 : null,
        flowYi: (curValue - vsValue) / 1e8,
        isNew,
      };
    });
    rows.sort((a, b) => Math.abs(b.changeShares) - Math.abs(a.changeShares));
    return rows;
  })();


  const top5 = derived.sectorsSorted.slice(0, 5);
  const others = derived.sectorsSorted.slice(5);
  // 把"其他"汇总成一条线
  const trendDataMerged = trendData.map(r => {
    if (showAll) return r;
    const o = {report_date: r.report_date as string} as Record<string, number | string>;
    top5.forEach(s => { o[s] = r[s]; });
    let sum = 0;
    others.forEach(s => { sum += (r[s] as number) || 0; });
    o['其他'] = Number(sum.toFixed(2));
    return o;
  });
  const allTrendKeys = showAll ? derived.sectorsSorted : [...top5, '其他'];

  // ── 模块 4:最新季度加/减仓 Top5 ──
  const lastDeltas = derived.sectorsSorted
    .filter(sec => byDateSector[lastQ]?.[sec])  // 仅本期存在
    .map(sec => ({
      sector: sec,
      delta: deltaOf[sec]?.[lastQ],
      shares: byDateSector[lastQ]?.[sec]?.shares || 0,
    }))
    .filter(x => typeof x.delta === 'number');  // 跳过 NEW
  const ups = [...lastDeltas].sort((a, b) => (b.delta as number) - (a.delta as number)).slice(0, 5);
  const downs = [...lastDeltas].sort((a, b) => (a.delta as number) - (b.delta as number)).slice(0, 5);

  return (
    <div className="nt-flow">
      {/* ── 模块 1:行业×季度增减热力图 ── */}
      <div className="nt-chart-box">
        <div className="nt-chart-title">
          行业×季度环比增减热力图(红=增持 / 绿=减持 / 灰=持平原或新增;
          以持股数环比判断,剔除股价波动)
        </div>
        <div className="nt-heatmap-wrap">
          <div
            className="nt-heatmap"
            style={{gridTemplateColumns: `120px repeat(${quarters.length}, 38px)`}}
          >
            {/* 表头:空格 + 各季度(斜排,旋转 -45deg) */}
            <div className="nt-heat-label nt-heat-label--head" />
            {quarters.map(q => (
              <div key={q} className="nt-heat-qhead" title={q}>{q.slice(2, 7)}</div>
            ))}
            {/* 行:行业(已按最新季度降序) */}
            {sectorsSorted.map(sec => (
              <React.Fragment key={sec}>
                <div className="nt-heat-label" title={sec}>{sec}</div>
                {quarters.map(q => {
                  const delta = deltaOf[sec]?.[q];
                  const shares = byDateSector[q]?.[sec]?.shares || 0;
                  const isNew = delta === null && shares > 0;
                  const tip = `${sec} @ ${q}: ${
                    delta === null ? '新增' : (delta >= 0 ? '+' : '') + delta.toFixed(1) + '%'
                  } (持股 ${fmtYiGu(shares)}亿股)`;
                  return (
                    <div
                      key={q}
                      className={`nt-heat-cell ${isNew ? 'nt-heat-cell--new' : ''} ${shares > 0 ? 'nt-clickable' : ''}`}
                      style={{background: heatColor(delta)}}
                      title={tip}
                      onClick={shares > 0 ? () => setSectorDrill({sector: sec, period: q}) : undefined}
                    >
                      {isNew && <span className="nt-heat-new">新</span>}
                    </div>
                  );
                })}
              </React.Fragment>
            ))}
          </div>
        </div>
        <div className="nt-heatmap-legend">
          <span className="nt-heat-cell" style={{background: heatColor(40)}} /> 增持
          <span className="nt-heat-cell" style={{background: heatColor(0)}} /> 持平
          <span className="nt-heat-cell" style={{background: heatColor(-40)}} /> 减持
          <span className="nt-heat-cell nt-heat-cell--new" style={{background: heatColor(null)}}>新</span> 新进
        </div>
      </div>

      {/* ── 模块 2:两期对比·行业资金流向表 ── */}
      <div className="nt-chart-box">
        <div className="nt-chart-title">两期对比·行业资金流向(以持股数为准)</div>
        <div className="nt-filter">
          <span>本期</span>
          <select value={period} onChange={e => setPeriod(e.target.value)}>
            {quarters.map(q => <option key={q} value={q}>{q}</option>)}
          </select>
          <span>对比</span>
          <select value={vsPeriod} onChange={e => setVsPeriod(e.target.value)}>
            {quarters.map(q => <option key={q} value={q}>{q}</option>)}
          </select>
        </div>
        <div className="nt-flow-table">
          <table className="nt-table">
            <thead>
              <tr>
                <th>行业</th>
                <th>上期持股(亿股)</th>
                <th>本期持股(亿股)</th>
                <th>变动股数(亿股)</th>
                <th>变动%</th>
                <th>流入/流出(亿元)</th>
              </tr>
            </thead>
            <tbody>
              {cmpRows.map(r => (
                <tr key={r.sector} className="nt-clickable" onClick={() => setSectorDrill({sector: r.sector, period: period || null})}>
                  <td>{r.sector}{r.isNew && <span className="nt-heat-new nt-heat-new--inline">新</span>}</td>
                  <td>{r.vsShares > 0 ? fmtYiGu(r.vsShares) : '—'}</td>
                  <td>{fmtYiGu(r.curShares)}</td>
                  <td className={r.changeShares >= 0 ? 'num is-up' : 'num is-down'}>
                    {r.changeShares >= 0 ? '+' : ''}{fmtYiGu(r.changeShares)}
                  </td>
                  <td className={r.changeShares >= 0 ? 'num is-up' : 'num is-down'}>
                    {r.isNew || r.changePct === null ? '新增' :
                      (r.changePct >= 0 ? '+' : '') + r.changePct.toFixed(1)}
                  </td>
                  <td className={r.flowYi >= 0 ? 'num is-up' : 'num is-down'}>
                    {r.flowYi >= 0 ? '+' : ''}{r.flowYi.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── 模块 3:行业占比趋势线 ── */}
      <div className="nt-chart-box">
        <div className="nt-chart-title">行业持股占比趋势(%,按最新季度 Top5 + 其他)</div>
        <Button
          size="sm"
          className="nt-flow-toggle"
          onClick={() => setShowAll(v => !v)}
        >
          {showAll ? '只看 Top5' : '显示全部'}
        </Button>
        <ResponsiveContainer width="100%" height={360}>
          <LineChart data={trendDataMerged}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="report_date" {...axisProps} />
            <YAxis {...axisProps} tickFormatter={v => v + '%'} />
            <Tooltip
              {...tooltipProps}
              formatter={(v: any) => [v + '%', '']}
            />
            {allTrendKeys.map((k, i) => (
              <Line
                key={k}
                type="monotone"
                dataKey={k}
                stroke={k === '其他' ? chartTextSecondary : FLOW_PALETTE[i % FLOW_PALETTE.length]}
                isAnimationActive={false}
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ── 模块 4:最新季度加/减仓排行 ── */}
      <div className="nt-chart-box">
        <div className="nt-chart-title">{lastQ} 行业加/减仓排行 Top5(按持股数环比)</div>
        <div className="nt-flow-cols">
          <div className="nt-rank-card nt-rank-card--up">
            <div className="nt-rank-card__head">增持 Top5</div>
            {ups.length === 0 && <div className="nt-rank-empty">无</div>}
            {ups.map((x, i) => (
              <div key={x.sector} className="nt-rank-item nt-clickable" onClick={() => setSectorDrill({sector: x.sector, period: lastQ})}>
                <span className="nt-rank-item__idx">{i + 1}</span>
                <span className="nt-rank-item__name">{x.sector}</span>
                <span className="nt-rank-item__val num is-up">
                  +{fmtYiGu(x.shares)}亿股 ({(x.delta as number) >= 0 ? '+' : ''}{(x.delta as number).toFixed(1)}%)
                </span>
              </div>
            ))}
          </div>
          <div className="nt-rank-card nt-rank-card--down">
            <div className="nt-rank-card__head">减持 Top5</div>
            {downs.length === 0 && <div className="nt-rank-empty">无</div>}
            {downs.map((x, i) => (
              <div key={x.sector} className="nt-rank-item nt-clickable" onClick={() => setSectorDrill({sector: x.sector, period: lastQ})}>
                <span className="nt-rank-item__idx">{i + 1}</span>
                <span className="nt-rank-item__name">{x.sector}</span>
                <span className="nt-rank-item__val num is-down">
                  {fmtYiGu(x.shares)}亿股 ({(x.delta as number).toFixed(1)}%)
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 行业→个股下钻弹窗:点个股行关闭本弹窗并打开既有的 SymbolDrill */}
      {sectorDrill && (
        <SectorStocksModal
          sector={sectorDrill.sector}
          period={sectorDrill.period}
          onClose={() => setSectorDrill(null)}
          onPickStock={(s, n) => { setSectorDrill(null); setStockDrill({symbol: s, name: n}); }}
        />
      )}
      {stockDrill && (
        <SymbolDrill symbol={stockDrill.symbol} name={stockDrill.name} onClose={() => setStockDrill(null)} />
      )}
    </div>
  );
};

const HoldingsTab: React.FC = () => {
  const [view, setView] = useState<'trend' | 'changes' | 'sector' | 'top' | 'flow'>('trend');
  const [coverage, setCoverage] = useState<{report_periods: string[]; symbol_count: number; latest_period: string|null} | null>(null);
  // 全局分类多选(空 = 全部)。仅作用于 trend/changes;sector/top 不受影响。
  const [selCats, setSelCats] = useState<string[]>([]);
  // 日期范围(独立于主体筛选,作用于 trend/sector)
  const [fromDate, setFromDate] = useState('2015-01-01');
  const [customFrom, setCustomFrom] = useState('');
  // 个股搜索 + 下钻
  const [drill, setDrill] = useState<{symbol:string; name:string}|null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/national-team/coverage`)
      .then(r => r.json())
      .then(j => setCoverage(j.data || null))
      .catch(() => setCoverage(null));
  }, []);

  const toggleCat = (key: string) => {
    setSelCats(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]);
  };

  const usingCustomFrom = customFrom !== '';

  return (
    <div className="nt-holdings">
      <SymbolSearch onPick={(s, name) => setDrill({symbol: s, name})} />
      {drill && <SymbolDrill symbol={drill.symbol} name={drill.name} onClose={()=>setDrill(null)} />}
      {coverage && (
        <div className="nt-coverage">
          数据覆盖:{coverage.report_periods.length} 个报告期 · {coverage.symbol_count} 只股 ·
          最新 {coverage.latest_period || '无'}
          {(coverage.report_periods.length < 40) && (
            <span className="nt-coverage-warn"> (历史回填进行中,展示已覆盖部分)</span>
          )}
        </div>
      )}
      <div className="nt-catfilter">
        <span className="nt-catfilter-label">主体筛选:</span>
        {CATEGORY_KEYS.map(k => (
          <button
            key={k}
            className={`nt-catpill ${selCats.includes(k) ? 'nt-catpill--active' : ''}`}
            style={selCats.includes(k) ? {background: CATEGORY_COLORS[k], borderColor: CATEGORY_COLORS[k], color: '#fff'} : undefined}
            onClick={() => toggleCat(k)}
          >
            {CATEGORY_LABEL[k]}
          </button>
        ))}
        {selCats.length > 0 && (
          <button className="nt-catclear" onClick={() => setSelCats([])}>清除</button>
        )}
      </div>
      <div className="nt-rangebar">
        <span className="nt-rangebar-label">时间范围:</span>
        <button
          className={`nt-range-btn ${!usingCustomFrom && fromDate === '2015-01-01' ? 'nt-range-btn--active' : ''}`}
          onClick={() => { setCustomFrom(''); setFromDate('2015-01-01'); }}
        >2015至今</button>
        <button
          className={`nt-range-btn ${!usingCustomFrom && fromDate === new Date(Date.now() - 3*365.25*86400000).toISOString().slice(0,10) ? 'nt-range-btn--active' : ''}`}
          onClick={() => { setCustomFrom(''); setFromDate(new Date(Date.now() - 3*365.25*86400000).toISOString().slice(0,10)); }}
        >近3年</button>
        <button
          className={`nt-range-btn ${!usingCustomFrom && fromDate === new Date(Date.now() - 1*365.25*86400000).toISOString().slice(0,10) ? 'nt-range-btn--active' : ''}`}
          onClick={() => { setCustomFrom(''); setFromDate(new Date(Date.now() - 1*365.25*86400000).toISOString().slice(0,10)); }}
        >近1年</button>
        <span className="nt-rangebar-label">自定义起:</span>
        <input
          type="date"
          className={`nt-date-input ${usingCustomFrom ? 'nt-date-input--active' : ''}`}
          value={customFrom}
          max={new Date().toISOString().slice(0, 10)}
          onChange={e => { setCustomFrom(e.target.value); if (e.target.value) setFromDate(e.target.value); }}
        />
      </div>
      <div className="nt-subtabs">
        <Tabs
          active={view}
          onChange={(k) => setView(k as typeof view)}
          tabs={[
            {key: 'trend', label: '总市值趋势'},
            {key: 'changes', label: '季度变动'},
            {key: 'sector', label: '行业分布'},
            {key: 'top', label: '个股Top'},
            {key: 'flow', label: '行业资金流向'},
          ]}
        />
      </div>
      {view === 'trend' && <TrendView selCats={selCats} fromDate={fromDate} />}
      {view === 'changes' && <ChangesView selCats={selCats} />}
      {view === 'sector' && <SectorView fromDate={fromDate} />}
      {view === 'top' && <TopView />}
      {view === 'flow' && <SectorFlowView />}
    </div>
  );
};

const TrendView: React.FC<{selCats: string[]; fromDate: string}> = ({selCats, fromDate}) => {
  const [series, setSeries] = useState<any[]>([]);
  useEffect(() => {
    const params = new URLSearchParams({from_date: fromDate});
    if (selCats.length) params.set('category', selCats.join(','));
    fetch(`${API_BASE}/national-team/holdings/summary?${params}`)
      .then(r => r.json())
      .then(j => {
        // 透视:report_date → {汇金:x, 证金:y, ...}
        const map: Record<string, any> = {};
        for (const s of (j.data?.series || [])) {
          const d = map[s.report_date] || {report_date: s.report_date};
          d[CATEGORY_LABEL[s.holder_category] || s.holder_category] = fmtYi(s.total_value);
          map[s.report_date] = d;
        }
        setSeries(Object.values(map).sort((a,b)=>a.report_date.localeCompare(b.report_date)));
      });
  }, [selCats.join(','), fromDate]);
  const cats = ['汇金','证金','外管局','社保'];
  return (
    <div className="nt-chart-box">
      <div className="nt-chart-title">国家队总持股市值(亿元,按主体堆叠)</div>
      <ResponsiveContainer width="100%" height={360}>
        <ComposedChart data={series}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="report_date" {...axisProps} />
          <YAxis {...axisProps} />
          <Tooltip {...tooltipProps} />
          {cats.map(c => (
            <Area key={c} type="monotone" dataKey={c} stackId="1"
                  stroke={CATEGORY_COLORS[Object.entries(CATEGORY_LABEL).find(([,v])=>v===c)![0]] || CHART_COLORS[0]}
                  fill={CATEGORY_COLORS[Object.entries(CATEGORY_LABEL).find(([,v])=>v===c)![0]] || CHART_COLORS[0]}
                  fillOpacity={0.4} isAnimationActive={false} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

const ChangesView: React.FC<{selCats: string[]}> = ({selCats}) => {
  const [periods, setPeriods] = useState<string[]>([]);
  const [period, setPeriod] = useState('');
  const [vs, setVs] = useState('');
  const [ctype, setCtype] = useState<string>('');
  const [rows, setRows] = useState<any[]>([]);

  useEffect(() => {
    fetch(`${API_BASE}/national-team/coverage`)
      .then(r=>r.json()).then(j=>{
        const ps = (j.data?.report_periods||[]).sort().reverse();
        setPeriods(ps);
        if (ps.length>=2){ setPeriod(ps[0]); setVs(ps[1]); }
      });
  }, []);

  const load = () => {
    if(!period||!vs) return;
    const params = new URLSearchParams({period, vs_period: vs});
    if(ctype) params.set('change_type', ctype);
    if(selCats.length) params.set('category', selCats.join(','));
    fetch(`${API_BASE}/national-team/holdings/changes?${params}`)
      .then(r=>r.json()).then(j=>setRows(j.data?.changes||[]));
  };

  return (
    <div className="nt-changes">
      <div className="nt-filter">
        <select value={period} onChange={e=>setPeriod(e.target.value)}>
          {periods.map(p=><option key={p} value={p}>{p}</option>)}
        </select>
        <span> vs </span>
        <select value={vs} onChange={e=>setVs(e.target.value)}>
          {periods.map(p=><option key={p} value={p}>{p}</option>)}
        </select>
        <select value={ctype} onChange={e=>setCtype(e.target.value)}>
          <option value="">全部类型</option>
          <option value="new">新进</option>
          <option value="increase">增持</option>
          <option value="decrease">减持</option>
          <option value="exit">退出</option>
        </select>
        <Button variant="primary" size="sm" onClick={load}>查询</Button>
      </div>
      <table className="nt-table">
        <thead><tr><th>股票</th><th>股东</th><th>类别</th><th>本期持股</th><th>变动股数</th><th>类型</th></tr></thead>
        <tbody>
          {rows.map((r,i)=>(
            <tr key={i}>
              <td>{r.company_name}({r.symbol})</td>
              <td>{r.holder_name}</td>
              <td>{CATEGORY_LABEL[r.holder_category]||r.holder_category}</td>
              <td>{r.cur_shares.toLocaleString()}</td>
              <td className={r.change_shares>=0?'num is-up':'num is-down'}>{r.change_shares>=0?'+':''}{r.change_shares.toLocaleString()}</td>
              <td>{{new:'新进',increase:'增持',decrease:'减持',exit:'退出'}[r.change_type]||r.change_type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const SectorView: React.FC<{fromDate: string}> = ({fromDate}) => {
  const [data, setData] = useState<any[]>([]);
  const [sectors, setSectors] = useState<string[]>([]);
  useEffect(()=>{
    fetch(`${API_BASE}/national-team/holdings/sector-distribution?from_date=${fromDate}`)
      .then(r=>r.json()).then(j=>{
        const map: Record<string, any> = {};
        const secs = new Set<string>();
        for (const s of (j.data?.series||[])){
          secs.add(s.sector);
          const d = map[s.report_date]||{report_date:s.report_date};
          d[s.sector] = fmtYi(s.total_value);
          map[s.report_date] = d;
        }
        setSectors([...secs]);
        setData(Object.values(map).sort((a,b)=>a.report_date.localeCompare(b.report_date)));
      });
  },[fromDate]);
  const palette = [CHART_COLORS[0], CHART_COLORS[5], CHART_COLORS[1], colorOrange, CHART_COLORS[0], '#a06bd9'];
  return (
    <div className="nt-chart-box">
      <div className="nt-chart-title">行业分布变迁(亿元,按行业堆叠)</div>
      <ResponsiveContainer width="100%" height={360}>
        <BarChart data={data}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="report_date" {...axisProps} />
          <YAxis {...axisProps} />
          <Tooltip {...tooltipProps} />
          {sectors.map((s,i)=>(
            <Bar key={s} dataKey={s} stackId="1" fill={palette[i%palette.length]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

const TopView: React.FC = () => {
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [drill, setDrill] = useState<{symbol:string; name:string}|null>(null);
  const PAGE = 50;
  const totalPages = Math.max(1, Math.ceil(total / PAGE));

  const loadPage = (p: number) => {
    setLoading(true);
    fetch(`${API_BASE}/national-team/holdings/top?limit=${PAGE}&offset=${(p-1)*PAGE}`)
      .then(r=>r.json())
      .then(j=>{
        setRows(j.data?.rows||[]);
        setTotal(j.data?.total || 0);
        setPage(p);
      })
      .catch(()=>{})
      .finally(()=>setLoading(false));
  };
  useEffect(()=>{ loadPage(1); /* eslint-disable-next-line */ },[]);

  // 分页器:首页 / 上一页 / 页码窗口 / 下一页 / 末页
  const pager = [];
  const win = 2;  // 当前页左右各显示 2 个页码
  const startP = Math.max(1, page - win);
  const endP = Math.min(totalPages, page + win);
  if (startP > 1) { pager.push(1); if (startP > 2) pager.push('…'); }
  for (let p = startP; p <= endP; p++) pager.push(p);
  if (endP < totalPages) { if (endP < totalPages - 1) pager.push('…'); pager.push(totalPages); }

  return (
    <div className="nt-top">
      <div className="nt-top-head">
        共 <b>{total}</b> 只个股有国家队持仓(按最新报告期持股市值降序)
        · 第 {page}/{totalPages} 页
      </div>
      <table className="nt-table">
        <thead><tr><th>#</th><th>股票</th><th>行业</th><th>持股市值(亿)</th><th>国家队成员</th></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={5}>加载中…</td></tr> :
           rows.map((r,i)=>(
            <tr key={r.symbol+i} className="nt-clickable" onClick={()=>setDrill({symbol:r.symbol, name:r.company_name})}>
              <td>{(page-1)*PAGE + i+1}</td>
              <td>{r.company_name}({r.symbol})</td>
              <td>{r.sector}</td>
              <td className="num is-up">{fmtYi(r.total_value)}</td>
              <td>{r.holders.map((h:any)=>CATEGORY_LABEL[h.holder_category]||h.holder_category).join('、')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {totalPages > 1 && (
        <div className="nt-pager">
          <button className="nt-page-btn" disabled={page<=1} onClick={()=>loadPage(1)}>« 首页</button>
          <button className="nt-page-btn" disabled={page<=1} onClick={()=>loadPage(page-1)}>‹ 上一页</button>
          {pager.map((p, idx) =>
            p === '…' ? <span key={`e${idx}`} className="nt-page-ellipsis">…</span> :
            <button key={p} className={`nt-page-btn ${p===page?'nt-page-btn--active':''}`} onClick={()=>loadPage(p as number)}>{p}</button>
          )}
          <button className="nt-page-btn" disabled={page>=totalPages} onClick={()=>loadPage(page+1)}>下一页 ›</button>
          <button className="nt-page-btn" disabled={page>=totalPages} onClick={()=>loadPage(totalPages)}>末页 »</button>
        </div>
      )}
      {drill && <SymbolDrill symbol={drill.symbol} name={drill.name} onClose={()=>setDrill(null)} />}
    </div>
  );
};

const SymbolDrill: React.FC<{symbol:string; name:string; onClose:()=>void}> = ({symbol,name,onClose}) => {
  const [hist, setHist] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(()=>{
    setLoading(true);
    fetch(`${API_BASE}/national-team/holdings/symbol/${symbol}`)
      .then(r=>r.json())
      .then(j=>{
        // 透视:report_date → 持股市值合计(亿) + 持股数量合计(亿股) + 当时收盘价(元)。
        // 先按原始单位(元/股)累加,最后统一换算,避免单位混乱。
        const acc: Record<string, {yuan: number; shares: number; price: number | null}> = {};
        for (const h of (j.data?.history||[])){
          const d = acc[h.report_date] || {yuan: 0, shares: 0, price: null};
          d.yuan += Number(h.hold_value) || 0;
          d.shares += Number(h.hold_shares) || 0;
          if (d.price === null && h.close_price != null) d.price = Number(h.close_price);
          acc[h.report_date] = d;
        }
        const arr = Object.entries(acc)
          .map(([date, d]) => ({
            report_date: date,
            value: Number((d.yuan / 1e8).toFixed(1)),       // 持股市值(亿)
            shares: Number((d.shares / 1e8).toFixed(2)),     // 持股数量(亿股)
            price: d.price,                                  // 报告期收盘价(元,前复权)
          }))
          .sort((a,b)=>a.report_date.localeCompare(b.report_date));
        setHist(arr);
      })
      .catch(()=>setHist([]))
      .finally(()=>setLoading(false));
  },[symbol]);
  const hasPrice = hist.some(h => h.price != null);
  return (
    <Modal
      open
      title={`${name}(${symbol}) 国家队持仓历史`}
      onClose={onClose}
      width={560}
      footer={<Button size="sm" onClick={onClose}>关闭</Button>}
    >
      {!loading && hist.length > 0 && hist.length < 3 && (
        <div className="nt-drill-hint">
          ⓘ 该股仅在 {hist.length} 个季度出现在国家队前十大流通股东中
          (共 {hist.map(h=>h.report_date).join('、')})。
          多数为打新/配售所得,后因流通市值扩大而淡出前十大;国家队未必已清仓,
          但未达前十大披露门槛,故无后续数据。
        </div>
      )}
      {loading ? <StateView state="loading" /> :
       hist.length === 0 ? <StateView state="empty" text="该股暂无国家队持仓记录(国家队从未进入其前十大流通股东)" /> :
       <ResponsiveContainer width="100%" height={280}>
           <ComposedChart data={hist}>
             <CartesianGrid {...gridProps} />
             <XAxis dataKey="report_date" {...axisProps} />
             <YAxis yAxisId="left" {...axisProps} stroke={CHART_COLORS[0]} label={{value:'市值(亿)', angle:-90, position:'insideLeft', fill:chartTextSecondary, style:{fontSize:11}}} />
             <YAxis yAxisId="right" orientation="right" {...axisProps} stroke={colorOrange} label={{value:'持股(亿股)', angle:90, position:'insideRight', fill:chartTextSecondary, style:{fontSize:11}}} />
             {hasPrice && <YAxis yAxisId="price" orientation="right" {...axisProps} stroke={CHART_COLORS[0]} offset={48} label={{value:'股价(元)', angle:-90, position:'insideRight', fill:chartTextSecondary, style:{fontSize:11}}} />}
             <Tooltip {...tooltipProps} formatter={(v:any, n:any)=>{
               if (n==='value') return [`${v} 亿`, '持股市值'];
               if (n==='shares') return [`${v} 亿股`, '持股数量'];
               if (n==='price') return [`${v} 元`, '收盘价'];
               return [v, n];
             }} />
             <Line yAxisId="left" type="monotone" dataKey="value" name="value" stroke={CHART_COLORS[0]} isAnimationActive={false} dot={false} />
             <Line yAxisId="right" type="monotone" dataKey="shares" name="shares" stroke={colorOrange} isAnimationActive={false} dot={false} />
             {hasPrice && <Line yAxisId="price" type="monotone" dataKey="price" name="price" stroke={CHART_COLORS[0]} isAnimationActive={false} dot={false} strokeDasharray="4 2" />}
           </ComposedChart>
         </ResponsiveContainer>}
        <div className="nt-legend">
          <span style={{color:'var(--color-accent)'}}>━ 持股市值(亿)</span>
          <span style={{color:colorOrange}}>━ 持股数量(亿股)</span>
          {hasPrice && <span style={{color:CHART_COLORS[0]}}>┄ 收盘价(元,前复权)</span>}
        </div>
    </Modal>
  );
};

export const NationalTeam: React.FC = () => {
  const [tab, setTab] = useState<TabKey>('daily');

  return (
    <div className="national-team">
      <PageHeader
        title="国家队动向"
        subtitle="每日 ETF 护盘信号 · 持仓全景(行情+估值+团队,DB每日同步) · 历年变迁(2015起) · ETF 动向"
      />

      <div className="national-team__caveat">
        两套口径互补:「每日动向」是行为信号,不点名国家队,盘后可见;
        「历年持仓」来自季报前十大流通股东,季度颗粒度,有 3-4 周披露滞后。
      </div>

      <div className="national-team__tabs">
        <Tabs
          active={tab}
          onChange={(k) => setTab(k as TabKey)}
          tabs={[
            {key: 'daily', label: '每日动向'},
            {key: 'panorama', label: '持仓全景'},
            {key: 'holdings', label: '历年变迁'},
            {key: 'etf', label: 'ETF动向'},
          ]}
        />
      </div>

      <div className="national-team__body">
        {tab === 'daily' ? (
          <DailyTab />
        ) : tab === 'holdings' ? (
          <HoldingsTab />
        ) : tab === 'panorama' ? (
          <NationalTeamLive />
        ) : (
          <NationalTeamEtf />
        )}
      </div>
    </div>
  );
};

export default NationalTeam;
