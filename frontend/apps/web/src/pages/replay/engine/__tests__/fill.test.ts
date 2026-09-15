import {describe, expect, it} from 'vitest';
import {commission, priceLimitRatio, stampTax, tryFill} from '../fill';
import type {AccountState} from '../../types';

const acct = (cash: number, positions: AccountState['positions'] = []): AccountState => ({cash, positions});

describe('priceLimitRatio', () => {
  it('按板块分档', () => {
    expect(priceLimitRatio('600519')).toBe(0.1);
    expect(priceLimitRatio('sh600519')).toBe(0.1); // 带库内前缀
    expect(priceLimitRatio('sz300750')).toBe(0.2);
    expect(priceLimitRatio('bj830799')).toBe(0.3);
    expect(priceLimitRatio('000001')).toBe(0.1);
    expect(priceLimitRatio('300750')).toBe(0.2);
    expect(priceLimitRatio('688981')).toBe(0.2);
    expect(priceLimitRatio('830799')).toBe(0.3);
    expect(priceLimitRatio('600519', 'ST茅台')).toBe(0.05);
  });
});

describe('费用', () => {
  it('佣金万2.5最低5元', () => {
    expect(commission(1000)).toBe(5);
    expect(commission(100000)).toBe(25);
  });
  it('印花税按日期换挡', () => {
    expect(stampTax(100000, '2020-01-06')).toBe(100);
    expect(stampTax(100000, '2024-01-02')).toBe(50);
  });
});

describe('tryFill 买入', () => {
  const ctx = {date: '2020-03-13', close: 11, prevClose: 10};
  it('涨停拒买（主板10%）', () => {
    const r = tryFill(acct(1e6), {symbol: '600519', side: 'buy', shares: 100}, ctx);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('涨停');
  });
  it('创业板20%：同价可买', () => {
    const r = tryFill(acct(1e6), {symbol: '300750', side: 'buy', shares: 100}, ctx);
    expect(r.ok).toBe(true);
  });
  it('非整手拒单', () => {
    const r = tryFill(acct(1e6), {symbol: '600519', side: 'buy', shares: 50}, {...ctx, close: 10.5});
    expect(r.ok).toBe(false);
  });
  it('资金不足拒单（含佣金）', () => {
    const r = tryFill(acct(1000), {symbol: '600519', side: 'buy', shares: 100}, {...ctx, close: 10.5});
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('资金不足');
  });
  it('买入成功：扣款=金额+佣金，持仓新增', () => {
    const r = tryFill(acct(1e6), {symbol: '600519', side: 'buy', shares: 100, note: '便宜'}, {...ctx, close: 10.5});
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.cash).toBe(1e6 - 1050 - 5);
      expect(r.positions).toEqual([{symbol: '600519', shares: 100, cost_price: 10.5, buy_date: '2020-03-13'}]);
      expect(r.trade).toMatchObject({side: 'buy', price: 10.5, shares: 100, fee: 5, tax: 0, note: '便宜'});
    }
  });
});

describe('tryFill 卖出', () => {
  const pos = [{symbol: '600519', shares: 200, cost_price: 10, buy_date: '2020-03-12'}];
  it('T+1：买入当日不可卖', () => {
    const r = tryFill(acct(0, [{...pos[0], buy_date: '2020-03-13'}]),
      {symbol: '600519', side: 'sell', shares: 100},
      {date: '2020-03-13', close: 10.5, prevClose: 10});
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('T+1');
  });
  it('跌停拒卖', () => {
    const r = tryFill(acct(0, pos), {symbol: '600519', side: 'sell', shares: 100},
      {date: '2020-03-13', close: 9, prevClose: 10});
    expect(r.ok).toBe(false);
  });
  it('持仓不足拒卖', () => {
    const r = tryFill(acct(0, pos), {symbol: '600519', side: 'sell', shares: 300},
      {date: '2020-03-13', close: 10.5, prevClose: 10});
    expect(r.ok).toBe(false);
  });
  it('卖出成功：回款=金额-佣金-印花税(2020年千1)', () => {
    const r = tryFill(acct(0, pos), {symbol: '600519', side: 'sell', shares: 100},
      {date: '2020-03-13', close: 10.5, prevClose: 10});
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.cash).toBe(1050 - 5 - 1.05);
      expect(r.positions).toEqual([{symbol: '600519', shares: 100, cost_price: 10, buy_date: '2020-03-12'}]);
      expect(r.trade.tax).toBe(1.05);
    }
  });
  it('清仓后持仓移除', () => {
    const r = tryFill(acct(0, pos), {symbol: '600519', side: 'sell', shares: 200},
      {date: '2020-03-13', close: 10.5, prevClose: 10});
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.positions).toEqual([]);
  });
});
