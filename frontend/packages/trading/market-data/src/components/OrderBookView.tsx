/**
 * Order book view component
 */
import React from 'react';
import {Card, CardContent} from '@ytrader/common-components';
import {formatPrice, formatVolume} from '@ytrader/arch-utils';
import type {OrderBook, OrderBookEntry} from '../types';
import './OrderBookView.css';

export interface OrderBookViewProps {
  orderBook: OrderBook | null;
  precision?: number;
}

export const OrderBookView: React.FC<OrderBookViewProps> = ({
  orderBook,
  precision = 2,
}) => {
  if (!orderBook) {
    return (
      <Card className="order-book">
        <CardContent>
          <div className="order-book__empty">Loading order book...</div>
        </CardContent>
      </Card>
    );
  }

  const maxBidTotal = Math.max(...orderBook.bids.map((b) => b.total || 0));
  const maxAskTotal = Math.max(...orderBook.asks.map((a) => a.total || 0));

  const renderRow = (entry: OrderBookEntry, side: 'bid' | 'ask', maxTotal: number) => {
    const total = entry.total || 0;
    const depthPercent = (total / maxTotal) * 100;

    return (
      <div key={entry.price} className={`order-book__row order-book__row--${side}`}>
        <div
          className={`order-book__depth order-book__depth--${side}`}
          style={{width: `${depthPercent}%`}}
        />
        <span className="order-book__price">{formatPrice(entry.price)}</span>
        <span className="order-book__quantity">{formatVolume(entry.quantity)}</span>
        <span className="order-book__total">{formatVolume(total)}</span>
      </div>
    );
  };

  return (
    <Card className="order-book">
      <CardContent>
        <div className="order-book__header">
          <span>Price</span>
          <span>Quantity</span>
          <span>Total</span>
        </div>
        <div className="order-book__asks">
          {[...orderBook.asks].reverse().map((ask) => renderRow(ask, 'ask', maxAskTotal))}
        </div>
        <div className="order-book__spread">
          <span>Spread</span>
          <span>
            {orderBook.asks[0] && orderBook.bids[0]
              ? formatPrice(orderBook.asks[0].price - orderBook.bids[0].price)
              : '-'}
          </span>
        </div>
        <div className="order-book__bids">
          {orderBook.bids.map((bid) => renderRow(bid, 'bid', maxBidTotal))}
        </div>
      </CardContent>
    </Card>
  );
};
