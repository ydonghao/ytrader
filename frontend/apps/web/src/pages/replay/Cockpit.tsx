import {useMemo} from 'react';
import {GaugePanel} from './GaugePanel';
import {OrderTicket} from './OrderTicket';
import {PlayControls} from './PlayControls';
import {PoolPanel} from './PoolPanel';
import {ReplayKlineChart} from './ReplayKlineChart';
import {TopBar} from './TopBar';
import {ValuationPanel} from './ValuationPanel';
import {useReplayStore, viewDate} from './store';
import type {ReplayBar} from './types';

// selector 必须返回稳定引用：zustand v5 直接透传 useSyncExternalStore，
// 每次返回新数组会被 React 判定为快照持续变化，触发无限重渲染
const NO_BARS: ReplayBar[] = [];

export const Cockpit: React.FC = () => {
  const symbol = useReplayStore((s) => s.selectedSymbol);
  const bars = useReplayStore((s) =>
    (s.selectedSymbol ? s.barsBySymbol[s.selectedSymbol] : undefined) ??
    NO_BARS);
  const vd = useReplayStore(viewDate);
  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  return (
    <>
      <TopBar />
      <div className="replay-cockpit">
        <PoolPanel />
        <div className="replay-center">
          <div className="replay-panel chart">
            {symbol
              ? <ReplayKlineChart bars={vis} height={460} />
              : <div className="replay-hint" style={{padding: 20}}>
                  从左侧股票池选一只标的，K 线风挡在这里展开。
                </div>}
          </div>
          <PlayControls />
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0, overflow: 'auto'}}>
          <OrderTicket />
          <GaugePanel />
          <ValuationPanel />
        </div>
      </div>
    </>
  );
};
