# News Agent Deep Analysis System Design

Date: 2026-06-04
Status: Draft

## Overview

在现有 Intel 新闻采集系统基础上，新增基于 LangGraph 的多 Agent 深度分析通道。采集的新闻经过现有 processor 快速处理后，可选触发多 Agent 深度分析：打标签、名人多视角辩论、事件关联趋势分析、综合报告生成。

Agent 编排拓扑、Prompt Template、名人知识库均存入数据库，前端可管理。

## Requirements

1. **4 个 Agent**：TaggingAgent、CelebrityAgent（子图，多名人）、TrendAgent、ReportAgent
2. **多轮辩论**：CelebrityAgent 内部名人之间可互相质疑和修正
3. **名人动态管理**：名人从数据库运行时读取，随时增删，影响并行 fan-out 数量
4. **数据库驱动配置**：Agent 配置、Prompt Template、Pipeline 编排存 DB
5. **前端可管理**：页面可编辑 Agent、Prompt、名人知识库、Pipeline 配置
6. **双通道共存**：保留现有 processor 做快速处理，新增 Agent 系统做深度分析
7. **触发方式**：采集后自动触发 + 手动可重跑单条新闻
8. **TDD 驱动开发**：先构建测试集和测试用例，驱动 Agent 实现和效果验证

## Architecture

### 系统定位

```
新闻采集 → 现有 Processor（快速通道：摘要/情感/标签）
         → Agent Deep Analysis（深度通道：多 Agent 辩论/分析/报告）
```

两个通道独立运行，深度分析结果是快速处理的补充。

### LangGraph 工作流拓扑

```
                         ┌──────────────┐
                         │  START       │
                         │  (NewsItem)  │
                         └──────┬───────┘
                                │
                         ┌──────▼───────┐
                         │ TaggingAgent │  打标签（主题、行业、情绪）
                         └──────┬───────┘
                                │
                    ┌───────────▼───────────┐
                    │   CelebrityAgent      │  LangGraph 子图
                    │  ┌─────────────────┐  │
                    │  │ Fan-out (Send)  │  │  运行时从 DB 动态读取名人列表
                    │  │  ├ MuskPersona  │  │  每个名人并行分析
                    │  │  ├ BuffettPersona│ │
                    │  │  └ DalioPersona │  │
                    │  │        │        │  │
                    │  │  Fan-in (汇总)  │  │  Annotated[list, operator.add]
                    │  │        │        │  │
                    │  │  Debate Rounds  │  │  名人间多轮辩论，轮数由 DB 配置
                    │  │        │        │  │
                    │  │  Synthesis      │  │  汇总辩论结果为共识
                    │  └────────┬────────┘  │
                    └──────────┼───────────┘
                               │
                    ┌──────────▼───────────┐
                    │    TrendAgent        │  事件关联/趋势分析
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │    ReportAgent       │  综合报告生成
                    └──────────┬───────────┘
                               │
                         ┌─────▼─────┐
                         │    END    │
                         └───────────┘
```

### CelebrityAgent 子图内部流程

1. **Fan-out**: `Send` API 动态创建 N 个 `persona_analyze` 节点，N = DB 中活跃名人数
2. **Fan-in**: `Annotated[list[dict], operator.add]` 汇总所有名人的分析结果
3. **Debate Rounds**: 条件边控制，每轮将所有名人的观点互相传递，名人可质疑他人观点
4. **Exit**: 达到 `debate_max_rounds`（DB 配置）或所有名人达成共识后退出
5. **Synthesis**: 将辩论结果汇总为 `celebrity_consensus` 输出给下游

### LLM 接入

- 使用 LangChain `ChatOpenAI`（OpenAI 兼容协议），复用现有 `llm_config` 表的 base_url/api_key/model
- 每个 Agent 可配置不同的 LLM 模型（通过 `agent_config.model_config_id`）
- 结构化输出使用 `with_structured_output(Pydantic, method="json_schema")`

## Data Models

### 新增数据库表

#### `agent_config` — Agent 定义

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL PK | |
| `name` | VARCHAR(100) UNIQUE | Agent 标识：`tagging`, `celebrity`, `trend`, `report` |
| `display_name` | VARCHAR(200) | 前端显示名 |
| `description` | TEXT | Agent 功能描述 |
| `agent_type` | VARCHAR(50) | `single` / `persona` / `debate` / `synthesis` |
| `system_prompt` | TEXT | System prompt（支持 Jinja2 变量） |
| `output_schema` | JSONB | Pydantic schema 的 JSON Schema |
| `model_config_id` | INT FK → llm_config.id | 使用的 LLM 配置 |
| `extra_params` | JSONB | 扩展参数（temperature, max_tokens 等） |
| `is_active` | BOOLEAN DEFAULT true | |
| `created_at` | TIMESTAMP DEFAULT now() | |
| `updated_at` | TIMESTAMP DEFAULT now() | |

#### `agent_pipeline` — 编排配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL PK | |
| `name` | VARCHAR(100) UNIQUE | Pipeline 标识 |
| `display_name` | VARCHAR(200) | 前端显示名 |
| `description` | TEXT | |
| `graph_config` | JSONB | LangGraph 拓扑定义 |
| `debate_max_rounds` | INT DEFAULT 3 | 辩论最大轮数 |
| `is_active` | BOOLEAN DEFAULT true | |
| `created_at` | TIMESTAMP DEFAULT now() | |
| `updated_at` | TIMESTAMP DEFAULT now() | |

`graph_config` 结构：
```json
{
  "nodes": [
    {"id": "tagging", "agent_config_name": "tagging"},
    {"id": "celebrity", "agent_config_name": "celebrity", "subgraph": true},
    {"id": "trend", "agent_config_name": "trend"},
    {"id": "report", "agent_config_name": "report"}
  ],
  "edges": [
    {"from": "START", "to": "tagging"},
    {"from": "tagging", "to": "celebrity"},
    {"from": "celebrity", "to": "trend"},
    {"from": "trend", "to": "report"},
    {"from": "report", "to": "END"}
  ]
}
```

#### `prompt_template` — Prompt 模板

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL PK | |
| `name` | VARCHAR(100) UNIQUE | 模板标识 |
| `description` | TEXT | 用途说明 |
| `template` | TEXT | Jinja2 模板内容 |
| `variables` | JSONB | 变量定义及说明 |
| `category` | VARCHAR(50) | `system` / `user` / `debate` |
| `version` | INT DEFAULT 1 | 版本号，编辑自增 |
| `is_active` | BOOLEAN DEFAULT true | |
| `created_at` | TIMESTAMP DEFAULT now() | |
| `updated_at` | TIMESTAMP DEFAULT now() | |

#### `celebrity` — 名人知识库

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL PK | |
| `name` | VARCHAR(100) | 英文名，如 "Elon Musk" |
| `display_name` | VARCHAR(100) | 显示名，如 "马斯克" |
| `domain` | VARCHAR(50) | `tech` / `finance` / `science` / `politics` / `other` |
| `title` | VARCHAR(200) | 头衔 |
| `bio` | TEXT | 人物简介 |
| `viewpoints` | TEXT | 核心观点/投资哲学 |
| `analysis_style` | TEXT | 分析风格描述 |
| `avatar_url` | VARCHAR(500) | 头像（可选） |
| `is_active` | BOOLEAN DEFAULT true | 是否参与分析 |
| `sort_order` | INT DEFAULT 0 | 排序权重 |
| `created_at` | TIMESTAMP DEFAULT now() | |
| `updated_at` | TIMESTAMP DEFAULT now() | |

### 修改现有表

- `intel_news` 新增 `deep_analysis` JSONB 字段，存储 Agent 深度分析结果

### LangGraph State 定义

```python
class NewsAnalysisState(TypedDict):
    # 输入
    news_id: int
    news_title: str
    news_content: str
    news_category: str

    # TaggingAgent 输出
    tags: list[str]
    industry: str
    sentiment: float

    # CelebrityAgent 输出
    persona_analyses: Annotated[list[dict], operator.add]
    debate_history: list[dict]
    celebrity_consensus: dict

    # TrendAgent 输出
    related_events: list[dict]
    trend_analysis: dict

    # ReportAgent 输出
    final_report: dict

    # 元信息
    errors: Annotated[list[str], operator.add]
    processing_steps: Annotated[list[str], operator.add]
```

```python
class PersonaState(TypedDict):
    news_title: str
    news_content: str
    celebrity: dict
    analysis: dict

class CelebritySubgraphState(TypedDict):
    news_title: str
    news_content: str
    celebrities: list[dict]
    persona_analyses: Annotated[list[dict], operator.add]
    debate_history: list[dict]
    debate_round: int
    celebrity_consensus: dict
```

## Code Structure (DDD 层级)

```
backend/src/
├── domain/
│   └── market/
│       └── intel/
│           └── agents/                    # 领域层：Agent 定义
│               ├── __init__.py
│               ├── state.py               # State TypedDict 定义
│               ├── base.py                # BaseAgent ABC
│               ├── tagging.py             # TaggingAgent
│               ├── celebrity.py           # CelebrityAgent 子图
│               ├── trend.py               # TrendAgent
│               ├── report.py              # ReportAgent
│               ├── debate.py              # 辩论逻辑
│               ├── graph.py               # 主 LangGraph StateGraph 构建
│               └── models.py              # Agent 相关领域模型
│
├── infra/
│   ├── database/
│   │   └── impl/
│   │       └── agent_db.py                # agent_config/pipeline/template/celebrity 表 + 仓储
│   └── llm/
│       └── langchain_adapter.py           # LLMManager → ChatOpenAI 适配器
│
└── api/
    └── router/
        ├── agent_router.py                # Agent 配置/执行 API
        ├── celebrity_router.py            # 名人知识库 CRUD API
        └── prompt_router.py               # Prompt Template CRUD API

frontend/apps/web/src/
├── pages/
│   ├── AgentConfig.tsx                    # Agent 配置管理页面
│   └── Celebrity.tsx                      # 名人知识库管理页面
```

## API Endpoints

### Agent 执行

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/agent/analyze/{news_id}` | 手动触发单条新闻深度分析 |
| POST | `/api/v1/agent/analyze/batch` | 批量触发（未分析的新闻） |
| GET | `/api/v1/agent/analysis/{news_id}` | 获取深度分析结果 |

### Agent 配置管理

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/agent/configs` | 列出所有 Agent 配置 |
| GET | `/api/v1/agent/configs/{id}` | 获取单个 Agent 配置 |
| PUT | `/api/v1/agent/configs/{id}` | 更新 Agent 配置（含 prompt） |
| POST | `/api/v1/agent/configs/{id}/test` | 测试 Agent 配置（单条新闻试跑） |

### Pipeline 管理

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/agent/pipelines` | 列出所有 Pipeline |
| PUT | `/api/v1/agent/pipelines/{id}` | 更新 Pipeline 配置 |

### 名人知识库

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/celebrities` | 列出所有名人 |
| POST | `/api/v1/celebrities` | 新增名人 |
| PUT | `/api/v1/celebrities/{id}` | 更新名人信息 |
| DELETE | `/api/v1/celebrities/{id}` | 删除名人 |
| PATCH | `/api/v1/celebrities/{id}/toggle` | 启用/禁用名人 |

### Prompt Template

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/prompts` | 列出所有模板 |
| PUT | `/api/v1/prompts/{id}` | 更新模板（version 自增） |
| GET | `/api/v1/prompts/{name}/render` | 预览渲染后的模板 |

## TDD Strategy

### 测试集构建

1. **构造测试新闻数据集**（10-20 条典型新闻，覆盖不同类别/行业/语言）
2. **定义名人知识库种子数据**（3-5 个名人，如马斯克、巴菲特、达利欧）
3. **为每个 Agent 定义期望输出 schema 和质量标准**

### 测试层级

| 层级 | 说明 | 依赖 |
|------|------|------|
| **单元测试** | 每个 Agent 独立测试，mock LLM 响应 | 无外部依赖 |
| **集成测试** | LangGraph 完整工作流，使用真实 LLM | 需要 LLM API |
| **效果评估测试** | 对比测试集新闻的分析结果与人工标注的期望结果 | 测试集 + LLM |

### TDD 流程

1. 写测试：定义输入新闻 + 期望的 tags/sentiment/名人分析结构
2. 写 Agent：实现最小可行逻辑
3. 跑测试：验证通过，不通过则迭代 prompt 或逻辑
4. 重复直到所有测试集通过

### 效果评估维度

- **TaggingAgent**: 标签准确率、行业分类正确率、情感方向一致性
- **CelebrityAgent**: 名人视角差异性、分析深度、辩论质量
- **TrendAgent**: 事件关联合理性、趋势识别准确性
- **ReportAgent**: 综合性、可读性、关键信息覆盖度

## Trigger Mechanism

### 自动触发

在 `scheduler.py` 中新增定时任务，在现有采集任务之后触发：

```python
# 采集完成后，触发未深度分析的新闻
scheduler.add_job(trigger_agent_deep_analysis, 'cron', minute='*/30',
                 id='intel_agent_analysis', replace_existing=True)
```

### 手动触发

- 单条：`POST /api/v1/agent/analyze/{news_id}`，支持重新分析
- 批量：`POST /api/v1/agent/analyze/batch`，处理所有 `deep_analysis IS NULL` 的新闻

## Dependencies

新增 Python 依赖：
- `langgraph` — LangGraph 工作流引擎
- `langchain-openai` — OpenAI 兼容 LLM 接入
- `langchain-core` — LangChain 核心抽象
- `jinja2` — Prompt 模板渲染（可能已有）
