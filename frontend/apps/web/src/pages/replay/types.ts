/** 时光机 — 与后端 replay 端点/data 形状一一对应。 */
export interface ReplayBar {
  trade_date: string; // "2020-03-13"
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
}

export type SessionMode = 'free' | 'exam';

export interface SegBar {
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface PendingOrder {
  id: string;
  side: 'buy' | 'sell';
  symbol: string;
  shares: number;
  limit_price: number;
  note: string | null;
  placed_day: string;
  frozen: number;
}

export interface ExamEvent {
  type: 'dividend' | 'split' | 'order_cancelled' | 'suspended' | 'info';
  symbol?: string;
  msg: string;
}

export interface SessionMeta {
  id: number;
  name: string;
  status: 'active' | 'revealed';
  mode: SessionMode;                       // v3: 默认 free
  start_date: string | null;               // v3: exam+active 服务端脱敏为 null
  current_date: string | null;
  day_ordinal?: number | null;             // v3: 仅 exam+active 返回
  length_days?: number | null;
  end_date: string | null;
  initial_capital: number;
  cash: number;
  benchmark_symbol: string;
}

export interface Position {
  symbol: string;
  shares: number;
  cost_price: number;
  buy_date: string;
}

export interface NavPoint {
  date: string;
  value: number;
  cash?: number;                 // v3: 日切披露位(评分用)
  pos?: Record<string, number>;
}

export interface ScoreResult {
  total: number;
  excess_score: number;
  turnover_score: number;
  annual_excess_pct: number;
  annual_turnover: number;
  disclosures: {
    max_drawdown: number | null;
    benchmark_max_drawdown: number | null;
    closed_win_rate: number | null;
    closed_trips: number;
    avg_cash_ratio: number | null;
    max_position_weight: number | null;
  };
}

export interface SessionState {
  pool: string[];
  positions: Position[];
  nav: NavPoint[];
  names?: Record<string, string>;       // v2: 旧旅程可缺省
  industries?: Record<string, string>;
  score?: ScoreResult;
}

export interface InstrumentInfo {
  symbol: string;
  name: string;
  industry: string | null;
}

export interface NewsItem {
  title: string;
  source: string;
  published_at: string;
  importance: number | null;
  url: string;
}

export interface SessionFull extends SessionMeta {
  state: SessionState;
}

export interface Trade {
  id?: number;
  trade_date: string;
  symbol: string;
  side: 'buy' | 'sell';
  price: number;
  shares: number;
  fee: number;
  tax: number;
  note?: string | null;
  confidence?: number | null;
  order_type?: 'market' | 'limit';
}

export interface AccountState {
  cash: number;
  positions: Position[];
}

export interface OrderReq {
  symbol: string;
  side: 'buy' | 'sell';
  shares: number;
  note?: string;
}

export interface AdvanceResp {
  dates: string[];
  bars: Record<string, ReplayBar[]>;
  benchmark: ReplayBar[];
  indices: Record<string, ReplayBar[]>;
}

export interface ValuationMetric {
  value: number;
  percentile: number | null;
  window: string;
}

export interface ValuationInfo {
  as_of: string;
  pe_ttm: ValuationMetric | null;
  pb: ValuationMetric | null;
}

export interface BoardRow {
  symbol: string;
  name: string;
  close: number;
  pct_chg: number;
  amount: number;
}

export interface ApiResp<T> {
  code: number;
  msg: string;
  data: T;
}

export interface ExamView {
  mode: 'exam';
  day_ordinal: number;
  seg_idx: number;
  seg_count: number;
  date: string;
  travel_complete: boolean;
  segments: Record<string, SegBar[]>;
  partial_bars: Record<string, ReplayBar>;
  indices_segments: Record<string, SegBar[]>;
  indices_partial: Record<string, ReplayBar>;
  cash: number;
  positions: Position[];
  nav: NavPoint[];
  pending: PendingOrder[];
  frozen_cash: number;
  events: ExamEvent[];
  pool: string[];
  names: Record<string, string>;
  industries: Record<string, string>;
  failed?: string[];   // 仅 pool 端点
  fills?: Trade[];     // 仅 advance 响应
}

export interface OrderResult {
  status: 'filled' | 'pending';
  trade?: Trade;
  order?: PendingOrder;
  cash: number;
  positions: Position[];
  pending: PendingOrder[];
  frozen_cash: number;
}

export interface LeaderboardRow {
  id: number;
  name: string;
  score: number;
  excess_score: number;
  turnover_score: number;
  annual_excess_pct: number;
  annual_turnover: number;
  days: number;
  initial_capital: number;
  final: number | null;
}
