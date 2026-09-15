import {create} from 'zustand';
import * as api from './api';
import {tryFill} from './engine/fill';
import {computeNav} from './engine/nav';
import type {
  NavPoint, Position, ReplayBar, SessionMeta, Trade,
} from './types';

export type Phase = 'sailing' | 'review';
export type Speed = 1 | 2 | 4;

export interface ReplayStore {
  session: SessionMeta | null;
  phase: Phase;
  dates: string[]; // 已走过的交易日（升序）
  cursor: number; // 视角位置；cursor < dates.length-1 为回看态
  pool: string[];
  names: Record<string, string>;
  barsBySymbol: Record<string, ReplayBar[]>; // ≤ 最新走过日期
  benchmarkBars: ReplayBar[];
  cash: number;
  positions: Position[];
  trades: Trade[];
  nav: NavPoint[];
  selectedSymbol: string | null;
  playing: boolean;
  speed: Speed;
  error: string | null;
  advancing: boolean;

  openSession: (id: number) => Promise<void>;
  closeSession: () => void;
  addSymbol: (symbol: string, name?: string) => Promise<void>;
  selectSymbol: (symbol: string) => void;
  advance: () => Promise<void>;
  stepBack: () => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: Speed) => void;
  placeOrder: (side: 'buy' | 'sell', shares: number, note?: string) => Promise<boolean>;
  reveal: () => Promise<void>;
  saveNow: () => Promise<void>;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

export const useReplayStore = create<ReplayStore>()((set, get) => {
  const scheduleSave = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => void get().saveNow(), 800);
  };

  return {
    session: null,
    phase: 'sailing',
    dates: [],
    cursor: 0,
    pool: [],
    names: {},
    barsBySymbol: {},
    benchmarkBars: [],
    cash: 0,
    positions: [],
    trades: [],
    nav: [],
    selectedSymbol: null,
    playing: false,
    speed: 1,
    error: null,
    advancing: false,

    openSession: async (id) => {
      const sj = await api.getSession(id);
      if (sj.code !== 0) {
        set({error: sj.msg || '会话加载失败'});
        return;
      }
      const sess = sj.data;
      // 交易日历从基准 K 线重建（start → current）
      const cal = await api.fetchKline(sess.benchmark_symbol, sess.current_date);
      const calBars = cal.code === 0 ? cal.data.bars : [];
      const dates = calBars
        .map((b) => b.trade_date)
        .filter((d) => d >= sess.start_date && d <= sess.current_date);
      const barsBySymbol: Record<string, ReplayBar[]> = {};
      for (const sym of sess.state.pool) {
        const kj = await api.fetchKline(sym, sess.current_date);
        if (kj.code === 0) barsBySymbol[sym] = kj.data.bars;
      }
      const tj = await api.listTrades(id);
      set({
        session: sess,
        phase: sess.status === 'revealed' ? 'review' : 'sailing',
        dates,
        cursor: Math.max(0, dates.length - 1),
        pool: sess.state.pool,
        barsBySymbol,
        benchmarkBars: calBars,
        cash: sess.cash,
        positions: sess.state.positions,
        trades: tj.code === 0 ? tj.data : [],
        nav: sess.state.nav,
        selectedSymbol: sess.state.pool[0] ?? null,
        error: null,
      });
      if (sess.status === 'revealed') await get().reveal();
    },

    closeSession: () => {
      if (saveTimer) clearTimeout(saveTimer);
      set({
        session: null, phase: 'sailing', dates: [], cursor: 0,
        pool: [], names: {}, barsBySymbol: {}, benchmarkBars: [],
        cash: 0, positions: [], trades: [], nav: [],
        selectedSymbol: null, playing: false, error: null,
        advancing: false,
      });
    },

    addSymbol: async (symbol, name) => {
      const s = get();
      if (s.pool.includes(symbol)) {
        set({selectedSymbol: symbol});
        return;
      }
      const asof = s.dates[s.dates.length - 1];
      const kj = await api.fetchKline(symbol, asof);
      if (kj.code !== 0 || kj.data.bars.length === 0) {
        set({error: kj.msg || `${symbol} 在 ${asof} 之前无行情数据`});
        return;
      }
      set((st) => ({
        pool: [...st.pool, symbol],
        names: name ? {...st.names, [symbol]: name} : st.names,
        barsBySymbol: {...st.barsBySymbol, [symbol]: kj.data.bars},
        selectedSymbol: symbol,
        error: null,
      }));
      scheduleSave();
    },

    selectSymbol: (symbol) => set({selectedSymbol: symbol}),

    advance: async () => {
      const s = get();
      if (!s.session || s.advancing || s.phase !== 'sailing') return;
      if (s.cursor < s.dates.length - 1) {
        set({cursor: s.cursor + 1}); // 回看态：只移动视角
        return;
      }
      set({advancing: true});
      try {
        const r = await api.fetchAdvance(s.session.id, 1);
        if (r.code !== 0) {
          set({error: r.msg || '推进失败', playing: false});
          return;
        }
        if (r.data.dates.length === 0) {
          set({playing: false, error: '已到数据终点，可揭晓复盘'});
          return;
        }
        const st = get();
        // 终审 C1 前端兜底：防抖窗口期服务端可能重复返回同一天，按 > 当前末日期去重
        const lastDate = st.dates[st.dates.length - 1] ?? '';
        const newDates = r.data.dates.filter((d) => d > lastDate);
        if (newDates.length === 0) return;
        const inNew = (d: string) => newDates.includes(d);
        const barsBySymbol = {...st.barsBySymbol};
        for (const [sym, bars] of Object.entries(r.data.bars)) {
          barsBySymbol[sym] = [
            ...(barsBySymbol[sym] ?? []),
            ...bars.filter((b) => inNew(b.trade_date)),
          ];
        }
        const date = newDates[newDates.length - 1];
        if (!date) return;
        const closeOf = (sym: string) => {
          const bars = barsBySymbol[sym];
          return bars && bars.length ? bars[bars.length - 1].close : null;
        };
        const nav = [
          ...st.nav,
          {date, value: computeNav(st.cash, st.positions, closeOf)},
        ];
        set({
          dates: [...st.dates, ...newDates],
          cursor: st.cursor + newDates.length,
          barsBySymbol,
          benchmarkBars: [
            ...st.benchmarkBars,
            ...r.data.benchmark.filter((b) => inNew(b.trade_date)),
          ],
          nav,
          error: null,
        });
        scheduleSave();
      } finally {
        set({advancing: false});
      }
    },

    stepBack: () => {
      const s = get();
      if (s.cursor > 0) set({cursor: s.cursor - 1, playing: false});
    },

    play: () => set({playing: true}),
    pause: () => set({playing: false}),
    setSpeed: (speed) => set({speed}),

    placeOrder: async (side, shares, note) => {
      const s = get();
      const symbol = s.selectedSymbol;
      if (!s.session || !symbol) return false;
      const date = s.dates[s.cursor];
      if (s.cursor < s.dates.length - 1) {
        set({error: '回看状态不能交易'});
        return false;
      }
      const bars = s.barsBySymbol[symbol] ?? [];
      const i = bars.findIndex((b) => b.trade_date === date);
      if (i < 0) {
        set({error: '当日停牌，无法成交'});
        return false;
      }
      const prevClose = i > 0 ? bars[i - 1].close : bars[i].open;
      const r = tryFill(
        {cash: s.cash, positions: s.positions},
        {symbol, side, shares, note},
        {date, close: bars[i].close, prevClose, name: s.names[symbol]},
      );
      if (!r.ok) {
        set({error: r.error});
        return false;
      }
      set({cash: r.cash, positions: r.positions,
           trades: [...s.trades, r.trade], error: null});
      await api.addTrade(s.session.id, r.trade);
      await get().saveNow(); // 成交即存档（不走防抖，防崩丢单）
      return true;
    },

    reveal: async () => {
      const s = get();
      if (!s.session) return;
      if (s.session.status !== 'revealed') {
        const r = await api.revealSession(s.session.id);
        if (r.code !== 0) {
          set({error: r.msg || '揭晓失败'});
          return;
        }
      }
      // 揭晓：拉全量 K 线（到 end_date 或今天）
      const st = get();
      const asof = st.session!.end_date ??
        new Date().toISOString().slice(0, 10);
      const barsBySymbol: Record<string, ReplayBar[]> = {};
      for (const sym of st.pool) {
        const kj = await api.fetchKline(sym, asof);
        if (kj.code === 0) barsBySymbol[sym] = kj.data.bars;
      }
      const bj = await api.fetchKline(st.session!.benchmark_symbol, asof);
      set({
        phase: 'review',
        playing: false,
        session: {...st.session!, status: 'revealed'},
        barsBySymbol,
        benchmarkBars: bj.code === 0 ? bj.data.bars : st.benchmarkBars,
      });
    },

    saveNow: async () => {
      const s = get();
      if (!s.session || s.dates.length === 0) return;
      await api.saveState(s.session.id, {
        current_date: s.dates[s.dates.length - 1],
        cash: s.cash,
        state: {pool: s.pool, positions: s.positions, nav: s.nav},
      });
    },
  };
});

// ── 选择器 helper ──
export const viewDate = (s: ReplayStore): string | null =>
  s.dates[s.cursor] ?? null;

export const lastClose = (s: ReplayStore, symbol: string): number | null => {
  const bars = s.barsBySymbol[symbol];
  return bars && bars.length ? bars[bars.length - 1].close : null;
};

export const visibleBars = (s: ReplayStore, symbol: string): ReplayBar[] => {
  const vd = viewDate(s);
  if (!vd) return [];
  return (s.barsBySymbol[symbol] ?? []).filter((b) => b.trade_date <= vd);
};
