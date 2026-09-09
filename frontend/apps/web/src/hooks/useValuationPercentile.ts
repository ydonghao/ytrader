/**
 * 个股/指数估值历史分位数据 hook。
 *
 * 调用 GET /financial/valuation-percentile/{symbol}，
 * 支持 windows / as_of / metrics 参数。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface PercentileWindowStats {
  current: number | null;
  percentile: number | null;
  sample_size: number;
  min: number;
  max: number;
  p25: number;
  p50: number;
  p75: number;
}

export interface PercentileMetric {
  current: number | null;
  windows: Record<string, PercentileWindowStats | null>;
  series: Array<{ date: string; value: number }>;
}

export interface ValuationPercentileData {
  symbol: string;
  as_of: string | null;
  metrics: Record<string, PercentileMetric | null>;
}

export interface UseValuationPercentileParams {
  windows?: string; // "3y,5y,10y,15y,20y,all"
  asOf?: string; // "YYYY-MM-DD"
  metrics?: string; // "pe_ttm,pb,ps_ttm,dv_ttm"
  exclude?: string; // "2020-06-01~2021-02-28,..." 剔除区间
  enabled?: boolean; // false 时不请求（Tab 未激活时省掉重型分位计算）
}

export function useValuationPercentile(
  symbol: string | null,
  params: UseValuationPercentileParams = {},
) {
  const { windows, asOf, metrics, exclude, enabled = true } = params;
  const [data, setData] = useState<ValuationPercentileData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol || !enabled) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    const qs = new URLSearchParams();
    if (windows) qs.set('windows', windows);
    if (asOf) qs.set('as_of', asOf);
    if (metrics) qs.set('metrics', metrics);
    if (exclude) qs.set('exclude', exclude);

    const url = `${API_BASE}/financial/valuation-percentile/${symbol}${qs.toString() ? '?' + qs.toString() : ''}`;
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
  }, [symbol, windows, asOf, metrics, exclude, enabled]);

  return { data, loading, error };
}
