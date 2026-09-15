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

export interface SessionMeta {
  id: number;
  name: string;
  status: 'active' | 'revealed';
  start_date: string;
  current_date: string;
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
}

export interface SessionState {
  pool: string[];
  positions: Position[];
  nav: NavPoint[];
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
