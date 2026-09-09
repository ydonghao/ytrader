/**
 * 看板技术指标纯函数 — 算法与后端 strategy/indicators.py 逐条对齐:
 * EMA 用 SMA 种子;MACD 的 DEA 对 DIF 序列 None→0 填充后做 EMA;
 * RSI 用 Wilder 平滑;BOLL 用样本标准差(n-1 分母)。
 * 输入序列按时间升序;输出与输入等长,不足周期位为 null。
 */
export type Series = (number | null)[];

export function ema(values: number[], period: number): Series {
  const n = values.length;
  const result: Series = new Array(n).fill(null);
  if (period < 1 || n < period) return result;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  result[period - 1] = sum / period;
  const k = 2 / (period + 1);
  for (let i = period; i < n; i++) {
    result[i] = (values[i] - (result[i - 1] as number)) * k + (result[i - 1] as number);
  }
  return result;
}

export interface MacdResult { dif: Series; dea: Series; hist: Series }

export function macd(values: number[], fast: number, slow: number, signal: number): MacdResult {
  const n = values.length;
  const fastE = ema(values, fast);
  const slowE = ema(values, slow);
  const dif: Series = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (fastE[i] != null && slowE[i] != null) dif[i] = (fastE[i] as number) - (slowE[i] as number);
  }
  // 对齐后端:DEA = EMA(DIF 的 None→0 填充序列, signal)
  const dea = ema(dif.map((x) => x ?? 0), signal);
  const hist: Series = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (dif[i] != null && dea[i] != null) hist[i] = (dif[i] as number) - (dea[i] as number);
  }
  return {dif, dea, hist};
}

export function rsiWilder(values: number[], period: number): Series {
  const n = values.length;
  const result: Series = new Array(n).fill(null);
  if (period < 2 || n < period + 1) return result;
  const gains: number[] = [];
  const losses: number[] = [];
  for (let i = 1; i < n; i++) {
    const diff = values[i] - values[i - 1];
    gains.push(Math.max(diff, 0));
    losses.push(Math.max(-diff, 0));
  }
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 0; i < period; i++) { avgGain += gains[i]; avgLoss += losses[i]; }
  avgGain /= period;
  avgLoss /= period;
  const rsiOf = (g: number, l: number) => (l === 0 ? 100 : 100 - 100 / (1 + g / l));
  result[period] = rsiOf(avgGain, avgLoss);
  for (let i = period; i < gains.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
    result[i + 1] = rsiOf(avgGain, avgLoss);
  }
  return result;
}

export interface BollResult { upper: Series; mid: Series; lower: Series }

export function boll(values: number[], period: number, stdDev: number): BollResult {
  const n = values.length;
  const mid: Series = new Array(n).fill(null);
  const upper: Series = new Array(n).fill(null);
  const lower: Series = new Array(n).fill(null);
  if (period < 2 || n < period) return {upper, mid, lower};
  for (let i = period - 1; i < n; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    const m = sum / period;
    let sq = 0;
    for (let j = i - period + 1; j <= i; j++) sq += (values[j] - m) ** 2;
    // 样本标准差(n-1 分母),对齐后端 statistics.stdev
    const sd = Math.sqrt(sq / (period - 1));
    mid[i] = m;
    upper[i] = m + stdDev * sd;
    lower[i] = m - stdDev * sd;
  }
  return {upper, mid, lower};
}
