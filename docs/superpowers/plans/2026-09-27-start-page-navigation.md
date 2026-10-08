# 「开始」页与导航体系重组 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/start` 工作流导航首页作为落地页,菜单按价值投资工作流重组为 6 组并为每项加副标题,消灭 `/checklist` 幽灵入口,并以"菜单↔路由双向校验"测试防回归。

**Architecture:** 单一数据源 `src/config/navigation.ts`(菜单分组+副标题+场景卡+工作流分层),`Layout.tsx` 与 `Start.tsx` 共同消费;路由仍集中定义在 `App.tsx`,测试用源码正则提取路由清单做双向校验(不导入 App.tsx,避免页面组件顶层副作用在 node 测试环境炸裂)。

**Tech Stack:** React 18 + TypeScript + react-router-dom v7 + rsbuild;测试 vitest(environment: node,纯逻辑测试,无 jsdom——**不写 DOM 渲染测试**)。

**Spec:** `docs/superpowers/specs/2026-09-27-start-page-navigation-design.md`

## Global Constraints

- 工作目录:`/home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web`(测试/构建命令都在此目录跑)。
- 测试命令:`pnpm vitest run <file>` 跑单文件;`pnpm test` 全量;`pnpm lint`;`pnpm build`。
- vitest 是 node 环境:所有 `.test.ts` 只测数据与纯函数,**不渲染组件、不导入页面组件**。
- 菜单项 label 除两处外全部保持现状(用户肌肉记忆):`/dashboard` label「总览」→「工作台」、`/financial` label「财务报表」→「财务分析」——这两处是 spec 明确决策。
- 副标题文案 ≤ 16 个中文字符(侧栏 220px,文本区约 160px,CSS ellipsis 兜底)。
- 纯前端改动:不动后端、不动数据库、不改任何现有页面(`pages/` 下除新增 Start 外不碰)。
- 样式一律复用现有 CSS 令牌(`var(--radius-sm)`、`var(--color-text-*)`、`var(--color-accent)` 等,见 Layout.css/ui.css),不硬编码色值。
- 提交信息用中文、`feat(nav):` / `test(nav):` / `feat(start):` 前缀,与仓库近期风格一致。
- 工作区已有一个无关的改动文件 `backend/.news_backfill_progress.json`——**每次 commit 只 add 本计划明确列出的文件**,绝不 `git add -A`。

---

### Task 1: navigation.ts 单一数据源 + 数据完整性测试

**Files:**
- Create: `src/config/navigation.ts`
- Test: `src/config/__tests__/navigation.test.ts`

**Interfaces:**
- Consumes: 无(纯数据)。
- Produces(Task 4/5 依赖的确切签名):
  - `navGroups: NavGroup[]`,其中 `NavGroup {id: string; title: string; defaultOpen: boolean; items: NavItem[]}`、`NavItem {path: string; label: string; desc: string; icon: string; aliases?: string[]}`(`icon` 是 `components/icons.tsx` 中 `Icons` 对象的 key 字符串,不是 ReactNode)
  - `scenarios: Scenario[]`,`Scenario {id: string; question: string; answer: string; primary: string; links: {label: string; path: string}[]}`
  - `workflowStages: WorkflowStage[]`,`WorkflowStage {id: string; title: string; role: string; links: {label: string; path: string}[]}`
  - `CALIBRATION_NOTES: string[]`(口径速记文案)

- [ ] **Step 1: 写失败的测试**

创建 `src/config/__tests__/navigation.test.ts`:

```ts
import {describe, expect, it} from 'vitest';
import {navGroups, scenarios, workflowStages, CALIBRATION_NOTES} from '../navigation';

const allItems = navGroups.flatMap((g) => g.items);
const allPaths = allItems.map((i) => i.path);

describe('navigation 配置完整性', () => {
  it('菜单项 path 唯一且 desc/label/icon 非空', () => {
    expect(new Set(allPaths).size).toBe(allPaths.length);
    for (const item of allItems) {
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.desc.length).toBeGreaterThan(0);
      expect(item.desc.length).toBeLessThanOrEqual(16);
      expect(item.icon.length).toBeGreaterThan(0);
    }
  });

  it('分组 id 唯一,至少两组默认展开', () => {
    const ids = navGroups.map((g) => g.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(navGroups.filter((g) => g.defaultOpen).length).toBeGreaterThanOrEqual(2);
  });

  it('幽灵入口已转正:/checklist 在菜单中', () => {
    expect(allPaths).toContain('/checklist');
    expect(allPaths).toContain('/start');
  });

  it('场景卡:primary 与 links 均指向菜单内路径', () => {
    expect(scenarios.length).toBe(6);
    for (const s of scenarios) {
      expect(allPaths).toContain(s.primary);
      for (const link of s.links) {
        expect(allPaths).toContain(link.path);
      }
    }
  });

  it('工作流六层:标题/职责非空,链接均指向菜单内路径', () => {
    expect(workflowStages.map((s) => s.id)).toEqual(
      ['market', 'research', 'decide', 'hold', 'sell', 'review']);
    for (const stage of workflowStages) {
      expect(stage.title.length).toBeGreaterThan(0);
      expect(stage.role.length).toBeGreaterThan(0);
      expect(stage.links.length).toBeGreaterThan(0);
      for (const link of stage.links) {
        expect(allPaths).toContain(link.path);
      }
    }
  });

  it('口径速记非空', () => {
    expect(CALIBRATION_NOTES.length).toBeGreaterThanOrEqual(4);
    for (const note of CALIBRATION_NOTES) {
      expect(note.length).toBeGreaterThan(5);
    }
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pnpm vitest run src/config`
Expected: FAIL,`Failed to resolve import ../navigation`(文件不存在)。

- [ ] **Step 3: 写 navigation.ts 完整实现**

创建 `src/config/navigation.ts`(副标题/场景/工作流文案提炼自 `docs/value-investing-loop.md`):

```ts
/**
 * 导航单一数据源:侧栏菜单(Layout)与开始页速查(Start)共用。
 * 文案来源:docs/value-investing-loop.md;icon 为 components/icons.tsx 中 Icons 的 key。
 */
export interface NavItem {
  path: string;
  label: string;
  desc: string;
  icon: string;
  aliases?: string[];
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
      {path: '/start', label: '开始', desc: '工作流导航与页面速查', icon: 'dashboard', aliases: ['指南', '帮助', '首页']},
      {path: '/dashboard', label: '工作台', desc: '账户资产与盈亏总览', icon: 'dashboard'},
    ],
  },
  {
    id: 'market',
    title: '市场',
    defaultOpen: true,
    items: [
      {path: '/market', label: '行情', desc: '个股行情快照', icon: 'market'},
      {path: '/indices', label: '指数', desc: '市场温度与估值水位', icon: 'globe', aliases: ['温度', '水位', '估值']},
      {path: '/macro', label: '宏观政策', desc: '政策事件与宏观跟踪', icon: 'analytics'},
      {path: '/national-team', label: '国家队', desc: '汇金等席位动向全景', icon: 'analytics', aliases: ['汇金', '席位']},
    ],
  },
  {
    id: 'research',
    title: '选股研究',
    defaultOpen: false,
    items: [
      {path: '/financial', label: '财务分析', desc: '报表/质量/五法估值', icon: 'financial', aliases: ['估值', '五法', 'DCF']},
      {path: '/checklist', label: '买入体检', desc: '买前清单与仓位建议', icon: 'strategies', aliases: ['体检', '建仓', '排雷']},
      {path: '/earnings-radar', label: '财报雷达', desc: '财报季景气与事件', icon: 'analytics'},
      {path: '/screener', label: '选股器', desc: '多条件筛选候选股', icon: 'strategies'},
      {path: '/industry-analysis', label: '行业分析', desc: '破净率/景气/资金流', icon: 'analytics', aliases: ['热力图']},
      {path: '/compare', label: '标的对比', desc: '候选股 13 维并排', icon: 'strategies', aliases: ['对比']},
      {path: '/notes', label: '研究笔记', desc: '按标的沉淀研究记录', icon: 'reports'},
      {path: '/course-portfolio', label: '自动建组合', desc: '按课程策略生成组合', icon: 'portfolio'},
      {path: '/reports', label: '报告', desc: '券商研报聚合', icon: 'reports'},
    ],
  },
  {
    id: 'position',
    title: '持仓与交易',
    defaultOpen: false,
    items: [
      {path: '/trading', label: '交易', desc: '下单与委托管理', icon: 'trading'},
      {path: '/thesis', label: '持仓体检', desc: '论点/温度卡/复盘', icon: 'portfolio', aliases: ['论点', '卖出体检', '复盘']},
      {path: '/watchlist', label: '自选股', desc: '关注列表跟踪', icon: 'star'},
      {path: '/risk', label: '风险', desc: '持仓风险与组合压测', icon: 'risk', aliases: ['压测']},
      {path: '/alerts', label: '预警', desc: '三源事件统一收件箱', icon: 'alerts', aliases: ['收件箱', '提醒']},
    ],
  },
  {
    id: 'review',
    title: '复盘与回测',
    defaultOpen: false,
    items: [
      {path: '/lt-backtest', label: '回测实验室', desc: '长期策略回测与优化', icon: 'backtest', aliases: ['回测']},
      {path: '/replay', label: '时光机', desc: '回到历史日期复盘决策', icon: 'star', aliases: ['历史', '复盘']},
      {path: '/perm-portfolio', label: '永久组合', desc: '永久组合跟踪', icon: 'portfolio'},
      {path: '/analytics', label: '分析', desc: '交易与业绩统计', icon: 'analytics'},
      {path: '/board', label: '看板', desc: '自定义数据看板', icon: 'dashboard'},
    ],
  },
  {
    id: 'system',
    title: 'AI / 系统',
    defaultOpen: false,
    items: [
      {path: '/ai-workspace/trader', label: 'AI交易助手', desc: 'AI 对话交易工作台', icon: 'intel'},
      {path: '/settings', label: '设置', desc: '系统与数据源配置', icon: 'settings'},
      {path: '/system-logs', label: '系统日志', desc: '运行日志与数据健康', icon: 'terminal', aliases: ['数据健康']},
    ],
  },
];

export const scenarios: Scenario[] = [
  {
    id: 'market-level',
    question: '我想看现在市场贵不贵、该留几成仓',
    answer: '持仓体检页顶部温度卡:五档温度 + 股债性价比 ERP 与历史分位 + 建议仓位水位;可展开 16 年回测曲线。',
    primary: '/thesis',
    links: [
      {label: '指数估值水位', path: '/indices'},
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
];

export const workflowStages: WorkflowStage[] = [
  {
    id: 'market',
    title: '看市场',
    role: '温度计定仓位水位',
    links: [
      {label: '温度卡', path: '/thesis'},
      {label: '指数水位', path: '/indices'},
      {label: '宏观', path: '/macro'},
      {label: '国家队', path: '/national-team'},
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
      {label: '研报', path: '/reports'},
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pnpm vitest run src/config`
Expected: PASS(6 个用例全绿)。

- [ ] **Step 5: Commit**

```bash
git add src/config/navigation.ts src/config/__tests__/navigation.test.ts
git commit -m "feat(nav): 导航单一数据源navigation.ts——6组28项含副标题/场景卡/工作流分层,数据完整性测试"
```

---

### Task 2: 菜单↔路由双向校验测试(此刻应为红)

**Files:**
- Test: `src/config/__tests__/routes.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `navGroups`。
- Produces: 无(纯测试)。约定:重定向路径豁免清单 `REDIRECT_PATHS = ['/', '/ai-chat', '/t-trading', '/agent-config']`(均为 `Navigate` 重定向,无页面)。

- [ ] **Step 1: 写测试(用源码正则提取 App.tsx 路由,不导入 App.tsx——避免页面组件顶层副作用在 node 环境崩溃)**

创建 `src/config/__tests__/routes.test.ts`:

```ts
import {readFileSync} from 'node:fs';
import {describe, expect, it} from 'vitest';
import {navGroups} from '../navigation';

/** 从 App.tsx 源码提取 <Route path="..."> 清单(App.tsx 中 path 均为双引号字面量) */
function extractRoutePaths(): string[] {
  const source = readFileSync(new URL('../../App.tsx', import.meta.url), 'utf-8');
  const matches = [...source.matchAll(/<Route\s+path="([^"]+)"/g)];
  return matches.map((m) => m[1]);
}

/** 重定向路由(Navigate,无页面)与菜单无关,显式豁免 */
const REDIRECT_PATHS = ['/', '/ai-chat', '/t-trading', '/agent-config'];

const menuPaths = navGroups.flatMap((g) => g.items.map((i) => i.path));
const routePaths = extractRoutePaths();

describe('菜单 ↔ 路由双向校验', () => {
  it('护栏:从 App.tsx 提取到足够多路由(正则失配时此处先红)', () => {
    expect(routePaths.length).toBeGreaterThanOrEqual(27);
  });

  it('每个菜单项都有对应路由(无死链)', () => {
    const missing = menuPaths.filter((p) => !routePaths.includes(p));
    expect(missing).toEqual([]);
  });

  it('每条页面路由都有菜单入口或显式豁免(无幽灵页面)', () => {
    const orphans = routePaths.filter(
      (p) => !menuPaths.includes(p) && !REDIRECT_PATHS.includes(p)
    );
    expect(orphans).toEqual([]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败(预期的红:App.tsx 还没有 /start 路由)**

Run: `pnpm vitest run src/config/__tests__/routes.test.ts`
Expected: FAIL —— 「每个菜单项都有对应路由」用例报 `missing` 包含 `'/start'`(Task 3 实现后转绿)。其余两个用例应 PASS。

---

### Task 3: App.tsx 挂载 /start 路由(让 Task 2 转绿)

**Files:**
- Modify: `src/App.tsx`(第 11 行 import 区、第 56-58 行 Routes 区)

**Interfaces:**
- Consumes: 无(`Start` 组件 Task 5 才实现,本任务先建占位会破坏"无占位符"原则——因此本任务直接创建最终版 `src/pages/Start.tsx` 骨架?**不**:调整顺序,本任务只改路由并创建一个最小的、可运行的 Start 页面(标题+一句话),Task 5 把它扩成完整四段。这样每步都可构建、可演示。)
- Produces: `/start` 路由存在;`/` 重定向到 `/start`。

- [ ] **Step 1: 创建最小可用的 Start 页面**

创建 `src/pages/Start.tsx`:

```tsx
import React from 'react';
import {PageHeader} from '../components/ui';

export const Start: React.FC = () => (
  <div className="page-container">
    <PageHeader
      title="开始"
      subtitle="A股价值投资工作台:从判断市场贵贱到卖出复盘的完整闭环"
    />
    <p style={{color: 'var(--color-text-secondary)'}}>工作流导航建设中(见 Task 5)。</p>
  </div>
);
```

注意:若其他页面没有统一的 `page-container` 类,以 `pages/Watchlist.tsx` 顶层容器类名为准抄一个,保证页边距一致(grep `className="page` 确认)。

- [ ] **Step 2: 修改 App.tsx**

在 import 区(`import {Dashboard} from './pages/Dashboard';` 之后)加:

```tsx
import {Start} from './pages/Start';
```

Routes 区首两行改为:

```tsx
<Route path="/" element={<Navigate to="/start" replace />} />
<Route path="/start" element={<Start />} />
```

(原 `<Route path="/" element={<Navigate to="/dashboard" replace />} />` 行被替换;`/dashboard` 路由保持不变。)

- [ ] **Step 3: 跑 Task 2 测试确认转绿**

Run: `pnpm vitest run src/config`
Expected: PASS(含 routes.test.ts 三个用例)。

- [ ] **Step 4: 类型与构建验证**

Run: `pnpm build`
Expected: 构建成功,无类型错误。

- [ ] **Step 5: Commit**

```bash
git add src/App.tsx src/pages/Start.tsx src/config/__tests__/routes.test.ts
git commit -m "feat(start): 挂载/start路由并设为落地页(/重定向改指/start),菜单路由双向校验转绿"
```

(routes.test.ts 在 Task 2 写就、此处才转绿,随本任务一并提交。)

---

### Task 4: Layout.tsx 改造——菜单从 navigation.ts 渲染 + 副标题 + 默认折叠

**Files:**
- Modify: `src/components/Layout.tsx`(第 9-83 行类型与 navGroups 定义、第 86-101 行状态初始化、第 122-154 行渲染)
- Modify: `src/components/Layout.css`(`.sidebar__item-label` 规则之后追加)

**Interfaces:**
- Consumes: Task 1 的 `navGroups`(结构见 Task 1 Produces);`Icons`(`components/icons.tsx`,key 见 navigation.ts 各项 `icon` 字段)。
- Produces: 侧栏渲染副标题;分组默认折叠状态由 `NavGroup.defaultOpen` 决定。

- [ ] **Step 1: 改 Layout.tsx**

1. 删除第 9-19 行本地 `NavItem`/`NavGroup` 接口与第 30-83 行内联 `navGroups` 数组,改为导入:

```tsx
import {navGroups} from '../config/navigation';
```

2. 折叠状态初始化(替换第 89 行):

```tsx
const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
  () => new Set(navGroups.filter((g) => !g.defaultOpen).map((g) => g.id))
);
```

3. `toggleGroup` 的参数语义从 title 改为 group.id(调用处同步改),渲染循环改用 `group.id` 作 key 与折叠判断:

```tsx
{navGroups.map((group) => (
  <div key={group.id} className="sidebar__group">
    {!collapsed && (
      <button
        className="sidebar__group-title"
        onClick={() => toggleGroup(group.id)}
      >
        <span>{group.title}</span>
        {collapsedGroups.has(group.id) ? Icon.chevronRight : Icon.chevronDown}
      </button>
    )}
    {!collapsedGroups.has(group.id) &&
      group.items.map((item) => {
        const isActive = location.pathname === item.path;
        return (
          <Link
            key={item.path}
            to={item.path}
            className={`sidebar__item ${isActive ? 'sidebar__item--active' : ''}`}
            title={collapsed ? `${item.label}——${item.desc}` : undefined}
          >
            <span className="sidebar__item-icon">
              {(Icons as Record<string, React.ReactNode>)[item.icon]}
            </span>
            {!collapsed && (
              <span className="sidebar__item-text">
                <span className="sidebar__item-label">{item.label}</span>
                <span className="sidebar__item-desc">{item.desc}</span>
              </span>
            )}
            {isActive && <span className="sidebar__item-indicator" />}
          </Link>
        );
      })}
  </div>
))}
```

- [ ] **Step 2: Layout.css 追加样式**

在 `.sidebar__item-label` 规则块后追加:

```css
/* Item text wrapper (label + desc stacked) */
.sidebar__item-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* Item description subtitle */
.sidebar__item-desc {
  font-size: 11px;
  line-height: 1.3;
  color: var(--color-text-tertiary);
  opacity: 0.75;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
```

- [ ] **Step 3: 验证**

Run: `pnpm test && pnpm lint`
Expected: 测试全绿(navigation/routes 均不受影响),lint 无新告警。

Run: `pnpm build`
Expected: 构建成功。

- [ ] **Step 4: Commit**

```bash
git add src/components/Layout.tsx src/components/Layout.css
git commit -m "feat(nav): 侧栏改渲染navigation.ts——6组28项+每项副标题常显+按defaultOpen默认折叠,折叠态title带描述"
```

---

### Task 5: Start 页完整四段(工作流地图/场景卡/速查表/口径速记)

**Files:**
- Create: `src/pages/Start.css`
- Modify: `src/pages/Start.tsx`(替换 Task 3 的最小版)

**Interfaces:**
- Consumes: Task 1 的 `navGroups, scenarios, workflowStages, CALIBRATION_NOTES`;`PageHeader` from `'../components/ui'`;`Link` from `'react-router-dom'`。
- Produces: 最终 `/start` 页面。

- [ ] **Step 1: 写 Start.css**

```css
/* Start page — workflow map / scenarios / cheat sheet */
.start-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.start-section-title {
  font-size: var(--text-md, 14px);
  font-weight: 600;
  color: var(--color-text-secondary);
  margin: 0 0 10px;
}

/* 工作流地图:横向六层 */
.start-workflow {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px;
}
.start-stage {
  background: var(--color-bg-secondary, rgba(255, 255, 255, 0.03));
  border: 0.5px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius-md, 8px);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.start-stage__title {
  font-weight: 600;
  color: var(--color-text-primary);
}
.start-stage__role {
  font-size: 12px;
  color: var(--color-text-tertiary);
}
.start-stage__links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}
.start-stage__links a {
  font-size: 12px;
  color: var(--color-accent);
  text-decoration: none;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-accent-light);
}
.start-stage__links a:hover {
  background: var(--color-accent-hover);
}

/* 场景卡 */
.start-scenarios {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px;
}
.start-scenario {
  background: var(--color-bg-secondary, rgba(255, 255, 255, 0.03));
  border: 0.5px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius-md, 8px);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.start-scenario__question {
  font-weight: 600;
  color: var(--color-text-primary);
}
.start-scenario__answer {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}
.start-scenario__links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: auto;
}
.start-scenario__primary {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-accent);
  text-decoration: none;
  padding: 4px 12px;
  border-radius: var(--radius-sm);
  background: var(--color-accent-light);
}
.start-scenario__primary:hover {
  background: var(--color-accent-hover);
}
.start-scenario__secondary {
  font-size: 12px;
  color: var(--color-text-tertiary);
  text-decoration: none;
  padding: 4px 8px;
}
.start-scenario__secondary:hover {
  color: var(--color-text-secondary);
  text-decoration: underline;
}

/* 速查表 */
.start-filter {
  width: 100%;
  max-width: 360px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--color-text-primary);
  font-size: 13px;
}
.start-cheatsheet {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.start-cheatsheet-group h3 {
  font-size: 13px;
  color: var(--color-text-tertiary);
  margin: 0 0 6px;
}
.start-cheatsheet-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.start-cheatsheet-table td {
  padding: 6px 10px 6px 0;
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.05);
}
.start-cheatsheet-table a {
  color: var(--color-text-primary);
  text-decoration: none;
  font-weight: 500;
}
.start-cheatsheet-table a:hover {
  color: var(--color-accent);
}
.start-cheatsheet-desc {
  color: var(--color-text-tertiary);
}

/* 口径速记 */
.start-calibration {
  font-size: 13px;
  color: var(--color-text-secondary);
}
.start-calibration summary {
  cursor: pointer;
  color: var(--color-text-tertiary);
  font-weight: 500;
}
.start-calibration ul {
  margin: 8px 0 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
```

- [ ] **Step 2: 写完整 Start.tsx**

```tsx
import React, {useMemo, useState} from 'react';
import {Link} from 'react-router-dom';
import {PageHeader} from '../components/ui';
import {
  navGroups,
  scenarios,
  workflowStages,
  CALIBRATION_NOTES,
} from '../config/navigation';
import './Start.css';

const pathLabel = new Map(
  navGroups.flatMap((g) => g.items.map((i) => [i.path, i.label] as [string, string]))
);

export const Start: React.FC = () => {
  const [query, setQuery] = useState('');

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return navGroups;
    return navGroups
      .map((g) => ({
        ...g,
        items: g.items.filter((i) =>
          [i.label, i.desc, ...(i.aliases ?? [])].join(' ').toLowerCase().includes(q)
        ),
      }))
      .filter((g) => g.items.length > 0);
  }, [query]);

  return (
    <div className="start-page">
      <PageHeader
        title="开始"
        subtitle="A股价值投资工作台:从判断市场贵贱到卖出复盘的完整闭环"
      />

      {/* ── 工作流地图 ── */}
      <section>
        <h2 className="start-section-title">投资闭环:六步走完一圈</h2>
        <div className="start-workflow">
          {workflowStages.map((stage) => (
            <div key={stage.id} className="start-stage">
              <span className="start-stage__title">{stage.title}</span>
              <span className="start-stage__role">{stage.role}</span>
              <div className="start-stage__links">
                {stage.links.map((link) => (
                  <Link key={link.path + link.label} to={link.path}>
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── 场景卡 ── */}
      <section>
        <h2 className="start-section-title">按你想做的事找功能</h2>
        <div className="start-scenarios">
          {scenarios.map((s) => (
            <div key={s.id} className="start-scenario">
              <span className="start-scenario__question">{s.question}</span>
              <span className="start-scenario__answer">{s.answer}</span>
              <div className="start-scenario__links">
                <Link className="start-scenario__primary" to={s.primary}>
                  {pathLabel.get(s.primary) ?? s.primary} →
                </Link>
                {s.links.map((link) => (
                  <Link key={link.path} className="start-scenario__secondary" to={link.path}>
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── 页面速查表 ── */}
      <section>
        <h2 className="start-section-title">页面速查</h2>
        <input
          className="start-filter"
          placeholder="搜功能:估值 / 排雷 / 回测 / 温度…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="start-cheatsheet">
          {filteredGroups.map((g) => (
            <div key={g.id} className="start-cheatsheet-group">
              <h3>{g.title}</h3>
              <table className="start-cheatsheet-table">
                <tbody>
                  {g.items.map((i) => (
                    <tr key={i.path}>
                      <td>
                        <Link to={i.path}>{i.label}</Link>
                      </td>
                      <td className="start-cheatsheet-desc">{i.desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {filteredGroups.length === 0 && (
            <p className="start-cheatsheet-desc">没有匹配的页面,换个关键词试试。</p>
          )}
        </div>
      </section>

      {/* ── 口径速记 ── */}
      <details className="start-calibration">
        <summary>口径速记(防误读)</summary>
        <ul>
          {CALIBRATION_NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </details>
    </div>
  );
};
```

- [ ] **Step 3: 验证**

Run: `pnpm test && pnpm lint && pnpm build`
Expected: 全部通过。

- [ ] **Step 4: Commit**

```bash
git add src/pages/Start.tsx src/pages/Start.css
git commit -m "feat(start): 开始页完整四段——六层工作流地图/6场景卡/带搜索页面速查/口径速记,全部消费navigation.ts"
```

---

### Task 6: 全量验证 + 手动验收

**Files:**
- 无新文件(验证任务;如手动验收发现微调,修复后单独 commit)

- [ ] **Step 1: 全量自动化验证**

Run: `pnpm test && pnpm lint && pnpm build`
Expected: 全绿、零新告警、构建成功。

- [ ] **Step 2: 手动验收(pnpm dev 起本地服务,浏览器核对)**

清单(逐项确认):

1. 打开 `http://localhost:<port>/` → 自动落到 `/start`,页头"开始"与一句话副标题。
2. 工作流地图 6 卡(看市场→复盘)可点击跳转,跳转目标页正常渲染。
3. 场景卡 6 张,主按钮"持仓体检 →"等直达正确;速查表输入"估值"能过滤出「财务分析」(alias 命中),输入"汇金"能过滤出「国家队」。
4. 侧栏 6 组;「开始」「市场」默认展开,其余折叠;展开组每项两行(标签+灰色副标题);点组头可折叠/展开。
5. 侧栏整体折叠(collapse 按钮)后悬停任一项,title 显示"标签——副标题"。
6. 点击侧栏「买入体检」→ `/checklist` 页面正常(幽灵入口转正)。
7. 直接访问 `/dashboard` 旧深链仍正常;「工作台」菜单项高亮正确。
8. 深色主题下 Start 页与侧栏副标题无不可读的低对比文字。

- [ ] **Step 3: 验收微调(如有)**

若发现文案/样式微调,修复后:

```bash
git add <涉及文件>
git commit -m "feat(start): 手动验收微调——<具体内容>"
```

---

## Self-Review 记录

- **Spec 覆盖**:菜单 6 组 28 项+副标题(Task 1/4)、defaultOpen 折叠(Task 4)、`/start` 落地+`/` 重定向(Task 3)、checklist 转正(Task 1 数据+Task 4 渲染)、Start 四段(Task 5)、速查 filter+alias(Task 5)、口径速记(Task 1/5)、双向校验测试(Task 2)、desc 非空测试(Task 1)——spec 各节均有对应任务。
- **占位符扫描**:Task 3 的最小 Start 页是"可运行的中间交付物"(每个任务独立可构建),不是 TBD;其余步骤均含完整代码。无"适当处理""稍后补充"类占位。
- **类型一致性**:`NavItem.icon: string` 与 Layout 的 `(Icons as Record<string, React.ReactNode>)[item.icon]` 一致;`Scenario.links`/`WorkflowStage.links` 均为 `{label, path}[]`;Task 1 测试断言的 `workflowStages` 六个 id 与实现一致。
- **已知取舍**:Start 页无组件渲染测试(vitest 为 node 环境,项目无 jsdom/testing-library 基建;引入违背 YAGNI),由 Task 1 数据测试 + Task 6 手动验收覆盖。
