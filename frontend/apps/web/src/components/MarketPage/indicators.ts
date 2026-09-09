/**
 * Technical Indicators Calculation
 */

import type { KlineBar, ProcessedBar } from './types';

/**
 * Calculate Simple Moving Average for the last N bars
 */
function calcSMA(closes: number[], index: number, period: number): number | null {
  if (index < period - 1) return null;
  let sum = 0;
  for (let i = index - period + 1; i <= index; i++) {
    sum += closes[i];
  }
  return sum / period;
}

/**
 * Calculate RSI(14)
 * RSI = 100 - 100/(1 + avg_gain/avg_loss)
 */
function calcRSI(closes: number[], index: number, period: number = 14): number | null {
  if (index < period) return null;

  let avgGain = 0;
  let avgLoss = 0;

  // First average: simple mean of first period gains/losses
  for (let i = index - period + 1; i <= index; i++) {
    const change = closes[i] - closes[i - 1];
    if (change > 0) avgGain += change;
    else avgLoss += Math.abs(change);
  }
  avgGain /= period;
  avgLoss /= period;

  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

/**
 * Process raw Kline bars into enriched data with indicators
 */
export function processKlineBars(bars: KlineBar[]): ProcessedBar[] {
  if (!bars || bars.length === 0) return [];

  const closes = bars.map((b) => b.close);

  return bars.map((bar, i) => {
    // Convert UTC trade_date to local Date
    const localTime = new Date(bar.trade_date);

    return {
      ...bar,
      localTime,
      isUp: bar.close >= bar.open,
      ma5: calcSMA(closes, i, 5),
      ma10: calcSMA(closes, i, 10),
      ma20: calcSMA(closes, i, 20),
      ma60: calcSMA(closes, i, 60),
      rsi: calcRSI(closes, i, 14),
    };
  });
}

/**
 * Filter bars by time range (most recent N bars)
 */
export function filterByTimeRange(bars: ProcessedBar[], limit: number): ProcessedBar[] {
  if (bars.length <= limit) return bars;
  return bars.slice(bars.length - limit);
}
