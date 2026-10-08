import {describe, expect, it} from 'vitest';
import {computeScale} from '../IntradayStrip';

describe('computeScale', () => {
  const seg = (c: number) => ({open: c, high: c + 1, low: c - 1, close: c});
  it('范围覆盖段高低与昨收,含边距', () => {
    const {lo, hi} = computeScale([seg(10), seg(11)], 10.5);
    expect(lo).toBeLessThan(9);
    expect(hi).toBeGreaterThan(12);
  });
  it('一字段也能出有限刻度', () => {
    const {lo, hi} = computeScale([{open: 5, high: 5, low: 5, close: 5}], 5);
    expect(lo).toBeLessThan(5);
    expect(hi).toBeGreaterThan(5);
    expect(Number.isFinite(lo) && Number.isFinite(hi)).toBe(true);
  });
});
