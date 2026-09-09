/**
 * 波特五力（five forces）数据 hook。
 *
 * 调用 GET /financial/five-forces/{symbol}，
 * 五力评分（0-100，None=数据不足）+ 每力证据列表 + 总分。
 */
import { useEffect, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

export interface ForceEvidence {
  metric: string;
  value: number | null;
  unit?: string;
  trend?: (number | null)[];
  interpretation: string;
}

export interface Force {
  key: string;
  label: string;
  score: number | null;
  evidence: ForceEvidence[];
}

export interface FiveForcesData {
  symbol: string;
  forces: Force[];
  total_score: number | null;
  note?: string;
}

export function useFiveForces(symbol: string | null) {
  const [data, setData] = useState<FiveForcesData | null>(null);
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
    fetch(`${API_BASE}/financial/five-forces/${symbol}`)
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
  }, [symbol]);

  return { data, loading, error };
}
