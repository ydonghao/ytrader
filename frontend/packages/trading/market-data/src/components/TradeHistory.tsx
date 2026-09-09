/**
 * Trade history component
 */
import React from 'react';
import {Card, CardContent, Badge} from '@ytrader/common-components';
import {formatPrice, formatVolume, formatRelativeTime} from '@ytrader/arch-utils';
import type {Trade} from '../types';
import './TradeHistory.css';

export interface TradeHistoryProps {
  trades: Trade[];
  symbol?: string;
}

export const TradeHistory: React.FC<TradeHistoryProps> = ({trades, symbol}) => {
  if (trades.length === 0) {
    return (
      <Card className="trade-history">
        <CardContent>
          <div className="trade-history__empty">Loading trade history...</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="trade-history">
      <CardContent>
        <div className="trade-history__header">
          <span>Price</span>
          <span>Quantity</span>
          <span>Time</span>
        </div>
        <div className="trade-history__list">
          {trades.slice(0, 50).map((trade) => (
            <div key={trade.id} className="trade-history__row">
              <span className={`trade-history__price trade-history__price--${trade.side.toLowerCase()}`}>
                {formatPrice(trade.price)}
              </span>
              <span className="trade-history__quantity">{formatVolume(trade.quantity)}</span>
              <span className="trade-history__time">{formatRelativeTime(trade.timestamp)}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};
