import {useEffect, useState} from 'react';
import * as api from './api';
import {useReplayStore, viewDate} from './store';
import type {ValuationInfo, ValuationMetric} from './types';

const Row: React.FC<{label: string; m: ValuationMetric | null}> = ({label, m}) => (
  <div className="replay-gauge" style={{gridColumn: '1 / -1'}}>
    <span className="label">{label}</span>
    {m ? (
      <>
        <span className="value">
          {m.value.toFixed(2)} · 十年分位{' '}
          {m.percentile == null ? '样本不足' : `${(m.percentile * 100).toFixed(0)}%`}
        </span>
        {m.percentile != null && (
          <div className="replay-pct-bar">
            <i style={{width: `${m.percentile * 100}%`}} />
          </div>
        )}
      </>
    ) : (
      <span className="value">—</span>
    )}
  </div>
);

export const ValuationPanel: React.FC = () => {
  const symbol = useReplayStore((s) => s.selectedSymbol);
  const vd = useReplayStore(viewDate);
  const [info, setInfo] = useState<ValuationInfo | null>(null);
  useEffect(() => {
    if (!symbol || !vd) return;
    let off = false;
    setInfo(null);
    void api.fetchValuation(symbol, vd).then((r) => {
      if (!off && r.code === 0) setInfo(r.data);
    });
    return () => { off = true; };
  }, [symbol, vd]);
  return (
    <div className="replay-panel">
      <h4>估值（截至 {vd}）</h4>
      <div className="replay-gauges">
        <Row label="PE(TTM)" m={info?.pe_ttm ?? null} />
        <Row label="PB" m={info?.pb ?? null} />
      </div>
    </div>
  );
};
