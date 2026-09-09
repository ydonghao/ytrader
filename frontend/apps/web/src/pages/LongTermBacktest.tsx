/**
 * 长期投资实验室 — Long-Term Backtest Lab
 * 路径：/lt-backtest
 *
 * 7 种经典长期投资算法的量化回测：双动量 / 均线趋势 / 全天候 / 估值定投 /
 * 神奇公式 / F-Score 价值 / 红利。多标的组合、定期调仓、对比基准。
 *
 * 面向想从做T升级到长期投资的人：用历史数据亲眼看每个门派怎么赚钱、
 * 风险多大、跑赢/跑输基准多少。
 */
import React, {useState, useEffect} from 'react';
import {
  LineChart, Line, ComposedChart, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import {getApiBase} from '../lib/api';
import {Button, PageHeader, StateView, Tabs} from '../components/ui';
import {BacktestHistory} from './lt-backtest/BacktestHistory';
import {TTrading} from './TTrading';
import {EfficientFrontier} from './lt-backtest/EfficientFrontier';
import {WalkForward} from './lt-backtest/WalkForward';
import './LongTermBacktest.css';
import { CHART_COLORS, axisProps, gridProps, tooltipProps } from '../lib/chartTheme';

const API = `${getApiBase()}/lt-backtest`;

type TabKey = 'lab' | 'frontier' | 'walkforward' | 'history';

// ── 类型 ──────────────────────────────────────────────────────────────────────
interface ParamSpec {
  key: string;
  label: string;
  type: string;
  default: number | string;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  options?: string[];
  help: string;
}
interface AlgoMeta {
  name: string;
  display_name: string;
  one_liner: string;
  description: string;
  market_fit: string;
  family: string;
  pros: string[];
  risks: string[];
  rebalance_freq: string;
  needs_fundamentals: boolean;
  params: ParamSpec[];
}
interface LTTrade {
  timestamp: string;
  symbol: string;
  action: string;
  shares: number;
  price: number;
  amount: number;
  commission: number;
  stamp_duty: number;
  total_cost: number;
  reason: string;
}
interface EquityPoint {
  date: string;
  equity: number;
  benchmark?: number | null;
}
interface BacktestResult {
  strategy: string;
  symbols: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_equity: number;
  total_return_pct: number;
  cagr: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  max_dd_duration: number;
  volatility: number;
  win_rate: number;
  rebalance_count: number;
  total_trades: number;
  benchmark_return_pct: number;
  benchmark_cagr: number;
  alpha: number;
  beta: number;
  equity_curve: EquityPoint[];
  rebalances: Array<{date: string; reason: string; target_weights: Record<string, number>; trades: number}>;
  trades: LTTrade[];
}

// ── 工具 ──────────────────────────────────────────────────────────────────────
const fmtMoney = (n: number) => n.toLocaleString('zh-CN', {minimumFractionDigits: 0, maximumFractionDigits: 0});
const fmtPct = (n: number, sign = true) => (sign && n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const fmtNum = (n: number, d = 2) => n.toLocaleString('zh-CN', {minimumFractionDigits: d, maximumFractionDigits: d});
const colorByVal = (n: number) => (n >= 0 ? 'pos' : 'neg');

// 门派标签颜色
const FAMILY_COLORS: Record<string, string> = {
  '动量': 'var(--color-accent)',
  '趋势': '#5e5ce6',
  '资产配置': 'var(--color-success)',
  '定投': '#ffd60a',
  '价值': 'var(--color-warning)',
};

// ── 主组件 ────────────────────────────────────────────────────────────────────
export const LongTermBacktest: React.FC = () => {
  // 顶层 Tab：长期回测 / 做T实验室（?tab=ttrading 直达做T）
  const [topTab, setTopTab] = useState<'lt' | 'ttrading'>(() =>
    new URLSearchParams(window.location.search).get('tab') === 'ttrading' ? 'ttrading' : 'lt');
  const [tab, setTab] = useState<TabKey>('lab');
  const [algos, setAlgos] = useState<AlgoMeta[]>([]);
  const [selectedAlgo, setSelectedAlgo] = useState('dual_momentum');
  const [expandedAlgo, setExpandedAlgo] = useState<string | null>(null);

  // 公共参数
  const [symbols, setSymbols] = useState('sh000300');
  const [benchmark, setBenchmark] = useState('sh000300');
  const [startDate, setStartDate] = useState('2020-01-01');
  const [endDate, setEndDate] = useState('2025-12-31');
  const [initialCapital, setInitialCapital] = useState(1000000);

  // 算法参数（动态）
  const [algoParams, setAlgoParams] = useState<Record<string, any>>({});

  // 运行状态
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);

  // 加载算法列表
  useEffect(() => {
    fetch(`${API}/algorithms`)
      .then(r => r.json())
      .then(d => { if (d.code === 0) setAlgos(d.data); })
      .catch(() => {});
  }, []);

  // 选中算法变化时，重置算法参数为默认值
  useEffect(() => {
    const algo = algos.find(a => a.name === selectedAlgo);
    if (!algo) return;
    const defaults: Record<string, any> = {};
    for (const p of algo.params) {
      defaults[p.key] = p.default;
    }
    setAlgoParams(defaults);
  }, [selectedAlgo, algos]);

  const currentAlgo = algos.find(a => a.name === selectedAlgo);

  // 切换算法时，按门派预设默认 symbols
  function selectAlgo(name: string) {
    setSelectedAlgo(name);
    const algo = algos.find(a => a.name === name);
    if (!algo) return;
    // 各门派合理的默认池
    if (algo.family === '资产配置') {
      setSymbols('sh510300,sh511010,sh511260,sh518880,sh510980');
    } else if (algo.family === '动量' || algo.name === 'dual_momentum') {
      setSymbols('sh000300,sh511010');
    } else if (algo.family === '价值') {
      setSymbols('sh600000,sz000001,sh600036,sz000002,sh600276,sh600519');
    } else {
      setSymbols('sh000300');
    }
  }

  async function runBacktest() {
    setRunning(true);
    setError(null);
    setResult(null);
    setSavedId(null);
    try {
      const res = await fetch(`${API}/backtest`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          strategy: selectedAlgo,
          symbols: symbols.split(',').map(s => s.trim()).filter(Boolean),
          benchmark,
          start_date: startDate,
          end_date: endDate,
          initial_capital: initialCapital,
          params: algoParams,
        }),
      });
      const d = await res.json();
      if (d.code !== 0) throw new Error(d.msg || '回测失败');
      setResult(d.data);
      if (d.data?.result_id) setSavedId(d.data.result_id);
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="lt-backtest-lab">
      <div className="lt-backtest-lab__tabs">
        <button
          className={`lab-tab${topTab === 'lt' ? ' lab-tab--active' : ''}`}
          onClick={() => setTopTab('lt')}>
          长期回测
        </button>
        <button
          className={`lab-tab${topTab === 'ttrading' ? ' lab-tab--active' : ''}`}
          onClick={() => setTopTab('ttrading')}>
          做T实验室
        </button>
      </div>
      {topTab === 'lt' ? (
    <div className="lt-backtest">
      <PageHeader
        title="长期回测实验室"
        subtitle="经典长期投资算法的量化回测：动量 / 趋势 / 资产配置 / 定投 / 价值 + 现代组合优化（风险平价 / 最小方差 / 均值-方差）。回测结果自动保存，可历史对比。"
      />

      {/* ── Tab 导航 ── */}
      <Tabs
        tabs={[
          {key: 'lab', label: '策略实验室'},
          {key: 'frontier', label: '有效前沿'},
          {key: 'walkforward', label: 'Walk-Forward'},
          {key: 'history', label: '回测历史/对比'},
        ]}
        active={tab}
        onChange={(k) => setTab(k as TabKey)}
        className="lt-backtest__tabs"
      />

      {/* ── 有效前沿 Tab ── */}
      {tab === 'frontier' && <EfficientFrontier />}

      {/* ── Walk-Forward Tab ── */}
      {tab === 'walkforward' && <WalkForward />}

      {/* ── 回测历史 Tab ── */}
      {tab === 'history' && <BacktestHistory />}

      {/* ── 策略实验室 Tab ── */}
      {tab === 'lab' && (
        <>
      {/* ── ① 策略门派卡片 ── */}
      <div className="lt-backtest__algo-grid">
        {algos.map(algo => (
          <div
            key={algo.name}
            className={`algo-card${selectedAlgo === algo.name ? ' algo-card--active' : ''}`}
            onClick={() => selectAlgo(algo.name)}
          >
            <div className="algo-card__head">
              <h3 className="algo-card__name">{algo.display_name}</h3>
              <span
                className="algo-card__family"
                style={{background: FAMILY_COLORS[algo.family] || '#666'}}
              >
                {algo.family}
              </span>
            </div>
            <p className="algo-card__one-liner">{algo.one_liner}</p>
            {algo.needs_fundamentals && (
              <span className="algo-card__tag">需基本面数据</span>
            )}
            <button
              className="algo-card__expand"
              onClick={(e) => {
                e.stopPropagation();
                setExpandedAlgo(expandedAlgo === algo.name ? null : algo.name);
              }}
            >
              {expandedAlgo === algo.name ? '收起 ▴' : '展开看原理 ▾'}
            </button>
            {expandedAlgo === algo.name && (
              <div className="algo-card__detail">
                <p>{algo.description}</p>
                <p><span className="label">适用场景：</span>{algo.market_fit}</p>
                <p><span className="label">调仓频率：</span>{algo.rebalance_freq}</p>
                <p><span className="label">优点：</span></p>
                <ul className="algo-card__pros">
                  {algo.pros.map((p, i) => <li key={i}>{p}</li>)}
                </ul>
                <p><span className="label">风险：</span></p>
                <ul className="algo-card__risks">
                  {algo.risks.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ── ② 参数表单 ── */}
      <div className="lt-backtest__form">
        <h3 className="lt-backtest__form-title">
          回测参数{currentAlgo ? ` · ${currentAlgo.display_name}` : ''}
        </h3>
        <div className="lt-backtest__form-grid">
          <div className="lt-backtest__field">
            <label>股票池（逗号分隔）</label>
            <input
              value={symbols}
              onChange={e => setSymbols(e.target.value)}
              placeholder="sh000300,sh510300"
            />
            <span className="lt-backtest__field-help">带 sh/sz 前缀；价值类需多只</span>
          </div>
          <div className="lt-backtest__field">
            <label>基准指数</label>
            <input
              value={benchmark}
              onChange={e => setBenchmark(e.target.value)}
              placeholder="sh000300"
            />
          </div>
          <div className="lt-backtest__field">
            <label>开始日期</label>
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
          </div>
          <div className="lt-backtest__field">
            <label>结束日期</label>
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} />
          </div>
          <div className="lt-backtest__field">
            <label>初始资金（元）</label>
            <input
              type="number"
              value={initialCapital}
              onChange={e => setInitialCapital(+e.target.value)}
              step={100000}
              min={10000}
            />
          </div>

          {/* 算法特定参数 */}
          {currentAlgo?.params.map(p => (
            <div className="lt-backtest__field" key={p.key}>
              <label>{p.label}{p.unit ? `（${p.unit}）` : ''}</label>
              {p.type === 'select' && p.options ? (
                <select
                  value={algoParams[p.key] ?? p.default}
                  onChange={e => setAlgoParams({...algoParams, [p.key]: e.target.value})}
                >
                  {p.options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              ) : (
                <input
                  type="number"
                  value={algoParams[p.key] ?? p.default}
                  min={p.min}
                  max={p.max}
                  step={p.step}
                  onChange={e => setAlgoParams({...algoParams, [p.key]: +e.target.value})}
                />
              )}
              <span className="lt-backtest__field-help">{p.help}</span>
            </div>
          ))}
        </div>

        <div className="lt-backtest__actions">
          <Button variant="primary" loading={running} onClick={runBacktest}>
            {running ? '回测中…' : '运行长期回测'}
          </Button>
          {error && <span className="lt-backtest__error">{error}</span>}
        </div>
      </div>

      {/* ── ③ 结果区 ── */}
      {result && (
        <div className="lt-backtest__result">
          {/* 关键指标卡片 */}
          <div className="lt-backtest__metrics">
            <MetricCard
              label="总收益率"
              value={fmtPct(result.total_return_pct)}
              sub={`年化 ${fmtPct(result.cagr)}`}
              tone={colorByVal(result.total_return_pct)}
            />
            <MetricCard
              label="最大回撤"
              value={`-${fmtNum(result.max_drawdown, 1)}%`}
              sub={`持续 ${result.max_dd_duration} 日`}
              tone="neg"
            />
            <MetricCard
              label="夏普 / 索提诺"
              value={`${fmtNum(result.sharpe_ratio, 2)} / ${fmtNum(result.sortino_ratio, 2)}`}
              sub={`波动率 ${fmtNum(result.volatility, 1)}%`}
              tone={result.sharpe_ratio >= 0 ? 'pos' : 'neg'}
            />
            <MetricCard
              label="vs 基准"
              value={`${fmtPct(result.alpha / 100, true)}`}
              sub={`基准 ${fmtPct(result.benchmark_return_pct)} · β ${fmtNum(result.beta, 2)}`}
              tone={colorByVal(result.alpha)}
            />
            <MetricCard
              label="调仓 / 交易"
              value={`${result.rebalance_count}`}
              sub={`${result.total_trades} 笔交易`}
              tone="neutral"
            />
          </div>

          {/* 权益曲线 vs 基准 */}
          <div className="lt-backtest__section">
            <h3 className="lt-backtest__section-title">权益曲线 vs 基准</h3>
            <p className="lt-backtest__section-desc">
              策略（蓝）对比基准买入持有（灰）。{result.symbols.length > 1 ? `组合：${result.symbols.join(', ')}` : result.symbols[0]}
            </p>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={result.equity_curve}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="date" {...axisProps} minTickGap={60} />
                <YAxis
                  {...axisProps}
                  tickFormatter={(v: number) => (v / 10000).toFixed(0) + '万'}
                  domain={['auto', 'auto']}
                />
                <Tooltip
                  {...tooltipProps}
                  formatter={(v: number, name: string) => [fmtMoney(v), name === 'equity' ? '策略' : '基准']}
                />
                <Legend formatter={(v) => v === 'equity' ? '策略' : '基准'} />
                <Line type="monotone" dataKey="equity" stroke={CHART_COLORS[0]} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="benchmark" stroke={chartTextTertiary} strokeWidth={1.5} dot={false} strokeDasharray="4 4" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* 调仓明细 */}
          {result.rebalances.length > 0 && (
            <div className="lt-backtest__section">
              <h3 className="lt-backtest__section-title">调仓明细</h3>
              <p className="lt-backtest__section-desc">最近 {Math.min(result.rebalances.length, 30)} 次调仓（共 {result.rebalance_count} 次）</p>
              <div className="lt-backtest__table-wrap">
                <table className="lt-backtest__table">
                  <thead>
                    <tr>
                      <th>日期</th>
                      <th>原因</th>
                      <th>目标权重</th>
                      <th>交易笔数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.rebalances.slice(-30).reverse().map((r, i) => (
                      <tr key={`${r.date}-${i}`}>
                        <td>{r.date}</td>
                        <td style={{fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)'}}>{r.reason}</td>
                        <td className="mono">
                          {Object.entries(r.target_weights).map(([s, w]) => (
                            <span key={s} className="weight-chip">{s} {fmtNum(w * 100, 0)}%</span>
                          ))}
                        </td>
                        <td>{r.trades}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 交易明细 */}
          {result.trades.length > 0 && (
            <div className="lt-backtest__section">
              <h3 className="lt-backtest__section-title">交易明细</h3>
              <p className="lt-backtest__section-desc">最近 {Math.min(result.trades.length, 50)} 笔（共 {result.total_trades} 笔）</p>
              <div className="lt-backtest__table-wrap">
                <table className="lt-backtest__table">
                  <thead>
                    <tr>
                      <th>日期</th>
                      <th>标的</th>
                      <th>方向</th>
                      <th>股数</th>
                      <th>价格</th>
                      <th>金额</th>
                      <th>成本</th>
                      <th>原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.slice(-50).reverse().map((t, i) => (
                      <tr key={`${t.timestamp}-${t.symbol}-${i}`}>
                        <td>{t.timestamp}</td>
                        <td className="mono">{t.symbol}</td>
                        <td className={t.action === 'BUY' ? 'txt-buy' : 'txt-sell'}>
                          {t.action === 'BUY' ? '买入' : '卖出'}
                        </td>
                        <td className="num">{t.shares}</td>
                        <td className="num">{fmtNum(t.price, 3)}</td>
                        <td className="num">{fmtMoney(t.amount)}</td>
                        <td className="num neg">{fmtNum(t.total_cost, 2)}</td>
                        <td style={{fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)'}}>{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {!result && !running && !error && (
        <StateView state="empty" text="选择一种长期投资策略，填好参数后点击「运行长期回测」" />
      )}

      {savedId && (
        <div className="lt-backtest__saved-note">
          已保存到回测历史（#{savedId}）。
          <button className="lt-backtest__saved-link" onClick={() => setTab('history')}>
            去历史对比 →
          </button>
        </div>
      )}
      </>
      )}
    </div>
      ) : (
        <TTrading />
      )}
    </div>
  );
};

// ── 子组件：指标卡 ────────────────────────────────────────────────────────────
const MetricCard: React.FC<{
  label: string;
  value: string;
  sub: string;
  tone: 'pos' | 'neg' | 'neutral';
}> = ({label, value, sub, tone}) => (
  <div className="metric-card">
    <span className="metric-card__label">{label}</span>
    <span className={`metric-card__value num metric-card__value--${tone}`}>{value}</span>
    <span className="metric-card__sub">{sub}</span>
  </div>
);
