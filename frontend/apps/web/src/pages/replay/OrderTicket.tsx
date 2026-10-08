import {useMemo, useState} from 'react';
import {useDayLabel} from './BlindMask';
import {useReplayStore, viewDate} from './store';
import type {ReplayBar} from './types';

// selector 必须返回稳定引用：zustand v5 直接透传 useSyncExternalStore，
// 每次返回新数组会被 React 判定为快照持续变化，触发无限重渲染
const NO_BARS: ReplayBar[] = [];

/** exam 下单前端校验（后端仍硬校验）。 */
export const validateExamOrder = (
  note: string,
  orderType: 'market' | 'limit',
  limitPrice: number | null,
): string | null => {
  const n = note.trim();
  if (n.length < 1 || n.length > 140) return '下单理由必填（1~140 字）';
  if (orderType === 'limit' && (limitPrice == null || !(limitPrice > 0))) {
    return '限价应为正数';
  }
  return null;
};

export const OrderTicket: React.FC = () => {
  const symbol = useReplayStore((s) => s.selectedSymbol);
  const names = useReplayStore((s) => s.names);
  const industries = useReplayStore((s) => s.industries);
  const cash = useReplayStore((s) => s.cash);
  const frozenCash = useReplayStore((s) => s.frozenCash);
  const positions = useReplayStore((s) => s.positions);
  const pending = useReplayStore((s) => s.pending);
  const mode = useReplayStore((s) => s.mode);
  const segments = useReplayStore((s) => s.segments);
  const bars = useReplayStore((s) =>
    (s.selectedSymbol ? s.barsBySymbol[s.selectedSymbol] : undefined) ??
    NO_BARS);
  const vd = useReplayStore(viewDate);
  const dayLabel = useDayLabel();
  const atLatest = useReplayStore((s) => s.cursor === s.dates.length - 1);
  const placeOrder = useReplayStore((s) => s.placeOrder);
  const [shares, setShares] = useState(100);
  const [note, setNote] = useState('');
  const [orderType, setOrderType] = useState<'market' | 'limit'>('market');
  const [limitPrice, setLimitPrice] = useState('');
  const [confidence, setConfidence] = useState('');
  const [busy, setBusy] = useState(false);

  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  const lastVis = vis[vis.length - 1];
  const today = lastVis && lastVis.trade_date === vd ? lastVis : null;
  const exam = mode === 'exam';
  const segs = exam && symbol ? segments[symbol] : undefined;
  const curPrice = segs && segs.length ? segs[segs.length - 1].close
    : today ? today.close : null;
  const frozenSell = pending
    .filter((o) => o.symbol === symbol && o.side === 'sell')
    .reduce((a, o) => a + o.shares, 0);
  const pos = positions.find((p) => p.symbol === symbol);
  const sellable = pos && vd && pos.buy_date < vd
    ? pos.shares - frozenSell : 0;
  const maxBuy = curPrice
    ? Math.floor((exam ? cash - frozenCash : cash) / (curPrice * 100)) * 100
    : 0;

  const submit = async (side: 'buy' | 'sell') => {
    if (exam) {
      const err = validateExamOrder(
        note, orderType,
        orderType === 'limit' ? Number(limitPrice) : null);
      if (err) return; // 按钮已 disable，双保险
    }
    setBusy(true);
    const ok = await placeOrder(side, shares, exam
      ? {
        note,
        orderType,
        ...(orderType === 'limit'
          ? {limitPrice: Number(limitPrice)} : {}),
        ...(confidence ? {confidence: Number(confidence)} : {}),
      }
      : {note: note || undefined});
    if (ok) setNote('');
    setBusy(false);
  };

  const invalid = exam
    ? validateExamOrder(
      note, orderType, orderType === 'limit' ? Number(limitPrice) : null)
    : null;

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
      <h4>下单台 · {names[symbol] ?? ''} {symbol}
        {industries[symbol] && (
          <span className="replay-ind-tag">{industries[symbol]}</span>
        )}
      </h4>
      <div className="replay-hint" style={{marginBottom: 8}}>
        {exam
          ? `${dayLabel(vd)} 现价 ¥${curPrice?.toFixed(2) ?? '—'}`
          : today
            ? `${vd} 收盘价 ¥${today.close.toFixed(2)}（尾盘价成交）`
            : `${vd} 停牌/无数据`}
      </div>
      {exam && (
        <div style={{display: 'flex', gap: 8, marginBottom: 8}}>
          {(['market', 'limit'] as const).map((t) => (
            <button key={t}
              className={`replay-btn${orderType === t ? ' primary' : ''}`}
              style={{flex: 1}}
              onClick={() => {
                setOrderType(t);
                if (t === 'limit' && !limitPrice && curPrice != null) {
                  setLimitPrice(curPrice.toFixed(2));
                }
              }}>
              {t === 'market' ? '市价' : '限价'}
            </button>
          ))}
        </div>
      )}
      {exam && orderType === 'limit' && (
        <input className="replay-input" type="number" min={0.01} step={0.01}
          value={limitPrice}
          onChange={(e) => setLimitPrice(e.target.value)}
          placeholder="限价（当日涨跌停区间内）" />
      )}
      <input className="replay-input" type="number" min={100} step={100}
        value={shares} onChange={(e) => setShares(Number(e.target.value))}
        placeholder="股数（100 的整数倍）" />
      <input className="replay-input" value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={exam ? '下单理由（必填，≤140字，复盘回看）'
          : '下单理由（复盘时回看，可空）'} />
      {exam && (
        <select className="replay-input" value={confidence}
          onChange={(e) => setConfidence(e.target.value)}>
          <option value="">信心度(可选)</option>
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>信心 {n}</option>
          ))}
        </select>
      )}
      <div className="replay-hint" style={{marginBottom: 8}}>
        可买 {Math.max(0, maxBuy)} 股 · 可卖 {Math.max(0, sellable)} 股
        {exam ? '（T+1，含挂单冻结）' : '（T+1）'}
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <button className="replay-btn buy" style={{flex: 1}}
          disabled={busy || !atLatest || !curPrice || !!invalid}
          onClick={() => void submit('buy')}>
          买入
        </button>
        <button className="replay-btn sell" style={{flex: 1}}
          disabled={busy || !atLatest || !curPrice || !!invalid
            || sellable <= 0}
          onClick={() => void submit('sell')}>
          卖出
        </button>
      </div>
      {invalid && (
        <div className="replay-hint" style={{marginTop: 6, color: '#e0413e'}}>
          {invalid}
        </div>
      )}
      {!atLatest && (
        <div className="replay-hint" style={{marginTop: 6}}>
          回看中，回到最新一天才能交易。
        </div>
      )}
    </div>
  );
};
