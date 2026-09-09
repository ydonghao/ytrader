/**
 * 财务明细数据 hook — GET /financial/detail(income/单季)。
 * 有全局起始日时走 start_date/end_date,否则 limit=100;
 * 后端 series 最新期在前,这里反转为升序供图表使用。
 */
import {useEffect, useState} from 'react';
import {getApiBase} from '../../../lib/api';
import {DateRange} from '../boardTypes';

const API_BASE = getApiBase();

export interface FinDetailPoint {
  report_date: string | null;
  [k: string]: unknown;
}

export function useFinancialDetail(
  symbol: string | null,
  range: DateRange,
  refreshKey: number,
) {
  const [series, setSeries] = useState<FinDetailPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    const qs = new URLSearchParams({statement_type: 'income', period: 'quarter'});
    if (range.start) {
      qs.set('start_date', range.start);
      qs.set('end_date', range.end || new Date().toISOString().slice(0, 10));
    } else {
      qs.set('limit', '100');
    }
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/financial/detail/${symbol}?${qs}`)
      .then((r) => r.json())
      .then((json) => {
        if (cancelled) return;
        if (json.code === 0) {
          setSeries([...(json.data?.series || [])].reverse());
        } else {
          setError(json.msg || '请求失败');
          setSeries([]);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        setSeries([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, range.start, range.end, refreshKey]);

  return {series, loading, error};
}
