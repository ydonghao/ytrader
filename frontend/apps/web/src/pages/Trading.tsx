/**
 * Trading page
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Input, Select, Badge } from '@ytrader/common-components';
import { OrderTable, BalanceCard } from '@ytrader/trading-portfolio';
import type { Order, AccountBalance } from '@ytrader/trading-portfolio';
import { getApiBase } from '../lib/api';
import { useIntervalWhenVisible } from '../hooks/useIntervalWhenVisible';
import { PageHeader, StateView } from '../components/ui';
import './Trading.css';

const API_BASE = getApiBase();

interface BackendAccount {
  account_id: string;
  total_assets: number;
  cash: number;
  positions_value: number;
  total_profit: number;
  total_profit_pct: number;
  frozen_cash: number;
  margin_used: number;
  status: string;
}

function mapBackendAccount(data: BackendAccount): AccountBalance {
  return {
    totalEquity: data.total_assets,
    availableBalance: data.cash,
    totalPositionMargin: data.margin_used,
    totalOrderMargin: data.frozen_cash,
    unrealizedPnl: data.total_profit,
    realizedPnl: 0,
    totalCollateral: data.total_assets,
    leverage: 1,
  };
}

function mapOrderStatus(status: string): Order['status'] {
  const map: Record<string, Order['status']> = {
    PENDING: 'PENDING',
    FILLED: 'FILLED',
    PARTIALLY_FILLED: 'PARTIALLY_FILLED',
    CANCELLED: 'CANCELLED',
    REJECTED: 'REJECTED',
  };
  return map[status] ?? 'PENDING';
}

function mapBackendOrder(data: any): Order {
  return {
    id: String(data.id),
    symbol: data.symbol,
    side: data.side === 'BUY' ? 'BUY' : 'SELL',
    type: data.order_type === 'MARKET' ? 'MARKET' : 'LIMIT',
    price: data.price,
    quantity: data.quantity,
    filledQuantity: data.filled_qty ?? 0,
    status: mapOrderStatus(data.status),
    createdAt: new Date(data.created_at).getTime(),
    updatedAt: new Date(data.created_at).getTime(),
  };
}

async function fetchAccount(abortCtrl: AbortController): Promise<AccountBalance | null> {
  const res = await fetch(`${API_BASE}/trade/account`, { signal: abortCtrl.signal });
  if (!res.ok) return null;
  const json = await res.json();
  if (json.code !== 0) return null;
  return mapBackendAccount(json.data);
}

async function fetchOrders(abortCtrl: AbortController): Promise<Order[]> {
  const res = await fetch(`${API_BASE}/trade/orders`, { signal: abortCtrl.signal });
  if (!res.ok) throw new Error(`Orders fetch failed: ${res.status}`);
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.msg || 'Orders API error');
  return (json.data || []).map(mapBackendOrder);
}

async function cancelOrder(orderId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/trade/orders/${orderId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Cancel failed: ${res.status}`);
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.msg || 'Cancel order failed');
}

export const Trading: React.FC = () => {
  const [balance, setBalance] = useState<AccountBalance | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [loadingOrders, setLoadingOrders] = useState(true);
  const [loadingBalance, setLoadingBalance] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [symbol, setSymbol] = useState('');
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY');
  const [orderType, setOrderType] = useState<'LIMIT' | 'MARKET'>('LIMIT');
  const [price, setPrice] = useState('');
  const [quantity, setQuantity] = useState('');

  // Feedback state
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const abortCtrlRef = useRef<AbortController | null>(null);

  const loadBalance = useCallback(async () => {
    const ctrl = new AbortController();
    abortCtrlRef.current = ctrl;
    try {
      const bal = await fetchAccount(ctrl);
      setBalance(bal);
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        // balance failure is non-fatal, keep previous
      }
    } finally {
      setLoadingBalance(false);
    }
  }, []);

  const loadOrders = useCallback(async () => {
    try {
      const ctrl = new AbortController();
      const data = await fetchOrders(ctrl);
      setOrders(data);
      setError(null);
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        setError(e.message || 'Failed to load orders');
      }
    } finally {
      setLoadingOrders(false);
    }
  }, []);

  useEffect(() => {
    loadBalance();
    loadOrders();

    return () => {
      abortCtrlRef.current?.abort();
    };
  }, [loadBalance, loadOrders]);

  // 5s 轮询账户 + 订单；页面隐藏时暂停（见 useIntervalWhenVisible）
  useIntervalWhenVisible(() => {
    loadBalance();
    loadOrders();
  }, 5000);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitMsg(null);

    if (!symbol.trim()) {
      setSubmitMsg({ type: 'error', text: 'Symbol is required' });
      return;
    }
    if (!quantity || parseFloat(quantity) <= 0) {
      setSubmitMsg({ type: 'error', text: 'Quantity must be greater than 0' });
      return;
    }
    if (orderType === 'LIMIT' && (!price || parseFloat(price) <= 0)) {
      setSubmitMsg({ type: 'error', text: 'Price must be greater than 0 for limit orders' });
      return;
    }

    setSubmitting(true);
    try {
      const body: any = {
        symbol: symbol.trim().toUpperCase(),
        side: side,
        order_type: orderType,
        quantity: parseFloat(quantity),
      };
      if (orderType === 'LIMIT') {
        body.price = parseFloat(price);
      }

      const res = await fetch(`${API_BASE}/trade/orders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (json.code !== 0) throw new Error(json.msg || 'Order submission failed');

      setSubmitMsg({ type: 'success', text: 'Order placed successfully!' });
      setPrice('');
      setQuantity('');
      loadOrders();
    } catch (e: any) {
      setSubmitMsg({ type: 'error', text: e.message || 'Failed to place order' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (order: Order) => {
    setCancellingId(order.id);
    try {
      await cancelOrder(order.id);
      setOrders((prev) => prev.filter((o) => o.id !== order.id));
    } catch (e: any) {
      setSubmitMsg({ type: 'error', text: e.message || 'Failed to cancel order' });
    } finally {
      setCancellingId(null);
    }
  };

  const total = orderType === 'LIMIT' && price && quantity
    ? (parseFloat(price) * parseFloat(quantity)).toFixed(2)
    : '—';

  return (
    <div className="trading">
      <PageHeader title="交易" subtitle="下单与订单管理" />

      <div className="trading__content">
        <div className="trading__left">
          <Card>
            <CardHeader>
              <CardTitle>Account Balance</CardTitle>
            </CardHeader>
            <CardContent>
              {loadingBalance ? (
                <StateView state="loading" />
              ) : balance ? (
                <BalanceCard balance={balance} />
              ) : (
                <StateView state="empty" text="无法加载账户余额" />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Place Order</CardTitle>
            </CardHeader>
            <CardContent>
              <form className="trading__form" onSubmit={handleSubmit}>
                <div className="trading__field">
                  <Input
                    label="Symbol"
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                    placeholder="BTCUSDT"
                  />
                </div>

                <div className="trading__side-toggle">
                  <button
                    type="button"
                    className={`trading__side-btn ${side === 'BUY' ? 'trading__side-btn--active-buy' : ''}`}
                    onClick={() => setSide('BUY')}
                  >
                    Buy
                  </button>
                  <button
                    type="button"
                    className={`trading__side-btn ${side === 'SELL' ? 'trading__side-btn--active-sell' : ''}`}
                    onClick={() => setSide('SELL')}
                  >
                    Sell
                  </button>
                </div>

                <div className="trading__field">
                  <Select
                    label="Order Type"
                    options={[
                      { label: 'Limit', value: 'LIMIT' },
                      { label: 'Market', value: 'MARKET' },
                    ]}
                    value={orderType}
                    onChange={(val) => setOrderType(val as 'LIMIT' | 'MARKET')}
                  />
                </div>

                {orderType === 'LIMIT' && (
                  <div className="trading__field">
                    <Input
                      label="Price (USDT)"
                      type="number"
                      value={price}
                      onChange={(e) => setPrice(e.target.value)}
                      placeholder="0.00"
                    />
                  </div>
                )}

                <div className="trading__field">
                  <Input
                    label="Quantity"
                    type="number"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    placeholder="0.00"
                  />
                </div>

                <div className="trading__total">
                  <span>Total</span>
                  <span>{total} USDT</span>
                </div>

                {submitMsg && (
                  <div className={`trading__feedback trading__feedback--${submitMsg.type}`}>
                    {submitMsg.text}
                  </div>
                )}

                <Button
                  variant={side === 'BUY' ? 'success' : 'danger'}
                  fullWidth
                  type="submit"
                  disabled={submitting}
                >
                  {submitting ? 'Placing...' : `${side === 'BUY' ? 'Buy' : 'Sell'}`}
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>

        <div className="trading__right">
          <Card>
            <CardHeader>
              <CardTitle>Open Orders</CardTitle>
            </CardHeader>
            <CardContent>
              {loadingOrders ? (
                <StateView state="loading" />
              ) : error ? (
                <StateView state="error" text={error} onRetry={() => loadOrders()} />
              ) : (
                // 仅渲染最近 50 条订单：该接口每 5s 轮询，全量渲染长历史会卡顿。
                <OrderTable
                  orders={orders.slice(-50).reverse()}
                  onCancel={(o) => {
                    if (cancellingId === null) handleCancel(o);
                  }}
                />
              )}
              {cancellingId && (
                <div className="trading__cancelling">
                  <div className="spinner spinner--xs" /> Cancelling...
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};
