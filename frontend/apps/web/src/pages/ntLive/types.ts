/**
 * 国家队「实时全景」共享类型 + 工具(与后端 nt_snapshot 输出对齐)。
 */

export interface SnapshotMeta {
  title: string;
  version: string;
  update_time: string;
  data_period: string;
  total_stocks: number;
  total_holdings: number;
  total_value_yi: number;
  total_value_display: string;
  market_status: string;
  data_integrity_note: string;
}

export interface TeamSummary {
  team: string;
  team_type: string;
  category: string;
  color: string;
  stock_count: number;
  total_holding_value: number;
  total_holding_value_display: string;
}
export interface SectorSummary {sector: string; total_value: number; count: number;}

export interface StockHolder {
  entity: string; team: string; category: string; team_type: string;
  shares: number; ratio: number; holding_value_yi: number;
}
export interface StockSummary {
  code: string; name: string; industry: string; sector: string;
  price: number; change_pct: number; pe_ttm: number; pb: number;
  mcap_yi: number; float_mcap_yi: number; amount_wan: number;
  turnover_pct: number; volume_ratio: number; amplitude: number;
  high_52w: number; low_52w: number; week_52_position: number;
  chg_5d: number; chg_20d: number; max_drawdown_20d: number;
  total_holding_value: number; holders: StockHolder[];
}
export interface HoldingDetail extends StockSummary {
  entity: string; team: string; team_type: string; category: string;
  shares: number; ratio: number; ranking: number; holding_value_yi: number;
  data_source: {holdings: string; quote: string; holding_value: string};
}
export interface Insight {type: string; level: string; title: string; detail: string;}
export interface EntityInfo {
  category: string; color: string; type: string; desc: string;
  has_holdings: boolean; total_holding_value: number;
}

export interface Snapshot {
  meta: SnapshotMeta;
  national_team_entities: Record<string, EntityInfo>;
  team_summary: TeamSummary[];
  sector_summary: SectorSummary[];
  stock_summary: StockSummary[];
  holdings_detail: HoldingDetail[];
  industry_team_matrix: Record<string, number>;
  insights: Insight[];
}

export interface EtfItem {
  code: string; name: string; index: string; category: string; note: string;
  first_holder_entity: string; first_holder_share_pct: number;
  first_holder_value_yi: number; first_holder_data_source: string;
  price: number; change_pct: number; amount_wan: number;
  shares_yi: number; total_value_yi: number; turnover_pct: number;
  volume_ratio: number; high_52w: number; low_52w: number;
  turnover_ratio_pct: number; prev_shares_yi: number | null;
  shares_change_yi: number | null; shares_change_pct: number | null;
  avg_20d_change_yi: number | null; change_multiple: number | null;
  history_count: number; data_source: string;
}
export interface EtfSnapshot {
  etfs: EtfItem[];
  signals: Insight[];
  total_value_yi: number;
  history_dates: string[];
  coverage: string;
}
export interface KlinePoint {date: string; open: number; close: number; high: number; low: number;}

// ── 工具 ──
export const fmtYi = (v: number) => {
  if (!v && v !== 0) return '-';
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(2) + '万亿';
  return v.toFixed(1) + '亿';
};
export const pct = (v: number, digits = 2) => (v >= 0 ? '+' : '') + v.toFixed(digits) + '%';
export const chgClass = (v: number) => (v >= 0 ? 'is-up' : 'is-down');

// 风格标签(PE 分档):价值/蓝筹/成长/高成长
export const styleTag = (pe: number): {label: string; cls: string} => {
  if (pe <= 0) return {label: '亏损', cls: 'nt-style-loss'};
  if (pe < 15) return {label: '价值', cls: 'nt-style-value'};
  if (pe < 25) return {label: '蓝筹', cls: 'nt-style-blue'};
  if (pe < 50) return {label: '成长', cls: 'nt-style-growth'};
  return {label: '高成长', cls: 'nt-style-hyper'};
};

export const INSIGHT_META: Record<string, {icon: string; cls: string}> = {
  warn: {icon: '⚠️', cls: 'nt-insight-warn'},
  alert: {icon: '🔴', cls: 'nt-insight-alert'},
  info: {icon: 'ℹ️', cls: 'nt-insight-info'},
  opportunity: {icon: '💡', cls: 'nt-insight-opp'},
};
