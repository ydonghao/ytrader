# 体系化重组：工作流主轴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 28 个菜单项按六段工作流主轴重组为 27 项，"看市场贵不贵"三入口合一为市场温度页，删除 AI 交易助手（唯一砍掉的功能），统一嵌入式 AI 面板外壳，每页页头加工作流串联条。

**Architecture:** 全部为前端信息架构重组 + 少量后端删除（ai_chat_router）。`config/navigation.ts` 仍是导航单一数据源，扩展 stage/prev/next 元数据驱动页头 WorkflowBar；温度计从 Thesis.tsx 抽为共享组件 ThermometerCard（full/compact 双模式）；`/indices` 升格三 Tab 市场温度页（温度计/指数水位/破净率择时）；新 AiInsightPanel 统一各 AI 面板外壳。

**Tech Stack:** React 18 + TypeScript + vite + vitest（node 环境纯函数测试，**无** RTL/jsdom 组件测试基建——组件逻辑抽纯函数测试）；后端 FastAPI + pytest（uv）。

**Spec:** `docs/superpowers/specs/2026-10-08-workflow-reorganization-design.md`

## Global Constraints

- 前端测试命令：`cd frontend/apps/web && npx vitest run`（全量）；单文件 `npx vitest run src/config/__tests__/navigation.test.ts`
- 后端测试命令：`cd backend && uv run pytest -q`；启动验证 `uv run uvicorn main:create_app --factory`（工厂模式，`main:app` 不可用）
- 前端构建：`cd frontend/apps/web && npm run build`（tsc 类型检查随构建跑）
- 菜单规模终态：6 组 `[2, 3, 8, 2, 5, 5, 2]` = 27 项；每项 desc 非空且 ≤16 字符（navigation.test 护栏）
- 不砍不动的功能：永久组合、看板、报告、自动建组合、宏观、国家队、行情——只调整归属
- 后端唯一改动：删 ai_chat_router（其余后端文件零改动）。spec §6 提到的"清理论证库 LLMManager/MiniMax 双路径"经侦察（2026-10-08）确认**已无需改动**：`backend/src/api/handler/argument_handler.py:58` 已走 `infra/llm/single_call.complete_with_retry`（commit 12ca11a 已落地），AI 统一本轮为纯前端壳统一
- navigation.ts 是侧栏（Layout）与开始页（Start）的单一数据源，不得出现重复定义
- 工作区可能有用户未提交改动（coursePortfolio 等）：**每次 commit 只 `git add` 本任务明确列出的文件**
- 实施顺序与 spec 阶段编号不同（删 AIChat 提前到 Task 1）：避免菜单护栏断言改两次、避免 /ai-workspace/trader 成为幽灵路由。spec 验收标准不受影响。

---

### Task 1: 删除 AI 交易助手（前端页面 + 路由 + 后端 router）

唯一砍掉的功能。前端删页面与路由、/ai-chat 老链接重定向到 /start；后端删 router 与挂载。此任务先做，后续菜单重组的护栏断言一步到位 27 项。

**Files:**
- Modify: `frontend/apps/web/src/config/navigation.ts`（删 1 个菜单项）
- Modify: `frontend/apps/web/src/config/__tests__/navigation.test.ts`（护栏 28→27）
- Modify: `frontend/apps/web/src/App.tsx`（删 import、删路由、改重定向目标）
- Delete: `frontend/apps/web/src/pages/AIChat.tsx`
- Delete: `frontend/apps/web/src/pages/AIChat.css`
- Modify: `backend/main.py:23`（删 import）、`backend/main.py:396`（删挂载）
- Delete: `backend/src/api/router/ai_chat_router.py`

**Interfaces:**
- Consumes: 无
- Produces: 菜单 27 项基线（后续任务的护栏新值）；`/ai-chat` → `/start` 重定向保留（仍在 routes.test.ts 的 REDIRECT_PATHS 豁免清单内，豁免清单**不需要改**）

- [ ] **Step 1: 改 navigation.ts——删除 AI 交易助手菜单项**

在 `navGroups` 的 `system` 组（id: 'system'）中删除这一行：

```ts
{path: '/ai-workspace/trader', label: 'AI交易助手', desc: 'AI 对话交易工作台', icon: 'intel'},
```

删除后 system 组仅剩：

```ts
{
  id: 'system',
  title: 'AI / 系统',
  defaultOpen: false,
  items: [
    {path: '/settings', label: '设置', desc: '系统与数据源配置', icon: 'settings'},
    {path: '/system-logs', label: '系统日志', desc: '运行日志与数据健康', icon: 'terminal', aliases: ['数据健康']},
  ],
},
```

- [ ] **Step 2: 改 navigation.test.ts 护栏断言（先于实现跑会红，作为 TDD 锚点）**

`frontend/apps/web/src/config/__tests__/navigation.test.ts` 第 24-28 行，菜单规模护栏改为：

```ts
it('菜单规模护栏:6 组 27 项,各组数量固定(增删须显式改此断言)', () => {
  expect(navGroups.length).toBe(6);
  expect(navGroups.map((g) => g.items.length)).toEqual([2, 4, 9, 5, 5, 2]);
  expect(allItems.length).toBe(27);
});
```

- [ ] **Step 3: 跑测试确认现状（删菜单前会红——AI 项还在）**

Run: `cd frontend/apps/web && npx vitest run src/config/__tests__/navigation.test.ts`
Expected: FAIL（`[2,4,9,5,5,3]` 与 `[2,4,9,5,5,2]` 不匹配）——若 Step 1 已做则此处直接绿，两种顺序都接受。

- [ ] **Step 4: 改 App.tsx——删 import 与路由，重定向改道**

1. 删除第 20 行：`import {AIChat} from './pages/AIChat';`
2. 第 109 行 `/ai-chat` 重定向目标从 `/ai-workspace/trader` 改为 `/start`：

```tsx
<Route path="/ai-chat" element={<Navigate to="/start" replace />} />
```

3. 删除第 130-131 行（AI 工作台注释 + 路由）：

```tsx
{/* ── AI 工作台 ── */}
<Route path="/ai-workspace/trader" element={<AIChat />} />
```

- [ ] **Step 5: 删除前端页面文件**

```bash
cd frontend/apps/web/src/pages && git rm AIChat.tsx AIChat.css
```

- [ ] **Step 6: 改后端 main.py + 删 router**

`backend/main.py` 删除第 23 行：

```python
from src.api.router.ai_chat_router import router as ai_chat_router
```

删除第 396 行（include_router 区块内）：

```python
app.include_router(ai_chat_router, prefix="/api/v1")  # /api/v1/ai/chat
```

删除文件：

```bash
cd backend && git rm src/api/router/ai_chat_router.py
```

- [ ] **Step 7: 全库残留检查**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader && grep -rn "ai-workspace\|AIChat" frontend/apps/web/src --include="*.ts" --include="*.tsx" | grep -v __tests__`
Expected: 无输出（routes.test.ts 的 REDIRECT_PATHS 含 `/ai-chat` 字面量，属豁免清单，不算残留）

Run: `cd backend && grep -rn "ai_chat_router" src/ main.py | grep -v __pycache__`
Expected: 无输出

- [ ] **Step 8: 跑测试**

Run: `cd frontend/apps/web && npx vitest run`
Expected: 全绿（navigation/routes 双测试文件通过——REDIRECT_PATHS 豁免清单含 `/ai-chat`，与 App.tsx 的 Navigate 路由仍精确一致）

Run: `cd backend && uv run pytest -q` 
Expected: 全绿（tests/ 中无 ai_chat 测试文件，llm 域的 test_openai_chat_provider 等属于 llm_config provider 类型名，与本任务无关）

- [ ] **Step 9: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/config/navigation.ts \
  frontend/apps/web/src/config/__tests__/navigation.test.ts \
  frontend/apps/web/src/App.tsx \
  frontend/apps/web/src/pages/AIChat.tsx \
  frontend/apps/web/src/pages/AIChat.css \
  backend/main.py backend/src/api/router/ai_chat_router.py
git commit -m "refactor(web): 移除AI交易助手——唯一砍项(spec体系化重组):删AIChat页/路由/ai_chat_router,/ai-chat老链接重定向至/start;菜单28→27项"
```

---

### Task 2: navigation.ts 六段主轴重组（分组重排，文案不动）

菜单从"开始/市场/选股研究/持仓与交易/复盘与回测/AI系统"重组为六段主轴"开始/市场/研究/决策/持仓/复盘/系统"。本任务**只动分组与组名**，各 item 的 label/desc/icon 保持原值（/indices 更名"市场温度"在 Task 6 页面内容就位后再改，避免文案先行的窗口期）。

**Files:**
- Modify: `frontend/apps/web/src/config/navigation.ts`（navGroups 全量替换 + scenarios 加 1 条 + workflowStages research 加 1 链接）
- Modify: `frontend/apps/web/src/config/__tests__/navigation.test.ts`（护栏 [2,4,9,5,5,2]→[2,3,8,2,5,5,2]；scenarios 6→7）

**Interfaces:**
- Consumes: Task 1 的 27 项基线
- Produces: 六段分组 id `start/market/research/decide/hold/review/system`（Task 3 的 stage 元数据、Task 10 的 WorkflowBar 依赖这些 id）；scenarios 第 7 条 `data-views`（Dashboard/分析/看板分工说明）

- [ ] **Step 1: 改护栏断言**

navigation.test.ts 菜单规模护栏改为：

```ts
it('菜单规模护栏:6 组 27 项,各组数量固定(增删须显式改此断言)', () => {
  expect(navGroups.length).toBe(6);
  expect(navGroups.map((g) => g.items.length)).toEqual([2, 3, 8, 2, 5, 5, 2]);
  expect(allItems.length).toBe(27);
});
```

scenarios 断言（"场景卡"用例）改为：

```ts
expect(scenarios.length).toBe(7);
```

- [ ] **Step 2: 跑测试确认红**

Run: `cd frontend/apps/web && npx vitest run src/config/__tests__/navigation.test.ts`
Expected: FAIL（当前分组数量 [2,4,9,5,5,2] 与新断言不符、scenarios 为 6）

- [ ] **Step 3: 全量替换 navGroups**

navigation.ts 中 `export const navGroups: NavGroup[] = [...]` 整段替换为：

```ts
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
      {path: '/indices', label: '指数', desc: '市场温度与估值水位', icon: 'globe', aliases: ['温度', '水位', '估值']},
      {path: '/macro', label: '宏观政策', desc: '政策事件与宏观跟踪', icon: 'analytics'},
      {path: '/national-team', label: '国家队', desc: '汇金等席位动向全景', icon: 'analytics', aliases: ['汇金', '席位']},
    ],
  },
  {
    id: 'research',
    title: '研究',
    defaultOpen: false,
    items: [
      {path: '/screener', label: '选股器', desc: '多条件筛选候选股', icon: 'strategies'},
      {path: '/financial', label: '财务分析', desc: '报表/质量/五法估值', icon: 'financial', aliases: ['估值', '五法', 'DCF']},
      {path: '/industry-analysis', label: '行业分析', desc: '破净率/景气/资金流', icon: 'analytics', aliases: ['热力图']},
      {path: '/earnings-radar', label: '财报雷达', desc: '财报季景气与事件', icon: 'analytics'},
      {path: '/compare', label: '标的对比', desc: '候选股 13 维并排', icon: 'strategies', aliases: ['对比']},
      {path: '/notes', label: '研究笔记', desc: '按标的沉淀研究记录', icon: 'reports'},
      {path: '/reports', label: '报告', desc: '券商研报聚合', icon: 'reports'},
      {path: '/market', label: '行情快照', desc: '个股行情快照', icon: 'market'},
    ],
  },
  {
    id: 'decide',
    title: '决策',
    defaultOpen: false,
    items: [
      {path: '/checklist', label: '买入体检', desc: '买前清单与仓位建议', icon: 'strategies', aliases: ['体检', '建仓', '排雷']},
      {path: '/course-portfolio', label: '自动建组合', desc: '按课程策略生成组合', icon: 'portfolio'},
    ],
  },
  {
    id: 'hold',
    title: '持仓',
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
    title: '复盘',
    defaultOpen: false,
    items: [
      {path: '/replay', label: '时光机', desc: '回到历史日期复盘决策', icon: 'star', aliases: ['历史', '复盘']},
      {path: '/lt-backtest', label: '回测实验室', desc: '长期策略回测与优化', icon: 'backtest', aliases: ['回测']},
      {path: '/analytics', label: '分析', desc: '交易与业绩统计', icon: 'analytics'},
      {path: '/board', label: '看板', desc: '自定义数据看板', icon: 'dashboard'},
      {path: '/perm-portfolio', label: '永久组合', desc: '永久组合跟踪', icon: 'portfolio'},
    ],
  },
  {
    id: 'system',
    title: '系统',
    defaultOpen: false,
    items: [
      {path: '/settings', label: '设置', desc: '系统与数据源配置', icon: 'settings'},
      {path: '/system-logs', label: '系统日志', desc: '运行日志与数据健康', icon: 'terminal', aliases: ['数据健康']},
    ],
  },
];
```

要点：行情 `/market` 从市场组移入研究组尾部（"看一只股"的轻量入口）；买入体检+自动建组合独立成"决策"组；报告/永久组合/看板归位复盘组；AI 交易助手已删。

- [ ] **Step 4: scenarios 追加第 7 条（Dashboard/分析/看板分工）**

在 `scenarios` 数组末尾（`review-loop` 之后）追加：

```ts
{
  id: 'data-views',
  question: '想看数据：账户、业绩、自定义各去哪页',
  answer: '工作台=账户资产与盈亏总览；分析=交易与业绩统计(胜率/回撤/月度)；看板=自选指标卡片自定义布局。',
  primary: '/dashboard',
  links: [
    {label: '业绩统计', path: '/analytics'},
    {label: '自定义看板', path: '/board'},
  ],
},
```

- [ ] **Step 5: workflowStages 的 research 段补行情入口**

`research` stage 的 links 数组末尾追加一行：

```ts
{label: '行情快照', path: '/market'},
```

- [ ] **Step 6: 跑测试**

Run: `cd frontend/apps/web && npx vitest run`
Expected: 全绿（27 项分 7 组、scenarios 7 条全部指向菜单内路径、workflowStages 链接合法、routes.test 菜单↔路由双向校验通过——所有菜单项路由都在）

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/web/src/config/navigation.ts \
  frontend/apps/web/src/config/__tests__/navigation.test.ts
git commit -m "refactor(web): 菜单六段主轴重组——开始/市场/研究/决策/持仓/复盘/系统;行情入研究、体检+建组合独立决策组、报告/永久组合/看板归位复盘;新增看数据分工场景卡"
```

---

### Task 3: navigation.ts 工作流元数据（stage/prev/next）+ getFlowContext 纯函数

为 Task 10 的页头工作流条提供数据。NavItem 增加可选元数据；`getFlowContext(path)` 纯函数把 path 解析为环节名与上下游页面。

**Files:**
- Modify: `frontend/apps/web/src/config/navigation.ts`（NavItem 接口 + 各项打标 + 新函数）
- Modify: `frontend/apps/web/src/config/__tests__/navigation.test.ts`（新增 describe 块）

**Interfaces:**
- Consumes: Task 2 的六段分组
- Produces:
  - `NavItem.stage?: string`、`NavItem.prev?: string`、`NavItem.next?: string`（均为 path 引用）
  - `export interface FlowContext { stageTitle: string; prev?: {path: string; label: string}; next?: {path: string; label: string}; }`
  - `export function getFlowContext(path: string): FlowContext | null`（Task 10 WorkflowBar 消费）

- [ ] **Step 1: 写失败测试（navigation.test.ts 末尾追加）**

```ts
import {getFlowContext} from '../navigation';

describe('工作流元数据', () => {
  it('每个 stage 都是合法环节或 start/system', () => {
    const validStages = ['start', 'market', 'research', 'decide', 'hold', 'review', 'system'];
    for (const item of allItems) {
      if (item.stage) expect(validStages).toContain(item.stage);
    }
  });

  it('prev/next 引用的 path 必须存在于菜单', () => {
    for (const item of allItems) {
      if (item.prev) expect(allPaths).toContain(item.prev);
      if (item.next) expect(allPaths).toContain(item.next);
    }
  });

  it('getFlowContext 解析主链页面', () => {
    const fin = getFlowContext('/financial');
    expect(fin?.stageTitle).toBe('研究');
    expect(fin?.prev?.path).toBe('/screener');
    expect(fin?.next?.path).toBe('/checklist');
  });

  it('getFlowContext 未知路径返回 null', () => {
    expect(getFlowContext('/nope')).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend/apps/web && npx vitest run src/config/__tests__/navigation.test.ts`
Expected: FAIL（`getFlowContext` 未导出）

- [ ] **Step 3: 实现——NavItem 接口扩展**

navigation.ts 的 NavItem 接口替换为：

```ts
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
```

- [ ] **Step 4: 实现——主链页面打标**

在 navGroups 对应 item 上追加属性（其余项不标）：

```ts
// start 组
{path: '/start', ..., stage: 'start'},
{path: '/dashboard', ..., stage: 'start'},
// market 组（3 项全部）
{path: '/indices', ..., stage: 'market', next: '/screener'},
{path: '/macro', ..., stage: 'market'},
{path: '/national-team', ..., stage: 'market'},
// research 组（8 项全部）
{path: '/screener', ..., stage: 'research', prev: '/indices', next: '/financial'},
{path: '/financial', ..., stage: 'research', prev: '/screener', next: '/checklist'},
{path: '/industry-analysis', ..., stage: 'research'},
{path: '/earnings-radar', ..., stage: 'research'},
{path: '/compare', ..., stage: 'research', next: '/checklist'},
{path: '/notes', ..., stage: 'research'},
{path: '/reports', ..., stage: 'research'},
{path: '/market', ..., stage: 'research'},
// decide 组（2 项全部）
{path: '/checklist', ..., stage: 'decide', prev: '/financial', next: '/thesis'},
{path: '/course-portfolio', ..., stage: 'decide', prev: '/checklist'},
// hold 组（5 项全部）
{path: '/trading', ..., stage: 'hold'},
{path: '/thesis', ..., stage: 'hold', next: '/replay'},
{path: '/watchlist', ..., stage: 'hold'},
{path: '/risk', ..., stage: 'hold'},
{path: '/alerts', ..., stage: 'hold'},
// review 组（5 项全部）
{path: '/replay', ..., stage: 'review', prev: '/thesis'},
{path: '/lt-backtest', ..., stage: 'review'},
{path: '/analytics', ..., stage: 'review'},
{path: '/board', ..., stage: 'review'},
{path: '/perm-portfolio', ..., stage: 'review'},
// system 组（2 项全部）
{path: '/settings', ..., stage: 'system'},
{path: '/system-logs', ..., stage: 'system'},
```

（`...` 表示该项原有的 label/desc/icon/aliases 原样保留，只追加 stage/prev/next 字段。）

- [ ] **Step 5: 实现——getFlowContext 函数（navigation.ts 末尾追加）**

```ts
export interface FlowContext {
  stageTitle: string;
  prev?: {path: string; label: string};
  next?: {path: string; label: string};
}

const itemByPath = new Map(navGroups.flatMap((g) => g.items.map((i) => [i.path, i] as const)));

/** 页头工作流条数据：path → 环节名 + 上下游直达（无 stage 的页面返回 null） */
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
```

- [ ] **Step 6: 跑测试**

Run: `cd frontend/apps/web && npx vitest run src/config/__tests__/navigation.test.ts`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/web/src/config/navigation.ts \
  frontend/apps/web/src/config/__tests__/navigation.test.ts
git commit -m "feat(web): navigation工作流元数据——NavItem增加stage/prev/next,getFlowContext纯函数解析环节与上下游;主链页面(温度→筛→财务→体检→论点→复盘)全部打通"
```

---

### Task 4: ThermometerCard 共享组件（full/compact 双模式）

把 Thesis.tsx 顶部的温度计（state + 3 个 API + JSX + CSS）抽为独立组件。full 模式 = 现有完整卡（温度行 + 水位回测结论 + ERP 历史曲线懒加载）；compact 模式 = 一行精简条 + 深链 `/indices?tab=thermo`（Task 6 的市场温度页 Tab 锚点）。

**Files:**
- Create: `frontend/apps/web/src/components/ThermometerCard.tsx`
- Create: `frontend/apps/web/src/components/ThermometerCard.css`

**Interfaces:**
- Consumes: 后端端点 `GET /thesis/thermometer`、`GET /thesis/thermometer/backtest`、`GET /thesis/thermometer/history?days=2000`（均已存在，thesis_router）
- Produces: `export function ThermometerCard({variant}: {variant?: 'full' | 'compact'})`（Task 5 Thesis compact、Task 6 Indices full 消费）

- [ ] **Step 1: 创建 ThermometerCard.tsx**

```tsx
/**
 * ThermometerCard — 市场温度计共享组件（数据自取）。
 * full:温度行 + 水位回测结论 + ERP 历史曲线(懒加载展开);
 * compact:一行精简条(Thesis 顶部),整条深链 /indices?tab=thermo。
 */
import {useEffect, useState} from 'react';
import {Link} from 'react-router-dom';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip,
} from 'recharts';
import {axisProps, tooltipProps} from '../lib/chartTheme';
import {getApiBase} from '../lib/api';
import './ThermometerCard.css';

const API = `${getApiBase()}/thesis`;

export function ThermometerCard({variant = 'full'}: {variant?: 'full' | 'compact'}) {
  const [thermo, setThermo] = useState<any>(null);
  const [thermoBt, setThermoBt] = useState<any>(null);
  const [thermoHist, setThermoHist] = useState<any[] | null>(null);

  useEffect(() => {
    fetch(`${API}/thermometer`).then(r => r.json())
      .then(d => d.code === 0 && setThermo(d.data)).catch(() => {});
    fetch(`${API}/thermometer/backtest`).then(r => r.json())
      .then(d => d.code === 0 && setThermoBt(d.data)).catch(() => {});
  }, []);

  function loadThermoHist() {
    if (thermoHist) return;
    fetch(`${API}/thermometer/history?days=2000`).then(r => r.json())
      .then(d => d.code === 0 && setThermoHist(d.data)).catch(() => {});
  }

  if (!thermo || !thermo.level || thermo.level === 'unknown') return null;

  if (variant === 'compact') {
    return (
      <Link to="/indices?tab=thermo" className={`thermo-card thermo-card--compact thermo-card--${thermo.level}`}>
        <span className="thermo-card__label">🌡 {thermo.level_label}</span>
        <span>股债性价比 {thermo.erp_pct}%{thermo.erp_percentile != null && `（分位 ${thermo.erp_percentile}%）`}</span>
        {thermo.position_band && (
          <span className="thermo-card__band">
            建议仓位 {thermo.position_band.low}~{thermo.position_band.high}%
          </span>
        )}
        <span className="thermo-card__toggle">市场温度页 →</span>
      </Link>
    );
  }

  return (
    <div className={`thermo-card thermo-card--${thermo.level}`}>
      <div className="thermo-card__row" onClick={loadThermoHist} style={{cursor: 'pointer'}}>
        <span className="thermo-card__label">🌡 {thermo.level_label}</span>
        <span>股债性价比 {thermo.erp_pct}%{thermo.erp_percentile != null &&
          `（分位 ${thermo.erp_percentile}%）`}</span>
        {thermo.buffett_pct != null && (
          <span>巴菲特指标 {thermo.buffett_pct}%（{thermo.buffett_label}）</span>
        )}
        {thermo.position_band && (
          <span className="thermo-card__band">
            建议整体仓位水位 {thermo.position_band.low}~{thermo.position_band.high}%
          </span>
        )}
        <span className="thermo-card__toggle">
          {thermoHist ? '收起历史 ▴' : '展开历史 ▾'}
        </span>
      </div>
      {thermoBt && (
        <p className="dim" style={{marginTop: 'var(--space-1)'}}>
          水位策略回测（{thermoBt.start?.slice(0, 4)}-{thermoBt.end?.slice(0, 4)}）：
          年化 <b style={{color: 'var(--color-success)'}}>{thermoBt.strategy?.cagr_pct}%</b>
          / 回撤 {thermoBt.strategy?.max_drawdown_pct}%
          vs 买入持有 {thermoBt.buy_hold?.cagr_pct}% / {thermoBt.buy_hold?.max_drawdown_pct}%
        </p>
      )}
      {thermoHist && (
        <div style={{height: 180, marginTop: 'var(--space-2)'}}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={thermoHist}>
              <XAxis dataKey="trade_date" {...axisProps} minTickGap={80} />
              <YAxis {...axisProps} domain={['auto', 'auto']}
                     tickFormatter={(v: number) => v.toFixed(1) + '%'} />
              <Tooltip {...tooltipProps} formatter={(v: number) => [v + '%', 'ERP']} />
              <Line type="monotone" dataKey="erp_pct" dot={false} strokeWidth={1.5}
                    stroke="var(--color-accent, #5e5ce6)" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 创建 ThermometerCard.css（样式从 Thesis.css 迁移并改前缀）**

```css
/* ThermometerCard — 从 Thesis.css thesis-thermo 段迁移,前缀改为 thermo-card */
.thermo-card {
  display: flex; flex-wrap: wrap; align-items: center;
  gap: var(--space-3); border-radius: 8px;
  padding: var(--space-3); margin-bottom: var(--space-3);
  border: 1px solid var(--color-border); font-size: var(--text-sm);
}
.thermo-card__label {font-weight: 600; font-size: var(--text-md);}
.thermo-card--deep_cold {border-color: var(--color-success); background: rgba(47, 158, 68, .08);}
.thermo-card--cold {border-color: var(--color-success);}
.thermo-card--neutral {border-color: var(--color-border);}
.thermo-card--warm {border-color: var(--color-warning);}
.thermo-card--hot {border-color: var(--color-danger); background: rgba(226, 106, 106, .08);}
.thermo-card__band {margin-left: auto; font-weight: 600;}
.thermo-card__row {display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3);}
.thermo-card__toggle {margin-left: auto; font-size: var(--text-xs); color: var(--color-text-tertiary);}

/* compact:一行精简条(Link 渲染) */
.thermo-card--compact {
  text-decoration: none; color: inherit;
}
.thermo-card--compact:hover {border-color: var(--color-accent, #5e5ce6);}
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend/apps/web && npm run build`
Expected: 构建成功（组件未被引用不报错，验证类型自洽）

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/components/ThermometerCard.tsx \
  frontend/apps/web/src/components/ThermometerCard.css
git commit -m "feat(web): ThermometerCard共享组件——温度计从Thesis抽出,full(温度行+回测+ERP曲线)/compact(一行条深链市场温度页)双模式,数据自取"
```

---

### Task 5: Thesis.tsx 换用 compact 温度条

Thesis 顶部完整温度卡替换为 compact 精简条；删除原 state/fetch/JSX/CSS。

**Files:**
- Modify: `frontend/apps/web/src/pages/Thesis.tsx`（删 state、删 2 个 fetch、删 loadThermoHist、替换 JSX、加 import）
- Modify: `frontend/apps/web/src/pages/Thesis.css`（删 thesis-thermo 段）

**Interfaces:**
- Consumes: Task 4 的 `ThermometerCard`（variant="compact"）
- Produces: Thesis.tsx 不再含温度计实现（grep `thermo` 仅剩 snapshot 快照展示与 Detail 内字段）

- [ ] **Step 1: Thesis.tsx 加 import（chartTheme import 行附近）**

```tsx
import {ThermometerCard} from '../components/ThermometerCard';
```

- [ ] **Step 2: 删除温度 state（约 1018-1019、1031 行）**

删除这三行：

```tsx
const [thermo, setThermo] = useState<any>(null);
const [thermoHist, setThermoHist] = useState<any[] | null>(null);
const [thermoBt, setThermoBt] = useState<any>(null);
```

- [ ] **Step 3: 删除 load 回调里的两个 fetch（约 1043-1044、1057-1058 行）**

```tsx
fetch(`${API}/thermometer`).then(r => r.json())
  .then(d => d.code === 0 && setThermo(d.data)).catch(() => {});
```

```tsx
fetch(`${API}/thermometer/backtest`).then(r => r.json())
  .then(d => d.code === 0 && setThermoBt(d.data)).catch(() => {});
```

- [ ] **Step 4: 删除 loadThermoHist 函数（约 1063-1067 行）**

```tsx
function loadThermoHist() {
  if (thermoHist) return;   // 已加载则切换显示即可
  fetch(`${API}/thermometer/history?days=2000`).then(r => r.json())
    .then(d => d.code === 0 && setThermoHist(d.data)).catch(() => {});
}
```

- [ ] **Step 5: 替换温度卡 JSX（约 1112-1157 行的 `{thermo && ...}` 整块）**

原 `{thermo && thermo.level && thermo.level !== 'unknown' && ( ... )}` 整块（46 行）替换为：

```tsx
<ThermometerCard variant="compact" />
```

- [ ] **Step 6: Thesis.css 删 thesis-thermo 段（约 83-98 行）**

删除从 `.thesis-thermo {` 到 `.thesis-thermo__toggle {...}` 的全部规则（9 条选择器）。

- [ ] **Step 7: 残留检查 + 测试 + 构建**

Run: `cd frontend/apps/web && grep -n "thermo" src/pages/Thesis.tsx`
Expected: 仅剩 `thesis.snapshot?.thermometer`（登记快照展示，走论点数据不走实时温度）与 `ThermometerCard` import/使用行

Run: `cd frontend/apps/web && grep -n "thesis-thermo" src -r`
Expected: 无输出

Run: `cd frontend/apps/web && npx vitest run && npm run build`
Expected: 全绿 + 构建成功

- [ ] **Step 8: Commit**

```bash
git add frontend/apps/web/src/pages/Thesis.tsx frontend/apps/web/src/pages/Thesis.css
git commit -m "refactor(web): Thesis顶部温度卡换ThermometerCard compact精简条——完整温度/回测/历史曲线移驻市场温度页,持仓页留一行深链"
```

---

### Task 6: /indices 升格"市场温度"三 Tab 页 + 行业分析移除破净率 Tab

"看市场贵不贵"三入口合一的落点：Indices 页改三 Tab（温度计/指数水位/破净率择时），支持 `?tab=` 深链；行业分析页移除 timing Tab 后保留景气热力图/板块强弱两 Tab；菜单文案同步。

**Files:**
- Modify: `frontend/apps/web/src/pages/Indices.tsx`（Tab 壳 + thermo/pb 两个新 Tab）
- Modify: `frontend/apps/web/src/pages/IndustryAnalysis.tsx`（移除 timing Tab）
- Modify: `frontend/apps/web/src/config/navigation.ts`（/indices 与 /industry-analysis 的 label/desc、/thesis desc、market-level 场景文案）

**Interfaces:**
- Consumes: Task 4 `ThermometerCard`（variant="full"）；既有 `PbBreakTab`（props `{industries: {sw_code: string; name: string}[]; onPick: (swCode: string) => void}`）、`useIndustryOverview(win)` hook、`IndustryDetailDrawer`（props `{swCode; onClose}`）、`components/ui` 的 `Tabs`（用法见 IndustryAnalysis.tsx:23-27）
- Produces: `/indices?tab=thermo|indices|pb` 深链锚点（Task 4 compact 卡已指向 thermo）；菜单项"市场温度"

- [ ] **Step 1: Indices.tsx 加 import**

在现有 import 区追加：

```tsx
import {Tabs} from '../components/ui';
import {ThermometerCard} from '../components/ThermometerCard';
import {PbBreakTab} from '../components/industry/PbBreakTab';
import {IndustryDetailDrawer} from '../components/industry/IndustryDetailDrawer';
import {useIndustryOverview} from '../hooks/useIndustryAnalysis';
```

- [ ] **Step 2: Indices 组件体加 Tab 状态与破净率数据（组件函数体顶部）**

```tsx
type ThermoTab = 'thermo' | 'indices' | 'pb';
const [tab, setTab] = useState<ThermoTab>(() => {
  const t = new URLSearchParams(window.location.search).get('tab');
  return t === 'indices' || t === 'pb' ? t : 'thermo';
});
const [picked, setPicked] = useState<string | null>(null);
const industryOverview = useIndustryOverview(8);
const industries = (industryOverview.data?.rows ?? [])
  .map((r) => ({sw_code: r.sw_code, name: r.name}));
```

- [ ] **Step 3: JSX 包 Tab 壳（PageHeader 之后、原内容之前）**

PageHeader 的 subtitle 改为 `'温度计 · 指数估值水位 · 破净率择时'`，title 改为 `'市场温度'`；紧随其后插入：

```tsx
<Tabs active={tab} onChange={(k) => setTab(k as ThermoTab)} tabs={[
  {key: 'thermo', label: '温度计'},
  {key: 'indices', label: '指数水位'},
  {key: 'pb', label: '破净率择时'},
]} />
{tab === 'thermo' && <ThermometerCard variant="full" />}
{tab === 'indices' && (
  <>
    {/* 原页面全部内容（核心指数卡片条/列表+图表/市值与业绩/PE趋势/排行表）原样移入 */}
  </>
)}
{tab === 'pb' && <PbBreakTab industries={industries} onPick={setPicked} />}
{picked && <IndustryDetailDrawer swCode={picked} onClose={() => setPicked(null)} />}
```

原 Indices 全部内容 JSX（core-index cards strip 起至排行表止）包进 `tab === 'indices'` 分支，内容零改动。

- [ ] **Step 4: IndustryAnalysis.tsx 移除 timing Tab（整文件 36 行，替换为 31 行版本）**

```tsx
/** 行业分析:行业景气热力图/板块强弱 两Tab+行业详情抽屉。(宏观择时破净率已迁 /indices 市场温度页) */
import {useState} from 'react';
import {PageHeader, Tabs} from '../components/ui';
import {ProsperityHeatmap} from '../components/industry/ProsperityHeatmap';
import {StrengthFlowTab} from '../components/industry/StrengthFlowTab';
import {IndustryDetailDrawer} from '../components/industry/IndustryDetailDrawer';
import {useIndustryOverview, type PctWindow} from '../hooks/useIndustryAnalysis';
import './IndustryAnalysis.css';

export function IndustryAnalysis() {
  const [tab, setTab] = useState<'heatmap' | 'strength'>('heatmap');
  const [win, setWin] = useState<PctWindow>(8);
  const [picked, setPicked] = useState<string | null>(null);
  const overview = useIndustryOverview(win);
  const industries = (overview.data?.rows ?? [])
    .map((r) => ({sw_code: r.sw_code, name: r.name}));

  return (
    <div className="ia-page">
      <PageHeader title="行业分析"
        subtitle="行业景气热力图 · 板块资金强弱(申万一级31行业);破净率择时已并入市场温度页" />
      <Tabs active={tab} onChange={(k) => setTab(k as typeof tab)} tabs={[
        {key: 'heatmap', label: '景气热力图'},
        {key: 'strength', label: '板块强弱'},
      ]} />
      {tab === 'heatmap' &&
        <ProsperityHeatmap win={win} setWin={setWin} overview={overview} onPick={setPicked} />}
      {tab === 'strength' &&
        <StrengthFlowTab industries={industries} onPick={setPicked} />}
      {picked && <IndustryDetailDrawer swCode={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}
```

- [ ] **Step 5: navigation.ts 文案同步**

```ts
// market 组
{path: '/indices', label: '市场温度', desc: '温度计/水位/破净率择时', icon: 'globe', aliases: ['温度', '水位', '估值', '指数'], stage: 'market', next: '/screener'},
// research 组
{path: '/industry-analysis', label: '行业分析', desc: '景气热力图/资金流/强弱', icon: 'analytics', aliases: ['热力图'], stage: 'research'},
// hold 组（温度卡已迁出，desc 去掉"温度卡"）
{path: '/thesis', label: '持仓体检', desc: '论点/复盘/组合体检', icon: 'portfolio', aliases: ['论点', '卖出体检', '复盘'], stage: 'hold', next: '/replay'},
```

scenarios 的 `market-level` 场景 answer 改为：

```ts
answer: '市场温度页:温度计Tab看五档温度 + 股债性价比 ERP 与历史分位 + 建议仓位水位;指数水位Tab看估值分位,破净率Tab看阶段性底部参考区。',
```

其 links 不变（`/macro` 与 `/national-team` 均在菜单内）。`/financial` 场景等其余文案不动。

- [ ] **Step 6: 测试 + 构建**

Run: `cd frontend/apps/web && npx vitest run && npm run build`
Expected: 全绿（desc 长度 ≤16：'温度计/水位/破净率择时'=11、'景气热力图/资金流/强弱'=11、'论点/复盘/组合体检'=9 均达标）

- [ ] **Step 7: 手测清单（dev server）**

Run: `cd frontend/apps/web && npm run dev`（后端 `cd backend && uv run uvicorn main:create_app --factory --port 12100`，若前端代理指向 12100）
- `/indices` 默认落在温度计 Tab，五档色卡与水位回测行显示
- `?tab=indices` 直达指数水位，原功能完整；`?tab=pb` 破净率图 + 行业下拉 + 抽屉
- `/thesis` 顶部一行 compact 温度条，点击跳 `/indices?tab=thermo`
- `/industry-analysis` 只剩两 Tab，默认景气热力图

- [ ] **Step 8: Commit**

```bash
git add frontend/apps/web/src/pages/Indices.tsx \
  frontend/apps/web/src/pages/IndustryAnalysis.tsx \
  frontend/apps/web/src/config/navigation.ts
git commit -m "feat(web): /indices升格市场温度页——温度计/指数水位/破净率择时三Tab(?tab=深链),行业分析移除timing Tab保留热力图+板块强弱;看市场贵不贵三入口合一"
```

---

### Task 7: AiInsightPanel 共享组件 + aiTaskReducer 纯函数

统一各 AI 面板外壳：标题行（标题+来源徽标+操作槽）、加载骨架、错误卡+重试、内容槽。触发式 AI 任务的状态机抽成可测纯函数 reducer（无组件测试基建，故 reducer 单测覆盖）。

**Files:**
- Create: `frontend/apps/web/src/lib/aiTask.ts`（reducer 纯函数）
- Create: `frontend/apps/web/src/lib/__tests__/aiTask.test.ts`
- Create: `frontend/apps/web/src/components/AiInsightPanel.tsx`
- Create: `frontend/apps/web/src/components/AiInsightPanel.css`

**Interfaces:**
- Consumes: 无
- Produces:
  - `aiTask.ts`: `export type AiTaskState = {status: 'idle' | 'loading' | 'error'; error?: string}`; `export type AiTaskAction = {type: 'start'} | {type: 'done'} | {type: 'fail'; error: string} | {type: 'reset'}`; `export function aiTaskReducer(state: AiTaskState, action: AiTaskAction): AiTaskState`
  - `AiInsightPanel.tsx`: `export function AiInsightPanel(props: {title: string; source?: string; loading?: boolean; error?: string | null; onRetry?: () => void; actions?: React.ReactNode; children: React.ReactNode})`（Task 8/9 消费）

- [ ] **Step 1: 写失败测试**

`frontend/apps/web/src/lib/__tests__/aiTask.test.ts`：

```ts
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend/apps/web && npx vitest run src/lib/__tests__/aiTask.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 aiTask.ts**

```ts
/** 触发式 AI 任务状态机（AiInsightPanel 配套） */
export type AiTaskState = {status: 'idle' | 'loading' | 'error'; error?: string};

export type AiTaskAction =
  | {type: 'start'}
  | {type: 'done'}
  | {type: 'fail'; error: string}
  | {type: 'reset'};

export function aiTaskReducer(state: AiTaskState, action: AiTaskAction): AiTaskState {
  switch (action.type) {
    case 'start': return {status: 'loading'};
    case 'done': return {status: 'idle'};
    case 'fail': return {status: 'error', error: action.error};
    case 'reset': return {status: 'idle'};
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend/apps/web && npx vitest run src/lib/__tests__/aiTask.test.ts`
Expected: 5 个用例全绿

- [ ] **Step 5: 实现 AiInsightPanel.tsx**

```tsx
/**
 * AiInsightPanel — 嵌入式 AI 面板统一外壳。
 * 统一标题行(标题+AI徽标+操作槽)/加载骨架/错误卡(带重试)/内容槽。
 * AI 是功能不是页面:各页 AI 面板以此壳渲染,配置统一走后端 llm_config。
 */
import React from 'react';
import './AiInsightPanel.css';

interface Props {
  title: string;
  /** 来源标注(如 glm-5.3 / AI 基本面),展示在标题右侧 */
  source?: string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** 标题行右侧操作槽(如"生成初稿"按钮) */
  actions?: React.ReactNode;
  children: React.ReactNode;
}

export function AiInsightPanel({title, source, loading, error, onRetry, actions, children}: Props) {
  return (
    <section className="ai-panel">
      <header className="ai-panel__head">
        <h3 className="ai-panel__title">
          ✦ {title}
          {source && <span className="ai-panel__source">{source}</span>}
        </h3>
        {actions && <div className="ai-panel__actions">{actions}</div>}
      </header>
      {loading && (
        <div className="ai-panel__loading" role="status">
          <span className="ui-state__spinner" /> AI 生成中,长文可能需要一两分钟…
        </div>
      )}
      {!loading && error && (
        <div className="ai-panel__error">
          <span>{error}</span>
          {onRetry && (
            <button className="ai-panel__retry" onClick={onRetry}>重试</button>
          )}
        </div>
      )}
      {!loading && !error && <div className="ai-panel__body">{children}</div>}
    </section>
  );
}
```

- [ ] **Step 6: 实现 AiInsightPanel.css**

```css
.ai-panel {
  border: 1px solid var(--color-border); border-radius: 8px;
  padding: var(--space-3); margin: var(--space-2) 0;
  background: var(--color-bg-elevated, rgba(255, 255, 255, 0.02));
}
.ai-panel__head {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-2); flex-wrap: wrap;
}
.ai-panel__title {margin: 0; font-size: var(--text-md); font-weight: 600;}
.ai-panel__source {
  margin-left: var(--space-2); font-size: var(--text-xs); font-weight: 400;
  color: var(--color-text-tertiary);
  border: 1px solid var(--color-border); border-radius: 999px;
  padding: 1px var(--space-2);
}
.ai-panel__actions {display: flex; gap: var(--space-2);}
.ai-panel__loading {
  display: flex; align-items: center; gap: var(--space-2);
  color: var(--color-text-secondary); padding: var(--space-3) 0;
}
.ai-panel__error {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-2); color: var(--color-danger);
  border: 1px solid var(--color-danger); border-radius: 6px;
  padding: var(--space-2) var(--space-3);
}
.ai-panel__retry {
  background: none; border: 1px solid currentColor; color: inherit;
  border-radius: 6px; padding: 2px var(--space-2); cursor: pointer;
}
.ai-panel__body {margin-top: var(--space-2);}
```

- [ ] **Step 7: 构建 + 全量测试 + Commit**

Run: `cd frontend/apps/web && npm run build && npx vitest run`
Expected: 构建成功、测试全绿

```bash
git add frontend/apps/web/src/lib/aiTask.ts \
  frontend/apps/web/src/lib/__tests__/aiTask.test.ts \
  frontend/apps/web/src/components/AiInsightPanel.tsx \
  frontend/apps/web/src/components/AiInsightPanel.css
git commit -m "feat(web): AiInsightPanel统一AI面板外壳+aiTaskReducer状态机——标题/AI徽标/加载骨架/错误重试/内容槽,嵌入式AI统一起点"
```

---

### Task 8: FundamentalReportPanel 迁入 AiInsightPanel 外壳

第一个示范迁移：把 Financial 页 AI 基本面报告面板的 loading/error 自绘块换成 AiInsightPanel 统一壳，业务内容（分组手风琴/护城河/历史列表）作为 children 原样保留。

**Files:**
- Modify: `frontend/apps/web/src/components/FundamentalReportPanel.tsx`

**Interfaces:**
- Consumes: Task 7 `AiInsightPanel`；既有 `useFundamentalAnalysis(symbol)` hook（返回 `{data, loading, error}`）
- Produces: 迁移范式（Task 9 及后续面板照此执行）

- [ ] **Step 1: 加 import**

```tsx
import {AiInsightPanel} from './AiInsightPanel';
```

- [ ] **Step 2: 替换三处自绘状态块**

现有（约 140-149 行）：

```tsx
if (loading) {
  return (
    <div className="fa-panel__loading">
      ...加载中自绘...
    </div>
  );
}
if (error) return <div className="fa-panel__error">{error}</div>;

    return <div className="fa-panel__empty">输入股票代码生成基本面报告</div>;
```

改为统一结构——组件主 return 外包 AiInsightPanel，三个分支收敛进 props/children：

```tsx
if (!symbol) {
  return (
    <AiInsightPanel title="AI 基本面报告" source="LLM">
      <div className="fa-panel__empty">输入股票代码生成基本面报告</div>
    </AiInsightPanel>
  );
}

return (
  <AiInsightPanel
    title="AI 基本面报告"
    source={data?.model_name ?? 'LLM'}
    loading={loading}
    error={error}
  >
    {/* 原 loading/error 之后的主内容 JSX 全部原样移入此处,零业务改动 */}
  </AiInsightPanel>
);
```

要点：原 `if (loading)` / `if (error)` 两个提前 return 分支删除（AiInsightPanel 内部处理）；原主内容 JSX（分组手风琴、护城河、历史报告列表、详情展开）不动。若 `useFundamentalAnalysis` 返回的数据无 `model_name` 字段，`source` 直接用 `'LLM'`（以实际字段为准，执行时 `grep -n "model" src/hooks/useFundamentalAnalysis* src/components/FundamentalReportPanel.tsx` 核对）。

- [ ] **Step 3: 构建验证**

Run: `cd frontend/apps/web && npm run build`
Expected: 构建成功

- [ ] **Step 4: 手测（dev server）**

`/financial` → 输入已配置 LLM 的标的 → AI 基本面 Tab：加载态显示统一骨架文案、报告正文在统一壳内渲染；断开 LLM 配置时错误卡出现"重试"按钮。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/components/FundamentalReportPanel.tsx
git commit -m "refactor(web): AI基本面面板迁入AiInsightPanel统一外壳——loading/error自绘块退役,业务内容零改动"
```

---

### Task 9: ArgumentPanel 迁入 AiInsightPanel 外壳

第二个迁移：论证库的 generating/error 状态换统一壳。此面板是"触发式"（点"生成初稿"→ loading → 结果落列表），用 aiTaskReducer 管理触发态。

**Files:**
- Modify: `frontend/apps/web/src/components/ArgumentPanel.tsx`

**Interfaces:**
- Consumes: Task 7 `AiInsightPanel` + `aiTaskReducer`（generating/error 状态收敛）
- Produces: 嵌入式 AI 迁移完成 2/2 示范式（boom 钻取/行业知识层等面板为后续 followup，不在本轮）

- [ ] **Step 1: 加 import**

```tsx
import {AiInsightPanel} from './AiInsightPanel';
import {aiTaskReducer} from '../lib/aiTask';
```

- [ ] **Step 2: generating/error 双 state 换 reducer**

现有（约 35-36 行）：

```tsx
const [generating, setGenerating] = useState<string | null>(null);
const [error, setError] = useState<string | null>(null);
```

改为：

```tsx
const [task, dispatch] = useReducer(aiTaskReducer, {status: 'idle'});
// generating 语义 = 正在为某 side 生成初稿;保留 side 记录,加载/错误态由 reducer 管
const [genSide, setGenSide] = useState<string | null>(null);
```

（`useReducer` 加入现有 react import；文件内所有 `setGenerating(...)` 调用点改为 `setGenSide(side ?? null)` + 对应 `dispatch({type: 'start'})`，`setError(...)` 调用点改为 `dispatch({type: 'fail', error: msg})`，成功路径 `setGenerating(null)` 改为 `setGenSide(null); dispatch({type: 'done'})`。以 grep 逐点核对：`grep -n "setGenerating\|setError" src/components/ArgumentPanel.tsx`）

- [ ] **Step 3: 外壳替换**

组件主 return 的最外层容器（现为普通 div/section）换成：

```tsx
return (
  <AiInsightPanel
    title="AI 陪练论证库"
    source="LLM 初稿·人工核对"
    loading={task.status === 'loading'}
    error={task.status === 'error' ? task.error : null}
    onRetry={genSide ? () => generateDraft(genSide) : undefined}
  >
    {/* 原面板全部内容 JSX 原样移入(草稿编辑/多空列表/手动新增),零业务改动 */}
  </AiInsightPanel>
);
```

（`generateDraft` 为现有生成函数名，执行时以实际函数名为准——`grep -n "generate\|/generate" src/components/ArgumentPanel.tsx` 核对。）

- [ ] **Step 4: 构建 + 手测 + Commit**

Run: `cd frontend/apps/web && npm run build`
Expected: 构建成功

手测：`/financial` → 论证库 Tab → 生成多头初稿：统一加载文案出现；LLM 失败时错误卡 + 重试可再次触发。

```bash
git add frontend/apps/web/src/components/ArgumentPanel.tsx
git commit -m "refactor(web): 论证库面板迁入AiInsightPanel——generating/error双state收敛为aiTaskReducer,统一加载/错误重试体验"
```

---

### Task 10: WorkflowBar 页头工作流条 + Layout 挂载

在 Layout 的 `<main>` 顶部按当前路由渲染工作流条：环节名徽标 + 上下游直达。25 个页面零改动（Layout 统一挂载）。

**Files:**
- Create: `frontend/apps/web/src/components/WorkflowBar.tsx`
- Create: `frontend/apps/web/src/components/WorkflowBar.css`
- Modify: `frontend/apps/web/src/components/Layout.tsx`（main 内挂载）

**Interfaces:**
- Consumes: Task 3 `getFlowContext(path)`（返回 `{stageTitle, prev?, next?}`）
- Produces: 全站页头工作流条（验收项）

- [ ] **Step 1: 创建 WorkflowBar.tsx**

```tsx
/**
 * WorkflowBar — 页头工作流条(Layout 统一挂载,页面零改动)。
 * 环节徽标 + 上下游直达;getFlowContext 为 null(无 stage 的路由)时不渲染。
 */
import {Link, useLocation} from 'react-router-dom';
import {getFlowContext} from '../config/navigation';
import './WorkflowBar.css';

export function WorkflowBar() {
  const location = useLocation();
  const flow = getFlowContext(location.pathname);
  if (!flow) return null;

  return (
    <nav className="wbar" aria-label="工作流位置">
      <span className="wbar__stage">{flow.stageTitle}</span>
      {flow.prev && (
        <Link className="wbar__link wbar__link--prev" to={flow.prev.path}>
          ← {flow.prev.label}
        </Link>
      )}
      {flow.next && (
        <Link className="wbar__link wbar__link--next" to={flow.next.path}>
          {flow.next.label} →
        </Link>
      )}
    </nav>
  );
}
```

- [ ] **Step 2: 创建 WorkflowBar.css**

```css
.wbar {
  display: flex; align-items: center; gap: var(--space-2);
  font-size: var(--text-xs); color: var(--color-text-tertiary);
  padding: var(--space-1) 0; margin-bottom: var(--space-2);
}
.wbar__stage {
  border: 1px solid var(--color-border); border-radius: 999px;
  padding: 1px var(--space-2); color: var(--color-text-secondary);
}
.wbar__link {
  color: var(--color-text-tertiary); text-decoration: none;
  border-bottom: 1px dashed transparent;
}
.wbar__link:hover {color: var(--color-accent, #5e5ce6); border-bottom-color: currentColor;}
```

- [ ] **Step 3: Layout.tsx 挂载**

import 区加：

```tsx
import {WorkflowBar} from './WorkflowBar';
```

第 104 行 main 改为：

```tsx
<main className="layout__content">
  <WorkflowBar />
  {children}
</main>
```

- [ ] **Step 4: 测试 + 构建**

Run: `cd frontend/apps/web && npx vitest run && npm run build`
Expected: 全绿 + 构建成功

- [ ] **Step 5: 手测清单（dev server）**

- `/financial` 顶部：`研究` 徽标 + `← 选股器` + `买入体检 →`
- `/settings` 顶部：`系统` 徽标、无上下游按钮
- 无 stage 的路由（如未来新增页）不渲染条

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/components/WorkflowBar.tsx \
  frontend/apps/web/src/components/WorkflowBar.css \
  frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(web): 页头WorkflowBar工作流条——Layout统一挂载,环节徽标+上下游直达,25页零改动接入主链"
```

---

### Task 11: Thesis 研究管道直达链接

研究管道表格每行加"直达"列：财务分析 / 买入体检深链（带 symbol 预填）。管道从名单变入口。

**Files:**
- Modify: `frontend/apps/web/src/pages/Thesis.tsx`（研究管道表格，约 1433-1457 行）

**Interfaces:**
- Consumes: 既有管道数据 `pipelineD.rows`（每行含 `symbol`、`stage`、`stage_label`）；Financial 页 `?symbol=` 预填（Financial.tsx:304 已支持）；Checklist 页 `?symbol=`（Financial.tsx:996 已有 `/checklist?symbol=` 用法）
- Produces: 无下游依赖

- [ ] **Step 1: 表头加列**

现有：

```tsx
<thead><tr><th>标的</th><th>阶段</th></tr></thead>
```

改为：

```tsx
<thead><tr><th>标的</th><th>阶段</th><th>直达</th></tr></thead>
```

- [ ] **Step 2: 行加直达链接（Link import 若无则补 `import {Link} from 'react-router-dom';`）**

现有行：

```tsx
<tr key={r.symbol}>
  <td className="mono">{r.symbol}</td>
  <td className={r.stage === 'checked' ? 'neg' : ''}>
    {r.stage_label}{r.stage === 'checked' ? ' ⚠' : ''}
  </td>
</tr>
```

改为：

```tsx
<tr key={r.symbol}>
  <td className="mono">{r.symbol}</td>
  <td className={r.stage === 'checked' ? 'neg' : ''}>
    {r.stage_label}{r.stage === 'checked' ? ' ⚠' : ''}
  </td>
  <td>
    <Link to={`/financial?symbol=${r.symbol}`}>财务</Link>
    {' '}·{' '}
    <Link to={`/checklist?symbol=${r.symbol}`}>体检</Link>
  </td>
</tr>
```

- [ ] **Step 3: 构建 + 手测 + Commit**

Run: `cd frontend/apps/web && npm run build`
Expected: 构建成功

手测：`/thesis` → 展开"研究管道"折叠区 → 点"财务"带 symbol 进财务页、"体检"进买入体检。

```bash
git add frontend/apps/web/src/pages/Thesis.tsx
git commit -m "feat(web): 研究管道加直达列——每标的直链财务分析/买入体检(带symbol预填),管道从名单变入口"
```

---

### Task 12: 全量验证 + 文档同步

**Files:**
- Modify: `docs/value-investing-loop.md`（页面速查表 + 场景文案同步新结构）

**Interfaces:**
- Consumes: Task 1-11 全部完成态
- Produces: spec 验收标准的最终证据

- [ ] **Step 1: 更新 value-investing-loop.md**

- 页面速查表首行加 `| 市场温度 | /indices | 温度计(五档+ERP+水位回测)/指数估值水位/破净率择时 |`
- "我想看现在市场贵不贵"场景段落中"持仓体检页顶部温度卡"改为"市场温度页（/indices）温度计 Tab"，并注明"持仓体检页顶部留有一行精简温度条"
- 页面速查表中"行业分析"行的主功能去掉"破净率择时"，改为"景气热力图/资金流/RS"
- AI 交易助手若在文中出现则删除该句（grep 核对：`grep -n "AI交易\|AI 交易\|ai-workspace" docs/value-investing-loop.md`）

- [ ] **Step 2: spec 验收标准逐条核对**

Run: `cd frontend/apps/web && npx vitest run`
Expected: 全绿（27 项护栏、flow 元数据、routes 双向校验、aiTaskReducer）

Run: `cd frontend/apps/web && npm run build`
Expected: 构建成功

Run: `cd backend && uv run pytest -q`
Expected: 全绿

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader && grep -rn "AIChat\|ai-workspace/trader" frontend/apps/web/src backend/src backend/main.py | grep -v __pycache__`
Expected: 无输出

手测冒烟（dev 前后端起服务）：
- 侧栏 6 组 27 项按六段排列，市场温度页三 Tab 正常，/thesis compact 条深链正确
- 每页页头工作流条显示环节与上下游（settings 也显示"系统"徽标）
- /financial 两个 AI 面板统一壳渲染
- 开始页 7 张场景卡 + 六段工作流图全部指向新结构

- [ ] **Step 3: Commit**

```bash
git add docs/value-investing-loop.md
git commit -m "docs: 工作流指南同步体系化重组——市场温度页速查/温度场景改道/行业分析功能描述更新"
```
