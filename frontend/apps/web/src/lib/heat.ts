/** 行业热力图纯逻辑:着色/排序/格式化(vitest 覆盖)。 */
import {HEAT_SCALE} from './chartTheme';

const [LO, MID, HI] = HEAT_SCALE;   // '#ffd60a' → '#ff9f0a' → '#ff453a'

function lerpColor(c1: string, c2: string, t: number): string {
  const p = (c: string) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const [r1, g1, b1] = p(c1);
  const [r2, g2, b2] = p(c2);
  const m = (a: number, b: number) => Math.round(a + (b - a) * t);
  const hex = (n: number) => n.toString(16).padStart(2, '0');
  return `#${hex(m(r1, r2))}${hex(m(g1, g2))}${hex(m(b1, b2))}`;
}

/** 值→暖色刻度;inverse=true 时低值暖(估值分位低=便宜=好)。null→null。 */
export function heatColor(v: number | null, lo: number, hi: number,
                          inverse = false): string | null {
  if (v == null || !Number.isFinite(v) || hi <= lo) return null;
  let t = (v - lo) / (hi - lo);
  t = Math.min(1, Math.max(0, t));
  if (inverse) t = 1 - t;
  return t <= 0.5 ? lerpColor(LO, MID, t * 2) : lerpColor(MID, HI, t * 2 - 1);
}

/** 排序:null 一律沉底;dir=1 升序/-1 降序。 */
export function sortByCol<T extends Record<string, any>>(rows: T[],
                                                         key: string,
                                                         dir: 1 | -1): T[] {
  return [...rows].sort((a, b) => {
    const va = a[key];
    const vb = b[key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') {
      return (va - vb) * dir;
    }
    return String(va).localeCompare(String(vb)) * dir;
  });
}

export const TIER_LABEL: Record<number, string> = {
  1: '易分析', 2: '需专业分析', 3: '消息驱动',
};

export const fmtPctN = (v: number | null | undefined, digits = 1): string =>
  v == null || !Number.isFinite(v) ? '—'
    : `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;

/** 分位类百分数(0-100,不加正号) */
export const fmtPctAbs = (v: number | null | undefined, digits = 0): string =>
  v == null || !Number.isFinite(v) ? '—' : `${v.toFixed(digits)}%`;

export const fmtYi = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? '—' : `${(v / 1e8).toFixed(1)}亿`;

export const fmtN = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? '—' : v.toFixed(digits);
