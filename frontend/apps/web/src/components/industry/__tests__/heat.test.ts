import {describe, expect, it} from 'vitest';
import {heatColor, sortByCol} from '../../../lib/heat';

describe('heatColor', () => {
  it('三段插值边界', () => {
    expect(heatColor(0, 0, 10)).toBe('#ffd60a');
    expect(heatColor(10, 0, 10)).toBe('#ff453a');
    expect(heatColor(5, 0, 10)).toBe('#ff9f0a');
  });
  it('inverse 取反(估值分位低=好→暖色)', () => {
    expect(heatColor(0, 0, 10, true)).toBe('#ff453a');
    expect(heatColor(10, 0, 10, true)).toBe('#ffd60a');
  });
  it('null/退化区间', () => {
    expect(heatColor(null, 0, 10)).toBeNull();
    expect(heatColor(3, 5, 5)).toBeNull();
  });
});

describe('sortByCol', () => {
  const rows = [{a: 2, b: 'x'}, {a: null, b: 'y'}, {a: 1, b: 'z'}];
  it('数值列降序,null 沉底', () => {
    expect(sortByCol(rows, 'a', -1).map((r) => r.a)).toEqual([2, 1, null]);
  });
  it('字符串列升序', () => {
    expect(sortByCol(rows, 'b', 1).map((r) => r.b)).toEqual(['x', 'y', 'z']);
  });
});
