# Blog Agent 演进计划

> 本文档是 blog 对话 agent 从"手写 loop"演进到"LangGraph + checkpointer + 多 agent + 人在回路"的完整路线图。
> 上下文丢失时，从本文档恢复。每个阶段标注了：目标、抄哪个范本、产出、验收。
>
> 参考项目（已 clone 到 /tmp）：
> - **Aegra**（/tmp/aegra）：Python/FastAPI/Postgres，自托管 LangGraph agent 后端。基础设施范本。
> - **open-canvas**（/tmp/open-canvas）：TS，多 graph 写作应用。多 agent 拆图思路范本。

## 背景：现状

- `backend/src/domain/market/intel/blog/agent/blog_agent.py`：手写 tool-calling loop（~50 行胶水），4 个工具（discover_trends / fetch_articles / write_draft / revise_draft），跑在 `POST /blog/agent/chat`（SSE）。
- 已用真 LLM 验证：discover_trends → 回答，全链路通。
- 前端 `frontend/apps/web/src/pages/blog/BlogChat.tsx`：聊天 UI + SSE 解析 + 工具卡片。
- **缺口**：会话历史只在内存，刷新即丢（无 checkpointer / 无 session 表）。
- 栈：FastAPI + React + Postgres + langchain-anthropic（z.ai / GLM）+ 已装 LangGraph 1.2.4。

## 关键决策

- **会话持久化用 LangGraph 的 `AsyncPostgresSaver` checkpointer**（不用自建 blog_session 表）。checkpointer 自动建表、自动存每个节点的 state、用 thread_id 续跑历史。范本：Aegra `libs/aegra-api/src/aegra_api/core/database.py`。
- **手写 loop（blog_agent.py）会被替换成一张 LangGraph 图**。这是必经路径——checkpointer/interrupt/多 agent 都要图，不能挂在手写 loop 上。
- **业务逻辑零重写**：4 个工具的函数体（discover_trends 等）直接复用，只是从"手写 loop 调用"改成"图的工具节点"。
- **editor_in_chief 自动审核本期不做**（先人工审核，跑顺了再加）。

## 演进路线图

### 阶段 0：已完成 ✅

手写 tool-calling loop，真 LLM 验证通过。

### 阶段 1：LangGraph 图 + Postgres checkpointer（进行中）

**目标**：把 blog_agent 重写成一张绑了 AsyncPostgresSaver 的 LangGraph 图。会话用 thread_id 持久化（刷新不丢、可续跑）。这是后续 HITL / 多 agent 的地基。

**抄谁**：Aegra `DatabaseManager`（/tmp/aegra/libs/aegra-api/src/aegra_api/core/database.py）—— pool + checkpointer 初始化、setup()、PgBouncer 兼容。

**做什么**：
1. 新建 `backend/src/infra/database/langgraph_checkpointer.py`：DatabaseManager 风格，初始化 AsyncConnectionPool + AsyncPostgresSaver，`setup()` 建表。单例，app startup 调 initialize()。
2. 把 `blog_agent.py` 的 4 个工具保留为 LangChain `@tool`（或图的工具节点），用 `create_react_agent` 或手写一张 StateGraph（call_model + tools 循环）替换手写 loop。图 compile 时绑 checkpointer。
3. `run_blog_agent(message, history, thread_id)` 改成 `graph.astream(...)`，config 带 `{"configurable": {"thread_id": thread_id}}`。
4. SSE 端点 `POST /blog/agent/chat` 改成接受 `thread_id`（可选，无则新建）。会话历史由 checkpointer 按 thread_id 自动恢复（不再需要前端传 history）。
5. 前端 BlogChat：生成/记住 thread_id（localStorage），每轮带上。新增会话 = 新 thread_id。

**产出**：对话刷新不丢、可续跑；会话状态在 Postgres checkpoint 表里。

**验收**：
- 发消息 → SSE 流正常（tool_start/tool_end/answer）。
- 刷新页面 → 历史对话恢复（从 checkpointer 按 thread_id 读）。
- 新建会话 → 独立 thread_id，互不串。
- 后端重启 → 会话不丢（在 Postgres 里）。

**依赖安装**：`langgraph-checkpoint-postgres`（若未装）。

---

### 阶段 2：人在回路（HITL）—— 等阶段 1 跑顺后做

**目标**：blog_writer 写完草稿后，图暂停，前端展示草稿 + 通过/改/否，用户响应后续跑。

**抄谁**：Aegra `examples/react_agent_hitl/graph.py` —— 用最新 `interrupt()` API + `Command(goto=...)`。

**做什么**：
1. 在写作工具后加 `human_approval` 节点，用 `interrupt({"action_request":..., "config":{"allow_accept":True,"allow_edit":True,"allow_ignore":True}})` 暂停。
2. 前端：SSE 收到 interrupt 事件 → 渲染审批卡片（草稿预览 + 3 按钮）。
3. 用户响应 → `POST .../runs` 带 `Command(resume=...)` 续跑。
4. accept → 继续落库；edit → 改参数后继续；ignore → 取消。

**验收**：用户能在聊天里"看草稿→确认/改/否→继续"，不离开对话流。

---

### 阶段 3：多 agent 动态协作（supervisor）—— 等阶段 2 后，且确认"单 agent 不够"时做

**目标**：固定边换成 supervisor 节点，LLM 动态决定下一个调哪个 agent。

**抄谁**：Aegra `examples/subgraph_agent` + open-canvas 多 graph 架构（/tmp/open-canvas/apps/agents/src/）。

**做什么**：
1. 加 `supervisor` 节点，用 `Command(goto=...)` 路由（找热点/写/改/校对）。
2. trend_spotter / blog_writer / editor_in_chief 作为子图或节点。
3. 按职责拆独立 graph（热点/写作/校对/反思），主图按需调用。

**验收**：supervisor 能根据用户意图动态调度多个 agent，而不是固定流水线。

---

### 阶段 4（可选）：反思 agent + 按职责拆图

抄 open-canvas 的 reflection/summarizer 模式。等阶段 3 后按需。

## 不做的事（本期）

- editor_in_chief 自动审核（先人工，跑顺再加）。
- 服务端会话表（用 checkpointer 替代）。
- 多 agent 辩论（AutoGen 那套）——不需要。
- 换 Pydantic-AI / CrewAI / 其他框架——留 LangGraph。

## 关键 API 速查（来自 Aegra 范本）

```python
# checkpointer 初始化（Aegra DatabaseManager）
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

pool = AsyncConnectionPool(conninfo=DSN, min_size=2, max_size=10, open=False,
    kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
await pool.open()
checkpointer = AsyncPostgresSaver(conn=pool)
await checkpointer.setup()  # 自动建表

# 图 compile 绑 checkpointer
graph = builder.compile(checkpointer=checkpointer)

# 跑（thread_id 管会话，自动恢复历史）
config = {"configurable": {"thread_id": thread_id}}
async for event in graph.astream({"messages":[HumanMessage(content=msg)]}, config):
    ...  # 转 SSE

# 人在回路（Aegra react_agent_hitl）
from langgraph.types import Command, interrupt
async def human_approval(state) -> Command:
    resp = interrupt({"action_request": {...}, "config": {"allow_accept": True, ...}})
    if resp[0]["type"] == "accept": return Command(goto="tools")
    ...
```

## 每阶段完成后的检查清单

- [ ] Python AST/import 通过
- [ ] 后端重启无报错
- [ ] 真 LLM 端到端验证（发消息→SSE→工具→回答）
- [ ] 前端 tsc 无错
- [ ] 验收点（见各阶段）全部满足
