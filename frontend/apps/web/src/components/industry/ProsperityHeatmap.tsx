/** 31行业×指标矩阵:单元格按列内 min-max 着色(HEAT_SCALE),估值分位取反。 */
import {useEffect, useMemo, useRef, useState} from 'react';
import {Card, StateView} from '../ui';
import type {OverviewRow, PctWindow} from '../../hooks/useIndustryAnalysis';
import {fmtN, fmtPctAbs, fmtPctN, fmtYi, heatColor, sortByCol} from '../../lib/heat';

interface Col {
  key: keyof OverviewRow;
  label: string;
  fmt: (r: OverviewRow) => string;
  inverse?: boolean;   // true=低值暖色(估值分位)
}

const COLS: Col[] = [
  {key: 'score', label: '景气分', fmt: (r) => fmtN(r.score, 0)},
  {key: 'revenue_yoy', label: '营收同比', fmt: (r) => fmtPctN(r.revenue_yoy)},
  {key: 'net_profit_yoy', label: '净利同比', fmt: (r) => fmtPctN(r.net_profit_yoy)},
  {key: 'pe_ttm', label: 'PE(TTM)', fmt: (r) => fmtN(r.pe_ttm, 1)},
  {key: 'pe_pct', label: 'PE分位', fmt: (r) => fmtPctAbs(r.pe_pct), inverse: true},
  {key: 'pb', label: 'PB', fmt: (r) => fmtN(r.pb, 2)},
  {key: 'pb_pct', label: 'PB分位', fmt: (r) => fmtPctAbs(r.pb_pct), inverse: true},
  {key: 'rs60', label: 'RS60', fmt: (r) => fmtPctN(r.rs60)},
  {key: 'flow20', label: '20日资金', fmt: (r) => fmtYi(r.flow20)},
];

/** 估值分位窗口能改变的仅此两列;其余列来自固定口径评分快照(规格§4 F2)。 */
const WIN_COLS = new Set<string>(['pe_pct', 'pb_pct']);

interface Props {
  win: PctWindow;
  setWin: (w: PctWindow) => void;
  overview: {data: {rows: OverviewRow[]; trade_date: string | null} | null;
             loading: boolean; error: string | null};
  onPick: (swCode: string) => void;
}

export function ProsperityHeatmap({win, setWin, overview, onPick}: Props) {
  const [sortKey, setSortKey] = useState<keyof OverviewRow>('score');
  const [dir, setDir] = useState<-1 | 1>(-1);
  const [flash, setFlash] = useState(false);
  const prevWin = useRef(win);
  const rows = overview.data?.rows ?? [];

  // 切换年限→受影响两列闪烁 1.5s;初次挂载不触发;连点则计时器重置
  useEffect(() => {
    if (prevWin.current === win) return;
    prevWin.current = win;
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 1500);
    return () => clearTimeout(t);
  }, [win]);

  const {sorted, bounds} = useMemo(() => {
    const b: Record<string, [number, number]> = {};
    for (const c of COLS) {
      const vals = rows.map((r) => r[c.key] as number | null)
        .filter((v): v is number => v != null && Number.isFinite(v));
      b[c.key as string] = vals.length
        ? [Math.min(...vals), Math.max(...vals)] : [0, 0];
    }
    return {sorted: sortByCol(rows as any[], sortKey as string, dir), bounds: b};
  }, [rows, sortKey, dir]);

  const toggleSort = (key: keyof OverviewRow) => {
    if (key === sortKey) setDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(key); setDir(key === 'name' ? 1 : -1); }
  };

  if (overview.loading && !rows.length) return <StateView state="loading" />;
  if (overview.error) return <StateView state="error" text={overview.error} />;
  if (!rows.length) return <StateView state="empty" text="暂无景气分数据" />;

  return (
    <Card>
      <div className="ia-toolbar">
        <span className="ia-hint">评分日 {overview.data?.trade_date} · 估值分位窗口</span>
        {([5, 8, 10] as PctWindow[]).map((w) => (
          <button key={w} className={`ia-select ${w === win ? 'is-active' : ''}`}
            onClick={() => setWin(w)}>{w}年</button>
        ))}
        <span className="ia-hint">年限仅切换 PE分位/PB分位 两列(↻);景气分口径恒定8年</span>
      </div>
      <div className="ia-heat-wrap">
        <table className="ia-heat">
          <thead><tr>
            <th onClick={() => toggleSort('name')}>行业</th>
            <th>难易度</th>
            {COLS.map((c) => (
              <th key={c.key as string} onClick={() => toggleSort(c.key)}>
                {c.label}
                {WIN_COLS.has(c.key as string) &&
                  <i className="ia-win-mark" title="此列随年限窗口切换,其余列口径恒定">↻</i>}
                {sortKey === c.key ? (dir === -1 ? ' ↓' : ' ↑') : ''}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.sw_code} onClick={() => onPick(r.sw_code)}
                title={r.hist_start ? `估值历史自 ${r.hist_start}(分位窗口内)` : undefined}>
                <td><b>{r.name}</b></td>
                <td style={{textAlign: 'left'}}>
                  <span className={`ia-tier ia-tier--${r.tier}`}>{r.tier_label}</span>
                </td>
                {COLS.map((c) => {
                  const [lo, hi] = bounds[c.key as string] ?? [0, 0];
                  const v = r[c.key] as number | null;
                  const bg = heatColor(v, lo, hi, c.inverse);
                  const winCol = WIN_COLS.has(c.key as string);
                  return (
                    <td key={c.key as string}
                      className={`num${winCol && flash ? ' is-flash' : ''}`}
                      style={bg ? {background: bg + '55',
                        fontWeight: c.key === 'score' ? 700 : undefined} : undefined}>
                      {c.fmt(r)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
