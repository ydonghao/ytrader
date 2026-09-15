import React, {useEffect, useRef} from 'react';
import {
  CandlestickSeries, HistogramSeries, LineSeries, createChart,
  createSeriesMarkers,
  type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi,
  type SeriesMarker, type Time, type UTCTimestamp,
} from 'lightweight-charts';
import {
  chartBorder, chartTextSecondary, colorDown, colorUp,
} from '../../lib/chartTheme';
import {sma} from './engine/indicators';
import type {ReplayBar, Trade} from './types';

const toTime = (d: string): UTCTimestamp =>
  Math.floor(new Date(`${d}T00:00:00Z`).getTime() / 1000) as UTCTimestamp;

const MA_COLORS = ['#f5c542', '#64d2ff', '#bf5af2', '#a1a1a6'];
const MA_NS = [5, 10, 20, 60];

export interface ReplayKlineChartProps {
  bars: ReplayBar[];
  trades?: Trade[]; // 复盘模式标注买卖点
  height?: number;
}

export const ReplayKlineChart: React.FC<ReplayKlineChartProps> = ({
  bars, trades = [], height = 420,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const maRefs = useRef<ISeriesApi<'Line'>[]>([]);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lenRef = useRef(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      height,
      layout: {
        background: {color: 'transparent'},
        textColor: chartTextSecondary,
      },
      grid: {
        vertLines: {color: chartBorder},
        horzLines: {color: chartBorder},
      },
      rightPriceScale: {borderColor: chartBorder},
      timeScale: {borderColor: chartBorder},
    });
    chartRef.current = chart;
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: colorUp, downColor: colorDown, borderVisible: false,
      wickUpColor: colorUp, wickDownColor: colorDown,
    });
    candleRef.current = candle;
    volRef.current = chart.addSeries(HistogramSeries, {
      priceFormat: {type: 'volume'}, priceScaleId: '',
    });
    chart.priceScale('').applyOptions({scaleMargins: {top: 0.8, bottom: 0}});
    maRefs.current = MA_COLORS.map((color) =>
      chart.addSeries(LineSeries, {
        color, lineWidth: 1, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false,
      }));
    markersRef.current = createSeriesMarkers(candle, []);
    const ro = new ResizeObserver(() => {
      chart.applyOptions({width: el.clientWidth});
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volRef.current = null;
      maRefs.current = [];
      markersRef.current = null;
      lenRef.current = 0;
    };
  }, [height]);

  useEffect(() => {
    const candle = candleRef.current;
    if (!candle) return;
    const cd = bars.map((b) => ({
      time: toTime(b.trade_date),
      open: b.open, high: b.high, low: b.low, close: b.close,
    }));
    const vd = bars.map((b) => ({
      time: toTime(b.trade_date), value: b.volume,
      color: b.close >= b.open ? colorUp : colorDown,
    }));
    const closes = bars.map((b) => b.close);
    const mas = MA_NS.map((n) => sma(closes, n));
    if (bars.length === lenRef.current + 1 && lenRef.current > 0) {
      // 增量：推进一根
      const i = bars.length - 1;
      const c = cd[i];
      if (c) {
        candle.update(c);
        const v = vd[i];
        if (v) volRef.current?.update(v);
        maRefs.current.forEach((s, k) => {
          const mv = mas[k]?.[i];
          if (mv != null) s.update({time: c.time, value: mv});
        });
      }
    } else {
      candle.setData(cd);
      volRef.current?.setData(vd);
      maRefs.current.forEach((s, k) => {
        s.setData(
          cd.flatMap((c, i) => {
            const v = mas[k]?.[i];
            return v == null ? [] : [{time: c.time, value: v}];
          }),
        );
      });
    }
    lenRef.current = bars.length;
    // height 变化时图表重建（lenRef 归零），需整包重喂
  }, [bars, height]);

  useEffect(() => {
    const markers: SeriesMarker<Time>[] = trades.map((t) => ({
      time: toTime(t.trade_date),
      position: t.side === 'buy' ? 'belowBar' : 'aboveBar',
      color: t.side === 'buy' ? colorUp : colorDown,
      shape: t.side === 'buy' ? 'arrowUp' : 'arrowDown',
      text: t.side === 'buy' ? 'B' : 'S',
    }));
    markersRef.current?.setMarkers(markers);
    // height 变化时 markers 插件随图表重建，需重设
  }, [trades, height]);

  return <div ref={ref} style={{height}} />;
};
