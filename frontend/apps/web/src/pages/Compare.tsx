/**
 * 标的对比工作台 — Compare
 * 路径：/compare（菜单"标的对比"）
 *
 * 2~4 只候选并排：质量/五法upside/ROE/成长/护城河/估值。
 * 支撑买入决策与卖出三问之"更优替代"。
 */
import React, {useState} from 'react';
import {getApiBase} from '../lib/api';
import {PageHeader, StateView} from '../components/ui';
import {Button} from '@ytrader/common-components';
import {StockSearch} from '../components/StockSearch';
import './Compare.css';

const API = getApiBase();

interface Row {
  symbol: string;
  quality_score?: number | null;
  quality_verdict?: string | null;
  dcf_upside?: number | null;
  ddm_upside?: number | null;
  asset_upside?: number | null;
  comps_upside?: number | null;
  roe?: number | null;
  revenue_yoy?: number | null;
  pe_ttm?: number | null;
  pb?: number | null;
  dv_ttm?: number | null;
  moat_score?: number | null;
  moat_verdict?: string | null;
  capital_score?: number | null;
}

const DIMS: {key: keyof Row; label: string; higherBetter: boolean; fmt?: (v: number) => string}[] = [
  {key: 'quality_score', label: '质量分(0-100)', higherBetter: true},
  {key: 'quality_verdict', label: '质量结论', higherBetter: true},
  {key: 'moat_score', label: '护城河分', higherBetter: true},
  {key: 'moat_verdict', label: '护城河', higherBetter: true},
  {key: 'capital_score', label: '资本配置分', higherBetter: true},
  {key: 'roe', label: 'ROE(TTM %)', higherBetter: true},
  {key: 'revenue_yoy', label: '营收同比(%)', higherBetter: true},
  {key: 'dcf_upside', label: 'DCF上行(%)', higherBetter: true,
   fmt: v => (v * 100).toFixed(0) + '%'},
  {key: 'ddm_upside', label: 'DDM上行(%)', higherBetter: true,
   fmt: v => (v * 100).toFixed(0) + '%'},
  {key: 'asset_upside', label: '净资产法上行(%)', higherBetter: true,
   fmt: v => (v * 100).toFixed(0) + '%'},
  {key: 'comps_upside', label: '类比法上行(%)', higherBetter: true,
   fmt: v => (v * 100).toFixed(0) + '%'},
  {key: 'pe_ttm', label: 'PE(TTM)', higherBetter: false},
  {key: 'pb', label: 'PB', higherBetter: false},
  {key: 'dv_ttm', label: '股息率(%)', higherBetter: true},
];

export const Compare: React.FC = () => {
  const [picked, setPicked] = useState<string[]>(() => {
    const add = new URLSearchParams(window.location.search).get('add');
    return add ? [add.toLowerCase()] : [];
  });
  const [input, setInput] = useState('');
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function add(sym: string) {
    const s = sym.toLowerCase();
    if (s && !picked.includes(s) && picked.length < 4) {
      setPicked([...picked, s]);
    }
    setInput('');
  }

  async function run() {
    if (picked.length < 2) {setError('至少选择 2 只'); return;}
    setLoading(true); setError(null);
    try {
      const d = await (await fetch(
        `${API}/thesis/compare?symbols=${picked.join(',')}`)).json();
      if (d.code !== 0) throw new Error(d.msg || '对比失败');
      setRows(d.data.rows);
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {setLoading(false);}
  }

  const numFmt = (v: any, fmt?: (n: number) => string) =>
    v == null ? '—' : (fmt ? fmt(v) : (typeof v === 'number' ? v.toFixed(2) : String(v)));

  // 每数值维度找最优（高优取max/低优取min），渲染时高亮
  const bestOf = (key: keyof Row, higherBetter: boolean): number | null => {
    if (!rows) return null;
    const vals = rows.map(r => r[key]).filter(
      (v): v is number => typeof v === 'number' && v !== null);
    if (vals.length < 2) return null;
    return higherBetter ? Math.max(...vals) : Math.min(...vals);
  };

  return (
    <div className="compare-page">
      <PageHeader
        title="标的对比"
        subtitle="2~4 只候选并排：质量/护城河/成长/五法估值/估值倍数——买入决策与'更优替代'的依据。"
      />
      <div className="compare__picker">
        <StockSearch value={input} onSelect={add}/>
        <span className="dim">已选 {picked.length}/4：</span>
        {picked.map(s => (
          <span key={s} className="compare__chip mono"
                onClick={() => setPicked(picked.filter(x => x !== s))}>
            {s} ×
          </span>
        ))}
        <Button variant="primary" loading={loading} onClick={run}>对比</Button>
      </div>
      {error && <p className="compare__error">{error}</p>}
      {picked.length < 2 && !rows && (
        <StateView state="empty" text="搜索并选择至少 2 只标的（点击已选标签可移除）"/>
      )}
      {rows && rows.length >= 1 && (
        <table className="thesis-table">
          <thead>
            <tr><th>维度</th>{rows.map(r => <th key={r.symbol} className="mono">{r.symbol}</th>)}</tr>
          </thead>
          <tbody>
            {DIMS.map(d => {
              const best = bestOf(d.key, d.higherBetter);
              return (
                <tr key={String(d.key)}>
                  <td>{d.label}</td>
                  {rows.map(r => {
                    const v = r[d.key];
                    const isBest = typeof v === 'number' && v === best;
                    return (
                      <td key={r.symbol}
                          className={isBest ? 'compare__best' : ''}>
                        {numFmt(v, d.fmt)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
};
