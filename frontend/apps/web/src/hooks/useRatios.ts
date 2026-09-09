/**
 * 比率分析（ratio analysis）数据 hook。
 *
 * 调用 GET /financial/ratio-analysis/{symbol}，
 * 14 个核心财务比率（盈利/偿债/营运/成长）多期时序。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export type RatioUnit = 'pct' | 'x' | 'growth' | 'day' | 'yi';

export interface RatioMeta {
  key: string;
  label: string;
  unit: RatioUnit;
  formula: string;
}

export interface RatioGroup {
  key: string;
  label: string;
  ratios: RatioMeta[];
}

export interface RatioPeriod {
  report_date: string;
  values: Record<string, number | null>;
  ratios: Record<string, number | null>;
}

export interface RatiosData {
  symbol: string;
  total_periods: number;
  groups: RatioGroup[];
  periods: RatioPeriod[];
  note?: string;
}

export type RatioPeriodMode = 'month' | 'year';

export function useRatios(
  symbol: string | null,
  periodMode: RatioPeriodMode,
  limit = 12,
) {
  const [data, setData] = useState<RatiosData | null>(null);
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
    const qs = new URLSearchParams({
      period: periodMode,
      limit: String(limit),
    });
    fetch(`${API_BASE}/financial/ratio-analysis/${symbol}?${qs.toString()}`)
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
  }, [symbol, periodMode, limit]);

  return { data, loading, error };
}
