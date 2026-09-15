import {useMemo} from 'react';
import {
  Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  axisProps, colorDown, colorUp, tooltipProps,
} from '../../lib/chartTheme';
import {ReplayKlineChart} from './ReplayKlineChart';
import {
  annualizedReturn, maxDrawdown, roundTrips, winRate,
} from './engine/nav';
import {useReplayStore} from './store';

const pctFmt = (v: number | null) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;

export const ReviewView: React.FC = () => {
  const session = useReplayStore((s) => s.session);
  const pool = useReplayStore((s) => s.pool);
  const names = useReplayStore((s) => s.names);
  const barsBySymbol = useReplayStore((s) => s.barsBySymbol);
  const benchmarkBars = useReplayStore((s) => s.benchmarkBars);
  const nav = useReplayStore((s) => s.nav);
  const trades = useReplayStore((s) => s.trades);
  const selected = useReplayStore((s) => s.selectedSymbol);
  const selectSymbol = useReplayStore((s) => s.selectSymbol);
  const closeSession = useReplayStore((s) => s.closeSession);

  const stats = useMemo(() => {
    if (!session || nav.length === 0) return null;
    const lastNav = nav[nav.length - 1];
    if (!lastNav) return null;
    const initial = session.initial_capital;
    const final = lastNav.value;
    const total = final / initial - 1;
    const days = nav.length;
    const b0 = benchmarkBars.find((b) => b.trade_date >= session.start_date);
    // 终审 I3：基准窗口钳到 nav 末日期（揭晓后拉到 end_date/今天的全量 K 线，
    // 末根基准可能远超组合终点，超额收益口径需对齐）
    const navEnd = lastNav.date;
    const b1 = [...benchmarkBars].reverse().find(
      (b) => b.trade_date <= navEnd);
    const benchRet = b0 && b1 ? b1.close / b0.close - 1 : null;
    return {
      total,
      annualized: annualizedReturn(initial, final, days),
      mdd: maxDrawdown(nav),
      winRate: winRate(trades),
      trips: roundTrips(trades).length,
      benchRet,
      excess: benchRet == null ? null : total - benchRet,
    };
  }, [session, nav, trades, benchmarkBars]);

  const curve = useMemo(() => {
    if (!session) return [];
    const initial = session.initial_capital;
    const b0 = benchmarkBars.find(
      (b) => b.trade_date >= session.start_date);
    const bClose = new Map(benchmarkBars.map((b) => [b.trade_date, b.close]));
    return nav.map((p) => {
      const bc = b0 ? bClose.get(p.date) : undefined;
      return {
        date: p.date,
        nav: +(p.value / initial).toFixed(4),
        benchmark: b0 && bc != null ? +(bc / b0.close).toFixed(4) : null,
      };
    });
  }, [session, nav, benchmarkBars]);

  if (!session) return null;
  const symbolTrades = trades.filter((t) => t.symbol === selected);
  return (
    <>
      <div className="replay-top">
        <b>✈ {session.name} · 复盘</b>
        <span className="stat">
          区间<b>{session.start_date} ~ {nav[nav.length - 1]?.date}</b>
        </span>
        <span style={{flex: 1}} />
        <button className="replay-btn" onClick={closeSession}>
          返回旅程列表
        </button>
      </div>
      {stats && (
        <div className="replay-stats">
          {([
            ['总收益', pctFmt(stats.total),
              stats.total >= 0 ? colorUp : colorDown],
            ['年化', pctFmt(stats.annualized), undefined],
            ['最大回撤', `-${(stats.mdd * 100).toFixed(2)}%`, colorDown],
            ['胜率(平仓)', stats.winRate == null
              ? '—' : `${(stats.winRate * 100).toFixed(0)}% (${stats.trips}次)`,
              undefined],
            ['超额(vs 基准)', pctFmt(stats.excess), undefined],
          ] as const).map(([label, value, color]) => (
            <div key={label} className="replay-gauge">
              <span className="label">{label}</span>
              <span className="value" style={{color}}>{value}</span>
            </div>
          ))}
        </div>
      )}
      <div className="replay-panel" style={{marginBottom: 10, height: 220}}>
        <h4>净值 vs 基准（归一）</h4>
        <ResponsiveContainer width="100%" height={170}>
          <LineChart data={curve}>
            <XAxis dataKey="date" {...axisProps} minTickGap={60} />
            <YAxis {...axisProps} domain={['auto', 'auto']} />
            <Tooltip {...tooltipProps} />
            <Line type="monotone" dataKey="nav" name="本组合"
              stroke="#0a84ff" dot={false} strokeWidth={1.5} />
            <Line type="monotone" dataKey="benchmark" name="基准"
              stroke="#a1a1a6" dot={false} strokeWidth={1}
              strokeDasharray="4 3" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="replay-panel" style={{marginBottom: 10}}>
        <h4>
          买卖点回顾{' '}
          <select className="replay-input"
            style={{width: 220, display: 'inline-block', marginBottom: 0}}
            value={selected ?? ''}
            onChange={(e) => selectSymbol(e.target.value)}>
            {pool.map((s) => (
              <option key={s} value={s}>{names[s] ?? ''} {s}</option>
            ))}
          </select>
        </h4>
        {selected && (
          <ReplayKlineChart
            bars={barsBySymbol[selected] ?? []}
            trades={symbolTrades}
            height={380}
          />
        )}
      </div>
      <div className="replay-panel">
        <h4>成交清单（含下单理由）</h4>
        <table className="replay-table">
          <thead>
            <tr>
              <th>日期</th><th>标的</th><th>方向</th><th>价格</th>
              <th>股数</th><th>佣金</th><th>印花税</th><th>理由</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={t.id ?? i}>
                <td>{t.trade_date}</td>
                <td>{t.symbol}</td>
                <td className={t.side === 'buy' ? 'is-up' : 'is-down'}>
                  {t.side === 'buy' ? '买入' : '卖出'}
                </td>
                <td>{t.price.toFixed(2)}</td>
                <td>{t.shares}</td>
                <td>{t.fee.toFixed(2)}</td>
                <td>{t.tax.toFixed(2)}</td>
                <td style={{textAlign: 'left'}}>{t.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
};
