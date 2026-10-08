import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.mock('../api', () => ({
  getSession: vi.fn(),
  fetchKline: vi.fn(),
  fetchAdvance: vi.fn(),
  fetchInstrument: vi.fn().mockResolvedValue({code: 0, msg: 'ok',
    data: {symbol: '', name: '', industry: null}}),
  fetchNews: vi.fn().mockResolvedValue({code: 0, msg: 'ok', data: []}),
  generatePortfolio: vi.fn().mockResolvedValue({code: 0, msg: 'ok',
    data: {risk_profile: '', total_capital: 0, investable_capital: 0,
      legs: [], warnings: []}}),
  addTrade: vi.fn().mockResolvedValue({code: 0, data: {}}),
  saveState: vi.fn().mockResolvedValue({code: 0, data: {}}),
  listTrades: vi.fn().mockResolvedValue({code: 0, data: []}),
  revealSession: vi.fn().mockResolvedValue({code: 0, data: {status: 'revealed'}}),
  fetchExamView: vi.fn(),
  advanceExam: vi.fn(),
  addToPool: vi.fn(),
  placeOrder: vi.fn(),
  fetchLeaderboard: vi.fn().mockResolvedValue({code: 0, msg: 'ok', data: []}),
}));

import * as api from '../api';
import {useReplayStore} from '../store';

const bar = (d: string, close: number) => ({
  trade_date: d, open: close, close, high: close, low: close, volume: 1, amount: 1,
});

const seedSession = {
  id: 7, name: 'T', status: 'active' as const, mode: 'free' as const,
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
        indices: {},
      }})
      .mockResolvedValueOnce({code: 0, msg: 'ok',
        data: {dates: [], bars: {}, benchmark: [], indices: {}}});
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
      indices: {},
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
      indices: {},
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
    const ok = await useReplayStore.getState().placeOrder('buy', 100, {note: '便宜'});
    expect(ok).toBe(true);
    const s = useReplayStore.getState();
    expect(s.cash).toBe(1e6 - 1000 - 5);
    expect(s.positions[0]).toMatchObject({symbol: '600519', shares: 100});
    expect(api.addTrade).toHaveBeenCalledWith(7,
      expect.objectContaining(
        {side: 'buy', price: 10, shares: 100, note: '便宜'}));
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

describe('free reveal asof', () => {
  it('free reveal 拉取 asof=今天(不用陈旧current_date截断复盘)', async () => {
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519', '贵州茅台');
    vi.mocked(api.fetchKline).mockClear(); // 只断言 reveal 阶段的拉取
    const today = new Date().toISOString().slice(0, 10);
    await useReplayStore.getState().reveal();
    const calls = vi.mocked(api.fetchKline).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.every((c) => c[1] === today)).toBe(true); // 不是陈旧 2020-03-13
    expect(calls.some((c) => c[0] === '600519')).toBe(true); // 池内标的也被拉
  });
});

describe('v2: 富化/指数带/批量入池', () => {
  it('addSymbol 富化名称行业并随 saveNow 持久化', async () => {
    vi.mocked(api.fetchInstrument).mockResolvedValue({code: 0, msg: 'ok',
      data: {symbol: '600519', name: '贵州茅台', industry: '食品饮料'}});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().addSymbol('600519');
    useReplayStore.getState().selectSymbol('600519');
    await useReplayStore.getState().placeOrder('buy', 100);
    const body = vi.mocked(api.saveState).mock.calls.at(-1)?.[1];
    expect(body?.state.names?.['600519']).toBe('贵州茅台');
    expect(body?.state.industries?.['600519']).toBe('食品饮料');
  });

  it('advance 合并 indices 四指数且去重', async () => {
    // 指数带在开仓时无历史 bar，断言 advance 合并后仅含服务端返回日
    vi.mocked(api.fetchKline).mockImplementation(async (symbol: string) => ({
      code: 0, msg: 'ok',
      data: {symbol, bars: symbol === 'sh000300'
        ? [bar('2020-03-13', 4000)]
        : []},
    }));
    const idx = {'sh000001': [bar('2020-03-16', 2890)]};
    vi.mocked(api.fetchAdvance).mockResolvedValue({code: 0, msg: 'ok', data: {
      dates: ['2020-03-16'], bars: {}, benchmark: [bar('2020-03-16', 4050)],
      indices: idx,
    }});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().advance();
    await useReplayStore.getState().advance(); // 重复返回同一天,去重
    const s = useReplayStore.getState();
    expect(s.indexBars['sh000001'].map((b) => b.trade_date))
      .toEqual(['2020-03-16']);
  });

  it('addSymbols 批量入池统计成败', async () => {
    vi.mocked(api.fetchKline).mockImplementation(async (symbol: string) => ({
      code: 0, msg: 'ok',
      data: {symbol, bars: symbol === 'sz000001'
        ? [] : [bar('2020-03-13', 10)]},   // sz000001 模拟无数据
    }));
    await useReplayStore.getState().openSession(7);
    const r = await useReplayStore.getState()
      .addSymbols(['600519', 'sz000001']);
    expect(r.added).toBe(1);
    expect(r.failed).toEqual(['sz000001']);
  });

  it('并发 addSymbol 同一标的只入池一次', async () => {
    await useReplayStore.getState().openSession(7);
    await Promise.all([
      useReplayStore.getState().addSymbol('600519'),
      useReplayStore.getState().addSymbol('600519'),
    ]);
    const s = useReplayStore.getState();
    expect(s.pool.filter((x) => x === '600519')).toHaveLength(1);
  });
});

describe('exam 模式(服务端权威)', () => {
  const examSession = {
    ...seedSession, mode: 'exam' as const,
    start_date: null, current_date: null,
    day_ordinal: 1, length_days: 120,
  };
  const seg = (c: number) => ({open: c, high: c, low: c, close: c});
  const view = {
    mode: 'exam' as const, day_ordinal: 1, seg_idx: 0, seg_count: 8,
    date: '2020-03-13', travel_complete: false,
    segments: {'600519': [seg(10)]},
    partial_bars: {'600519': bar('2020-03-13', 10)},
    indices_segments: {}, indices_partial: {},
    cash: 1e5, positions: [], nav: [],
    pending: [], frozen_cash: 0, events: [],
    pool: ['600519'], names: {'600519': 'X'}, industries: {},
  };

  beforeEach(() => {
    vi.mocked(api.fetchExamView).mockResolvedValue(
      {code: 0, msg: 'ok', data: view});
  });

  it('openSession hydrate:历史K线止于昨日+今日partial', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    // 历史 asof 应为 2020-03-12(防当日收盘泄露)
    await useReplayStore.getState().openSession(7);
    expect(api.fetchKline).toHaveBeenCalledWith('600519', '2020-03-12');
    const s = useReplayStore.getState();
    expect(s.mode).toBe('exam');
    expect(s.dates[s.dates.length - 1]).toBe('2020-03-13');
    expect(s.barsBySymbol['600519'].slice(-1)[0].close).toBe(10);
    expect(s.segIdx).toBe(0);
  });

  it('addSymbol: 补历史K线(止于昨日)+今日partial+选中', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    await useReplayStore.getState().openSession(7);
    vi.mocked(api.addToPool).mockResolvedValue({code: 0, msg: 'ok', data: {
      ...view,
      pool: ['600519', 'sh600000'],
      partial_bars: {'600519': view.partial_bars['600519'],
        'sh600000': bar('2020-03-13', 20)},
    }});
    vi.mocked(api.fetchKline).mockImplementation(async (symbol: string) => ({
      code: 0, msg: 'ok',
      data: {symbol, bars: symbol === 'sh000300'
        ? [bar('2020-03-13', 4000)]
        : [bar('2020-03-10', 9), bar('2020-03-12', 9.5)]},
    }));
    await useReplayStore.getState().addSymbol('sh600000');
    // 新股历史拉取止于 2020-03-12(openSession 同款防泄露纪律)
    expect(api.fetchKline).toHaveBeenCalledWith('sh600000', '2020-03-12');
    const s = useReplayStore.getState();
    // 2 根历史 + 当日 partial,主图不再只有单根K线
    expect(s.barsBySymbol['sh600000']).toHaveLength(3);
    expect(s.barsBySymbol['sh600000'].slice(-1)[0].close).toBe(20);
    expect(s.selectedSymbol).toBe('sh600000');
    expect(s.pool).toContain('sh600000');
  });

  it('addSymbol: 池端点失败名单不入池不选中', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    await useReplayStore.getState().openSession(7);
    vi.mocked(api.addToPool).mockResolvedValue({code: 0, msg: 'ok',
      data: {...view, failed: ['sh999999']}});
    vi.mocked(api.fetchKline).mockClear();
    await useReplayStore.getState().addSymbol('sh999999');
    const s = useReplayStore.getState();
    expect(s.error).toContain('sh999999');
    expect(s.pool).not.toContain('sh999999');
    expect(s.selectedSymbol).toBe('600519'); // 维持原选中
    expect(api.fetchKline).not.toHaveBeenCalled();
  });

  it('openSession: 揭晓后的 exam 会话直接进复盘视图', async () => {
    vi.mocked(api.getSession).mockResolvedValue({code: 0, msg: 'ok',
      data: {...examSession, status: 'revealed' as const,
        start_date: '2019-01-02', current_date: '2020-06-30'}});
    await useReplayStore.getState().openSession(7);
    // 已揭晓:reveal 内部短路不再调揭晓端点,但会重拉全量K线进复盘
    expect(api.revealSession).not.toHaveBeenCalled();
    expect(useReplayStore.getState().phase).toBe('review');
  });

  it('advance seg:合并fills与段数据', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    await useReplayStore.getState().openSession(7);
    vi.mocked(api.advanceExam).mockResolvedValue({code: 0, msg: 'ok', data: {
      ...view, seg_idx: 1, segments: {'600519': [seg(10), seg(10.2)]},
      partial_bars: {'600519': bar('2020-03-13', 10.2)},
      fills: [{trade_date: '2020-03-13', symbol: '600519',
               side: 'buy', price: 10.1, shares: 100, fee: 5, tax: 0,
               note: 't', order_type: 'market'}],
      positions: [{symbol: '600519', shares: 100, cost_price: 10.1,
                   buy_date: '2020-03-13'}],
      cash: 98995,
    }});
    await useReplayStore.getState().advance();
    expect(api.advanceExam).toHaveBeenCalledWith(7, 'seg');
    const s = useReplayStore.getState();
    expect(s.segIdx).toBe(1);
    expect(s.trades).toHaveLength(1);
    expect(s.positions[0].shares).toBe(100);
  });

  it('placeOrder 走服务端,不再本地撮合', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    await useReplayStore.getState().openSession(7);
    useReplayStore.setState({selectedSymbol: '600519'});
    vi.mocked(api.placeOrder).mockResolvedValue({code: 0, msg: 'ok', data: {
      status: 'filled',
      trade: {trade_date: '2020-03-13', symbol: '600519', side: 'buy',
              price: 10.1, shares: 100, fee: 5, tax: 0, note: 'n',
              order_type: 'market'},
      cash: 98995,
      positions: [{symbol: '600519', shares: 100, cost_price: 10.1,
                   buy_date: '2020-03-13'}],
      pending: [], frozen_cash: 0,
    }});
    const ok = await useReplayStore.getState().placeOrder('buy', 100,
      {note: 'n'});
    expect(ok).toBe(true);
    expect(api.placeOrder).toHaveBeenCalled();
    expect(api.addTrade).not.toHaveBeenCalled();
    expect(useReplayStore.getState().cash).toBe(98995);
  });

  it('saveNow 对 exam no-op', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().saveNow();
    expect(api.saveState).not.toHaveBeenCalled();
  });
});
