/**
 * Portfolio components
 */
import React from 'react';
import {Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell, Badge, PnlBadge} from '@ytrader/common-components';
import type {Position} from '../types';
import {formatPrice, formatPercent} from '@ytrader/arch-utils';
import './PositionTable.css';

export interface PositionTableProps {
  positions: Position[];
  onSelect?: (position: Position) => void;
}

export const PositionTable: React.FC<PositionTableProps> = ({positions, onSelect}) => {
  if (positions.length === 0) {
    return (
      <div className="position-table__empty">
        <p>No open positions</p>
      </div>
    );
  }

  return (
    <Table variant="striped">
      <TableHead>
        <TableRow>
          <TableHeaderCell>Symbol</TableHeaderCell>
          <TableHeaderCell>Side</TableHeaderCell>
          <TableHeaderCell numeric>Size</TableHeaderCell>
          <TableHeaderCell numeric>Entry</TableHeaderCell>
          <TableHeaderCell numeric>Mark</TableHeaderCell>
          <TableHeaderCell numeric>Liq. Price</TableHeaderCell>
          <TableHeaderCell numeric>P&L</TableHeaderCell>
          <TableHeaderCell numeric>P&L %</TableHeaderCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {positions.map((position) => (
          <TableRow
            key={position.id}
            onClick={() => onSelect?.(position)}
            className="position-table__row"
          >
            <TableCell>{position.symbol}</TableCell>
            <TableCell>
              <Badge variant={position.side === 'LONG' ? 'success' : 'danger'}>
                {position.side}
              </Badge>
            </TableCell>
            <TableCell numeric>{position.quantity}</TableCell>
            <TableCell numeric>{formatPrice(position.entryPrice)}</TableCell>
            <TableCell numeric>{formatPrice(position.markPrice)}</TableCell>
            <TableCell numeric>
              {position.liquidationPrice
                ? formatPrice(position.liquidationPrice)
                : '-'}
            </TableCell>
            <TableCell numeric>
              <PnlBadge value={position.unrealizedPnl} />
            </TableCell>
            <TableCell numeric>
              <PnlBadge value={position.unrealizedPnlPercent} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};

export {OrderTable} from './OrderTable';
export {BalanceCard} from './BalanceCard';
