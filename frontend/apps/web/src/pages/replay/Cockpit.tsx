import {useMemo} from 'react';
import {useDayLabel, useBlind} from './BlindMask';
import {EraBar} from './EraBar';
import {EventCard} from './EventCard';
import {GaugePanel} from './GaugePanel';
import {IndexStrip} from './IndexStrip';
import {IntradayStrip} from './IntradayStrip';
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
  const session = useReplayStore((s) => s.session);
  const pool = useReplayStore((s) => s.pool);
  const mode = useReplayStore((s) => s.mode);
  const segments = useReplayStore((s) => s.segments);
  const segCount = useReplayStore((s) => s.segCount);
  const dayLabel = useDayLabel();
  const blind = useBlind(); // 盲盒航行中禁跳转回测(回测URL带真实起止日期,会泄题)
  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  // exam 分时条的昨收基准:严格 < 视角日,防当日 partial bar 泄露收盘
  const prevClose = useMemo(() => {
    const hist = bars.filter((b) => !vd || b.trade_date < vd);
    return hist.length ? hist[hist.length - 1].close : null;
  }, [bars, vd]);
  return (
    <>
      <TopBar />
      <IndexStrip />
      <EraBar />
      <div className="replay-cockpit">
        <PoolPanel />
        <div className="replay-center">
          <div className="replay-panel chart">
            {mode === 'exam' && symbol && (
              <IntradayStrip segs={segments[symbol] ?? []}
                segCount={segCount} prevClose={prevClose} />
            )}
            {symbol
              ? <ReplayKlineChart bars={vis} height={460} labelFor={dayLabel} />
              : <div className="replay-hint" style={{padding: 20}}>
                  从左侧股票池选一只标的，K 线风挡在这里展开。
                </div>}
          </div>
          <div style={{display: 'flex', gap: 8, alignItems: 'center'}}>
            <PlayControls />
            {/* 舱内跳转：池 + 旅程起点 → 当前视角日，交给回测实验室跑长周期 */}
            <button
              className="replay-btn"
              disabled={!session || pool.length === 0 || !vd || blind}
              title={blind
                ? '盲盒航行中不可跳转回测（会泄露真实日期）'
                : '当前股票池与 旅程起点→视角日 区间，交给回测实验室跑长期回测'}
              onClick={() => {
                if (!session || !vd) return;
                window.open(`/lt-backtest?symbols=${
                  encodeURIComponent(pool.join(','))}&start=${
                  session.start_date}&end=${vd}`, '_blank');
              }}>
              丢给回测实验室
            </button>
          </div>
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0, overflow: 'auto'}}>
          <OrderTicket />
          <EventCard />
          <GaugePanel />
          <ValuationPanel />
        </div>
      </div>
    </>
  );
};
