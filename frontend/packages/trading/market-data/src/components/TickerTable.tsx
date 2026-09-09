/**
 * Market data components
 */
import React from 'react';
import {Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell, Badge, PnlBadge} from '@ytrader/common-components';
import {formatPrice, formatVolume, formatPercent} from '@ytrader/arch-utils';
import type {Ticker} from '../types';
import './TickerTable.css';

export interface TickerTableProps {
  tickers: Ticker[];
  onSelect?: (ticker: Ticker) => void;
  selectedSymbol?: string;
}

export const TickerTable: React.FC<TickerTableProps> = ({
  tickers,
  onSelect,
  selectedSymbol,
}) => {
  if (tickers.length === 0) {
    return (
      <div className="ticker-table__empty">
        <p>No market data available</p>
      </div>
    );
  }

  return (
    <Table variant="striped" className="ticker-table">
      <TableHead>
        <TableRow>
          <TableHeaderCell>Symbol</TableHeaderCell>
          <TableHeaderCell numeric>Price</TableHeaderCell>
          <TableHeaderCell numeric>24h Change</TableHeaderCell>
          <TableHeaderCell numeric>24h High</TableHeaderCell>
          <TableHeaderCell numeric>24h Low</TableHeaderCell>
          <TableHeaderCell numeric>24h Volume</TableHeaderCell>
          <TableHeaderCell numeric>Quote Volume</TableHeaderCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {tickers.map((ticker) => (
          <TableRow
            key={ticker.symbol}
            onClick={() => onSelect?.(ticker)}
            className={`ticker-table__row ${
              selectedSymbol === ticker.symbol ? 'ticker-table__row--selected' : ''
            }`}
          >
            <TableCell>
              <span className="ticker-table__symbol">{ticker.symbol}</span>
            </TableCell>
            <TableCell numeric>{formatPrice(ticker.price)}</TableCell>
            <TableCell numeric>
              <PnlBadge value={ticker.priceChangePercent} />
            </TableCell>
            <TableCell numeric>{formatPrice(ticker.high24h)}</TableCell>
            <TableCell numeric>{formatPrice(ticker.low24h)}</TableCell>
            <TableCell numeric>{formatVolume(ticker.volume24h)}</TableCell>
            <TableCell numeric>{formatVolume(ticker.quoteVolume24h)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};

export {KlineChart} from './KlineChart';
export {OrderBookView} from './OrderBookView';
export {TradeHistory} from './TradeHistory';
