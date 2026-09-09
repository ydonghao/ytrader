/**
 * A-Share Market API Client
 */

import type { KlineResponse } from './types';

import { getApiBase } from '../../lib/api';
const API_BASE = getApiBase();

interface RawKlineResponse {
  code: number;
  msg: string;
  data: {
    symbol: string;
    interval: string;
    total: number;
    bars: Array<{
      trade_date: string;
      open: number;
      close: number;
      high: number;
      low: number;
      volume: number;
      amount: number;
    }>;
  };
}

export interface StockSearchResult {
  symbol: string;
  name: string;
}

/**
 * Server-side stock search — fuzzy match on code + name.
 * Returns a small, bounded result set (limit default 50), so the dropdown
 * never has to filter thousands of symbols client-side.
 */
export async function searchSymbols(
  q: string,
  market: string = 'A',
  limit: number = 50,
): Promise<StockSearchResult[]> {
  const url = `${API_BASE}/market/search?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}&limit=${limit}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to search symbols: ${res.status} ${res.statusText}`);
  }
  const data: { code: number; data: Array<{ symbol: string; name?: string }> } = await res.json();
  if (data.code !== 0 || !Array.isArray(data.data)) return [];
  return data.data.map((r) => ({ symbol: r.symbol, name: r.name || r.symbol }));
}

/**
 * K-line session cache: switching back to a previously viewed symbol renders
 * instantly instead of re-downloading 3000 bars (~0.5-0.8s). 5-minute TTL is
 * a good tradeoff for daily bars; real-time updates still come via WebSocket.
 */
const KLINE_CACHE_TTL_MS = 5 * 60 * 1000;
const klineCache = new Map<string, { ts: number; data: KlineResponse }>();

/**
 * Fetch K-line data for a given symbol
 */
export async function fetchKline(
  symbol: string,
  interval: string = '1d',
  limit: number = 3000
): Promise<KlineResponse> {
  const key = `${symbol}:${interval}:${limit}`;
  const cached = klineCache.get(key);
  if (cached && Date.now() - cached.ts < KLINE_CACHE_TTL_MS) {
    return cached.data;
  }
  const res = await fetch(
    `${API_BASE}/market/kline/${symbol}?interval=${interval}&limit=${limit}`
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch kline: ${res.status} ${res.statusText}`);
  }
  const data: RawKlineResponse = await res.json();
  const result = { bars: data.data.bars };
  klineCache.set(key, { ts: Date.now(), data: result });
  // Bound cache size: symbols are few in a session, drop oldest beyond 50
  if (klineCache.size > 50) {
    const oldest = klineCache.keys().next().value;
    if (oldest !== undefined) klineCache.delete(oldest);
  }
  return result;
}
