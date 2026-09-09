/**
 * K线卡片 — lightweight-charts 蜡烛图 + 成交量叠底 + MA5/10/20/60;
 * 可选技术指标:BOLL 叠主图,MACD/RSI 独立副图(多窗格,共享时间轴)。
 * 数据由全局时间范围驱动;EMA 类指标左侧需预热,fetch start 前扩 200 自然日,
 * 展示切片回 range.start;开关/参数变化用缓存 bars 重算,不重新请求。
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
  CandlestickData,
  CandlestickSeries,
  HistogramData,
  HistogramSeries,
  IChartApi,
  ISeriesApi,
  LineData,
  LineSeries,
  LineStyle,
  Time,
  createChart,
} from 'lightweight-charts';
import {StateView} from '../../../components/ui';
import {getApiBase} from '../../../lib/api';
import {DateRange, KlineIndicatorConfig} from '../boardTypes';
import {boll, macd, rsiWilder} from '../indicators';
import {colorDown, colorUp} from '../../../lib/chartTheme';

const API_BASE = getApiBase();
const COLOR_VOLUME_UP = 'rgba(255, 69, 58, 0.4)';
const COLOR_VOLUME_DOWN = 'rgba(48, 209, 88, 0.4)';
const MA_COLORS = ['#f59e0b', '#0a84ff', '#8b5cf6', '#ec4899'];
const BOLL_COLOR = '#22d3ee';
const MACD_DIF_COLOR = '#f59e0b';
const MACD_DEA_COLOR = '#0a84ff';
const RSI_COLOR = '#ec4899';
const REF_LINE_COLOR = 'rgba(161, 161, 166, 0.4)';
/** EMA 类指标预热:覆盖默认参数及 slow≤60 的收敛 */
const WARMUP_CALENDAR_DAYS = 200;

interface KlineBar {
  trade_date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
}

function parseDate(dateStr: string): number {
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00');
  return Math.floor(d.getTime() / 1000);
}

function sma(closes: number[], index: number, period: number): number | null {
  if (index < period - 1) return null;
  let sum = 0;
  for (let i = index - period + 1; i <= index; i++) sum += closes[i];
  return sum / period;
}

/** range.start 前扩 N 自然日(YYYY-MM-DD),供指标预热 */
function warmupStart(start: string | null): string | null {
  if (!start) return null;
  const d = new Date(start + 'T00:00:00');
  d.setDate(d.getDate() - WARMUP_CALENDAR_DAYS);
  const p = (x: number) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export interface KlineCardProps {
  symbol: string;
  range: DateRange;
  refreshKey: number;
  config: KlineIndicatorConfig;
}

export const KlineCard: React.FC<KlineCardProps> = ({symbol, range, refreshKey, config}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const maRefs = useRef<Array<ISeriesApi<'Line'> | null>>([]);
  const bollRefs = useRef<Array<ISeriesApi<'Line'> | null>>([]);
  const macdHistRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const macdDifRef = useRef<ISeriesApi<'Line'> | null>(null);
  const macdDeaRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsiRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsiPaneRef = useRef<number | null>(null);
  const barsRef = useRef<KlineBar[]>([]);
  const [state, setState] = useState<{loading: boolean; error: string | null; empty: boolean}>(
    {loading: true, error: null, empty: false},
  );
  const reqIdRef = useRef(0);
  // applySeries 依赖最新 config/load,用 ref 镜像避免 effect 闭包陈值
  const configRef = useRef(config);
  configRef.current = config;
  const rangeRef = useRef(range);
  rangeRef.current = range;

  // 建图(一次) + 尺寸随卡片缩放
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      layout: {background: {color: 'transparent'}, textColor: '#a1a1a6', fontSize: 11},
      grid: {
        vertLines: {color: 'rgba(161, 161, 166, 0.15)'},
        horzLines: {color: 'rgba(161, 161, 166, 0.15)'},
      },
      crosshair: {
        mode: 1,
        vertLine: {color: 'rgba(161, 161, 166, 0.4)', width: 1, style: 2},
        horzLine: {color: 'rgba(161, 161, 166, 0.4)', width: 1, style: 2},
      },
      rightPriceScale: {
        borderColor: 'rgba(161, 161, 166, 0.2)',
        scaleMargins: {top: 0.08, bottom: 0.28},
      },
      timeScale: {
        borderColor: 'rgba(161, 161, 166, 0.2)',
        timeVisible: true,
        secondsVisible: false,
      },
      width: el.clientWidth,
      height: el.clientHeight,
    });
    chartRef.current = chart;
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: colorUp,
      downColor: colorDown,
      borderUpColor: colorUp,
      borderDownColor: colorDown,
      wickUpColor: colorUp,
      wickDownColor: colorDown,
    });
    volumeRef.current = chart.addSeries(HistogramSeries, {
      color: '#6366f1',
      priceFormat: {type: 'volume'},
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({scaleMargins: {top: 0.8, bottom: 0}});
    maRefs.current = MA_COLORS.map((c) =>
      chart.addSeries(LineSeries, {
        color: c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      }),
    );
    const ro = new ResizeObserver(() => {
      chart.applyOptions({width: el.clientWidth, height: el.clientHeight});
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      maRefs.current = [];
      bollRefs.current = [];
      macdHistRef.current = null;
      macdDifRef.current = null;
      macdDeaRef.current = null;
      rsiRef.current = null;
      rsiPaneRef.current = null;
    };
  }, []);

  /** 序列随 config 增删(BOLL 主图;MACD pane1;RSI pane=macd?2:1,窗格变了重建) */
  const ensureSeries = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const ind = configRef.current.indicators;

    if (ind.boll && bollRefs.current.length === 0) {
      bollRefs.current = [0, 1, 2].map(() =>
        chart.addSeries(LineSeries, {
          color: BOLL_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        }),
      );
    } else if (!ind.boll && bollRefs.current.length > 0) {
      bollRefs.current.forEach((s) => { if (s) chart.removeSeries(s); });
      bollRefs.current = [];
    }

    if (ind.macd && !macdDifRef.current) {
      macdHistRef.current = chart.addSeries(HistogramSeries, {}, 1);
      macdDifRef.current = chart.addSeries(LineSeries, {
        color: MACD_DIF_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      }, 1);
      macdDifRef.current.createPriceLine({
        price: 0, color: REF_LINE_COLOR, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: false, title: '',
      });
      macdDeaRef.current = chart.addSeries(LineSeries, {
        color: MACD_DEA_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      }, 1);
    } else if (!ind.macd && macdDifRef.current) {
      if (macdHistRef.current) chart.removeSeries(macdHistRef.current);
      if (macdDifRef.current) chart.removeSeries(macdDifRef.current);
      if (macdDeaRef.current) chart.removeSeries(macdDeaRef.current);
      macdHistRef.current = null;
      macdDifRef.current = null;
      macdDeaRef.current = null;
    }

    const wantRsiPane = ind.macd ? 2 : 1;
    if (ind.rsi && (!rsiRef.current || rsiPaneRef.current !== wantRsiPane)) {
      if (rsiRef.current) chart.removeSeries(rsiRef.current);
      rsiRef.current = chart.addSeries(LineSeries, {
        color: RSI_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      }, wantRsiPane);
      rsiRef.current.createPriceLine({
        price: 30, color: REF_LINE_COLOR, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: false, title: '',
      });
      rsiRef.current.createPriceLine({
        price: 70, color: REF_LINE_COLOR, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: false, title: '',
      });
      rsiPaneRef.current = wantRsiPane;
    } else if (!ind.rsi && rsiRef.current) {
      if (rsiRef.current) chart.removeSeries(rsiRef.current);
      rsiRef.current = null;
      rsiPaneRef.current = null;
    }

    // 窗格高度比:主图 3 : 副图 1
    chart.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 3 : 1));
  }, []);

  /** 缓存 bars + 当前 config → 纯渲染(不请求) */
  const applySeries = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    ensureSeries();
    const cfg = configRef.current;
    const bars = barsRef.current;
    const start = rangeRef.current.start;
    // 展示窗:预热数据只参与计算,不进图
    const dispIdx: number[] = [];
    bars.forEach((b, i) => {
      if (!start || b.trade_date >= start) dispIdx.push(i);
    });
    if (dispIdx.length === 0) {
      candleRef.current?.setData([]);
      volumeRef.current?.setData([]);
      maRefs.current.forEach((m) => m?.setData([]));
      bollRefs.current.forEach((s) => s?.setData([]));
      macdHistRef.current?.setData([]);
      macdDifRef.current?.setData([]);
      macdDeaRef.current?.setData([]);
      rsiRef.current?.setData([]);
      setState((s) => (s.loading ? s : {loading: false, error: null, empty: true}));
      return;
    }
    const closes = bars.map((b) => b.close);
    const t = (i: number) => parseDate(bars[i].trade_date) as Time;
    candleRef.current?.setData(
      dispIdx.map((i) => ({
        time: t(i),
        open: bars[i].open, high: bars[i].high, low: bars[i].low, close: bars[i].close,
      })),
    );
    volumeRef.current?.setData(
      dispIdx.map((i) => ({
        time: t(i),
        value: bars[i].volume,
        color: bars[i].close >= bars[i].open ? COLOR_VOLUME_UP : COLOR_VOLUME_DOWN,
      })),
    );
    [5, 10, 20, 60].forEach((period, pi) => {
      const line: LineData<Time>[] = [];
      dispIdx.forEach((i) => {
        const v = sma(closes, i, period);
        if (v != null) line.push({time: t(i), value: v});
      });
      maRefs.current[pi]?.setData(line);
    });
    const lineOf = (series: ISeriesApi<'Line'> | null, values: (number | null)[]) => {
      if (!series) return;
      const line: LineData<Time>[] = [];
      dispIdx.forEach((i) => {
        const v = values[i];
        if (v != null) line.push({time: t(i), value: v});
      });
      series.setData(line);
    };
    if (cfg.indicators.boll) {
      const bb = boll(closes, cfg.params.boll.period, cfg.params.boll.stdDev);
      lineOf(bollRefs.current[0], bb.upper);
      lineOf(bollRefs.current[1], bb.mid);
      lineOf(bollRefs.current[2], bb.lower);
    }
    if (cfg.indicators.macd) {
      const m = macd(closes, cfg.params.macd.fast, cfg.params.macd.slow, cfg.params.macd.signal);
      if (macdHistRef.current) {
        const hist: HistogramData<Time>[] = [];
        dispIdx.forEach((i) => {
          const v = m.hist[i];
          if (v != null) hist.push({
            time: t(i), value: v,
            color: v >= 0 ? 'rgba(255, 69, 58, 0.55)' : 'rgba(48, 209, 88, 0.55)',
          });
        });
        macdHistRef.current.setData(hist);
      }
      lineOf(macdDifRef.current, m.dif);
      lineOf(macdDeaRef.current, m.dea);
    }
    if (cfg.indicators.rsi) {
      lineOf(rsiRef.current, rsiWilder(closes, cfg.params.rsi.period));
    }
    chart.timeScale().fitContent();
    setState({loading: false, error: null, empty: false});
  }, [ensureSeries]);

  const load = useCallback(async () => {
    const reqId = ++reqIdRef.current;
    const qs = new URLSearchParams({interval: '1d', limit: '3000'});
    const fetchStart = warmupStart(range.start);
    if (fetchStart) qs.set('start', fetchStart);
    if (range.end) qs.set('end', range.end);
    setState({loading: true, error: null, empty: false});
    try {
      const res = await fetch(`${API_BASE}/market/kline/${symbol}?${qs}`);
      if (reqId !== reqIdRef.current) return;
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (reqId !== reqIdRef.current) return;
      const bars: KlineBar[] = json?.data?.bars || [];
      bars.sort((a, b) => a.trade_date.localeCompare(b.trade_date));
      barsRef.current = bars;
      applySeries();
    } catch (e) {
      setState({loading: false, error: String(e), empty: false});
    }
  }, [symbol, range.start, range.end, applySeries]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // 开关/参数变化:只重算不重拉
  useEffect(() => {
    applySeries();
  }, [config, applySeries]);

  const legendExtras = [
    ...(config.indicators.boll ? [{label: 'BOLL', color: BOLL_COLOR}] : []),
    ...(config.indicators.macd ? [
      {label: 'DIF', color: MACD_DIF_COLOR},
      {label: 'DEA', color: MACD_DEA_COLOR},
    ] : []),
    ...(config.indicators.rsi ? [{label: `RSI(${config.params.rsi.period})`, color: RSI_COLOR}] : []),
  ];

  return (
    <div className="board-chart">
      {(state.loading || state.error || state.empty) && (
        <div className="board-chart__state">
          <StateView
            state={state.loading ? 'loading' : state.error ? 'error' : 'empty'}
            text={state.error ? state.error : state.empty ? '该区间无K线数据' : undefined}
            onRetry={state.error ? () => void load() : undefined}
          />
        </div>
      )}
      <div ref={containerRef} className="board-chart__canvas" />
      <div className="board-chart__legend">
        {['MA5', 'MA10', 'MA20', 'MA60'].map((l, i) => (
          <span key={l} style={{color: MA_COLORS[i]}}>{l}</span>
        ))}
        {legendExtras.map((x) => (
          <span key={x.label} style={{color: x.color}}>{x.label}</span>
        ))}
      </div>
    </div>
  );
};
