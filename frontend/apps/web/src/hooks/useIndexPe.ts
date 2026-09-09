/**
 * 指数整体法市盈率趋势数据 hook。
 *
 * 调 GET /financial/index-pe/{code}，years=0 为全部历史。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface IndexPePoint {
  date: string;
  pe: number | null;
}

export interface IndexPeStats {
  mean: number;
  std: number;
  high: number;
  low: number;
  sample_size: number;
}

export interface IndexPeData {
  kind: 'index_pe';
  code: string;
  name: string | null;
  as_of: string | null;
  series: IndexPePoint[];
  stats: IndexPeStats | null;
  current: IndexPePoint | null;
  note?: string;
}

export function useIndexPe(code: string | null, years = 8) {
  const [data, setData] = useState<IndexPeData | null>(null);
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
    fetch(`${API_BASE}/financial/index-pe/${code}?years=${years}`)
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
  }, [code, years]);

  return { data, loading, error };
}
