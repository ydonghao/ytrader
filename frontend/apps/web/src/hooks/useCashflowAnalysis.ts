/**
 * 现金流分析（cashflow analysis）数据 hook。
 *
 * 调用 GET /financial/cashflow-analysis/{symbol}，
 * 11 个现金流指标（盈利质量/增长趋势/现金流结构）多期时序。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export type CashflowUnit = 'pct' | 'x' | 'growth' | 'yi';

export interface CashflowMeta {
  key: string;
  label: string;
  unit: CashflowUnit;
  formula: string;
}

export interface CashflowGroup {
  key: string;
  label: string;
  ratios: CashflowMeta[];
}

export interface CashflowPeriod {
  report_date: string;
  values: Record<string, number | null>;
  ratios: Record<string, number | null>;
}

export interface CashflowData {
  symbol: string;
  total_periods: number;
  groups: CashflowGroup[];
  periods: CashflowPeriod[];
  note?: string;
}

export type CashflowPeriodMode = 'month' | 'year';

export function useCashflowAnalysis(
  symbol: string | null,
  periodMode: CashflowPeriodMode,
  limit = 12,
) {
  const [data, setData] = useState<CashflowData | null>(null);
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
    fetch(
      `${API_BASE}/financial/cashflow-analysis/${symbol}?${qs.toString()}`,
    )
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
