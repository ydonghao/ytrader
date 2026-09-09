# Agent / LLM 过程可观测性（Tracing）— 设计文档

> 日期：2026-06-16
> 状态：已与用户对齐，待 review → writing-plans
> 决策摘要：自建 trace + 前端追踪页；节点级 + LLM 调用级；contextvar + langchain callback 自动捕获；过程持久化到 DB

---

## 1. Context（背景与目标）

**现状问题**：blog/intel 等 agent pipeline（topic_discovery → article_retrieval → deep_analysis → blog_writer → editor_in_chief → image_picker）出问题时无法定位是哪个环节：
- 只有 loguru 日志（非结构化、难关联）
- `state.processing_steps` 只在内存、不持久化、不展示
- draft.metadata 只存 material/source_refs/topic，**不含各节点输入输出/耗时/错误、不含 LLM 的 prompt/response**
- LLM 调用（`create_chat_model_for_agent`）无任何 callback/tracing

**目标**：让每次 pipeline 运行的全过程（每个节点 + 每个 LLM 调用）可见、可持久化、可在前端按草稿查看，出问题能精确定位环节与 LLM 返回。

**非目标（YAGNI）**
- 不接入 LangSmith/Langfuse（自建，数据在内）
- 不做实时流式追踪（事后查看即可）
- 不追踪非 agent 的普通业务逻辑

---

## 2. 核心决策（均已确认）

| # | 决策 | 选择 |
|---|------|------|
| 1 | 可见性形式 | 自建 trace + 前端追踪页 |
| 2 | trace 粒度 | 节点级 + LLM 调用级 |
| 3 | 捕获机制 | contextvar + langchain callback（节点/LLM 代码零改动） |
| 4 | 持久化 | DB（agent_run / agent_run_step / agent_run_llm 三表） |
| 5 | 查看 | 前端 BlogDraft「运行追踪」按钮，按 run_id 拉时间线 |

---

## 3. 数据模型（3 张表）

位置：`backend/src/infra/database/tracing/`（entity + repository）

### agent_run（一次 pipeline 运行）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| run_id | str(uuid) unique | 对外标识 |
| pipeline | str | 如 `blog_topic` |
| topic | str | 如 `ai_tech`（可空） |
| status | str | running / success / failed |
| draft_id | int | 关联 blog_draft.id（可空） |
| started_at / ended_at | datetime | |
| duration_ms | int | |
| error | text | 可空 |

### agent_run_step（一个节点）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| run_id | str(uuid) | FK agent_run.run_id |
| node | str | topic_discovery / article_retrieval / deep_analysis / blog_writer / editor_in_chief / image_picker |
| seq | int | 执行顺序 |
| status | str | running / success / failed |
| input | JSONB | 节点入参摘要 |
| output | JSONB | 节点出参摘要 |
| duration_ms | int | |
| started_at / ended_at | datetime | |
| error | text | 可空 |

### agent_run_llm（一次 LLM 调用）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| run_id | str(uuid) | FK |
| step_node | str | 所属节点 node |
| agent_name | str | topic_discovery / blog_writer / editor_in_chief ... |
| prompt | text | system+user 拼接 |
| response | text | LLM 返回 |
| tokens_prompt / tokens_completion / tokens_total | int | |
| duration_ms | int | |
| status | str | success / failed |
| error | text | 可空 |
| started_at | datetime | |

---

## 4. 组件设计

### 4.1 TraceRecorder【新增·核心】
位置：`backend/src/infra/tracing/recorder.py`
- 用 `contextvars` 存当前 `run_id` + `step_node`（异步安全）
- API：
  - `record_run_start(pipeline, topic=None) -> run_id`
  - `record_run_end(run_id, status, draft_id=None, error=None)`
  - `record_step_start(run_id, node, seq, input_summary) -> step_id`（同时设 contextvar.step_node）
  - `record_step_end(run_id, node, status, output_summary, duration_ms, error=None)`
  - `record_llm_call(run_id, step_node, agent_name, prompt, response, tokens, duration_ms, status, error)`（由 callback 调）
- 所有 record 包 try/except，**失败只 log，不阻塞 pipeline**
- input/output_summary 做截断（避免超大 JSON，如 content 截 2000 字）

### 4.2 LLMCallback【新增】
位置：`backend/src/infra/tracing/llm_callback.py`
- 继承 `langchain_core.callbacks.BaseCallbackHandler`
- `on_llm_start`：记录 started_at + prompt（从 serialized/messages 提取），读 contextvar 当前 run_id/step_node
- `on_llm_end`：记录 response + tokens（response.llm_output.usage）+ duration_ms
- `on_llm_error`：记录 error + status=failed
- 调 `recorder.record_llm_call(...)`
- 若 contextvar 无 run_id（非 pipeline 内的 LLM 调用），静默跳过（不记）

### 4.3 langchain_adapter 改造【改】
`backend/src/infra/llm/langchain_adapter.py`：`create_chat_model_for_agent` 创建的 ChatModel 默认挂 LLMCallback（通过 `.with_config(callbacks=[LLMCallback()])` 或在 ainvoke 传 callbacks）。每个 agent LLM 调用自动被捕获。

### 4.4 agent_node 装饰器改造【改】
`backend/src/domain/market/intel/agents/base.py` 的 `agent_node`：
- 节点开始：`record_step_start(run_id, node_name, seq, input_summary)` + 设 contextvar.step_node
- 节点结束：`record_step_end(run_id, node_name, status, output_summary, duration_ms, error)`
- node_name 从函数名推导（如 `topic_discovery_node` → `topic_discovery`）
- input/output_summary 从 state 提取关键摘要（不全量）

### 4.5 blog graph 集成【改】
`backend/src/domain/market/intel/blog/agents/graph.py` 的 `run_topic_blog_generation`：
- 开头：`run_id = record_run_start(pipeline="blog_topic", topic=topic)` → 设 contextvar.run_id
- graph.ainvoke（节点自动记 step + LLM callback 自动记 llm_call）
- 结尾：`record_run_end(run_id, status, draft_id=saved.id, error)`
- draft.metadata 加 `"run_id": run_id`
- 整体 try/except：pipeline 失败时 record_run_end(status=failed, error)

### 4.6 tracing repository【新增】
`backend/src/infra/database/tracing/`：entity（3 表 SQLModel）+ repository（create run/step/llm + get_run_trace(run_id) 返回 run+steps+llms）

### 4.7 tracing router【新增】
`backend/src/api/router/tracing_router.py`：
- `GET /tracing/runs/{run_id}` → 返回 run + steps（按 seq）+ 每 step 的 llm_calls
- `GET /tracing/runs`（可选，列表，按 pipeline/draft_id 过滤）

### 4.8 前端 BlogDraft 追踪视图【改】
`frontend/apps/web/src/pages/BlogDraft.tsx`：
- 草稿列表项 / 预览工具栏加「运行追踪」按钮（用 `metadata.run_id`）
- 点击 → 拉 `GET /tracing/runs/{run_id}` → 展开追踪面板：
  - 时间线：每节点一行（node / status / duration_ms / 展开 input/output/error）
  - 节点内：该步的 LLM 调用（agent_name / status / tokens / duration / 展开 prompt/response）
  - 状态色：success 绿 / failed 红 / running 灰
- 复用 intel/settings 深色设计系统

---

## 5. 数据流（端到端）

```
run_topic_blog_generation(topic)
  → record_run_start("blog_topic", topic) → run_id, contextvar.run_id=run_id
  → graph.ainvoke
      topic_discovery_node:
        agent_node 记 step_start(input=hotlist_count) → 设 contextvar.step_node
          llm.with_config(callbacks=[LLMCallback]).ainvoke
            → on_llm_start 记 prompt; on_llm_end 记 response/tokens/duration → record_llm_call
        agent_node 记 step_end(output=topic_hint, duration, status)
      article_retrieval_node: 同上（无 LLM 调用则只记 step）
      deep_analysis / blog_writer / editor_in_chief / image_picker: 同上
  → record_run_end(run_id, status, draft_id=saved.id)
  → draft.metadata.run_id = run_id
前端: 点「运行追踪」→ GET /tracing/runs/{run_id} → 时间线（节点+LLM）
```

---

## 6. 错误处理
- **trace 记录失败不阻塞 pipeline**：所有 recorder 调用 try/except，失败只 log.warning
- 节点失败：`agent_node` 捕获异常 → record_step_end(status=failed, error) → 重新抛出（不吞 pipeline 错误）
- LLM 失败：LLMCallback.on_llm_error → record_llm_call(status=failed, error)
- pipeline 失败：run_topic_blog_generation try/except → record_run_end(status=failed, error)
- prompt/response 截断（避免超大）：各 4000 字封顶

---

## 7. 测试
- **TraceRecorder 单测**：record_run/step/llm，contextvar 隔离（async）
- **LLMCallback 单测**：mock LLM，断言 on_llm_start/end 记录 prompt/response/tokens
- **agent_node 单测**：mock 节点，断言 step 被记（input/output/duration/status）
- **集成**：mock run_topic_blog_generation 各节点，断言 agent_run + steps(6) + llm_calls 入库 + draft.metadata.run_id
- **API**：GET /tracing/runs/{run_id} 返回结构

---

## 8. 实施顺序（建议）
1. DB 表 + repository（4.6）
2. TraceRecorder + contextvar（4.1）
3. LLMCallback（4.2）+ langchain_adapter 挂载（4.3）
4. agent_node 改造记 step（4.4）
5. run_topic_blog_generation 集成 run（4.5）
6. tracing router + API（4.7）
7. 前端追踪视图（4.8）
8. main.py 注册 tracing_router

---

## 9. 涉及文件（预估）

**新增**
- `backend/src/infra/tracing/recorder.py`、`llm_callback.py`、`__init__.py`
- `backend/src/infra/database/tracing/`（entity + repository）
- `backend/src/api/router/tracing_router.py`

**改造**
- `backend/src/infra/llm/langchain_adapter.py`（挂 LLMCallback）
- `backend/src/domain/market/intel/agents/base.py`（agent_node 记 step）
- `backend/src/domain/market/intel/blog/agents/graph.py`（run_topic_blog_generation 记 run）
- `backend/main.py`（注册 tracing_router）
- `frontend/apps/web/src/pages/BlogDraft.tsx`（运行追踪视图）

---

## 10. 覆盖范围与扩展
- **一期覆盖**：blog topic pipeline 全覆盖（agent_node 节点 + create_chat_model_for_agent 的 LLM 调用自动）
- **后续扩展**：任何用 `agent_node` 的 pipeline 自动覆盖；直接 `llm.ainvoke` 的调用（如 intel processor）挂 callback 即纳入；可为采集类（intel processor 的 LLM）单独包 run
