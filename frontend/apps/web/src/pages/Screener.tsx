/**
 * 选股器页（含 P1a CSV 导出）。
 *
 * 4 种模式：神奇公式 / 红利 / F-Score / 自定义多因子。
 * 运行选股 → 表格展示 → 一键导出 CSV。
 */
import {useEffect, useMemo, useState} from 'react';
import {getApiBase} from '../lib/api';
import {Button, PageHeader, StateView} from '../components/ui';
import {ScreenerDrillModal} from '../components/ScreenerDrillModal';
import './Screener.css';

const API_BASE = getApiBase();

interface ScreenItem {
  rank: number;
  symbol: string;
  score: number;
  pe_ttm: number | null;
  pb: number | null;
  dv_ttm: number | null;
  roe: number | null;
  roic?: number | null;
  ebit_yield?: number | null;
  debt_ratio: number | null;
  fscore: number | null;
  reason: string;
}

interface ScreenData {
  mode: string;
  as_of: string;
  universe_size: number;
  count: number;
  ranked_list: ScreenItem[];
}

const MODES = [
  {key: 'magic_formula', label: '神奇公式', desc: '低 PE + 高 ROE'},
  {key: 'dividend', label: '红利', desc: '高股息 + 质量过滤'},
  {key: 'fscore', label: 'F-Score', desc: '财务质量 + 低 PB'},
  {key: 'custom', label: '自定义', desc: '多因子门槛'},
  {key: 'dividend_value', label: '红利低估值', desc: '高股息 + 低估分位(PB/PE/PB+PE)'},
];

const fmt = (v: number | null, digits = 2) =>
  v == null || Number.isNaN(v) ? '-' : v.toFixed(digits);

export function Screener() {
  const [mode, setMode] = useState('magic_formula');
  const [topN, setTopN] = useState(20);
  const [data, setData] = useState<ScreenData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [valueMetric, setValueMetric] = useState('pb');       // pb | pe_ttm | pb_pe
  const [valueWindow, setValueWindow] = useState('10y');      // 10y | 20y
  const [excludeRanges, setExcludeRanges] = useState<string[][]>([]);
  const [exStart, setExStart] = useState('');
  const [exEnd, setExEnd] = useState('');
  const [drillSymbol, setDrillSymbol] = useState<string | null>(null);
  const [drillBreakdown, setDrillBreakdown] = useState<any>(null);
  const [drillItem, setDrillItem] = useState<any>(null);

  // 批量加入自选股
  const [bulkGroups, setBulkGroups] = useState<{id: number; name: string}[]>([]);
  const [showBulk, setShowBulk] = useState(false);
  const [bulkGroup, setBulkGroup] = useState<number | null>(null);
  const [bulkAdding, setBulkAdding] = useState(false);
  const [bulkMsg, setBulkMsg] = useState<{ok: boolean; text: string} | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/watchlist/groups`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && Array.isArray(j.data)) {
          const list = j.data.map((g: any) => ({id: g.id, name: g.name}));
          setBulkGroups(list);
          if (list.length > 0) setBulkGroup(list[0].id);
        }
      })
      .catch(() => {});
  }, []);

  // 结果表排序（按真实 Greenblatt 指标等列升降序）
  type SortKey = 'score' | 'pe_ttm' | 'pb' | 'dv_ttm' | 'roe' | 'roic' | 'ebit_yield' | 'debt_ratio' | 'fscore';
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };
  const sortIndicator = (key: SortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ' ↕';
  const sortedList = useMemo(() => {
    if (!data) return [];
    const list = [...data.ranked_list];
    if (!sortKey) return list;
    list.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return sortDir === 'asc'
        ? (av as number) - (bv as number)
        : (bv as number) - (av as number);
    });
    return list;
  }, [data, sortKey, sortDir]);

  const handleBulkAdd = async () => {
    if (bulkGroup == null || bulkAdding || !data) return;
    setBulkAdding(true);
    setBulkMsg(null);
    let ok = 0, fail = 0;
    // 分批并发（8/批）：原来逐只 await，500 只 = 数百个串行 RTT
    const CONCURRENCY = 8;
    const addOne = (symbol: string) =>
      fetch(`${API_BASE}/watchlist/groups/${bulkGroup}/items`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({symbol}),
      }).then((res) => res.json());
    for (let i = 0; i < sortedList.length; i += CONCURRENCY) {
      const outcomes = await Promise.allSettled(
        sortedList.slice(i, i + CONCURRENCY).map((r) => addOne(r.symbol)),
      );
      for (const o of outcomes) {
        if (o.status === 'fulfilled' && o.value.code === 0) ok++;
        else fail++;
      }
    }
    setBulkMsg({
      ok: fail === 0,
      text: `已加入 ${ok} 只${fail > 0 ? `，${fail} 只失败(可能已在分组)` : ''}`,
    });
    setBulkAdding(false);
  };

  const runScreen = () => {
    setLoading(true);
    setError(null);
    const filters: Record<string, any> = {};
    if (mode === 'dividend_value') {
      filters.value_metric = valueMetric;
      filters.value_window = valueWindow;
    }
    fetch(`${API_BASE}/screener/screen`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode, top_n: topN, filters}),
    })
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0) setData(j.data);
        else setError(j.msg || '选股失败');
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  // 首次自动跑一次
  useEffect(() => {
    runScreen();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 拉全局剔除区间
  useEffect(() => {
    fetch(`${API_BASE}/screener/exclude-ranges`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && j.data?.ranges) setExcludeRanges(j.data.ranges);
      })
      .catch(() => {});
  }, []);

  const exportCsv = () => {
    // 直接触发浏览器下载（GET /export）
    const params = new URLSearchParams({
      mode,
      top_n: String(topN),
    });
    window.open(`${API_BASE}/screener/export?${params.toString()}`, '_blank');
  };

  const putExcludeRanges = (ranges: string[][]) => {
    fetch(`${API_BASE}/screener/exclude-ranges`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ranges}),
    })
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0) setExcludeRanges(j.data.ranges);
      })
      .catch(() => {});
  };

  const addExclude = () => {
    if (!exStart || !exEnd) return;
    const next = [...excludeRanges, [exStart, exEnd]];
    putExcludeRanges(next);
    setExStart('');
    setExEnd('');
  };

  const removeExclude = (idx: number) => {
    putExcludeRanges(excludeRanges.filter((_, i) => i !== idx));
  };

  const openDrill = (symbol: string, rowData: any) => {
    setDrillSymbol(symbol);
    setDrillItem(rowData);
    setDrillBreakdown(rowData.factor_breakdown || null);
  };

  return (
    <div style={{padding: 16, color: '#e0e0e0', maxWidth: 1200, margin: '0 auto'}}>
      <PageHeader title="选股器" subtitle="神奇公式 / 红利 / F-Score / 自定义多因子选股" />

      {/* 控制条 */}
      <div style={{display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          {MODES.map((m) => (
            <button
              key={m.key}
              onClick={() => setMode(m.key)}
              title={m.desc}
              style={{
                padding: '4px 14px',
                borderRadius: 16,
                border: '1px solid',
                borderColor: mode === m.key ? 'var(--color-accent)' : '#444',
                background: mode === m.key ? 'var(--color-accent)' : 'transparent',
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
        <label style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 13}}>
          前
          <input
            type="number"
            min={1}
            max={500}
            value={topN}
            onChange={(e) => setTopN(Math.max(1, Math.min(500, Number(e.target.value) || 20)))}
            style={{width: 60, padding: '4px 8px', background: 'var(--color-background)', border: '1px solid #333', borderRadius: 4, color: '#e0e0e0'}}
          />
          名
        </label>
        <Button variant="primary" onClick={runScreen} loading={loading}>
          {loading ? '筛选中…' : '运行选股'}
        </Button>
        {data && (
          <Button variant="secondary" onClick={exportCsv}>导出 CSV</Button>
        )}
      </div>

      {mode === 'dividend_value' && (
        <div style={{display: 'flex', gap: 16, alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', padding: 12, background: 'var(--color-background)', borderRadius: 8}}>
          {/* 低估指标切换 */}
          <div>
            <div style={{fontSize: 12, color: '#888', marginBottom: 4}}>低估指标</div>
            <div style={{display: 'flex', gap: 6}}>
              {[
                {k: 'pb', label: 'PB'},
                {k: 'pe_ttm', label: 'PE'},
                {k: 'pb_pe', label: 'PB+PE'},
              ].map((m) => (
                <button key={m.k} onClick={() => setValueMetric(m.k)}
                  style={{
                    padding: '3px 12px', borderRadius: 14, border: '1px solid',
                    borderColor: valueMetric === m.k ? 'var(--color-accent)' : '#444',
                    background: valueMetric === m.k ? 'var(--color-accent)' : 'transparent',
                    color: '#fff', cursor: 'pointer', fontSize: 12,
                  }}>
                  {m.label}
                </button>
              ))}
            </div>
          </div>
          {/* 窗口切换 */}
          <div>
            <div style={{fontSize: 12, color: '#888', marginBottom: 4}}>历史窗口</div>
            <div style={{display: 'flex', gap: 6}}>
              {['10y', '20y'].map((w) => (
                <button key={w} onClick={() => setValueWindow(w)}
                  style={{
                    padding: '3px 12px', borderRadius: 14, border: '1px solid',
                    borderColor: valueWindow === w ? 'var(--color-accent)' : '#444',
                    background: valueWindow === w ? 'var(--color-accent)' : 'transparent',
                    color: '#fff', cursor: 'pointer', fontSize: 12,
                  }}>
                  {w}
                </button>
              ))}
            </div>
          </div>
          {/* 全局剔除区间编辑器 */}
          <div style={{flex: 1, minWidth: 280}}>
            <div style={{fontSize: 12, color: '#888', marginBottom: 4}}>全局剔除区间（选股+下钻默认剔除）</div>
            <div style={{display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6}}>
              <input type="date" value={exStart} onChange={(e) => setExStart(e.target.value)}
                style={{padding: '3px 6px', background: 'var(--color-background)', border: '1px solid #333', borderRadius: 4, color: '#e0e0e0', fontSize: 12}} />
              <span style={{color: '#888'}}>~</span>
              <input type="date" value={exEnd} onChange={(e) => setExEnd(e.target.value)}
                style={{padding: '3px 6px', background: 'var(--color-background)', border: '1px solid #333', borderRadius: 4, color: '#e0e0e0', fontSize: 12}} />
              <button onClick={addExclude} disabled={!exStart || !exEnd}
                style={{padding: '3px 10px', borderRadius: 4, border: '1px solid #444', background: 'transparent', color: !exStart || !exEnd ? '#666' : '#e0e0e0', cursor: !exStart || !exEnd ? 'not-allowed' : 'pointer', fontSize: 12}}>
                + 添加
              </button>
            </div>
            <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
              {excludeRanges.map((r, i) => (
                <span key={i} style={{display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 10px', borderRadius: 12, background: '#2a2a2a', border: '1px solid #333', fontSize: 11, color: '#aaa'}}>
                  {r[0]}~{r[1]}
                  <button onClick={() => removeExclude(i)} style={{background: 'none', border: 'none', color: 'var(--color-danger)', cursor: 'pointer', fontSize: 13, lineHeight: 1}}>×</button>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {loading && !data && <StateView state="loading" />}
      {error && <StateView state="error" text={error} onRetry={runScreen} />}

      {data && (
        <div style={{fontSize: 12, color: '#888', marginBottom: 8}}>
          模式 {data.mode}　|　截止 {data.as_of}　|　全市场 {data.universe_size} 只 → 入选 {data.count} 只
        </div>
      )}

      {data && data.ranked_list.length > 0 && (
        <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap'}}>
          <span style={{fontSize: 11, color: '#666'}}>点击行查看个股详情</span>
          <Button variant="secondary" size="sm" onClick={() => { setShowBulk((s) => !s); setBulkMsg(null); }}>
            加入全部到自选（{data.count} 只）
          </Button>
          {showBulk && bulkGroups.length > 0 && (
            <span style={{display: 'flex', gap: 6, alignItems: 'center'}}>
              <select
                value={bulkGroup ?? ''}
                onChange={(e) => setBulkGroup(Number(e.target.value))}
                style={{background: 'var(--color-background)', border: '1px solid #444', color: '#e0e0e0', borderRadius: 4, padding: '3px', fontSize: 12}}
              >
                {bulkGroups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
              <Button
                variant="primary"
                size="sm"
                onClick={handleBulkAdd}
                loading={bulkAdding}
                disabled={bulkGroup == null}
              >
                {bulkAdding ? '加入中…' : '确认加入'}
              </Button>
            </span>
          )}
          {showBulk && bulkGroups.length === 0 && (
            <span style={{fontSize: 11, color: '#888'}}>还没有分组，请先到自选股页创建</span>
          )}
          {bulkMsg && (
            <span style={{fontSize: 11, color: bulkMsg.ok ? 'var(--color-success)' : 'var(--color-warning)'}}>{bulkMsg.text}</span>
          )}
        </div>
      )}

      {/* 结果表 */}
      {data && data.ranked_list.length > 0 && (
        <div className="screener-result-wrap">
        <table className="screener-result" style={{width: '100%', fontSize: 13}}>
          <thead>
            <tr style={{borderBottom: '1px solid #333', textAlign: 'left'}}>
              <th style={{padding: '8px 6px'}}>排名</th>
              <th style={{padding: '8px 6px'}}>代码</th>
              <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('score')}>评分{sortIndicator('score')}</th>
              <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('pe_ttm')}>PE_TTM{sortIndicator('pe_ttm')}</th>
              <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('pb')}>PB{sortIndicator('pb')}</th>
              <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('dv_ttm')}>股息率%{sortIndicator('dv_ttm')}</th>
              <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('roe')}>ROE%{sortIndicator('roe')}</th>
              {mode === 'magic_formula' && <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('roic')}>ROIC%{sortIndicator('roic')}</th>}
              {mode === 'magic_formula' && <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('ebit_yield')}>EBIT收益率%{sortIndicator('ebit_yield')}</th>}
              <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('debt_ratio')}>负债率%{sortIndicator('debt_ratio')}</th>
              {mode === 'fscore' && <th style={{padding: '8px 6px', cursor: 'pointer', userSelect: 'none'}} onClick={() => toggleSort('fscore')}>F-Score{sortIndicator('fscore')}</th>}
              <th style={{padding: '8px 6px'}}>理由</th>
            </tr>
          </thead>
          <tbody>
            {sortedList.map((r) => (
              <tr key={r.symbol} onClick={() => openDrill(r.symbol, r)}
                style={{borderBottom: '1px solid #222', cursor: 'pointer'}}>
                <td style={{padding: '6px'}}>{r.rank}</td>
                <td style={{padding: '6px', fontFamily: 'monospace', color: '#5b9dff'}}>{r.symbol}</td>
                <td className="num" style={{padding: '6px'}}>{fmt(r.score)}</td>
                <td className="num" style={{padding: '6px'}}>{fmt(r.pe_ttm)}</td>
                <td className="num" style={{padding: '6px'}}>{fmt(r.pb)}</td>
                <td className="num" style={{padding: '6px'}}>{fmt(r.dv_ttm)}</td>
                <td className="num" style={{padding: '6px'}}>{fmt(r.roe)}</td>
                {mode === 'magic_formula' && <td className="num" style={{padding: '6px'}}>{fmt(r.roic)}</td>}
                {mode === 'magic_formula' && <td className="num" style={{padding: '6px'}}>{fmt(r.ebit_yield)}</td>}
                <td className="num" style={{padding: '6px'}}>{fmt(r.debt_ratio)}</td>
                {mode === 'fscore' && <td style={{padding: '6px'}}>{r.fscore ?? '-'}</td>}
                <td style={{padding: '6px', color: '#aaa', maxWidth: 200}}>{r.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {data && data.ranked_list.length === 0 && (
        <StateView state="empty" text="无入选股票，尝试放宽筛选条件" />
      )}

      {drillSymbol && (
        <ScreenerDrillModal
          symbol={drillSymbol}
          factorBreakdown={drillBreakdown}
          item={drillItem}
          onClose={() => setDrillSymbol(null)}
        />
      )}
    </div>
  );
}

export default Screener;
