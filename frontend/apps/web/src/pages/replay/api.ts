import {getApiBase} from '../../lib/api';
import type {
  AdvanceResp, ApiResp, BoardRow, ReplayBar, SessionFull,
  SessionMeta, Trade, ValuationInfo,
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
export const fetchValuation = (symbol: string, asof: string) =>
  jget<ValuationInfo>(`${API}/replay/valuation/${symbol}?asof=${asof}`);
export const fetchBoard = (asof: string, type: 'gainers' | 'amount') =>
  jget<BoardRow[]>(`${API}/replay/board?asof=${asof}&type=${type}`);

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
