# Settings MCP + Skill 功能设计

**日期**: 2026-06-11
**状态**: Approved
**范围**: Settings 页面新增 MCP Server 管理、MCP Tool 面板、Agent Pipeline 集成、Prompt 模板管理、Agent 配置管理、Skill 工作流定义

---

## 概述

在 Settings 页面新增 6 张 Card，分三阶段交付：

| Phase | 功能 | 后端 | 前端 |
|-------|------|------|------|
| 1 | MCP Server 连接管理 | 新增 DB 表 + Router + MCP Client | 新增 Card |
| 2A | MCP Tool 调用面板 | 新增 API 端点 | 新增 Card |
| 2B | Agent Pipeline MCP 集成 | 新增 MCPToolNode | graph_config 扩展 |
| 3A | Prompt 模板管理 | 无改动（已有） | 新增 Card |
| 3B | Agent 配置统一管理 | 无改动（已有） | 新增 Card |
| 3C | Skill 工作流定义 | 新增 DB 表 + Router | 新增 Card |

---

## Phase 1: MCP Server 连接管理

### 架构

```
Frontend (Settings Card)          Backend                          External
+---------------------+    +------------------------+    +--------------+
| MCP Server Card     |--->| /api/v1/mcp/servers    |    | MCP Servers  |
| - List servers      |    | - CRUD (SQLModel DB)   |    | - codegraph  |
| - Add/Edit form     |    | - Test connectivity    |    | - web_reader |
| - Test connection   |<---| - List tools (via SDK) |    | - context7   |
| - View tools list   |    +------------------------+    +--------------+
+---------------------+
```

### 数据库表

**McpServerTable** (`src/infra/database/mcp/repository.py`):

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 自增主键 |
| name | VARCHAR(100) UNIQUE | 服务器名称（如 "web_reader"） |
| display_name | VARCHAR(200) | 显示名称 |
| description | TEXT | 服务器描述 |
| transport_type | VARCHAR(20) | "stdio" 或 "sse" |
| command | TEXT | stdio 模式的启动命令（如 "npx @anthropic/mcp-server-web-reader"） |
| url | VARCHAR(500) | sse 模式的 URL（如 "http://localhost:3001/sse"） |
| headers | JSON | sse 模式的请求头（如 Authorization） |
| env_vars | JSON | 环境变量键值对（如 {"API_KEY": "sk-xxx"}） |
| is_active | BOOLEAN DEFAULT true | 是否启用 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### 后端文件

**`src/infra/mcp/client.py`** — MCP 客户端封装：
- 使用 Python `mcp` SDK 连接外部 MCP Server
- 方法：
  - `async connect(server_config)` — 建立连接（stdio 用 subprocess，sse 用 HTTP）
  - `async disconnect()` — 关闭连接
  - `async list_tools()` — 获取工具列表（name, description, inputSchema）
  - `async call_tool(tool_name, arguments)` — 调用工具
  - `async health_check()` — 连接测试（connect + list_tools + disconnect）
- 连接生命周期：每次调用时连接 → 执行 → 断开（不保持长连接，避免资源泄漏）
- 异步上下文管理器：`async with McpClient(config) as client: ...`

**`src/infra/database/mcp/repository.py`** — 数据库 CRUD：
- `create_mcp_repository()` 工厂函数
- 方法：`list_servers()`, `get_server(id)`, `create_server(data)`, `update_server(id, data)`, `delete_server(id)`
- SQLModel 表定义：`McpServerTable(SQLModel, table=True)`

**`src/api/router/mcp_router.py`** — API 端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /mcp/servers | 列出所有已配置的服务器 |
| POST | /mcp/servers | 添加新的服务器配置 |
| PUT | /mcp/servers/{id} | 更新服务器配置 |
| DELETE | /mcp/servers/{id} | 删除服务器 |
| POST | /mcp/servers/{id}/test | 测试连接（connect + list_tools + disconnect） |
| GET | /mcp/servers/{id}/tools | 列出服务器暴露的工具（name + description + inputSchema） |

请求模型（`src/api/model/mcp_api_model.py`）：
- `McpServerCreate(name, display_name, description, transport_type, command, url, headers, env_vars, is_active)`
- `McpServerUpdate` — 所有字段 Optional
- `McpServerResponse` — 含 id, created_at, updated_at
- `McpTestResponse(success, message, tools_count, tools: list, duration_ms)`

### 前端

Settings.tsx 新增 **MCP Servers Card**（与 LLM Model Config Card 同模式）：

**列表视图：**
- 服务器卡片网格，每张卡片显示：名称、transport_type 标签（stdio/sse）、is_active 状态灯、tools 数量
- 操作按钮：编辑、删除、测试连接

**添加/编辑 Modal：**
- 名称（text input）
- 显示名称（text input）
- 描述（text input）
- Transport Type（select: stdio / sse）
- 条件显示：
  - stdio → Command（text input，如 `npx @anthropic/mcp-server-web-reader`）
  - sse → URL（text input）+ Headers（JSON textarea）
- Environment Variables（key-value pair 列表，可增删行）
- is_active 开关

**测试连接：**
- 点击后调用 `POST /mcp/servers/{id}/test`
- 成功显示：绿色 "Connected, N tools available"
- 失败显示：红色错误信息

**Tools 列表：**
- 每个服务器卡片可展开，显示 tool 列表（name + description）
- 展开时调用 `GET /mcp/servers/{id}/tools`

---

## Phase 2A: MCP Tool 调用面板

### 架构

```
Frontend                          Backend
+----------------------+    +-------------------------+
| MCP Tool Console     |--->| POST /mcp/servers/{id}/ |
| - Select server      |    |      invoke             |
| - Select tool        |    | - Load server config    |
| - Fill args (JSON)   |    | - Connect via mcp SDK   |
| - See result         |<---| - call_tool(name, args) |
+----------------------+    +-------------------------+
```

### 后端新增端点

**`src/api/router/mcp_router.py`** 扩展：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /mcp/servers/{id}/invoke | 调用指定服务器上的指定工具 |

请求体：`McpToolInvokeRequest(tool_name: str, arguments: dict)`
响应：`McpToolInvokeResponse(tool: str, result: Any, duration_ms: float, error: str | None)`

实现逻辑：
1. 从 DB 加载 server config
2. 用 McpClient 建立 async 连接
3. 调用 `client.call_tool(tool_name, arguments)`
4. 返回结果 + 耗时
5. 超时保护：30 秒上限

### 前端新增 MCP Tool Console Card

位于 MCP Servers Card 下方：

**输入区：**
- Server 下拉选择器（数据来自 MCP Servers Card 同源 API）
- Tool 下拉选择器（级联，选择 server 后加载其 tools）
- Tool 选中后显示 description 文本
- Arguments 编辑区：
  - **表单模式**：基于 inputSchema 动态生成表单字段（string → input, number → input, boolean → checkbox, object → textarea）
  - **JSON 模式**：textarea 编辑 raw JSON，可一键切换

**执行与结果：**
- "执行" 按钮 → 调用 `POST /mcp/servers/{id}/invoke`
- 结果区：JSON 格式化显示（syntax highlight），可切换纯文本模式
- 错误显示：红色错误信息 + duration

**请求历史：**
- Session 内保留最近 10 条请求（前端 state，不持久化）
- 每条记录：server name + tool name + timestamp + success/error
- 点击可回填参数

---

## Phase 2B: Agent Pipeline MCP 集成

### 架构

```
Blog/Intel/Celebrity Pipeline
+--------------+     +-----------------+     +--------------+
| TrendSpotter |---->| MCP Tool Bridge |---->| ContentEnrich |
| (existing)   |     | (new node)      |     | (existing)   |
+--------------+     +-----------------+     +--------------+
                          |
                     +----v----+
                     | web_    |  <- MCP Server
                     | reader  |    configured in Phase 1
                     +---------+
```

### 后端新文件

**`src/domain/market/intel/agents/mcp_tool_node.py`** — LangGraph 通用 MCP Tool Node：

```python
class MCPToolNode:
    """通用 MCP Tool 调用节点，可插入任意 LangGraph pipeline。
    
    配置示例:
    {
        "server_id": 1,
        "tool_name": "webReader",
        "args_template": {"url": "{{ state.article_url }}"},
        "output_key": "web_content",
        "on_error": "skip"  # skip | fail
    }
    """
    async def __call__(self, state: dict) -> dict:
        # 1. 从 DB 加载 server config
        # 2. 用 Jinja2 模板从 state 渲染 args_template
        # 3. McpClient.connect → call_tool → disconnect
        # 4. 将结果写入 state[output_key]
        # 5. 错误处理：on_error="skip" 时写 None，"fail" 时抛异常
```

**Pipeline 配置扩展：**
- graph_config JSON 中的 nodes 数组新增 `"type": "mcp_tool"` 支持
- 现有 graph 解析逻辑扩展：识别 `mcp_tool` 类型节点 → 实例化 `MCPToolNode`

**新端点：**
- `GET /mcp/pipelines/available` — 返回可用 pipeline 列表及其当前 graph_config（供前端展示）

### 依赖

- Phase 1 的 McpClient + McpServerTable
- 现有 LangGraph pipeline 基础设施

---

## Phase 3A: Prompt 模板管理

### 后端

无需改动。已有完整 API：
- `GET /prompts` — 列出所有模板
- `PUT /prompts/{id}` — 更新模板
- `GET /prompts/{name}/render` — 渲染预览

### 前端新增 Prompt Templates Card

**列表视图：**
- 按 category 分组显示（`blog_writing`, `intel_analysis`, `celebrity` 等）
- 每项显示：name, description, version badge, is_active 指示灯
- 点击展开 → 显示完整 template 文本

**编辑模式：**
- 展开后点击"编辑"进入编辑模式
- template 文本用 textarea 编辑
- 右侧显示当前 variables JSON（只读参考）
- 保存调用 `PUT /prompts/{id}`

**变量高亮：**
- 在 template 文本显示时，用 CSS 高亮 `{{变量名}}` 占位符
- 颜色区分已定义变量（绿色）vs 未定义变量（橙色）

**渲染预览：**
- "预览" 按钮 → 弹出 modal
- 左侧：variables 编辑表单（从 variables JSON 自动生成字段）
- 右侧：调用 `GET /prompts/{name}/render` 后的渲染结果
- 实时预览：每次修改 variables 自动重新渲染

---

## Phase 3B: Agent 配置统一管理

### 后端

无需改动。已有完整 API：
- `GET /agent/configs` — 列出所有 Agent 配置
- `PUT /agent/configs/{id}` — 更新配置
- `GET /agent/pipelines` — 列出 pipeline
- `PUT /agent/pipelines/{id}` — 更新 pipeline
- `POST /agent/analyze/{news_id}` — 触发分析

### 前端新增 Agent Config Card

**Agent 列表：**
- 表格/卡片形式显示所有 Agent
- 列：name, display_name, agent_type, LLM config name, is_active 状态
- 点击展开显示详情

**编辑弹窗：**
- name（只读）
- display_name（text input）
- description（text input）
- system_prompt（textarea，高度自适应）
- output_schema（JSON textarea）
- LLM config 下拉选择（数据来自 `GET /llm/configs`）
- is_active 开关
- extra_params（JSON textarea）

**Pipeline 列表（Agent 下方）：**
- 表格显示：name, display_name, 节点数量（从 graph_config 计算）, is_active
- 点击展开 → 显示 graph_config 的节点摘要列表（每节点：type + name）
- 编辑弹窗：graph_config 用 JSON textarea 编辑
- 支持包含 `mcp_tool` 类型节点（Phase 2B 扩展）

---

## Phase 3C: Skill 工作流定义

### 数据库表

**SkillDefinitionTable** (`src/infra/database/skill/repository.py`):

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 自增主键 |
| name | VARCHAR(100) UNIQUE | Skill 名称（如 "web_article_reader"） |
| display_name | VARCHAR(200) | 显示名称 |
| description | TEXT | Skill 描述 |
| input_schema | JSON | 输入参数 schema（JSON Schema 格式） |
| steps | JSON ARRAY | 执行步骤序列（见下方 steps 结构） |
| output_schema | JSON | 输出格式 schema |
| is_active | BOOLEAN DEFAULT true | 是否启用 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

**steps 结构** — JSON array，每步为一个 object：

```json
[
  {
    "type": "prompt",
    "template_id": 5,
    "variables": {"topic": "{{ input.topic }}"},
    "output_key": "rendered_prompt"
  },
  {
    "type": "mcp_tool",
    "server_id": 1,
    "tool_name": "webReader",
    "args": {"url": "{{ input.url }}"},
    "output_key": "web_content"
  },
  {
    "type": "llm_call",
    "config_id": "uuid-or-null-for-default",
    "system_prompt": "You are a content analyzer...",
    "user_prompt": "{{ steps.rendered_prompt }}\n\nContent:\n{{ steps.web_content }}",
    "output_key": "analysis"
  }
]
```

每步的 type 及必填字段：

| type | 必填字段 | 可选字段 | 说明 |
|------|---------|---------|------|
| `prompt` | template_id, output_key | on_error | 渲染 Prompt 模板 |
| `mcp_tool` | server_id, tool_name, output_key | on_error | 调用 MCP Server 的工具 |
| `llm_call` | user_prompt, output_key | system_prompt, config_id, on_error | 调用 LLM 生成内容 |

`on_error` 可选值：`"skip"`（默认，写 None 继续执行）或 `"fail"`（抛异常中断 pipeline）。

所有字段支持 Jinja2 模板语法，可引用 `{{ input.xxx }}` 和 `{{ steps.yyy }}`。

### 后端文件

**`src/infra/database/skill/repository.py`** — 数据库 CRUD：
- SQLModel 表定义：`SkillDefinitionTable(SQLModel, table=True)`
- `create_skill_repository()` 工厂函数
- 方法：`list_skills()`, `get_skill(id)`, `create_skill(data)`, `update_skill(id, data)`, `delete_skill(id)`

**`src/domain/market/intel/agents/skill_executor.py`** — Skill 执行引擎：
- `async def execute_skill(skill_id, input_params)` — 按顺序执行 steps
- 每步执行逻辑：
  1. 用 Jinja2 渲染当前步的模板变量
  2. 根据 type 分发执行（prompt → 渲染模板，mcp_tool → McpClient 调用，llm_call → LLMManager 调用）
  3. 将结果存入 `context[output_key]`
  4. 错误处理：按每步的 `on_error` 字段决定行为——`"skip"`（默认）写 None 继续执行，`"fail"` 抛异常中断 pipeline
- 返回完整 context（包含每步的 output）

**`src/api/router/skill_router.py`** — API 端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /skills | 列出所有 Skill 定义 |
| POST | /skills | 创建 Skill |
| PUT | /skills/{id} | 更新 Skill |
| DELETE | /skills/{id} | 删除 Skill |
| POST | /skills/{id}/execute | 执行一个 Skill |
| POST | /skills/{id}/validate | 校验 steps 定义（检查引用的 template_id、server_id 是否存在） |

请求模型（`src/api/model/skill_api_model.py`）：
- `SkillCreate(name, display_name, description, input_schema, steps, output_schema, is_active)`
- `SkillUpdate` — 所有字段 Optional
- `SkillResponse` — 含 id, created_at, updated_at
- `SkillExecuteRequest(input_params: dict)`
- `SkillExecuteResponse(success: bool, outputs: dict, errors: list, duration_ms: float)`
- `SkillValidateResponse(valid: bool, errors: list)`

### 前端新增 Skill Definitions Card

**列表视图：**
- 卡片网格显示所有 Skill
- 每张：name, description, steps 数量 badge, is_active 状态灯
- 操作：编辑、删除、执行测试

**新建/编辑 Modal：**
- 基本信息：name, display_name, description
- Input Schema：JSON textarea（带格式校验）
- Steps 编辑器（两种模式可切换）：
  - **表单模式**：每步一个卡片行
    - Type 下拉（prompt / mcp_tool / llm_call）
    - 条件字段：选择 type 后显示对应字段（prompt → template_id 下拉, mcp_tool → server 下拉 + tool 下拉, llm_call → LLM config 下拉 + prompt textarea）
    - output_key 输入框
    - 可上下移动顺序、删除
  - **JSON 模式**：textarea 编辑完整 steps JSON array
- Output Schema：JSON textarea
- is_active 开关

**执行测试弹窗：**
- 输入区：根据 input_schema 动态生成表单字段
- 点击"执行" → 调用 `POST /skills/{id}/execute`
- 结果区：显示每步的 output_key → 结果值（JSON 格式化），总耗时
- 错误区：显示失败的步骤及错误信息

---

## Settings 页面布局

Settings.tsx 的 `settings__sections` 中的 Card 顺序：

1. API Configuration（已有）
2. LLM 模型配置（已有）
3. MCP Servers（Phase 1 新增）
4. MCP Tool Console（Phase 2A 新增）
5. Prompt Templates（Phase 3A 新增）
6. Agent Config（Phase 3B 新增）
7. Skill Definitions（Phase 3C 新增）
8. Feishu Notifications（已有）
9. Appearance（已有）
10. Language（已有）
11. Market Data（已有）

由于 Card 数量增多，页面会变长。CSS 改进：可以考虑两列布局（左侧 API/LLM/MCP，右侧 Prompt/Agent/Skill），但初版保持单列即可。

---

## 文件变更汇总

### 新增文件

| 文件 | Phase | 说明 |
|------|-------|------|
| `src/infra/mcp/client.py` | 1 | MCP 客户端封装（mcp SDK） |
| `src/infra/database/mcp/repository.py` | 1 | MCP Server DB CRUD |
| `src/api/router/mcp_router.py` | 1+2A | MCP Server + Tool API |
| `src/api/model/mcp_api_model.py` | 1 | MCP 请求/响应模型 |
| `src/domain/market/intel/agents/mcp_tool_node.py` | 2B | LangGraph MCP Tool Node |
| `src/infra/database/skill/repository.py` | 3C | Skill 定义 DB CRUD |
| `src/domain/market/intel/agents/skill_executor.py` | 3C | Skill 执行引擎 |
| `src/api/router/skill_router.py` | 3C | Skill API |
| `src/api/model/skill_api_model.py` | 3C | Skill 请求/响应模型 |

### 修改文件

| 文件 | Phase | 说明 |
|------|-------|------|
| `main.py` | 1+3C | 注册 mcp_router + skill_router |
| `frontend/apps/web/src/pages/Settings.tsx` | 1-3 | 新增 6 张 Card 组件 |
| `frontend/apps/web/src/pages/Settings.css` | 1-3 | 新增 Card 样式 |

### 不改动的文件

| 文件 | 原因 |
|------|------|
| `conf/settings.py` | MCP/Skill 配置存 DB，不存 YAML |
| `src/api/router/prompt_router.py` | Phase 3A 只加前端，后端已完整 |
| `src/api/router/agent_router.py` | Phase 3B 只加前端，后端已完整 |

---

## 实施顺序

```
Phase 1 (MCP Server 管理)
  ├── 后端: mcp_api_model + mcp client + mcp repository + mcp_router
  ├── main.py: 注册 mcp_router
  └── 前端: Settings.tsx MCP Servers Card

Phase 2A (MCP Tool 面板) — 依赖 Phase 1
  ├── 后端: mcp_router 新增 invoke 端点
  └── 前端: Settings.tsx MCP Tool Console Card

Phase 2B (Pipeline 集成) — 依赖 Phase 1
  ├── 后端: mcp_tool_node.py
  └── 前端: 无（配置在 Agent Config Card 中展示）

Phase 3A (Prompt 模板) — 无依赖
  └── 前端: Settings.tsx Prompt Templates Card

Phase 3B (Agent 配置) — 无依赖
  └── 前端: Settings.tsx Agent Config Card

Phase 3C (Skill 定义) — 依赖 Phase 1 + Phase 2
  ├── 后端: skill_api_model + skill repository + skill_executor + skill_router
  ├── main.py: 注册 skill_router
  └── 前端: Settings.tsx Skill Definitions Card
```

可并行的实施路径：
- Phase 1 先做（其他都依赖它）
- Phase 2A + 2B 可并行
- Phase 3A + 3B 可与 Phase 2 并行
- Phase 3C 在 Phase 1 完成后开始
