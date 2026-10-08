/**
 * 自动建组合(课程组合)——类型 + 课程23常量 + API 封装。
 * 配比常量与后端 course_allocation.RISK_PROFILES 镜像, 不得单方面修改。
 */
import {getApiBase} from './api';

export type Category = 'dividend' | 'bluechip' | 'growth';

export interface ProfileWeights {
  dividend: number;
  bluechip: number;
  growth: number;
}

export const RISK_PROFILES: ReadonlyArray<{
  key: 'defensive' | 'balanced' | 'aggressive' | 'radical';
  label: string;
  desc: string;
  weights: ProfileWeights;
}> = [
  {key: 'defensive', label: '防御型', desc: '资产保值为主, 跑赢通胀即可',
   weights: {dividend: 0.7, bluechip: 0.3, growth: 0.0}},
  {key: 'balanced', label: '稳健型', desc: '本金相对安全下取市场平均回报',
   weights: {dividend: 0.5, bluechip: 0.4, growth: 0.1}},
  {key: 'aggressive', label: '积极型', desc: '高于市场平均, 能容忍短期波动',
   weights: {dividend: 0.3, bluechip: 0.5, growth: 0.2}},
  {key: 'radical', label: '激进型', desc: '追求数倍回报, 可接受大幅回撤',
   weights: {dividend: 0.0, bluechip: 0.3, growth: 0.7}},
];

export type RiskProfile = (typeof RISK_PROFILES)[number];

export const CATEGORY_LABEL: Record<Category, string> = {
  dividend: '红利股',
  bluechip: '蓝筹股',
  growth: '创新类',
};

export const PE_STATE_LABEL: Record<string, string> = {
  oversold: '超跌',
  low_fair: '合理偏低',
  high_fair: '合理偏高',
  overvalued: '虚高',
  insufficient: '数据不足',
};

export const PE_STATE_TONE: Record<string, string> = {
  oversold: 'success',
  low_fair: 'accent',
  high_fair: 'warning',
  overvalued: 'danger',
  insufficient: 'muted',
};

export interface LadderRung {
  rung_index: number;
  drop_pct: number;
  price_level: number;
  amount: number;
  executed: boolean;
  executed_at?: string | null;
  fill_price?: number | null;
  fill_shares?: number | null;
}

export interface PeBand {
  mean?: number;
  std?: number;
  z_score?: number;
  state: string;
  sample_count: number;
  current_pe?: number;
}

export interface PlanLeg {
  symbol: string;
  name: string;
  category: Category;
  target_weight: number;
  target_amount: number;
  pe_band: PeBand | null;
  entry_plan: LadderRung[];
  current_price?: number | null;
}

export interface Candidate {
  symbol: string;
  dv_ttm?: number | null;
  total_mv?: number | null;
  revenue_growth?: number | null;
  payout_ratio?: number | null;
}

export interface GenerateResponse {
  risk_profile: string;
  profile_weights: ProfileWeights;
  total_capital: number;
  investable_capital: number;
  slots: Record<string, number>;
  legs: PlanLeg[];
  warnings: string[];
  candidates: Record<Category, Candidate[]>;
}

export interface PlanSummary {
  id: number;
  name: string;
  risk_profile: string;
  total_capital: number;
  cash_reserve_pct: number;
  target_stock_count: number;
  status: string;
  notes: string;
  created_at?: string | null;
}

export interface DetailLeg extends PlanLeg {
  id: number;
  shares: number;
  invested_amount: number;
  avg_cost: number;
}

export interface PlanDetail extends PlanSummary {
  legs: DetailLeg[];
}

export interface Advice {
  symbol: string;
  code: 'BUY_RUNG' | 'TRIM' | 'BREAKDOWN' | 'HOLD';
  message: string;
  amount?: number | null;
  shares?: number | null;
}

export interface ReviewResponse {
  advices: Advice[];
  progress_invested: number;
  progress_target: number;
  cash_remaining: number;
  category_actual: Record<string, number>;
  category_target: Record<string, number>;
  dividend_yield_weighted?: number | null;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${getApiBase()}/course-portfolio${path}`, {
    headers: {'Content-Type': 'application/json'},
    ...init,
  });
  let body: {code?: number; msg?: string; detail?: string; data?: T} | null =
    null;
  try {
    body = await resp.json();
  } catch {
    // 后端不可达时开发代理返回纯文本(如 "Error occurred while trying to
    // proxy..."), 不能让它以 JSON 解析错误的形式抛出
  }
  if (!resp.ok || !body || body.code !== 0) {
    const detail = pydanticErrorDetail(body?.data);
    throw new Error(
      detail ? `${body?.msg ?? '参数验证失败'}: ${detail}`
        : body?.msg || body?.detail ||
          (resp.ok ? '响应不是有效 JSON' : `HTTP ${resp.status}`),
    );
  }
  return body.data as T;
}

/**
 * 提交前校验向导输入, 与后端 GenerateRequest/SaveRequest 的约束
 * (total_capital gt=0, stock_count ge=5 le=8) 对齐。
 * 输入框清空时 Number('') === 0, 误输入字母时 === NaN, 均拦截。
 * 返回中文错误提示, 合法返回 null。
 */
export function validateWizardInput(
  capital: number, stockCount: number,
): string | null {
  if (!Number.isFinite(capital) || capital <= 0) {
    return '总资金必须是大于 0 的数字';
  }
  if (!Number.isInteger(stockCount) || stockCount < 5 || stockCount > 8) {
    return '股票数量需为 5–8 的整数';
  }
  return null;
}

/**
 * 从后端 422 响应的 data( RequestValidationError.errors() 数组)中
 * 取第一条拼成 "字段: 消息", 让笼统的"参数验证失败"能定位到字段。
 * 形状不符(非数组/空/缺 loc+msg)返回 null。
 */
export function pydanticErrorDetail(data: unknown): string | null {
  if (!Array.isArray(data) || !data.length) {
    return null;
  }
  const first = data[0] as {loc?: unknown; msg?: unknown};
  if (typeof first?.msg !== 'string' || !Array.isArray(first?.loc)) {
    return null;
  }
  const field = first.loc.slice(1).join('.');  // 去掉 'body' 前缀
  return field ? `${field}: ${first.msg}` : first.msg;
}

export function categoryOf(c: string): Category {
  return c === 'dividend' || c === 'bluechip' || c === 'growth'
    ? c : 'bluechip';
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v == null ? '—' : `${(v * 100).toFixed(digits)}%`;
}

export function fmtMoney(v: number | null | undefined): string {
  return v == null ? '—' : v.toLocaleString('zh-CN', {maximumFractionDigits: 0});
}
