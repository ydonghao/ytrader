import type {NavPoint, Position, Trade} from '../types';

const round2 = (v: number) => Math.round(v * 100) / 100;

/** 净值 = 现金 + Σ(持仓股数 × 最近已知收盘价)；无行情的标的跳过。 */
export function computeNav(
  cash: number,
  positions: Position[],
  closeOf: (symbol: string) => number | null,
): number {
  let v = cash;
  for (const p of positions) {
    const c = closeOf(p.symbol);
    if (c != null) v += c * p.shares;
  }
  return round2(v);
}

/** 最大回撤（0~1 正数）。 */
export function maxDrawdown(nav: NavPoint[]): number {
  let peak = -Infinity;
  let mdd = 0;
  for (const p of nav) {
    peak = Math.max(peak, p.value);
    if (peak > 0) mdd = Math.max(mdd, (peak - p.value) / peak);
  }
  return mdd;
}

/** 年化（按 252 个交易日）。 */
export function annualizedReturn(
  initial: number,
  final: number,
  tradeDays: number,
): number {
  if (initial <= 0 || tradeDays <= 0) return 0;
  return Math.pow(final / initial, 252 / tradeDays) - 1;
}

export interface RoundTrip {
  symbol: string;
  pnl: number;
}

/** FIFO 配对：卖出按先进先出结转买入成本（含佣金），得每次平仓盈亏。 */
export function roundTrips(trades: Trade[]): RoundTrip[] {
  const lots = new Map<string, {shares: number; cost: number}[]>();
  const trips: RoundTrip[] = [];
  for (const t of trades) {
    const q = lots.get(t.symbol) ?? [];
    if (t.side === 'buy') {
      q.push({shares: t.shares, cost: t.price * t.shares + t.fee});
    } else {
      let remain = t.shares;
      let costOut = 0;
      while (remain > 0 && q.length > 0) {
        const lot = q[0];
        const take = Math.min(remain, lot.shares);
        const ratio = take / lot.shares;
        costOut += lot.cost * ratio;
        lot.shares -= take;
        lot.cost *= 1 - ratio;
        if (lot.shares <= 0) q.shift();
        remain -= take;
      }
      const proceeds = t.price * t.shares - t.fee - t.tax;
      trips.push({symbol: t.symbol, pnl: round2(proceeds - costOut)});
    }
    lots.set(t.symbol, q);
  }
  return trips;
}

/** 胜率 = 盈利平仓次数 / 总平仓次数；无平仓返回 null。 */
export function winRate(trades: Trade[]): number | null {
  const trips = roundTrips(trades);
  if (trips.length === 0) return null;
  return trips.filter((t) => t.pnl > 0).length / trips.length;
}
