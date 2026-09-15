import {useState} from 'react';
import {AddStockModal} from './AddStockModal';
import {useReplayStore, viewDate} from './store';
import type {ReplayBar} from './types';

const pct = (bars: ReplayBar[], vd: string | null) => {
  const vis = bars.filter((b) => !vd || b.trade_date <= vd);
  if (vis.length < 2) return null;
  const a = vis[vis.length - 2]?.close;
  const b = vis[vis.length - 1]?.close;
  if (a == null || b == null) return null;
  return a > 0 ? (b / a - 1) * 100 : null;
};

export const PoolPanel: React.FC = () => {
  const pool = useReplayStore((s) => s.pool);
  const names = useReplayStore((s) => s.names);
  const barsBySymbol = useReplayStore((s) => s.barsBySymbol);
  const positions = useReplayStore((s) => s.positions);
  const selected = useReplayStore((s) => s.selectedSymbol);
  const vd = useReplayStore(viewDate);
  const selectSymbol = useReplayStore((s) => s.selectSymbol);
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div className="replay-panel">
      <h4>
        股票池{' '}
        <button className="replay-btn" style={{float: 'right'}}
          onClick={() => setShowAdd(true)}>
          + 加股
        </button>
      </h4>
      {pool.length === 0 && (
        <div className="replay-hint">池子还空着，点「+ 加股」开始。</div>
      )}
      {pool.map((sym) => {
        const p = pct(barsBySymbol[sym] ?? [], vd);
        return (
          <div key={sym}
            className={`replay-pool-item${sym === selected ? ' active' : ''}`}
            onClick={() => selectSymbol(sym)}>
            <span>{names[sym] ? `${names[sym]} ` : ''}{sym}</span>
            <span className={p == null ? '' : p >= 0 ? 'is-up' : 'is-down'}>
              {p == null ? '—' : `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`}
            </span>
          </div>
        );
      })}
      <h4 style={{marginTop: 14}}>持仓</h4>
      {positions.length === 0 ? (
        <div className="replay-hint">空仓</div>
      ) : (
        <table className="replay-table">
          <thead>
            <tr><th>标的</th><th>股数</th><th>成本</th><th>现价</th><th>浮盈</th></tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const bars = (barsBySymbol[p.symbol] ?? []).filter(
                (b) => !vd || b.trade_date <= vd);
              const lastBar = bars.length ? bars[bars.length - 1] : undefined;
              const last = lastBar ? lastBar.close : null;
              const pnl = last == null || p.shares === 0
                ? null : (last / p.cost_price - 1) * 100;
              return (
                <tr key={p.symbol} style={{cursor: 'pointer'}}
                  onClick={() => selectSymbol(p.symbol)}>
                  <td>{p.symbol}</td>
                  <td>{p.shares}</td>
                  <td>{p.cost_price.toFixed(2)}</td>
                  <td>{last == null ? '—' : last.toFixed(2)}</td>
                  <td className={pnl == null ? '' : pnl >= 0 ? 'is-up' : 'is-down'}>
                    {pnl == null ? '—' : `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <AddStockModal open={showAdd} onClose={() => setShowAdd(false)} />
    </div>
  );
};
