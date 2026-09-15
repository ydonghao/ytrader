import {describe, expect, it} from 'vitest';
import {annualizedReturn, computeNav, maxDrawdown, roundTrips, winRate} from '../nav';
import {tryFill} from '../fill';
import type {AccountState, Trade} from '../../types';

describe('computeNav', () => {
  it('现金+持仓市值；无行情的标的按 0 跳过', () => {
    const v = computeNav(1000, [
      {symbol: '600519', shares: 100, cost_price: 10, buy_date: '2020-01-01'},
      {symbol: '000001', shares: 100, cost_price: 5, buy_date: '2020-01-01'},
    ], (s) => (s === '600519' ? 20 : null));
    expect(v).toBe(3000);
  });
});

describe('maxDrawdown', () => {
  it('120→90 回撤 25%', () => {
    const nav = [100, 120, 90, 130].map((v, i) => ({date: `2020-01-0${i + 1}`, value: v}));
    expect(maxDrawdown(nav)).toBeCloseTo(0.25, 6);
  });
  it('单调不降为 0', () => {
    expect(maxDrawdown([{date: 'a', value: 1}, {date: 'b', value: 2}])).toBe(0);
  });
});

describe('annualizedReturn', () => {
  it('252 天翻倍 → +100%', () => {
    expect(annualizedReturn(100, 200, 252)).toBeCloseTo(1, 6);
  });
  it('非法输入为 0', () => {
    expect(annualizedReturn(0, 200, 252)).toBe(0);
    expect(annualizedReturn(100, 200, 0)).toBe(0);
  });
});

describe('roundTrips/winRate（用 tryFill 造真实成交）', () => {
  const mk = () => {
    let acct: AccountState = {cash: 1e6, positions: []};
    const trades: Trade[] = [];
    const fill = (side: 'buy' | 'sell', price: number, shares: number, date: string, prev: number) => {
      const r = tryFill(acct, {symbol: '600519', side, shares}, {date, close: price, prevClose: prev});
      if (!r.ok) throw new Error(r.error);
      acct = {cash: r.cash, positions: r.positions};
      trades.push(r.trade);
    };
    fill('buy', 10, 100, '2020-01-02', 9.9);
    fill('buy', 20, 100, '2020-01-03', 19.9);
    fill('sell', 25, 150, '2020-01-06', 24.9); // FIFO 吃掉 100@10 + 50@20
    return trades;
  };
  it('FIFO 配对一笔盈利 round-trip', () => {
    const trips = roundTrips(mk());
    expect(trips).toHaveLength(1);
    // proceeds=3750-5-3.75=3741.25；cost=1005+0.5*2005=2007.5
    expect(trips[0].pnl).toBeCloseTo(3741.25 - 2007.5, 2);
    expect(winRate(mk())).toBe(1);
  });
  it('无卖出 → winRate 为 null', () => {
    expect(winRate([])).toBeNull();
  });
});
