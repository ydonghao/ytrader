import {useMemo} from 'react';
import {kdj, macd, rsiWilder, sma} from './engine/indicators';
import {useReplayStore, viewDate} from './store';
import type {ReplayBar} from './types';

// selector 必须返回稳定引用：zustand v5 直接透传 useSyncExternalStore，
// 每次返回新数组会被 React 判定为快照持续变化，触发无限重渲染
const NO_BARS: ReplayBar[] = [];

const last = <T,>(arr: (T | null)[]): T | null => {
  for (let i = arr.length - 1; i >= 0; i--) {
    const v = arr[i];
    if (v != null) return v;
  }
  return null;
};

export const GaugePanel: React.FC = () => {
  const bars = useReplayStore((s) =>
    (s.selectedSymbol ? s.barsBySymbol[s.selectedSymbol] : undefined) ??
    NO_BARS);
  const vd = useReplayStore(viewDate);
  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  if (vis.length < 2) {
    return (
      <div className="replay-panel">
        <h4>指标仪表</h4>
        <div className="replay-hint">数据不足。</div>
      </div>
    );
  }
  const closes = vis.map((b) => b.close);
  const {dif, dea, hist} = macd(closes, 12, 26, 9);
  const rsi = rsiWilder(closes, 14);
  const kd = kdj(vis);
  // noUncheckedIndexedAccess：数组下标先落成变量再判空（k/d/j 同点同生）
  const lastKd = kd.length ? kd[kd.length - 1] : undefined;
  const kdjText = lastKd && lastKd.k != null && lastKd.d != null &&
    lastKd.j != null
    ? `${lastKd.k.toFixed(1)} / ${lastKd.d.toFixed(1)} / ${lastKd.j.toFixed(1)}`
    : '—';
  const gauges: [string, string][] = [
    ['MA5', last(sma(closes, 5))?.toFixed(2) ?? '—'],
    ['MA20', last(sma(closes, 20))?.toFixed(2) ?? '—'],
    ['MA60', last(sma(closes, 60))?.toFixed(2) ?? '—'],
    ['DIF', last(dif)?.toFixed(3) ?? '—'],
    ['DEA', last(dea)?.toFixed(3) ?? '—'],
    ['MACD柱', last(hist)?.toFixed(3) ?? '—'],
    ['RSI14', last(rsi)?.toFixed(1) ?? '—'],
    ['K / D / J', kdjText],
  ];
  return (
    <div className="replay-panel">
      <h4>指标仪表（{vd} 口径）</h4>
      <div className="replay-gauges">
        {gauges.map(([label, value]) => (
          <div key={label} className="replay-gauge">
            <span className="label">{label}</span>
            <span className="value">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
