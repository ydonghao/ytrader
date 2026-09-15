import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.mock('../api', () => ({
  getSession: vi.fn(),
  fetchKline: vi.fn(),
  fetchAdvance: vi.fn(),
  addTrade: vi.fn().mockResolvedValue({code: 0, data: {}}),
  saveState: vi.fn().mockResolvedValue({code: 0, data: {}}),
  listTrades: vi.fn().mockResolvedValue({code: 0, data: []}),
  revealSession: vi.fn().mockResolvedValue({code: 0, data: {status: 'revealed'}}),
}));

import * as api from '../api';
import {useReplayStore} from '../store';

const bar = (d: string, close: number) => ({
  trade_date: d, open: close, close, high: close, low: close, volume: 1, amount: 1,
});

const seedSession = {
  id: 7, name: 'T', status: 'active' as const,
  start_date: '2020-03-13', current_date: '2020-03-13',
  end_date: null, initial_capital: 1e6, cash: 1e6,
  benchmark_symbol: 'sh000300',
  state: {pool: [], positions: [], nav: []},
};

beforeEach(() => {
  vi.clearAllMocks();
  useReplayStore.getState().closeSession();
  vi.mocked(api.getSession).mockResolvedValue({code: 0, msg: 'ok', data: seedSession});
  vi.mocked(api.fetchKline).mockImplementation(async (symbol: string) => ({
    code: 0, msg: 'ok',
    data: {symbol, bars: symbol === 'sh000300'
      ? [bar('2020-03-13', 4000)]
      : [bar('2020-03-13', 10)]},
  }));
});

describe('openSession/advance', () => {
  it('开仓恢复：dates 从基准日历重建，视角在最新日', async () => {
    await useReplayStore.getState().openSession(7);
    const s = useReplayStore.getState();
    expect(s.session?.id).toBe(7);
    expect(s.dates).toEqual(['2020-03-13']);
    expect(s.cursor).toBe(0);
    expect(s.cash).toBe(1e6);
  });

  it('advance 追加新日 bar 与净值点；走到数据尽头自动停', async () => {
    vi.mocked(api.fetchAdvance)
      .mockResolvedValueOnce({code: 0, msg: 'ok', data: {
        dates: ['2020-03-16'],
        bars: {'600519': [bar('2020-03-16', 10.4)]},
        benchmark: [bar('2020-03-16', 4050)],
      }})
      .mockResolvedValueOnce({code: 0, msg: 'ok',
        data: {dates: [], bars: {}, benchmark: []}});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519', '贵州茅台');
    await useReplayStore.getState().advance();
    let s = useReplayStore.getState();
    expect(s.dates).toEqual(['2020-03-13', '2020-03-16']);
    expect(s.barsBySymbol['600519'].map((b) => b.trade_date))
      .toEqual(['2020-03-13', '2020-03-16']);
    expect(s.nav[s.nav.length - 1].date).toBe('2020-03-16');
    await useReplayStore.getState().advance();
    s = useReplayStore.getState();
    expect(s.dates).toHaveLength(2); // 不再前进
    expect(s.error).toContain('终点');
  });

  it('回看态 advance 只移动视角不发请求，且禁止交易', async () => {
    vi.mocked(api.fetchAdvance).mockResolvedValue({code: 0, msg: 'ok', data: {
      dates: ['2020-03-16'], bars: {'600519': [bar('2020-03-16', 10.4)]},
      benchmark: [bar('2020-03-16', 4050)],
    }});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519');
    await useReplayStore.getState().advance();
    useReplayStore.getState().stepBack();
    expect(useReplayStore.getState().cursor).toBe(0);
    vi.mocked(api.fetchAdvance).mockClear();
    await useReplayStore.getState().advance(); // 回看→前进，不发请求
    expect(api.fetchAdvance).not.toHaveBeenCalled();
    expect(useReplayStore.getState().cursor).toBe(1);
  });

  it('服务端游标重复返回时已前端去重，不重复推进', async () => {
    vi.mocked(api.fetchAdvance).mockResolvedValue({code: 0, msg: 'ok', data: {
      dates: ['2020-03-16'], bars: {'600519': [bar('2020-03-16', 10.4)]},
      benchmark: [bar('2020-03-16', 4050)],
    }});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519');
    await useReplayStore.getState().advance();
    await useReplayStore.getState().advance(); // 模拟防抖窗口期的重复返回
    const s = useReplayStore.getState();
    expect(s.dates).toEqual(['2020-03-13', '2020-03-16']);
    expect(s.nav.filter((p) => p.date === '2020-03-16')).toHaveLength(1);
  });
});

describe('placeOrder', () => {
  it('收盘价成交：扣款、持仓、成交落库、自动存档', async () => {
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519', '贵州茅台');
    useReplayStore.getState().selectSymbol('600519');
    const ok = await useReplayStore.getState().placeOrder('buy', 100, '便宜');
    expect(ok).toBe(true);
    const s = useReplayStore.getState();
    expect(s.cash).toBe(1e6 - 1000 - 5);
    expect(s.positions[0]).toMatchObject({symbol: '600519', shares: 100});
    expect(api.addTrade).toHaveBeenCalledWith(7,
      expect.objectContaining({side: 'buy', price: 10, shares: 100}));
    expect(api.saveState).toHaveBeenCalled();
  });

  it('涨停拒买且不落库', async () => {
    vi.mocked(api.fetchKline).mockImplementation(async (symbol: string) => ({
      code: 0, msg: 'ok',
      data: {symbol, bars: symbol === 'sh000300'
        ? [bar('2020-03-13', 4000)]
        : [bar('2020-03-12', 10), bar('2020-03-13', 11)]},
    }));
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519', '贵州茅台');
    useReplayStore.getState().selectSymbol('600519');
    const ok = await useReplayStore.getState().placeOrder('buy', 100);
    expect(ok).toBe(false);
    expect(useReplayStore.getState().error).toContain('涨停');
    expect(api.addTrade).not.toHaveBeenCalled();
  });
});
