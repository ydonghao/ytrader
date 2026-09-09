/**
 * 个股基本面分析历史 hook。
 *
 * 调用 GET /financial/fundamental-analysis/{symbol}/history，
 * 返回历史报告列表（评分趋势 / 回看）。
 */
import {useEffect, useState} from 'react';
import {getApiBase} from '../lib/api';

const API_BASE = getApiBase();

export interface HistoryReport {
  id: number;
  created_at: string | null;
  overall_score: number | null;
  data_available?: boolean;
  one_line_conclusion?: string;
}

export function useFundamentalAnalysisHistory(symbol: string | null, limit = 20) {
  const [data, setData] = useState<HistoryReport[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(`${API_BASE}/financial/fundamental-analysis/${symbol}/history?limit=${limit}`)
      .then((r) => r.json())
      .then((json) => {
        if (cancelled) return;
        setData(json.code === 0 ? (json.data?.reports || []) : null);
      })
      .catch(() => {
        if (cancelled) return;
        setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, limit]);

  return {data, loading};
}
