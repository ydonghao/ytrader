/**
 * 同型分析（common-size）数据 hook。
 *
 * 调用 GET /financial/common-size/{symbol}，
 * 三大报表全科目 ÷ 基准值 → 结构百分比时序。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface CommonSizeItem {
  name: string;
  level: number;
  raw: number | null;
  pct: number | null;
}

export interface CommonSizePeriod {
  report_date: string;
  base_value: number;
  items: CommonSizeItem[];
}

export interface CommonSizeData {
  symbol: string;
  statement_type: string;
  base_name: string | null;
  total_periods: number;
  periods: CommonSizePeriod[];
  note?: string;
}

export type CommonSizeStatement = 'income' | 'balance' | 'cashflow';
export type CommonSizePeriodMode = 'month' | 'year';

export function useCommonSize(
  symbol: string | null,
  statementType: CommonSizeStatement,
  periodMode: CommonSizePeriodMode,
  limit = 12,
) {
  const [data, setData] = useState<CommonSizeData | null>(null);
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
      statement_type: statementType,
      period: periodMode,
      limit: String(limit),
    });
    fetch(`${API_BASE}/financial/common-size/${symbol}?${qs.toString()}`)
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
  }, [symbol, statementType, periodMode, limit]);

  return { data, loading, error };
}
