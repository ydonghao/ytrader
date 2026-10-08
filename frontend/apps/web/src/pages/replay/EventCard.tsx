import {useReplayStore} from './store';

const ICON: Record<string, string> = {
  dividend: '💰', split: '🎁', order_cancelled: '↩️',
  suspended: '⏸', info: 'ℹ️',
};

export const EventCard: React.FC = () => {
  const events = useReplayStore((s) => s.examEvents);
  const pending = useReplayStore((s) => s.pending);
  if (events.length === 0 && pending.length === 0) return null;
  return (
    <div className="replay-panel">
      <h4>今日事件 · 挂单</h4>
      {events.map((e, i) => (
        <div key={i} className="replay-hint"
          style={{textAlign: 'left', marginBottom: 2}}>
          {ICON[e.type] ?? '·'} {e.symbol ? `${e.symbol} ` : ''}{e.msg}
        </div>
      ))}
      {pending.map((o) => (
        <div key={o.id} className="replay-hint"
          style={{textAlign: 'left', marginBottom: 2}}>
          📌 限价{o.side === 'buy' ? '买' : '卖'} {o.shares}股 @{' '}
          {o.limit_price}
        </div>
      ))}
    </div>
  );
};
