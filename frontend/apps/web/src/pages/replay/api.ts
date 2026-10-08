import {getApiBase} from '../../lib/api';
import type {
  AdvanceResp, ApiResp, BoardRow, ExamView, InstrumentInfo, LeaderboardRow,
  NewsItem, OrderResult, ReplayBar, SessionFull, SessionMeta, Trade,
  ValuationInfo,
} from './types';

const API = getApiBase();

const jget = <T>(u: string): Promise<ApiResp<T>> =>
  fetch(u).then((r) => r.json());
const jpost = <T>(u: string, b?: unknown): Promise<ApiResp<T>> =>
  fetch(u, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(b ?? {}),
  }).then((r) => r.json());
const jput = <T>(u: string, b: unknown): Promise<ApiResp<T>> =>
  fetch(u, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(b),
  }).then((r) => r.json());
const jdel = <T>(u: string): Promise<ApiResp<T>> =>
  fetch(u, {method: 'DELETE'}).then((r) => r.json());

// ── 会话 ──
export const listSessions = () => jget<SessionMeta[]>(`${API}/replay/sessions`);
export const createSession = (body: {
  name: string; start_date: string; initial_capital: number; end_date?: string;
}) => jpost<SessionFull>(`${API}/replay/sessions`, body);
export const createExamSession = (body: {
  initial_capital: number; length_days: number; era_pref: string;
  name?: string;
}) => jpost<SessionFull>(`${API}/replay/sessions`, {mode: 'exam', ...body});
export const fetchExamView = (id: number) =>
  jget<ExamView>(`${API}/replay/sessions/${id}/view`);
export const advanceExam = (id: number, step: 'seg' | 'day') =>
  jget<ExamView>(`${API}/replay/advance?session_id=${id}&step=${step}`);
export const addToPool = (id: number, symbols: string[]) =>
  jpost<ExamView>(`${API}/replay/sessions/${id}/pool`, {symbols});
export const placeOrder = (id: number, body: {
  symbol: string; side: 'buy' | 'sell';
  order_type: 'market' | 'limit'; shares: number;
  limit_price?: number; note: string; confidence?: number;
}) => jpost<OrderResult>(`${API}/replay/sessions/${id}/orders`, body);
export const fetchLeaderboard = () =>
  jget<LeaderboardRow[]>(`${API}/replay/leaderboard`);
export interface TrainingLogResp {
  sessions: {
    id: number; name: string; score: number | null;
    annual_excess_pct: number | null; days: number;
    final: number | null; trade_count: number;
  }[];
  trades: (Trade & {session_name: string})[];
}
export const fetchTrainingLog = () =>
  jget<TrainingLogResp>(`${API}/replay/training-log`);
export const getSession = (id: number) =>
  jget<SessionFull>(`${API}/replay/sessions/${id}`);
export const saveState = (id: number, body: {
  current_date: string; cash: number; state: SessionFull['state'];
}) => jput<{id: number}>(`${API}/replay/sessions/${id}/state`, body);
export const revealSession = (id: number) =>
  jpost<{id: number; status: string}>(`${API}/replay/sessions/${id}/reveal`);
export const deleteSession = (id: number) =>
  jdel<{id: number}>(`${API}/replay/sessions/${id}`);

// ── 成交 ──
export const addTrade = (id: number, t: Trade) =>
  jpost<Trade>(`${API}/replay/sessions/${id}/trades`, t);
export const listTrades = (id: number) =>
  jget<Trade[]>(`${API}/replay/sessions/${id}/trades`);

// ── 行情切片 ──
export const fetchKline = (symbol: string, asof: string, limit = 3000) =>
  jget<{symbol: string; bars: ReplayBar[]}>(
    `${API}/replay/kline/${symbol}?asof=${asof}&limit=${limit}`);
export const fetchAdvance = (sessionId: number, days: number) =>
  jget<AdvanceResp>(`${API}/replay/advance?session_id=${sessionId}&days=${days}`);
export const fetchInstrument = (symbol: string) =>
  jget<InstrumentInfo>(`${API}/replay/instrument/${symbol}`);
export const fetchNews = (asof: string, days = 3) =>
  jget<NewsItem[]>(`${API}/replay/news?asof=${asof}&days=${days}`);
export interface GeneratePortfolioLeg {
  symbol: string; name: string; category: string;
  target_weight: number; current_price: number;
  pe_band: {state: string} | null;
}
export interface GeneratePortfolioResp {
  risk_profile: string; total_capital: number;
  investable_capital: number;
  legs: GeneratePortfolioLeg[];
  warnings: string[];
}
export const generatePortfolio = (body: {
  total_capital: number; risk_profile: string;
  stock_count: number; as_of: string;
}) => jpost<GeneratePortfolioResp>(`${API}/course-portfolio/generate`, body);
export const fetchValuation = (symbol: string, asof: string) =>
  jget<ValuationInfo>(`${API}/replay/valuation/${symbol}?asof=${asof}`);
export const fetchBoard = (asof: string, type: 'gainers' | 'amount') =>
  jget<BoardRow[]>(`${API}/replay/board?asof=${asof}&type=${type}`);
export const fetchMacroEvents = () =>
  jget<{date: string; title: string; desc: string}[]>(
    `${API}/macro/events`);

// ── 选股复用（现有端点，as_of 即旅程当前日） ──
export const runScreener = (mode: string, topN: number, asOf: string) =>
  jpost<{ranked_list: Record<string, unknown>[]}>(
    `${API}/screener/screen`, {mode, top_n: topN, as_of: asOf});
export const searchSymbols = (q: string) =>
  jget<{symbol: string; name: string; market: string}[]>(
    `${API}/market/search?q=${encodeURIComponent(q)}&market=A`);
export const listWatchGroups = () =>
  jget<{id: number; name: string}[]>(`${API}/watchlist/groups`);
export const listWatchItems = (gid: number) =>
  jget<{id: number; symbol: string; note?: string}[]>(
    `${API}/watchlist/groups/${gid}/items`);
