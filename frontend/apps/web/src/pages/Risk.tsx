import { useState, useEffect } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { getApiBase } from '../lib/api';
import { CorrelationMatrix } from '../components/CorrelationMatrix';
import { PageHeader, Button, StateView, Tabs } from '../components/ui';
import './Risk.css';
import { CHART_COLORS, colorWarning, tooltipProps } from '../lib/chartTheme';

const API_BASE = getApiBase();

interface ScenarioContribution {
  symbol: string;
  name: string;
  weight: number;
  shock_pct: number;
  loss: number;
}

interface CorrelationMatrixData {
  symbols: string[];
  matrix: number[][];
  avg_correlation: number;
}

interface RiskData {
  portfolio_value: number;
  var_95: number;
  var_95_pct: number;
  cvar_95: number;
  sharpe_ratio: number;
  max_drawdown: number;
  risk_score: string;
  sector_exposure: { sector: string; value: number; weight: number }[];
  top_positions: {
    symbol: string; name: string; weight: number; value: number; daily_return: number;
  }[];
  scenarios: {
    id: string; name: string; description: string;
    loss: number; loss_pct: number; probability: number;
    category?: 'static' | 'factor' | 'historical';
    source?: string | null;
    contributions?: ScenarioContribution[];
  }[];
  position_count: number;
  returns_volatility: number;
  // ── P2-8/9 新增风险指标（可选，降级/旧数据时可能缺失）──
  sortino_ratio?: number;
  calmar_ratio?: number;
  monte_carlo_var?: number;       // 正数 = 损失金额
  monte_carlo_var_pct?: number;
  avg_correlation?: number;
  correlation_matrix?: CorrelationMatrixData;
}

function formatMoney(v: number) {
  if (v === undefined || v === null || isNaN(v)) return '¥0';
  return '¥' + v.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

function formatPct(v: number) {
  if (v === undefined || v === null || isNaN(v)) return '0%';
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

function formatNum(v: number | undefined | null, digits = 3): string {
  if (v === undefined || v === null || isNaN(v)) return '—';
  return v.toFixed(digits);
}

function RiskGauge({ score }: { score: string }) {
  const scoreNum = score === 'HIGH' ? 80 : score === 'MEDIUM' ? 50 : 25;
  const color = score === 'HIGH' ? 'var(--color-danger)' : score === 'MEDIUM' ? 'var(--color-warning)' : 'var(--color-success)';
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: '2rem', fontWeight: 800, color }}>{score}</div>
      <div style={{ fontSize: '0.7rem', color: 'var(--color-text-secondary)', marginTop: 4 }}>
        风险指数 {scoreNum}/100
      </div>
      <div style={{
        width: '80%', height: 6, background: '#2a2a3e', borderRadius: 3, margin: '6px auto 0',
        overflow: 'hidden',
      }}>
        <div style={{ width: `${scoreNum}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
    </div>
  );
}

const PIE_COLORS = ['#2d7a4f', '#1e88e5', colorWarning, CHART_COLORS[5], '#a855f7', '#06b6d4', '#84cc16'];

function SectorChart({ data }: { data: { sector: string; value: number; weight: number }[] }) {
  const chartData = data.map(d => ({ name: d.sector, value: Math.round(d.value) }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={chartData}
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={90}
          paddingAngle={3}
          dataKey="value"
          label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
          labelLine={{ stroke: chartTextSecondary, strokeWidth: 1 }}
        >
          {chartData.map((_, index) => (
            <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          {...tooltipProps}
          formatter={(value: number) => [`¥${value.toLocaleString()}`, '市值']}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

/* ── Scenario category metadata ── */

const SCENARIO_CATEGORIES = [
  { key: 'static', label: '静态情景' },
  { key: 'factor', label: '因子驱动' },
  { key: 'historical', label: '历史危机重放' },
] as const;

function resolveCategory(cat?: string | null): string {
  return cat && SCENARIO_CATEGORIES.find((c) => c.key === cat) ? cat : 'static';
}

function categoryMeta(cat?: string | null): { key: string; label: string } {
  const resolved = resolveCategory(cat);
  return SCENARIO_CATEGORIES.find((c) => c.key === resolved) ?? SCENARIO_CATEGORIES[0];
}

type ScenarioItem = RiskData['scenarios'][number];

function ScenarioCard({ sc }: { sc: ScenarioItem }) {
  const [expanded, setExpanded] = useState(false);
  const contributions = sc.contributions ?? [];
  const top3 = contributions.slice(0, 3);
  const meta = categoryMeta(sc.category);

  return (
    <div className="risk-scenario-card">
      <div className="risk-scenario-header">
        <div className="risk-scenario-title">
          <span className={`risk-scenario-cat risk-scenario-cat--${meta.key}`}>
            {meta.label}
          </span>
          <span className="risk-scenario-name">{sc.name}</span>
        </div>
        <span className="risk-scenario-prob">{(sc.probability * 100).toFixed(0)}% 概率</span>
      </div>

      <div className="risk-scenario-desc">{sc.description}</div>

      {sc.source && (
        <div className="risk-scenario-source">跌幅参考：{sc.source}</div>
      )}

      <div className="risk-scenario-loss">
        <span className={`num ${sc.loss_pct < 0 ? 'risk-negative' : 'risk-positive'}`}>
          {sc.loss_pct < 0 ? '' : '+'}{sc.loss_pct.toFixed(1)}%
        </span>
        <span className="risk-scenario-loss-abs">({formatMoney(Math.abs(sc.loss))})</span>
      </div>

      {contributions.length > 0 && (
        <div className="risk-scenario-contrib">
          {!expanded && top3.length > 0 && (
            <ul className="risk-scenario-contrib-preview">
              {top3.map((c) => (
                <li key={c.symbol} className="risk-scenario-contrib-row">
                  <span className="risk-scenario-contrib-name">{c.name || c.symbol}</span>
                  <span className="risk-scenario-contrib-val">
                    {formatPct(c.shock_pct)}
                    <span className={`risk-scenario-contrib-loss num ${c.loss < 0 ? 'risk-negative' : 'risk-positive'}`}>
                      {' ' + (c.loss < 0 ? '-' : '+')}{formatMoney(Math.abs(c.loss))}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <button
            className="risk-scenario-toggle"
            onClick={() => setExpanded((e) => !e)}
            aria-expanded={expanded}
          >
            {expanded
              ? '收起仓位贡献'
              : `查看全部仓位贡献 (${contributions.length})`}
          </button>
          {expanded && (
            <table className="risk-table risk-scenario-contrib-table">
              <thead>
                <tr>
                  <th>仓位</th>
                  <th>代码</th>
                  <th>权重</th>
                  <th>冲击</th>
                  <th>损失</th>
                </tr>
              </thead>
              <tbody>
                {contributions.map((c) => (
                  <tr key={c.symbol}>
                    <td>{c.name || '—'}</td>
                    <td className="mono">{c.symbol}</td>
                    <td>{(c.weight * 100).toFixed(2)}%</td>
                    <td className={`num ${c.shock_pct < 0 ? 'risk-negative' : 'risk-positive'}`}>
                      {formatPct(c.shock_pct)}
                    </td>
                    <td className={`num ${c.loss < 0 ? 'risk-negative' : 'risk-positive'}`}>
                      {c.loss < 0 ? '-' : '+'}{formatMoney(Math.abs(c.loss))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

export function RiskPage() {
  const [data, setData] = useState<RiskData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<'overview' | 'sectors' | 'scenarios'>('overview');

  // silent=true 时保留旧数据（仅刷新指示器），避免手动刷新把整屏替换成 loading。
  async function load(silent = false) {
    if (silent) setRefreshing(true); else setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/risk/portfolio`);
      const json = await res.json();
      if (json.code === 0) setData(json.data);
      else setError(json.msg || '加载失败');
    } catch {
      setError('网络错误，加载风险分析失败');
    } finally {
      if (silent) setRefreshing(false); else setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  if (loading) return <StateView state="loading" text="正在加载风险分析…" />;

  if (error && !data) return (
    <StateView state="error" text={error} onRetry={() => load()} />
  );

  const riskScoreColor = data.risk_score === 'HIGH' ? 'risk-high'
    : data.risk_score === 'MEDIUM' ? 'risk-medium' : 'risk-low';

  return (
    <div className="risk-page">
      <PageHeader
        title="风险分析"
        subtitle={refreshing ? '刷新中…' : undefined}
        actions={<Button variant="secondary" size="sm" onClick={() => load(true)} disabled={refreshing}>刷新</Button>}
      />

      {error && data && (
        <div className="risk-loading">{error}（以下为上次数据）</div>
      )}

      {data.message && (
        <div className="risk-empty-msg">
          <p>{data.message}</p>
          <p className="risk-empty-hint">在 <a href="/portfolio">组合页面</a> 添加持仓后即可查看完整风险分析</p>
        </div>
      )}

      {/* ── Key Metrics Row ── */}
      <div className="risk-metrics-grid">
        <div className="risk-metric-card">
          <div className="risk-metric-label">组合市值</div>
          <div className="risk-metric-value">{formatMoney(data.portfolio_value)}</div>
          <div className="risk-metric-sub">{data.position_count} 个持仓</div>
        </div>

        <div className="risk-metric-card">
          <div className="risk-metric-label">VaR (95% 1日)</div>
          <div className="risk-metric-value risk-negative">
            {data.portfolio_value > 0 ? `-${formatMoney(data.var_95)}` : '¥0'}
          </div>
          <div className="risk-metric-sub">
            {data.var_95_pct > 0 ? `占 ${data.var_95_pct}%` : '—'}
          </div>
        </div>

        <div className="risk-metric-card">
          <div className="risk-metric-label">CVaR (Expected Shortfall)</div>
          <div className="risk-metric-value risk-negative">
            {data.portfolio_value > 0 ? `-${formatMoney(data.cvar_95)}` : '¥0'}
          </div>
          <div className="risk-metric-sub">极端行情下预期损失</div>
        </div>

        <div className="risk-metric-card">
          <div className="risk-metric-label">蒙特卡洛 VaR</div>
          <div className="risk-metric-value risk-negative">
            {data.portfolio_value > 0 && data.monte_carlo_var
              ? `-${formatMoney(data.monte_carlo_var)}`
              : '¥0'}
          </div>
          <div className="risk-metric-sub">
            {data.monte_carlo_var_pct ? `占 ${data.monte_carlo_var_pct}%` : '模拟分布 95% 分位'}
          </div>
        </div>

        <div className="risk-metric-card">
          <div className="risk-metric-label">夏普比率</div>
          <div className={`risk-metric-value ${data.sharpe_ratio >= 1 ? 'risk-positive' : ''}`}>
            {data.sharpe_ratio.toFixed(3)}
          </div>
          <div className="risk-metric-sub">
            {data.returns_volatility > 0 ? `波动率 ${data.returns_volatility}%` : '—'}
          </div>
        </div>

        <div className="risk-metric-card">
          <div className="risk-metric-label">Sortino 比率</div>
          <div className={`risk-metric-value ${data.sortino_ratio && data.sortino_ratio >= 1 ? 'risk-positive' : ''}`}>
            {formatNum(data.sortino_ratio)}
          </div>
          <div className="risk-metric-sub">仅按下行波动调整</div>
        </div>

        <div className="risk-metric-card">
          <div className="risk-metric-label">Calmar 比率</div>
          <div className={`risk-metric-value ${data.calmar_ratio && data.calmar_ratio >= 1 ? 'risk-positive' : ''}`}>
            {formatNum(data.calmar_ratio)}
          </div>
          <div className="risk-metric-sub">年化收益 / 最大回撤</div>
        </div>

        <div className="risk-metric-card">
          <div className="risk-metric-label">最大回撤</div>
          <div className="risk-metric-value risk-negative">
            {data.max_drawdown.toFixed(2)}%
          </div>
          <div className="risk-metric-sub">历史最大跌幅</div>
        </div>

        <div className={`risk-metric-card ${riskScoreColor}`}>
          <div className="risk-metric-label">风险评分</div>
          <div className="risk-gauge-wrap">
            <RiskGauge score={data.risk_score} />
          </div>
        </div>
      </div>

      {/* ── Tabs ── */}
      <Tabs
        className="risk-tabs"
        active={tab}
        onChange={(k) => setTab(k as typeof tab)}
        tabs={[
          { key: 'overview', label: '持仓风险' },
          { key: 'sectors', label: '板块分布' },
          { key: 'scenarios', label: '压力测试' },
        ]}
      />

      {tab === 'overview' && (
        <div className="risk-section">
          <h3>持仓风险贡献</h3>
          {data.top_positions.length === 0 ? (
            <StateView state="empty" text="暂无持仓数据" />
          ) : (
            <table className="risk-table">
              <thead>
                <tr>
                  <th>股票</th>
                  <th>代码</th>
                  <th>市值</th>
                  <th>权重</th>
                  <th>今日涨跌</th>
                </tr>
              </thead>
              <tbody>
                {data.top_positions.map((p) => (
                  <tr key={p.symbol}>
                    <td>{p.name || '—'}</td>
                    <td className="mono">{p.symbol}</td>
                    <td>{formatMoney(p.value)}</td>
                    <td>{(p.weight * 100).toFixed(2)}%</td>
                    <td className={`num ${p.daily_return >= 0 ? 'risk-positive' : 'risk-negative'}`}>
                      {formatPct(p.daily_return)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'overview' && data.correlation_matrix && data.correlation_matrix.symbols.length > 0 && (
        <div className="risk-section risk-correlation-section">
          <h3>持仓相关性矩阵</h3>
          <div className="risk-correlation-summary">
            <div className="risk-correlation-avg">
              平均相关度 <strong>{formatNum(data.avg_correlation ?? data.correlation_matrix.avg_correlation, 2)}</strong>
            </div>
            <div className="risk-correlation-hint">平均相关度越高 = 集中度风险越大</div>
          </div>
          <CorrelationMatrix
            symbols={data.correlation_matrix.symbols}
            matrix={data.correlation_matrix.matrix}
          />
        </div>
      )}

      {tab === 'sectors' && (
        <div className="risk-section">
          <h3>板块敞口分析</h3>
          <div className="risk-sector-layout">
            <div className="risk-sector-chart">
              <SectorChart data={data.sector_exposure} />
            </div>
            <div className="risk-sector-table-wrap">
              <table className="risk-table">
                <thead>
                  <tr>
                    <th>板块</th>
                    <th>市值</th>
                    <th>占比</th>
                    <th>风险敞口</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sector_exposure.map((s) => (
                    <tr key={s.sector}>
                      <td>{s.sector}</td>
                      <td>{formatMoney(s.value)}</td>
                      <td>{(s.weight * 100).toFixed(1)}%</td>
                      <td>
                        <div className="risk-bar-wrap">
                          <div
                            className="risk-bar-fill"
                            style={{ width: `${Math.min(s.weight * 100, 100)}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === 'scenarios' && (
        <div className="risk-section">
          <h3>压力测试情景</h3>
          {SCENARIO_CATEGORIES.map((cat) => {
            const items = data.scenarios.filter((s) => resolveCategory(s.category) === cat.key);
            if (items.length === 0) return null;
            return (
              <div key={cat.key} className="risk-scenario-group">
                <div className="risk-scenario-group-title">
                  {cat.label}
                  <span className="risk-scenario-group-count">{items.length}</span>
                </div>
                <div className="risk-scenario-grid">
                  {items.map((sc) => (
                    <ScenarioCard key={sc.id} sc={sc} />
                  ))}
                </div>
              </div>
            );
          })}

          <div className="risk-scenario-note">
            压力测试帮助评估极端行情下的潜在损失。以上情景基于历史极端事件模拟，实际损失可能不同。
          </div>
        </div>
      )}
    </div>
  );
}
