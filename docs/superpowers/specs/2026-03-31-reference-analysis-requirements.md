# YTrader Reference 项目需求吸收清单

**项目**: YTrader 量化交易平台
**版本**: 1.0
**日期**: 2026-03-31
**状态**: 初稿

---

## 一、需求总览

本文档汇总 6 个 reference 项目（OpenBB、Qlib、TradingAgents、TradingAgents-CN、TrendRadar、vnpy）中适合 YTrader 吸收的需求、功能和设计模式，按优先级分组。

---

## 二、优先级定义

| 优先级 | 说明 |
|--------|------|
| **P0** | 核心基础设施，影响整体架构，必须实现 |
| **P1** | 关键业务模块，下一迭代必须实现 |
| **P2** | 平台增强，提升竞争力，后续迭代实现 |
| **P3** | 长期演进，差异化竞争力 |

---

## 三、P0 - 核心基础设施

### P0-1: Provider + Fetcher 分离模式

| 字段 | 内容 |
|------|------|
| **需求** | 数据源适配层重构为 Provider + Fetcher 分离模式 |
| **来源** | OpenBB |
| **理由** | 支持多数据源热插拔，credentials 和数据拉取职责分离 |
| **影响** | 数据层架构 |
| **对应 Spec** | `market-data-design.md` (已更新) |
| **关键代码模式** | `Provider` 管理凭证和 fetcher_dict；`Fetcher` 实现 extract/transform |

### P0-2: 多级缓存架构

| 字段 | 内容 |
|------|------|
| **需求** | 实现 MemCache → ExpressionCache → DatasetCache 三级缓存 |
| **来源** | Qlib |
| **理由** | 数据获取性能提升 50x（7.4s vs 184s HDF5） |
| **影响** | 数据访问性能 |
| **对应 Spec** | `market-data-design.md` (已更新) |

### P0-3: 二进制列式存储

| 字段 | 内容 |
|------|------|
| **需求** | 使用紧凑二进制 .bin 格式替代 CSV/JSON |
| **来源** | Qlib |
| **理由** | 高效字节级读取，避免格式解析开销 |
| **影响** | 存储层 |
| **对应 Spec** | `market-data-design.md` (已更新) |

### P0-4: Alpha158 因子库

| 字段 | 内容 |
|------|------|
| **需求** | 集成 Qlib Alpha158 因子集（158 维因子） |
| **来源** | Qlib / vnpy.alpha |
| **理由** | 策略引擎特征工程基础，业界标准 |
| **影响** | 策略引擎 |
| **对应 Spec** | `ytrader-design.md` (已更新) |

### P0-5: 多 Agent 协作架构

| 字段 | 内容 |
|------|------|
| **需求** | 实现 Analyst Team → Researcher Team → Trader → Risk Management 的多 Agent 协作链 |
| **来源** | TradingAgents |
| **理由** | 模拟真实交易公司，多视角决策，避免单一偏差 |
| **影响** | AI Lab 模块核心架构 |
| **对应 Spec** | `2026-03-31-multi-agent-trading-design.md` (新建) |

---

## 四、P1 - 关键业务模块

### P1-1: 舆情情报聚合

| 字段 | 内容 |
|------|------|
| **需求** | 多源新闻聚合（11+ 平台）+ 关键词过滤 + 加权趋势评分 |
| **来源** | TrendRadar |
| **理由** | AI Lab 的新闻数据输入；差异化功能 |
| **影响** | 新增 News Intelligence 模块 |
| **对应 Spec** | `2026-03-31-news-intelligence-design.md` (新建) |
| **关键指标** | 排名60% + 频率30% + 热度10% 加权评分；3种推送模式 |

### P1-2: MCP Server

| 字段 | 内容 |
|------|------|
| **需求** | 基于 FastMCP 2.0 实现 MCP 工具服务器 |
| **来源** | TrendRadar |
| **理由** | AI Agent（Claude Desktop、Cherry Studio 等）调用平台工具的标准协议 |
| **影响** | AI 集成能力 |
| **对应 Spec** | `2026-03-31-mcp-tool-server-design.md` (新建) |

### P1-3: 多 LLM Provider 集成

| 字段 | 内容 |
|------|------|
| **需求** | Provider 工厂模式，支持 DeepSeek/DashScope/千帆等国产模型 |
| **来源** | TradingAgents-CN |
| **理由** | 国产化需求；成本优化；避免单一 Provider 锁定 |
| **影响** | AI 基础设施 |
| **对应 Spec** | `2026-03-31-multi-llm-provider-design.md` (新建) |
| **关键功能** | 混合调用模式（deep_think/quick_think）；Token 用量追踪；降级策略 |

### P1-4: ChromaDB 向量记忆

| 字段 | 内容 |
|------|------|
| **需求** | 多 Agent 决策上下文存储，相似情境检索 |
| **来源** | TradingAgents |
| **理由** | Agent 从历史决策中学习 |
| **影响** | AI Lab 记忆系统 |
| **对应 Spec** | `2026-03-31-multi-agent-trading-design.md` |

### P1-5: OBBject 统一结果封装

| 字段 | 内容 |
|------|------|
| **需求** | 所有 API 返回值统一封装，保留 provider、warnings、chart 元数据 |
| **来源** | OpenBB |
| **理由** | API 返回值标准化；保留数据来源和警告信息 |
| **影响** | API 层 |
| **对应 Spec** | `market-data-design.md` (已更新) |

---

## 五、P2 - 平台增强

### P2-1: RD-Agent 因子挖掘引擎

| 字段 | 内容 |
|------|------|
| **需求** | LLM 驱动的自动化因子/模型优化循环 |
| **来源** | Qlib RD-Agent |
| **理由** | 持续自动发现新 alpha 因子 |
| **影响** | AI Lab 研究能力 |
| **对应 Spec** | `2026-03-31-rd-agent-design.md` (新建) |

### P2-2: 多通道推送系统

| 字段 | 内容 |
|------|------|
| **需求** | 企业微信/飞书/钉钉/Telegram/邮件推送 |
| **来源** | TrendRadar |
| **理由** | 告警和舆情实时通知 |
| **影响** | 通知系统 |
| **对应 Spec** | `2026-03-31-news-intelligence-design.md` |

### P2-3: vnpy Gateway 插件模式

| 字段 | 内容 |
|------|------|
| **需求** | 扩展交易接口（CTP/XTP/IB 等） |
| **来源** | vnpy |
| **理由** | 对接更多券商和柜台 |
| **影响** | 交易执行层 |
| **对应 Spec** | 待补充 |

### P2-4: Model Zoo 架构

| 字段 | 内容 |
|------|------|
| **需求** | 20+ 模型的注册与比较框架 |
| **来源** | Qlib |
| **理由** | 快速试验不同模型；对比基准 |
| **影响** | 策略引擎 |
| **对应 Spec** | `ytrader-design.md` (已更新) |

### P2-5: qrun YAML 工作流

| 字段 | 内容 |
|------|------|
| **需求** | YAML 配置的自动化研究流程 |
| **来源** | Qlib |
| **理由** | 实验可复现性 |
| **影响** | 研究流程 |
| **对应 Spec** | `ytrader-design.md` (已更新) |

### P2-6: FastAPI + MongoDB + Redis 后端架构

| 字段 | 内容 |
|------|------|
| **需求** | 企业级后端架构，多租户支持 |
| **来源** | TradingAgents-CN |
| **理由** | User auth、角色管理、batch analysis、report export |
| **影响** | 后端架构 |
| **对应 Spec** | 待补充 |

---

## 六、P3 - 长期演进

### P3-1: 强化学习交易策略

| 字段 | 内容 |
|------|------|
| **需求** | RL 框架支持连续决策 |
| **来源** | Qlib (rl module) |
| **影响** | 策略引擎 |

### P3-2: 人类参与式决策

| 字段 | 内容 |
|------|------|
| **需求** | 用户在 Agent 讨论中实时插话确认 |
| **来源** | TradingAgents |
| **影响** | AI Lab 交互模式 |

### P3-3: LoRA 微调个性化金融 LLM

| 字段 | 内容 |
|------|------|
| **需求** | 基于用户风险偏好的个性化投顾 |
| **来源** | FinGPT (RLHF) |
| **影响** | AI Lab |

### P3-4: vnpy EventEngine 事件驱动架构

| 字段 | 内容 |
|------|------|
| **需求** | 事件驱动的订单/持仓/风控事件流 |
| **来源** | vnpy |
| **影响** | 交易执行层 |

### P3-5: vnpy BaseApp 插件生态

| 字段 | 内容 |
|------|------|
| **需求** | App 动态注册和 MainEngine 编排 |
| **来源** | vnpy |
| **影响** | 平台可扩展性 |

---

## 七、关键技术模式映射

| 模式 | 来源 | 吸收位置 |
|------|------|---------|
| Provider + Fetcher 抽象 | OpenBB | market-data-design.md (P0-1) |
| OBBject 统一结果封装 | OpenBB | market-data-design.md (P1-5) |
| 多级缓存 (Mem/Expr/Dataset) | Qlib | market-data-design.md (P0-2) |
| 二进制列式存储 | Qlib | market-data-design.md (P0-3) |
| qrun YAML 工作流 | Qlib | ytrader-design.md (P2-5) |
| Model Zoo 架构 | Qlib | ytrader-design.md (P2-4) |
| RD-Agent 自动化循环 | Qlib RD-Agent | rd-agent-design.md (P2-1) |
| LangGraph 状态机 | TradingAgents | multi-agent-trading-design.md (P0-5) |
| ChromaDB 向量记忆 | TradingAgents | multi-agent-trading-design.md (P1-4) |
| 多 LLM Provider 工厂 | TradingAgents-CN | multi-llm-provider-design.md (P1-3) |
| AkShare/Tushare 中国数据 | TradingAgents-CN | market-data-design.md |
| FastMCP 工具服务器 | TrendRadar | mcp-tool-server-design.md (P1-2) |
| 加权趋势评分算法 | TrendRadar | news-intelligence-design.md (P1-1) |
| 多通道推送架构 | TrendRadar | news-intelligence-design.md (P2-2) |
| Gateway 适配器模式 | vnpy | P2-3 |
| EventEngine 事件驱动 | vnpy | P3-4 |
| BaseApp 插件生态 | vnpy | P3-5 |

---

## 八、实现状态追踪

| ID | 需求 | Spec 文件 | 状态 |
|----|------|-----------|------|
| P0-1 | Provider + Fetcher 分离模式 | market-data-design.md | 已更新 |
| P0-2 | 多级缓存架构 | market-data-design.md | 已更新 |
| P0-3 | 二进制列式存储 | market-data-design.md | 已更新 |
| P0-4 | Alpha158 因子库 | ytrader-design.md | 已更新 |
| P0-5 | 多 Agent 协作架构 | multi-agent-trading-design.md | 已新建 |
| P1-1 | 舆情情报聚合 | news-intelligence-design.md | 已新建 |
| P1-2 | MCP Server | mcp-tool-server-design.md | 已新建 |
| P1-3 | 多 LLM Provider 集成 | multi-llm-provider-design.md | 已新建 |
| P1-4 | ChromaDB 向量记忆 | multi-agent-trading-design.md | 已新建 |
| P1-5 | OBBject 统一结果封装 | market-data-design.md | 已更新 |
| P2-1 | RD-Agent 因子挖掘引擎 | rd-agent-design.md | 已新建 |
| P2-2 | 多通道推送系统 | news-intelligence-design.md | 已新建 |
| P2-3 | vnpy Gateway 插件模式 | 待补充 | 待设计 |
| P2-4 | Model Zoo 架构 | ytrader-design.md | 已更新 |
| P2-5 | qrun YAML 工作流 | ytrader-design.md | 已更新 |
| P2-6 | FastAPI + MongoDB + Redis | 待补充 | 待设计 |
| P3-1 | 强化学习交易策略 | - | 待规划 |
| P3-2 | 人类参与式决策 | multi-agent-trading-design.md | 已设计 |
| P3-3 | LoRA 微调个性化金融 LLM | - | 待规划 |
| P3-4 | vnpy EventEngine | - | 待规划 |
| P3-5 | vnpy BaseApp 插件生态 | - | 待规划 |

---

**文档版本**: 1.0
**最后更新**: 2026-03-31
