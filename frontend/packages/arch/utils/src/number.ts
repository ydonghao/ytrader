/**
 * Number utilities
 */

/**
 * Clamp a value between min and max
 */
export const clamp = (value: number, min: number, max: number): number => {
  return Math.min(Math.max(value, min), max);
};

/**
 * Round to specified decimal places
 */
export const round = (value: number, decimals: number = 2): number => {
  const factor = Math.pow(10, decimals);
  return Math.round(value * factor) / factor;
};

/**
 * Calculate percentage
 */
export const percent = (value: number, total: number): number => {
  if (total === 0) return 0;
  return (value / total) * 100;
};

/**
 * Calculate percentage change
 */
export const percentChange = (current: number, previous: number): number => {
  if (previous === 0) return 0;
  return ((current - previous) / previous) * 100;
};

/**
 * Calculate win rate
 */
export const winRate = (wins: number, total: number): number => {
  if (total === 0) return 0;
  return round((wins / total) * 100, 2);
};

/**
 * Calculate Sharpe Ratio
 */
export const sharpeRatio = (
  returns: number[],
  riskFreeRate: number = 0
): number => {
  if (returns.length === 0) return 0;

  const avgReturn = returns.reduce((a, b) => a + b, 0) / returns.length;
  const excessReturn = avgReturn - riskFreeRate;

  const squaredDiffs = returns.map(r => Math.pow(r - avgReturn, 2));
  const variance = squaredDiffs.reduce((a, b) => a + b, 0) / returns.length;
  const stdDev = Math.sqrt(variance);

  if (stdDev === 0) return 0;
  return round(excessReturn / stdDev, 2);
};

/**
 * Calculate Maximum Drawdown
 */
export const maxDrawdown = (values: number[]): number => {
  if (values.length === 0) return 0;

  let maxDD = 0;
  let peak = values[0];

  for (const value of values) {
    if (value > peak) {
      peak = value;
    }
    const dd = ((peak - value) / peak) * 100;
    if (dd > maxDD) {
      maxDD = dd;
    }
  }

  return round(maxDD, 2);
};

/**
 * Calculate Total Return
 */
export const totalReturn = (initial: number, current: number): number => {
  if (initial === 0) return 0;
  return round(((current - initial) / initial) * 100, 2);
};

/**
 * Linear interpolation
 */
export const lerp = (start: number, end: number, t: number): number => {
  return start + (end - start) * clamp(t, 0, 1);
};

/**
 * Calculate position size based on risk
 */
export const calculatePositionSize = (
  capital: number,
  riskPercent: number,
  entryPrice: number,
  stopLossPrice: number
): number => {
  if (entryPrice === 0 || entryPrice === stopLossPrice) return 0;
  const riskAmount = capital * (riskPercent / 100);
  const riskPerUnit = Math.abs(entryPrice - stopLossPrice);
  return round(riskAmount / riskPerUnit, 4);
};

/**
 * Calculate liquidation price for long position
 */
export const liquidationPriceLong = (
  entryPrice: number,
  leverage: number,
  maintenanceMargin: number = 0.5
): number => {
  return round(entryPrice * (1 - (1 / leverage) * (1 - maintenanceMargin)), 4);
};

/**
 * Calculate liquidation price for short position
 */
export const liquidationPriceShort = (
  entryPrice: number,
  leverage: number,
  maintenanceMargin: number = 0.5
): number => {
  return round(entryPrice * (1 + (1 / leverage) * (1 - maintenanceMargin)), 4);
};
