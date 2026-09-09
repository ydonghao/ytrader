/**
 * 永久投资组合页面
 *
 * 功能:
 * - 左栏: 组合列表(永久/全天候/黄金蝴蝶 + 最新净值)
 * - 右栏 Tab:
 *   概览: 净值曲线 + 配置对比饼图 + 偏离条形图
 *   再平衡: 偏离趋势 + 再平衡建议卡 + 应用按钮
 *   持仓: 持仓表 + 回测
 */
import React, {useEffect, useState, useCallback} from 'react';
import {
  LineChart, Line, PieChart, Pie, Cell,
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid, ReferenceLine,
} from 'recharts';
import { CHART_COLORS, axisProps, chartBorderStrong, colorUp, gridProps, tooltipProps } from '../lib/chartTheme';
import {getApiBase} from '../lib/api';
import {Button, Modal, PageHeader, StateView, Tabs} from '../components/ui';
import './PermPortfolio.css';

const API = getApiBase();

// 资产类颜色
const ASSET_COLORS: Record<string, string> = {
  equity: '#5470c6',
  bond: '#91cc75',
  gold: '#fac858',
  cash: '#73c0de',
};

// ── 类型 ──────────────────────────────────────────────────────
interface Instrument {
  id: number;
  symbol: string;
  market: string;
  asset_class: string;
  ccy: string;
  name: string;
  enabled: boolean;
}
interface Portfolio {
  id: number;
  name: string;
  strategy_type: string;
  base_ccy: string;
  rebalance_threshold: number;
  initial_capital: number;
  is_active: boolean;
  latest_nav: {
    trade_date: string;
    nav_cny: number;
    daily_return: number | null;
    max_drift: number;
    rebalance_suggested: boolean;
  } | null;
}
interface Holding {
  id: number;
  instrument_id: number;
  symbol: string | null;
  market: string | null;
  asset_class: string | null;
  ccy: string | null;
  name: string | null;
  target_weight: number;
  shares: number;
  cost_price: number;
}
interface NavItem {
  symbol: string;
  asset_class: string;
  shares: number;
  price: number;
  price_cny: number;
  value_cny: number;
  target_weight: number;
  actual_weight: number;
  drift: number;
}
interface PortfolioDetail {
  id: number;
  name: string;
  strategy_type: string;
  rebalance_threshold: number;
  initial_capital: number;
  is_active: boolean;
  holdings: Holding[];
  latest_nav: {
    trade_date: string;
    nav_cny: number;
    daily_return: number | null;
    total_value_cny: number;
    max_drift: number;
    rebalance_suggested: boolean;
    items: NavItem[];
  } | null;
}
interface NavHistoryPoint {
  trade_date: string;
  nav_cny: number;
  daily_return: number | null;
  total_value_cny: number;
  max_drift: number;
  rebalance_suggested: boolean;
}
interface RebalanceAction {
  instrument_id: number;
  symbol: string;
  asset_class: string;
  action: string;
  shares_delta: number;
  value_cny: number;
  reason: string;
}
interface Breakdown {
  asset_class: string;
  target_weight: number;
  actual_weight: number;
  drift: number;
}
interface RebalanceSuggestion {
  portfolio_id: number;
  trade_date: string;
  total_value_cny: number;
  max_drift: number;
  threshold: number;
  rebalance_suggested: boolean;
  breakdowns: Breakdown[];
  actions: RebalanceAction[];
}

// ── API helpers ───────────────────────────────────────────────
async function apiGet(path: string) {
  const r = await fetch(`${API}${path}`);
  const j = await r.json();
  if (j.code !== 0) throw new Error(j.msg || 'API error');
  return j.data;
}
async function apiPost(path: string, body?: any) {
  const r = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json();
  if (j.code !== 0) throw new Error(j.msg || 'API error');
  return j.data;
}
async function apiPut(path: string, body?: any) {
  const r = await fetch(`${API}${path}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json();
  if (j.code !== 0) throw new Error(j.msg || 'API error');
  return j.data;
}
async function apiDelete(path: string) {
  const r = await fetch(`${API}${path}`, {method: 'DELETE'});
  const j = await r.json();
  if (j.code !== 0) throw new Error(j.msg || 'API error');
  return j.data;
}

// ── 主组件 ────────────────────────────────────────────────────
export const PermPortfolio: React.FC = () => {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PortfolioDetail | null>(null);
  const [navHistory, setNavHistory] = useState<NavHistoryPoint[]>([]);
  const [tab, setTab] = useState<'overview' | 'rebalance' | 'holdings'>('overview');
  const [range, setRange] = useState<'1M' | '3M' | '6M' | '1Y' | 'ALL'>('1Y');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showInstrumentModal, setShowInstrumentModal] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [instruments, setInstruments] = useState<Instrument[]>([]);

  const loadPortfolios = useCallback(async () => {
    try {
      const data = await apiGet('/perm-portfolio/portfolios?active_only=true');
      setPortfolios(data);
      if (data.length > 0 && selectedId === null) {
        setSelectedId(data[0].id);
      }
    } catch (e: any) {
      setError(e.message);
    }
  }, [selectedId]);

  const loadDetail = useCallback(async (id: number) => {
    setLoading(true);
    setError(null);
    try {
      const d = await apiGet(`/perm-portfolio/portfolios/${id}`);
      setDetail(d);
      // 净值历史
      const ranges: Record<string, number> = {
        '1M': 30, '3M': 90, '6M': 180, '1Y': 365, 'ALL': 36500,
      };
      const days = ranges[range];
      const end = new Date();
      const start = new Date(end.getTime() - days * 86400000);
      const nav = await apiGet(
        `/perm-portfolio/portfolios/${id}/nav?start_date=${start.toISOString().slice(0, 10)}&end_date=${end.toISOString().slice(0, 10)}`
      );
      setNavHistory(nav);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => { loadPortfolios(); }, [loadPortfolios]);
  useEffect(() => {
    if (selectedId !== null) loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  const loadInstruments = useCallback(async () => {
    try {
      const data = await apiGet('/perm-portfolio/instruments');
      setInstruments(data);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  const openInstrumentModal = async () => {
    await loadInstruments();
    setShowInstrumentModal(true);
  };

  return (
    <div className="pp-page">
      <PageHeader
        title="永久投资组合"
        subtitle="跨 A 股 / H 股 / 美股 的多策略资产配置 · 25/25/25/25 永久组合"
        actions={<Button variant="secondary" size="sm" onClick={openInstrumentModal}>标的池管理</Button>}
      />

      {error && <div className="pp-error">{error}</div>}

      <div className="pp-layout">
        {/* 左栏: 组合列表 */}
        <div className="pp-sidebar">
          <div className="pp-sidebar__head">
            <h3 className="pp-sidebar__title">策略组合</h3>
            <Button variant="primary" size="sm" onClick={() => setShowCreateModal(true)}>
              新建
            </Button>
          </div>
          {portfolios.map(p => (
            <div
              key={p.id}
              className={`pp-portfolio-card ${selectedId === p.id ? 'pp-portfolio-card--active' : ''}`}
              onClick={() => setSelectedId(p.id)}
            >
              <div className="pp-portfolio-card__name">{p.name}</div>
              <div className="pp-portfolio-card__type">{p.strategy_type}</div>
              {p.latest_nav ? (
                <div className="pp-portfolio-card__nav">
                  <span className="pp-portfolio-card__nav-value num">
                    {p.latest_nav.nav_cny.toFixed(4)}
                  </span>
                  {p.latest_nav.daily_return !== null && (
                    <span className={`pp-portfolio-card__return num ${p.latest_nav.daily_return >= 0 ? 'positive' : 'negative'}`}>
                      {(p.latest_nav.daily_return * 100).toFixed(2)}%
                    </span>
                  )}
                  {p.latest_nav.rebalance_suggested && (
                    <span className="pp-portfolio-card__alert">需再平衡</span>
                  )}
                </div>
              ) : (
                <div className="pp-portfolio-card__nav pp-portfolio-card__nav--empty">暂无净值</div>
              )}
            </div>
          ))}
        </div>

        {/* 右栏: 详情 */}
        <div className="pp-main">
          {loading && <StateView state="loading" text="加载中…" />}
          {!loading && detail && (
            <>
              <Tabs
                tabs={[
                  {key: 'overview', label: '概览'},
                  {key: 'rebalance', label: '再平衡'},
                  {key: 'holdings', label: '持仓管理'},
                ]}
                active={tab}
                onChange={(k) => setTab(k as 'overview' | 'rebalance' | 'holdings')}
                className="pp-tabs"
              />

              {tab === 'overview' && <OverviewTab detail={detail} navHistory={navHistory} range={range} onRangeChange={setRange} />}
              {tab === 'rebalance' && <RebalanceTab portfolioId={detail.id} portfolioName={detail.name} />}
              {tab === 'holdings' && <HoldingsTab detail={detail} onChanged={() => selectedId !== null && loadDetail(selectedId)} />}
            </>
          )}
        </div>
      </div>

      {showInstrumentModal && (
        <InstrumentManagerModal
          instruments={instruments}
          onClose={() => setShowInstrumentModal(false)}
          onChanged={loadInstruments}
        />
      )}
      {showCreateModal && (
        <CreatePortfolioModal
          instruments={instruments}
          onClose={() => setShowCreateModal(false)}
          onCreated={async (newId) => {
            setShowCreateModal(false);
            await loadPortfolios();
            setSelectedId(newId);
          }}
          onLoadInstruments={loadInstruments}
        />
      )}
    </div>
  );
};

// ── 概览 Tab ──────────────────────────────────────────────────
const OverviewTab: React.FC<{
  detail: PortfolioDetail;
  navHistory: NavHistoryPoint[];
  range: string;
  onRangeChange: (r: any) => void;
}> = ({detail, navHistory, range, onRangeChange}) => {
  const latest = detail.latest_nav;
  const items = latest?.items || [];

  // 配置对比数据
  const targetPie = ['equity', 'bond', 'gold', 'cash'].map(ac => {
    const tgt = items.filter(i => i.asset_class === ac).reduce((s, i) => s + i.target_weight, 0);
    return {name: ac, value: tgt, kind: 'target'};
  }).filter(d => d.value > 0);

  const actualPie = ['equity', 'bond', 'gold', 'cash'].map(ac => {
    const act = items.filter(i => i.asset_class === ac).reduce((s, i) => s + i.actual_weight, 0);
    return {name: ac, value: act, kind: 'actual'};
  }).filter(d => d.value > 0);

  // 偏离条形图(按资产类)
  const driftData = ['equity', 'bond', 'gold', 'cash'].map(ac => {
    const tgt = items.filter(i => i.asset_class === ac).reduce((s, i) => s + i.target_weight, 0);
    const act = items.filter(i => i.asset_class === ac).reduce((s, i) => s + i.actual_weight, 0);
    return {asset: ac, drift: (act - tgt) * 100};
  }).filter(d => items.some(i => i.asset_class === d.asset));

  return (
    <div className="pp-overview">
      {/* 净值曲线 */}
      <div className="pp-card pp-card--nav">
        <div className="pp-card__header">
          <h3>净值走势</h3>
          <div className="pp-range">
            {['1M', '3M', '6M', '1Y', 'ALL'].map(r => (
              <button key={r} className={`pp-range__btn ${range === r ? 'active' : ''}`} onClick={() => onRangeChange(r)}>{r}</button>
            ))}
          </div>
        </div>
        {navHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={navHistory}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="trade_date" {...axisProps} />
              <YAxis {...axisProps} domain={['auto', 'auto']} />
              <Tooltip {...tooltipProps} />
              <Line type="monotone" dataKey="nav_cny" stroke={CHART_COLORS[0]} strokeWidth={2} dot={false} name="净值" />
            </LineChart>
          </ResponsiveContainer>
        ) : <StateView state="empty" text="暂无净值数据" />}
      </div>

      <div className="pp-row">
        {/* 配置对比 */}
        <div className="pp-card pp-card--alloc">
          <h3 className="pp-card__title">配置对比 (目标 vs 实际)</h3>
          {items.length > 0 ? (
            <div className="pp-pie-row">
              <div className="pp-pie">
                <h4>目标</h4>
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={targetPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label>
                      {targetPie.map(d => <Cell key={d.name} fill={ASSET_COLORS[d.name]} />)}
                    </Pie>
                    <Tooltip {...tooltipProps} formatter={(v: any) => `${(v * 100).toFixed(1)}%`} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="pp-pie">
                <h4>实际</h4>
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={actualPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label>
                      {actualPie.map(d => <Cell key={d.name} fill={ASSET_COLORS[d.name]} />)}
                    </Pie>
                    <Tooltip {...tooltipProps} formatter={(v: any) => `${(v * 100).toFixed(1)}%`} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : <StateView state="empty" />}
        </div>

        {/* 偏离条形图 */}
        <div className="pp-card pp-card--drift">
          <h3 className="pp-card__title">资产类偏离度 (%)</h3>
          {driftData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={driftData} layout="vertical">
                <CartesianGrid {...gridProps} />
                <XAxis type="number" {...axisProps} />
                <YAxis type="category" dataKey="asset" {...axisProps} width={60} />
                <Tooltip {...tooltipProps} />
                <Bar dataKey="drift">
                  {driftData.map(d => (
                    <Cell key={d.asset} fill={Math.abs(d.drift) > 5 ? '#ee6666' : '#91cc75'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <StateView state="empty" />}
        </div>
      </div>
    </div>
  );
};

// ── 再平衡 Tab ────────────────────────────────────────────────
const RebalanceTab: React.FC<{portfolioId: number; portfolioName: string}> = ({portfolioId, portfolioName}) => {
  const [suggestion, setSuggestion] = useState<RebalanceSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [appliedMsg, setAppliedMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiGet(`/perm-portfolio/portfolios/${portfolioId}/rebalance`);
      setSuggestion(d);
    } catch (e: any) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [portfolioId]);

  useEffect(() => { load(); }, [load]);

  const apply = async () => {
    setApplying(true);
    setAppliedMsg(null);
    try {
      const d = await apiPost(`/perm-portfolio/portfolios/${portfolioId}/rebalance/apply`);
      setAppliedMsg(`已应用 ${d.applied_actions}/${d.total_actions} 条指令`);
      load();
    } catch (e: any) {
      setAppliedMsg(`应用失败: ${e.message}`);
    } finally {
      setApplying(false);
    }
  };

  if (loading) return <StateView state="loading" text="计算再平衡建议…" />;
  if (!suggestion) return <StateView state="empty" />;

  return (
    <div className="pp-rebalance">
      <div className="pp-card">
        <div className="pp-card__header">
          <h3>再平衡建议 — {portfolioName}</h3>
          <div className="pp-rebalance__meta">
            <span>交易日: {suggestion.trade_date}</span>
            <span>总市值: ¥{suggestion.total_value_cny.toFixed(0)}</span>
            <span>最大偏离: {(suggestion.max_drift * 100).toFixed(2)}%</span>
            <span>阈值: {(suggestion.threshold * 100).toFixed(0)}%</span>
          </div>
        </div>

        {suggestion.rebalance_suggested ? (
          <div className="pp-rebalance__alert">配置偏离超过阈值, 建议再平衡</div>
        ) : (
          <div className="pp-rebalance__ok">配置在阈值内, 无需再平衡</div>
        )}

        {/* 资产类偏离表 */}
        <table className="pp-table">
          <thead>
            <tr><th>资产类</th><th>目标权重</th><th>实际权重</th><th>偏离</th></tr>
          </thead>
          <tbody>
            {suggestion.breakdowns.map(b => (
              <tr key={b.asset_class}>
                <td>{b.asset_class}</td>
                <td className="num">{(b.target_weight * 100).toFixed(1)}%</td>
                <td className="num">{(b.actual_weight * 100).toFixed(1)}%</td>
                <td className={`num ${Math.abs(b.drift) > suggestion.threshold ? 'negative' : ''}`}>
                  {(b.drift * 100).toFixed(+2)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* 买卖指令 */}
        {suggestion.actions.length > 0 && (
          <>
            <h4 className="pp-rebalance__actions-title">建议操作 ({suggestion.actions.length} 条)</h4>
            <table className="pp-table">
              <thead>
                <tr><th>操作</th><th>标的</th><th>股数</th><th>金额</th><th>原因</th></tr>
              </thead>
              <tbody>
                {suggestion.actions.map((a, i) => (
                  <tr key={i}>
                    <td className={a.action === 'BUY' ? 'positive' : 'negative'}>{a.action === 'BUY' ? '买入' : '卖出'}</td>
                    <td>{a.symbol}</td>
                    <td className="num">{a.shares_delta}</td>
                    <td className="num">¥{a.value_cny.toFixed(0)}</td>
                    <td className="pp-rebalance__reason">{a.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Button variant="primary" loading={applying} onClick={apply}>
              {applying ? '应用中…' : '应用再平衡建议'}
            </Button>
            {appliedMsg && <div className="pp-rebalance__applied">{appliedMsg}</div>}
          </>
        )}
      </div>
    </div>
  );
};

// ── 持仓 Tab ──────────────────────────────────────────────────
const HoldingsTab: React.FC<{detail: PortfolioDetail; onChanged: () => void}> = ({detail, onChanged}) => {
  const [backtest, setBacktest] = useState<any>(null);
  const [btLoading, setBtLoading] = useState(false);
  const [btError, setBtError] = useState<string | null>(null);
  const [showEditHoldings, setShowEditHoldings] = useState(false);
  const [btCapital, setBtCapital] = useState(String(detail.initial_capital || 100000));
  const [btStart, setBtStart] = useState('2020-01-01');
  const [btEnd, setBtEnd] = useState('2026-12-31');
  const [rolling, setRolling] = useState<any[] | null>(null);
  const [rollLoading, setRollLoading] = useState(false);
  const [rollError, setRollError] = useState<string | null>(null);
  const [rollStart, setRollStart] = useState('2016-01-01');
  const [rollWindow, setRollWindow] = useState('12');

  const runBacktest = async () => {
    setBtLoading(true);
    setBtError(null);
    setBacktest(null);
    try {
      const body: any = {
        start_date: btStart,
        end_date: btEnd,
      };
      const cap = parseFloat(btCapital);
      if (!isNaN(cap) && cap > 0) {
        body.initial_capital = cap;
      }
      const d = await apiPost(`/perm-portfolio/portfolios/${detail.id}/backtest`, body);
      setBacktest(d);
    } catch (e: any) {
      setBtError(e.message);
    } finally {
      setBtLoading(false);
    }
  };

  const runRolling = async () => {
    setRollLoading(true);
    setRollError(null);
    setRolling(null);
    try {
      const d = await apiPost(`/perm-portfolio/portfolios/${detail.id}/rolling-backtest`, {
        start_date: rollStart,
        end_date: btEnd,
        window_months: parseInt(rollWindow) || 12,
      });
      setRolling(d.windows || []);
    } catch (e: any) {
      setRollError(e.message);
    } finally {
      setRollLoading(false);
    }
  };

  const latest = detail.latest_nav;
  const items = latest?.items || [];

  return (
    <div className="pp-holdings">
      <div className="pp-card">
        <div className="pp-card__header">
          <h3 className="pp-card__title">持仓明细</h3>
          <Button variant="secondary" size="sm" onClick={() => setShowEditHoldings(true)}>编辑持仓</Button>
        </div>
        <table className="pp-table">
          <thead>
            <tr>
              <th>标的</th><th>市场</th><th>资产类</th><th>目标权重</th>
              <th>实际权重</th><th>偏离</th><th>股数</th><th>成本</th>
            </tr>
          </thead>
          <tbody>
            {detail.holdings.map(h => {
              const navItem = items.find(i => i.symbol === h.symbol);
              return (
                <tr key={h.id}>
                  <td>{h.name} ({h.symbol})</td>
                  <td>{h.market}</td>
                  <td>{h.asset_class}</td>
                  <td className="num">{(h.target_weight * 100).toFixed(1)}%</td>
                  <td className="num">{navItem ? `${(navItem.actual_weight * 100).toFixed(1)}%` : '-'}</td>
                  <td className={`num ${navItem && Math.abs(navItem.drift) > detail.rebalance_threshold ? 'negative' : ''}`}>
                    {navItem ? `${(navItem.drift * 100).toFixed(2)}%` : '-'}
                  </td>
                  <td className="num">{h.shares}</td>
                  <td className="num">{h.cost_price.toFixed(2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="pp-card">
        <div className="pp-card__header">
          <h3>组合回测</h3>
        </div>
        <div className="pp-backtest__form">
          <label className="pp-form__label">
            初始资金 (CNY)
            <input className="pp-form__input" type="number" min="1" step="1000"
              value={btCapital}
              onChange={e => setBtCapital(e.target.value)} />
          </label>
          <label className="pp-form__label">
            起始日期
            <input className="pp-form__input" type="date"
              value={btStart}
              onChange={e => setBtStart(e.target.value)} />
          </label>
          <label className="pp-form__label">
            结束日期
            <input className="pp-form__input" type="date"
              value={btEnd}
              onChange={e => setBtEnd(e.target.value)} />
          </label>
          <Button variant="primary" loading={btLoading} onClick={runBacktest}>
            {btLoading ? '回测中…' : '运行回测'}
          </Button>
        </div>
        {btError && <div className="pp-error">{btError}</div>}
        {backtest && (
          <div className="pp-backtest">
            <div className="pp-backtest__metrics">
              <div className="pp-metric">
                <span className="pp-metric__label">初始资金</span>
                <span className="pp-metric__value num">¥{Number(backtest.initial_capital).toLocaleString()}</span>
              </div>
              <div className="pp-metric">
                <span className="pp-metric__label">终值</span>
                <span className="pp-metric__value num">¥{Number(backtest.final_equity).toLocaleString()}</span>
              </div>
              <div className="pp-metric">
                <span className="pp-metric__label">总收益</span>
                <span className="pp-metric__value num">{backtest.total_return_pct}%</span>
              </div>
              <div className="pp-metric">
                <span className="pp-metric__label">年化</span>
                <span className="pp-metric__value num">{backtest.cagr}%</span>
              </div>
              <div className="pp-metric">
                <span className="pp-metric__label">最大回撤</span>
                <span className="pp-metric__value num negative">{backtest.max_drawdown}%</span>
              </div>
              <div className="pp-metric">
                <span className="pp-metric__label">夏普</span>
                <span className="pp-metric__value num">{backtest.sharpe_ratio}</span>
              </div>
              <div className="pp-metric">
                <span className="pp-metric__label">波动率</span>
                <span className="pp-metric__value num">{backtest.volatility}%</span>
              </div>
            </div>
            {backtest.equity_curve && backtest.equity_curve.length > 0 && (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={backtest.equity_curve}>
                  <CartesianGrid {...gridProps} />
                  <XAxis dataKey="date" {...axisProps} />
                  <YAxis {...axisProps} />
                  <Tooltip {...tooltipProps} />
                  <Line type="monotone" dataKey="equity" stroke={CHART_COLORS[1]} strokeWidth={2} dot={false} name="权益" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        )}

        {/* ── 任意时段滚动回测 ── */}
        <div className="pp-backtest__divider" />
        <div className="pp-backtest__section">
          <h4 className="pp-backtest__section-title">任意时段滚动回测</h4>
          <p className="pp-form__hint">
            从起始时间按月滚动，每个点 = 该窗口的累计收益率。看策略在不同时段的表现稳定性。
          </p>
          <div className="pp-backtest__form">
            <label className="pp-form__label">
              滚动起始日期
              <input className="pp-form__input" type="date"
                value={rollStart}
                onChange={e => setRollStart(e.target.value)} />
            </label>
            <label className="pp-form__label">
              窗口长度 (月)
              <input className="pp-form__input" type="number" min="1" max="60"
                value={rollWindow}
                onChange={e => setRollWindow(e.target.value)} />
            </label>
            <label className="pp-form__label">
              结束日期
              <input className="pp-form__input" type="date"
                value={btEnd}
                onChange={e => setBtEnd(e.target.value)} />
            </label>
            <Button variant="primary" loading={rollLoading} onClick={runRolling}>
              {rollLoading ? '计算中…' : '运行滚动回测'}
            </Button>
          </div>
          {rollError && <div className="pp-error">{rollError}</div>}
          {rolling && rolling.length > 0 && (
            <>
              <div className="pp-backtest__roll-stats">
                <span>窗口数: {rolling.length}</span>
                <span>平均收益: {(rolling.reduce((s, w) => s + w.return_pct, 0) / rolling.length).toFixed(2)}%</span>
                <span>最佳: {Math.max(...rolling.map(w => w.return_pct)).toFixed(2)}%</span>
                <span>最差: {Math.min(...rolling.map(w => w.return_pct)).toFixed(2)}%</span>
                <span>胜率: {(rolling.filter(w => w.return_pct > 0).length / rolling.length * 100).toFixed(0)}%</span>
              </div>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={rolling}>
                  <CartesianGrid {...gridProps} />
                  <XAxis dataKey="start" {...axisProps} />
                  <YAxis {...axisProps} unit="%" />
                  <Tooltip
                    {...tooltipProps}
                    formatter={(v: any) => `${v}%`}
                  />
                  <ReferenceLine y={0} stroke={chartBorderStrong} strokeDasharray="2 2" />
                  <Line type="monotone" dataKey="return_pct" stroke={colorUp} strokeWidth={2} dot={{r: 2}} name="窗口收益率" />
                </LineChart>
              </ResponsiveContainer>
            </>
          )}
          {rolling && rolling.length === 0 && <StateView state="empty" text="该时段无足够数据" />}
        </div>
      </div>

      {showEditHoldings && (
        <EditHoldingsModal
          detail={detail}
          onClose={() => setShowEditHoldings(false)}
          onChanged={() => {
            setShowEditHoldings(false);
            onChanged();
          }}
        />
      )}
    </div>
  );
};

// ── 标的池管理弹窗 ─────────────────────────────────────────────
const InstrumentManagerModal: React.FC<{
  instruments: Instrument[];
  onClose: () => void;
  onChanged: () => void;
}> = ({instruments, onClose, onChanged}) => {
  const [symbol, setSymbol] = useState('');
  const [market, setMarket] = useState('A');
  const [assetClass, setAssetClass] = useState('equity');
  const [ccy, setCcy] = useState('CNY');
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const ccyByMarket: Record<string, string> = {A: 'CNY', HK: 'HKD', US: 'USD'};
  const onMarketChange = (m: string) => {
    setMarket(m);
    setCcy(ccyByMarket[m] || 'CNY');
  };

  const handleAdd = async () => {
    if (!symbol.trim() || !name.trim()) {
      setMsg('代码和名称必填');
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      await apiPost('/perm-portfolio/instruments', {
        symbol: symbol.trim().toUpperCase(),
        market, asset_class: assetClass, ccy, name: name.trim(),
      });
      setSymbol(''); setName('');
      onChanged();
      setMsg('添加成功');
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number, sym: string) => {
    if (!confirm(`确认删除标的 ${sym}？被组合引用时无法删除。`)) return;
    try {
      await apiDelete(`/perm-portfolio/instruments/${id}`);
      onChanged();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const handleToggle = async (inst: Instrument) => {
    try {
      await apiPut(`/perm-portfolio/instruments/${inst.id}`, {enabled: !inst.enabled});
      onChanged();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  return (
    <Modal
      open
      title="标的池管理"
      onClose={onClose}
      width={760}
      footer={<Button variant="secondary" onClick={onClose}>关闭</Button>}
    >

        <div className="pp-form">
          <div className="pp-form__row">
            <label className="pp-form__label">代码 *
              <input className="pp-form__input" value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="如 sh510300 / 02800 / VOO" />
            </label>
            <label className="pp-form__label">市场
              <select className="pp-form__select" value={market} onChange={e => onMarketChange(e.target.value)}>
                <option value="A">A 股</option>
                <option value="HK">港股</option>
                <option value="US">美股</option>
              </select>
            </label>
            <label className="pp-form__label">资产类
              <select className="pp-form__select" value={assetClass} onChange={e => setAssetClass(e.target.value)}>
                <option value="equity">股票</option>
                <option value="bond">债券</option>
                <option value="gold">黄金</option>
                <option value="cash">现金</option>
              </select>
            </label>
            <label className="pp-form__label">币种
              <select className="pp-form__select" value={ccy} onChange={e => setCcy(e.target.value)}>
                <option value="CNY">CNY</option>
                <option value="HKD">HKD</option>
                <option value="USD">USD</option>
              </select>
            </label>
            <label className="pp-form__label">名称 *
              <input className="pp-form__input" value={name} onChange={e => setName(e.target.value)} placeholder="如 沪深300ETF" />
            </label>
            <Button variant="primary" loading={saving} onClick={handleAdd}>
              {saving ? '添加中…' : '添加'}
            </Button>
          </div>
          {msg && <div className="pp-form__msg">{msg}</div>}
        </div>

        <table className="pp-table pp-modal__table">
          <thead>
            <tr><th>代码</th><th>市场</th><th>资产类</th><th>币种</th><th>名称</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            {instruments.map(i => (
              <tr key={i.id}>
                <td>{i.symbol}</td>
                <td>{i.market}</td>
                <td>{i.asset_class}</td>
                <td>{i.ccy}</td>
                <td>{i.name}</td>
                <td>
                  <span className={`pp-status ${i.enabled ? 'pp-status--on' : 'pp-status--off'}`}>
                    {i.enabled ? '启用' : '停用'}
                  </span>
                </td>
                <td>
                  <Button variant="secondary" size="sm" onClick={() => handleToggle(i)}>{i.enabled ? '停用' : '启用'}</Button>
                  {' '}
                  <Button variant="danger" size="sm" onClick={() => handleDelete(i.id, i.symbol)}>删除</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

    </Modal>
  );
};

// ── 新建组合弹窗 ───────────────────────────────────────────────
const CreatePortfolioModal: React.FC<{
  instruments: Instrument[];
  onClose: () => void;
  onCreated: (newId: number) => void;
  onLoadInstruments: () => void;
}> = ({instruments, onClose, onCreated, onLoadInstruments}) => {
  const [name, setName] = useState('');
  const [strategyType, setStrategyType] = useState('custom');
  const [initialCapital, setInitialCapital] = useState('100000');
  const [threshold, setThreshold] = useState('0.05');
  const [selected, setSelected] = useState<Record<number, number>>({}); // {instrument_id: weight}
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    onLoadInstruments();
  }, []);

  const totalWeight = Object.values(selected).reduce((s, w) => s + w, 0);

  const toggleInstrument = (id: number) => {
    setSelected(prev => {
      const next = {...prev};
      if (id in next) delete next[id];
      else next[id] = 0; // 默认0, 让用户填
      return next;
    });
  };

  const setWeight = (id: number, w: number) => {
    setSelected(prev => ({...prev, [id]: w}));
  };

  const equalWeight = () => {
    const ids = Object.keys(selected);
    if (ids.length === 0) return;
    const w = 1 / ids.length;
    const next: Record<number, number> = {};
    ids.forEach(id => next[+id] = w);
    setSelected(next);
  };

  const handleCreate = async () => {
    if (!name.trim()) {
      setError('请填写组合名称');
      return;
    }
    const capital = parseFloat(initialCapital);
    const thresh = parseFloat(threshold);
    if (isNaN(capital) || capital <= 0) {
      setError('初始资金无效');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const holdings = Object.entries(selected).map(([id, w]) => ({
        instrument_id: parseInt(id),
        target_weight: w,
      }));
      const data = await apiPost('/perm-portfolio/portfolios', {
        name: name.trim(),
        strategy_type: strategyType,
        initial_capital: capital,
        rebalance_threshold: thresh,
        holdings,
      });
      onCreated(data.id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      title="新建组合"
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button variant="primary" loading={saving} onClick={handleCreate}>
            {saving ? '创建中…' : '创建组合'}
          </Button>
        </>
      }
    >

        <div className="pp-form">
          <div className="pp-form__row">
            <label className="pp-form__label">组合名称 *
              <input className="pp-form__input" value={name} onChange={e => setName(e.target.value)} placeholder="如 我的永久组合" />
            </label>
            <label className="pp-form__label">策略类型
              <select className="pp-form__select" value={strategyType} onChange={e => setStrategyType(e.target.value)}>
                <option value="custom">自定义</option>
                <option value="permanent">永久组合(25/25/25/25)</option>
                <option value="all_weather">全天候</option>
                <option value="golden_butterfly">黄金蝴蝶</option>
              </select>
            </label>
            <label className="pp-form__label">初始资金 (CNY)
              <input className="pp-form__input" value={initialCapital} onChange={e => setInitialCapital(e.target.value)} type="number" />
            </label>
            <label className="pp-form__label">再平衡阈值
              <input className="pp-form__input" value={threshold} onChange={e => setThreshold(e.target.value)} type="number" step="0.01" />
            </label>
          </div>
        </div>

        <div className="pp-form__section">
          <div className="pp-form__section-head">
            <h4>选择持仓标的 + 目标权重</h4>
            <div className="pp-weight-badge-wrap">
              {Object.keys(selected).length > 0 && (
                <Button variant="secondary" size="sm" onClick={equalWeight}>等权分配</Button>
              )}
              <span className={`pp-weight-badge ${Math.abs(totalWeight - 1) > 0.001 ? 'pp-weight-badge--warn' : ''}`}>
                权重总和: {(totalWeight * 100).toFixed(1)}%
              </span>
            </div>
          </div>
          <div className="pp-instrument-pick">
            {instruments.map(inst => (
              <div key={inst.id} className={`pp-instrument-pick__item ${inst.id in selected ? 'pp-instrument-pick__item--on' : ''}`}>
                <label className="pp-instrument-pick__check">
                  <input type="checkbox" checked={inst.id in selected} onChange={() => toggleInstrument(inst.id)} />
                  <span className="pp-instrument-pick__label">
                    {inst.name} <span className="pp-instrument-pick__meta">[{inst.market}/{inst.asset_class}] {inst.symbol}</span>
                  </span>
                </label>
                {inst.id in selected && (
                  <input
                    className="pp-form__input pp-instrument-pick__weight"
                    type="number" step="0.01" min="0" max="1"
                    value={selected[inst.id]}
                    onChange={e => setWeight(inst.id, parseFloat(e.target.value) || 0)}
                    placeholder="权重"
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        {error && <div className="pp-error">{error}</div>}
        <p className="pp-form__hint">
          股数会自动按 初始资金 × 权重 / 最近收盘价 计算。创建后可在持仓 Tab 手动调整。
        </p>
    </Modal>
  );
};

// ── 编辑持仓弹窗 ───────────────────────────────────────────────
const EditHoldingsModal: React.FC<{
  detail: PortfolioDetail;
  onClose: () => void;
  onChanged: () => void;
}> = ({detail, onClose, onChanged}) => {
  const [rows, setRows] = useState<Array<{
    instrument_id: number;
    target_weight: number;
    shares: number;
    cost_price: number;
    symbol?: string;
  }>>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);

  useEffect(() => {
    setRows(detail.holdings.map(h => ({
      instrument_id: h.instrument_id,
      target_weight: h.target_weight,
      shares: h.shares,
      cost_price: h.cost_price,
      symbol: h.symbol || undefined,
    })));
    apiGet('/perm-portfolio/instruments').then(setInstruments).catch(() => {});
  }, []);

  const updateRow = (idx: number, patch: Partial<typeof rows[0]>) => {
    setRows(prev => prev.map((r, i) => i === idx ? {...r, ...patch} : r));
  };
  const removeRow = (idx: number) => {
    setRows(prev => prev.filter((_, i) => i !== idx));
  };
  const addRow = () => {
    if (instruments.length === 0) return;
    setRows(prev => [...prev, {
      instrument_id: instruments[0].id,
      target_weight: 0, shares: 0, cost_price: 0,
    }]);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await apiPut(`/perm-portfolio/portfolios/${detail.id}`, {holdings: rows});
      onChanged();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const totalWeight = rows.reduce((s, r) => s + r.target_weight, 0);

  return (
    <Modal
      open
      title={`编辑持仓 — ${detail.name}`}
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button variant="primary" loading={saving} onClick={handleSave}>
            {saving ? '保存中…' : '保存'}
          </Button>
        </>
      }
    >

        <table className="pp-table pp-edit-table">
          <thead>
            <tr>
              <th>标的</th><th>目标权重</th><th>股数</th><th>成本价</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, idx) => (
              <tr key={idx}>
                <td>
                  <select
                    className="pp-form__select"
                    value={r.instrument_id}
                    onChange={e => updateRow(idx, {instrument_id: parseInt(e.target.value)})}
                  >
                    {instruments.map(inst => (
                      <option key={inst.id} value={inst.id}>
                        {inst.name} [{inst.market}/{inst.symbol}]
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input className="pp-form__input pp-edit-input" type="number" step="0.01" min="0" max="1"
                    value={r.target_weight}
                    onChange={e => updateRow(idx, {target_weight: parseFloat(e.target.value) || 0})} />
                </td>
                <td>
                  <input className="pp-form__input pp-edit-input" type="number"
                    value={r.shares}
                    onChange={e => updateRow(idx, {shares: parseInt(e.target.value) || 0})} />
                </td>
                <td>
                  <input className="pp-form__input pp-edit-input" type="number" step="0.01"
                    value={r.cost_price}
                    onChange={e => updateRow(idx, {cost_price: parseFloat(e.target.value) || 0})} />
                </td>
                <td>
                  <Button variant="danger" size="sm" onClick={() => removeRow(idx)}>删除</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <Button variant="secondary" size="sm" onClick={addRow}>添加持仓</Button>

        <div className="pp-weight-badge-wrap">
          <span className={`pp-weight-badge ${Math.abs(totalWeight - 1) > 0.001 ? 'pp-weight-badge--warn' : ''}`}>
            权重总和: {(totalWeight * 100).toFixed(1)}%
          </span>
        </div>

        {error && <div className="pp-error">{error}</div>}
        <p className="pp-form__hint">
          保存会全量替换该组合的全部持仓。修改股数后需手动重跑净值同步才能看到净值变化。
        </p>
    </Modal>
  );
};
