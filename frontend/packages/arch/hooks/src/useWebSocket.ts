/**
 * WebSocket hook for real-time data
 */
import {useEffect, useRef, useCallback, useState} from 'react';

export type WebSocketStatus = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' | 'ERROR';

export interface WebSocketMessage<T = unknown> {
  type: string;
  channel: string;
  data: T;
  timestamp: number;
}

interface UseWebSocketOptions {
  url: string;
  topics: string[];
  onMessage?: (message: WebSocketMessage) => void;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

export const useWebSocket = ({
  url,
  topics,
  onMessage,
  reconnectInterval = 3000,
  maxReconnectAttempts = 5,
}: UseWebSocketOptions) => {
  const [status, setStatus] = useState<WebSocketStatus>('DISCONNECTED');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      setStatus('CONNECTING');
      const ws = new WebSocket(url);

      ws.onopen = () => {
        setStatus('CONNECTED');
        reconnectAttemptsRef.current = 0;

        // Subscribe to topics
        topics.forEach(topic => {
          ws.send(
            JSON.stringify({
              type: 'SUBSCRIBE',
              channel: topic,
            })
          );
        });
      };

      ws.onmessage = event => {
        try {
          const message = JSON.parse(event.data) as WebSocketMessage;
          onMessage?.(message);
        } catch {
          console.warn('Failed to parse WebSocket message');
        }
      };

      ws.onerror = () => {
        setStatus('ERROR');
      };

      ws.onclose = () => {
        setStatus('DISCONNECTED');

        // Reconnect logic
        if (reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectAttemptsRef.current += 1;
            connect();
          }, reconnectInterval);
        }
      };

      wsRef.current = ws;
    } catch {
      setStatus('ERROR');
    }
  }, [url, topics, onMessage, reconnectInterval, maxReconnectAttempts]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus('DISCONNECTED');
  }, []);

  const send = useCallback((message: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  const subscribe = useCallback((topic: string) => {
    send({type: 'SUBSCRIBE', channel: topic});
  }, [send]);

  const unsubscribe = useCallback((topic: string) => {
    send({type: 'UNSUBSCRIBE', channel: topic});
  }, [send]);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    status,
    connect,
    disconnect,
    send,
    subscribe,
    unsubscribe,
  };
};

// Pre-configured hooks for common trading topics
export const useMarketWebSocket = (onTick: (data: {symbol: string; price: number; volume: number}) => void) => {
  return useWebSocket({
    url: import.meta.env.VITE_WS_URL || 'ws://localhost:8080/ws',
    topics: ['market.tickers', 'market.trades'],
    onMessage: msg => {
      if (msg.type === 'TICK' || msg.channel === 'market.tickers') {
        onTick(msg.data);
      }
    },
  });
};

// --- useMarketTick: real-time OHLCV tick stream via WebSocket ---
export interface TickData {
  trade_date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
}

export interface UseMarketTickOptions {
  symbol: string;
  onTick: (tick: TickData) => void;
  enabled?: boolean;
}

export function useMarketTick({ symbol, onTick, enabled = true }: UseMarketTickOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onTickRef = useRef(onTick);
  onTickRef.current = onTick;

  const getWsUrl = () => {
    const base = localStorage.getItem('ytrader_api_base');
    if (base && /^https?:\/\//.test(base)) {
      // 完整 URL（如 http://host:12101/api/v1）→ 直连后端
      const wsBase = base.replace(/^http/, 'ws').replace('/api/v1', '');
      return `${wsBase}/ws/market/tick/${symbol}`;
    }
    // 相对路径或未设置 → 走当前页面的 dev proxy（rsbuild /ws → 后端）
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}/ws/market/tick/${symbol}`;
  };

  const connect = useCallback(() => {
    if (!enabled || !symbol) return;
    const url = getWsUrl();
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data as string);
          if (msg.type === 'tick' && msg.data) {
            onTickRef.current(msg.data as TickData);
          }
        } catch { /* ignore parse errors */ }
      };

      ws.onerror = () => { /* swallow */ };
      ws.onclose = () => {
        wsRef.current = null;
        if (enabled) {
          reconnectTimer.current = setTimeout(connect, 3000);
        }
      };
    } catch { /* ignore */ }
  }, [symbol, enabled]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { sendPing: () => wsRef.current?.send('ping') };
}
