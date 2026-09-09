/**
 * Portfolio store
 */
import {create} from 'zustand';
import {devtools} from 'zustand/middleware';
import type {Position, Order, AccountBalance, PortfolioSummary} from './types';

interface PortfolioState {
  positions: Position[];
  orders: Order[];
  balance: AccountBalance | null;
  summary: PortfolioSummary | null;
  isLoading: boolean;
  error: string | null;

  // Actions
  setPositions: (positions: Position[]) => void;
  updatePosition: (id: string, updates: Partial<Position>) => void;
  removePosition: (id: string) => void;

  setOrders: (orders: Order[]) => void;
  addOrder: (order: Order) => void;
  updateOrder: (id: string, updates: Partial<Order>) => void;
  removeOrder: (id: string) => void;

  setBalance: (balance: AccountBalance | null) => void;
  setSummary: (summary: PortfolioSummary | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const usePortfolioStore = create<PortfolioState>()(
  devtools(
    (set) => ({
      positions: [],
      orders: [],
      balance: null,
      summary: null,
      isLoading: false,
      error: null,

      setPositions: (positions) => set({positions}),

      updatePosition: (id, updates) =>
        set((state) => ({
          positions: state.positions.map((p) =>
            p.id === id ? {...p, ...updates, updatedAt: Date.now()} : p
          ),
        })),

      removePosition: (id) =>
        set((state) => ({
          positions: state.positions.filter((p) => p.id !== id),
        })),

      setOrders: (orders) => set({orders}),

      addOrder: (order) =>
        set((state) => ({orders: [order, ...state.orders]})),

      updateOrder: (id, updates) =>
        set((state) => ({
          orders: state.orders.map((o) =>
            o.id === id ? {...o, ...updates, updatedAt: Date.now()} : o
          ),
        })),

      removeOrder: (id) =>
        set((state) => ({
          orders: state.orders.filter((o) => o.id !== id),
        })),

      setBalance: (balance) => set({balance}),

      setSummary: (summary) => set({summary}),

      setLoading: (isLoading) => set({isLoading}),

      setError: (error) => set({error}),
    }),
    {name: 'portfolio-store'}
  )
);

// Selectors
export const useOpenPositions = () =>
  usePortfolioStore((state) => state.positions);

export const useOpenOrders = () =>
  usePortfolioStore((state) => state.orders.filter((o) => o.status === 'PENDING'));

export const usePositionBySymbol = (symbol: string) =>
  usePortfolioStore((state) => state.positions.find((p) => p.symbol === symbol));

export const usePortfolioSummary = () => usePortfolioStore((state) => state.summary);
