/**
 * Walk-Forward 滚动寻优 + 过拟合检测
 * 属于 /lt-backtest 页面的一个 Tab。
 *
 * 滑动窗口：训练段(IS)网格寻优 → 测试段(OOS)验证 → 拼接 OOS 曲线。
 * 用 IS vs OOS 落差衡量过拟合：WFE(走样效率)、参数稳定性、OOS 正收益窗口比。
 */
import React, {useState} from 'react';
import {
  LineChart, Line, ComposedChart, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts';
import {getApiBase} from '../../lib/api';
import { CHART_COLORS, axisProps, gridProps, tooltipProps } from '../../lib/chartTheme';
import {Button} from '../../components/ui';

const API = `${getApiBase()}/lt-backtest`;

interface WindowRow {
  index: number;
  train_start: string; train_end: string;
  test_start: string; test_end: string;
  best_params: Record<string, any>;
  is_sharpe: number; is_cagr: number;
  oos_sharpe: number; oos_cagr: number;
  oos_max_drawdown: number; oos_total_return_pct: number;
}
interface WFResult {
  strategy: string; n_windows: number; skipped: number;
  windows: WindowRow[];
  oos_equity_curve: Array<{date: string; nav: number}>;
  aggregated: Record<string, any>;
  overfitting: {
    walk_forward_efficiency: number;
    param_stability: number;
    oos_positive_ratio: number;
    median_is_sharpe: number;
    median_oos_sharpe: number;
    distinct_param_sets: number;
  };
  warning?: string;
}

const fmtPct = (n: number) => (n >= 0 ? '+' : '') + (n ?? 0).toFixed(2) + '%';
const fmtNum = (n: number, d = 2) => (n ?? 0).toFixed(d);

export const WalkForward: React.FC = () => {
  const [strategy, setStrategy] = useState('dual_momentum');
  const [symbols, setSymbols] = useState('sh510300,sh511010');
  const [benchmark, setBenchmark] = useState('sh510300');
  const [startDate, setStartDate] = useState('2018-01-01');
  const [endDate, setEndDate] = useState('2025-12-31');
  const [trainDays, setTrainDays] = useState(504);
  const [testDays, setTestDays] = useState(126);
  const [stepDays, setStepDays] = useState(126);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<WFResult | null>(null);

  async function run() {
    setRunning(true); setError(null); setData(null);
    try {
      const res = await fetch(`${API}/walk-forward`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          strategy,
          symbols: symbols.split(',').map(s => s.trim()).filter(Boolean),
          benchmark, start_date: startDate, end_date: endDate,
          train_days: trainDays, test_days: testDays, step_days: stepDays,
          metric: 'sharpe_ratio',
        }),
      });
      const d = await res.json();
      if (d.code !== 0) throw new Error(d.msg || 'walk-forward 失败');
      setData(d.data);
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setRunning(false);
    }
  }

  const of = data?.overfitting;
  // 过拟合判定
  const wfeVerdict = of
    ? of.walk_forward_efficiency > 0.7 ? {t: '稳健', c: 'pos'}
      : of.walk_forward_efficiency > 0.4 ? {t: '一般', c: 'neutral'}
      : {t: '偏过拟合', c: 'neg'}
    : null;

  // IS vs OOS 夏普对比数据
  const isOosData = data?.windows.map(w => ({
    idx: w.index,
    IS: Number(w.is_sharpe.toFixed(3)),
    OOS: Number(w.oos_sharpe.toFixed(3)),
  })) || [];

  return (
    <div className="wf-tab">
      <p className="wf-tab__intro">
        Walk-Forward 用"训练段选参数 → 测试段验证"的滚动窗口检验策略是否过拟合。
        <b>关键看 IS(样本内) vs OOS(样本外) 的落差</b>：若 IS 大幅优于 OOS，说明参数是事后诸葛亮。
        走样效率(WFE) = OOS夏普 / IS夏普，大于 0.7 稳健，小于 0.3 偏过拟合。
      </p>

      {/* 参数 */}
      <div className="wf-tab__form">
        <div className="lt-backtest__field">
          <label>策略</label>
          <select value={strategy} onChange={e => setStrategy(e.target.value)}>
            <option value="dual_momentum">双动量</option>
            <option value="sma_trend">均线趋势</option>
            <option value="all_weather">全天候</option>
            <option value="risk_parity">风险平价</option>
            <option value="min_variance">最小方差</option>
          </select>
        </div>
        <div className="lt-backtest__field">
          <label>标的池</label>
          <input value={symbols} onChange={e => setSymbols(e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>基准</label>
          <input value={benchmark} onChange={e => setBenchmark(e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>开始</label>
          <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>结束</label>
          <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>训练段(日)</label>
          <input type="number" value={trainDays} step={63}
            onChange={e => setTrainDays(+e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>测试段(日)</label>
          <input type="number" value={testDays} step={21}
            onChange={e => setTestDays(+e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>步长(日)</label>
          <input type="number" value={stepDays} step={21}
            onChange={e => setStepDays(+e.target.value)} />
        </div>
        <Button variant="primary" loading={running} onClick={run}>
          {running ? '运行中…' : '运行 Walk-Forward'}
        </Button>
      </div>

      {error && <div className="lt-backtest__error">{error}</div>}
      {data?.warning && <div className="lt-backtest__error">{data.warning}</div>}

      {data && !data.warning && (
        <>
          {/* 过拟合度量卡 */}
          <div className="wf-tab__metrics">
            <div className={`metric-card`}>
              <span className="metric-card__label">走样效率 WFE</span>
              <span className={`metric-card__value metric-card__value--${wfeVerdict?.c}`}>
                {fmtNum(of!.walk_forward_efficiency, 2)}
              </span>
              <span className="metric-card__sub">{wfeVerdict?.t}（OOS/IS 夏普）</span>
            </div>
            <div className="metric-card">
              <span className="metric-card__label">参数稳定性</span>
              <span className="metric-card__value metric-card__value--neutral">
                {fmtNum(of!.param_stability, 2)}
              </span>
              <span className="metric-card__sub">
                {of!.distinct_param_sets}/{data.n_windows} 种参数（越少越稳）
              </span>
            </div>
            <div className="metric-card">
              <span className="metric-card__label">OOS 正收益窗口比</span>
              <span className={`metric-card__value metric-card__value--${of!.oos_positive_ratio >= 0.5 ? 'pos' : 'neg'}`}>
                {fmtNum(of!.oos_positive_ratio * 100, 0)}%
              </span>
              <span className="metric-card__sub">样本外夏普为正的窗口</span>
            </div>
            <div className="metric-card">
              <span className="metric-card__label">OOS 年化 / 夏普</span>
              <span className="metric-card__value metric-card__value--neutral">
                {fmtNum(data.aggregated.cagr, 1)}%
              </span>
              <span className="metric-card__sub">
                夏普 {fmtNum(data.aggregated.sharpe_ratio, 2)} · 回撤 {fmtNum(data.aggregated.max_drawdown, 1)}%
              </span>
            </div>
          </div>

          {/* IS vs OOS 夏普对比 */}
          <div className="lt-backtest__section">
            <h3 className="lt-backtest__section-title">IS vs OOS 夏普（逐窗口）</h3>
            <p className="lt-backtest__section-desc">
              蓝=训练段(IS)夏普，绿=测试段(OOS)夏普。OOS 持续低于 IS = 过拟合信号。
            </p>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={isOosData}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="idx" {...axisProps} />
                <YAxis {...axisProps} />
                <Tooltip {...tooltipProps} />
                <Legend />
                <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" />
                <Bar dataKey="IS" fill={CHART_COLORS[0]} />
                <Bar dataKey="OOS" fill={CHART_COLORS[1]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* 拼接 OOS 权益曲线 */}
          <div className="lt-backtest__section">
            <h3 className="lt-backtest__section-title">Walk-Forward OOS 累计净值</h3>
            <p className="lt-backtest__section-desc">
              各窗口测试段拼接（复利衔接，起点=1.0）。这是策略在"未见数据"上的真实表现。
            </p>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={data.oos_equity_curve}>
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="date" {...axisProps} minTickGap={60} />
                <YAxis {...axisProps} />
                <Tooltip {...tooltipProps} />
                <Line type="monotone" dataKey="nav" stroke={CHART_COLORS[1]} strokeWidth={2} dot={false} name="OOS净值" />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* 逐窗口表 */}
          <div className="lt-backtest__section">
            <h3 className="lt-backtest__section-title">逐窗口明细（{data.n_windows} 窗口，跳过 {data.skipped}）</h3>
            <div className="bt-history__table-wrap">
              <table className="bt-history__table">
                <thead>
                  <tr>
                    <th>#</th><th>训练段</th><th>测试段</th>
                    <th>IS夏普</th><th>OOS夏普</th><th>OOS年化</th>
                    <th>OOS回撤</th><th>最优参数</th>
                  </tr>
                </thead>
                <tbody>
                  {data.windows.map(w => (
                    <tr key={w.index}>
                      <td>{w.index}</td>
                      <td className="mono" style={{fontSize: 'var(--text-xs)'}}>{w.train_start}~{w.train_end}</td>
                      <td className="mono" style={{fontSize: 'var(--text-xs)'}}>{w.test_start}~{w.test_end}</td>
                      <td className={`num ${w.is_sharpe >= 0 ? 'txt-pos' : 'txt-neg'}`}>{fmtNum(w.is_sharpe, 2)}</td>
                      <td className={`num ${w.oos_sharpe >= 0 ? 'txt-pos' : 'txt-neg'}`}>{fmtNum(w.oos_sharpe, 2)}</td>
                      <td className={`num ${w.oos_cagr >= 0 ? 'txt-pos' : 'txt-neg'}`}>{fmtPct(w.oos_cagr)}</td>
                      <td className="num neg">-{fmtNum(w.oos_max_drawdown, 1)}%</td>
                      <td className="mono" style={{fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)'}}>
                        {Object.entries(w.best_params).map(([k, v]) => `${k}=${v}`).join(', ') || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
