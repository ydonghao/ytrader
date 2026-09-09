/**
 * Market data store
 */
import {create} from 'zustand';
import {devtools} from 'zustand/middleware';
import type {Ticker, KlineData, OrderBook, Trade} from './types';

interface MarketDataState {
  tickers: Map<string, Ticker>;
  klineData: Map<string, KlineData[]>;
  orderBook: OrderBook | null;
  recentTrades: Trade[];
  selectedSymbol: string;
  selectedInterval: string;
  isLoading: boolean;
  error: string | null;

  // Actions
  setTickers: (tickers: Ticker[]) => void;
  updateTicker: (ticker: Ticker) => void;
  setKlineData: (symbol: string, data: KlineData[]) => void;
  appendKlineData: (symbol: string, data: KlineData) => void;
  setOrderBook: (orderBook: OrderBook | null) => void;
  setRecentTrades: (trades: Trade[]) => void;
  addTrade: (trade: Trade) => void;
  setSelectedSymbol: (symbol: string) => void;
  setSelectedInterval: (interval: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useMarketDataStore = create<MarketDataState>()(
  devtools(
    (set) => ({
      tickers: new Map(),
      klineData: new Map(),
      orderBook: null,
      recentTrades: [],
      selectedSymbol: 'BTCUSDT',
      selectedInterval: '1h',
      isLoading: false,
      error: null,

      setTickers: (tickers) =>
        set({
          tickers: new Map(tickers.map((t) => [t.symbol, t])),
        }),

      updateTicker: (ticker) =>
        set((state) => {
          const newTickers = new Map(state.tickers);
          newTickers.set(ticker.symbol, ticker);
          return {tickers: newTickers};
        }),

      setKlineData: (symbol, data) =>
        set((state) => {
          const newKlineData = new Map(state.klineData);
          newKlineData.set(symbol, data);
          return {klineData: newKlineData};
        }),

      appendKlineData: (symbol, data) =>
        set((state) => {
          const existing = state.klineData.get(symbol) || [];
          const newKlineData = new Map(state.klineData);
          newKlineData.set(symbol, [...existing, data]);
          return {klineData: newKlineData};
        }),

      setOrderBook: (orderBook) => set({orderBook}),

      setRecentTrades: (trades) => set({recentTrades: trades}),

      addTrade: (trade) =>
        set((state) => ({
          recentTrades: [trade, ...state.recentTrades].slice(0, 100),
        })),

      setSelectedSymbol: (selectedSymbol) => set({selectedSymbol}),

      setSelectedInterval: (selectedInterval) => set({selectedInterval}),

      setLoading: (isLoading) => set({isLoading}),

      setError: (error) => set({error}),
    }),
    {name: 'market-data-store'}
  )
);

// Selectors
export const useTicker = (symbol: string) =>
  useMarketDataStore((state) => state.tickers.get(symbol));

export const useAllTickers = () =>
  useMarketDataStore((state) => Array.from(state.tickers.values()));

export const useKlineData = (symbol: string) =>
  useMarketDataStore((state) => state.klineData.get(symbol) || []);

export const useOrderBook = () => useMarketDataStore((state) => state.orderBook);

export const useRecentTrades = () => useMarketDataStore((state) => state.recentTrades);
