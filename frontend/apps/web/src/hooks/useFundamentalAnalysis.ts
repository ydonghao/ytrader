/**
 * 个股基本面深度分析 hook。
 *
 * 调用 GET /financial/fundamental-analysis/{symbol}（同步返回结构化报告）。
 * 后端注入真实三大报表 + 估值分位 + 衍生指标，LLM 产出结构化结论，
 * 铁律禁止臆测（数据缺失标「无数据」）。
 */
import {useEffect, useState} from 'react';
import {getApiBase} from '../lib/api';

const API_BASE = getApiBase();

export interface FaSection {
  summary?: string;
  [k: string]: any;
}

export interface FaMoat {
  has_moat?: boolean;
  evidence?: string[];
  summary?: string;
}

export interface FaRisk {
  category?: string;
  description?: string;
  severity?: string;
}

export interface FundamentalReport {
  symbol?: string;
  data_available?: boolean;
  periods_injected?: number;
  profitability?: FaSection;
  financial_health?: FaSection;
  valuation?: FaSection;
  capital_efficiency?: FaSection;
  moat?: FaMoat;
  risks?: FaRisk[];
  overall_score?: number;
  one_line_conclusion?: string;
}

export function useFundamentalAnalysis(symbol: string | null, periods = 12) {
  const [data, setData] = useState<FundamentalReport | null>(null);
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
    fetch(`${API_BASE}/financial/fundamental-analysis/${symbol}?periods=${periods}`)
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
  }, [symbol, periods]);

  return {data, loading, error};
}
