import {describe, expect, it, vi} from 'vitest';

// BlindMask 引 store → api 顶层读 localStorage（node 环境无），mock 断链；
// useReplayStore 仅在 hook 调用时执行，纯函数测试不受影响
vi.mock('../store', () => ({useReplayStore: vi.fn()}));

import {dayLabelOf} from '../BlindMask';

describe('dayLabelOf', () => {
  const dates = ['2020-03-13', '2020-03-16', '2020-03-17'];
  it('盲盒中渲染为第N天', () => {
    expect(dayLabelOf(true, dates, '2020-03-13')).toBe('第1天');
    expect(dayLabelOf(true, dates, '2020-03-17')).toBe('第3天');
  });
  it('非盲盒原样返回;未知日期原样返回', () => {
    expect(dayLabelOf(false, dates, '2020-03-13')).toBe('2020-03-13');
    expect(dayLabelOf(true, dates, '2020-03-20')).toBe('2020-03-20');
  });
  it('offset 锚定旅程首日为第1天(历史窗不算天数)', () => {
    // 3000根历史窗 + 3个旅程日:offset=3000,旅程日=第1/2/3天
    const win = [...Array(3000).keys()].map((i) => `2010-${i}`);
    win.push('2020-01-01', '2020-01-02', '2020-01-03');
    const off = win.length - 3;
    expect(dayLabelOf(true, win, '2020-01-01', off)).toBe('第1天');
    expect(dayLabelOf(true, win, '2020-01-03', off)).toBe('第3天');
    // 旅程开始前的历史日 → 前N日
    expect(dayLabelOf(true, win, win[2999], off)).toBe('前1日');
    expect(dayLabelOf(true, win, win[0], off)).toBe('前3000日');
  });
});
