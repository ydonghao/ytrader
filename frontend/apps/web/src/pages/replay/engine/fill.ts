import type {AccountState, OrderReq, Position, Trade} from '../types';

export interface FillCtx {
  date: string;
  close: number;
  prevClose: number;
  name?: string; // 用于识别 ST
}

export type FillResult =
  | {ok: true; cash: number; positions: Position[]; trade: Trade}
  | {ok: false; error: string};

export function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

/** 涨跌停幅度：ST 5% / 创业·科创 20% / 北交 30% / 主板 10%。 */
export function priceLimitRatio(symbol: string, name?: string): number {
  if (name && name.toUpperCase().includes('ST')) return 0.05;
  const code = symbol.replace(/^[a-z]{2}/i, ''); // 剥离 sh/sz/bj 前缀
  if (/^(300|301|688|689)/.test(code)) return 0.2;
  if (/^(8|4|92)/.test(code)) return 0.3;
  return 0.1;
}

export function limitPrices(prevClose: number, ratio: number): {up: number; down: number} {
  return {up: round2(prevClose * (1 + ratio)), down: round2(prevClose * (1 - ratio))};
}

export function commission(amount: number): number {
  return Math.max(5, round2(amount * 0.00025));
}

/** 印花税（仅卖出）：2023-08-28 起 0.05%，此前 0.1%。 */
export function stampTax(amount: number, date: string): number {
  const rate = date >= '2023-08-28' ? 0.0005 : 0.001;
  return round2(amount * rate);
}

export function tryFill(acct: AccountState, req: OrderReq, ctx: FillCtx): FillResult {
  const {date, close, prevClose} = ctx;
  if (!Number.isInteger(req.shares) || req.shares <= 0) {
    return {ok: false, error: '股数须为正整数'};
  }
  // A 股口径：买入须 100 整数倍；卖出允许零股（如实盘零股申报）
  if (req.side === 'buy' && req.shares % 100 !== 0) {
    return {ok: false, error: '买入股数须为100的整数倍'};
  }
  const {up, down} = limitPrices(prevClose, priceLimitRatio(req.symbol, ctx.name));
  const amount = round2(close * req.shares);

  if (req.side === 'buy') {
    if (close >= up) return {ok: false, error: '涨停，无法买入'};
    const fee = commission(amount);
    const cost = round2(amount + fee);
    if (cost > acct.cash) return {ok: false, error: '资金不足'};
    const positions = [...acct.positions];
    const i = positions.findIndex((p) => p.symbol === req.symbol);
    if (i >= 0) {
      const p = positions[i];
      const shares = p.shares + req.shares;
      // 加仓：成本加权；buy_date 保留首次（T+1 口径宽松，文档记录）
      const cost_price = round2((p.cost_price * p.shares + close * req.shares) / shares);
      positions[i] = {...p, shares, cost_price};
    } else {
      positions.push({symbol: req.symbol, shares: req.shares, cost_price: close, buy_date: date});
    }
    return {
      ok: true,
      cash: round2(acct.cash - cost),
      positions,
      trade: {trade_date: date, symbol: req.symbol, side: 'buy', price: close, shares: req.shares, fee, tax: 0, note: req.note ?? null},
    };
  }

  // sell
  if (close <= down) return {ok: false, error: '跌停，无法卖出'};
  const i = acct.positions.findIndex((p) => p.symbol === req.symbol);
  if (i < 0) return {ok: false, error: '无持仓'};
  const p = acct.positions[i];
  if (p.shares < req.shares) return {ok: false, error: '持仓不足'};
  if (p.buy_date >= date) return {ok: false, error: 'T+1：今日买入明日才可卖出'};
  const fee = commission(amount);
  const tax = stampTax(amount, date);
  const positions = [...acct.positions];
  if (p.shares === req.shares) positions.splice(i, 1);
  else positions[i] = {...p, shares: p.shares - req.shares};
  return {
    ok: true,
    cash: round2(acct.cash + amount - fee - tax),
    positions,
    trade: {trade_date: date, symbol: req.symbol, side: 'sell', price: close, shares: req.shares, fee, tax, note: req.note ?? null},
  };
}
