import {useReplayStore, viewDate} from './store';

const fmt = (v: number) =>
  v.toLocaleString('zh-CN', {maximumFractionDigits: 0});

export const TopBar: React.FC = () => {
  const session = useReplayStore((s) => s.session);
  const cursor = useReplayStore((s) => s.cursor);
  const datesLen = useReplayStore((s) => s.dates.length);
  const vd = useReplayStore(viewDate);
  const cash = useReplayStore((s) => s.cash);
  const nav = useReplayStore((s) => s.nav);
  const error = useReplayStore((s) => s.error);
  const closeSession = useReplayStore((s) => s.closeSession);
  const reveal = useReplayStore((s) => s.reveal);
  if (!session) return null;
  const lastNav = nav[nav.length - 1];
  const total = lastNav ? lastNav.value : session.initial_capital;
  const ret = total / session.initial_capital - 1;
  const retCls = ret >= 0 ? 'is-up' : 'is-down';
  return (
    <div className="replay-top">
      <b>✈ {session.name}</b>
      <span className="stat">日期<b>{vd}</b></span>
      <span className="stat">第<b>{cursor + 1}</b>/{datesLen} 个交易日</span>
      <span className="stat">现金<b>{fmt(cash)}</b></span>
      <span className="stat">总资产<b>{fmt(total)}</b></span>
      <span className="stat">收益
        <b className={retCls}>{(ret * 100).toFixed(2)}%</b>
      </span>
      <span style={{flex: 1}} />
      {error && <span className="replay-error">{error}</span>}
      <button className="replay-btn" onClick={() => {
        if (window.confirm('揭晓后不可回到盲盒训练，确定揭晓？')) void reveal();
      }}>
        揭晓复盘
      </button>
      <button className="replay-btn"
        onClick={() => { void useReplayStore.getState().saveNow(); closeSession(); }}>
        离舱
      </button>
    </div>
  );
};
