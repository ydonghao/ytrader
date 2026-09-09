/**
 * DcfPanel — DCF 内在价值 + 安全边际面板（Financial 页 Tab）。
 *
 * 价值投资绝对估值锚：调假设（增长率/折现率/永续/年数）→
 * 内在价值 vs 当前市值 → 安全边际（>0 低估，<0 高估）。
 */
import {useEffect, useState} from 'react';
import {BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine, LabelList} from 'recharts';
import {getApiBase} from '../lib/api';
import {useDcf} from '../hooks/useDcf';
import './DcfPanel.css';

const API_BASE = getApiBase();

function fmtYi(v: number | null) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v / 1e8).toFixed(2) + ' 亿';
}

function fmtPct(v: number | null) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
}

export function DcfPanel({symbol}: {symbol: string}) {
  const [growthRate, setGrowthRate] = useState(0.08);
  const [terminalGrowth, setTerminalGrowth] = useState(0.03);
  const [wacc, setWacc] = useState(0.09);
  const [years, setYears] = useState(10);

  const {data, loading, error} = useDcf(symbol, {
    growthRate,
    terminalGrowth,
    wacc,
    projectionYears: years,
  });

  const mos = data?.margin_of_safety;
  const mosColor =
    mos == null ? '#8b949e' : mos > 0.25 ? '#3fb950' : mos > 0 ? '#d29922' : '#f85149';

  // annual_fallback = 缺去年同期数据退回年报口径，标签如实标注
  const fcfLabel = data?.fcf_method === 'annual_fallback'
    ? '基础 FCF(上年报)' : '基础 FCF(TTM)';

  // 增长率敏感性：固定一组 g，看内在价值如何随增长假设变化
  const [sensitivity, setSensitivity] = useState<{g: number; intrinsic: number | null}[]>([]);
  useEffect(() => {
    if (!symbol) { setSensitivity([]); return; }
    let cancelled = false;
    const gs = [0, 0.03, 0.06, 0.09, 0.12, 0.15, 0.18, 0.21];
    const base = new URLSearchParams();
    base.set('terminal_growth', String(terminalGrowth));
    base.set('wacc', String(wacc));
    base.set('projection_years', String(years));
    Promise.all(gs.map(async (g) => {
      try {
        const r = await fetch(`${API_BASE}/financial/dcf/${symbol}?growth_rate=${g}&${base.toString()}`);
        const j = await r.json();
        return {g, intrinsic: j.code === 0 ? (j.data?.intrinsic_value ?? null) : null};
      } catch {
        return {g, intrinsic: null};
      }
    })).then((rows) => { if (!cancelled) setSensitivity(rows); });
    return () => { cancelled = true; };
  }, [symbol, wacc, terminalGrowth, years]);

  // 多情景对比：乐观(g=0.15,wacc=0.07) / 悲观(g=0.03,wacc=0.11)，中性=当前假设
  const [scenarios, setScenarios] = useState<{pessimistic: number | null; optimistic: number | null}>({pessimistic: null, optimistic: null});
  useEffect(() => {
    if (!symbol) { setScenarios({pessimistic: null, optimistic: null}); return; }
    let cancelled = false;
    const cases = [
      {key: 'optimistic', g: 0.15, wacc: 0.07},
      {key: 'pessimistic', g: 0.03, wacc: 0.11},
    ];
    Promise.all(cases.map(async (c) => {
      try {
        const r = await fetch(`${API_BASE}/financial/dcf/${symbol}?growth_rate=${c.g}&wacc=${c.wacc}&terminal_growth=${terminalGrowth}&projection_years=${years}`);
        const j = await r.json();
        return {key: c.key, val: j.code === 0 ? (j.data?.intrinsic_value ?? null) : null};
      } catch {
        return {key: c.key, val: null};
      }
    })).then((rows) => {
      if (cancelled) return;
      const out: {pessimistic: number | null; optimistic: number | null} = {pessimistic: null, optimistic: null};
      rows.forEach((r) => { out[r.key as 'pessimistic' | 'optimistic'] = r.val; });
      setScenarios(out);
    });
    return () => { cancelled = true; };
  }, [symbol, terminalGrowth, years]);

  const [copied, setCopied] = useState(false);
  const copySummary = () => {
    if (!data) return;
    const a = data.assumptions;
    const text =
      `${symbol} DCF 估值\n` +
      `内在价值: ${fmtYi(data.intrinsic_value)}\n` +
      `当前市值: ${fmtYi(data.market_value)}\n` +
      `安全边际: ${fmtPct(data.margin_of_safety)}\n` +
      `基础FCF: ${fmtYi(data.fcf_base)}\n` +
      `假设: g=${(a.growth_rate * 100).toFixed(0)}%, WACC=${(a.wacc * 100).toFixed(0)}%, 永续=${(a.terminal_growth * 100).toFixed(0)}%, ${a.projection_years}年`;
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const exportReport = () => {
    if (!data) return;
    const a = data.assumptions;
    const row = (label: string, v: string) =>
      `<tr><td style="padding:6px 12px;color:#666">${label}</td><td style="padding:6px 12px;font-weight:600">${v}</td></tr>`;
    const html =
      `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${symbol} DCF 报告</title></head>` +
      `<body style="font-family:-apple-system,sans-serif;max-width:600px;margin:40px auto;color:#222">` +
      `<h2>${symbol} DCF 估值报告</h2>` +
      `<table style="border-collapse:collapse;border:1px solid #ddd;width:100%">` +
      row('内在价值', fmtYi(data.intrinsic_value)) +
      row('当前市值', fmtYi(data.market_value)) +
      row('安全边际', fmtPct(data.margin_of_safety)) +
      row(fcfLabel, fmtYi(data.fcf_base)) +
      row('财报报告期', data.report_date || '—') +
      row('增长率 g', `${(a.growth_rate * 100).toFixed(0)}%`) +
      row('折现率 WACC', `${(a.wacc * 100).toFixed(0)}%`) +
      row('永续增长率', `${(a.terminal_growth * 100).toFixed(0)}%`) +
      row('预测年数', `${a.projection_years} 年`) +
      `</table>` +
      `<p style="color:#999;font-size:12px;margin-top:16px">生成于 ${new Date().toLocaleString('zh-CN')} · 浏览器打印可另存 PDF</p>` +
      `</body></html>`;
    const blob = new Blob([html], {type: 'text/html'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${symbol}_DCF报告.html`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="dcf-panel">
      <div className="dcf-panel__assumptions">
        <div className="dcf-panel__title-row">
          <h3 className="dcf-panel__title">DCF 估值假设（按公司实际自行调整）</h3>
          {data && (
            <span className="dcf-title-actions">
              <button type="button" className="dcf-copy-btn" onClick={copySummary}>
                {copied ? '✓ 已复制' : '复制摘要'}
              </button>
              <button type="button" className="dcf-copy-btn" onClick={exportReport}>
                导出报告
              </button>
            </span>
          )}
        </div>
        <div className="dcf-assump">
          <label>
            增长率 g
            <input type="number" step="0.01" value={growthRate}
              onChange={(e) => setGrowthRate(+e.target.value)} />
          </label>
          <label>
            折现率 WACC
            <input type="number" step="0.01" value={wacc}
              onChange={(e) => setWacc(+e.target.value)} />
          </label>
          <label>
            永续 g
            <input type="number" step="0.005" value={terminalGrowth}
              onChange={(e) => setTerminalGrowth(+e.target.value)} />
          </label>
          <label>
            预测年数
            <input type="number" step="1" value={years}
              onChange={(e) => setYears(+e.target.value)} />
          </label>
        </div>
      </div>

      {loading && <div className="dcf-panel__loading">计算中…</div>}
      {error && <div className="dcf-panel__error">❌ {error}</div>}
      {data && !loading && data.fcf_base == null && (
        <div className="dcf-panel__hint">
          ⚠️ 暂无自由现金流数据（<code>free_cash_flow</code> 为本次新增字段）。
          请运行 <code>python -m src.domain.market.sync.jobs.fundamentals --only all</code> 回填后再算 DCF。
        </div>
      )}
      {data && !loading && (
        <div className="dcf-panel__result">
          <div className="dcf-mos" style={{color: mosColor}}>
            <div className="dcf-mos__label">安全边际</div>
            <div className="dcf-mos__value">{fmtPct(mos)}</div>
          </div>
          <div className="dcf-vals">
            <div className="dcf-val">
              <span>内在价值</span>
              <b>{fmtYi(data.intrinsic_value)}</b>
            </div>
            <div className="dcf-val">
              <span>当前市值</span>
              <b>{fmtYi(data.market_value)}</b>
            </div>
            <div className="dcf-val">
              <span>{fcfLabel}</span>
              <b>{fmtYi(data.fcf_base)}</b>
            </div>
            <div className="dcf-val">
              <span>财报报告期</span>
              <b>{data.report_date || '—'}</b>
            </div>
          </div>
        </div>
      )}
      {data && data.intrinsic_value != null && data.market_value != null && (
        <div className="dcf-chart">
          <div className="dcf-chart__title">内在价值 vs 当前市值（亿）</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart
              data={[
                {name: '当前市值', value: (data.market_value ?? 0) / 1e8},
                {name: '内在价值', value: (data.intrinsic_value ?? 0) / 1e8},
              ]}
            >
              <XAxis dataKey="name" stroke="#8b949e" fontSize={12} />
              <YAxis stroke="#8b949e" fontSize={11} />
              <Tooltip
                contentStyle={{background: '#161b22', border: '1px solid #30363d', color: '#e6edf3'}}
                formatter={(v: number) => [`${v.toFixed(1)} 亿`, '']}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                <Cell fill="#8b949e" />
                <Cell fill={mosColor} />
                <LabelList dataKey="value" position="top" formatter={(v: any) => (v == null ? '' : `${Number(v).toFixed(0)} 亿`)} style={{fill: '#adbac7', fontSize: 11}} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {sensitivity.some((s) => s.intrinsic != null) && (
        <div className="dcf-chart">
          <div className="dcf-chart__title">增长率敏感性（不同 g 下的内在价值，亿）</div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart
              data={sensitivity.map((s) => ({
                g: s.g,
                intrinsic: s.intrinsic != null ? s.intrinsic / 1e8 : null,
              }))}
            >
              <XAxis
                dataKey="g"
                type="number"
                domain={[0, Math.max(0.25, growthRate)]}
                tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                stroke="#8b949e"
                fontSize={11}
              />
              <YAxis stroke="#8b949e" fontSize={11} />
              <Tooltip
                contentStyle={{background: '#161b22', border: '1px solid #30363d', color: '#e6edf3'}}
                formatter={(v: any) => (v == null ? ['—', '内在价值'] : [`${Number(v).toFixed(1)} 亿`, '内在价值'])}
                labelFormatter={(v: number) => `增长率 ${Math.round(v * 100)}%`}
              />
              <ReferenceLine
                x={growthRate}
                stroke="#f85149"
                strokeDasharray="3 3"
                strokeOpacity={0.7}
                label={{value: '当前', fontSize: 10, fill: '#f85149', position: 'insideTopLeft'}}
              />
              <Line
                type="monotone"
                dataKey="intrinsic"
                stroke="#58a6ff"
                strokeWidth={2}
                dot={{r: 3, fill: '#58a6ff'}}
                activeDot={{r: 6, fill: '#58a6ff', stroke: '#fff', strokeWidth: 2}}
                connectNulls
                name="内在价值"
              >
                <LabelList
                  dataKey="intrinsic"
                  position="top"
                  offset={8}
                  formatter={(v: any) => (v == null ? '' : `${Number(v).toFixed(0)}`)}
                  style={{fill: '#8b949e', fontSize: 10}}
                />
              </Line>
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {(data?.intrinsic_value != null || scenarios.optimistic != null || scenarios.pessimistic != null) && data?.market_value != null && (
        <div className="dcf-chart">
          <div className="dcf-chart__title">情景对比（悲观/中性/乐观 内在价值 vs 当前市值，亿）</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={[
                {name: '悲观', value: scenarios.pessimistic != null ? scenarios.pessimistic / 1e8 : null},
                {name: '中性', value: data?.intrinsic_value != null ? data.intrinsic_value / 1e8 : null},
                {name: '乐观', value: scenarios.optimistic != null ? scenarios.optimistic / 1e8 : null},
              ]}
            >
              <XAxis dataKey="name" stroke="#8b949e" fontSize={11} />
              <YAxis stroke="#8b949e" fontSize={11} />
              <Tooltip
                contentStyle={{background: '#161b22', border: '1px solid #30363d', color: '#e6edf3'}}
                formatter={(v: any) => (v == null ? ['—', '内在价值'] : [`${Number(v).toFixed(1)} 亿`, '内在价值'])}
              />
              <ReferenceLine
                y={(data?.market_value ?? 0) / 1e8}
                stroke="#8b949e"
                strokeDasharray="4 4"
                label={{value: '市值', fontSize: 10, fill: '#8b949e', position: 'right'}}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                <Cell fill="#f85149" />
                <Cell fill="#d29922" />
                <Cell fill="#3fb950" />
                <LabelList dataKey="value" position="top" formatter={(v: any) => (v == null ? '' : `${Number(v).toFixed(0)}`)} style={{fill: '#8b949e', fontSize: 10}} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {data?.monte_carlo && (
        <div className="dcf-chart">
          <div className="dcf-chart__title">蒙特卡洛估值分布（{data.monte_carlo.sample_size} 次模拟，g/WACC 正态采样）</div>
          <div style={{display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, color: '#8b949e', marginBottom: 4}}>
            <span>均值 <b style={{color: '#e6edf3'}}>{fmtYi(data.monte_carlo.mean)}</b></span>
            <span>标准差 <b style={{color: '#e6edf3'}}>{fmtYi(data.monte_carlo.std)}</b></span>
            <span>变异系数{' '}
              <b style={{color: data.monte_carlo.cv != null && data.monte_carlo.cv < 0.3 ? '#3fb950' : data.monte_carlo.cv != null && data.monte_carlo.cv < 0.5 ? '#d29922' : '#f85149'}}>
                {data.monte_carlo.cv != null ? (data.monte_carlo.cv * 100).toFixed(1) + '%' : '—'}
              </b>
            </span>
          </div>
          <div style={{fontSize: 11, color: '#6e7681', marginBottom: 8}}>
            95% 置信区间：{fmtYi(data.monte_carlo.p5)} ~ {fmtYi(data.monte_carlo.p95)}
            {data.market_value != null && data.market_value < data.monte_carlo.p5 ? ' · 当前市值低于 P5（极大概率低估）' : ''}
          </div>
          <ResponsiveContainer width="100%" height={140}>
            <BarChart data={data.monte_carlo.histogram}>
              <XAxis dataKey="bin_start" tickFormatter={(v: number) => (v / 1e8).toFixed(0)} stroke="#8b949e" fontSize={9} />
              <YAxis stroke="#8b949e" fontSize={10} />
              <Tooltip
                contentStyle={{background: '#161b22', border: '1px solid #30363d', color: '#e6edf3'}}
                labelFormatter={(v: number) => `~${(v / 1e8).toFixed(0)}亿`}
                formatter={(v: any) => [`${v} 次`, '频数']}
              />
              <Bar dataKey="count" fill="#58a6ff" opacity={0.6} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {data && data.note && (
        <div className="dcf-panel__note">{data.note}</div>
      )}
      {!data && !loading && !error && (
        <div className="dcf-panel__empty">输入股票代码查看 DCF 估值</div>
      )}
    </div>
  );
}
