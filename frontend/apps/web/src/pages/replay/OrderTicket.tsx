import {useMemo, useState} from 'react';
import {useReplayStore, viewDate} from './store';
import type {ReplayBar} from './types';

// selector 必须返回稳定引用：zustand v5 直接透传 useSyncExternalStore，
// 每次返回新数组会被 React 判定为快照持续变化，触发无限重渲染
const NO_BARS: ReplayBar[] = [];

export const OrderTicket: React.FC = () => {
  const symbol = useReplayStore((s) => s.selectedSymbol);
  const names = useReplayStore((s) => s.names);
  const cash = useReplayStore((s) => s.cash);
  const positions = useReplayStore((s) => s.positions);
  const bars = useReplayStore((s) =>
    (s.selectedSymbol ? s.barsBySymbol[s.selectedSymbol] : undefined) ??
    NO_BARS);
  const vd = useReplayStore(viewDate);
  const atLatest = useReplayStore((s) => s.cursor === s.dates.length - 1);
  const placeOrder = useReplayStore((s) => s.placeOrder);
  const [shares, setShares] = useState(100);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  const lastVis = vis[vis.length - 1];
  const today = lastVis && lastVis.trade_date === vd ? lastVis : null;
  const pos = positions.find((p) => p.symbol === symbol);
  const sellable = pos && vd && pos.buy_date < vd ? pos.shares : 0;
  const maxBuy = today ? Math.floor(cash / (today.close * 100)) * 100 : 0;

  const submit = async (side: 'buy' | 'sell') => {
    setBusy(true);
    const ok = await placeOrder(side, shares, note || undefined);
    if (ok) setNote('');
    setBusy(false);
  };

  if (!symbol) {
    return (
      <div className="replay-panel">
        <h4>下单台</h4>
        <div className="replay-hint">先在左侧选一只股票。</div>
      </div>
    );
  }
  return (
    <div className="replay-panel">
      <h4>下单台 · {names[symbol] ?? ''} {symbol}</h4>
      <div className="replay-hint" style={{marginBottom: 8}}>
        {today
          ? `${vd} 收盘价 ¥${today.close.toFixed(2)}（尾盘价成交）`
          : `${vd} 停牌/无数据`}
      </div>
      <input className="replay-input" type="number" min={100} step={100}
        value={shares} onChange={(e) => setShares(Number(e.target.value))}
        placeholder="股数（100 的整数倍）" />
      <input className="replay-input" value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="下单理由（复盘时回看，可空）" />
      <div className="replay-hint" style={{marginBottom: 8}}>
        可买 {maxBuy} 股 · 可卖 {sellable} 股（T+1）
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <button className="replay-btn buy" style={{flex: 1}}
          disabled={busy || !atLatest || !today}
          onClick={() => void submit('buy')}>
          买入
        </button>
        <button className="replay-btn sell" style={{flex: 1}}
          disabled={busy || !atLatest || !today || sellable === 0}
          onClick={() => void submit('sell')}>
          卖出
        </button>
      </div>
      {!atLatest && (
        <div className="replay-hint" style={{marginTop: 6}}>
          回看中，回到最新一天才能交易。
        </div>
      )}
    </div>
  );
};
