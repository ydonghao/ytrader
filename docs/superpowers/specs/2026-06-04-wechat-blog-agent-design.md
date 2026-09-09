# WeChat Blog Agent — AI 科技博文自动生成系统

Date: 2026-06-04
Status: Draft

## Overview

在现有 Intel 新闻采集 + Agent 深度分析系统基础上，新增博文生成管线。每日自动从已采集和分析的资讯中选题，生成适合微信公众号发布的 Markdown 博文，支持 3 种写作风格，含配图建议。

## Requirements

1. **每日自动选题**：从 intel_news + deep_analysis 中筛选过去 24h 最适合写博文的话题
2. **3 种写作风格**：技术深度型 / 通俗科普型 / 热点评论型，每次生成可选
3. **完整博文输出**：标题 + 导语 + 正文（1500-3000 字）+ 结尾，Markdown 格式
4. **配图建议**：每个博文 3-5 个配图位置，给出描述和搜索关键词
5. **前端审核页面**：查看博文列表、预览内容、编辑、重新生成、复制 Markdown
6. **调度**：每天早上 8:00 自动选题生成，也可手动触发
7. **复用现有基础设施**：采集系统、LLM Manager、LangGraph 框架、调度器

## Architecture

### 系统定位

```
现有采集 → 现有 Processor（快速通道）
         → 现有 Agent Deep Analysis（深度通道）
                ↓
         ── 新增：Blog Pipeline ──
         TopicPickerAgent → BlogWriterAgent → ImageAdvisorAgent
                ↓
         blog_draft 表（存储生成的博文）
                ↓
         前端 BlogDraft 页面（审核/编辑/导出）
```

### Pipeline 拓扑

```
┌─────────────────┐
│  START           │
│  (date_range)    │
└────────┬────────┘
         │
┌────────▼────────┐
│ TopicPickerAgent │  从 intel_news 选最佳话题
│  评分排序         │  输入：近 24h 新闻 + 分析结果
└────────┬────────┘
         │
┌────────▼────────┐
│ BlogWriterAgent  │  按指定风格写完整博文
│  支持 3 种风格    │  输出：Markdown 博文
└────────┬────────┘
         │
┌────────▼────────┐
│ ImageAdvisorAgent│  配图建议
│  3-5 个配图位    │  输出：配图描述 + 关键词
└────────┬────────┘
         │
┌────────▼────────┐
│     END          │
│  保存到 DB       │
└─────────────────┘
```

### 与现有系统的关系

- **数据来源**：读取 `intel_news` + `deep_analysis` JSONB 字段
- **LLM 接入**：复用 `langchain_adapter.py` → `create_chat_model_for_agent()`
- **Agent 框架**：复用 `base.py`（agent_node 装饰器、prompt 渲染）
- **调度器**：在 `scheduler.py` 新增定时任务
- **DB 模式**：新建 `blog_draft` 表 + `BlogRepository`

## Data Models

### 新增数据库表

#### `blog_draft` — 博文草稿

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL PK | |
| `title` | VARCHAR(500) | 博文标题 |
| `style` | VARCHAR(50) | `tech_depth` / `pop_science` / `hot_commentary` |
| `status` | VARCHAR(20) | `draft` / `approved` / `published` / `discarded` |
| `content` | TEXT | Markdown 正文 |
| `image_suggestions` | JSONB | 配图建议列表 |
| `source_news_ids` | ARRAY(INTEGER) | 引用的 intel_news ID 列表 |
| `topic_score` | FLOAT | 选题评分 |
| `topic_reason` | TEXT | 选题理由 |
| `metadata` | JSONB | 扩展信息（字数、阅读时间等） |
| `created_at` | TIMESTAMP DEFAULT now() | |
| `updated_at` | TIMESTAMP DEFAULT now() | |
| `published_at` | TIMESTAMP | 发布时间 |

### 新增 Agent Config（seed data）

在 `agent_config` 表新增 3 条记录：

| name | display_name | agent_type | description |
|------|-------------|------------|-------------|
| `topic_picker` | Topic Picker | single | 从新闻中选题，评分排序 |
| `blog_writer` | Blog Writer | single | 按风格写博文 |
| `image_advisor` | Image Advisor | single | 配图建议 |

### LangGraph State

```python
class BlogPipelineState(TypedDict, total=False):
    # Input
    date_range_hours: int  # 默认 24
    style: str  # tech_depth / pop_science / hot_commentary
    candidate_news: list[dict]  # 候选新闻列表

    # TopicPicker 输出
    selected_topic: dict  # 选中的话题 + 相关新闻
    topic_score: float
    topic_reason: str
    source_news_ids: list[int]

    # BlogWriter 输出
    title: str
    content: str  # Markdown
    metadata: dict  # 字数、阅读时间等

    # ImageAdvisor 输出
    image_suggestions: list[dict]  # [{position, description, keywords}]

    # Meta
    errors: Annotated[list[str], operator.add]
    processing_steps: Annotated[list[str], operator.add]
```

## Code Structure

```
backend/src/
├── domain/market/intel/
│   └── blog/                          # 新增目录
│       ├── __init__.py
│       ├── models.py                  # BlogDraft dataclass
│       ├── state.py                   # BlogPipelineState
│       ├── schemas.py                 # TopicResult, BlogResult, ImageSuggestion
│       ├── repository_interface.py    # IBlogRepository ABC
│       └── agents/                    # 3 个 Agent 节点
│           ├── __init__.py
│           ├── topic_picker.py        # TopicPickerAgent
│           ├── blog_writer.py         # BlogWriterAgent
│           ├── image_advisor.py       # ImageAdvisorAgent
│           └── graph.py              # Blog pipeline StateGraph
├── infra/database/impl/
│   └── blog_db.py                    # blog_draft 表 + BlogRepository
├── api/router/
│   └── blog_router.py                # 博文 API

frontend/apps/web/src/pages/
├── BlogDraft.tsx                      # 博文管理页面
└── BlogDraft.css
```

## API Endpoints

### 博文管理

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/blog/drafts` | 列出所有博文草稿（分页） |
| GET | `/api/v1/blog/drafts/{id}` | 获取单篇博文详情 |
| POST | `/api/v1/blog/generate` | 手动触发生成（可选 style 参数） |
| PUT | `/api/v1/blog/drafts/{id}` | 编辑博文（标题/内容/状态） |
| DELETE | `/api/v1/blog/drafts/{id}` | 删除草稿 |
| PATCH | `/api/v1/blog/drafts/{id}/status` | 更新状态（approved/published/discarded） |

### 请求/响应模型

```python
class BlogGenerateRequest(BaseModel):
    style: str = "pop_science"  # tech_depth / pop_science / hot_commentary
    date_range_hours: int = 24

class BlogDraftResponse(BaseModel):
    id: int
    title: str
    style: str
    status: str
    content: str
    image_suggestions: list[dict]
    source_news_ids: list[int]
    topic_score: float
    topic_reason: str
    metadata: dict
    created_at: datetime
```

## Agent Prompt Design

### TopicPickerAgent

系统提示词要点：
- 输入：近 24h 新闻列表（标题 + 摘要 + 标签 + 深度分析结果）
- 评分维度：热度(30%) × 时效性(30%) × 公众关注度(20%) × 博文适配度(20%)
- 输出：选中的话题 + 相关新闻 ID 集合 + 评分 + 推荐理由
- 选话题原则：有故事性、有争议性、有启发性、读者会产生共鸣

### BlogWriterAgent

三种风格的系统提示词：

**技术深度型 (tech_depth)：**
- 深入分析技术原理
- 引用论文/技术报告
- 有代码示例或技术图解描述
- 面向技术从业者
- 结构：背景 → 原理 → 应用 → 展望

**通俗科普型 (pop_science)：**
- 用日常生活比喻解释技术
- 少用专业术语，必须用时加解释
- 有故事线，吸引人读下去
- 面向大众
- 结构：引人入胜的开头 → 核心概念 → 实际影响 → 未来想象

**热点评论型 (hot_commentary)：**
- 快速梳理事件脉络
- 多源整合，加犀利点评
- 有数据支撑
- 面向关注行业动态的读者
- 结构：事件回顾 → 多方观点 → 我的分析 → 行业影响

通用要求：
- 微信公众号格式：短段落（3-4 行）、适当加粗、有小标题
- 字数 1500-3000 字
- 标题要有吸引力，不是论文标题
- 导语要在一开始就抓住读者

### ImageAdvisorAgent

- 根据博文内容，建议 3-5 个配图位置
- 每个位置输出：`{position: "第2段后", description: "描述", keywords: ["AI", "芯片"]}`
- 关键词可用于在 Unsplash 等图库搜索，或 AI 生图

## Trigger Mechanism

### 自动触发

在 `scheduler.py` 新增定时任务：

```python
# 每天早上 8:00 自动生成博文
sched.add_job(
    _run_blog_generation,
    CronTrigger(hour=8, minute=7, timezone="Asia/Shanghai"),
    id="blog_daily_generate",
    name="每日博文生成",
    replace_existing=True,
    misfire_grace_time=600,
)
```

### 手动触发

- `POST /api/v1/blog/generate` — 可指定 style，立即生成

## Frontend — BlogDraft Page

### 功能

1. **草稿列表**：按创建时间倒序，显示标题/风格/状态/评分
2. **预览面板**：点击草稿显示 Markdown 渲染后的内容 + 配图建议
3. **操作按钮**：
   - 重新生成（换风格）
   - 编辑（修改标题/内容）
   - 复制 Markdown
   - 标记为已发布/已丢弃
4. **手动生成**：点击"生成今日博文"，选择风格

### 布局

左侧列表 + 右侧预览，类似邮件客户端。顶部有"生成"按钮。

## Dependencies

无新增依赖。完全复用：
- langgraph / langchain-openai / langchain-core / jinja2（已在 pyproject.toml）
- SQLModel / FastAPI / APScheduler（已有）
