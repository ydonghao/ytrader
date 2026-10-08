import {INDEX_NAMES, INDEX_SYMBOLS, useReplayStore, viewDate} from './store';
import type {ReplayBar} from './types';

// selector 必须返回稳定引用：zustand v5 直接透传 useSyncExternalStore，
// 每次返回新数组会被 React 判定为快照持续变化，触发无限重渲染
const NO_IDX: ReplayBar[] = [];

const pctOf = (bars: ReplayBar[], vd: string | null) => {
  const vis = bars.filter((b) => !vd || b.trade_date <= vd);
  if (vis.length < 2) return null;
  const a = vis[vis.length - 2]?.close;
  const b = vis[vis.length - 1]?.close;
  if (a == null || b == null) return null;
  return a > 0 ? (b / a - 1) * 100 : null;
};

export const IndexStrip: React.FC = () => {
  const indexBars = useReplayStore((s) => s.indexBars);
  const vd = useReplayStore(viewDate);
  return (
    <div className="replay-indices">
      {INDEX_SYMBOLS.map((sym) => {
        const bars = indexBars[sym] ?? NO_IDX;
        const vis = bars.filter((b) => !vd || b.trade_date <= vd);
        const lastBar = vis.length ? vis[vis.length - 1] : undefined;
        const close = lastBar ? lastBar.close : null;
        const p = pctOf(bars, vd);
        return (
          <span className="idx" key={sym}>
            <span style={{color: '#86868b'}}>{INDEX_NAMES[sym]}</span>
            <b>{close == null ? '—' : close.toFixed(2)}</b>
            <span className={p == null ? '' : p >= 0 ? 'is-up' : 'is-down'}>
              {p == null ? '—' : `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`}
            </span>
          </span>
        );
      })}
    </div>
  );
};
