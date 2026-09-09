# AI 工作台信息架构方案

> 把分散的 AI 能力收拢进一个顶级「AI 工作台」场景。blog 退回纯文稿管理。
> 上下文丢失时从本文档恢复。三个分歧已定（见下）。

## 已定决策
- **不合并**：写作助手、交易问答分开（各自独立应用，不混进同一 agent）。
- **日志拆两处**：大模型运行日志（LLM trace / MCP / Copilot）在 AI 工作台；系统运行日志在 System。
- **blog 旧生成入口全删**：blog 只管草稿，生成一律去工作台写作助手。
- **路由前缀**：`/ai-workspace`。

## 目标菜单结构（全局侧边栏）

```
Overview        Dashboard / Market / Trading / Alerts      （移除 AI Copilot）
Strategy        Strategies / Portfolio / Backtest           （不变）
Analytics       Analytics / Risk / Factors                 （不变）
AI 工作台 ★     写作助手 / 交易问答 / 大模型日志 / 设置      （新建顶级分组）
Research        Intel / Reports / Financial / Celebrity / Blog（blog 瘦身）
System          设置 / 系统日志                             （加系统日志）
```

## 路由与页面归属

| 路由 | 页面 | 来源 | 动作 |
|---|---|---|---|
| `/ai-workspace/writer` | 写作助手 | blog 页「对话生成」tab（BlogChat.tsx） | 抽出为独立页面 |
| `/ai-workspace/trader` | 交易问答 | `/ai-chat`（AIChat.tsx） | 迁路由，实现不改 |
| `/ai-workspace/llm-logs` | 大模型日志 | blog 页「执行日志」tab（ExecutionLog.tsx） | 抽出，扩为工作台级 LLM 日志 |
| `/ai-workspace/settings` | 工作台设置 | blog 页「提示词/模型」tab（PromptConsole/ModelConsole） | 抽出为工作台配置页 |
| `/blog` | Blog 文稿管理（瘦身） | 现有 blog 页 | 只留草稿列表+预览+发布，删 4 个 tab + 旧生成入口 |

## 迁移项清单

### 写作助手 `/ai-workspace/writer`
- `BlogChat.tsx` → 独立页面（已是自包含组件，直接挂路由）
- 后端端点不变（`/blog/agent/chat`、`/resume`、`/sessions`），前端前缀暂不改

### 交易问答 `/ai-workspace/trader`
- `AIChat.tsx` 改路由 `/ai-chat` → `/ai-workspace/trader`
- navGroups 从 Overview 移到 AI 工作台
- 后端 `/ai/chat` 不变

### 大模型日志 `/ai-workspace/llm-logs`
- `ExecutionLog.tsx` 抽出为工作台级页面
- 追踪所有 agent run（不只 blog），现在主要 blog 生成
- 从 blog 页移除该 tab

### 工作台设置 `/ai-workspace/settings`
- `PromptConsole.tsx` + `ModelConsole.tsx` 抽出
- 这俩是 agent 级配置（prompt 模板/LLM 参数），提到工作台对
- 从 blog 页移除 prompts/models tab

### blog 页瘦身 `/blog`
- 删 viewMode：`chat / prompts / models / logs`
- 只留 `drafts`（草稿列表 + 预览 + 发布）
- 删旧的生成入口（主题预设按钮 / 向导 / 自定义生成）——分歧2已定全删
- 保留草稿 CRUD + 配图 + 发布

## 实施顺序（低风险 → 高）
1. 路由 + navGroups：加新分组、新路由、重定向 `/ai-chat`→`/ai-workspace/trader`
2. 写作助手：BlogChat 独立挂 `/ai-workspace/writer`
3. 交易问答：AIChat 迁路由
4. 工作台设置页：PromptConsole+ModelConsole 挂 `/ai-workspace/settings`
5. 大模型日志页：ExecutionLog 挂 `/ai-workspace/llm-logs`
6. blog 瘦身：删 4 tab + 旧生成入口
7. 验证：各页面可达、blog 只剩文稿、旧路由重定向

## 图标
- AI 工作台分组：sparkles/robot（看 Icons 有什么）
- 写作助手：blog icon 或 pen
- 交易问答：copilot icon（沿用）
