/**
 * CompsPanel — 类比估值法面板，五法估值之一（相对估值：跟同类型公司比）。
 *
 * 《股票投资课程》15 集：相似的资产应有相似的价格。同行（申万二级，
 * 无归属降一级）中位 PE/PB/PS/股息率反推隐含市值与上下行空间；
 * 局限：只能判断相对高低，须与绝对估值交叉验证。
 */
import {useEffect, useState} from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Cell, LabelList,
} from 'recharts';
import {getApiBase} from '../../lib/api';
import {StateView} from '../ui';
import {axisProps, tooltipProps} from '../../lib/chartTheme';
import '../DcfPanel.css';

const API_BASE = getApiBase();

interface PeerRow {
  symbol: string;
  name: string | null;
  pe_ttm: number | null;
  pb: number | null;
  ps_ttm: number | null;
  dv_ttm: number | null;
  total_mv: number | null;
}

interface MultEntry {
  count: number;
  median: number | null;
  mean: number | null;
  p25: number | null;
  p75: number | null;
  own: number | null;
  own_valid: boolean;
  implied_value: number | null;
  upside: number | null;
  rank_pct: number | null;
}

interface CompsData {
  symbol: string;
  industry: {level: number; code: string; name: string; member_count: number};
  multiples: Record<string, MultEntry>;
  peers: PeerRow[];
  note?: string;
}

const MULT_DEFS: Array<{key: 'pe_ttm' | 'pb' | 'ps_ttm'; label: string}> = [
  {key: 'pe_ttm', label: '市盈率 PE'},
  {key: 'pb', label: '市净率 PB'},
  {key: 'ps_ttm', label: '市销率 PS'},
];

function fmtYi(v: number | null) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v / 1e8).toFixed(0) + ' 亿';
}

function fmtPct(v: number | null) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
}

function fmtN(v: number | null, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  return v.toFixed(digits);
}

export function CompsPanel({symbol}: {symbol: string}) {
  const [data, setData] = useState<CompsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/financial/comps/${symbol}`)
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        if (j.code === 0) setData(j.data ?? null);
        else { setData(null); setError(j.msg || '查询失败'); }
      })
      .catch((e) => alive && setError(e.message || '网络错误'))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [symbol]);

  if (loading) return <StateView state="loading" />;
  if (error) return <StateView state="empty" text={error} />;
  if (!data) return null;

  const {multiples, peers, industry} = data;

  // 乘数对比柱状图数据：目标 vs 同行中位（p25~p75 区间在 tooltip 里看）
  const compareData = MULT_DEFS.map((m) => ({
    name: m.label,
    own: multiples[m.key]?.own ?? null,
    median: multiples[m.key]?.median ?? null,
    p75: multiples[m.key]?.p75 ?? null,
    p25: multiples[m.key]?.p25 ?? null,
  }));

  return (
    <div className="dcf-panel">
      <div className="dcf-panel__title-row">
        <h3 className="dcf-panel__title">
          类比估值 · 同行 {industry.member_count} 家
          （申万{industry.level === 2 ? '二级' : '一级'}：{industry.name}）
        </h3>
      </div>

      {/* 三乘数隐含市值卡 */}
      <div className="vh-cards">
        {MULT_DEFS.map((m) => {
          const e = multiples[m.key];
          const up = e?.upside;
          const color = up == null ? 'var(--color-text-secondary)' : up > 0.2 ? '#3fb950' : up > -0.2 ? '#d29922' : '#f85149';
          return (
            <div className="vh-card" key={m.key}>
              <div className="vh-card__label">{m.label}</div>
              <div className="vh-card__value" style={{color}}>
                {up != null ? fmtPct(up) : '—'}
              </div>
              <div className="vh-card__sub">
                自身 {fmtN(e?.own)} vs 同行中位 {fmtN(e?.median)}
              </div>
              <div className="vh-card__sub">隐含市值 {fmtYi(e?.implied_value)}</div>
              {e?.rank_pct != null && (
                <div className="vh-card__sub">
                  同行排位 {Math.round(e.rank_pct * 100)}%（{e.count} 家有效）
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 目标 vs 同行中位 */}
      <div className="dcf-chart">
        <div className="dcf-chart__title">自身乘数 vs 同行中位（PE/PB/PS）</div>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={compareData} margin={{top: 18, right: 10, left: 0, bottom: 5}}>
            <XAxis dataKey="name" {...axisProps} />
            <YAxis {...axisProps} />
            <Tooltip {...tooltipProps} formatter={(v: number, n: string) => [fmtN(v), n]} />
            <Legend wrapperStyle={{fontSize: 12}} />
            <Bar dataKey="own" name="自身" radius={[3, 3, 0, 0]}>
              {compareData.map((d, i) => (
                <Cell key={i} fill="#d29922" />
              ))}
              <LabelList dataKey="own" position="top"
                formatter={(v: any) => (v == null ? '' : Number(v).toFixed(1))}
                style={{fill: '#adbac7', fontSize: 11}} />
            </Bar>
            <Bar dataKey="median" name="同行中位" radius={[3, 3, 0, 0]} fill="#58a6ff">
              <LabelList dataKey="median" position="top"
                formatter={(v: any) => (v == null ? '' : Number(v).toFixed(1))}
                style={{fill: '#adbac7', fontSize: 11}} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* 同行明细表 */}
      <div className="fin-table-wrap">
        <table className="fin-table">
          <thead>
            <tr>
              <th>股票</th><th>名称</th><th>PE(TTM)</th><th>PB</th>
              <th>PS(TTM)</th><th>股息率%</th><th>总市值</th>
            </tr>
          </thead>
          <tbody>
            {peers.map((p) => {
              const isTarget = p.symbol === symbol;
              return (
                <tr
                  key={p.symbol}
                  className={`${isTarget ? 'vh-row--target' : ''}`}
                  style={isTarget ? {background: 'rgba(210, 153, 34, 0.12)'} : undefined}
                >
                  <td><b>{p.symbol}</b>{isTarget ? ' ★' : ''}</td>
                  <td>{p.name || '—'}</td>
                  <td className="num">{fmtN(p.pe_ttm)}</td>
                  <td className="num">{fmtN(p.pb)}</td>
                  <td className="num">{fmtN(p.ps_ttm)}</td>
                  <td className="num">{fmtN(p.dv_ttm)}</td>
                  <td className="num">{fmtYi(p.total_mv)}</td>
                </tr>
              );
            })}
            <tr style={{borderTop: '2px solid var(--color-border-strong)'}}>
              <td colSpan={2}><b>同行中位（剔除 ≤0）</b></td>
              <td className="num"><b>{fmtN(multiples.pe_ttm?.median)}</b></td>
              <td className="num"><b>{fmtN(multiples.pb?.median)}</b></td>
              <td className="num"><b>{fmtN(multiples.ps_ttm?.median)}</b></td>
              <td className="num"><b>{fmtN(multiples.dv_ttm?.median)}</b></td>
              <td />
            </tr>
            <tr>
              <td colSpan={2}><b>同行均值</b></td>
              <td className="num">{fmtN(multiples.pe_ttm?.mean)}</td>
              <td className="num">{fmtN(multiples.pb?.mean)}</td>
              <td className="num">{fmtN(multiples.ps_ttm?.mean)}</td>
              <td className="num">{fmtN(multiples.dv_ttm?.mean)}</td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>

      {data.note && <div className="dcf-panel__note">{data.note}</div>}
    </div>
  );
}
