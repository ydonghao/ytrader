/** 时光机指标：sma/kdj 本地实现；ema/macd/rsiWilder 复用 Board
 *  （与后端 strategy/indicators.py 逐条对齐的那套）。 */

export function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= n) sum -= values[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

export interface KdjPoint {
  k: number | null;
  d: number | null;
  j: number | null;
}

/** KDJ（9,3,3）：K/D 初值 50，K = 2/3·K' + 1/3·RSV。 */
export function kdj(
  bars: {high: number; low: number; close: number}[],
  n = 9,
): KdjPoint[] {
  const out: KdjPoint[] = [];
  let prevK = 50;
  let prevD = 50;
  for (let i = 0; i < bars.length; i++) {
    if (i < n - 1) {
      out.push({k: null, d: null, j: null});
      continue;
    }
    let hh = -Infinity;
    let ll = Infinity;
    for (let m = i - n + 1; m <= i; m++) {
      hh = Math.max(hh, bars[m].high);
      ll = Math.min(ll, bars[m].low);
    }
    const rsv = hh === ll ? 50 : ((bars[i].close - ll) / (hh - ll)) * 100;
    const k = (2 / 3) * prevK + (1 / 3) * rsv;
    const d = (2 / 3) * prevD + (1 / 3) * k;
    out.push({k, d, j: 3 * k - 2 * d});
    prevK = k;
    prevD = d;
  }
  return out;
}

export {ema, macd, rsiWilder} from '../../Board/indicators';
export type {MacdResult, Series} from '../../Board/indicators';
