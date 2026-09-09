/**
 * Balance card component
 */
import React from 'react';
import {Card, CardContent} from '@ytrader/common-components';
import {formatCurrency} from '@ytrader/arch-utils';
import type {AccountBalance} from '../types';
import './BalanceCard.css';

export interface BalanceCardProps {
  balance: AccountBalance;
}

export const BalanceCard: React.FC<BalanceCardProps> = ({balance}) => {
  return (
    <Card className="balance-card">
      <CardContent>
        <div className="balance-card__grid">
          <div className="balance-card__item">
            <span className="balance-card__label">Total Equity</span>
            <span className="balance-card__value">
              {formatCurrency(balance.totalEquity)}
            </span>
          </div>

          <div className="balance-card__item">
            <span className="balance-card__label">Available</span>
            <span className="balance-card__value">
              {formatCurrency(balance.availableBalance)}
            </span>
          </div>

          <div className="balance-card__item">
            <span className="balance-card__label">Unrealized P&L</span>
            <span
              className={`balance-card__value ${
                balance.unrealizedPnl >= 0 ? 'positive' : 'negative'
              }`}
            >
              {formatCurrency(balance.unrealizedPnl)}
            </span>
          </div>

          <div className="balance-card__item">
            <span className="balance-card__label">Position Margin</span>
            <span className="balance-card__value">
              {formatCurrency(balance.totalPositionMargin)}
            </span>
          </div>

          <div className="balance-card__item">
            <span className="balance-card__label">Order Margin</span>
            <span className="balance-card__value">
              {formatCurrency(balance.totalOrderMargin)}
            </span>
          </div>

          <div className="balance-card__item">
            <span className="balance-card__label">Leverage</span>
            <span className="balance-card__value">{balance.leverage}x</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
