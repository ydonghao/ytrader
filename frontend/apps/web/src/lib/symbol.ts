/**
 * 股票代码归一：裸 6 位 A 股代码 → sh/sz 前缀（DB/API 统一口径）；
 * 已带前缀的输入幂等。与后端 boom service.to_prefixed 同规则：
 * 6/9/5 开头 → sh，其余（0/3）→ sz。北交所(bj)/港股(5位)等非此口径
 * 的输入原样返回，交由接口层判无数据。
 */
export const ensurePrefixed = (s: string): string => {
  if (!/^\d{6}$/.test(s)) return s;
  return (/^[695]/.test(s) ? 'sh' : 'sz') + s;
};
