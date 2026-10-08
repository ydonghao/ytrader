/** 行业分析数据 hook(GET /industry/*;信封 {code,msg,data})。 */
import {useCallback, useEffect, useRef, useState} from 'react';
import {getApiBase} from '../lib/api';

const API_BASE = getApiBase();

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  const j = await r.json();
  if (j.code !== 0) throw new Error(j.msg || '请求失败');
  return j.data as T;
}

export type PctWindow = 5 | 8 | 10;

export interface OverviewRow {
  sw_code: string;
  name: string;
  tier: number;
  tier_label: string;
  retail_suitable: string;
  revenue_yoy: number | null;
  net_profit_yoy: number | null;
  pe_ttm: number | null;
  pe_pct: number | null;
  pb: number | null;
  pb_pct: number | null;
  rs60: number | null;
  flow20: number | null;
  score: number | null;
  score_profit: number | null;
  score_valuation: number | null;
  score_momentum: number | null;
  score_flow: number | null;
  hist_start: string | null;
}

export interface OverviewData {
  trade_date: string | null;
  window: number;
  rows: OverviewRow[];
}

export interface PbBreakPoint {
  trade_date: string;
  total_count: number;
  break_count: number;
  break_rate: number | null;
  median_pb: number | null;
}

export interface PbBreakData {
  scope: string;
  scope_code: string | null;
  threshold: number;
  series: PbBreakPoint[];
  current: PbBreakPoint | null;
  current_percentile: number | null;
  over_threshold_now: boolean;
}

export interface FlowRow {
  em_industry_name: string;
  sw_code: string | null;
  day: number | null;
  flow5: number | null;
  flow20: number | null;
}

export interface IndustryDetail {
  sw_code: string;
  name: string;
  knowledge: {
    tier: number;
    tier_label: string;
    retail_suitable: string;
    approach: string;
    upstream: string[];
    downstream: string[];
    note: string;
  };
  prosperity: {
    score: number | null;
    score_profit: number | null;
    score_valuation: number | null;
    score_momentum: number | null;
    score_flow: number | null;
    inputs: Record<string, number | null>;
  } | null;
  valuation_date: string | null;
  member_count: number;
  pb_histogram: {edges: number[]; counts: number[]};
  pe_histogram: {edges: number[]; counts: number[]};
  members: {symbol: string; name: string | null; pb: number | null;
            pe_ttm: number | null; total_mv: number | null}[];
  concentration: Record<string, any> | null;
}

export interface StrengthData {
  sw_code: string;
  benchmark: {date: string; close: number}[];
  lines: Record<string, {date: string; rs: number}[]>;
  names: Record<string, string>;
}

function useJson<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const genRef = useRef(0);
  const load = useCallback(() => {
    if (!url) return;
    const gen = ++genRef.current;
    setLoading(true);
    getJson<T>(url)
      .then((d) => {
        if (gen !== genRef.current) return;
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (gen !== genRef.current) return;
        setError(e.message);
      })
      .finally(() => {
        if (gen === genRef.current) setLoading(false);
      });
  }, [url]);
  useEffect(() => { load(); }, [load]);
  return {data, loading, error, reload: load};
}

export function useIndustryOverview(win: PctWindow) {
  return useJson<OverviewData>(`${API_BASE}/industry/overview?window=${win}`);
}

export function usePbBreak(scope: 'market' | 'industry', scopeCode: string,
                           years: number) {
  const qs = new URLSearchParams({scope, years: String(years)});
  if (scope === 'industry') qs.set('scope_code', scopeCode);
  return useJson<PbBreakData>(`${API_BASE}/industry/pb-break?${qs}`);
}

export function useIndustryFlow() {
  return useJson<{snapshot: string | null; rows: FlowRow[]}>(
    `${API_BASE}/industry/flow`);
}

export function useIndustryDetail(swCode: string | null) {
  return useJson<IndustryDetail>(
    swCode ? `${API_BASE}/industry/${swCode}` : null);
}

export function useStrength(swCode: string | null, compare: string[]) {
  const qs = compare.length ? `?compare=${compare.join(',')}` : '';
  return useJson<StrengthData>(
    swCode ? `${API_BASE}/industry/${swCode}/strength${qs}` : null);
}

export function useInterpret() {
  const [result, setResult] = useState<
    {summary: string; drivers: string[]; risks: string[]} | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (swCode: string) => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/industry/${swCode}/interpret`,
        {method: 'POST'});
      const j = await r.json();
      if (j.code !== 0) throw new Error(j.msg || j.detail || '解读失败');
      setResult(j.data);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setLoading(false);
    }
  }, []);
  return {run, result, loading, error};
}
