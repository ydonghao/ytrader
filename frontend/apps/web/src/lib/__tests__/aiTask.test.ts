import {describe, expect, it} from 'vitest';
import {aiTaskReducer} from '../aiTask';

describe('aiTaskReducer', () => {
  it('idle→start→loading', () => {
    expect(aiTaskReducer({status: 'idle'}, {type: 'start'}))
      .toEqual({status: 'loading'});
  });

  it('loading→done→idle(无错误残留)', () => {
    expect(aiTaskReducer({status: 'loading'}, {type: 'done'}))
      .toEqual({status: 'idle'});
  });

  it('loading→fail→error带信息', () => {
    expect(aiTaskReducer({status: 'loading'}, {type: 'fail', error: 'LLM 调用失败'}))
      .toEqual({status: 'error', error: 'LLM 调用失败'});
  });

  it('error→start→loading(错误清空,重试路径)', () => {
    expect(aiTaskReducer({status: 'error', error: 'x'}, {type: 'start'}))
      .toEqual({status: 'loading'});
  });

  it('任意→reset→idle', () => {
    expect(aiTaskReducer({status: 'error', error: 'x'}, {type: 'reset'}))
      .toEqual({status: 'idle'});
  });
});
