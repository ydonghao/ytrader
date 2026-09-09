/**
 * 财报季景气雷达数据 hook。
 * GET /boom/radar —— 财报季状态 + 候选池;可见时 60s 轮询。
 */
import {useCallback, useEffect, useRef, useState} from 'react';
import {getApiBase} from '../lib/api';
import {useIntervalWhenVisible} from './useIntervalWhenVisible';

const API_BASE = getApiBase();

export interface BoomHit {
  keyword: string;
  category: string;
  category_label: string;
  source_type: string;
  source_date: string | null;
  snippet: string;
}

export interface BoomCandidate {
  symbol: string;
  report_date: string;
  forecast_type: string;
  company_name: string | null;
  announce_date: string | null;
  change_pct: number | null;
  forecast_type_label: string | null;
  categories: string[];
  category_labels: string[];
  keyword_count: number;
  news_hit_count: number;
  llm_score: number | null;
  llm_verdict: string | null;
  llm_summary: string | null;
  status: string;
  hits_preview: BoomHit[];
}

export interface BoomRadarData {
  season: {
    in_season: boolean;
    window_name: string;
    window_start: string;
    window_end: string;
    next_window_start: string;
  };
  report_dates: string[];
  candidates: BoomCandidate[];
  summary: {pool: number; with_hits: number};
}

export function useBoomRadar(params: {reportDate?: string; categories?: string}) {
  const [data, setData] = useState<BoomRadarData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // generation 计数器:仅最新一次请求可写状态,防止旧请求(旧筛选条件)晚返回覆盖新数据
  const genRef = useRef(0);

  const load = useCallback(() => {
    const gen = ++genRef.current;
    const qs = new URLSearchParams();
    if (params.reportDate) qs.set('report_date', params.reportDate);
    if (params.categories) qs.set('categories', params.categories);
    const url = `${API_BASE}/boom/radar${qs.toString() ? '?' + qs.toString() : ''}`;
    setLoading(true);
    fetch(url)
      .then((r) => r.json())
      .then((json) => {
        if (gen !== genRef.current) return;
        if (json.code === 0) {
          setData(json.data);
          setError(null);
        } else {
          setError(json.msg || '请求失败');
        }
      })
      .catch((e) => {
        if (gen !== genRef.current) return;
        setError(String(e));
      })
      .finally(() => {
        if (gen === genRef.current) setLoading(false);
      });
  }, [params.reportDate, params.categories]);

  useEffect(() => {
    load();
  }, [load]);

  useIntervalWhenVisible(load, 60_000);

  return {data, loading, error, reload: load};
}
