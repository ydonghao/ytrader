/**
 * 做T实验室 — T-Trading Lab
 * 路径：/t-trading
 *
 * 用历史分钟数据，亲眼看 4 种做T算法怎么赚钱、被成本吃掉多少。
 * 面向金融小白：原理卡片 + 收益/成本拆解 + 算法原理。
 */
import React, {useState, useEffect} from 'react';
import {
  BarChart, Bar, LineChart, Line, ComposedChart, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceDot, Cell,
} from 'recharts';
import {getApiBase} from '../lib/api';
import { CHART_COLORS, axisProps, colorDown, colorUp, gridProps, tooltipProps } from '../lib/chartTheme';
import {Button, PageHeader, StateView} from '../components/ui';
import './TTrading.css';

const API = `${getApiBase()}/t-trading`;

// ── 类型 ──────────────────────────────────────────────────────────────────────
interface ParamSpec {
  key: string;
  label: string;
  type: string;
  default: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  help: string;
}
interface AlgoMeta {
  name: string;
  display_name: string;
  one_liner: string;
  description: string;
  market_fit: string;
  pros: string[];
  risks: string[];
  danger: boolean;
  params: ParamSpec[];
}
interface TTrade {
  timestamp: string;
  action: string;
  price: number;
  quantity: number;
  amount: number;
  commission: number;
  stamp_duty: number;
  transfer_fee: number;
  slippage: number;
  total_cost: number;
  reason: string;
}
interface DayResult {
  day: string;
  trades: number;
  gross_pnl: number;
  net_pnl: number;
  cost_total: number;
  close_price: number;
}
interface BacktestResult {
  algorithm: string;
  symbol: string;
  interval: string;
  start_date: string;
  end_date: string;
  base_shares: number;
  base_price: number;
  base_market_value: number;
  total_net_pnl: number;
  total_return_pct: number;
  cost_reduction: number;
  gross_pnl: number;
  total_cost: number;
  cost_breakdown: {commission: number; stamp_duty: number; transfer_fee: number; slippage: number; total: number};
  total_trades: number;
  total_buys: number;
  total_sells: number;
  total_days: number;
  win_days: number;
  win_rate: number;
  daily_results: DayResult[];
  trades: TTrade[];
  price_series: Array<{t: string; price: number; action?: string}>;
}

// ── 工具 ──────────────────────────────────────────────────────────────────────
const fmtMoney = (n: number) => {
  const sign = n >= 0 ? '+' : '';
  return sign + n.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
};
const fmtPct = (n: number) => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const fmtNum = (n: number, d = 2) => n.toLocaleString('zh-CN', {minimumFractionDigits: d, maximumFractionDigits: d});

// ── 主组件 ────────────────────────────────────────────────────────────────────
export const TTrading: React.FC = () => {
  const [algos, setAlgos] = useState<AlgoMeta[]>([]);
  const [selectedAlgo, setSelectedAlgo] = useState('grid');
  const [expandedAlgo, setExpandedAlgo] = useState<string | null>(null);

  // 公共参数
  const [symbol, setSymbol] = useState('sh600000');
  const [startDate, setStartDate] = useState('2024-06-01');
  const [endDate, setEndDate] = useState('2024-06-30');
  const [interval, setInterval] = useState('5m');
  const [baseShares, setBaseShares] = useState(1000);
  const [cashBuffer, setCashBuffer] = useState(100000);

  // 算法参数（动态）
  const [algoParams, setAlgoParams] = useState<Record<string, number>>({});

  // 成本高级设置
  const [showCost, setShowCost] = useState(false);
  const [cost, setCost] = useState({
    commission_rate: 0.00025,
    min_commission: 5.0,
    stamp_duty_rate: 0.0005,
    transfer_fee_rate: 0.00001,
    slippage: 0.0001,
  });

  // 运行状态
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);

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
    const defaults: Record<string, number> = {};
    for (const p of algo.params) {
      // fixed_band 的 step_pct/levels 是百分比/整数，特殊处理
      if (p.key === 'step_pct' || p.key === 'take_profit' || p.key === 'drop_step' || p.key === 'dev_threshold') {
        defaults[p.key] = p.default;  // 已是百分数值
      } else {
        defaults[p.key] = p.default;
      }
    }
    setAlgoParams(defaults);
  }, [selectedAlgo, algos]);

  const currentAlgo = algos.find(a => a.name === selectedAlgo);

  async function runBacktest() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/backtest`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          algorithm: selectedAlgo,
          symbol,
          start_date: startDate,
          end_date: endDate,
          interval,
          base_shares: baseShares,
          cash_buffer: cashBuffer,
          params: algoParams,
          cost: showCost ? cost : null,
        }),
      });
      const d = await res.json();
      if (d.code !== 0) throw new Error(d.msg || '回测失败');
      setResult(d.data);
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setRunning(false);
    }
  }

  // 成本瀑布数据
  const waterfall = result ? [
    {label: '毛收益', value: result.gross_pnl, type: 'gross', pct: 100},
    {label: '佣金', value: -result.cost_breakdown.commission, type: 'cost', pct: Math.abs(result.cost_breakdown.commission / (result.gross_pnl || 1)) * 100},
    {label: '印花税', value: -result.cost_breakdown.stamp_duty, type: 'cost', pct: Math.abs(result.cost_breakdown.stamp_duty / (result.gross_pnl || 1)) * 100},
    {label: '过户费', value: -result.cost_breakdown.transfer_fee, type: 'cost', pct: Math.abs(result.cost_breakdown.transfer_fee / (result.gross_pnl || 1)) * 100},
    {label: '滑点', value: -result.cost_breakdown.slippage, type: 'cost', pct: Math.abs(result.cost_breakdown.slippage / (result.gross_pnl || 1)) * 100},
    {label: '净收益', value: result.total_net_pnl, type: 'net', pct: Math.abs(result.total_net_pnl / (result.gross_pnl || 1)) * 100},
  ] : [];

  return (
    <div className="t-trading">
      {/* ── 页头 ── */}
      <PageHeader
        title="做T实验室"
        subtitle="A 股 T+1 制度下，靠底仓日内高抛低吸降低持仓成本。用历史分钟数据，亲眼看 4 种做T算法怎么赚钱、被成本吃掉多少。"
      />

      {/* ── ① 算法原理卡片 ── */}
      <div className="t-trading__algo-grid">
        {algos.map(algo => (
          <div
            key={algo.name}
            className={`algo-card${selectedAlgo === algo.name ? ' algo-card--active' : ''}${algo.danger ? ' algo-card--danger' : ''}`}
            onClick={() => setSelectedAlgo(algo.name)}
          >
            <h3 className="algo-card__name">
              {algo.display_name}
              {algo.danger && <span className="algo-card__danger-tag">高风险</span>}
            </h3>
            <p className="algo-card__one-liner">{algo.one_liner}</p>
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
                <p><span className="label">适用行情：</span>{algo.market_fit}</p>
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
      <div className="t-trading__form">
        <h3 className="t-trading__form-title">回测参数{currentAlgo ? ` · ${currentAlgo.display_name}` : ''}</h3>
        <div className="t-trading__form-grid">
          <div className="t-trading__field">
            <label>股票代码</label>
            <input value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="sh600000" />
          </div>
          <div className="t-trading__field">
            <label>开始日期</label>
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
          </div>
          <div className="t-trading__field">
            <label>结束日期</label>
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} />
          </div>
          <div className="t-trading__field">
            <label>K线周期</label>
            <select value={interval} onChange={e => setInterval(e.target.value)}>
              <option value="5m">5 分钟</option>
              <option value="15m">15 分钟</option>
              <option value="30m">30 分钟</option>
              <option value="60m">60 分钟</option>
            </select>
          </div>
          <div className="t-trading__field">
            <label>底仓数量（股）</label>
            <input type="number" value={baseShares} onChange={e => setBaseShares(+e.target.value)} min={100} step={100} />
            <span className="t-trading__field-help">手中已持有、可日内卖出的股票</span>
          </div>
          <div className="t-trading__field">
            <label>日内现金缓冲（元）</label>
            <input type="number" value={cashBuffer} onChange={e => setCashBuffer(+e.target.value)} step={10000} />
            <span className="t-trading__field-help">用于日内买入的可用资金</span>
          </div>

          {/* 算法特定参数 */}
          {currentAlgo?.params.map(p => (
            <div className="t-trading__field" key={p.key}>
              <label>{p.label}{p.unit ? `（${p.unit}）` : ''}</label>
              <input
                type="number"
                value={algoParams[p.key] ?? p.default}
                min={p.min}
                max={p.max}
                step={p.step}
                onChange={e => setAlgoParams({...algoParams, [p.key]: +e.target.value})}
              />
              <span className="t-trading__field-help">{p.help}</span>
            </div>
          ))}
        </div>

        {/* 成本高级设置 */}
        <button className="t-trading__cost-toggle" onClick={() => setShowCost(!showCost)}>
          {showCost ? '▾ 收起成本设置' : '▸ 成本高级设置（佣金/印花税/过户费）'}
        </button>
        {showCost && (
          <div className="t-trading__cost-grid">
            <div className="t-trading__field">
              <label>佣金率</label>
              <input type="number" step={0.00001} value={cost.commission_rate}
                onChange={e => setCost({...cost, commission_rate: +e.target.value})} />
            </div>
            <div className="t-trading__field">
              <label>最低佣金（元）</label>
              <input type="number" step={0.5} value={cost.min_commission}
                onChange={e => setCost({...cost, min_commission: +e.target.value})} />
            </div>
            <div className="t-trading__field">
              <label>印花税率（卖出）</label>
              <input type="number" step={0.0001} value={cost.stamp_duty_rate}
                onChange={e => setCost({...cost, stamp_duty_rate: +e.target.value})} />
            </div>
            <div className="t-trading__field">
              <label>过户费率</label>
              <input type="number" step={0.000001} value={cost.transfer_fee_rate}
                onChange={e => setCost({...cost, transfer_fee_rate: +e.target.value})} />
            </div>
            <div className="t-trading__field">
              <label>滑点</label>
              <input type="number" step={0.0001} value={cost.slippage}
                onChange={e => setCost({...cost, slippage: +e.target.value})} />
            </div>
          </div>
        )}

        <div className="t-trading__actions">
          <Button variant="primary" loading={running} onClick={runBacktest}>
            {running ? '回测中…' : '运行做T回测'}
          </Button>
          {error && <span className="t-trading__error">{error}</span>}
        </div>
      </div>

      {/* ── ⑤ 结果区 ── */}
      {result && (
        <div className="t-trading__result">
          {/* 第1层：总览大数字 */}
          <div className="t-trading__metrics">
            <div className="metric-card">
              <span className="metric-card__label">做T总收益</span>
              <span className={`metric-card__value ${result.total_net_pnl >= 0 ? 'metric-card__value--pos' : 'metric-card__value--neg'}`}>
                {fmtMoney(result.total_net_pnl)}
              </span>
              <span className="metric-card__sub">净赚现金（扣全部成本后）</span>
            </div>
            <div className="metric-card">
              <span className="metric-card__label">做T收益率</span>
              <span className={`metric-card__value ${result.total_return_pct >= 0 ? 'metric-card__value--pos' : 'metric-card__value--neg'}`}>
                {fmtPct(result.total_return_pct)}
              </span>
              <span className="metric-card__sub">相对底仓市值</span>
            </div>
            <div className="metric-card">
              <span className="metric-card__label">降低持仓成本</span>
              <span className={`metric-card__value ${result.cost_reduction >= 0 ? 'metric-card__value--pos' : 'metric-card__value--neg'}`}>
                {fmtNum(result.cost_reduction, 4)} <span style={{fontSize: 'var(--text-sm)'}}>元/股</span>
              </span>
              <span className="metric-card__sub">相当于每股便宜了这么多</span>
            </div>
            <div className="metric-card">
              <span className="metric-card__label">交易次数 / 总成本</span>
              <span className="metric-card__value metric-card__value--neutral">
                {result.total_trades} <span style={{fontSize: 'var(--text-sm)', color: 'var(--color-warning)'}}>· {fmtNum(result.total_cost, 0)}元</span>
              </span>
              <span className="metric-card__sub">买{result.total_buys} / 卖{result.total_sells} · 胜日{result.win_days}/{result.total_days}</span>
            </div>
          </div>

          {/* 第2层：图表 */}
          <div className="t-trading__section">
            <h3 className="t-trading__section-title">每日做T收益</h3>
            <p className="t-trading__section-desc">绿色=当日赚钱，红色=当日亏钱</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={result.daily_results}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="day" {...axisProps} />
                <YAxis {...axisProps} tickFormatter={(v: number) => v.toFixed(0)} />
                <Tooltip
                  {...tooltipProps}
                  formatter={(v: number) => [fmtNum(v), '净收益(元)']}
                />
                <Bar dataKey="net_pnl" radius={[3, 3, 0, 0]}>
                  {/* 图表仅渲染最近 ~120 个交易日，避免长回测时渲染上千个 Cell。 */}
                  {result.daily_results.slice(-120).map((d, i) => (
                    <Cell key={i} fill={d.net_pnl >= 0 ? colorUp : colorDown} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* 价格走势 + 买卖点 */}
          <div className="t-trading__section">
            <h3 className="t-trading__section-title">价格走势与买卖点</h3>
            <p className="t-trading__section-desc">蓝线=价格，红点=买入（A股红买），绿点=卖出（A股绿卖）</p>
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={result.price_series}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="t" {...axisProps} interval="preserveStartEnd" minTickGap={50} />
                <YAxis {...axisProps} domain={['auto', 'auto']} />
                <Tooltip
                  {...tooltipProps}
                  formatter={(v: number) => [fmtNum(v, 3), '价格']}
                />
                <Line type="monotone" dataKey="price" stroke={CHART_COLORS[0]} strokeWidth={1.5} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* 第3层：成本拆解 */}
          <div className="t-trading__section">
            <h3 className="t-trading__section-title">钱去哪了？成本拆解</h3>
            <p className="t-trading__section-desc">
              毛收益 {fmtMoney(result.gross_pnl)} 元，扣掉 {fmtNum(result.total_cost, 2)} 元成本后，净赚 {fmtMoney(result.total_net_pnl)} 元
            </p>
            <div className="t-trading__waterfall">
              {waterfall.map((row, i) => (
                <div className="waterfall-row" key={i}>
                  <span className="waterfall-row__label">{row.label}</span>
                  <div className="waterfall-row__bar">
                    <div
                      className={`waterfall-row__fill waterfall-row__fill--${row.type}`}
                      style={{width: `${Math.min(row.pct, 100)}%`}}
                    />
                  </div>
                  <span className="waterfall-row__value">{fmtMoney(row.value)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 第4层：交易明细 */}
          <div className="t-trading__section">
            <h3 className="t-trading__section-title">交易明细</h3>
            <p className="t-trading__section-desc">最近 {Math.min(result.trades.length, 50)} 笔（共 {result.total_trades} 笔）</p>
            {result.trades.length === 0 ? (
              <StateView state="empty" text="该算法在选定区间内未触发任何交易，可尝试调整参数或换一只波动更大的股票" />
            ) : (
              <div className="t-trading__table-wrap">
                <table className="t-trading__table">
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>方向</th>
                      <th>价格</th>
                      <th>数量</th>
                      <th>金额</th>
                      <th>成本</th>
                      <th>原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.slice(-50).reverse().map((t, i) => (
                      <tr key={i}>
                        <td>{t.timestamp}</td>
                        <td className={t.action === 'BUY' ? 'txt-buy' : 'txt-sell'}>
                          {t.action === 'BUY' ? '买入' : '卖出'}
                        </td>
                        <td className="num">{fmtNum(t.price, 3)}</td>
                        <td className="num">{t.quantity}</td>
                        <td className="num">{fmtNum(t.amount, 0)}</td>
                        <td className="num neg">{fmtNum(t.total_cost, 2)}</td>
                        <td style={{fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)'}}>{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {!result && !running && !error && (
        <StateView state="empty" text="选择一种做T算法，填好参数后点击「运行做T回测」" />
      )}
    </div>
  );
};
