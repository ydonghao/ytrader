/**
 * 市值与业绩增长趋势数据 hook（指数/个股共用）。
 * 调 GET /financial/market-cap-growth/{kind}/{code}，
 * 三口径（单季/累计/TTM）一次返回，前端切换零请求。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface McgBarPoint {
  report_date: string;
  revenue: number | null;
  net_profit: number | null;
}

export interface McgData {
  kind: 'index' | 'stock';
  code: string;
  name: string | null;
  as_of: string | null;
  bars: {
    quarter: McgBarPoint[];
    cumulative: McgBarPoint[];
    ttm: McgBarPoint[];
  };
  mv_series: Array<{ report_date: string; total_mv: number | null }>;
  sample_count?: Array<{ report_date: string; count: number }>;
  note?: string;
}

export function useMarketCapGrowth(
  kind: 'index' | 'stock',
  code: string | null,
  years = 10,
) {
  const [data, setData] = useState<McgData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(
      `${API_BASE}/financial/market-cap-growth/${kind}/${code}?years=${years}`,
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
  }, [kind, code, years]);

  return { data, loading, error };
}
