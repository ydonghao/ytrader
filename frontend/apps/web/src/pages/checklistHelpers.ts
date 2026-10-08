/** 买入体检页纯工具(日期复检提醒等)。 */
export function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.floor((Date.now() - t) / 86400000);
}

export function formatDaysAgo(iso: string | null | undefined): string {
  const d = daysSince(iso);
  if (d === null) return '';
  if (d <= 0) return '今天';
  if (d === 1) return '1 天前';
  if (d < 30) return `${d} 天前`;
  if (d < 365) return `${Math.floor(d / 30)} 个月前`;
  return `${Math.floor(d / 365)} 年前`;
}
