/**
 * 有效前沿资产配置工具 — Efficient Frontier
 * 属于 /lt-backtest 页面的一个 Tab。
 *
 * 输入一组标的 + 回看窗口 → 绘制马科维茨有效前沿（风险-收益散点），
 * 标注最小方差点 / 最大夏普点，点击点查看该点权重分布。
 *
 * 用途：在跑回测之前，先探索"这组资产能组成怎样的风险/收益组合"。
 */
import React, {useState} from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceDot, Cell,
} from 'recharts';
import {getApiBase} from '../../lib/api';
import { CHART_COLORS, axisProps, chartTextTertiary, colorOrange, gridProps, tooltipProps } from '../../lib/chartTheme';
import {Button} from '../../components/ui';

const API = `${getApiBase()}/lt-backtest`;

interface FrontierPoint {
  ret: number;
  risk: number;
  sharpe: number;
  weights: Record<string, number>;
}
interface FrontierResp {
  symbols: string[];
  frontier: FrontierPoint[];
  min_variance: FrontierPoint | null;
  max_sharpe: FrontierPoint | null;
  warning?: string;
}

const fmtPct = (n: number) => (n * 100).toFixed(2) + '%';

export const EfficientFrontier: React.FC = () => {
  const [symbols, setSymbols] = useState('sh510300,sh511010,sh518880');
  const [lookback, setLookback] = useState(120);
  const [maxWeight, setMaxWeight] = useState(0.4);
  const [cashBuffer, setCashBuffer] = useState(0.05);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<FrontierResp | null>(null);
  const [picked, setPicked] = useState<FrontierPoint | null>(null);

  async function compute() {
    setLoading(true);
    setError(null);
    setData(null);
    setPicked(null);
    try {
      const res = await fetch(`${API}/efficient-frontier`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          symbols: symbols.split(',').map(s => s.trim()).filter(Boolean),
          lookback,
          max_weight: maxWeight,
          cash_buffer: cashBuffer,
          n_points: 25,
        }),
      });
      const d = await res.json();
      if (d.code !== 0) throw new Error(d.msg || '计算失败');
      setData(d.data);
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setLoading(false);
    }
  }

  const frontier = data?.frontier || [];
  const minVar = data?.min_variance;
  const maxSh = data?.max_sharpe;

  return (
    <div className="ef-frontier">
      <p className="ef-frontier__intro">
        马科维茨有效前沿：用最近 {lookback} 个交易日的收益率与波动率，
        计算这组资产能组成的所有"风险-收益"最优组合。
        横轴=年化波动率，纵轴=年化收益。<b>最小方差点</b>风险最低，<b>最大夏普点</b>每单位风险收益最高。
      </p>

      {/* 参数 */}
      <div className="ef-frontier__form">
        <div className="lt-backtest__field">
          <label>标的池（逗号分隔）</label>
          <input value={symbols} onChange={e => setSymbols(e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>回看窗口（日）</label>
          <input type="number" value={lookback} min={20} max={500} step={10}
            onChange={e => setLookback(+e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>单标的上限</label>
          <input type="number" value={maxWeight} min={0.1} max={1} step={0.05}
            onChange={e => setMaxWeight(+e.target.value)} />
        </div>
        <div className="lt-backtest__field">
          <label>现金缓冲</label>
          <input type="number" value={cashBuffer} min={0} max={0.5} step={0.05}
            onChange={e => setCashBuffer(+e.target.value)} />
        </div>
        <Button variant="primary" loading={loading} onClick={compute}>
          {loading ? '计算中…' : '计算有效前沿'}
        </Button>
      </div>

      {error && <div className="lt-backtest__error">{error}</div>}
      {data?.warning && <div className="lt-backtest__error">{data.warning}</div>}

      {/* 散点图 */}
      {frontier.length > 0 && (
        <div className="ef-frontier__chart">
          <ResponsiveContainer width="100%" height={380}>
            <ScatterChart>
              <CartesianGrid {...gridProps} />
              <XAxis
                type="number" dataKey="risk" name="年化波动率"
                {...axisProps}
                tickFormatter={(v: number) => fmtPct(v)}
                label={{value: '年化波动率', position: 'insideBottom', offset: -5, fill: chartTextTertiary, fontSize: 11}}
              />
              <YAxis
                type="number" dataKey="ret" name="年化收益"
                {...axisProps}
                tickFormatter={(v: number) => fmtPct(v)}
                label={{value: '年化收益', angle: -90, position: 'insideLeft', fill: chartTextTertiary, fontSize: 11}}
              />
              <ZAxis range={[60, 60]} />
              <Tooltip
                {...tooltipProps}
                cursor={{strokeDasharray: '3 3'}}
                formatter={(v: number, name: string) => [fmtPct(v), name]}
              />
              <Scatter
                name="前沿" data={frontier} fill={CHART_COLORS[0]}
                onClick={(p: any) => setPicked(p.payload)}
              />
              {minVar && (
                <ReferenceDot
                  x={minVar.risk} y={minVar.ret} r={8} fill={CHART_COLORS[1]}
                  stroke={chartText} strokeWidth={1.5}
                  label={{value: '最小方差', position: 'top', fill: CHART_COLORS[1], fontSize: 11}}
                  onClick={() => setPicked(minVar)}
                />
              )}
              {maxSh && (
                <ReferenceDot
                  x={maxSh.risk} y={maxSh.ret} r={8} fill={colorOrange}
                  stroke={chartText} strokeWidth={1.5}
                  label={{value: '最大夏普', position: 'top', fill: colorOrange, fontSize: 11}}
                  onClick={() => setPicked(maxSh)}
                />
              )}
            </ScatterChart>
          </ResponsiveContainer>
          <p className="ef-frontier__hint">点击任意点查看该组合的权重分配。</p>
        </div>
      )}

      {/* 选中点权重 */}
      {picked && (
        <div className="ef-frontier__picked">
          <h4>
            选中组合 · 年化收益 <span className="pos">{fmtPct(picked.ret)}</span>
            {' · '}波动率 <span>{fmtPct(picked.risk)}</span>
            {' · '}夏普 <span>{picked.sharpe.toFixed(3)}</span>
          </h4>
          <div className="ef-frontier__weights">
            {Object.entries(picked.weights).map(([s, w], i) => (
              <div key={s} className="ef-frontier__weight">
                <div className="ef-frontier__weight-bar">
                  <div
                    className="ef-frontier__weight-fill"
                    style={{width: `${w * 100}%`, background: CHART_COLORS[i % CHART_COLORS.length]}}
                  />
                </div>
                <span className="mono">{s}</span>
                <span>{(w * 100).toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 关键点对比 */}
      {minVar && maxSh && (
        <div className="ef-frontier__keypoints">
          <div className="ef-frontier__keypoint ef-frontier__keypoint--min">
            <h5>最小方差组合</h5>
            <p>风险最低：年化波动 {fmtPct(minVar.risk)}，收益 {fmtPct(minVar.ret)}</p>
            <div className="ef-frontier__mini-weights">
              {Object.entries(minVar.weights).map(([s, w]) => (
                <span key={s} className="weight-chip">{s} {(w * 100).toFixed(0)}%</span>
              ))}
            </div>
          </div>
          <div className="ef-frontier__keypoint ef-frontier__keypoint--max">
            <h5>最大夏普组合</h5>
            <p>性价比最高：夏普 {maxSh.sharpe.toFixed(3)}，收益 {fmtPct(maxSh.ret)}</p>
            <div className="ef-frontier__mini-weights">
              {Object.entries(maxSh.weights).map(([s, w]) => (
                <span key={s} className="weight-chip">{s} {(w * 100).toFixed(0)}%</span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
