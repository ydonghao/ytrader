/**
 * DCF 内在价值与安全边际 hook。
 *
 * 调用 GET /financial/dcf/{symbol}（假设可调：增长率/折现率/永续/年数）。
 * 价值投资绝对估值锚：内在价值 vs 当前市值 → 安全边际。
 */
import {useEffect, useState} from 'react';
import {getApiBase} from '../lib/api';

const API_BASE = getApiBase();

export interface DcfAssumptions {
  growth_rate: number;
  terminal_growth: number;
  wacc: number;
  projection_years: number;
}

export interface MonteCarloBin {
  bin_start: number;
  bin_end: number;
  count: number;
}

export interface MonteCarloData {
  mean: number;
  std: number;
  cv: number | null;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
  min: number;
  max: number;
  sample_size: number;
  histogram: MonteCarloBin[];
}

export interface DcfData {
  symbol: string;
  fcf_base: number | null;
  report_date: string | null;
  fcf_method?: string | null; // ttm / annual / annual_fallback
  market_value: number | null;
  valuation_date: string | null;
  intrinsic_value: number | null;
  margin_of_safety: number | null;
  assumptions: DcfAssumptions;
  monte_carlo?: MonteCarloData | null;
  note?: string;
  error?: string;
}

export interface UseDcfParams {
  growthRate?: number;
  terminalGrowth?: number;
  wacc?: number;
  projectionYears?: number;
}

export function useDcf(symbol: string | null, params: UseDcfParams = {}) {
  const {growthRate, terminalGrowth, wacc, projectionYears} = params;
  const [data, setData] = useState<DcfData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    const qs = new URLSearchParams();
    if (growthRate != null) qs.set('growth_rate', String(growthRate));
    if (terminalGrowth != null) qs.set('terminal_growth', String(terminalGrowth));
    if (wacc != null) qs.set('wacc', String(wacc));
    if (projectionYears != null) qs.set('projection_years', String(projectionYears));

    const url = `${API_BASE}/financial/dcf/${symbol}${qs.toString() ? '?' + qs.toString() : ''}`;
    fetch(url)
      .then((r) => r.json())
      .then((json) => {
        if (cancelled) return;
        if (json.code === 0) {
          setData(json.data);
        } else {
          setError(json.msg || '请求失败');
          setData(null);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, growthRate, terminalGrowth, wacc, projectionYears]);

  return {data, loading, error};
}
