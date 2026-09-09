/**
 * 回测历史 + 对比 — Backtest History & Compare
 * 属于 /lt-backtest 页面的一个 Tab。
 *
 * - 列表：分页 + 筛选（strategy/source），点击行看详情
 * - 对比：多选 → 叠加权益曲线（归一化）+ 指标对比表
 * - 删除单条
 */
import React, {useState, useEffect, useCallback} from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, BarChart, Bar, ReferenceLine, Cell,
} from 'recharts';
import {getApiBase} from '../../lib/api';
import { CHART_COLORS, axisProps, colorDown, colorOrange, colorUp, chartTextTertiary, gridProps, tooltipProps } from '../../lib/chartTheme';
import {Button, StateView} from '../../components/ui';

const API = `${getApiBase()}/lt-backtest`;

interface ResultSummary {
  id: number;
  name: string;
  source: string;
  strategy: string;
  symbols: string[];
  start_date: string;
  end_date: string;
  total_return_pct: number;
  cagr: number;
  sharpe_ratio: number;
  max_drawdown: number;
  volatility: number;
  alpha: number;
  beta: number;
  benchmark_return_pct: number;
  status: string;
  created_at: string;
}

interface ResultDetail extends ResultSummary {
  params: Record<string, any>;
  benchmark: string;
  initial_capital: number;
  final_equity: number;
  sortino_ratio: number;
  max_dd_duration: number;
  win_rate: number;
  rebalance_count: number;
  total_trades: number;
  benchmark_cagr: number;
  equity_curve: Array<{date: string; equity: number; benchmark?: number | null}>;
  rebalances: any[];
  trades: any[];
  final_weights: Record<string, number>;
}

interface CompareResp {
  metrics_table: Array<Record<string, any>>;
  equity_overlay: Array<{
    id: number;
    name: string;
    strategy: string;
    curve: Array<{date: string; nav: number}>;
  }>;
}

const fmtPct = (n: number, sign = true) =>
  (sign && n >= 0 ? '+' : '') + (n ?? 0).toFixed(2) + '%';
const fmtNum = (n: number, d = 2) =>
  (n ?? 0).toLocaleString('zh-CN', {minimumFractionDigits: d, maximumFractionDigits: d});
const colorByVal = (n: number) => (n >= 0 ? 'pos' : 'neg');

const OVERLAY_COLORS = [CHART_COLORS[0], CHART_COLORS[1], colorOrange, '#ffd60a', '#5e5ce6', '#ff375f', '#64d2ff', '#bf5af2'];

const SOURCE_LABEL: Record<string, string> = {
  lt_backtest: '实验室',
  perm_portfolio: '永久组合',
  optimizer: '优化器',
};

export const BacktestHistory: React.FC = () => {
  const [records, setRecords] = useState<ResultSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [size] = useState(15);
  const [fStrategy, setFStrategy] = useState('');
  const [fSource, setFSource] = useState('');
  const [loading, setLoading] = useState(false);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<ResultDetail | null>(null);
  const [compare, setCompare] = useState<CompareResp | null>(null);
  const [attribution, setAttribution] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('page', String(page));
      params.set('size', String(size));
      if (fStrategy) params.set('strategy', fStrategy);
      if (fSource) params.set('source', fSource);
      const res = await fetch(`${API}/results?${params}`);
      const d = await res.json();
      if (d.code === 0) {
        setRecords(d.data.records);
        setTotal(d.data.total);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [page, size, fStrategy, fSource]);

  useEffect(() => { load(); }, [load]);

  async function openDetail(id: number) {
    setBusy(true);
    try {
      const res = await fetch(`${API}/results/${id}`);
      const d = await res.json();
      if (d.code === 0) { setDetail(d.data); setCompare(null); setAttribution(null); }
    } finally { setBusy(false); }
  }

  async function loadAttribution(id: number) {
    setBusy(true);
    try {
      const res = await fetch(`${API}/results/${id}/attribution`, {method: 'POST'});
      const d = await res.json();
      if (d.code === 0) setAttribution(d.data);
    } finally { setBusy(false); }
  }

  function toggleSelect(id: number) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function runCompare() {
    if (selected.size < 2) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/compare`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ids: Array.from(selected)}),
      });
      const d = await res.json();
      if (d.code === 0) { setCompare(d.data); setDetail(null); }
    } finally { setBusy(false); }
  }

  async function removeOne(id: number) {
    if (!confirm('确定删除这条回测记录？')) return;
    await fetch(`${API}/results/${id}`, {method: 'DELETE'});
    setSelected(prev => {
      const next = new Set(prev); next.delete(id); return next;
    });
    if (detail?.id === id) setDetail(null);
    load();
  }

  const totalPages = Math.max(1, Math.ceil(total / size));

  return (
    <div className="bt-history">
      {/* 筛选栏 */}
      <div className="bt-history__filters">
        <select value={fStrategy} onChange={e => { setFStrategy(e.target.value); setPage(1); }}>
          <option value="">全部策略</option>
          <option value="risk_parity">风险平价</option>
          <option value="min_variance">最小方差</option>
          <option value="mvo">均值-方差</option>
          <option value="equal_weight">等权</option>
          <option value="dual_momentum">双动量</option>
          <option value="all_weather">全天候</option>
          <option value="fixed_weight">固定权重</option>
        </select>
        <select value={fSource} onChange={e => { setFSource(e.target.value); setPage(1); }}>
          <option value="">全部来源</option>
          <option value="lt_backtest">实验室</option>
          <option value="perm_portfolio">永久组合</option>
        </select>
        <span className="bt-history__count">共 {total} 条</span>
        <Button
          variant="primary"
          size="sm"
          disabled={selected.size < 2 || busy}
          onClick={runCompare}
        >
          对比选中（{selected.size}）
        </Button>
      </div>

      {/* 列表 */}
      <div className="bt-history__table-wrap">
        <table className="bt-history__table">
          <thead>
            <tr>
              <th></th>
              <th>名称</th>
              <th>策略</th>
              <th>来源</th>
              <th>区间</th>
              <th>总收益</th>
              <th>年化</th>
              <th>夏普</th>
              <th>最大回撤</th>
              <th>创建</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {records.map(r => (
              <tr key={r.id} className={selected.has(r.id) ? 'row-selected' : ''}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(r.id)}
                    onChange={() => toggleSelect(r.id)}
                  />
                </td>
                <td className="bt-history__name" onClick={() => openDetail(r.id)}>
                  {r.name}
                </td>
                <td><span className="bt-history__strat">{r.strategy}</span></td>
                <td><span className="bt-history__src">{SOURCE_LABEL[r.source] || r.source}</span></td>
                <td className="mono" style={{fontSize: 'var(--text-xs)'}}>{r.start_date}~{r.end_date}</td>
                <td className={`num txt-${colorByVal(r.total_return_pct)}`}>{fmtPct(r.total_return_pct)}</td>
                <td className={`num txt-${colorByVal(r.cagr)}`}>{fmtPct(r.cagr)}</td>
                <td className="num">{fmtNum(r.sharpe_ratio, 2)}</td>
                <td className="num neg">-{fmtNum(r.max_drawdown, 1)}%</td>
                <td style={{fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)'}}>
                  {r.created_at?.slice(0, 16).replace('T', ' ')}
                </td>
                <td>
                  <Button variant="danger" size="sm" onClick={() => removeOne(r.id)}>删除</Button>
                </td>
              </tr>
            ))}
            {!loading && records.length === 0 && (
              <tr><td colSpan={11}>
                <StateView state="empty" text="暂无回测历史。去「策略实验室」跑一次回测，结果会自动保存到这里。" />
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      {totalPages > 1 && (
        <div className="bt-history__pager">
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>上一页</button>
          <span>{page} / {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>下一页</button>
        </div>
      )}

      {/* 对比结果 */}
      {compare && (
        <div className="bt-history__panel">
          <h3>对比结果（{compare.metrics_table.length} 条）</h3>
          <Button variant="ghost" size="sm" onClick={() => setCompare(null)}>关闭</Button>
          <div className="bt-history__table-wrap">
            <table className="bt-history__table">
              <thead>
                <tr>
                  <th>名称</th><th>策略</th><th>总收益</th><th>年化</th>
                  <th>夏普</th><th>索提诺</th><th>最大回撤</th><th>波动率</th>
                  <th>α</th><th>β</th><th>基准</th>
                </tr>
              </thead>
              <tbody>
                {compare.metrics_table.map(m => (
                  <tr key={m.id}>
                    <td>{m.name}</td>
                    <td><span className="bt-history__strat">{m.strategy}</span></td>
                    <td className={`num txt-${colorByVal(m.total_return_pct)}`}>{fmtPct(m.total_return_pct)}</td>
                    <td className={`num txt-${colorByVal(m.cagr)}`}>{fmtPct(m.cagr)}</td>
                    <td className="num">{fmtNum(m.sharpe_ratio, 2)}</td>
                    <td className="num">{fmtNum(m.sortino_ratio, 2)}</td>
                    <td className="num neg">-{fmtNum(m.max_drawdown, 1)}%</td>
                    <td className="num">{fmtNum(m.volatility, 1)}%</td>
                    <td className="num">{fmtNum(m.alpha * 100, 2)}%</td>
                    <td className="num">{fmtNum(m.beta, 2)}</td>
                    <td className={`num txt-${colorByVal(m.benchmark_return_pct)}`}>{fmtPct(m.benchmark_return_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h4 style={{marginTop: 16}}>归一化权益曲线（起点=1.0）</h4>
          <ResponsiveContainer width="100%" height={340}>
            <LineChart>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="date" {...axisProps} minTickGap={60}
                type="category" allowDuplicatedCategory={false} />
              <YAxis {...axisProps} />
              <Tooltip {...tooltipProps} />
              <Legend />
              {compare.equity_overlay.map((ov, i) => (
                <Line
                  key={ov.id}
                  data={ov.curve}
                  type="monotone"
                  dataKey="nav"
                  name={ov.name}
                  stroke={OVERLAY_COLORS[i % OVERLAY_COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 单条详情 */}
      {detail && (
        <div className="bt-history__panel">
          <div className="bt-history__panel-head">
            <h3>{detail.name}</h3>
            <Button variant="ghost" size="sm" onClick={() => setDetail(null)}>关闭</Button>
          </div>
          <div className="bt-history__metrics">
            {[
              ['总收益', fmtPct(detail.total_return_pct), colorByVal(detail.total_return_pct)],
              ['年化', fmtPct(detail.cagr), colorByVal(detail.cagr)],
              ['夏普', fmtNum(detail.sharpe_ratio, 2), 'neutral'],
              ['最大回撤', `-${fmtNum(detail.max_drawdown, 1)}%`, 'neg'],
              ['波动率', `${fmtNum(detail.volatility, 1)}%`, 'neutral'],
              ['α / β', `${fmtNum(detail.alpha * 100, 2)}% / ${fmtNum(detail.beta, 2)}`, colorByVal(detail.alpha)],
            ].map(([l, v, t], i) => (
              <div key={i} className="bt-history__metric">
                <span className="bt-history__metric-label">{l}</span>
                <span className={`bt-history__metric-val txt-${t}`}>{v}</span>
              </div>
            ))}
          </div>
          <div className="bt-history__info">
            <span>策略：<b>{detail.strategy}</b></span>
            <span>标的：{detail.symbols.join(', ')}</span>
            <span>区间：{detail.start_date} ~ {detail.end_date}</span>
            <span>调仓 {detail.rebalance_count} 次 · 交易 {detail.total_trades} 笔</span>
            <span>期末权重：
              {Object.entries(detail.final_weights || {}).map(([s, w]) => (
                <span key={s} className="weight-chip">{s} {fmtNum(w * 100, 0)}%</span>
              ))}
            </span>
          </div>
          <h4 style={{marginTop: 16}}>权益曲线 vs 基准</h4>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={detail.equity_curve}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="date" {...axisProps} minTickGap={60} />
              <YAxis {...axisProps} />
              <Tooltip {...tooltipProps} />
              <Legend />
              <Line type="monotone" dataKey="equity" name="策略" stroke={CHART_COLORS[0]} strokeWidth={2} dot={false} />
              {detail.equity_curve[0]?.benchmark != null && (
                <Line type="monotone" dataKey="benchmark" name="基准" stroke={chartTextTertiary} strokeWidth={1.5} dot={false} strokeDasharray="4 4" />
              )}
            </LineChart>
          </ResponsiveContainer>

          {/* 收益归因 */}
          <div className="bt-history__attr-head">
            <h4 style={{marginTop: 16, marginBottom: 0}}>收益归因</h4>
            <Button
              variant="secondary"
              size="sm"
              loading={busy}
              onClick={() => loadAttribution(detail.id)}
            >
              {attribution ? '刷新归因' : '计算收益归因'}
            </Button>
          </div>
          {attribution && (
            <div className="bt-history__attr">
              <p className="bt-history__attr-summary">
                总收益 <b className={attribution.total_return_pct >= 0 ? 'txt-pos' : 'txt-neg'}>
                  {fmtPct(attribution.total_return_pct)}
                </b> · 归因解释 {fmtPct(attribution.total_attributed_pct)}
                （残差 {fmtPct(attribution.residual_pct)}：权重漂移/再平衡/成本）
              </p>
              {/* 逐标的贡献 */}
              <ResponsiveContainer width="100%" height={Math.max(160, (attribution.by_symbol?.length || 0) * 36)}>
                <BarChart data={attribution.by_symbol.map((s: any) => ({
                  symbol: s.symbol, contribution: Number((s.contribution_pct || 0).toFixed(2)),
                }))} layout="vertical">
                  <CartesianGrid {...gridProps} />
                  <XAxis type="number" {...axisProps} unit="%" />
                  <YAxis type="category" dataKey="symbol" {...axisProps} width={80} />
                  <Tooltip {...tooltipProps} />
                  <ReferenceLine x={0} stroke="rgba(255,255,255,0.2)" />
                  <Bar dataKey="contribution" name="收益贡献(%)">
                    {attribution.by_symbol.map((s: any, i: number) => (
                      <Cell key={i} fill={(s.contribution_pct || 0) >= 0 ? colorUp : colorDown} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              {/* 行业聚合 + vs等权 */}
              <div className="bt-history__attr-grid">
                <div>
                  <h5>行业贡献</h5>
                  <table className="bt-history__table">
                    <thead><tr><th>行业</th><th>权重</th><th>贡献</th></tr></thead>
                    <tbody>
                      {attribution.by_sector.map((s: any, i: number) => (
                        <tr key={i}>
                          <td>{s.sector}</td>
                          <td>{fmtNum(s.avg_weight * 100, 1)}%</td>
                          <td className={s.contribution_pct >= 0 ? 'txt-pos' : 'txt-neg'}>
                            {fmtPct(s.contribution_pct)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div>
                  <h5>vs 等权基准</h5>
                  <table className="bt-history__table">
                    <tbody>
                      <tr><td>等权收益</td><td className={attribution.vs_equal_weight.equal_weight_return_pct >= 0 ? 'txt-pos' : 'txt-neg'}>
                        {fmtPct(attribution.vs_equal_weight.equal_weight_return_pct)}</td></tr>
                      <tr><td>策略(归因)</td><td>{fmtPct(attribution.vs_equal_weight.strategy_attributed_pct)}</td></tr>
                      <tr><td>超额</td><td className={attribution.vs_equal_weight.excess_pct >= 0 ? 'txt-pos' : 'txt-neg'}>
                        {fmtPct(attribution.vs_equal_weight.excess_pct)}</td></tr>
                      <tr><td>配置效应</td><td className={attribution.vs_equal_weight.allocation_effect_pct >= 0 ? 'txt-pos' : 'txt-neg'}>
                        {fmtPct(attribution.vs_equal_weight.allocation_effect_pct)}</td></tr>
                    </tbody>
                  </table>
                  <p className="bt-history__attr-note">{attribution.vs_equal_weight.allocation_note}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
