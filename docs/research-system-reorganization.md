# Research / System 菜单与功能重组规划

> 日期：2026-06-16
> 范围：前端 `frontend/apps/web` 侧边栏 **Research**、**System** 两个一级菜单的结构与功能项整合
> 决策方向：**完整重组** —— 订阅并入 Intel、AI 配置统一成页、Settings 精简、错位项归位
> 推进方式：本文档定稿 → 分阶段逐步执行（每阶段独立验收 + commit）

---

## 1. 背景与目标

Research / System 两个分组存在三类问题：**功能错位**（业务功能塞进 System）、**订阅割裂**（订阅管理散落 3 处）、**配置分散**（AI 配置两处 + Settings 臃肿）。

**目标**
- 按功能本质归类：研究/分析 → Research，配置 → System
- 去重：订阅三处合一、AI 配置两处合一
- System 只保留「系统配置」，业务功能（AI 对话、告警、大V）归位到合适的业务分组

---

## 2. 现状诊断

### Research 分组（6 项，偏多 + 订阅割裂）
| 菜单 | 路由 | 功能 | 问题 |
|------|------|------|------|
| Reports | /reports | AI 日报（账户/业绩/交易/市场/告警/回测）+ 飞书推送 + 历史 | ✓ |
| Financial | /financial | 财务分析（利润表/资产负债/现金流） | ✓ |
| Intel | /intel | 资讯中心 4 tabs（AI分析/源看板/**订阅管理**/新闻管理） | 自带订阅管理 tab |
| Blog | /blog | AI 微信公众号博客（BlogDraft） | △ 与 Reports 同为 AI 内容产出 |
| Subscriptions | /subscriptions | 订阅源 CRUD + sync | ❌ 与 Intel 订阅 tab 重叠 |
| Sub Results | /subscription-results | 订阅抓取结果查看 | ❌ 与上面割裂成两页 |

### System 分组（5 项，错位 + 配置分散）
| 菜单 | 路由 | 功能 | 问题 |
|------|------|------|------|
| AI Copilot | /ai-chat | AI 交易对话 | ❌ 常用工具，非系统配置 |
| Alerts | /alerts | 价格告警 | ❌ 交易监控功能，非系统配置 |
| Agent Config | /agent-config | agents / pipeline / prompts 三 tab | ❌ 与 Settings AI 配置重叠（Pipeline 尤其） |
| Celebrities | /celebrities | 大V观点管理 | ❌ 研究素材，非系统配置 |
| Settings | /settings | LLM/MCP/Pipeline/Skills/工具台/主题/语言 (67KB) | △ 臃肿，AI 配置与系统设置混杂 |

**三大病灶**
1. 订阅管理散落 3 处（Intel `subscriptions` tab + Subscriptions + SubscriptionResults）
2. System 塞了 3 个业务功能（AIChat / Alerts / Celebrity 都不是系统配置）
3. AI 配置分散两处（AgentConfig + Settings），且 Settings 67KB 臃肿

---

## 3. 目标菜单结构（最终态）

```
Overview:  Dashboard · Market · Trading · AI Copilot · Alerts     ← AI Copilot/Alerts 从 System 移入
Strategy:  Strategies · Portfolio · Backtest                       （不变）
Analytics: Analytics · Risk · Factors                              （不变）
Research:  Intel · Reports · Financial · Celebrity · Blog          ← 去 Sub/SubResults，加 Celebrity
System:    AI 配置 · 系统设置                                      ← 仅 2 项配置
```

---

## 4. 整合动作详细方案

### 动作 A — 菜单重组（Layout.tsx）
- `Overview` 增：AI Copilot (/ai-chat)、Alerts (/alerts)
- `Research` 改为：Intel · Reports · Financial · Celebrity · Blog（去 Subscriptions、Sub Results，加 Celebrity）
- `System` 改为：AI 配置 (暂指 /agent-config) · 系统设置 (/settings)
- 路由（App.tsx）**本阶段全部保留**，避免删菜单导致直达链接 404

### 动作 B — 订阅整合到 Intel（删 2 页）
- Intel 已有 `SubscriptionsTab`（`activeTab='subscriptions'`）作为基础
- 迁移 `Subscriptions.tsx` 的能力：Add / toggle / delete / sync（调 `/subscriptions*` API）→ 并入 Intel subscriptions tab
- 迁移 `SubscriptionResults.tsx` 的结果查看 → 作为 Intel subscriptions tab 内的子视图或 tab 内切换
- 删除 `Subscriptions.tsx`、`SubscriptionResults.tsx`
- `App.tsx` 删除 `/subscriptions`、`/subscription-results` 路由

### 动作 C — AI 配置统一页（合并 AgentConfig + Settings AI 部分）
- 统一为「AI 配置」页，tab 结构建议：
  - LLM（迁自 Settings：`llmConfigs` / `/llm/configs` / 测试）
  - MCP（迁自 Settings：`mcpServers` / 测试 / 工具台 `toolConsole*`）
  - Agents（来自 AgentConfig：agents 列表 + system_prompt 编辑）
  - Pipeline（**去重**：AgentConfig 与 Settings 都有，合一）
  - Prompts（来自 AgentConfig：`/prompts` CRUD）
  - Skills（迁自 Settings：`skills` / 步骤 / 执行）
  - 工具台（迁自 Settings toolConsole，或并入 MCP tab）
- 可基于 `AgentConfig.tsx` 扩展（它已有 tab 框架），或新建 `AiConfig.tsx`

### 动作 D — Settings 精简
- Settings 仅保留纯系统设置：theme、apiBase（API 地址）、language、health（系统健康）
- 移除 llm / mcp / toolConsole / pipeline / skills（迁至 AI 配置页）

---

## 5. 分阶段实施计划

### 阶段 1 — 菜单重组（动作 A） · 风险低 · 可逆
**步骤**
1. 改 `Layout.tsx` 的 `navGroups`（line 176–222）为目标结构
2. `App.tsx` 路由全部保留不动
3. 验收：5 个分组菜单项正确，各页面点达无 404

**目标 navGroups**
```ts
Overview:  Dashboard, Market, Trading, AI Copilot(/ai-chat), Alerts(/alerts)
Strategy:  Strategies, Portfolio, Backtest
Analytics: Analytics, Risk, Factors
Research:  Intel(/intel), Reports(/reports), Financial(/financial), Celebrity(/celebrities), Blog(/blog)
System:    AI 配置(/agent-config), 系统设置(/settings)
```
> Icon：AI 配置沿用 `Icon.copilot`；系统设置 `Icon.settings`；Celebrity 沿用 `Icon.reports`。

### 阶段 2 — 订阅整合（动作 B） · 风险中
**步骤**
1. 通读 `Intel.tsx` 的 `SubscriptionsTab` 现有能力（`fetchDataSources`、sync、groups/items 渲染）
2. 将 `Subscriptions.tsx` 的 Add/toggle/delete/sync CRUD 补入 SubscriptionsTab
3. 将 `SubscriptionResults.tsx` 的结果查看并入（tab 内视图切换）
4. 删除 `Subscriptions.tsx`、`SubscriptionResults.tsx` + 对应 CSS
5. `App.tsx` 删除 `/subscriptions`、`/subscription-results` 路由
6. 验收：Intel 订阅 tab 可完成 原2页 的全部操作

### 阶段 3 — AI 配置统一 + Settings 精简（动作 C + D） · 风险高
**步骤**
1. 确定 AI 配置页载体（扩展 AgentConfig.tsx 或新建 AiConfig.tsx），定 tab 结构
2. 从 `Settings.tsx` 抽出 llm / mcp / toolConsole / pipeline / skills 状态与 UI → 迁入 AI 配置页
3. 并入 `AgentConfig.tsx` 的 agents / prompts；去重 Pipeline
4. 精简 `Settings.tsx`，仅留 theme / apiBase / language / health
5. `App.tsx`：`/agent-config` 指向新 AI 配置页（或新增 `/ai-config`，菜单同步）
6. 验收：AI 配置页各 tab 功能等价于原 AgentConfig + Settings AI 部分；Settings 只剩系统设置

---

## 6. 涉及文件清单

| 文件 | 阶段 | 动作 |
|------|------|------|
| `components/Layout.tsx` | 1 | 改 navGroups |
| `App.tsx` | 1/2/3 | 路由保留 → 删订阅路由 → AI 配置路由 |
| `pages/Intel.tsx` (+Intel.css) | 2 | 吸收订阅 CRUD + 结果视图 |
| `pages/Subscriptions.tsx` | 2 | 删除 |
| `pages/SubscriptionResults.tsx` | 2 | 删除 |
| `pages/AgentConfig.tsx` | 3 | 改造为 AI 配置页（或被新页替代） |
| `pages/Settings.tsx` (+Settings.css) | 3 | 精简，移除 AI 配置部分 |
| 新 `pages/AiConfig.tsx`（可选） | 3 | 若不扩展 AgentConfig 则新建 |

---

## 7. 风险与回滚
- 每阶段独立 commit，可单独回滚
- 阶段 1 仅改菜单数组，最安全，先做
- 阶段 2/3 涉及页面合并/拆分，执行前备份原文件（git 已覆盖）
- 合并功能时逐一对照原页面的 API 调用与交互，防止丢功能
- 视觉沿用已对齐的 Intel/Settings 深色设计系统（见 memory: frontend-css-theme-system）
