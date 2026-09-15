import {describe, expect, it} from 'vitest';
import {kdj, macd, rsiWilder, sma} from '../indicators';

describe('sma', () => {
  it('手算小序列', () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });
  it('n=1 原样返回', () => {
    expect(sma([7, 8], 1)).toEqual([7, 8]);
  });
});

describe('kdj', () => {
  const bars = Array.from({length: 12}, (_, i) => ({
    high: 10 + i, low: 8 + i, close: 9 + i,
  }));
  it('前 n-1 个为 null，之后有值且 K/D 在 0~100', () => {
    const out = kdj(bars, 9);
    expect(out).toHaveLength(12);
    expect(out[7].k).toBeNull();
    expect(out[8].k).not.toBeNull();
    for (const p of out.slice(8)) {
      expect(p.k!).toBeGreaterThanOrEqual(0);
      expect(p.k!).toBeLessThanOrEqual(100);
      expect(p.d!).toBeGreaterThanOrEqual(0);
      expect(p.d!).toBeLessThanOrEqual(100);
      expect(p.j!).toBeCloseTo(3 * p.k! - 2 * p.d!, 6);
    }
  });
  it('单边上涨 RSV=100 → K 单调上升', () => {
    const out = kdj(bars, 9).slice(8);
    for (let i = 1; i < out.length; i++) {
      expect(out[i].k!).toBeGreaterThanOrEqual(out[i - 1].k!);
    }
  });
});

describe('复用 Board 指标', () => {
  it('macd 输出等长且 hist=dif-dea', () => {
    const closes = Array.from({length: 40}, (_, i) => 10 + Math.sin(i / 3));
    const {dif, dea, hist} = macd(closes, 12, 26, 9);
    expect(dif).toHaveLength(40);
    const i = 39;
    if (dif[i] != null && dea[i] != null) {
      expect(hist[i]!).toBeCloseTo(dif[i]! - dea[i]!, 6);
    }
  });
  it('rsiWilder 值域 0~100', () => {
    const closes = Array.from({length: 30}, (_, i) => 10 + i * 0.1);
    const r = rsiWilder(closes, 14);
    const last = r[r.length - 1];
    expect(last).not.toBeNull();
    expect(last!).toBeGreaterThan(50); // 单边上涨
    expect(last!).toBeLessThanOrEqual(100);
  });
});
