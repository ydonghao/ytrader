import {describe, expect, it, vi} from 'vitest';

// OrderTicket 引 store → api 顶层读 localStorage（node 环境无），mock 断链；
// useReplayStore 仅在组件渲染时执行，纯函数测试不受影响
vi.mock('../store', () => ({useReplayStore: vi.fn()}));

import {validateExamOrder} from '../OrderTicket';

describe('validateExamOrder', () => {
  it('理由必填且≤140字', () => {
    expect(validateExamOrder('', 'market', null)).toContain('理由');
    expect(validateExamOrder('  ', 'market', null)).toContain('理由');
    expect(validateExamOrder('a'.repeat(141), 'market', null))
      .toContain('理由');
    expect(validateExamOrder('低吸', 'market', null)).toBeNull();
  });
  it('限价必须为正数', () => {
    expect(validateExamOrder('挂单', 'limit', null)).toContain('限价');
    expect(validateExamOrder('挂单', 'limit', 0)).toContain('限价');
    expect(validateExamOrder('挂单', 'limit', 10.5)).toBeNull();
  });
});
