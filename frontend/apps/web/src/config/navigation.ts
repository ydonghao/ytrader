/**
 * 导航单一数据源:侧栏菜单(Layout)与开始页速查(Start)共用。
 * 文案来源:docs/value-investing-loop.md;icon 为 components/icons.tsx 中 Icons 的 key。
 */
import type {IconName} from '../components/icons';

export interface NavItem {
  path: string;
  label: string;
  desc: string;
  icon: IconName;
  aliases?: string[];
  /** 所属工作流环节（六段 id 或 start/system），驱动页头工作流条 */
  stage?: string;
  /** 工作流上下游直达（菜单内 path），省略则该页无上下游按钮 */
  prev?: string;
  next?: string;
}

export interface NavGroup {
  id: string;
  title: string;
  defaultOpen: boolean;
  items: NavItem[];
}

export interface Scenario {
  id: string;
  question: string;
  answer: string;
  primary: string;
  links: {label: string; path: string}[];
}

export interface WorkflowStage {
  id: string;
  title: string;
  role: string;
  links: {label: string; path: string}[];
}

export const navGroups: NavGroup[] = [
  {
    id: 'start',
    title: '开始',
    defaultOpen: true,
    items: [
      {path: '/start', label: '开始', desc: '工作流导航与页面速查', icon: 'compass', aliases: ['指南', '帮助', '首页'], stage: 'start'},
      {path: '/dashboard', label: '工作台', desc: '账户资产与盈亏总览', icon: 'dashboard', stage: 'start'},
    ],
  },
  {
    id: 'market',
    title: '市场',
    defaultOpen: true,
    items: [
      {path: '/indices', label: '市场温度', desc: '温度计/水位/破净率择时', icon: 'globe', aliases: ['温度', '水位', '估值', '指数'], stage: 'market', next: '/screener'},
      {path: '/macro', label: '宏观政策', desc: '政策事件与宏观跟踪', icon: 'bank', stage: 'market'},
      {path: '/national-team', label: '国家队', desc: '汇金等席位动向全景', icon: 'shield', aliases: ['汇金', '席位'], stage: 'market'},
      {path: '/market', label: '行情快照', desc: '指数/ETF/港股蜡烛图看盘', icon: 'market', aliases: ['行情', '看盘', 'ETF', '港股'], stage: 'market'},
    ],
  },
  {
    id: 'research',
    title: '研究',
    defaultOpen: false,
    items: [
      {path: '/screener', label: '选股器', desc: '多条件筛选候选股', icon: 'funnel', stage: 'research', prev: '/indices', next: '/financial'},
      {path: '/financial', label: '财务分析', desc: '报表/质量/五法估值', icon: 'financial', aliases: ['估值', '五法', 'DCF'], stage: 'research', prev: '/screener', next: '/checklist'},
      {path: '/industry-analysis', label: '行业分析', desc: '景气热力图/资金流/强弱', icon: 'layers', aliases: ['热力图'], stage: 'research'},
      {path: '/earnings-radar', label: '财报雷达', desc: '财报季景气与事件', icon: 'radar', stage: 'research'},
      {path: '/compare', label: '标的对比', desc: '候选股 13 维并排', icon: 'compare', aliases: ['对比'], stage: 'research', next: '/checklist'},
      {path: '/notes', label: '研究笔记', desc: '按标的沉淀研究记录', icon: 'reports', stage: 'research'},
    ],
  },
  {
    id: 'decide',
    title: '决策',
    defaultOpen: false,
    items: [
      {path: '/checklist', label: '买入体检', desc: '买前清单与仓位建议', icon: 'checklist', aliases: ['体检', '建仓', '排雷'], stage: 'decide', prev: '/financial', next: '/thesis'},
      {path: '/course-portfolio', label: '自动建组合', desc: '按课程策略生成组合', icon: 'portfolio', stage: 'decide', prev: '/checklist'},
    ],
  },
  {
    id: 'hold',
    title: '持仓',
    defaultOpen: false,
    items: [
      {path: '/trading', label: '交易', desc: '下单与委托管理', icon: 'trading', stage: 'hold'},
      {path: '/thesis', label: '持仓体检', desc: '论点/复盘/组合体检', icon: 'pulse', aliases: ['论点', '卖出体检', '复盘'], stage: 'hold', next: '/replay'},
      {path: '/watchlist', label: '自选股', desc: '关注列表跟踪', icon: 'star', stage: 'hold'},
      {path: '/risk', label: '风险', desc: '持仓风险与组合压测', icon: 'risk', aliases: ['压测'], stage: 'hold'},
      {path: '/alerts', label: '预警', desc: '三源事件统一收件箱', icon: 'alerts', aliases: ['收件箱', '提醒'], stage: 'hold'},
    ],
  },
  {
    id: 'review',
    title: '复盘',
    defaultOpen: false,
    items: [
      {path: '/replay', label: '时光机', desc: '回到历史日期复盘决策', icon: 'history', aliases: ['历史', '复盘'], stage: 'review', prev: '/thesis'},
      {path: '/lt-backtest', label: '回测实验室', desc: '长期策略回测与优化', icon: 'backtest', aliases: ['回测'], stage: 'review'},
      {path: '/analytics', label: '分析', desc: '交易与业绩统计', icon: 'analytics', stage: 'review'},
      {path: '/board', label: '看板', desc: '自定义数据看板', icon: 'layout', stage: 'review'},
      {path: '/perm-portfolio', label: '永久组合', desc: '永久组合跟踪', icon: 'infinity', stage: 'review'},
    ],
  },
  {
    id: 'system',
    title: '系统',
    defaultOpen: false,
    items: [
      {path: '/settings', label: '设置', desc: '系统与数据源配置', icon: 'settings', stage: 'system'},
      {path: '/system-logs', label: '系统日志', desc: '运行日志与数据健康', icon: 'terminal', aliases: ['数据健康'], stage: 'system'},
    ],
  },
];

export const scenarios: Scenario[] = [
  {
    id: 'market-level',
    question: '我想看现在市场贵不贵、该留几成仓',
    answer: '市场温度页:温度计Tab看五档温度 + 股债性价比 ERP 与历史分位 + 建议仓位水位;指数水位Tab看估值分位,破净率Tab看阶段性底部参考区。',
    primary: '/indices',
    links: [
      {label: '持仓页温度条', path: '/thesis'},
      {label: '宏观政策', path: '/macro'},
    ],
  },
  {
    id: 'screen-candidate',
    question: '我有一只候选股,怎么系统排查',
    answer: '财务分析页看五法估值(含 Reverse DCF 隐含预期)、质量分、护城河;买入体检排雷;对比页 13 维并排;笔记沉淀。',
    primary: '/financial',
    links: [
      {label: '买入体检排雷', path: '/checklist'},
      {label: '标的对比', path: '/compare'},
      {label: '研究笔记', path: '/notes'},
    ],
  },
  {
    id: 'buy-decision',
    question: '决定买了:买多少、怎么买',
    answer: '买入体检给仓位建议档位 + 三档建仓计划;登记论点自动抓快照;假设阈值可用 16 季回测校准。',
    primary: '/checklist',
    links: [
      {label: '登记论点', path: '/thesis'},
      {label: '自动建组合', path: '/course-portfolio'},
    ],
  },
  {
    id: 'holding',
    question: '持有期间要盯什么',
    answer: '全部自动化:财报重估、估值到价、每日排雷都推送到预警中心统一收件箱,论点事件可标已读,不用盯盘。',
    primary: '/alerts',
    links: [
      {label: '论点重估记录', path: '/thesis'},
      {label: '组合风险压测', path: '/risk'},
    ],
  },
  {
    id: 'sell-decision',
    question: '考虑卖出时怎么决策',
    answer: '持仓体检 → 点论点卡片 → 卖出体检四区报告:假设破没破 / 估值到没到 / 基本面变化 / 卖出三问;之后记录决策与归因。',
    primary: '/thesis',
    links: [{label: '拉同行对照', path: '/compare'}],
  },
  {
    id: 'review-loop',
    question: '定期复盘看什么',
    answer: '持仓体检复盘区:盈亏归因 + 卖飞统计 + 组合体检(集中度/相关性/四窗压测)+ 股息日历 + 研究管道堵点。',
    primary: '/thesis',
    links: [
      {label: '时光机回到过去', path: '/replay'},
      {label: '策略回测', path: '/lt-backtest'},
      {label: '业绩统计', path: '/analytics'},
    ],
  },
  {
    id: 'data-views',
    question: '想看数据:账户、业绩、自定义各去哪页',
    answer: '工作台=账户资产与盈亏总览;分析=交易与业绩统计(胜率/回撤/月度);看板=自选指标卡片自定义布局。',
    primary: '/dashboard',
    links: [
      {label: '业绩统计', path: '/analytics'},
      {label: '自定义看板', path: '/board'},
    ],
  },
];

export const workflowStages: WorkflowStage[] = [
  {
    id: 'market',
    title: '看市场',
    role: '温度计定仓位水位',
    links: [
      {label: '市场温度', path: '/indices'},
      {label: '指数水位', path: '/indices'},
      {label: '宏观', path: '/macro'},
      {label: '国家队', path: '/national-team'},
      {label: '行情快照', path: '/market'},
    ],
  },
  {
    id: 'research',
    title: '选股',
    role: '筛选候选并深度研究',
    links: [
      {label: '选股器', path: '/screener'},
      {label: '财务分析', path: '/financial'},
      {label: '行业分析', path: '/industry-analysis'},
      {label: '财报雷达', path: '/earnings-radar'},
    ],
  },
  {
    id: 'decide',
    title: '买前体检',
    role: '仓位建议、阈值校准、登记论点',
    links: [
      {label: '买入体检', path: '/checklist'},
      {label: '自动建组合', path: '/course-portfolio'},
    ],
  },
  {
    id: 'hold',
    title: '持有',
    role: '自动重估与事件推送',
    links: [
      {label: '预警收件箱', path: '/alerts'},
      {label: '风险压测', path: '/risk'},
      {label: '自选股', path: '/watchlist'},
    ],
  },
  {
    id: 'sell',
    title: '卖出',
    role: '卖出体检四区报告',
    links: [
      {label: '持仓体检', path: '/thesis'},
      {label: '同行对照', path: '/compare'},
    ],
  },
  {
    id: 'review',
    title: '复盘',
    role: '归因、压测、回到过去验证',
    links: [
      {label: '复盘区', path: '/thesis'},
      {label: '时光机', path: '/replay'},
      {label: '回测实验室', path: '/lt-backtest'},
      {label: '业绩统计', path: '/analytics'},
      {label: '看板', path: '/board'},
    ],
  },
];

export const CALIBRATION_NOTES: string[] = [
  'ROE 一律 TTM(当期累计 + 上年年报 − 去年同期);同比基期 = 去年同一报告期',
  '估值内在值多为公司总值,跨口径比较一律用 upside 比率(内在/市值 − 1)',
  '温度计历史分位为运行分位(截至当日序列内),无未来数据',
  'DCF 结论看敏感性区间,不看单点;行业资金流源只有当日快照,断档无法回填',
];

export interface FlowContext {
  stageTitle: string;
  prev?: {path: string; label: string};
  next?: {path: string; label: string};
}

const itemByPath = new Map(navGroups.flatMap((g) => g.items.map((i) => [i.path, i] as const)));

/** 页头工作流条数据:path → 环节名 + 上下游直达(无 stage 的页面返回 null) */
export function getFlowContext(path: string): FlowContext | null {
  const item = itemByPath.get(path);
  if (!item?.stage) return null;
  const group = navGroups.find((g) => g.id === item.stage) ?? navGroups.find((g) => g.items.includes(item));
  const toRef = (p?: string) => {
    if (!p) return undefined;
    const target = itemByPath.get(p);
    return target ? {path: p, label: target.label} : undefined;
  };
  return {stageTitle: group?.title ?? item.stage, prev: toRef(item.prev), next: toRef(item.next)};
}
