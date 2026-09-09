/**
 * Order table component
 */
import React from 'react';
import {Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell, Badge} from '@ytrader/common-components';
import {formatPrice, formatDate} from '@ytrader/arch-utils';
import type {Order} from '../types';
import './OrderTable.css';

export interface OrderTableProps {
  orders: Order[];
  onCancel?: (order: Order) => void;
}

const statusBadgeVariant = {
  PENDING: 'warning' as const,
  FILLED: 'success' as const,
  PARTIALLY_FILLED: 'info' as const,
  CANCELLED: 'default' as const,
  REJECTED: 'danger' as const,
};

export const OrderTable: React.FC<OrderTableProps> = ({orders, onCancel}) => {
  if (orders.length === 0) {
    return (
      <div className="order-table__empty">
        <p>No orders</p>
      </div>
    );
  }

  return (
    <Table variant="striped">
      <TableHead>
        <TableRow>
          <TableHeaderCell>Time</TableHeaderCell>
          <TableHeaderCell>Symbol</TableHeaderCell>
          <TableHeaderCell>Side</TableHeaderCell>
          <TableHeaderCell>Type</TableHeaderCell>
          <TableHeaderCell numeric>Price</TableHeaderCell>
          <TableHeaderCell numeric>Quantity</TableHeaderCell>
          <TableHeaderCell numeric>Filled</TableHeaderCell>
          <TableHeaderCell>Status</TableHeaderCell>
          <TableHeaderCell>Action</TableHeaderCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {orders.map((order) => (
          <TableRow key={order.id} className="order-table__row">
            <TableCell>{formatDate(order.createdAt)}</TableCell>
            <TableCell>{order.symbol}</TableCell>
            <TableCell>
              <Badge variant={order.side === 'BUY' ? 'success' : 'danger'}>
                {order.side}
              </Badge>
            </TableCell>
            <TableCell>{order.type}</TableCell>
            <TableCell numeric>
              {order.price ? formatPrice(order.price) : 'Market'}
            </TableCell>
            <TableCell numeric>{order.quantity}</TableCell>
            <TableCell numeric>
              {order.filledQuantity}/{order.quantity}
            </TableCell>
            <TableCell>
              <Badge variant={statusBadgeVariant[order.status]}>
                {order.status}
              </Badge>
            </TableCell>
            <TableCell>
              {order.status === 'PENDING' && onCancel && (
                <button
                  className="order-table__cancel"
                  onClick={() => onCancel(order)}
                >
                  Cancel
                </button>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};
