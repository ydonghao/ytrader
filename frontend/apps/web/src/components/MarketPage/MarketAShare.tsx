/**
 * MarketAShare - A-Share Stock Market Dashboard Page
 *
 * Features:
 * - Stock search dropdown
 * - Real candlestick chart (lightweight-charts, shared component) with
 *   MA5/10/20/60, volume pane, interval + time-range controls, WebSocket ticks
 * - RSI(14) panel (recharts)
 * - 分时成交 panel
 */
import React, { useState, useEffect, useCallback } from 'react';
import { StockSelect } from './StockSelect';
import { RSIPanel } from './RSIPanel';
import { KlineChart as CandleChart, TradeHistory } from '@ytrader/trading-market-data';
import type { Trade } from '@ytrader/trading-market-data';
import { fetchKline } from './api';
import { getApiBase } from '../../lib/api';
import { processKlineBars } from './indicators';
import type { ProcessedBar } from './types';
import { StateView } from '../../components/ui';
import './MarketPage.css';

// RSI 面板固定展示最近约 1 年（~250 根日线），内部会再采样到 200 点
const RSI_BARS = 250;

export const MarketAShare: React.FC = () => {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('sh600000');

  const [klineData, setKlineData] = useState<ProcessedBar[]>([]);
  const [klineLoading, setKlineLoading] = useState(false);
  const [klineError, setKlineError] = useState<string | null>(null);

  const [trades, setTrades] = useState<Trade[]>([]);
  const [tradesLoading, setTradesLoading] = useState(false);

  // 拉全量日线（fetchKline 带 5 分钟会话缓存，切回已看过的标的秒开）。
  // 仅用于价格信息和 RSI；蜡烛图本身由共享 CandleChart 自行取数。
  const loadKlineData = useCallback((symbol: string) => {
    let cancelled = false;
    setKlineLoading(true);
    setKlineError(null);

    fetchKline(symbol, '1d', 3000)
      .then((res) => {
        if (cancelled) return;
        const processed = processKlineBars(res.bars || []);
        setKlineData(processed);
        setKlineLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setKlineError(err.message);
        setKlineLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    loadKlineData(selectedSymbol);
  }, [selectedSymbol, loadKlineData]);

  // Fetch trades (分时成交)
  useEffect(() => {
    let cancelled = false;
    setTradesLoading(true);
    const controller = new AbortController();
    const apiBase = getApiBase();
    fetch(`${apiBase}/market/trades/${selectedSymbol}?limit=200`, { signal: controller.signal })
      .then((r) => r.json())
      .then((json) => {
        if (cancelled) return;
        if (json.code === 0) {
          setTrades(json.data.trades || []);
        } else {
          setTrades([]);
        }
        setTradesLoading(false);
      })
      .catch(() => {
        if (!cancelled) setTrades([]);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [selectedSymbol]);

  // Current price info（取全量数据的最后一根，与时间范围无关）
  const lastBar = klineData[klineData.length - 1];
  const prevBar = klineData[klineData.length - 2];

  const priceChange = lastBar && prevBar
    ? lastBar.close - prevBar.close
    : 0;
  const priceChangePercent = lastBar && prevBar && prevBar.close !== 0
    ? (priceChange / prevBar.close) * 100
    : 0;

  // RSI 数据：最近约 1 年
  const rsiData = klineData.length > RSI_BARS
    ? klineData.slice(-RSI_BARS)
    : klineData;

  return (
    <div className="market-ashare">
      {/* Toolbar */}
      <div className="market-ashare__toolbar">
        <div className="market-ashare__toolbar-left">
          <h2 className="market-ashare__title">A股市场</h2>
          <StockSelect
            value={selectedSymbol}
            onChange={(sym) => setSelectedSymbol(sym)}
            market="A"
          />
          {lastBar && (
            <div className="price-info">
              <span className="price-info__symbol">{selectedSymbol.toUpperCase()}</span>
              <span className={`num price-info__price ${priceChange >= 0 ? 'price-info__price--up' : 'price-info__price--down'}`}>
                {lastBar.close.toFixed(2)}
              </span>
              <span className={`num price-info__change ${priceChange >= 0 ? 'price-info__change--up' : 'price-info__change--down'}`}>
                {priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)} ({priceChangePercent >= 0 ? '+' : ''}{priceChangePercent.toFixed(2)}%)
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Charts */}
      <div className="market-ashare__charts">
        {/* 真蜡烛图（与其他 Tab 一致的共享组件：K线 + 量 + MA + 周期/范围按钮 + 实时推送）*/}
        <CandleChart symbol={selectedSymbol} interval="1d" height={480} />

        {/* RSI Panel */}
        <div className="market-ashare__chart-card">
          <div className="market-ashare__chart-body">
            {klineLoading && klineData.length === 0 ? (
              <div className="skeleton skeleton-chart" style={{ height: 120 }} />
            ) : klineError ? (
              <StateView
                state="error"
                text={`RSI 加载失败: ${klineError}`}
                onRetry={() => loadKlineData(selectedSymbol)}
              />
            ) : (
              <RSIPanel data={rsiData} height={120} />
            )}
          </div>
        </div>

        {/* 分时成交 */}
        <div className="market-ashare__chart-card" style={{ maxHeight: 320 }}>
          <div className="market-ashare__chart-header">
            <h3 className="market-ashare__chart-title">分时成交</h3>
          </div>
          <div className="market-ashare__chart-body" style={{ overflow: 'auto' }}>
            {tradesLoading ? (
              <div className="skeleton" style={{ height: 200 }} />
            ) : trades.length === 0 ? (
              <StateView state="empty" text="暂无分时数据" />
            ) : (
              <TradeHistory trades={trades} symbol={selectedSymbol} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
