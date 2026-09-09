/**
 * 财务分析叠加层数据 hooks。
 *
 * 三个独立 hook 各自降级，互不阻塞：
 *   - useStockValuationHistory: 个股 PE/PB/PS 历史（按报告期末对齐）
 *   - usePriceOverlays: 个股股价 + 行业指数（按报告期末对齐）
 *   - useIndustryValuationSnapshot: 行业 PE/PB 当天快照
 *
 * buildOverlayData: 把前两者合并成 FinancialOverlayChart 需要的 OverlayData。
 */
import { useEffect, useMemo, useState } from 'react';
import { getApiBase } from '../lib/api';

const API_BASE = getApiBase();

// ── 类型 ────────────────────────────────────────────────────────────────

export type OverlayKey =
  | 'stock_price'
  | 'industry_index'
  | 'pe'
  | 'pb'
  | 'ps';

export interface ValuationPoint {
  report_date: string;
  trade_date: string | null;
  pe: number | null;
  pe_ttm: number | null;
  pb: number | null;
  ps: number | null;
  total_mv: number | null;
}

export interface OverlayPoint {
  stock_price?: number;
  industry_index?: number;
  pe?: number;
  pb?: number;
  ps?: number;
}

/** key = report_date（YYYY-MM-DD），与财务图表 x 轴对齐 */
export type OverlayData = Record<string, OverlayPoint>;

export interface IndustrySnapshot {
  industry: string;
  sw_code: string;
  as_of: string;
  pe_static: number | null;
  pe_ttm: number | null;
  pb: number | null;
  dividend_yield: number | null;
  company_count: number | null;
}

export interface IndustryListItem {
  sw_code: string;
  industry: string;
  company_count: number | null;
  pe_static: number | null;
  pe_ttm: number | null;
  pb: number | null;
  dividend_yield: number | null;
}

// ── 1. 个股估值历史（按报告期末）─────────────────────────────────────────

export function useStockValuationHistory(
  symbol: string,
  reportDates: string[],
): { data: Map<string, ValuationPoint>; loading: boolean } {
  const [data, setData] = useState<Map<string, ValuationPoint>>(
    () => new Map(),
  );
  const [loading, setLoading] = useState(false);

  const key = symbol + '|' + reportDates.join(',');
  useEffect(() => {
    if (!symbol || !reportDates.length) {
      setData(new Map());
      return;
    }
    let alive = true;
    setLoading(true);
    const params = new URLSearchParams();
    params.set('report_dates', reportDates.join(','));
    fetch(
      `${API_BASE}/financial/valuation-history/${symbol}?${params}`,
    )
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        const points: ValuationPoint[] = j.data?.points || [];
        const m = new Map<string, ValuationPoint>();
        for (const p of points) m.set(p.report_date, p);
        setData(m);
      })
      .catch(() => {
        if (alive) setData(new Map());
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, loading };
}

// ── 2. 股价 + 行业指数（按报告期末对齐）──────────────────────────────────

interface RawBar {
  trade_date: string;
  close: number;
}

/**
 * 拉个股 + 行业指数日线，按 reportDates 取「<= report_date 的最近收盘价」。
 * 返回 Map<report_date, {stock_price, industry_index}>。
 */
export function usePriceOverlays(
  symbol: string,
  industrySwCode: string | null,
  reportDates: string[],
  startDate: string,
  endDate: string,
): { data: Map<string, OverlayPoint>; loading: boolean } {
  const [data, setData] = useState<Map<string, OverlayPoint>>(
    () => new Map(),
  );
  const [loading, setLoading] = useState(false);

  const key = [
    symbol,
    industrySwCode || '',
    reportDates.join(','),
    startDate,
    endDate,
  ].join('|');

  useEffect(() => {
    if (!symbol || !reportDates.length) {
      setData(new Map());
      return;
    }
    let alive = true;
    setLoading(true);

    const fetchKline = async (sym: string): Promise<RawBar[]> => {
      const params = new URLSearchParams();
      params.set('interval', '1d');
      params.set('limit', '8000');
      if (startDate) params.set('start', startDate);
      if (endDate) params.set('end', endDate);
      try {
        const r = await fetch(
          `${API_BASE}/market/kline/${sym}?${params}`,
        );
        const j = await r.json();
        const bars: any[] = j.data?.bars || [];
        return bars
          .map((b) => ({
            trade_date: String(b.trade_date).slice(0, 10),
            close: Number(b.close),
          }))
          .filter(
            (b) =>
              b.trade_date && Number.isFinite(b.close),
          )
          .sort((a, b) =>
            a.trade_date.localeCompare(b.trade_date),
          );
      } catch {
        return [];
      }
    };

    const symbols = [symbol];
    if (industrySwCode) symbols.push(industrySwCode);

    Promise.all(symbols.map((s) => fetchKline(s))).then(
      (allBars) => {
        if (!alive) return;
        const stockBars = allBars[0] || [];
        const indexBars = allBars[1] || [];

        // 对每个 report_date，二分找 <= report_date 的最近交易日
        const pickClosest = (
          bars: RawBar[],
          rd: string,
        ): number | undefined => {
          // bars 已升序；从末尾往前找第一个 <= rd
          for (let i = bars.length - 1; i >= 0; i--) {
            if (bars[i].trade_date <= rd) return bars[i].close;
          }
          return undefined;
        };

        const m = new Map<string, OverlayPoint>();
        for (const rd of reportDates) {
          const point: OverlayPoint = {};
          const sp = pickClosest(stockBars, rd);
          if (sp !== undefined) point.stock_price = sp;
          if (industrySwCode) {
            const ip = pickClosest(indexBars, rd);
            if (ip !== undefined) point.industry_index = ip;
          }
          m.set(rd, point);
        }
        setData(m);
      },
    ).finally(() => {
      if (alive) setLoading(false);
    });

    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, loading };
}

// ── 3. 行业估值快照 ──────────────────────────────────────────────────────

export function useIndustryValuationSnapshot(
  industrySwCode: string | null,
): {
  data: IndustrySnapshot | null;
  list: IndustryListItem[];
  loading: boolean;
} {
  const [snapshot, setSnapshot] =
    useState<IndustrySnapshot | null>(null);
  const [list, setList] = useState<IndustryListItem[]>([]);
  const [loading, setLoading] = useState(false);

  const listKey = 'all'; // 全行业列表只拉一次
  const singleKey = industrySwCode || '';

  // 拉全行业列表（供下拉，1 小时缓存由后端保证）
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API_BASE}/financial/industry-valuation-snapshot`)
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        const industries: IndustryListItem[] =
          j.data?.industries || [];
        setList(industries);
      })
      .catch(() => {
        if (alive) setList([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listKey]);

  // 按选中行业拉单条快照
  useEffect(() => {
    if (!industrySwCode) {
      setSnapshot(null);
      return;
    }
    let alive = true;
    fetch(
      `${API_BASE}/financial/industry-valuation-snapshot?industry=${encodeURIComponent(industrySwCode)}`,
    )
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        setSnapshot(j.data || null);
      })
      .catch(() => {
        if (alive) setSnapshot(null);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [singleKey]);

  return { data: snapshot, list, loading };
}

// ── 4. 日线收盘价 Map（估值分位图叠加股价用）─────────────────────────────

/**
 * 拉个股全量日线收盘价，按给定日期列表取「<= 该日期的最近收盘价」。
 * enabled=false 时不请求（叠加开关关闭时省一次全量 kline）。
 */
export function useKlineCloseMap(
  symbol: string | null,
  dates: string[],
  enabled: boolean,
): { data: Map<string, number>; loading: boolean } {
  const [bars, setBars] = useState<RawBar[]>([]);
  const [loading, setLoading] = useState(false);
  const datesKey = dates.join(',');
  const key = `${symbol}|${enabled}`;

  useEffect(() => {
    if (!symbol || !enabled) {
      setBars([]);
      return;
    }
    let alive = true;
    setLoading(true);
    const params = new URLSearchParams();
    params.set('interval', '1d');
    params.set('limit', '8000');
    // 显式 start 走后端「从早到晚」分支：即使未来日线超过 limit 也从最早处覆盖
    params.set('start', '1990-01-01');
    fetch(`${API_BASE}/market/kline/${symbol}?${params}`)
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        const raw: any[] = j.data?.bars || [];
        setBars(
          raw
            .map((b) => ({
              trade_date: String(b.trade_date).slice(0, 10),
              close: Number(b.close),
            }))
            .filter((b) => b.trade_date && Number.isFinite(b.close))
            .sort((a, b) => a.trade_date.localeCompare(b.trade_date)),
        );
      })
      .catch(() => {
        if (alive) setBars([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const data = useMemo(() => {
    const m = new Map<string, number>();
    if (!bars.length || !dates.length) return m;
    for (const d of dates) {
      // 二分：最后一个 trade_date <= d 的 bar
      let lo = 0;
      let hi = bars.length - 1;
      let ans = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (bars[mid].trade_date <= d) {
          ans = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      if (ans >= 0) m.set(d, bars[ans].close);
    }
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, datesKey]);

  return { data, loading };
}

// ── 合并函数：估值 + 价格 → OverlayData ──────────────────────────────────

/**
 * 把估值 Map 和价格 Map 合并成 OverlayData（key = report_date）。
 * 任一 Map 缺失的 report_date 不出现（以财务 reportDates 为准）。
 */
export function buildOverlayData(
  valMap: Map<string, ValuationPoint>,
  priceMap: Map<string, OverlayPoint>,
  reportDates: string[],
): OverlayData {
  const out: OverlayData = {};
  for (const rd of reportDates) {
    const v = valMap.get(rd);
    const p = priceMap.get(rd);
    const point: OverlayPoint = {};
    if (p) {
      if (p.stock_price !== undefined)
        point.stock_price = p.stock_price;
      if (p.industry_index !== undefined)
        point.industry_index = p.industry_index;
    }
    if (v) {
      point.pe = v.pe ?? undefined;
      point.pb = v.pb ?? undefined;
      point.ps = v.ps ?? undefined;
    }
    out[rd] = point;
  }
  return out;
}
