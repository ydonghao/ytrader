/**
 * 国家队「实时全景」5 个新 Tab(移植自压缩包仪表盘,全动态数据)。
 *
 * 数据源:
 *   /national-team/live/snapshot  — 持仓+实时行情+汇总+矩阵+洞察(覆盖 4 个 Tab)
 *   /national-team/etf/snapshot   — ETF 实时+份额信号(覆盖 ETF Tab)
 *   /national-team/live/kline     — 个股/ETF 日K(详情弹窗蜡烛图)
 *
 * 既有「每日动向/历年持仓」两 Tab 在 NationalTeam.tsx 中完全不变,本文件只服务新 Tab。
 */
import React, {useEffect, useMemo, useState} from 'react';
import {getApiBase} from '../../lib/api';
import {Button, Modal, StateView, Tabs} from '../../components/ui';
import {EChart} from './EChart';
import { CHART_COLORS, colorUp, colorDown, colorOrange, chartTextSecondary, chartTextTertiary, chartBorder, chartSurface, HEAT_SCALE } from '../../lib/chartTheme';
import {
  Snapshot, EtfSnapshot, KlinePoint, TeamSummary, StockSummary,
  HoldingDetail, Insight, fmtYi, pct, chgClass, styleTag, INSIGHT_META,
} from './types';

const API = getApiBase();

// ── 数据 hooks ──
function useSnapshot() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API}/national-team/live/snapshot`)
      .then(r => r.json()).then(j => {if (alive) setSnap(j.data || null);})
      .catch(() => {if (alive) setErr('加载失败');});
    return () => {alive = false;};
  }, []);
  return {snap, err};
}
function useEtf() {
  const [etf, setEtf] = useState<EtfSnapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API}/national-team/etf/snapshot`)
      .then(r => r.json()).then(j => {if (alive) setEtf(j.data || null);})
      .catch(() => {if (alive) setErr('加载失败');});
    return () => {alive = false;};
  }, []);
  return {etf, err};
}

// ── 股票详情弹窗(前复权日K蜡烛图)──
const StockModal: React.FC<{code: string; name: string; onClose: () => void}> = ({code, name, onClose}) => {
  const [kline, setKline] = useState<KlinePoint[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API}/national-team/live/kline?symbol=${code}&days=60`)
      .then(r => r.json()).then(j => {if (alive) setKline(j.data?.kline || []);})
      .catch(() => {}).finally(() => {if (alive) setLoading(false);});
    return () => {alive = false;};
  }, [code]);
  const option = useMemo(() => {
    if (!kline.length) return {};
    return {
      tooltip: {trigger: 'axis', axisPointer: {type: 'cross'}},
      xAxis: {type: 'category', data: kline.map(k => k.date.slice(5)), axisLine: {lineStyle: {color: chartBorder}}},
      yAxis: {scale: true, splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      dataZoom: [{type: 'inside', start: 40, end: 100}],
      series: [{
        type: 'candlestick',
        data: kline.map(k => [k.open, k.close, k.low, k.high]),
        // A股:涨红跌绿
        itemStyle: {color: colorUp, color0: colorDown, borderColor: colorUp, borderColor0: colorDown},
      }],
    } as any;
  }, [kline]);
  return (
    <Modal
      open
      title={`${name}(${code}) 近60日K线(前复权)`}
      onClose={onClose}
      width={640}
      footer={<Button size="sm" onClick={onClose}>关闭</Button>}
    >
      {loading ? <StateView state="loading" /> :
       kline.length === 0 ? <StateView state="empty" text="暂无K线数据" /> :
       <EChart option={option} height={260} />}
    </Modal>
  );
};

// ════════════════ 1. 实时全景 ════════════════
const OverviewTab: React.FC<{snap: Snapshot; onPickStock: (c: string, n: string) => void}> = ({snap, onPickStock}) => {
  const {meta, team_summary, sector_summary, stock_summary, insights} = snap;
  const ups = stock_summary.filter(s => s.change_pct > 0).length;
  const downs = stock_summary.filter(s => s.change_pct < 0).length;
  const top3up = [...stock_summary].sort((a, b) => b.change_pct - a.change_pct).slice(0, 3);
  const top3down = [...stock_summary].sort((a, b) => a.change_pct - b.change_pct).slice(0, 3);

  const teamPieOpt = useMemo(() => ({
    tooltip: {trigger: 'item', formatter: '{b}: {c}亿 ({d}%)'},
    legend: {bottom: 0, textStyle: {color: chartTextSecondary, fontSize: 11}},
    series: [{
      type: 'pie', radius: ['42%', '70%'], center: ['50%', '45%'],
      itemStyle: {borderRadius: 4, borderColor: chartSurface, borderWidth: 2},
      label: {color: chartTextSecondary, fontSize: 11},
      data: team_summary.map(t => ({name: t.team, value: Number(t.total_holding_value.toFixed(1)), itemStyle: {color: t.color}})),
    }],
  }), [team_summary]);

  const sectorBarOpt = useMemo(() => {
    const data = [...sector_summary].slice(0, 12);
    return {
      tooltip: {trigger: 'axis', formatter: (p: any) => `${p[0].name}: ${fmtYi(p[0].value)}`},
      grid: {left: 10, right: 40, top: 10, bottom: 10, containLabel: true},
      xAxis: {type: 'value', splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {type: 'category', data: data.map(d => d.sector).reverse(), axisLabel: {color: chartTextSecondary, fontSize: 11}},
      series: [{
        type: 'bar', data: data.map(d => Number(d.total_value.toFixed(0))).reverse(),
        itemStyle: {borderRadius: [0, 4, 4, 0], color: {type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: CHART_COLORS[0]}, {offset: 1, color: '#bf5af2'}]}},
        label: {show: true, position: 'right', formatter: (p: any) => fmtYi(p.value), color: chartTextSecondary, fontSize: 10},
      }],
    } as any;
  }, [sector_summary]);

  const topBarOpt = useMemo(() => {
    const data = [...stock_summary].sort((a, b) => b.total_holding_value - a.total_holding_value).slice(0, 15);
    return {
      tooltip: {trigger: 'axis', formatter: (p: any) => `${p[0].name}: ${fmtYi(p[0].value)}`},
      grid: {left: 10, right: 50, top: 10, bottom: 10, containLabel: true},
      xAxis: {type: 'value', splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {type: 'category', data: data.map(d => `${d.name}(${d.industry})`).reverse(), axisLabel: {color: chartTextSecondary, fontSize: 10}},
      series: [{
        type: 'bar', data: data.map(d => Number(d.total_holding_value.toFixed(0))).reverse(),
        itemStyle: {borderRadius: [0, 4, 4, 0], color: {type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: CHART_COLORS[5]}, {offset: 1, color: colorOrange}]}},
        label: {show: true, position: 'right', formatter: (p: any) => fmtYi(p.value), color: chartTextSecondary, fontSize: 10},
      }],
    } as any;
  }, [stock_summary]);

  const treemapOpt = useMemo(() => {
    const bySector: Record<string, any[]> = {};
    for (const s of stock_summary) {
      (bySector[s.sector] = bySector[s.sector] || []).push({name: `${s.name}\n${fmtYi(s.total_holding_value)}`, value: Number(s.total_holding_value.toFixed(0))});
    }
    return {
      tooltip: {formatter: (p: any) => `${p.name}: ${fmtYi(p.value)}`},
      series: [{
        type: 'treemap', roam: false, nodeClick: false,
        breadcrumb: {show: false},
        label: {color: '#fff', fontSize: 10},
        upperLabel: {show: true, height: 22, color: '#fff', fontSize: 11},
        data: Object.entries(bySector).map(([sec, children]) => ({name: sec, value: children.reduce((a, b) => a + b.value, 0), children})),
        levels: [{itemStyle: {borderColor: chartSurface, borderWidth: 2, gapWidth: 2}}, {colorSaturation: [0.3, 0.6], itemStyle: {borderColor: chartSurface, borderWidth: 1, gapWidth: 1}}],
      }],
    } as any;
  }, [stock_summary]);

  return (
    <div className="nt-live">
      <div className="nt-kpi-row">
        <div className="nt-kpi-card" style={{borderTopColor: 'var(--color-accent)'}}>
          <div className="nt-kpi-label">国家队持仓总市值</div>
          <div className="nt-kpi-val">{meta.total_value_display}</div>
          <div className="nt-kpi-sub">{meta.total_holdings} 条持仓 · {meta.total_stocks} 只标的</div>
        </div>
        <div className="nt-kpi-card" style={{borderTopColor: 'var(--color-danger)'}}>
          <div className="nt-kpi-label">今日上涨</div>
          <div className="nt-kpi-val num is-up">{ups}</div>
          <div className="nt-kpi-sub">只</div>
        </div>
        <div className="nt-kpi-card" style={{borderTopColor: 'var(--color-success)'}}>
          <div className="nt-kpi-label">今日下跌</div>
          <div className="nt-kpi-val num is-down">{downs}</div>
          <div className="nt-kpi-sub">只</div>
        </div>
        <div className="nt-kpi-card" style={{borderTopColor: '#bf5af2'}}>
          <div className="nt-kpi-label">数据时点</div>
          <div className="nt-kpi-val-sm">{meta.market_status}</div>
          <div className="nt-kpi-sub">{meta.update_time.slice(11)}</div>
        </div>
      </div>

      {insights.length > 0 && (
        <div className="nt-insights">
          <div className="nt-insights-title">量化信号洞察</div>
          <div className="nt-insights-grid">
            {insights.map((ins, i) => {
              const m = INSIGHT_META[ins.level] || INSIGHT_META.info;
              return (
                <div key={i} className={`nt-insight-card ${m.cls}`}>
                  <div className="nt-insight-head">{m.icon} {ins.title}</div>
                  <div className="nt-insight-detail">{ins.detail}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="nt-chart-grid2">
        <div className="nt-chart-box">
          <div className="nt-chart-title">团队持仓分布</div>
          <EChart option={teamPieOpt} height={260} />
        </div>
        <div className="nt-chart-box">
          <div className="nt-chart-title">行业板块分布(持仓市值)</div>
          <EChart option={sectorBarOpt} height={260} />
        </div>
      </div>
      <div className="nt-chart-box">
        <div className="nt-chart-title">TOP15 持仓市值排行(点击柱查看个股)</div>
        <EChart option={topBarOpt} height={320}
          onEvents={{click: (p: any) => {
            if (p.componentType === 'series') return;
            const idx = stock_summary.length - 1 - p.dataIndex;
            const sorted = [...stock_summary].sort((a, b) => b.total_holding_value - a.total_holding_value);
            const s = sorted[p.dataIndex];
            if (s) onPickStock(s.code, s.name);
          }}}
        />
      </div>
      <div className="nt-chart-box">
        <div className="nt-chart-title">持仓分布树图(按行业→个股,面积=市值)</div>
        <EChart option={treemapOpt} height={340} />
      </div>

      <div className="nt-movers">
        <div className="nt-mover-col">
          <div className="nt-mover-head is-up">今日涨幅 TOP3</div>
          {top3up.map(s => (
            <div key={s.code} className="nt-mover-item nt-clickable" onClick={() => onPickStock(s.code, s.name)}>
              <span>{s.name}</span><span className="num is-up">{pct(s.change_pct)}</span>
            </div>
          ))}
        </div>
        <div className="nt-mover-col">
          <div className="nt-mover-head is-down">今日跌幅 TOP3</div>
          {top3down.map(s => (
            <div key={s.code} className="nt-mover-item nt-clickable" onClick={() => onPickStock(s.code, s.name)}>
              <span>{s.name}</span><span className="num is-down">{pct(s.change_pct)}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="nt-source-note">数据来源:{meta.data_period} · {meta.data_integrity_note}</div>
    </div>
  );
};

// ════════════════ 2. 持仓明细 ════════════════
const HoldingsDetailTab: React.FC<{snap: Snapshot; onPickStock: (c: string, n: string) => void}> = ({snap, onPickStock}) => {
  const {holdings_detail, sector_summary} = snap;
  const [sector, setSector] = useState('');
  const [q, setQ] = useState('');
  const [sortKey, setSortKey] = useState<'holding_value_yi'|'change_pct'|'pe_ttm'|'pb'|'ratio'|'week_52_position'>('holding_value_yi');
  const [asc, setAsc] = useState(false);

  const sectors = sector_summary.map(s => s.sector);
  const filtered = useMemo(() => {
    let r = holdings_detail;
    if (sector) r = r.filter(d => d.sector === sector);
    if (q.trim()) {
      const k = q.trim().toLowerCase();
      r = r.filter(d => d.name.toLowerCase().includes(k) || d.code.includes(k) || d.team.includes(q.trim()) || d.entity.includes(q.trim()));
    }
    const arr = [...r].sort((a, b) => {
      const va = (a as any)[sortKey] || 0, vb = (b as any)[sortKey] || 0;
      return asc ? va - vb : vb - va;
    });
    return arr.slice(0, 200); // 前200条(展示用,避免渲染过万行)
  }, [holdings_detail, sector, q, sortKey, asc]);

  const toggleSort = (k: typeof sortKey) => {
    if (k === sortKey) setAsc(!asc); else {setSortKey(k); setAsc(false);}
  };
  const Th = ({k, children}: {k: typeof sortKey; children: React.ReactNode}) => (
    <th className="nt-th-sort" onClick={() => toggleSort(k)}>{children}{sortKey === k ? (asc ? ' ↑' : ' ↓') : ''}</th>
  );

  return (
    <div className="nt-detail">
      <div className="nt-detail-bar">
        <input className="nt-search2" placeholder="搜索股票/代码/主体" value={q} onChange={e => setQ(e.target.value)} />
        <div className="nt-sector-chips">
          <button className={`nt-chip ${!sector ? 'nt-chip--active' : ''}`} onClick={() => setSector('')}>全部</button>
          {sectors.map(s => (
            <button key={s} className={`nt-chip ${sector === s ? 'nt-chip--active' : ''}`} onClick={() => setSector(s)}>{s}</button>
          ))}
        </div>
        <span className="nt-detail-count">显示 {filtered.length} / {holdings_detail.length} 条</span>
      </div>
      <div className="nt-table-wrap">
        <table className="nt-table">
          <thead>
            <tr>
              <th>股票</th><th>主体</th><th><span className="nt-team-tag">团队</span></th>
              <Th k="ratio">持股%</Th><th>现价</th><Th k="change_pct">涨跌%</Th>
              <Th k="holding_value_yi">持仓市值</Th><Th k="pe_ttm">PE</Th><Th k="pb">PB</Th>
              <Th k="week_52_position">52周位</Th><th>量比</th><th>风格</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((d, i) => {
              const st = styleTag(d.pe_ttm);
              return (
                <tr key={i} className="nt-clickable" onClick={() => onPickStock(d.code, d.name)}>
                  <td>{d.name}<br/><span className="nt-sub">{d.code} · {d.industry}</span></td>
                  <td>{d.entity}</td>
                  <td><span className="nt-team-tag" style={{color: snap.team_summary.find(t => t.team === d.team)?.color || '#999', borderColor: snap.team_summary.find(t => t.team === d.team)?.color || '#999'}}>{d.team_type}</span></td>
                  <td>{d.ratio.toFixed(2)}%</td>
                  <td>{d.price.toFixed(2)}</td>
                  <td className={chgClass(d.change_pct)}>{pct(d.change_pct)}</td>
                  <td className="num is-up">{fmtYi(d.holding_value_yi)}</td>
                  <td>{d.pe_ttm > 0 ? d.pe_ttm.toFixed(1) : '-'}</td>
                  <td>{d.pb > 0 ? d.pb.toFixed(2) : '-'}</td>
                  <td>{d.week_52_position.toFixed(0)}</td>
                  <td>{d.volume_ratio.toFixed(2)}</td>
                  <td><span className={`nt-style-tag ${st.cls}`}>{st.label}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ════════════════ 3. 估值分析 ════════════════
const ValuationTab: React.FC<{snap: Snapshot; onPickStock: (c: string, n: string) => void}> = ({snap, onPickStock}) => {
  const {stock_summary, team_summary} = snap;

  // PE-PB 气泡散点(4维:x=pe y=pb size=holding_value color=team)
  const scatterOpt = useMemo(() => {
    const byTeam: Record<string, any[]> = {};
    for (const s of stock_summary) {
      if (s.pe_ttm <= 0 || s.pb <= 0) continue;
      const team = s.holders[0]?.team || '其他';
      (byTeam[team] = byTeam[team] || []).push([s.pe_ttm, s.pb, Math.sqrt(Math.max(s.total_holding_value, 1)), s.name, s.code]);
    }
    return {
      tooltip: {formatter: (p: any) => {
        const d = p.value;
        return `${d[3]}(${d[4]})<br/>PE: ${d[0].toFixed(1)}<br/>PB: ${d[1].toFixed(2)}<br/>持仓: ${fmtYi(d[2] * d[2])}`;
      }},
      legend: {top: 0, textStyle: {color: chartTextSecondary, fontSize: 11}},
      grid: {left: 10, right: 20, top: 40, bottom: 30, containLabel: true},
      xAxis: {name: 'PE(TTM)', nameTextStyle: {color: chartTextSecondary}, type: 'value', scale: true, max: 80, splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {name: 'PB', nameTextStyle: {color: chartTextSecondary}, type: 'value', scale: true, max: 10, splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      series: Object.entries(byTeam).map(([team, data]) => ({
        name: team, type: 'scatter', data,
        symbolSize: (v: number[]) => Math.min(60, Math.max(8, v[2] / 15)),
        itemStyle: {opacity: 0.75, color: team_summary.find(t => t.team === team)?.color || CHART_COLORS[0]},
      })),
    } as any;
  }, [stock_summary, team_summary]);

  const distBar = (field: 'pe_ttm' | 'pb', max: number, label: string, colorFn: (v: number) => string) => {
    const data = [...stock_summary].filter(s => s[field] > 0 && s[field] < max).sort((a, b) => b[field] - a[field]).slice(0, 20);
    return {
      tooltip: {trigger: 'axis'},
      grid: {left: 10, right: 30, top: 10, bottom: 10, containLabel: true},
      xAxis: {type: 'value', splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {type: 'category', data: data.map(d => d.name).reverse(), axisLabel: {color: chartTextSecondary, fontSize: 10}},
      series: [{
        type: 'bar', data: data.map(d => Number(d[field].toFixed(2))).reverse(),
        itemStyle: {borderRadius: [0, 4, 4, 0], color: (p: any) => colorFn(data[data.length - 1 - p.dataIndex][field])},
      }],
    } as any;
  };
  const peOpt = distBar('pe_ttm', 60, 'PE', (v) => v < 10 ? colorDown : v < 20 ? colorOrange : colorUp);
  const pbOpt = distBar('pb', 15, 'PB', (v) => v < 1 ? colorDown : v < 3 ? colorOrange : colorUp);

  // 52周位置分布(visualMap 绿→黄→红)
  const w52Opt = useMemo(() => {
    const data = [...stock_summary].filter(s => s.week_52_position > 0).sort((a, b) => b.week_52_position - a.week_52_position).slice(0, 20);
    return {
      tooltip: {trigger: 'axis'},
      grid: {left: 10, right: 30, top: 30, bottom: 10, containLabel: true},
      xAxis: {type: 'value', max: 100, splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {type: 'category', data: data.map(d => d.name).reverse(), axisLabel: {color: chartTextSecondary, fontSize: 10}},
      visualMap: {min: 0, max: 100, show: false, inRange: {color: [colorDown, colorOrange, colorUp]}},
      series: [{type: 'bar', data: data.map(d => Number(d.week_52_position.toFixed(0))).reverse(), itemStyle: {borderRadius: [0, 4, 4, 0]}}],
    } as any;
  }, [stock_summary]);

  // 今日涨跌幅分布(7档直方)
  const chgDistOpt = useMemo(() => {
    const bins = ['跌>3%', '跌1-3%', '跌0-1%', '平', '涨0-1%', '涨1-3%', '涨>3%'];
    const counts = [0, 0, 0, 0, 0, 0, 0];
    for (const s of stock_summary) {
      const c = s.change_pct;
      if (c <= -3) counts[0]++;
      else if (c < -1) counts[1]++;
      else if (c < 0) counts[2]++;
      else if (c === 0) counts[3]++;
      else if (c < 1) counts[4]++;
      else if (c < 3) counts[5]++;
      else counts[6]++;
    }
    const colors = [colorDown, colorDown, colorDown, chartTextTertiary, colorUp, colorUp, colorUp];
    return {
      tooltip: {trigger: 'axis'},
      grid: {left: 10, right: 20, top: 20, bottom: 30, containLabel: true},
      xAxis: {type: 'category', data: bins, axisLabel: {color: chartTextSecondary, fontSize: 10}},
      yAxis: {type: 'value', splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      series: [{type: 'bar', data: counts.map((v, i) => ({value: v, itemStyle: {color: colors[i]}})), itemStyle: {borderRadius: [4, 4, 0, 0]}}],
    } as any;
  }, [stock_summary]);

  // 近20日动量 TOP15
  const momOpt = useMemo(() => {
    const data = [...stock_summary].filter(s => s.chg_20d != null).sort((a, b) => b.chg_20d - a.chg_20d).slice(0, 15);
    return {
      tooltip: {trigger: 'axis'},
      grid: {left: 10, right: 30, top: 10, bottom: 10, containLabel: true},
      xAxis: {type: 'value', splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {type: 'category', data: data.map(d => d.name).reverse(), axisLabel: {color: chartTextSecondary, fontSize: 10}},
      series: [{type: 'bar', data: data.map(d => ({value: Number(d.chg_20d.toFixed(2)), itemStyle: {color: d.chg_20d >= 0 ? colorUp : colorDown, borderRadius: [0, 4, 4, 0]}})).reverse()}],
    } as any;
  }, [stock_summary]);
  // 近20日最大回撤 TOP15(最负在前)
  const ddOpt = useMemo(() => {
    const data = [...stock_summary].filter(s => s.max_drawdown_20d != null).sort((a, b) => a.max_drawdown_20d - b.max_drawdown_20d).slice(0, 15);
    return {
      tooltip: {trigger: 'axis'},
      grid: {left: 10, right: 30, top: 10, bottom: 10, containLabel: true},
      xAxis: {type: 'value', splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {type: 'category', data: data.map(d => d.name).reverse(), axisLabel: {color: chartTextSecondary, fontSize: 10}},
      series: [{type: 'bar', data: data.map(d => ({value: Number(d.max_drawdown_20d.toFixed(2)), itemStyle: {color: colorDown, borderRadius: [0, 4, 4, 0]}})).reverse()}],
    } as any;
  }, [stock_summary]);

  return (
    <div className="nt-val">
      <div className="nt-chart-box">
        <div className="nt-chart-title">PE-PB 估值散点图(X=PE, Y=PB, 气泡=持仓市值, 颜色=团队)</div>
        <EChart option={scatterOpt} height={420}
          onEvents={{click: (p: any) => {
            const code = p.value?.[4];
            const name = p.value?.[3];
            if (code) onPickStock(code, name);
          }}}
        />
      </div>
      <div className="nt-chart-grid2">
        <div className="nt-chart-box">
          <div className="nt-chart-title">PE(TTM) TOP20(绿&lt;10 橙&lt;20 红≥20)</div>
          <EChart option={peOpt} height={300} />
        </div>
        <div className="nt-chart-box">
          <div className="nt-chart-title">PB TOP20(绿&lt;1 橙&lt;3 红≥3)</div>
          <EChart option={pbOpt} height={300} />
        </div>
      </div>
      <div className="nt-chart-grid2">
        <div className="nt-chart-box">
          <div className="nt-chart-title">52周位置 TOP20(绿低位→红高位)</div>
          <EChart option={w52Opt} height={300} />
        </div>
        <div className="nt-chart-box">
          <div className="nt-chart-title">今日涨跌幅分布</div>
          <EChart option={chgDistOpt} height={300} />
        </div>
      </div>
      <div className="nt-chart-grid2">
        <div className="nt-chart-box">
          <div className="nt-chart-title">近20日动量 TOP15(红涨绿跌)</div>
          <EChart option={momOpt} height={300} />
        </div>
        <div className="nt-chart-box">
          <div className="nt-chart-title">近20日最大回撤 TOP15</div>
          <EChart option={ddOpt} height={300} />
        </div>
      </div>
    </div>
  );
};

// ════════════════ 4. ETF 追踪 ════════════════
const EtfTab: React.FC<{onPickEtf: (c: string, n: string) => void}> = ({onPickEtf}) => {
  const {etf, err} = useEtf();
  if (err) return <StateView state="error" text={err} />;
  if (!etf) return <StateView state="loading" />;

  const shareChgOpt = (() => {
    const data = etf.etfs.filter(e => e.shares_change_yi != null).sort((a, b) => Math.abs(b.shares_change_yi!) - Math.abs(a.shares_change_yi!)).slice(0, 10);
    return {
      tooltip: {trigger: 'axis', formatter: (p: any) => `${p[0].name}: ${p[0].value > 0 ? '申购' : '赎回'} ${Math.abs(p[0].value)}亿份`},
      grid: {left: 10, right: 30, top: 10, bottom: 10, containLabel: true},
      xAxis: {type: 'value', splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {type: 'category', data: data.map(d => d.name).reverse(), axisLabel: {color: chartTextSecondary, fontSize: 10}},
      series: [{type: 'bar', data: data.map(d => ({value: Number(d.shares_change_yi!.toFixed(2)), itemStyle: {color: (d.shares_change_yi! >= 0 ? colorUp : colorDown), borderRadius: [0, 4, 4, 0]}})).reverse()}],
    } as any;
  })();
  const sizeOpt = (() => {
    const data = [...etf.etfs].sort((a, b) => b.total_value_yi - a.total_value_yi);
    return {
      tooltip: {trigger: 'axis', formatter: (p: any) => `${p[0].name}: ${fmtYi(p[0].value)}`},
      grid: {left: 10, right: 40, top: 10, bottom: 10, containLabel: true},
      xAxis: {type: 'value', splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      yAxis: {type: 'category', data: data.map(d => d.name).reverse(), axisLabel: {color: chartTextSecondary, fontSize: 10}},
      series: [{type: 'bar', data: data.map(d => Number(d.total_value_yi.toFixed(0))).reverse(), itemStyle: {borderRadius: [0, 4, 4, 0], color: {type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#bf5af2'}, {offset: 1, color: '#64d2ff'}]}}, label: {show: true, position: 'right', formatter: (p: any) => fmtYi(p.value), color: chartTextSecondary, fontSize: 10}}],
    } as any;
  })();

  return (
    <div className="nt-etf">
      <div className="nt-kpi-row">
        <div className="nt-kpi-card" style={{borderTopColor: '#bf5af2'}}><div className="nt-kpi-label">ETF 总规模</div><div className="nt-kpi-val">{fmtYi(etf.total_value_yi)}</div><div className="nt-kpi-sub">{etf.etfs.length} 只核心宽基</div></div>
        <div className="nt-kpi-card" style={{borderTopColor: 'var(--color-warning)'}}><div className="nt-kpi-label">异常信号</div><div className="nt-kpi-val">{etf.signals.length}</div><div className="nt-kpi-sub">份额变动/换手</div></div>
        <div className="nt-kpi-card" style={{borderTopColor: 'var(--color-text-tertiary)'}}><div className="nt-kpi-label">数据状态</div><div className="nt-kpi-val-sm">{etf.history_dates.length} 日</div><div className="nt-kpi-sub">{etf.coverage}</div></div>
      </div>

      {etf.signals.length > 0 && (
        <div className="nt-insights">
          <div className="nt-insights-title">ETF 信号</div>
          <div className="nt-insights-grid">
            {etf.signals.map((s, i) => {
              const m = INSIGHT_META[s.level] || INSIGHT_META.info;
              return <div key={i} className={`nt-insight-card ${m.cls}`}><div className="nt-insight-head">{m.icon} {s.title}</div><div className="nt-insight-detail">{s.detail}</div></div>;
            })}
          </div>
        </div>
      )}

      <div className="nt-chart-grid2">
        <div className="nt-chart-box"><div className="nt-chart-title">今日份额变动 TOP(红=申购 绿=赎回)</div><EChart option={shareChgOpt} height={300} /></div>
        <div className="nt-chart-box"><div className="nt-chart-title">ETF 规模排行</div><EChart option={sizeOpt} height={300} /></div>
      </div>

      <div className="nt-table-wrap">
        <table className="nt-table">
          <thead><tr><th>ETF</th><th>汇金占比</th><th>今日涨跌</th><th>份额(亿份)</th><th>规模(亿)</th><th>换手%</th><th>成交(亿)</th><th>倍数</th></tr></thead>
          <tbody>
            {etf.etfs.map(e => (
              <tr key={e.code} className="nt-clickable" onClick={() => onPickEtf(e.code, e.name)}>
                <td>{e.name}<br/><span className="nt-sub">{e.code} · {e.index}</span></td>
                <td className="num is-up">{e.first_holder_share_pct}%<br/><span className="nt-sub">≈{fmtYi(e.first_holder_value_yi)}</span></td>
                <td className={chgClass(e.change_pct)}>{pct(e.change_pct)}</td>
                <td>{e.shares_yi.toFixed(1)}</td>
                <td>{e.total_value_yi.toFixed(1)}</td>
                <td>{e.turnover_pct.toFixed(2)}</td>
                <td>{(e.amount_wan / 1e4).toFixed(1)}</td>
                <td>{e.change_multiple != null ? e.change_multiple.toFixed(1) + 'x' : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="nt-source-note">份额/规模/行情:腾讯财经实时 · 汇金占比:交易所ETF季报(手工维护参考值)</div>
    </div>
  );
};

// ════════════════ 5. 团队 & 对比 ════════════════
const TeamTab: React.FC<{snap: Snapshot; onPickStock: (c: string, n: string) => void}> = ({snap, onPickStock}) => {
  const {national_team_entities, team_summary, industry_team_matrix, stock_summary} = snap;

  // 团队 × 行业 热力图
  const heatOpt = useMemo(() => {
    const industries = [...new Set(Object.keys(industry_team_matrix).map(k => k.split('|')[0]))];
    const teams = team_summary.map(t => t.team);
    const data: any[] = [];
    let maxV = 0;
    for (let xi = 0; xi < industries.length; xi++) {
      for (let yi = 0; yi < teams.length; yi++) {
        const v = industry_team_matrix[`${industries[xi]}|${teams[yi]}`] || 0;
        data.push([xi, yi, v]);
        if (v > maxV) maxV = v;
      }
    }
    return {
      tooltip: {formatter: (p: any) => `${industries[p.value[0]]} × ${teams[p.value[1]]}: ${p.value[2] ? fmtYi(p.value[2]) : '无'}`},
      grid: {left: 10, right: 20, top: 10, bottom: 60, containLabel: true},
      xAxis: {type: 'category', data: industries, axisLabel: {color: chartTextSecondary, fontSize: 10, rotate: 30}},
      yAxis: {type: 'category', data: teams, axisLabel: {color: chartTextSecondary, fontSize: 11}},
      visualMap: {min: 0, max: maxV || 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, textStyle: {color: chartTextSecondary}, inRange: {color: [...HEAT_SCALE]}},
      series: [{type: 'heatmap', data, label: {show: true, formatter: (p: any) => p.value[2] ? (p.value[2] >= 10000 ? (p.value[2] / 10000).toFixed(1) + '万亿' : p.value[2].toFixed(0) + '亿') : '', color: '#000', fontSize: 9}, emphasis: {itemStyle: {shadowBlur: 10, shadowColor: 'rgba(100,210,255,0.5)'}}}],
    } as any;
  }, [industry_team_matrix, team_summary]);

  // 对比(选中的股票转置对比表)
  const [compareCodes, setCompareCodes] = useState<string[]>([]);
  const toggleCompare = (code: string) => {
    setCompareCodes(prev => prev.includes(code) ? prev.filter(c => c !== code) : prev.length >= 4 ? prev : [...prev, code]);
  };
  const compareStocks = compareCodes.map(c => stock_summary.find(s => s.code === c)).filter(Boolean) as StockSummary[];
  const compareRows = ['现价', '涨跌幅%', 'PE', 'PB', '总市值(亿)', '持仓市值', '52周位置', '量比', '换手率%', '行业', '团队数'];

  return (
    <div className="nt-team">
      <div className="nt-entity-grid">
        {Object.entries(national_team_entities).map(([name, e]) => (
          <div key={name} className={`nt-entity-card ${e.has_holdings ? '' : 'nt-entity-card--empty'}`} style={{borderTopColor: e.color}}>
            <div className="nt-entity-head"><span className="nt-entity-dot" style={{background: e.color}} />{name}<span className="nt-entity-type">({e.type})</span></div>
            {e.has_holdings ? (
              <>
                <div className="nt-entity-val" style={{color: e.color}}>{fmtYi(e.total_holding_value)}</div>
                <div className="nt-entity-desc">{e.desc}</div>
              </>
            ) : (
              <div className="nt-entity-empty">— 未纳入监控 —<br/><span>该团队持仓极少进入前十大流通股东,故无单独数据</span></div>
            )}
          </div>
        ))}
      </div>

      <div className="nt-chart-box">
        <div className="nt-chart-title">国家队团队 × 行业 持仓热力图(市值,黄→深)</div>
        <EChart option={heatOpt} height={360} />
      </div>

      <div className="nt-chart-box">
        <div className="nt-chart-title">🆚 持仓对比(点击下方个股选择,最多4只)</div>
        <div className="nt-compare-picks">
          {stock_summary.slice(0, 30).map(s => (
            <button key={s.code} className={`nt-chip ${compareCodes.includes(s.code) ? 'nt-chip--active' : ''}`} onClick={() => toggleCompare(s.code)}>{s.name}</button>
          ))}
        </div>
        {compareStocks.length > 0 && (
          <table className="nt-table nt-compare-table">
            <thead><tr><th>指标</th>{compareStocks.map(s => <th key={s.code}>{s.name}<br/><span className="nt-sub">{s.code}</span></th>)}</tr></thead>
            <tbody>
              {compareRows.map(row => (
                <tr key={row}>
                  <td className="nt-compare-label">{row}</td>
                  {compareStocks.map(s => {
                    const val: any = {
                      '现价': s.price.toFixed(2),
                      '涨跌幅%': <span className={chgClass(s.change_pct)}>{pct(s.change_pct)}</span>,
                      'PE': s.pe_ttm > 0 ? s.pe_ttm.toFixed(1) : '-',
                      'PB': s.pb > 0 ? s.pb.toFixed(2) : '-',
                      '总市值(亿)': s.mcap_yi.toFixed(0),
                      '持仓市值': fmtYi(s.total_holding_value),
                      '52周位置': s.week_52_position.toFixed(0),
                      '量比': s.volume_ratio.toFixed(2),
                      '换手率%': s.turnover_pct.toFixed(2),
                      '行业': s.industry,
                      '团队数': s.holders.length,
                    }[row];
                    return <td key={s.code} className="nt-clickable" onClick={() => onPickStock(s.code, s.name)}>{val}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

// ════════════════ 入口 ════════════════
// 持仓全景:顶层 Tab,内部 4 个子视图(总览/明细/估值/团队),共用一份 snapshot + 个股弹窗。
export const NationalTeamLive: React.FC = () => {
  const {snap, err} = useSnapshot();
  const [sub, setSub] = useState<'overview' | 'detail' | 'valuation' | 'team'>('overview');
  const [stockModal, setStockModal] = useState<{code: string; name: string} | null>(null);

  if (err) return <StateView state="error" text={err} />;
  if (!snap) return <StateView state="loading" />;
  const pickStock = (code: string, name: string) => setStockModal({code, name});

  const SUBS: {key: typeof sub; label: string}[] = [
    {key: 'overview', label: '总览'},
    {key: 'detail', label: '持仓明细'},
    {key: 'valuation', label: '估值分析'},
    {key: 'team', label: '团队对比'},
  ];

  return (
    <div>
      <div className="nt-subtabs">
        <Tabs
          active={sub}
          onChange={(k) => setSub(k as typeof sub)}
          tabs={SUBS.map(s => ({key: s.key, label: s.label}))}
        />
      </div>
      {sub === 'overview' && <OverviewTab snap={snap} onPickStock={pickStock} />}
      {sub === 'detail' && <HoldingsDetailTab snap={snap} onPickStock={pickStock} />}
      {sub === 'valuation' && <ValuationTab snap={snap} onPickStock={pickStock} />}
      {sub === 'team' && <TeamTab snap={snap} onPickStock={pickStock} />}
      {stockModal && <StockModal code={stockModal.code} name={stockModal.name} onClose={() => setStockModal(null)} />}
    </div>
  );
};

// ETF 动向:独立顶层 Tab。
export const NationalTeamEtf: React.FC = () => {
  const [etfModal, setEtfModal] = useState<{code: string; name: string} | null>(null);
  return (
    <>
      <EtfTab onPickEtf={(c, n) => setEtfModal({code: c, name: n})} />
      {etfModal && <StockModal code={etfModal.code} name={etfModal.name} onClose={() => setEtfModal(null)} />}
    </>
  );
};

export default NationalTeamLive;
