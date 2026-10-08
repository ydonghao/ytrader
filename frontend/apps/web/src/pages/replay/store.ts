import {create} from 'zustand';
import * as api from './api';
import {tryFill} from './engine/fill';
import {computeNav} from './engine/nav';
import type {
  ExamEvent, ExamView, NavPoint, PendingOrder, Position, ReplayBar,
  SegBar, SessionMeta, SessionMode, Trade,
} from './types';

export type Phase = 'sailing' | 'review';
export type Speed = 1 | 2 | 4;

// v2: 指数带四指数（advance 的 indices 键 / openSession 初始化共用）
export const INDEX_SYMBOLS = ['sh000001', 'sz399001',
  'sz399006', 'sh000300'] as const;
export const INDEX_NAMES: Record<string, string> = {
  sh000001: '上证指数', sz399001: '深证成指',
  sz399006: '创业板指', sh000300: '沪深300',
};

const dayBefore = (iso: string): string => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
};

/** exam advance/view 响应 → store 增量(纯函数,测试直用)。 */
export const mergeExamView = (st: ReplayStore, v: ExamView) => {
  const dates = [...st.dates];
  if (v.date > (dates[dates.length - 1] ?? '')) dates.push(v.date);
  const mergePartial = (
    src: Record<string, ReplayBar[]>, patch: Record<string, ReplayBar>,
  ): Record<string, ReplayBar[]> => {
    const out = {...src};
    for (const [sym, pb] of Object.entries(patch)) {
      const arr = out[sym] ? [...out[sym]] : [];
      if (arr.length && arr[arr.length - 1].trade_date === pb.trade_date) {
        arr[arr.length - 1] = pb;
      } else {
        arr.push(pb);
      }
      out[sym] = arr;
    }
    return out;
  };
  const indexBars = mergePartial(st.indexBars, v.indices_partial);
  return {
    dates,
    cursor: dates.length - 1,
    // pool/names/industries 服务端权威——加股后新标的需要反映到池面板
    pool: v.pool, names: v.names, industries: v.industries,
    barsBySymbol: mergePartial(st.barsBySymbol, v.partial_bars),
    indexBars,
    benchmarkBars: st.session
      ? indexBars[st.session.benchmark_symbol] ?? st.benchmarkBars
      : st.benchmarkBars,
    segments: v.segments,
    indicesSegs: v.indices_segments,
    segIdx: v.seg_idx,
    dayOrdinal: v.day_ordinal,
    cash: v.cash,
    positions: v.positions,
    nav: v.nav,
    pending: v.pending,
    frozenCash: v.frozen_cash,
    examEvents: v.events,
    travelComplete: v.travel_complete,
    trades: v.fills ? [...st.trades, ...v.fills] : st.trades,
    error: v.travel_complete ? '已到旅程终点，可揭晓复盘' : null,
    playing: v.travel_complete ? false : st.playing,
  };
};

export interface ReplayStore {
  session: SessionMeta | null;
  phase: Phase;
  dates: string[]; // 已走过的交易日（升序）
  cursor: number; // 视角位置；cursor < dates.length-1 为回看态
  pool: string[];
  names: Record<string, string>;
  industries: Record<string, string>;
  barsBySymbol: Record<string, ReplayBar[]>; // ≤ 最新走过日期
  indexBars: Record<string, ReplayBar[]>; // 四指数，口径同 barsBySymbol
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

  // ── v3 拟真考核(服务端权威) ──
  mode: SessionMode;
  segIdx: number;
  segCount: number;
  dayOrdinal: number;
  travelComplete: boolean;
  segments: Record<string, SegBar[]>;
  indicesSegs: Record<string, SegBar[]>;
  pending: PendingOrder[];
  frozenCash: number;
  examEvents: ExamEvent[];

  openSession: (id: number) => Promise<void>;
  closeSession: () => void;
  addSymbol: (symbol: string, name?: string) => Promise<void>;
  addSymbols: (symbols: string[]) => Promise<{added: number; failed: string[]}>;
  selectSymbol: (symbol: string) => void;
  advance: (step?: 'seg' | 'day') => Promise<void>;
  stepBack: () => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: Speed) => void;
  placeOrder: (side: 'buy' | 'sell', shares: number, opts?: {
    note?: string;
    orderType?: 'market' | 'limit';
    limitPrice?: number;
    confidence?: number;
  }) => Promise<boolean>;
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
    industries: {},
    barsBySymbol: {},
    indexBars: {},
    benchmarkBars: [],
    cash: 0,
    positions: [],
    trades: [],
    nav: [],
    selectedSymbol: null,
    playing: false,
    speed: 1,
    error: null,
    mode: 'free',
    segIdx: 0,
    segCount: 8,
    dayOrdinal: 0,
    travelComplete: false,
    segments: {},
    indicesSegs: {},
    pending: [],
    frozenCash: 0,
    examEvents: [],
    advancing: false,

    openSession: async (id) => {
      const sj = await api.getSession(id);
      if (sj.code !== 0) {
        set({error: sj.msg || '会话加载失败'});
        return;
      }
      const sess = sj.data;
      if (sess.mode === 'exam') {
        const vj = await api.fetchExamView(id);
        if (vj.code !== 0) {
          set({error: vj.msg || '拟真视图加载失败'});
          return;
        }
        const v = vj.data;
        const asof = dayBefore(v.date); // 历史 K 线止于昨日,防当日收盘泄露
        const barsBySymbol: Record<string, ReplayBar[]> = {};
        for (const sym of v.pool) {
          const kj = await api.fetchKline(sym, asof);
          if (kj.code === 0) barsBySymbol[sym] = kj.data.bars;
          const pb = v.partial_bars[sym];
          if (pb) barsBySymbol[sym] = [...(barsBySymbol[sym] ?? []), pb];
        }
        const idxArr = await Promise.all(INDEX_SYMBOLS.map(
          (s) => api.fetchKline(s, asof)));
        const indexBars: Record<string, ReplayBar[]> = {};
        INDEX_SYMBOLS.forEach((s, i) => {
          if (idxArr[i].code !== 0) return;
          indexBars[s] = [...idxArr[i].data.bars];
          const pb = v.indices_partial[s];
          if (pb) indexBars[s] = [...indexBars[s], pb];
        });
        const tj = await api.listTrades(id);
        const dates = (indexBars[sess.benchmark_symbol] ?? [])
          .map((b) => b.trade_date);
        set({
          session: sess,
          phase: sess.status === 'revealed' ? 'review' : 'sailing',
          mode: 'exam',
          dates, cursor: Math.max(0, dates.length - 1),
          pool: v.pool, names: v.names, industries: v.industries,
          barsBySymbol, indexBars,
          indicesSegs: v.indices_segments, segments: v.segments,
          benchmarkBars: indexBars[sess.benchmark_symbol] ?? [],
          segIdx: v.seg_idx, segCount: v.seg_count,
          dayOrdinal: v.day_ordinal, travelComplete: v.travel_complete,
          cash: v.cash, positions: v.positions, nav: v.nav,
          pending: v.pending, frozenCash: v.frozen_cash,
          examEvents: v.events,
          trades: tj.code === 0 ? tj.data : [],
          selectedSymbol: v.pool[0] ?? null, error: null,
        });
        // 已揭晓的拟真会话直接进复盘视图(同 free 分支:reveal 内部
        // 见 status 已是 revealed 不会再调揭晓端点,无循环)
        if (sess.status === 'revealed') await get().reveal();
        return;
      }
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
      // v2: 四指数初始化（与基准同口径，到 current_date）
      const idxArr = await Promise.all(INDEX_SYMBOLS.map(
        (s) => api.fetchKline(s, sess.current_date)));
      const indexBars: Record<string, ReplayBar[]> = {};
      INDEX_SYMBOLS.forEach((s, i) => {
        if (idxArr[i].code === 0) indexBars[s] = idxArr[i].data.bars;
      });
      const tj = await api.listTrades(id);
      set({
        session: sess,
        phase: sess.status === 'revealed' ? 'review' : 'sailing',
        mode: 'free',
        dates,
        cursor: Math.max(0, dates.length - 1),
        pool: sess.state.pool,
        names: sess.state.names ?? {},      // v2: 旧旅程可缺省
        industries: sess.state.industries ?? {},
        barsBySymbol,
        indexBars,
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
        pool: [], names: {}, industries: {}, barsBySymbol: {},
        indexBars: {}, benchmarkBars: [],
        cash: 0, positions: [], trades: [], nav: [],
        selectedSymbol: null, playing: false, error: null,
        advancing: false,
        mode: 'free',
        segIdx: 0,
        segCount: 8,
        dayOrdinal: 0,
        travelComplete: false,
        segments: {},
        indicesSegs: {},
        pending: [],
        frozenCash: 0,
        examEvents: [],
      });
    },

    addSymbol: async (symbol, name) => {
      const s = get();
      if (s.mode === 'exam') {
        const r = await api.addToPool(s.session.id, [symbol]);
        if (r.code !== 0) {
          set({error: r.msg || '入池失败'});
          return;
        }
        const v = r.data;
        // 池端点的失败名单(该日期前无行情)不进池不选中
        if (v.failed?.includes(symbol)) {
          set({error: `该日期前无行情数据：${symbol}`});
          return;
        }
        set(mergeExamView(get(), v));
        // 新股补历史K线(止于昨日,防当日收盘泄露——openSession同款纪律)。
        // 必须在 mergeExamView 之后整体替换:merge 只追加当日 partial 一根,
        // 主图会只剩单根K线;此处用 [历史..., partial] 覆盖为完整序列
        const kj = await api.fetchKline(symbol, dayBefore(v.date));
        if (kj.code === 0 && kj.data.bars.length) {
          const pb = v.partial_bars[symbol];
          const bars = pb ? [...kj.data.bars, pb] : [...kj.data.bars];
          set((st) => ({barsBySymbol: {...st.barsBySymbol, [symbol]: bars}}));
        }
        set({selectedSymbol: symbol});
        return;
      }
      if (s.pool.includes(symbol)) {
        set({selectedSymbol: symbol});
        return;
      }
      const asof = s.dates[s.dates.length - 1];
      // v2: kline 与 instrument 并发富化
      const [kj, ij] = await Promise.all([
        api.fetchKline(symbol, asof),
        api.fetchInstrument(symbol),
      ]);
      if (kj.code !== 0 || kj.data.bars.length === 0) {
        set({error: kj.msg || `${symbol} 在 ${asof} 之前无行情数据`});
        return;
      }
      // 并发兜底：预检后 await 期间另一路同标的可能已入池，set 前重查去重
      if (get().pool.includes(symbol)) return;
      const finalName = name ??
        (ij.code === 0 && ij.data.name ? ij.data.name : undefined);
      const industry = ij.code === 0 ? ij.data.industry : null;
      set((st) => ({
        pool: [...st.pool, symbol],
        names: finalName ? {...st.names, [symbol]: finalName} : st.names,
        industries: industry
          ? {...st.industries, [symbol]: industry}
          : st.industries,
        barsBySymbol: {...st.barsBySymbol, [symbol]: kj.data.bars},
        selectedSymbol: symbol,
        error: null,
      }));
      scheduleSave();
    },

    addSymbols: async (symbols) => {
      let added = 0;
      const failed: string[] = [];
      const uniq = [...new Set(symbols)]; // 批内去重，防并发双写
      for (let i = 0; i < uniq.length; i += 6) { // 6 只一批并发
        await Promise.all(uniq.slice(i, i + 6).map(async (sym) => {
          await get().addSymbol(sym); // 失败只记 symbol 不中断
          if (get().pool.includes(sym)) added += 1;
          else failed.push(sym);
        }));
      }
      return {added, failed};
    },

    selectSymbol: (symbol) => set({selectedSymbol: symbol}),

    advance: async (step) => {
      const s = get();
      if (!s.session || s.advancing || s.phase !== 'sailing') return;
      if (s.cursor < s.dates.length - 1) {
        set({cursor: s.cursor + 1}); // 回看态：只移动视角
        return;
      }
      set({advancing: true});
      try {
        if (s.mode === 'exam') {
          const r = await api.advanceExam(s.session.id, step ?? 'seg');
          if (r.code !== 0) {
            set({error: r.msg || '推进失败', playing: false});
            return;
          }
          set(mergeExamView(get(), r.data));
          return;
        }
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
        // v2: 指数带与 bars 同口径去重合并（仅 > lastDate 的 bar）
        const indexBars = {...st.indexBars};
        for (const [sym, bars] of Object.entries(r.data.indices)) {
          indexBars[sym] = [
            ...(indexBars[sym] ?? []),
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
          indexBars,
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

    placeOrder: async (
      side, shares,
      opts?: {note?: string; orderType?: 'market' | 'limit';
        limitPrice?: number; confidence?: number},
    ) => {
      const s = get();
      const symbol = s.selectedSymbol;
      if (!s.session || !symbol) return false;
      if (s.cursor < s.dates.length - 1) {
        set({error: '回看状态不能交易'});
        return false;
      }
      if (s.mode === 'exam') {
        if (s.travelComplete) {
          set({error: '旅程已走完，请揭晓复盘'});
          return false;
        }
        const r = await api.placeOrder(s.session.id, {
          symbol, side, order_type: opts?.orderType ?? 'market', shares,
          ...(opts?.orderType === 'limit' && opts?.limitPrice != null
            ? {limit_price: opts.limitPrice} : {}),
          ...(opts?.confidence != null
            ? {confidence: opts.confidence} : {}),
          note: (opts?.note ?? '').trim(),
        });
        if (r.code !== 0) {
          set({error: r.msg || '下单失败'});
          return false;
        }
        const d = r.data;
        set({
          cash: d.cash, positions: d.positions, pending: d.pending,
          frozenCash: d.frozen_cash, error: null,
          ...(d.status === 'filled' && d.trade
            ? {trades: [...get().trades, d.trade]} : {}),
        });
        return true;
      }
      // ↓ free:本地撮合
      const date = s.dates[s.cursor];
      const bars = s.barsBySymbol[symbol] ?? [];
      const i = bars.findIndex((b) => b.trade_date === date);
      if (i < 0) {
        set({error: '当日停牌，无法成交'});
        return false;
      }
      const prevClose = i > 0 ? bars[i - 1].close : bars[i].open;
      const r = tryFill(
        {cash: s.cash, positions: s.positions},
        {symbol, side, shares, note: opts?.note},
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
      if (s.mode === 'exam') {
        // 揭晓后服务端不再脱敏,重取真实日期
        const sj2 = await api.getSession(s.session.id);
        if (sj2.code === 0) set({session: sj2.data});
      }
      // 揭晓：拉全量 K 线（到 end_date 或今天）
      const st = get();
      // free 的 session.current_date 是 openSession 时的陈旧快照(advance 不更新),
      // 不能拿来截断复盘 → 只有 exam 才信 current_date
      const asof = st.session!.end_date
        ?? (st.mode === 'exam' ? st.session!.current_date : null)
        ?? new Date().toISOString().slice(0, 10);
      const barsBySymbol: Record<string, ReplayBar[]> = {};
      for (const sym of st.pool) {
        const kj = await api.fetchKline(sym, asof);
        if (kj.code === 0) barsBySymbol[sym] = kj.data.bars;
      }
      const bj = await api.fetchKline(st.session!.benchmark_symbol, asof);
      // v2: 揭晓重拉阶段并发补 4 指数全量
      const idxArr = await Promise.all(INDEX_SYMBOLS.map(
        (s) => api.fetchKline(s, asof)));
      const indexBars = {...st.indexBars};
      INDEX_SYMBOLS.forEach((s, i) => {
        if (idxArr[i].code === 0) indexBars[s] = idxArr[i].data.bars;
      });
      set({
        phase: 'review',
        playing: false,
        session: {...st.session!, status: 'revealed'},
        barsBySymbol,
        indexBars,
        benchmarkBars: bj.code === 0 ? bj.data.bars : st.benchmarkBars,
      });
    },

    saveNow: async () => {
      const s = get();
      if (s.mode === 'exam') return; // 服务端权威,不外部存档
      if (!s.session || s.dates.length === 0) return;
      await api.saveState(s.session.id, {
        current_date: s.dates[s.dates.length - 1],
        cash: s.cash,
        state: {
          pool: s.pool, positions: s.positions, nav: s.nav,
          names: s.names, industries: s.industries,
        },
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
