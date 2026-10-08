import {describe, expect, it} from 'vitest';
import {
  CATEGORY_LABEL,
  PE_STATE_LABEL,
  RISK_PROFILES,
  categoryOf,
  fmtMoney,
  fmtPct,
  pydanticErrorDetail,
  validateWizardInput,
} from './coursePortfolio';

describe('coursePortfolio lib', () => {
  it('四档风险配比之和为1且覆盖课程23数值', () => {
    expect(RISK_PROFILES.map(p => p.key)).toEqual(
      ['defensive', 'balanced', 'aggressive', 'radical']);
    for (const p of RISK_PROFILES) {
      const sum = p.weights.dividend + p.weights.bluechip + p.weights.growth;
      expect(Math.abs(sum - 1)).toBeLessThan(1e-9);
    }
    expect(RISK_PROFILES[0].weights).toEqual({dividend: 0.7, bluechip: 0.3, growth: 0.0});
    expect(RISK_PROFILES[3].weights).toEqual({dividend: 0.0, bluechip: 0.3, growth: 0.7});
  });

  it('状态与类别中文标签齐全', () => {
    for (const s of ['oversold', 'low_fair', 'high_fair', 'overvalued', 'insufficient']) {
      expect(PE_STATE_LABEL[s]).toBeTruthy();
    }
    for (const c of ['dividend', 'bluechip', 'growth'] as const) {
      expect(CATEGORY_LABEL[c]).toBeTruthy();
    }
  });

  it('categoryOf 归一化非法类别', () => {
    expect(categoryOf('dividend')).toBe('dividend');
    expect(categoryOf('whatever')).toBe('bluechip');
  });

  it('格式化工具', () => {
    expect(fmtPct(0.125)).toBe('12.5%');
    expect(fmtPct(null)).toBe('—');
    expect(fmtMoney(500000)).toBe('500,000');
    expect(fmtMoney(null)).toBe('—');
  });

  it('validateWizardInput 拦截清空/越界输入(与后端 gt=0, ge=5 le=8 对齐)', () => {
    // 输入框清空时 Number('') === 0, 误输入字母时 === NaN
    expect(validateWizardInput(0, 8)).toBeTruthy();
    expect(validateWizardInput(NaN, 8)).toBeTruthy();
    expect(validateWizardInput(-1, 8)).toBeTruthy();
    expect(validateWizardInput(500000, 0)).toBeTruthy();
    expect(validateWizardInput(500000, 4)).toBeTruthy();
    expect(validateWizardInput(500000, 9)).toBeTruthy();
    expect(validateWizardInput(500000, 8)).toBeNull();
    expect(validateWizardInput(10000, 5)).toBeNull();
  });

  it('pydanticErrorDetail 透出首个验证错误字段', () => {
    const errors = [
      {type: 'greater_than', loc: ['body', 'total_capital'],
       msg: 'Input should be greater than 0', input: 0},
    ];
    expect(pydanticErrorDetail(errors))
      .toBe('total_capital: Input should be greater than 0');
    expect(pydanticErrorDetail(null)).toBeNull();
    expect(pydanticErrorDetail('随便')).toBeNull();
    expect(pydanticErrorDetail([])).toBeNull();
  });
});
