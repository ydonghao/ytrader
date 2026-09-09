/**
 * Portfolio types
 */

export type PositionSide = 'LONG' | 'SHORT';

export interface Position {
  id: string;
  symbol: string;
  side: PositionSide;
  quantity: number;
  entryPrice: number;
  markPrice: number;
  unrealizedPnl: number;
  unrealizedPnlPercent: number;
  realizedPnl: number;
  leverage: number;
  liquidationPrice?: number;
  margin: number;
  stopLoss?: number;
  takeProfit?: number;
  openedAt: number;
  updatedAt: number;
}

export interface Order {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  type: 'LIMIT' | 'MARKET' | 'STOP_LOSS' | 'TAKE_PROFIT';
  price?: number;
  stopPrice?: number;
  quantity: number;
  filledQuantity: number;
  avgFilledPrice?: number;
  status: 'PENDING' | 'FILLED' | 'PARTIALLY_FILLED' | 'CANCELLED' | 'REJECTED';
  createdAt: number;
  updatedAt: number;
}

export interface AccountBalance {
  totalEquity: number;
  availableBalance: number;
  totalPositionMargin: number;
  totalOrderMargin: number;
  unrealizedPnl: number;
  realizedPnl: number;
  totalCollateral: number;
  marginLevel?: number;
  leverage: number;
}

export interface Trade {
  id: string;
  orderId: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  price: number;
  quantity: number;
  fee: number;
  realizedPnl?: number;
  timestamp: number;
}

export interface PortfolioSummary {
  totalBalance: number;
  totalPnl: number;
  totalPnlPercent: number;
  todayPnl: number;
  openPositions: number;
  totalTrades: number;
  winRate: number;
}
