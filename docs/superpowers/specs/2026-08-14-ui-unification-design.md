# UI 统一化设计 — 消灭"四不像"

**日期**: 2026-08-14
**状态**: 已定稿（用户未响应澄清提问，按推荐默认方案执行，决策均可在实施中调整）
**范围**: 仅前端（`frontend/apps/web/src`）。零功能变更、零后端变更、零路由变更。

---

## 1. 问题陈述

全站 61 个页面 / 44 个 CSS 文件存在系统性视觉割裂（用户原话："四不像"）：

1. **涨跌色语义反向**：国家队页"涨=红"，指数页/板块页"涨=绿"（`--color-up/--color-down` 从未在 global.css 定义，三处各自给了矛盾的 fallback）。
2. **三套暗色色板并存**：Apple Dark（global.css 令牌）+ GitHub Dark（13 文件）+ Tailwind（16 文件）。仅红色就有 6 种值。
3. **34 个 CSS 变量被引用但未定义**（`--text`、`--surface`、`--accent`…），静默失效或靠各自的 fallback 硬编码。
4. **基础组件每页重写**：按钮 33 套、卡片 17 套，Tab/Modal/表格/Loading/空态/错误态全部各画各的；global.css 的 `.card` 形同虚设。
5. **信息架构割裂**：侧边栏分组英文、条目中英混排；`/ai-workspace/*` 4 条路由在导航中不可达；回测/交易/组合概念重复但无清晰分层。
6. **排版失控**：字号 30+ 种值（令牌/px/rem 三套单位并存）、圆角 9 种硬编码、卡片 padding 四种单位、emoji 只在部分页面出现。
7. **假主题开关**：Settings 里有亮/暗切换，但页面大量硬编码暗色，切亮色必然花屏。

## 2. 已定决策（默认方案，用户未答复时采用）

| 决策点 | 结论 | 理由 |
|---|---|---|
| 范围 | 前端视觉 + 信息架构 | "看起来自然"是 UI 问题；后端不动、功能零变化、风险可控 |
| 视觉基准 | 现有 Apple Dark 令牌（global.css） | 令牌体系已完整，映射收敛可预测；不重新设计 |
| 涨跌色 | A股惯例：**红涨绿跌**（`--color-up`=#ff453a 系、`--color-down`=#30d158 系） | 既有提交"涨跌幅A股配色"已确立此约定，用户是A股用户 |
| 文案语言 | 统一中文（侧边栏、标题、按钮、状态文案） | 侧边栏中英混排是割裂感主要来源之一 |
| emoji | 从标题/按钮中全部移除，用 `icons.tsx` SVG 图标 | 专业交易终端风格，且图标库已存在 |
| 主题 | 仅暗色；隐藏 Settings 里的亮色开关 | 亮色主题需全套 fill/border 令牌重定义，超出本次范围 |
| 路由 | 所有路由保持不变 | 不破坏书签/后端集成；只重组导航呈现 |

## 3. 目标状态

**单一真相源**：global.css 的设计令牌是唯一起点。任何页面 CSS/TSX 中不再出现色板级硬编码（hex/rgb 颜色一律来自令牌；图表色板来自共享模块）。

**一套基础组件**：`src/components/ui/` 下提供 `Button`、`Card`、`Tabs`、`Modal`、`PageHeader`、`StateView`（loading/empty/error 三态）+ `lib/chartTheme.ts`（recharts 统一色板/坐标轴样式）。

**一个清晰的导航**：中文分组 + 中文条目，AI 工作台可见，同类概念命名分层清晰。

## 4. 实施设计

### 阶段 0 — 令牌补齐（治本起点）

global.css 增补：

```css
/* 涨跌语义色 — A股红涨绿跌，全站唯一定义点 */
--color-up: #ff453a;
--color-up-light: rgba(255, 69, 58, 0.12);
--color-down: #30d158;
--color-down-light: rgba(48, 209, 88, 0.12);
--color-flat: var(--color-text-secondary);

/* 图表色板 — 与令牌同源，供 lib/chartTheme.ts 与 ECharts/recharts 引用 */
--chart-1..8: #0a84ff #30d158 #ff9f0a #bf5af2 #64d2ff #ff453a #ffd60a #5e5ce6
```

同时修复 34 个未定义变量引用：一律改写为正确令牌名（`--text`→`--color-text`、`--surface`→`--color-surface`、`--accent`→`--color-accent`、`--font-sans`→`--font-body` 等），删除各处 fallback 硬编码。

### 阶段 1 — 色板收敛（机械替换，脚本 + 人工核对）

映射表（GitHub Dark / Tailwind → Apple 令牌）：

| 外来色 | 映射到 |
|---|---|
| `#0d1117` `#0f1216` `#1a1a1a` | `var(--color-background)` |
| `#161b22` `#21262d` `#1e1e2e` | `var(--color-surface)` |
| `#30363d` | `var(--color-border-strong)` |
| `#8b949e` `#9ca3af` `#6b7280` | `var(--color-text-secondary)` |
| `#c9d1d9` `#e6edf3` | `var(--color-text)` |
| `#58a6ff` `#3b82f6` `#2563eb` | `var(--color-accent)` |
| `#f85149` `#ef4444` `#dc2626` `#e54d4d` | `var(--color-danger)` |
| `#3fb950` `#22c55e` `#16a34a` `#2eb872` | `var(--color-success)` |
| `#d29922` `#fbbf24` `#d97706` | `var(--color-warning)` |
| `#64748b` | `var(--color-text-tertiary)` |

**涨跌色专项**：所有表达"涨跌/变动方向"的红绿（含图表 `stroke/fill`、涨跌幅数字、箭头）统一改用 `var(--color-up)/var(--color-down)`；语义为"成功/危险"的才用 `--color-success/--color-danger`。重点文件：`NationalTeam.css:39-40`、`SectorScan.tsx:75-76`、`Indices.tsx:418-419` 及全量 grep 复查。

TSX 内联色（ECharts option、recharts 属性）同样按映射表替换为从 `lib/chartTheme.ts` 导出的常量。

### 阶段 2 — 排版收敛

- 字号：`11px→var(--text-xs)`、`13px/0.8125rem→var(--text-sm)`、`14px/0.875rem→var(--text-sm 或 base 按语境)`、`15px→var(--text-base)`、`18px/1.125rem→var(--text-lg)`、`22px→var(--text-xl)`、`28px→var(--text-2xl)`；`10px/9px` 等超小字→`var(--text-xs)` 并由视觉复核。
- 圆角：`2-4px→--radius-sm`、`6-8px→--radius-sm/md 按语境`、`10-12px→--radius-md`、`14-16px→--radius-lg`、`999px/100px→--radius-pill`、`50%` 保留（圆用）。
- 阴影：全部硬编码 box-shadow → 最近似的 `--shadow-sm/md/lg/xl`。
- 卡片 padding：统一 `var(--space-4)`（紧凑）/ `var(--space-5)`（标准）两档；长尾值就近归档。
- 数字列：涨跌/金额/百分比统一加 `.num`（tabular-nums）。

### 阶段 3 — 共享基础组件

新建 `src/components/ui/`：

- **Button**：`variant: primary|secondary|ghost|danger`，`size: sm|md`，`loading` 态。替代 33 套页面按钮。
- **Card**：包装全局 `.card`，`padding: compact|normal`，`interactive`。
- **Tabs**：受控/非受控，统一 `--active` 视觉。替代 9 套页内 Tab。
- **Modal**：统一遮罩（`--color-overlay` + `--z-modal`）、圆角、关闭交互。替代 4 套自制弹窗。
- **PageHeader**：统一页面标题（一律 `h1` + 可选副标题/操作区），替代各页 `xxx__title`。
- **StateView**：`loading|empty|error` 三态统一组件（骨架屏采用现有 `.skeleton`；空态文案统一"暂无×××"；错误态统一"加载失败 + 重试"）。替代 8 套 loading 和散乱空态/错误态。

迁移策略：**逐页替换**。页面 CSS 中对应类删除，TSX 改用组件。每页迁移后该页 CSS 行数应净减少。

### 阶段 4 — 信息架构与文案

侧边栏重组（全中文，路由不变）：

```
总览    总览 / 行情 / 指数 / 自选股
研究    财务报表 / 选股器 / 估值 / 因子 / 宏观政策 / 国家队 / 情报 / 报告 / 名人持仓 / 博客
交易    交易 / 做T实验室
策略    策略 / 组合 / 回测 / 长期回测 / 永久组合
分析    分析 / 风险 / 预警
AI 工作台  AI交易助手 / 写作助手 / LLM日志 / 工作台设置
系统    设置 / 系统日志
```

- `/ai-workspace/*` 4 条路由全部挂入导航（当前不可达是硬伤）。
- 页面标题层级统一：所有页面主标题 `h1`（经 PageHeader）。
- 全站 emoji 移除（标题/按钮），功能性图标用 `icons.tsx`。
- Settings 隐藏亮/暗切换（保留 useTheme 的 applyTheme 以防回退，仅 UI 不展示）。
- 空态/加载态文案统一为中文规范（"加载中…""暂无数据""加载失败，请重试"）。

### 阶段 5 — 图表主题统一

`lib/chartTheme.ts`：

```ts
export const CHART_COLORS = ['#0a84ff', '#30d158', '#ff9f0a', '#bf5af2', '#64d2ff', '#ff453a', '#ffd60a', '#5e5ce6'];
export const chartAxisProps = { … }   // 统一 tick 颜色/字号/网格线
export const chartTooltipProps = { … } // 统一 tooltip 样式
```

recharts 21 处、echarts 2 处全部改用该模块；热力图色带（LiveTabs 两套黄橙）统一为单一刻度。

### 阶段 6 — 验证

1. `pnpm build`（或项目等价命令）通过、TypeScript 无新错误。
2. 全仓 grep 断言：CSS/TSX 中不再出现映射表里的外来 hex；`var(--color-up`/`var(--color-down` 的 fallback 硬编码为 0 处。
3. 启动 dev server，用浏览器逐页截图抽查（重点：国家队 vs 指数 vs 板块——涨跌色必须一致红涨绿跌；Settings；AI 工作台入口）。
4. 回归：所有路由可达、无 console 报错。

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 批量替换误伤（如把语义"成功"错换成"跌"） | 阶段 1 拆两步：先机械映射中性色，涨跌色逐处人工判语义 |
| 页面迁移引入回归 | 逐页小步提交；每阶段后 build + 抽查 |
| 体量大（61 页） | 阶段 1/2 脚本化；阶段 3 优先高频页面，其余按同一模式批量推进 |
| 未提交的 DCF 工作区改动 | 不触碰 `financial_detail_handler.py`、`dcf.py`、`DcfPanel.tsx`、`useDcf.ts`、`test_dcf_monte_carlo.py`；提交时选择性 stage |

## 6. 明确不做（本次）

- 不合并/删除任何页面或路由
- 不动后端、不改任何 API
- 不做亮色主题（仅预留：所有颜色走令牌后天然具备可行性）
- 不接 i18n key 化（文案直接写中文；i18n 基建保留）
- 不做 BEM 类名全量重命名（仅新组件遵循 BEM）
