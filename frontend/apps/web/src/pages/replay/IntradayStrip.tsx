import {colorDown, colorUp} from '../../lib/chartTheme';
import type {SegBar} from './types';

export const computeScale = (
  segs: SegBar[], prevClose: number | null,
): {lo: number; hi: number} => {
  const lows = segs.map((s) => s.low);
  const highs = segs.map((s) => s.high);
  if (prevClose != null) {
    lows.push(prevClose);
    highs.push(prevClose);
  }
  let lo = Math.min(...lows);
  let hi = Math.max(...highs);
  const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.01 || 1;
  lo -= pad;
  hi += pad;
  return {lo, hi};
};

export const IntradayStrip: React.FC<{
  segs: SegBar[];
  segCount: number;
  prevClose: number | null;
  height?: number;
}> = ({segs, segCount, prevClose, height = 64}) => {
  if (segs.length === 0) return null;
  const W = 100;
  const {lo, hi} = computeScale(segs, prevClose);
  const x = (i: number) => (i / (segCount - 1)) * W;
  const y = (v: number) => ((hi - v) / (hi - lo)) * 100;
  const pts = segs.map((s, i) => `${x(i)},${y(s.close)}`).join(' ');
  const cur = segs[segs.length - 1];
  const up = cur.close >= (prevClose ?? cur.close);
  const color = up ? colorUp : colorDown;
  return (
    <svg viewBox={`0 0 ${W} 100`} preserveAspectRatio="none"
      style={{width: '100%', height}} role="img" aria-label="当日分时">
      {prevClose != null && (
        <line x1={0} x2={W} y1={y(prevClose)} y2={y(prevClose)}
          stroke="#6e6e73" strokeDasharray="3 3" strokeWidth={0.5} />
      )}
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.2} />
      <circle cx={x(segs.length - 1)} cy={y(cur.close)} r={1.6}
        fill={color} />
      {Array.from({length: segCount}, (_, i) =>
        i < segs.length ? null : (
          <line key={i} x1={x(i)} x2={x(i)} y1={46} y2={54}
            stroke="#6e6e73" strokeWidth={0.3} />
        ))}
    </svg>
  );
};
