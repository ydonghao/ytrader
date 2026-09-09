# AI 写微信公众号（三专题）— 设计文档

> 日期：2026-06-16
> 状态：已与用户对齐，待 review → writing-plans
> 决策摘要：演进现有 blog 系统，做 **AI技术 / AI应用 / 炒股** 三专题；**选题驱动**（newsnow 热点→选题 → miniflux/wewe 深度文章检索解读）+ 多 agent 主编工作流；arxiv 二期；砍 AI 分析（tagging 保留复用）

---

## 1. Context（背景与目标）

**现状**
- 已有一套博客生成底子：`BlogDraft.tsx`（前端草稿管理）+ `backend/src/domain/market/intel/blog/agents/graph.py`（LangGraph：`load_news → topic_picker → blog_writer → image_advisor`，另有热点模式 `trend_spotter → content_enrich → ...`），支持 3 风格、草稿 `draft→approved→published`。
- 有一套"AI 分析"功能（Intel `AnalysisTab` + `agents/graph.py` 分析管线 + 事件检测 + 市场关联），用户决定**砍掉**。
- arxiv / 论文：项目完全没有，二期再接。
- LLM：新 `backend/src/infra/llm/`（LLMManager，支持 openai/anthropic 多 provider）。

**目标**
把现有 blog 演进为"三专题 AI 写公众号"，每专题：按数据源差异化处理 → 专题写作 → 主编把关 → 配图 → 草稿人工审核。追求文章质量（"怎么效果好怎么来"）。

**非目标（YAGNI）**
- arxiv 论文采集/解读（二期）
- 配图文生图（一期用图库检索）
- 全自动发布（一期保留人工 approved）

---

## 2. 核心决策（均已与用户确认）

| # | 决策 | 选择 |
|---|------|------|
| 1 | 与现有 blog 关系 | 演进（复用 BlogDraft + blog agents） |
| 2 | arxiv | 二期，一期用现有资讯 |
| 3 | 质量机制 | 多 agent 主编工作流 |
| 4 | 架构方案 | A：Processor 层 + 专题写作 + 共享主编 |
| 5 | 数据源处理 | 不同源差异化处理（Processor 层） |
| 6 | 配图 | 图库检索（资讯图/Unsplash，不生成） |
| 7 | tagging | 从 AI 分析抽出，保留给 blog 复用 |
| 8 | 自动化 | 定时 + 手动 + 人工审 |

---

## 3. 架构总览（选题驱动）

```
选题信号源（newsnow hotlist / cctv / finnhub）        深度内容源（miniflux / wewe，带正文）
        ↓                                                    ↓
【新增】选题发现（可选）：LLM 按专题筛热点 → 选题(topic)
        ↓
【新增】深度文章检索：按选题（或无选题直接）在 miniflux+wewe 检索带正文深度文章
        ↓
【新增】深度解读：深度文章 → Material（含 source_refs）
        ↓
【改造】编写：按专题 prompt/风格，基于 Material
        ↓
【新增】主编 agent（评分 / 打回 / 事实核查）
        ↓
【改造】配图（图库检索）
        ↓
草稿（BlogDraft：draft→approved→published）
```

**专题 ↔ 选题信号 ↔ 深度内容源**
| 专题 | 选题信号 | 深度内容源 | 写作风格 |
|------|---------|-----------|----------|
| AI技术 | newsnow 筛 AI技术热点 | miniflux(future_tech) + wewe | tech_depth |
| AI应用 | newsnow 筛 AI应用热点 | miniflux(future_tech) + wewe | pop_science |
| 炒股 | newsnow 财经热点 / cctv | miniflux(finance) | 专业财经 |

---

## 4. 组件设计

### 4.1 内容获取与处理【新增 · 核心 · 选题驱动】

数据源按角色分两类：
- **选题信号源**（决定"写什么"）：newsnow hotlist（社会热点，LLM 筛专题相关）、cctv/finnhub（炒股选题信号）
- **深度内容源**（文章素材，须带正文）：miniflux（技术/财经文）、wewe（微信深度文，已带正文）

**原则**：newsnow 只作选题线索，不作文章主体、不补正文（webreader 珍贵）；深度内容来自有正文的 miniflux/wewe。

**三步处理**（位置 `backend/src/domain/market/intel/blog/processors/`，替代原"各源 Processor 提炼"）：

1. **TopicDiscovery 选题发现（可选）** — `topic_discovery.py`
   - 从选题信号源（newsnow hotlist）取近期热点 → LLM 按目标专题筛选相关性（如 AI技术专题只留 AI 技术热点）→ 候选选题 `topic_hint`
   - 支持**无选题模式**：跳过本步，直接进 2（直接取深度文章）
2. **ArticleRetrieval 深度文章检索** — `article_retrieval.py`
   - 有选题：按选题主题在深度内容源（miniflux + wewe）检索相关且**有正文**的文章，按相关度/时效取 Top-N
   - 无选题：直接取 miniflux + wewe 近期高质量深度文章
3. **DeepAnalysis 深度解读** — `deep_analysis.py`
   - 对检索到的深度文章做深度解读 → 统一 `Material`（`topic_hint/key_points/entities/source_refs/suggested_angle`）
   - 多篇可融合；复用 `LLMManager`

- `base.py`：`Material` schema + 公共 LLM 调用封装

**关键点**：newsnow 当选题线索、miniflux/wewe 当深度内容；下游（编写/主编）只消费统一 `Material`。

### 4.2 专题配置【新增】
**位置**：`backend/src/domain/market/intel/blog/topics.py`

`TopicConfig`：`{name, sources[], processor, writer_prompt, style, audience, editor_rubric}`
- 三专题各一份配置（AI技术 / AI应用 / 炒股）
- 写作 prompt、主编评分标准按专题定制

### 4.3 工作流改造【改 `blog/agents/graph.py`】
现：`load_news → topic_picker → blog_writer → image_advisor`
改为（选题驱动）：
```
topic_discovery(可选) → article_retrieval → deep_analysis → blog_writer → editor_in_chief → image_picker
```
- `topic_discovery_node`（新，可基于现有 `trend_spotter` 改造）：newsnow 热点 → LLM 按专题筛 → 选题（返回空 = 无选题模式）
- `article_retrieval_node`（新）：按选题（或直接）在 miniflux + wewe 检索带正文深度文章 Top-N
- `deep_analysis_node`（新）：深度解读 → Material
- `blog_writer_node`（改）：基于 Material + 专题 `writer_prompt`/`style` 编写，关联 `source_news_ids`
- `editor_in_chief_node`（新）：见 4.4
- `image_picker_node`（改）：图库检索，见 4.5
- **无选题模式**：`topic_discovery` 跳过/返回空，`article_retrieval` 直接取近期深度文章

### 4.4 主编 agent【新增】
**位置**：`backend/src/domain/market/intel/blog/agents/editor_in_chief.py`

- 输入：草稿 + 专题 `editor_rubric` + `source_refs`（引用的源资讯）
- 评分维度（各 0-10）：信息密度 / 可读性 / **事实可溯性** / 专题契合度 / 标题吸引力
- **事实可溯性（防幻觉核心）**：核对草稿关键论点是否能在 `source_refs` 找到支撑；无支撑的论点标记并打回，要求 blog_writer 删除或补引用
- 不达标（总分阈值或事实可溯性过低）→ 打回，附修改意见，`blog_writer` 重写（≤2 轮）
- 达标 → 放行进入配图
- state 中记录评分、轮次、修改意见、未支撑论点（可追溯）

### 4.5 配图【改 `image_advisor` → `image_picker`】
- 现状：`image_advisor` 只给"位置/描述/关键词"建议
- 改为：`image_picker` 按建议关键词从**图库检索**（优先现有资讯附图，回退 Unsplash API），选配图 URL
- 不做文生图（二期再评估）
- 配图结果写入草稿 `image_suggestions`（结构扩展为含 url）

### 4.6 tagging 抽取复用
- 从 `agents/graph.py` 分析管线抽出 `tagging`（关键词/情感/行业分类）为独立可复用模块（如 `blog/processors/tagging.py` 或 `domain/market/intel/tagging.py`）
- blog 的 Processor 在提炼 Material 时复用 tagging 能力
- 其余分析节点（celebrity / trend / report）随 AI 分析砍掉

### 4.7 去 AI 分析【清理】
**砍除**：
- 前端：Intel `AnalysisTab`（`Intel.tsx`）+ 相关 reader/分析展示
- 后端：`domain/market/intel/agents/graph.py` 的分析管线（celebrity/trend/report 节点）
- `domain/market/intel/agents/` 的 celebrity subgraph
- `domain/market/intel/analysis/event_service.py`、`market_correlation_service.py`
- `infra/database/intel/analysis_repository.py`、`infra/database/agent/repository.py`
- 对应 router/handler/scheduler 任务（cctv_event_detection / cctv_market_correlation / intel_agent_analysis）
- **保留**：tagging（按 4.6 抽出复用）

**安全**：blog 不依赖上述分析，砍除不影响 blog 生成。

### 4.8 前端 BlogDraft 扩展
- 加专题维度：列表按专题分栏/筛选
- 生成入口：选专题触发 `/blog/generate`（带 topic 参数）
- 配图展示：渲染 `image_suggestions` 的 url
- 草稿审核流程不变（draft→approved→published）

### 4.9 自动化【改 `infra/scheduler.py`】
- 现有 `blog_daily_generation`（8:07）扩展为三专题各生成 1 篇草稿
- 保留 BlogDraft 手动触发
- 草稿须人工 `approved`（不自动发布）

### 4.10 arxiv 二期【预留】
- Processor 层预留 `ArxivProcessor` 接口位
- 二期加 arxiv 采集（API/RSS）+ 论文解读，服务于 AI技术专题
- 一期不实现

### 4.11 溯源与防幻觉【贯穿全流程】
目标：每篇文章可追溯到源资讯，杜绝 AI 幻觉。
1. **强制引用**：`Material.source_refs` 携带源 NewsItem id/url；blog_writer 只能基于 Material 事实写作，每篇草稿必须关联 `source_news_ids`（现有 blog 草稿字段），空引用直接打回
2. **主编事实核查**：见 4.4，无源支撑的论点打回
3. **前端溯源展示**：文章详情「本文依据」区，列出引用资讯（标题/来源/时间/原文链接），可点击跳原文；主编评分（尤其事实可溯性）一并展示
4. **句级引用**（二期）：生成时每段标注来源 id，段末角注

### 4.12 结果呈现与菜单
- 复用现有 **Blog 菜单**（Research 分组），BlogDraft 页内加**专题 tab**（AI技术 / AI应用 / 炒股），与 Intel 多 tab 一致
- 生成入口与草稿浏览均按专题组织；Blog label 可保留或改「公众号」
- 文章详情含「本文依据」溯源区（4.11）+ 主编评分

---

## 5. 数据流（端到端）

```
定时(8:07)/手动 → 选专题(如 AI技术)，可选指定选题或无选题
  → topic_discovery(可选): newsnow hotlist → LLM 筛 AI技术热点 → 选题(可空)
  → article_retrieval: 按选题(或直接)在 miniflux(future_tech)+wewe 检索带正文深度文章 Top-N
  → deep_analysis: 深度解读 → Material(含 source_refs)
  → blog_writer: 用 AI技术 prompt/tech_depth 风格，基于 Material，关联 source_news_ids → 草稿
  → editor_in_chief: 评分(含事实可溯性核查) → 不达标打回重写(≤2) / 达标放行
  → image_picker: 关键词 → 图库检索 → 配图 url
  → 存草稿(status=draft, source_news_ids, 评分) → BlogDraft 按专题展示 + 「本文依据」溯源
  → 人工 approved → (published 由后续发布流程)
```

---

## 6. 错误处理
- Processor/写作/主编 LLM 调用失败：重试 + 降级（该专题本次跳过，记日志，不阻塞其它专题）
- 主编 2 轮仍不达标：以最后版本入库，标记 `needs_manual_edit`，前端提示人工介入
- 图库检索失败：回退无图（不阻塞生成）
- 数据源无素材：该专题本次跳过，日志记录

---

## 7. 测试
- **Processor 单测**：每类 Processor 给定 mock NewsItem，断言 Material 输出格式 + 关键提炼（mock LLM）
- **主编单测**：给定草稿 + rubric，断言评分/打回逻辑（高质量放行、低质量打回）
- **工作流集成**：mock 各节点，断言端到端 state 流转（含打回重写分支）
- **专题配置单测**：三专题配置完整性
- 复用现有 `tests/` 结构（按 `tests/domain/...` 镜像）

---

## 8. 实施顺序（建议，供 writing-plans 细化）
1. **清理 AI 分析**（4.7）——先砍，减少干扰；tagging 抽出（4.6）
2. **Processor 层 + Material schema**（4.1）+ **专题配置**（4.2）
3. **工作流改造**（4.3）：material_builder / 改 topic_picker / 改 blog_writer
4. **主编 agent**（4.4）+ 打回重写闭环
5. **配图 image_picker**（4.5）
6. **前端 BlogDraft 专题维度**（4.8）
7. **scheduler 三专题定时**（4.9）
8. arxiv 预留接口（4.10，二期实现）

---/

## 9. 涉及文件（预估）

**新增**
- `backend/src/domain/market/intel/blog/processors/`（base + topic_discovery + article_retrieval + deep_analysis）
- `backend/src/domain/market/intel/blog/topics.py`
- `backend/src/domain/market/intel/blog/agents/editor_in_chief.py`
- `backend/src/domain/market/intel/blog/agents/image_picker.py`（改造自 image_advisor）

**改造**
- `backend/src/domain/market/intel/blog/agents/graph.py`（工作流节点）
- `backend/src/domain/market/intel/blog/state.py`、`schemas.py`（Material、主编评分字段）
- `backend/src/domain/market/intel/blog/agents/blog_writer.py`（按专题 prompt）
- `backend/src/api/handler/blog_handler.py` + `router/blog_router.py`（生成带 topic）
- `backend/src/infra/scheduler.py`（三专题定时）
- `frontend/apps/web/src/pages/BlogDraft.tsx`（专题维度）

**删除（AI 分析）**
- `Intel.tsx` AnalysisTab；`agents/graph.py` 分析管线；celebrity；`analysis/event_service.py`、`market_correlation_service.py`；`analysis_repository.py`；`agent/repository.py`；相关 router/scheduler 任务
