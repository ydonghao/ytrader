/**
 * Real K-Line Candlestick Chart using lightweight-charts
 * Fetches data from /market/kline/{symbol}?interval=...
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useMarketTick } from '@ytrader/arch-hooks';
import { createChart, IChartApi, ISeriesApi, CandlestickData, HistogramData, LineData, Time, CandlestickSeries, HistogramSeries, LineSeries } from 'lightweight-charts';
import { Card, CardContent } from '@ytrader/common-components';
import './KlineChart.css';

export interface KlineBar {
  trade_date: string; // "2024-01-15"
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
}

export interface KlineResponse {
  symbol: string;
  interval: string;
  total: number;
  bars: KlineBar[];
}

export interface KlineChartProps {
  symbol: string;
  interval?: string;
  timeRange?: string; // 初始时间范围，默认 '1Y'；可选值见 TIME_RANGES
  height?: number;
  onIntervalChange?: (interval: string) => void;
  onTimeRangeChange?: (range: string) => void;
}

const INTERVALS = [
  { label: '日K', value: '1d' },
  { label: '60分钟', value: '60m' },
  { label: '30分钟', value: '30m' },
  { label: '15分钟', value: '15m' },
  { label: '5分钟', value: '5m' },
];

// 时间范围筛选：1月/3月/6月/1年/2年/5年/全部（与个股 Tab 一致 + 全部）
const TIME_RANGES = [
  { label: '1月', value: '1M' },
  { label: '3月', value: '3M' },
  { label: '6月', value: '6M' },
  { label: '1年', value: '1Y' },
  { label: '2年', value: '2Y' },
  { label: '5年', value: '5Y' },
  { label: '全部', value: 'ALL' },
];
const TIME_RANGE_DAYS: Record<string, number | undefined> = {
  '1M': 30, '3M': 90, '6M': 180, '1Y': 365, '2Y': 730, '5Y': 1825,
};

const getApiBase = () => localStorage.getItem('ytrader_api_base') || '/api/v1';

// lightweight-charts 需要具体色值（非 CSS 变量），此处内联与宿主设计令牌等值的常量
// A 股惯例：红涨绿跌
const COLOR_UP = '#ff453a';
const COLOR_DOWN = '#30d158';
const COLOR_ACCENT = '#0a84ff';
const COLOR_TEXT_SECONDARY = '#a1a1a6';
const COLOR_VOLUME_UP = 'rgba(255, 69, 58, 0.4)';
const COLOR_VOLUME_DOWN = 'rgba(48, 209, 88, 0.4)';
const API_BASE = getApiBase();

function parseDate(dateStr: string): number {
  // Backend returns "2024-01-15" or "2024-01-15T00:00:00"
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00');
  return Math.floor(d.getTime() / 1000);
}

// 会话级 K 线缓存：切回已看过的标的/周期时免请求秒开（原来每次 ~0.5-0.8s）。
// 5 分钟 TTL；实时更新仍走 WebSocket，不受缓存影响。
interface CachedKlineData {
  ts: number;
  candle: CandlestickData<Time>[];
  volume: HistogramData<Time>[];
  ma5: LineData<Time>[];
  ma10: LineData<Time>[];
  ma20: LineData<Time>[];
  ma60: LineData<Time>[];
  lastBar: KlineBar;
}
const KLINE_CACHE_TTL_MS = 5 * 60 * 1000;
const klineChartCache = new Map<string, CachedKlineData>();

export const KlineChart: React.FC<KlineChartProps> = ({
  symbol,
  interval: initialInterval = '1d',
  timeRange: initialTimeRange = '1Y',
  height = 400,
  onIntervalChange,
  onTimeRangeChange,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const ma5SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ma10SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ma20SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ma60SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeInterval, setActiveInterval] = useState(initialInterval);
  const [activeTimeRange, setActiveTimeRange] = useState(initialTimeRange);
  const lastBarRef = useRef<KlineBar | null>(null);

  // 时间范围用 ref 参与 setData 切片逻辑，避免切范围时触发 loadData 重取数
  const activeTimeRangeRef = useRef(activeTimeRange);
  useEffect(() => {
    activeTimeRangeRef.current = activeTimeRange;
  }, [activeTimeRange]);

  // 全量数据缓存（MA 已在全量上算好）：切时间范围时从此切片，不重新请求
  const fullDataRef = useRef<{
    candle: CandlestickData<Time>[];
    volume: HistogramData<Time>[];
    ma5: LineData<Time>[]; ma10: LineData<Time>[]; ma20: LineData<Time>[]; ma60: LineData<Time>[];
  } | null>(null);

  const calcSMA = useCallback((closes: number[], index: number, period: number): number | null => {
    if (index < period - 1) return null;
    let sum = 0;
    for (let i = index - period + 1; i <= index; i++) sum += closes[i];
    return sum / period;
  }, []);

  const initChart = useCallback(() => {
    if (!containerRef.current) return;

    // Cleanup existing chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: COLOR_TEXT_SECONDARY,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(161, 161, 166, 0.15)' },
        horzLines: { color: 'rgba(161, 161, 166, 0.15)' },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: 'rgba(161, 161, 166, 0.4)', width: 1, style: 2 },
        horzLine: { color: 'rgba(161, 161, 166, 0.4)', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: 'rgba(161, 161, 166, 0.2)',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: 'rgba(161, 161, 166, 0.2)',
        timeVisible: true,
        secondsVisible: false,
      },
      height,
    });

    chartRef.current = chart;

    // Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: COLOR_UP,
      downColor: COLOR_DOWN,
      borderUpColor: COLOR_UP,
      borderDownColor: COLOR_DOWN,
      wickUpColor: COLOR_UP,
      wickDownColor: COLOR_DOWN,
    });
    candleSeriesRef.current = candleSeries;

    // Volume histogram (in separate pane)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#6366f1',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    volumeSeriesRef.current = volumeSeries;

    // MA lines
    const ma5Series = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ma10Series = chart.addSeries(LineSeries, { color: COLOR_ACCENT, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ma20Series = chart.addSeries(LineSeries, { color: '#8b5cf6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ma60Series = chart.addSeries(LineSeries, { color: '#ec4899', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    ma5SeriesRef.current = ma5Series;
    ma10SeriesRef.current = ma10Series;
    ma20SeriesRef.current = ma20Series;
    ma60SeriesRef.current = ma60Series;

    // Fit content on load
    chart.timeScale().fitContent();

    // Resize observer
    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [height]);

  // 按当前时间范围切片全量数据并 setData（不重新请求；切范围只刷视图）
  const renderSliced = useCallback(() => {
    const fd = fullDataRef.current;
    if (!fd || !candleSeriesRef.current) return;
    const tr = activeTimeRangeRef.current;
    const slice = <T extends { time: Time }>(arr: T[]): T[] => {
      if (tr === 'ALL') return arr;
      const days = TIME_RANGE_DAYS[tr];
      if (!days) return arr;
      const cutoff = Math.floor(Date.now() / 1000) - days * 86400;
      return arr.filter((d) => (d.time as number) >= cutoff);
    };
    candleSeriesRef.current.setData(slice(fd.candle));
    volumeSeriesRef.current?.setData(slice(fd.volume));
    ma5SeriesRef.current?.setData(slice(fd.ma5));
    ma10SeriesRef.current?.setData(slice(fd.ma10));
    ma20SeriesRef.current?.setData(slice(fd.ma20));
    ma60SeriesRef.current?.setData(slice(fd.ma60));
    chartRef.current?.timeScale().fitContent();
  }, []);

  const loadData = useCallback(async (sym: string, intv: string) => {
    if (!chartRef.current || !candleSeriesRef.current) return;

    // 缓存命中：直接复用已处理好的序列，跳过请求和 MA 重算
    const cacheKey = `${sym}:${intv}`;
    const hit = klineChartCache.get(cacheKey);
    if (hit && Date.now() - hit.ts < KLINE_CACHE_TTL_MS) {
      fullDataRef.current = {
        candle: hit.candle, volume: hit.volume,
        ma5: hit.ma5, ma10: hit.ma10, ma20: hit.ma20, ma60: hit.ma60,
      };
      lastBarRef.current = hit.lastBar;
      renderSliced();
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const url = `${API_BASE}/market/kline/${sym}?interval=${intv}&limit=3000`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const bars: KlineBar[] = json?.data?.bars || [];

      if (bars.length === 0) {
        setLoading(false);
        return;
      }

      // Sort ascending by date
      bars.sort((a, b) => a.trade_date.localeCompare(b.trade_date));

      const candleData: CandlestickData<Time>[] = bars.map((b) => ({
        time: parseDate(b.trade_date) as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }));

      const closes = bars.map((b) => b.close);
      const volumeData: HistogramData<Time>[] = bars.map((b) => ({
        time: parseDate(b.trade_date) as Time,
        value: b.volume,
        color: b.close >= b.open ? COLOR_VOLUME_UP : COLOR_VOLUME_DOWN,
      }));

      const ma5Data: LineData<Time>[] = bars.map((b, i) => ({
        time: parseDate(b.trade_date) as Time,
        value: calcSMA(closes, i, 5) ?? NaN,
      })).filter((d) => !isNaN(d.value));

      const ma10Data: LineData<Time>[] = bars.map((b, i) => ({
        time: parseDate(b.trade_date) as Time,
        value: calcSMA(closes, i, 10) ?? NaN,
      })).filter((d) => !isNaN(d.value));

      const ma20Data: LineData<Time>[] = bars.map((b, i) => ({
        time: parseDate(b.trade_date) as Time,
        value: calcSMA(closes, i, 20) ?? NaN,
      })).filter((d) => !isNaN(d.value));

      const ma60Data: LineData<Time>[] = bars.map((b, i) => ({
        time: parseDate(b.trade_date) as Time,
        value: calcSMA(closes, i, 60) ?? NaN,
      })).filter((d) => !isNaN(d.value));

      // 缓存全量数据（MA 已在全量上算好），按当前时间范围切片显示
      fullDataRef.current = {
        candle: candleData, volume: volumeData,
        ma5: ma5Data, ma10: ma10Data, ma20: ma20Data, ma60: ma60Data,
      };
      renderSliced();

      // Track last bar for real-time updates
      if (bars.length > 0) {
        lastBarRef.current = bars[bars.length - 1];
        // 写入会话缓存（key 在函数入口已计算）
        klineChartCache.set(cacheKey, {
          ts: Date.now(),
          candle: candleData, volume: volumeData,
          ma5: ma5Data, ma10: ma10Data, ma20: ma20Data, ma60: ma60Data,
          lastBar: bars[bars.length - 1],
        });
        // 限制缓存规模，超出时淘汰最早写入的条目
        if (klineChartCache.size > 50) {
          const oldest = klineChartCache.keys().next().value;
          if (oldest !== undefined) klineChartCache.delete(oldest);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [calcSMA, renderSliced]);

  // Initialize chart on mount
  useEffect(() => {
    const cleanup = initChart();
    return cleanup;
  }, [initChart]);

  // Reload data when symbol/interval changes
  useEffect(() => {
    if (chartRef.current) {
      loadData(symbol, activeInterval);
    }
  }, [symbol, activeInterval, loadData]);

  // Real-time WebSocket tick updates
  useMarketTick({
    symbol: symbol.toLowerCase(),
    enabled: !!symbol,
    onTick: (tick) => {
      if (!candleSeriesRef.current || !volumeSeriesRef.current || !lastBarRef.current) return;
      const tickDate = tick.trade_date.includes('T') ? tick.trade_date.split('T')[0] : tick.trade_date;
      const lastDate = lastBarRef.current.trade_date.includes('T')
        ? lastBarRef.current.trade_date.split('T')[0]
        : lastBarRef.current.trade_date;

      const tickTime = parseDate(tickDate) as Time;
      const lastTime = parseDate(lastDate) as Time;

      if (tickDate === lastDate) {
        // Update last candle
        candleSeriesRef.current.update({
          time: lastTime,
          open: lastBarRef.current.open,
          high: Math.max(lastBarRef.current.high, tick.high),
          low: Math.min(lastBarRef.current.low, tick.low),
          close: tick.close,
        });
        volumeSeriesRef.current.update({
          time: lastTime,
          value: tick.volume,
          color: tick.close >= lastBarRef.current.open
            ? COLOR_VOLUME_UP
            : COLOR_VOLUME_DOWN,
        });
        lastBarRef.current = { ...lastBarRef.current, high: Math.max(lastBarRef.current.high, tick.high), low: Math.min(lastBarRef.current.low, tick.low), close: tick.close, volume: tick.volume };
      } else if (tickDate > lastDate) {
        // Add new candle
        candleSeriesRef.current.update({
          time: lastTime,
          open: lastBarRef.current.open,
          high: lastBarRef.current.high,
          low: lastBarRef.current.low,
          close: lastBarRef.current.close,
        });
        candleSeriesRef.current.update({
          time: tickTime,
          open: tick.open,
          high: tick.high,
          low: tick.low,
          close: tick.close,
        });
        volumeSeriesRef.current.update({
          time: lastTime,
          value: lastBarRef.current.volume,
          color: lastBarRef.current.close >= lastBarRef.current.open
            ? COLOR_VOLUME_UP
            : COLOR_VOLUME_DOWN,
        });
        volumeSeriesRef.current.update({
          time: tickTime,
          value: tick.volume,
          color: tick.close >= tick.open ? COLOR_VOLUME_UP : COLOR_VOLUME_DOWN,
        });
        lastBarRef.current = tick;
      }
    },
  });

  const handleIntervalChange = (intv: string) => {
    setActiveInterval(intv);
    onIntervalChange?.(intv);
  };

  const handleTimeRangeChange = (r: string) => {
    setActiveTimeRange(r);
    activeTimeRangeRef.current = r; // 立即生效，不必等 effect
    onTimeRangeChange?.(r);
    renderSliced(); // 只切片重绘，不重新请求
  };

  return (
    <Card className="kline-chart-card">
      <CardContent className="kline-chart-card__content">
        {/* Header */}
        <div className="kline-chart__header">
          <span className="kline-chart__symbol">{symbol.toUpperCase()}</span>
          <div className="kline-chart__controls">
            <div className="kline-chart__intervals">
              {INTERVALS.map((iv) => (
                <button
                  key={iv.value}
                  type="button"
                  className={`kline-chart__interval-btn ${activeInterval === iv.value ? 'kline-chart__interval-btn--active' : ''}`}
                  onClick={() => handleIntervalChange(iv.value)}
                >
                  {iv.label}
                </button>
              ))}
            </div>
            <div className="kline-chart__time-ranges">
              {TIME_RANGES.map((tr) => (
                <button
                  key={tr.value}
                  type="button"
                  className={`kline-chart__interval-btn ${activeTimeRange === tr.value ? 'kline-chart__interval-btn--active' : ''}`}
                  onClick={() => handleTimeRangeChange(tr.value)}
                >
                  {tr.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Chart container */}
        <div className="kline-chart__wrapper">
          {loading && (
            <div className="kline-chart__loading">
              <span className="kline-chart__spinner" />
              加载K线数据...
            </div>
          )}
          {error && (
            <div className="kline-chart__error">
              <span>⚠️ {error}</span>
              <button type="button" onClick={() => loadData(symbol, activeInterval)}>
                重试
              </button>
            </div>
          )}
          <div ref={containerRef} className="kline-chart__container" style={{ height }} />

          {/* Legend */}
          <div className="kline-chart__legend">
            <span className="kline-chart__legend-item" style={{ color: '#f59e0b' }}>MA5</span>
            <span className="kline-chart__legend-item" style={{ color: COLOR_ACCENT }}>MA10</span>
            <span className="kline-chart__legend-item" style={{ color: '#8b5cf6' }}>MA20</span>
            <span className="kline-chart__legend-item" style={{ color: '#ec4899' }}>MA60</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
