/**
 * A-Share Market Data Types
 */

export interface KlineBar {
  symbol: string;
  trade_date: string; // ISO 8601 UTC
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
}

export interface KlineResponse {
  bars: KlineBar[];
}

export interface SymbolsResponse {
  symbols: string[];
}

export interface ProcessedBar extends KlineBar {
  localTime: Date;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma60: number | null;
  rsi: number | null;
  isUp: boolean; // close >= open
}

export type TimeRange = '1M' | '3M' | '6M' | '1Y' | '2Y' | '5Y';

export const TIME_RANGE_LIMITS: Record<TimeRange, number> = {
  '1M': 30,
  '3M': 90,
  '6M': 180,
  '1Y': 365,
  '2Y': 730,
  '5Y': 1825,
};
