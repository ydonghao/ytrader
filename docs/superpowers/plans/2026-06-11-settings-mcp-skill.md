# Settings MCP + Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MCP Server management, Tool invocation, Pipeline integration, Prompt/Agent management UI, and Skill workflow definition to the Settings page.

**Architecture:** Backend uses Python `mcp` SDK as MCP Client connecting to external MCP Servers (stdio/SSE). SQLModel tables store server configs and skill definitions. Frontend adds 6 new Cards to the existing Settings page. Skill executor runs step sequences (prompt render → mcp_tool call → llm_call) using Jinja2 templating.

**Tech Stack:** Python `mcp` SDK, SQLModel ORM, FastAPI, Jinja2, React (Settings.tsx), Python `mcp` client library

**Spec:** `docs/superpowers/specs/2026-06-11-settings-mcp-skill-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/src/api/model/mcp_api_model.py` | Pydantic request/response models for MCP API |
| `backend/src/infra/database/mcp/entity.py` | SQLModel table: `McpServerTable` |
| `backend/src/infra/database/mcp/repository.py` | MCP server DB CRUD + factory |
| `backend/src/infra/mcp/client.py` | MCP SDK wrapper: connect, list_tools, call_tool, health_check |
| `backend/src/api/router/mcp_router.py` | MCP Server CRUD + Tool invoke endpoints |
| `backend/src/domain/market/intel/agents/mcp_tool_node.py` | LangGraph node: call MCP tool from pipeline state |
| `backend/src/api/model/skill_api_model.py` | Pydantic request/response models for Skill API |
| `backend/src/infra/database/skill/entity.py` | SQLModel table: `SkillDefinitionTable` |
| `backend/src/infra/database/skill/repository.py` | Skill definition DB CRUD + factory |
| `backend/src/domain/market/intel/agents/skill_executor.py` | Skill execution engine: sequential step runner |
| `backend/src/api/router/skill_router.py` | Skill CRUD + execute + validate endpoints |

### Modified Files

| File | Change |
|------|--------|
| `backend/main.py` | Add 2 imports + 2 `include_router` lines |
| `frontend/apps/web/src/pages/Settings.tsx` | Add 6 Card components (~1200 lines total) |
| `frontend/apps/web/src/pages/Settings.css` | Add card-specific styles (~300 lines) |

---

## Phase 1: MCP Server Connection Management

### Task 1: MCP API Models

**Files:**
- Create: `backend/src/api/model/mcp_api_model.py`

- [ ] **Step 1: Create the Pydantic models file**

```python
"""Request/response models for MCP config API."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel


class McpServerCreate(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    transport_type: Literal["stdio", "sse"] = "stdio"
    command: str = ""
    url: str = ""
    headers: dict[str, str] = {}
    env_vars: dict[str, str] = {}
    is_active: bool = True


class McpServerUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    transport_type: Literal["stdio", "sse"] | None = None
    command: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    env_vars: dict[str, str] | None = None
    is_active: bool | None = None


class McpServerResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    transport_type: str
    command: str
    url: str
    headers: dict[str, str]
    env_vars: dict[str, str]
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None


class McpTestResponse(BaseModel):
    success: bool
    message: str
    tools_count: int = 0
    tools: list[dict[str, Any]] = []
    duration_ms: float = 0.0


class McpToolInvokeRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = {}


class McpToolInvokeResponse(BaseModel):
    tool: str
    result: Any = None
    duration_ms: float = 0.0
    error: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/api/model/mcp_api_model.py
git commit -m "feat(mcp): add MCP API request/response models"
```

---

### Task 2: MCP Entity (SQLModel Table)

**Files:**
- Create: `backend/src/infra/database/mcp/entity.py`

- [ ] **Step 1: Create the SQLModel table definition**

```python
"""MCP server SQLModel table definition."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field


class McpServerTable(SQLModel, table=True):
    __tablename__ = "mcp_server"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=100)
    display_name: str = Field(default="", max_length=200)
    description: str = Field(default="", sa_column=Column(Text))
    transport_type: str = Field(default="stdio", max_length=20)
    command: str = Field(default="", sa_column=Column(Text))
    url: str = Field(default="", max_length=500)
    headers: dict = Field(default={}, sa_column=Column(JSONB))
    env_vars: dict = Field(default={}, sa_column=Column(JSONB))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/infra/database/mcp/entity.py
git commit -m "feat(mcp): add McpServerTable SQLModel entity"
```

---

### Task 3: MCP Repository (DB CRUD)

**Files:**
- Create: `backend/src/infra/database/mcp/__init__.py`
- Create: `backend/src/infra/database/mcp/repository.py`

- [ ] **Step 1: Create `__init__.py`**

```python
"""MCP database module."""
```

- [ ] **Step 2: Create the repository**

```python
"""MCP server repository — CRUD operations for McpServerTable."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlmodel import select

from src.infra.database.mcp.entity import McpServerTable
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn


# ── Singleton DB connection ────────────────────────────────────────────

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    """Thread-safe singleton DB connection."""
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def _row_to_dict(row: McpServerTable) -> dict:
    """Convert a DB row to a response dict."""
    return {
        "id": row.id,
        "name": row.name,
        "display_name": row.display_name,
        "description": row.description,
        "transport_type": row.transport_type,
        "command": row.command,
        "url": row.url,
        "headers": row.headers or {},
        "env_vars": row.env_vars or {},
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class McpServerRepository:
    """MCP server config repository."""

    def __init__(self, db_connection: DBConnection | None = None):
        self._db = db_connection or _get_db_connection()

    def list_servers(self) -> list[dict]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(McpServerTable).order_by(McpServerTable.id)
            ).all()
            return [_row_to_dict(r) for r in rows]

    def get_server(self, server_id: int) -> dict | None:
        with self._db.session_scope() as session:
            row = session.get(McpServerTable, server_id)
            if row is None:
                return None
            return _row_to_dict(row)

    def get_server_by_name(self, name: str) -> dict | None:
        with self._db.session_scope() as session:
            stmt = select(McpServerTable).where(
                McpServerTable.name == name
            ).limit(1)
            row = session.exec(stmt).first()
            if row is None:
                return None
            return _row_to_dict(row)

    def create_server(self, data: dict) -> dict:
        row = McpServerTable(
            name=data["name"],
            display_name=data.get("display_name", ""),
            description=data.get("description", ""),
            transport_type=data.get("transport_type", "stdio"),
            command=data.get("command", ""),
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            env_vars=data.get("env_vars", {}),
            is_active=data.get("is_active", True),
        )
        with self._db.session_scope() as session:
            session.add(row)
            session.flush()
            session.refresh(row)
            result = _row_to_dict(row)
        return result

    def update_server(
        self, server_id: int, updates: dict,
    ) -> dict | None:
        with self._db.session_scope() as session:
            row = session.get(McpServerTable, server_id)
            if row is None:
                return None
            for key, value in updates.items():
                if value is not None:
                    setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            session.refresh(row)
            result = _row_to_dict(row)
        return result

    def delete_server(self, server_id: int) -> bool:
        with self._db.session_scope() as session:
            row = session.get(McpServerTable, server_id)
            if row is None:
                return False
            session.delete(row)
        return True


# ── Factory ────────────────────────────────────────────────────────────

def create_mcp_repository(
    db_connection: DBConnection | None = None,
) -> McpServerRepository:
    """Factory function for McpServerRepository."""
    return McpServerRepository(db_connection)
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/database/mcp/
git commit -m "feat(mcp): add MCP server repository with CRUD operations"
```

---

### Task 4: MCP Client (mcp SDK Wrapper)

**Files:**
- Create: `backend/src/infra/mcp/__init__.py`
- Create: `backend/src/infra/mcp/client.py`

- [ ] **Step 1: Install the `mcp` Python package**

```bash
cd backend && uv add mcp
```

- [ ] **Step 2: Create `__init__.py`**

```python
"""MCP client module."""
```

- [ ] **Step 3: Create the MCP client wrapper**

This wraps the `mcp` SDK to connect to an external MCP Server via stdio or SSE, list its tools, and invoke them. Uses "connect-execute-disconnect" pattern — no persistent connections.

```python
"""MCP Client — connects to external MCP Servers via stdio or SSE.

Uses the Python ``mcp`` SDK. Each operation opens a connection,
executes, then closes — no persistent connections to avoid leaks.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class McpServerConfig:
    """Connection config for a single MCP server."""
    transport_type: str  # "stdio" or "sse"
    command: str = ""     # stdio: launch command (e.g. "npx @anthropic/mcp-server-web-reader")
    url: str = ""         # sse: server URL (e.g. "http://localhost:3001/sse")
    headers: dict[str, str] | None = None  # sse: auth headers
    env_vars: dict[str, str] | None = None  # stdio: env vars


@dataclass
class McpToolInfo:
    """A single tool exposed by an MCP server."""
    name: str
    description: str
    input_schema: dict[str, Any]


class McpClient:
    """Async MCP client — connect, list tools, call tool, disconnect.

    Usage::

        async with McpClient(config) as client:
            tools = await client.list_tools()
            result = await client.call_tool("webReader", {"url": "..."})
    """

    def __init__(self, config: McpServerConfig):
        self._config = config
        self._session: Any = None
        self._exit_stack: Any = None

    async def __aenter__(self) -> McpClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """Open a connection to the MCP server."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.sse import sse_client
        except ImportError:
            raise RuntimeError(
                "Python 'mcp' package not installed. "
                "Run: uv add mcp"
            )

        from contextlib import AsyncExitStack

        self._exit_stack = AsyncExitStack()

        if self._config.transport_type == "stdio":
            server_params = StdioServerParameters(
                command=self._config.command.split()[0] if self._config.command else "",
                args=self._config.command.split()[1:] if self._config.command else [],
                env=self._config.env_vars or None,
            )
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
        else:  # sse
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                sse_client(
                    url=self._config.url,
                    headers=self._config.headers or {},
                )
            )

        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        logger.debug(
            f"[McpClient] Connected to "
            f"{self._config.transport_type} server"
        )

    async def disconnect(self) -> None:
        """Close the connection."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._session = None
            self._exit_stack = None
            logger.debug("[McpClient] Disconnected")

    async def list_tools(self) -> list[McpToolInfo]:
        """List tools exposed by the connected server."""
        result = await self._session.list_tools()
        return [
            McpToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {},
            )
            for t in result.tools
        ]

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any],
    ) -> Any:
        """Invoke a tool on the connected server."""
        result = await self._session.call_tool(tool_name, arguments)
        # MCP returns content blocks; extract text or return raw
        if result.content and len(result.content) == 1:
            content = result.content[0]
            if hasattr(content, "text"):
                return content.text
        return [
            c.text if hasattr(c, "text") else str(c)
            for c in result.content
        ]

    @staticmethod
    async def health_check(config: McpServerConfig) -> tuple[bool, str, list[McpToolInfo], float]:
        """Test connectivity: connect → list_tools → disconnect.

        Returns (success, message, tools, duration_ms).
        """
        start = time.monotonic()
        try:
            async with McpClient(config) as client:
                tools = await client.list_tools()
                elapsed = (time.monotonic() - start) * 1000
                return (
                    True,
                    f"Connected, {len(tools)} tools available",
                    tools,
                    elapsed,
                )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return (False, str(e), [], elapsed)
```

- [ ] **Step 4: Commit**

```bash
git add backend/src/infra/mcp/ backend/uv.lock backend/pyproject.toml
git commit -m "feat(mcp): add McpClient wrapper for mcp SDK (stdio/sse)"
```

---

### Task 5: MCP Router (API Endpoints)

**Files:**
- Create: `backend/src/api/router/mcp_router.py`

- [ ] **Step 1: Create the MCP router with all Phase 1 + 2A endpoints**

```python
"""MCP Server management and tool invocation API router."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.api.model.mcp_api_model import (
    McpServerCreate,
    McpServerUpdate,
    McpServerResponse,
    McpTestResponse,
    McpToolInvokeRequest,
    McpToolInvokeResponse,
)
from src.infra.database.mcp.repository import create_mcp_repository
from src.infra.mcp.client import McpClient, McpServerConfig


router = APIRouter(prefix="/mcp", tags=["mcp"])

_repo = create_mcp_repository()


def _ok(data) -> dict:
    return {"code": 0, "msg": "ok", "data": data}


def _to_response(row: dict) -> McpServerResponse:
    return McpServerResponse(**row)


def _build_config(server: dict) -> McpServerConfig:
    """Build McpServerConfig from a DB row dict."""
    return McpServerConfig(
        transport_type=server["transport_type"],
        command=server.get("command", ""),
        url=server.get("url", ""),
        headers=server.get("headers") or {},
        env_vars=server.get("env_vars") or {},
    )


# ── Server CRUD ────────────────────────────────────────────────────────

@router.get("/servers")
def list_servers():
    """List all configured MCP servers."""
    servers = _repo.list_servers()
    return _ok([_to_response(s) for s in servers])


@router.post("/servers", status_code=201)
def create_server(body: McpServerCreate):
    """Add a new MCP server configuration."""
    data = body.model_dump()
    created = _repo.create_server(data)
    return _ok(_to_response(created))


@router.put("/servers/{server_id}")
def update_server(server_id: int, body: McpServerUpdate):
    """Update an existing MCP server configuration."""
    updates = body.model_dump(exclude_none=True)
    updated = _repo.update_server(server_id, updates)
    if updated is None:
        raise HTTPException(404, "Server not found")
    return _ok(_to_response(updated))


@router.delete("/servers/{server_id}")
def delete_server(server_id: int):
    """Delete an MCP server configuration."""
    deleted = _repo.delete_server(server_id)
    if not deleted:
        raise HTTPException(404, "Server not found")
    return _ok({"deleted": True})


# ── Server Actions ─────────────────────────────────────────────────────

@router.post("/servers/{server_id}/test")
async def test_server(server_id: int):
    """Test connectivity to an MCP server."""
    server = _repo.get_server(server_id)
    if server is None:
        raise HTTPException(404, "Server not found")

    config = _build_config(server)
    success, message, tools, duration_ms = await McpClient.health_check(config)

    return _ok(McpTestResponse(
        success=success,
        message=message,
        tools_count=len(tools),
        tools=[{"name": t.name, "description": t.description} for t in tools],
        duration_ms=round(duration_ms, 1),
    ))


@router.get("/servers/{server_id}/tools")
async def list_server_tools(server_id: int):
    """List tools exposed by an MCP server."""
    server = _repo.get_server(server_id)
    if server is None:
        raise HTTPException(404, "Server not found")

    config = _build_config(server)
    try:
        async with McpClient(config) as client:
            tools = await client.list_tools()
        return _ok([
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ])
    except Exception as e:
        logger.warning(f"[mcp_router] list_tools failed: {e}")
        raise HTTPException(502, f"Failed to list tools: {e}")


# ── Tool Invocation (Phase 2A) ─────────────────────────────────────────

@router.post("/servers/{server_id}/invoke")
async def invoke_tool(server_id: int, body: McpToolInvokeRequest):
    """Invoke a tool on a specific MCP server."""
    server = _repo.get_server(server_id)
    if server is None:
        raise HTTPException(404, "Server not found")

    config = _build_config(server)
    start = time.monotonic()
    try:
        async with McpClient(config) as client:
            result = await client.call_tool(body.tool_name, body.arguments)
        elapsed = (time.monotonic() - start) * 1000
        return _ok(McpToolInvokeResponse(
            tool=body.tool_name,
            result=result,
            duration_ms=round(elapsed, 1),
            error=None,
        ))
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning(
            f"[mcp_router] invoke {body.tool_name} failed: {e}"
        )
        return _ok(McpToolInvokeResponse(
            tool=body.tool_name,
            result=None,
            duration_ms=round(elapsed, 1),
            error=str(e),
        ))
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/api/router/mcp_router.py
git commit -m "feat(mcp): add MCP router with server CRUD + tool invoke endpoints"
```

---

### Task 6: Register MCP Router in main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add import**

After the `blog_router` import line (around line 42), add:

```python
from src.api.router.mcp_router import router as mcp_router
```

- [ ] **Step 2: Add router registration**

After the `intel_cctv_router` registration line (around line 262), add:

```python
    app.include_router(mcp_router, prefix="/api/v1")  # /api/v1/mcp
```

- [ ] **Step 3: Verify backend starts**

```bash
cd backend && python main.py &
sleep 3 && curl -s http://localhost:12100/api/v1/mcp/servers | python -m json.tool
# Expected: {"code": 0, "msg": "ok", "data": []}
kill %1
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(mcp): register MCP router in main.py"
```

---

### Task 7: Frontend — MCP Servers Card

**Files:**
- Modify: `frontend/apps/web/src/pages/Settings.tsx`
- Modify: `frontend/apps/web/src/pages/Settings.css`

This Card follows the exact pattern of the existing LLM Model Config Card (list + modal + CRUD + test).

- [ ] **Step 1: Add MCP state variables**

After the LLM Model Config state block (after line 42), add:

```tsx
  // MCP Server Config
  const [mcpServers, setMcpServers] = useState<any[]>([]);
  const [mcpLoading, setMcpLoading] = useState(false);
  const [showMcpModal, setShowMcpModal] = useState(false);
  const [editingMcp, setEditingMcp] = useState<any>(null);
  const [mcpForm, setMcpForm] = useState({
    name: '', display_name: '', description: '',
    transport_type: 'stdio' as string, command: '', url: '',
    headers: '{}', env_vars: '{}', is_active: true,
  });
  const [mcpTestResult, setMcpTestResult] = useState<{success: boolean; message: string; tools_count?: number; duration_ms?: number} | null>(null);
  const [mcpTesting, setMcpTesting] = useState(false);
  const [expandedMcpTools, setExpandedMcpTools] = useState<Record<number, any[]>>({});
```

- [ ] **Step 2: Add MCP CRUD functions**

After the `openEditModal` function (after line 220), add:

```tsx
  // ── MCP Server CRUD ────────────────────────────────────────────────
  const fetchMcpServers = useCallback(() => {
    setMcpLoading(true);
    fetch(`${getStoredApiBase()}/mcp/servers`)
      .then(r => r.json())
      .then(j => { if (j.code === 0) setMcpServers(j.data); })
      .catch(() => {})
      .finally(() => setMcpLoading(false));
  }, []);

  const saveMcpServer = async () => {
    const payload: any = {...mcpForm};
    try { payload.headers = JSON.parse(payload.headers || '{}'); } catch { payload.headers = {}; }
    try { payload.env_vars = JSON.parse(payload.env_vars || '{}'); } catch { payload.env_vars = {}; }
    const url = editingMcp
      ? `${getStoredApiBase()}/mcp/servers/${editingMcp.id}`
      : `${getStoredApiBase()}/mcp/servers`;
    const res = await fetch(url, {
      method: editingMcp ? 'PUT' : 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const j = await res.json();
    if (j.code === 0 || j.code === 201) {
      setShowMcpModal(false);
      setEditingMcp(null);
      fetchMcpServers();
    }
  };

  const deleteMcpServer = async (id: number) => {
    if (!confirm('确定删除此 MCP 服务器配置？')) return;
    await fetch(`${getStoredApiBase()}/mcp/servers/${id}`, {method: 'DELETE'});
    fetchMcpServers();
  };

  const testMcpServer = async (id: number) => {
    setMcpTesting(true);
    setMcpTestResult(null);
    try {
      const res = await fetch(`${getStoredApiBase()}/mcp/servers/${id}/test`, {method: 'POST'});
      const j = await res.json();
      if (j.code === 0) setMcpTestResult(j.data);
    } catch (e: any) {
      setMcpTestResult({success: false, message: e.message});
    } finally {
      setMcpTesting(false);
    }
  };

  const toggleMcpTools = async (id: number) => {
    if (expandedMcpTools[id]) {
      setExpandedMcpTools(prev => { const n = {...prev}; delete n[id]; return n; });
      return;
    }
    try {
      const res = await fetch(`${getStoredApiBase()}/mcp/servers/${id}/tools`);
      const j = await res.json();
      if (j.code === 0) setExpandedMcpTools(prev => ({...prev, [id]: j.data}));
    } catch {}
  };

  const openMcpModal = (server?: any) => {
    if (server) {
      setEditingMcp(server);
      setMcpForm({
        name: server.name,
        display_name: server.display_name || '',
        description: server.description || '',
        transport_type: server.transport_type || 'stdio',
        command: server.command || '',
        url: server.url || '',
        headers: JSON.stringify(server.headers || {}, null, 2),
        env_vars: JSON.stringify(server.env_vars || {}, null, 2),
        is_active: server.is_active ?? true,
      });
    } else {
      setEditingMcp(null);
      setMcpForm({
        name: '', display_name: '', description: '',
        transport_type: 'stdio', command: '', url: '',
        headers: '{}', env_vars: '{}', is_active: true,
      });
    }
    setShowMcpModal(true);
  };

  useEffect(() => { fetchMcpServers(); }, [fetchMcpServers]);
```

- [ ] **Step 3: Add MCP Servers Card JSX**

Insert after the LLM Model Config Card closing `</Card>` (after line 383) and before the Feishu Notifications Card:

```tsx
        {/* ── MCP Servers ── */}
        <Card>
          <CardHeader>
            <CardTitle>🔌 MCP Servers</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__llm-toolbar">
              <Button size="sm" onClick={() => openMcpModal()}>+ 添加服务器</Button>
            </div>

            <div className="settings__llm-list">
              {mcpServers.length === 0 && !mcpLoading && (
                <div className="settings__llm-empty">暂无 MCP 服务器配置</div>
              )}
              {mcpServers.map(srv => (
                <div key={srv.id} className="settings__llm-card">
                  <div className="settings__llm-card-header">
                    <span className="settings__llm-card-name">
                      {srv.display_name || srv.name}
                      <Badge variant={srv.transport_type === 'sse' ? 'info' : 'secondary'}>
                        {srv.transport_type.toUpperCase()}
                      </Badge>
                      {srv.is_active
                        ? <span style={{color: 'var(--color-success)', fontSize: '0.75rem'}}>● Active</span>
                        : <span style={{color: 'var(--color-text-secondary)', fontSize: '0.75rem'}}>○ Inactive</span>
                      }
                    </span>
                    <div className="settings__llm-card-actions">
                      <Button variant="secondary" size="sm" onClick={() => testMcpServer(srv.id)} disabled={mcpTesting}>
                        测试
                      </Button>
                      <Button variant="secondary" size="sm" onClick={() => openMcpModal(srv)}>编辑</Button>
                      <Button variant="secondary" size="sm" onClick={() => deleteMcpServer(srv.id)}>删除</Button>
                    </div>
                  </div>
                  <div className="settings__llm-card-meta">
                    <span>{srv.transport_type === 'stdio' ? srv.command : srv.url}</span>
                  </div>
                  {mcpTestResult && (
                    <div className={`settings__test-msg settings__test-msg--${mcpTestResult.success ? 'success' : 'error'}`}>
                      {mcpTestResult.message}
                      {mcpTestResult.duration_ms != null && ` (${mcpTestResult.duration_ms}ms)`}
                    </div>
                  )}
                  <div style={{marginTop: '0.5rem'}}>
                    <Button variant="secondary" size="sm" onClick={() => toggleMcpTools(srv.id)}>
                      {expandedMcpTools[srv.id] ? '收起工具' : '查看工具'}
                    </Button>
                  </div>
                  {expandedMcpTools[srv.id] && (
                    <div className="settings__mcp-tools-list">
                      {expandedMcpTools[srv.id].map((tool: any) => (
                        <div key={tool.name} className="settings__mcp-tool-item">
                          <strong>{tool.name}</strong>
                          <span style={{color: 'var(--color-text-secondary)', fontSize: '0.8125rem', marginLeft: '0.5rem'}}>
                            {tool.description}
                          </span>
                        </div>
                      ))}
                      {expandedMcpTools[srv.id].length === 0 && (
                        <div style={{color: 'var(--color-text-secondary)', fontSize: '0.8125rem'}}>无可用工具</div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {showMcpModal && (
              <div className="settings__modal-overlay" onClick={() => setShowMcpModal(false)}>
                <div className="settings__modal settings__modal--wide" onClick={e => e.stopPropagation()}>
                  <h3 className="settings__modal-title">{editingMcp ? '编辑 MCP 服务器' : '添加 MCP 服务器'}</h3>
                  <div className="settings__field">
                    <label className="settings__label">名称 (唯一标识)</label>
                    <input className="settings__input" value={mcpForm.name}
                      onChange={e => setMcpForm({...mcpForm, name: e.target.value})} placeholder="web_reader" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">显示名称</label>
                    <input className="settings__input" value={mcpForm.display_name}
                      onChange={e => setMcpForm({...mcpForm, display_name: e.target.value})} placeholder="Web Reader" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">描述</label>
                    <input className="settings__input" value={mcpForm.description}
                      onChange={e => setMcpForm({...mcpForm, description: e.target.value})} placeholder="Read web pages" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">Transport Type</label>
                    <select className="settings__input" value={mcpForm.transport_type}
                      onChange={e => setMcpForm({...mcpForm, transport_type: e.target.value})}>
                      <option value="stdio">stdio</option>
                      <option value="sse">sse</option>
                    </select>
                  </div>
                  {mcpForm.transport_type === 'stdio' ? (
                    <div className="settings__field">
                      <label className="settings__label">Command</label>
                      <input className="settings__input" value={mcpForm.command}
                        onChange={e => setMcpForm({...mcpForm, command: e.target.value})}
                        placeholder="npx @anthropic/mcp-server-web-reader" />
                    </div>
                  ) : (
                    <>
                      <div className="settings__field">
                        <label className="settings__label">URL</label>
                        <input className="settings__input" value={mcpForm.url}
                          onChange={e => setMcpForm({...mcpForm, url: e.target.value})}
                          placeholder="http://localhost:3001/sse" />
                      </div>
                      <div className="settings__field">
                        <label className="settings__label">Headers (JSON)</label>
                        <textarea className="settings__input settings__textarea" value={mcpForm.headers}
                          onChange={e => setMcpForm({...mcpForm, headers: e.target.value})} rows={3} />
                      </div>
                    </>
                  )}
                  <div className="settings__field">
                    <label className="settings__label">Environment Variables (JSON)</label>
                    <textarea className="settings__input settings__textarea" value={mcpForm.env_vars}
                      onChange={e => setMcpForm({...mcpForm, env_vars: e.target.value})} rows={3} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">
                      <input type="checkbox" checked={mcpForm.is_active}
                        onChange={e => setMcpForm({...mcpForm, is_active: e.target.checked})} />
                      {' '}启用
                    </label>
                  </div>
                  <div className="settings__modal-actions">
                    <Button onClick={saveMcpServer}>保存</Button>
                    <Button variant="secondary" onClick={() => setShowMcpModal(false)}>取消</Button>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
```

- [ ] **Step 4: Add MCP CSS styles**

Append to `Settings.css`:

```css
/* MCP Tools List */
.settings__mcp-tools-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin-top: 0.5rem;
  padding: 0.5rem;
  background: var(--color-background);
  border-radius: var(--radius-md);
}

.settings__mcp-tool-item {
  padding: 0.375rem 0.5rem;
  font-size: 0.8125rem;
  border-bottom: 1px solid var(--color-border);
}

.settings__mcp-tool-item:last-child {
  border-bottom: none;
}

/* Wide modal for complex forms */
.settings__modal--wide {
  max-width: 560px;
}

.settings__textarea {
  resize: vertical;
  min-height: 60px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  line-height: 1.5;
}
```

- [ ] **Step 5: Verify frontend compiles**

```bash
cd frontend && pnpm --filter web build 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/pages/Settings.tsx frontend/apps/web/src/pages/Settings.css
git commit -m "feat(mcp): add MCP Servers Card to Settings page"
```

---

## Phase 2A: MCP Tool Invocation Console

### Task 8: Frontend — MCP Tool Console Card

The backend invoke endpoint was already included in Task 5. This task adds only the frontend Card.

**Files:**
- Modify: `frontend/apps/web/src/pages/Settings.tsx`
- Modify: `frontend/apps/web/src/pages/Settings.css`

- [ ] **Step 1: Add Tool Console state variables**

After the MCP Server Config state block added in Task 7, add:

```tsx
  // MCP Tool Console
  const [toolConsoleServer, setToolConsoleServer] = useState<number | null>(null);
  const [toolConsoleTools, setToolConsoleTools] = useState<any[]>([]);
  const [toolConsoleTool, setToolConsoleTool] = useState<string>('');
  const [toolConsoleArgs, setToolConsoleArgs] = useState('{}');
  const [toolConsoleResult, setToolConsoleResult] = useState<any>(null);
  const [toolConsoleRunning, setToolConsoleRunning] = useState(false);
  const [toolConsoleHistory, setToolConsoleHistory] = useState<any[]>([]);
```

- [ ] **Step 2: Add Tool Console functions**

After the MCP CRUD functions added in Task 7, add:

```tsx
  // ── MCP Tool Console ───────────────────────────────────────────────
  const loadToolConsoleTools = async (serverId: number) => {
    setToolConsoleServer(serverId);
    setToolConsoleTools([]);
    setToolConsoleTool('');
    try {
      const res = await fetch(`${getStoredApiBase()}/mcp/servers/${serverId}/tools`);
      const j = await res.json();
      if (j.code === 0) setToolConsoleTools(j.data);
    } catch {}
  };

  const executeToolConsole = async () => {
    if (!toolConsoleServer || !toolConsoleTool) return;
    setToolConsoleRunning(true);
    let args: any = {};
    try { args = JSON.parse(toolConsoleArgs); } catch {}
    try {
      const res = await fetch(`${getStoredApiBase()}/mcp/servers/${toolConsoleServer}/invoke`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tool_name: toolConsoleTool, arguments: args}),
      });
      const j = await res.json();
      if (j.code === 0) {
        setToolConsoleResult(j.data);
        setToolConsoleHistory(prev => [{
          server: mcpServers.find(s => s.id === toolConsoleServer)?.name,
          tool: toolConsoleTool,
          args: toolConsoleArgs,
          success: !j.data.error,
          time: new Date().toLocaleTimeString(),
        }, ...prev].slice(0, 10));
      }
    } catch (e: any) {
      setToolConsoleResult({error: e.message});
    } finally {
      setToolConsoleRunning(false);
    }
  };

  const refillFromHistory = (item: any) => {
    const srv = mcpServers.find(s => s.name === item.server);
    if (srv) {
      setToolConsoleServer(srv.id);
      loadToolConsoleTools(srv.id);
    }
    setToolConsoleTool(item.tool);
    setToolConsoleArgs(item.args);
  };
```

- [ ] **Step 3: Add Tool Console Card JSX**

Insert after the MCP Servers Card (after the closing `</Card>` of MCP Servers):

```tsx
        {/* ── MCP Tool Console ── */}
        <Card>
          <CardHeader>
            <CardTitle>🛠️ MCP Tool Console</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__tool-console">
              <div className="settings__field">
                <label className="settings__label">Server</label>
                <select className="settings__input" value={toolConsoleServer ?? ''}
                  onChange={e => { const id = Number(e.target.value); if (id) loadToolConsoleTools(id); }}>
                  <option value="">选择服务器...</option>
                  {mcpServers.filter(s => s.is_active).map(s => (
                    <option key={s.id} value={s.id}>{s.display_name || s.name}</option>
                  ))}
                </select>
              </div>
              {toolConsoleTools.length > 0 && (
                <div className="settings__field">
                  <label className="settings__label">Tool</label>
                  <select className="settings__input" value={toolConsoleTool}
                    onChange={e => setToolConsoleTool(e.target.value)}>
                    <option value="">选择工具...</option>
                    {toolConsoleTools.map(t => (
                      <option key={t.name} value={t.name}>{t.name}</option>
                    ))}
                  </select>
                  {toolConsoleTool && (
                    <span className="settings__hint">
                      {toolConsoleTools.find(t => t.name === toolConsoleTool)?.description}
                    </span>
                  )}
                </div>
              )}
              <div className="settings__field">
                <label className="settings__label">Arguments (JSON)</label>
                <textarea className="settings__input settings__textarea"
                  value={toolConsoleArgs}
                  onChange={e => setToolConsoleArgs(e.target.value)}
                  rows={4} />
              </div>
              <Button onClick={executeToolConsole} disabled={!toolConsoleServer || !toolConsoleTool || toolConsoleRunning}>
                {toolConsoleRunning ? '执行中...' : '▶ 执行'}
              </Button>

              {toolConsoleResult && (
                <div className="settings__tool-result">
                  <div className="settings__tool-result-header">
                    <span>Result</span>
                    {toolConsoleResult.duration_ms != null && (
                      <span className="settings__hint">{toolConsoleResult.duration_ms}ms</span>
                    )}
                  </div>
                  {toolConsoleResult.error ? (
                    <div className="settings__test-msg settings__test-msg--error">
                      {toolConsoleResult.error}
                    </div>
                  ) : (
                    <pre className="settings__tool-result-json">
                      {typeof toolConsoleResult.result === 'string'
                        ? toolConsoleResult.result
                        : JSON.stringify(toolConsoleResult.result, null, 2)}
                    </pre>
                  )}
                </div>
              )}

              {toolConsoleHistory.length > 0 && (
                <div className="settings__tool-history">
                  <div className="settings__tool-result-header">History (session)</div>
                  {toolConsoleHistory.map((h, i) => (
                    <div key={i} className="settings__tool-history-item" onClick={() => refillFromHistory(h)}>
                      <span>{h.server} / {h.tool}</span>
                      <span className="settings__hint">{h.time}</span>
                      <span className={h.success ? 'settings__test-msg--success' : 'settings__test-msg--error'}>
                        {h.success ? '✓' : '✗'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
```

- [ ] **Step 4: Add Tool Console CSS**

Append to `Settings.css`:

```css
/* MCP Tool Console */
.settings__tool-console {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.settings__tool-result {
  margin-top: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.settings__tool-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  background: var(--color-surface);
  font-size: 0.8125rem;
  font-weight: 600;
  border-bottom: 1px solid var(--color-border);
}

.settings__tool-result-json {
  padding: 0.75rem;
  margin: 0;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  color: var(--color-text);
  background: var(--color-background);
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.settings__tool-history {
  margin-top: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.settings__tool-history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.375rem 0.75rem;
  font-size: 0.8125rem;
  cursor: pointer;
  border-bottom: 1px solid var(--color-border);
}

.settings__tool-history-item:last-child {
  border-bottom: none;
}

.settings__tool-history-item:hover {
  background: var(--color-surface-hover);
}
```

- [ ] **Step 5: Verify frontend compiles**

```bash
cd frontend && pnpm --filter web build 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/pages/Settings.tsx frontend/apps/web/src/pages/Settings.css
git commit -m "feat(mcp): add MCP Tool Console Card to Settings page"
```

---

## Phase 2B: Agent Pipeline MCP Integration

### Task 9: MCPToolNode for LangGraph Pipelines

**Files:**
- Create: `backend/src/domain/market/intel/agents/mcp_tool_node.py`

- [ ] **Step 1: Create MCPToolNode**

```python
"""LangGraph node — calls an MCP tool and writes result into pipeline state.

Configuration (passed as node_config dict):
    server_id: int        — PK of McpServerTable row
    tool_name: str        — tool to call on that server
    args_template: dict   — Jinja2-template args (values like "{{ state.xxx }}")
    output_key: str       — key name to write into pipeline state
    on_error: str         — "skip" (default, write None) or "fail" (raise)
"""
from __future__ import annotations

from typing import Any

from jinja2 import Template
from loguru import logger

from src.infra.database.mcp.repository import create_mcp_repository
from src.infra.mcp.client import McpClient, McpServerConfig


class MCPToolNode:
    """LangGraph-compatible node that calls an MCP tool."""

    def __init__(self, node_config: dict):
        self.server_id: int = node_config["server_id"]
        self.tool_name: str = node_config["tool_name"]
        self.args_template: dict = node_config.get("args_template", {})
        self.output_key: str = node_config["output_key"]
        self.on_error: str = node_config.get("on_error", "skip")

    async def __call__(self, state: dict) -> dict:
        """Execute the MCP tool call and return state update."""
        try:
            repo = create_mcp_repository()
            server = repo.get_server(self.server_id)
            if server is None:
                raise ValueError(
                    f"MCP server id={self.server_id} not found"
                )

            config = McpServerConfig(
                transport_type=server["transport_type"],
                command=server.get("command", ""),
                url=server.get("url", ""),
                headers=server.get("headers") or {},
                env_vars=server.get("env_vars") or {},
            )

            # Render Jinja2 templates from state
            rendered_args: dict[str, Any] = {}
            for key, template_str in self.args_template.items():
                if isinstance(template_str, str) and "{{" in template_str:
                    rendered_args[key] = Template(template_str).render(
                        state=state,
                    )
                else:
                    rendered_args[key] = template_str

            # Call tool
            async with McpClient(config) as client:
                result = await client.call_tool(
                    self.tool_name, rendered_args,
                )

            logger.info(
                f"[MCPToolNode] {self.tool_name} → "
                f"{self.output_key} ({len(str(result))} chars)"
            )
            return {self.output_key: result}

        except Exception as e:
            logger.warning(
                f"[MCPToolNode] {self.tool_name} failed: {e}"
            )
            if self.on_error == "fail":
                raise
            return {self.output_key: None}
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/domain/market/intel/agents/mcp_tool_node.py
git commit -m "feat(mcp): add MCPToolNode for LangGraph pipeline integration"
```

---

## Phase 3A: Prompt Template Management UI

### Task 10: Frontend — Prompt Templates Card

**Files:**
- Modify: `frontend/apps/web/src/pages/Settings.tsx`

The backend already has `GET /prompts`, `PUT /prompts/{id}`, and `GET /prompts/{name}/render` from `prompt_router.py`. This task adds only the frontend Card.

- [ ] **Step 1: Add Prompt Templates state variables**

```tsx
  // Prompt Templates
  const [prompts, setPrompts] = useState<any[]>([]);
  const [promptsLoading, setPromptsLoading] = useState(false);
  const [expandedPrompt, setExpandedPrompt] = useState<number | null>(null);
  const [editingPromptId, setEditingPromptId] = useState<number | null>(null);
  const [promptEditText, setPromptEditText] = useState('');
  const [promptPreview, setPromptPreview] = useState<{name: string; rendered: string} | null>(null);
  const [showPromptPreviewModal, setShowPromptPreviewModal] = useState(false);
```

- [ ] **Step 2: Add Prompt Templates functions**

```tsx
  // ── Prompt Templates ───────────────────────────────────────────────
  const fetchPrompts = useCallback(() => {
    setPromptsLoading(true);
    fetch(`${getStoredApiBase()}/prompts`)
      .then(r => r.json())
      .then(j => { if (j.code === 0) setPrompts(j.data); })
      .catch(() => {})
      .finally(() => setPromptsLoading(false));
  }, []);

  const savePromptEdit = async (id: number) => {
    await fetch(`${getStoredApiBase()}/prompts/${id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({template: promptEditText}),
    });
    setEditingPromptId(null);
    fetchPrompts();
  };

  const previewPrompt = async (name: string) => {
    try {
      const res = await fetch(`${getStoredApiBase()}/prompts/${encodeURIComponent(name)}/render`);
      const j = await res.json();
      if (j.code === 0) {
        setPromptPreview(j.data);
        setShowPromptPreviewModal(true);
      }
    } catch {}
  };

  useEffect(() => { fetchPrompts(); }, [fetchPrompts]);
```

- [ ] **Step 3: Add Prompt Templates Card JSX**

Insert before the Agent Config Card (or after MCP Tool Console Card):

```tsx
        {/* ── Prompt Templates ── */}
        <Card>
          <CardHeader>
            <CardTitle>📝 Prompt Templates</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__llm-list">
              {prompts.length === 0 && !promptsLoading && (
                <div className="settings__llm-empty">暂无 Prompt 模板</div>
              )}
              {prompts.map(pt => (
                <div key={pt.id} className="settings__llm-card">
                  <div className="settings__llm-card-header">
                    <span className="settings__llm-card-name">
                      {pt.name}
                      <Badge variant="secondary">v{pt.version}</Badge>
                      {pt.is_active
                        ? <span style={{color: 'var(--color-success)', fontSize: '0.75rem'}}>●</span>
                        : <span style={{color: 'var(--color-text-secondary)', fontSize: '0.75rem'}}>○</span>
                      }
                    </span>
                    <div className="settings__llm-card-actions">
                      <Button variant="secondary" size="sm" onClick={() => previewPrompt(pt.name)}>预览</Button>
                      {expandedPrompt === pt.id ? (
                        <Button variant="secondary" size="sm" onClick={() => setExpandedPrompt(null)}>收起</Button>
                      ) : (
                        <Button variant="secondary" size="sm" onClick={() => setExpandedPrompt(pt.id)}>展开</Button>
                      )}
                    </div>
                  </div>
                  <div className="settings__llm-card-meta">
                    <span>{pt.category}</span>
                    <span>{pt.description}</span>
                  </div>
                  {expandedPrompt === pt.id && (
                    <div style={{marginTop: '0.5rem'}}>
                      {editingPromptId === pt.id ? (
                        <>
                          <textarea className="settings__input settings__textarea"
                            value={promptEditText}
                            onChange={e => setPromptEditText(e.target.value)}
                            rows={10} />
                          <div style={{marginTop: '0.5rem', display: 'flex', gap: '0.5rem'}}>
                            <Button size="sm" onClick={() => savePromptEdit(pt.id)}>保存</Button>
                            <Button variant="secondary" size="sm" onClick={() => setEditingPromptId(null)}>取消</Button>
                          </div>
                        </>
                      ) : (
                        <>
                          <pre className="settings__prompt-template">
                            {pt.template}
                          </pre>
                          <div style={{marginTop: '0.5rem'}}>
                            <Button variant="secondary" size="sm" onClick={() => { setEditingPromptId(pt.id); setPromptEditText(pt.template); }}>
                              编辑
                            </Button>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
            {showPromptPreviewModal && promptPreview && (
              <div className="settings__modal-overlay" onClick={() => setShowPromptPreviewModal(false)}>
                <div className="settings__modal settings__modal--wide" onClick={e => e.stopPropagation()}>
                  <h3 className="settings__modal-title">Preview: {promptPreview.name}</h3>
                  <pre className="settings__tool-result-json">{promptPreview.rendered}</pre>
                  <div className="settings__modal-actions">
                    <Button variant="secondary" onClick={() => setShowPromptPreviewModal(false)}>关闭</Button>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
```

- [ ] **Step 4: Add Prompt CSS**

Append to `Settings.css`:

```css
/* Prompt Template Display */
.settings__prompt-template {
  padding: 0.75rem;
  margin: 0;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  color: var(--color-text);
  background: var(--color-background);
  border-radius: var(--radius-md);
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/Settings.tsx frontend/apps/web/src/pages/Settings.css
git commit -m "feat(settings): add Prompt Templates Card"
```

---

## Phase 3B: Agent Config Management UI

### Task 11: Frontend — Agent Config Card

**Files:**
- Modify: `frontend/apps/web/src/pages/Settings.tsx`

The backend already has `GET /agent/configs`, `PUT /agent/configs/{id}`, `GET /agent/pipelines`, `PUT /agent/pipelines/{id}` from `agent_router.py`. This task adds only the frontend Card.

- [ ] **Step 1: Add Agent Config state variables**

```tsx
  // Agent Config
  const [agentConfigs, setAgentConfigs] = useState<any[]>([]);
  const [agentPipelines, setAgentPipelines] = useState<any[]>([]);
  const [agentLoading, setAgentLoading] = useState(false);
  const [showAgentModal, setShowAgentModal] = useState(false);
  const [editingAgent, setEditingAgent] = useState<any>(null);
  const [agentForm, setAgentForm] = useState({
    display_name: '', description: '', system_prompt: '',
    output_schema: '{}', llm_config_id: '', extra_params: '{}', is_active: true,
  });
  const [showPipelineModal, setShowPipelineModal] = useState(false);
  const [editingPipeline, setEditingPipeline] = useState<any>(null);
  const [pipelineForm, setPipelineForm] = useState({graph_config: '{}', is_active: true});
```

- [ ] **Step 2: Add Agent Config functions**

```tsx
  // ── Agent Config ───────────────────────────────────────────────────
  const fetchAgentData = useCallback(() => {
    setAgentLoading(true);
    Promise.all([
      fetch(`${getStoredApiBase()}/agent/configs`).then(r => r.json()),
      fetch(`${getStoredApiBase()}/agent/pipelines`).then(r => r.json()),
    ]).then(([cfgJson, pipeJson]) => {
      if (cfgJson.code === 0) setAgentConfigs(cfgJson.data);
      if (pipeJson.code === 0) setAgentPipelines(pipeJson.data);
    }).catch(() => {}).finally(() => setAgentLoading(false));
  }, []);

  const saveAgentConfig = async () => {
    const payload: any = {...agentForm};
    try { payload.output_schema = JSON.parse(payload.output_schema); } catch { payload.output_schema = {}; }
    try { payload.extra_params = JSON.parse(payload.extra_params); } catch { payload.extra_params = {}; }
    await fetch(`${getStoredApiBase()}/agent/configs/${editingAgent.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    setShowAgentModal(false);
    fetchAgentData();
  };

  const savePipelineConfig = async () => {
    const payload: any = {is_active: pipelineForm.is_active};
    try { payload.graph_config = JSON.parse(pipelineForm.graph_config); } catch { payload.graph_config = {}; }
    await fetch(`${getStoredApiBase()}/agent/pipelines/${editingPipeline.id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    setShowPipelineModal(false);
    fetchAgentData();
  };

  const openAgentModal = (config: any) => {
    setEditingAgent(config);
    setAgentForm({
      display_name: config.display_name || '',
      description: config.description || '',
      system_prompt: config.system_prompt || '',
      output_schema: JSON.stringify(config.output_schema || {}, null, 2),
      llm_config_id: config.llm_config_id || '',
      extra_params: JSON.stringify(config.extra_params || {}, null, 2),
      is_active: config.is_active ?? true,
    });
    setShowAgentModal(true);
  };

  const openPipelineModal = (pipeline: any) => {
    setEditingPipeline(pipeline);
    setPipelineForm({
      graph_config: JSON.stringify(pipeline.graph_config || {}, null, 2),
      is_active: pipeline.is_active ?? true,
    });
    setShowPipelineModal(true);
  };

  useEffect(() => { fetchAgentData(); }, [fetchAgentData]);
```

- [ ] **Step 3: Add Agent Config Card JSX**

```tsx
        {/* ── Agent Config ── */}
        <Card>
          <CardHeader>
            <CardTitle>🤖 Agent Config</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__llm-list">
              {agentConfigs.length === 0 && !agentLoading && (
                <div className="settings__llm-empty">暂无 Agent 配置</div>
              )}
              {agentConfigs.map(ac => (
                <div key={ac.id} className="settings__llm-card">
                  <div className="settings__llm-card-header">
                    <span className="settings__llm-card-name">
                      {ac.display_name || ac.name}
                      <Badge variant="secondary">{ac.agent_type}</Badge>
                    </span>
                    <div className="settings__llm-card-actions">
                      <Button variant="secondary" size="sm" onClick={() => openAgentModal(ac)}>编辑</Button>
                    </div>
                  </div>
                  <div className="settings__llm-card-meta">
                    <span>{ac.description}</span>
                    {ac.is_active
                      ? <span style={{color: 'var(--color-success)'}}>● Active</span>
                      : <span style={{color: 'var(--color-text-secondary)'}}>○ Inactive</span>
                    }
                  </div>
                </div>
              ))}
            </div>

            <h4 style={{marginTop: '1rem', marginBottom: '0.5rem', color: 'var(--color-text)'}}>Pipelines</h4>
            <div className="settings__llm-list">
              {agentPipelines.map(ap => (
                <div key={ap.id} className="settings__llm-card">
                  <div className="settings__llm-card-header">
                    <span className="settings__llm-card-name">
                      {ap.display_name || ap.name}
                    </span>
                    <div className="settings__llm-card-actions">
                      <Button variant="secondary" size="sm" onClick={() => openPipelineModal(ap)}>编辑</Button>
                    </div>
                  </div>
                  <div className="settings__llm-card-meta">
                    <span>节点: {Array.isArray(ap.graph_config?.nodes) ? ap.graph_config.nodes.length : 0}</span>
                    {ap.is_active
                      ? <span style={{color: 'var(--color-success)'}}>● Active</span>
                      : <span style={{color: 'var(--color-text-secondary)'}}>○ Inactive</span>
                    }
                  </div>
                </div>
              ))}
            </div>

            {showAgentModal && editingAgent && (
              <div className="settings__modal-overlay" onClick={() => setShowAgentModal(false)}>
                <div className="settings__modal settings__modal--wide" onClick={e => e.stopPropagation()}>
                  <h3 className="settings__modal-title">编辑 Agent: {editingAgent.name}</h3>
                  <div className="settings__field">
                    <label className="settings__label">显示名称</label>
                    <input className="settings__input" value={agentForm.display_name}
                      onChange={e => setAgentForm({...agentForm, display_name: e.target.value})} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">描述</label>
                    <input className="settings__input" value={agentForm.description}
                      onChange={e => setAgentForm({...agentForm, description: e.target.value})} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">System Prompt</label>
                    <textarea className="settings__input settings__textarea"
                      value={agentForm.system_prompt}
                      onChange={e => setAgentForm({...agentForm, system_prompt: e.target.value})}
                      rows={6} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">LLM Config</label>
                    <select className="settings__input" value={agentForm.llm_config_id}
                      onChange={e => setAgentForm({...agentForm, llm_config_id: e.target.value})}>
                      <option value="">默认</option>
                      {llmConfigs.map(lc => (
                        <option key={lc.id} value={lc.id}>{lc.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">Extra Params (JSON)</label>
                    <textarea className="settings__input settings__textarea"
                      value={agentForm.extra_params}
                      onChange={e => setAgentForm({...agentForm, extra_params: e.target.value})}
                      rows={3} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">
                      <input type="checkbox" checked={agentForm.is_active}
                        onChange={e => setAgentForm({...agentForm, is_active: e.target.checked})} />
                      {' '}启用
                    </label>
                  </div>
                  <div className="settings__modal-actions">
                    <Button onClick={saveAgentConfig}>保存</Button>
                    <Button variant="secondary" onClick={() => setShowAgentModal(false)}>取消</Button>
                  </div>
                </div>
              </div>
            )}

            {showPipelineModal && editingPipeline && (
              <div className="settings__modal-overlay" onClick={() => setShowPipelineModal(false)}>
                <div className="settings__modal settings__modal--wide" onClick={e => e.stopPropagation()}>
                  <h3 className="settings__modal-title">编辑 Pipeline: {editingPipeline.name}</h3>
                  <div className="settings__field">
                    <label className="settings__label">Graph Config (JSON)</label>
                    <textarea className="settings__input settings__textarea"
                      value={pipelineForm.graph_config}
                      onChange={e => setPipelineForm({...pipelineForm, graph_config: e.target.value})}
                      rows={12} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">
                      <input type="checkbox" checked={pipelineForm.is_active}
                        onChange={e => setPipelineForm({...pipelineForm, is_active: e.target.checked})} />
                      {' '}启用
                    </label>
                  </div>
                  <div className="settings__modal-actions">
                    <Button onClick={savePipelineConfig}>保存</Button>
                    <Button variant="secondary" onClick={() => setShowPipelineModal(false)}>取消</Button>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/pages/Settings.tsx
git commit -m "feat(settings): add Agent Config Card with pipeline editing"
```

---

## Phase 3C: Skill Workflow Definition

### Task 12: Skill API Models

**Files:**
- Create: `backend/src/api/model/skill_api_model.py`

- [ ] **Step 1: Create the Pydantic models**

```python
"""Request/response models for Skill definition API."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class SkillCreate(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    output_schema: dict[str, Any] = {}
    is_active: bool = True


class SkillUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    steps: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | None = None
    is_active: bool | None = None


class SkillResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    steps: list[dict[str, Any]]
    output_schema: dict[str, Any]
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None


class SkillExecuteRequest(BaseModel):
    input_params: dict[str, Any] = {}


class SkillExecuteResponse(BaseModel):
    success: bool
    outputs: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    duration_ms: float = 0.0


class SkillValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = []
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/api/model/skill_api_model.py
git commit -m "feat(skill): add Skill API request/response models"
```

---

### Task 13: Skill Entity (SQLModel Table)

**Files:**
- Create: `backend/src/infra/database/skill/__init__.py`
- Create: `backend/src/infra/database/skill/entity.py`

- [ ] **Step 1: Create `__init__.py`**

```python
"""Skill database module."""
```

- [ ] **Step 2: Create the SQLModel table**

```python
"""Skill definition SQLModel table definition."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field


class SkillDefinitionTable(SQLModel, table=True):
    __tablename__ = "skill_definition"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=100)
    display_name: str = Field(default="", max_length=200)
    description: str = Field(default="", sa_column=Column(Text))
    input_schema: dict = Field(default={}, sa_column=Column(JSONB))
    steps: list = Field(default=[], sa_column=Column(JSONB))
    output_schema: dict = Field(default={}, sa_column=Column(JSONB))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/database/skill/
git commit -m "feat(skill): add SkillDefinitionTable SQLModel entity"
```

---

### Task 14: Skill Repository (DB CRUD)

**Files:**
- Create: `backend/src/infra/database/skill/repository.py`

- [ ] **Step 1: Create the repository**

```python
"""Skill definition repository — CRUD operations for SkillDefinitionTable."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlmodel import select

from src.infra.database.skill.entity import SkillDefinitionTable
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn


# ── Singleton DB connection ────────────────────────────────────────────

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    """Thread-safe singleton DB connection."""
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def _row_to_dict(row: SkillDefinitionTable) -> dict:
    """Convert a DB row to a response dict."""
    return {
        "id": row.id,
        "name": row.name,
        "display_name": row.display_name,
        "description": row.description,
        "input_schema": row.input_schema or {},
        "steps": row.steps or [],
        "output_schema": row.output_schema or {},
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class SkillRepository:
    """Skill definition repository."""

    def __init__(self, db_connection: DBConnection | None = None):
        self._db = db_connection or _get_db_connection()

    def list_skills(self) -> list[dict]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(SkillDefinitionTable).order_by(SkillDefinitionTable.id)
            ).all()
            return [_row_to_dict(r) for r in rows]

    def get_skill(self, skill_id: int) -> dict | None:
        with self._db.session_scope() as session:
            row = session.get(SkillDefinitionTable, skill_id)
            if row is None:
                return None
            return _row_to_dict(row)

    def create_skill(self, data: dict) -> dict:
        row = SkillDefinitionTable(
            name=data["name"],
            display_name=data.get("display_name", ""),
            description=data.get("description", ""),
            input_schema=data.get("input_schema", {}),
            steps=data.get("steps", []),
            output_schema=data.get("output_schema", {}),
            is_active=data.get("is_active", True),
        )
        with self._db.session_scope() as session:
            session.add(row)
            session.flush()
            session.refresh(row)
            result = _row_to_dict(row)
        return result

    def update_skill(
        self, skill_id: int, updates: dict,
    ) -> dict | None:
        with self._db.session_scope() as session:
            row = session.get(SkillDefinitionTable, skill_id)
            if row is None:
                return None
            for key, value in updates.items():
                if value is not None:
                    setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            session.refresh(row)
            result = _row_to_dict(row)
        return result

    def delete_skill(self, skill_id: int) -> bool:
        with self._db.session_scope() as session:
            row = session.get(SkillDefinitionTable, skill_id)
            if row is None:
                return False
            session.delete(row)
        return True


# ── Factory ────────────────────────────────────────────────────────────

def create_skill_repository(
    db_connection: DBConnection | None = None,
) -> SkillRepository:
    """Factory function for SkillRepository."""
    return SkillRepository(db_connection)
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/infra/database/skill/repository.py
git commit -m "feat(skill): add Skill repository with CRUD operations"
```

---

### Task 15: Skill Executor

**Files:**
- Create: `backend/src/domain/market/intel/agents/skill_executor.py`

- [ ] **Step 1: Create the skill execution engine**

```python
"""Skill executor — runs a sequence of steps (prompt / mcp_tool / llm_call).

Each step is a dict with a ``type`` field and Jinja2-templated arguments
that can reference ``{{ input.xxx }}`` and ``{{ steps.yyy }}``.
"""
from __future__ import annotations

import time
from typing import Any

from jinja2 import Template
from loguru import logger

from src.infra.database.skill.repository import create_skill_repository
from src.infra.database.mcp.repository import create_mcp_repository
from src.infra.mcp.client import McpClient, McpServerConfig


async def execute_skill(
    skill_id: int, input_params: dict[str, Any],
) -> dict[str, Any]:
    """Execute a skill by ID with the given input parameters.

    Returns a dict with:
        success: bool
        outputs: dict[str, Any]  — keyed by output_key of each step
        errors: list[dict]       — {step_index, output_key, error}
        duration_ms: float
    """
    start = time.monotonic()

    repo = create_skill_repository()
    skill = repo.get_skill(skill_id)
    if skill is None:
        return {
            "success": False,
            "outputs": {},
            "errors": [{"step_index": -1, "output_key": "", "error": f"Skill {skill_id} not found"}],
            "duration_ms": (time.monotonic() - start) * 1000,
        }

    steps = skill.get("steps", [])
    context: dict[str, Any] = {"input": input_params, "steps": {}}
    outputs: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []

    for i, step in enumerate(steps):
        step_type = step.get("type", "")
        output_key = step.get("output_key", f"step_{i}")
        on_error = step.get("on_error", "skip")

        try:
            result = await _execute_step(step, context)
            context["steps"][output_key] = result
            outputs[output_key] = result
            logger.info(
                f"[SkillExecutor] Step {i} ({step_type}) → "
                f"{output_key}: OK"
            )
        except Exception as e:
            logger.warning(
                f"[SkillExecutor] Step {i} ({step_type}) → "
                f"{output_key}: ERROR: {e}"
            )
            errors.append({
                "step_index": i,
                "output_key": output_key,
                "error": str(e),
            })
            if on_error == "fail":
                break
            context["steps"][output_key] = None
            outputs[output_key] = None

    elapsed = (time.monotonic() - start) * 1000
    return {
        "success": len(errors) == 0,
        "outputs": outputs,
        "errors": errors,
        "duration_ms": round(elapsed, 1),
    }


async def _execute_step(
    step: dict, context: dict[str, Any],
) -> Any:
    """Execute a single step and return its result."""
    step_type = step["type"]

    if step_type == "prompt":
        return await _execute_prompt_step(step, context)
    elif step_type == "mcp_tool":
        return await _execute_mcp_tool_step(step, context)
    elif step_type == "llm_call":
        return await _execute_llm_call_step(step, context)
    else:
        raise ValueError(f"Unknown step type: {step_type}")


async def _execute_prompt_step(
    step: dict, context: dict[str, Any],
) -> str:
    """Render a prompt template with Jinja2."""
    from src.infra.database.agent.repository import create_agent_repository

    template_id = step.get("template_id")
    if template_id is None:
        raise ValueError("prompt step requires template_id")

    agent_repo = create_agent_repository()
    template_obj = agent_repo.get_prompt_template(template_id)
    if template_obj is None:
        raise ValueError(f"Template {template_id} not found")

    variables = _render_dict(step.get("variables", {}), context)
    merged_vars = {**(template_obj.variables or {}), **variables}

    from jinja2 import Template as JinjaTemplate
    rendered = JinjaTemplate(template_obj.template).render(**merged_vars)
    return rendered


async def _execute_mcp_tool_step(
    step: dict, context: dict[str, Any],
) -> Any:
    """Call an MCP tool."""
    server_id = step.get("server_id")
    tool_name = step.get("tool_name")
    if server_id is None or not tool_name:
        raise ValueError("mcp_tool step requires server_id and tool_name")

    mcp_repo = create_mcp_repository()
    server = mcp_repo.get_server(server_id)
    if server is None:
        raise ValueError(f"MCP server {server_id} not found")

    config = McpServerConfig(
        transport_type=server["transport_type"],
        command=server.get("command", ""),
        url=server.get("url", ""),
        headers=server.get("headers") or {},
        env_vars=server.get("env_vars") or {},
    )

    args = _render_dict(step.get("args", {}), context)

    async with McpClient(config) as client:
        result = await client.call_tool(tool_name, args)
    return result


async def _execute_llm_call_step(
    step: dict, context: dict[str, Any],
) -> str:
    """Call an LLM with rendered prompts."""
    from src.infra.database.llm.repository import create_llm_repository
    from src.infra.llm.manager import LLMManager

    llm_repo = create_llm_repository()
    manager = LLMManager(llm_repo)

    config_id = step.get("config_id")
    system_prompt = _render_value(step.get("system_prompt", ""), context)
    user_prompt = _render_value(step.get("user_prompt", ""), context)

    if config_id:
        config = llm_repo.get_decrypted_config(config_id)
        if config is None:
            raise ValueError(f"LLM config {config_id} not found")

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    result = await manager.chat(messages, config_id=config_id)
    return result


def _render_dict(
    data: dict, context: dict[str, Any],
) -> dict[str, Any]:
    """Render Jinja2 templates in dict values."""
    rendered: dict[str, Any] = {}
    for key, value in data.items():
        rendered[key] = _render_value(value, context)
    return rendered


def _render_value(value: Any, context: dict[str, Any]) -> Any:
    """Render a single value if it contains Jinja2 template syntax."""
    if isinstance(value, str) and "{{" in value:
        return Template(value).render(**context)
    return value
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/domain/market/intel/agents/skill_executor.py
git commit -m "feat(skill): add Skill executor engine with prompt/mcp_tool/llm_call steps"
```

---

### Task 16: Skill Router (API Endpoints)

**Files:**
- Create: `backend/src/api/router/skill_router.py`

- [ ] **Step 1: Create the Skill router**

```python
"""Skill definition management and execution API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.api.model.skill_api_model import (
    SkillCreate,
    SkillUpdate,
    SkillResponse,
    SkillExecuteRequest,
    SkillExecuteResponse,
    SkillValidateResponse,
)
from src.infra.database.skill.repository import create_skill_repository
from src.domain.market.intel.agents.skill_executor import execute_skill


router = APIRouter(prefix="/skills", tags=["skills"])

_repo = create_skill_repository()


def _ok(data) -> dict:
    return {"code": 0, "msg": "ok", "data": data}


def _to_response(row: dict) -> SkillResponse:
    return SkillResponse(**row)


# ── Skill CRUD ─────────────────────────────────────────────────────────

@router.get("")
def list_skills():
    """List all skill definitions."""
    skills = _repo.list_skills()
    return _ok([_to_response(s) for s in skills])


@router.post("", status_code=201)
def create_skill(body: SkillCreate):
    """Create a new skill definition."""
    data = body.model_dump()
    created = _repo.create_skill(data)
    return _ok(_to_response(created))


@router.put("/{skill_id}")
def update_skill(skill_id: int, body: SkillUpdate):
    """Update an existing skill definition."""
    updates = body.model_dump(exclude_none=True)
    updated = _repo.update_skill(skill_id, updates)
    if updated is None:
        raise HTTPException(404, "Skill not found")
    return _ok(_to_response(updated))


@router.delete("/{skill_id}")
def delete_skill(skill_id: int):
    """Delete a skill definition."""
    deleted = _repo.delete_skill(skill_id)
    if not deleted:
        raise HTTPException(404, "Skill not found")
    return _ok({"deleted": True})


# ── Skill Execution ────────────────────────────────────────────────────

@router.post("/{skill_id}/execute")
async def execute_skill_endpoint(skill_id: int, body: SkillExecuteRequest):
    """Execute a skill with the given input parameters."""
    skill = _repo.get_skill(skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found")

    result = await execute_skill(skill_id, body.input_params)
    return _ok(SkillExecuteResponse(**result))


@router.post("/{skill_id}/validate")
def validate_skill(skill_id: int):
    """Validate a skill's steps (check referenced IDs exist)."""
    skill = _repo.get_skill(skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found")

    errors: list[str] = []
    steps = skill.get("steps", [])

    # Check template_id references
    from src.infra.database.agent.repository import create_agent_repository
    agent_repo = create_agent_repository()
    template_ids = {
        s.get("template_id") for s in steps if s.get("type") == "prompt"
    }
    for tid in template_ids:
        if tid and agent_repo.get_prompt_template(tid) is None:
            errors.append(f"Template {tid} not found")

    # Check server_id references
    from src.infra.database.mcp.repository import create_mcp_repository
    mcp_repo = create_mcp_repository()
    server_ids = {
        s.get("server_id") for s in steps if s.get("type") == "mcp_tool"
    }
    for sid in server_ids:
        if sid and mcp_repo.get_server(sid) is None:
            errors.append(f"MCP server {sid} not found")

    # Check config_id references
    from src.infra.database.llm.repository import create_llm_repository
    llm_repo = create_llm_repository()
    config_ids = {
        s.get("config_id") for s in steps if s.get("type") == "llm_call"
    }
    for cid in config_ids:
        if cid and llm_repo.get_config(cid) is None:
            errors.append(f"LLM config {cid} not found")

    return _ok(SkillValidateResponse(
        valid=len(errors) == 0,
        errors=errors,
    ))
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/api/router/skill_router.py
git commit -m "feat(skill): add Skill router with CRUD + execute + validate endpoints"
```

---

### Task 17: Register Skill Router in main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add import**

After the `mcp_router` import line added in Task 6, add:

```python
from src.api.router.skill_router import router as skill_router
```

- [ ] **Step 2: Add router registration**

After the `mcp_router` registration line added in Task 6, add:

```python
    app.include_router(skill_router, prefix="/api/v1")  # /api/v1/skills
```

- [ ] **Step 3: Verify backend starts**

```bash
cd backend && python main.py &
sleep 3 && curl -s http://localhost:12100/api/v1/skills | python -m json.tool
# Expected: {"code": 0, "msg": "ok", "data": []}
kill %1
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(skill): register Skill router in main.py"
```

---

### Task 18: Frontend — Skill Definitions Card

**Files:**
- Modify: `frontend/apps/web/src/pages/Settings.tsx`
- Modify: `frontend/apps/web/src/pages/Settings.css`

- [ ] **Step 1: Add Skill state variables**

```tsx
  // Skill Definitions
  const [skills, setSkills] = useState<any[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [showSkillModal, setShowSkillModal] = useState(false);
  const [editingSkill, setEditingSkill] = useState<any>(null);
  const [skillForm, setSkillForm] = useState({
    name: '', display_name: '', description: '',
    input_schema: '{}', steps: '[]', output_schema: '{}', is_active: true,
  });
  const [skillStepsMode, setSkillStepsMode] = useState<'form' | 'json'>('json');
  const [showSkillExecModal, setShowSkillExecModal] = useState(false);
  const [skillExecInput, setSkillExecInput] = useState('{}');
  const [skillExecResult, setSkillExecResult] = useState<any>(null);
  const [skillExecRunning, setSkillExecRunning] = useState(false);
```

- [ ] **Step 2: Add Skill CRUD functions**

```tsx
  // ── Skill Definitions ──────────────────────────────────────────────
  const fetchSkills = useCallback(() => {
    setSkillsLoading(true);
    fetch(`${getStoredApiBase()}/skills`)
      .then(r => r.json())
      .then(j => { if (j.code === 0) setSkills(j.data); })
      .catch(() => {})
      .finally(() => setSkillsLoading(false));
  }, []);

  const saveSkill = async () => {
    const payload: any = {...skillForm};
    try { payload.input_schema = JSON.parse(payload.input_schema); } catch { payload.input_schema = {}; }
    try { payload.steps = JSON.parse(payload.steps); } catch { payload.steps = []; }
    try { payload.output_schema = JSON.parse(payload.output_schema); } catch { payload.output_schema = {}; }
    const url = editingSkill
      ? `${getStoredApiBase()}/skills/${editingSkill.id}`
      : `${getStoredApiBase()}/skills`;
    const res = await fetch(url, {
      method: editingSkill ? 'PUT' : 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const j = await res.json();
    if (j.code === 0 || j.code === 201) {
      setShowSkillModal(false);
      setEditingSkill(null);
      fetchSkills();
    }
  };

  const deleteSkill = async (id: number) => {
    if (!confirm('确定删除此 Skill？')) return;
    await fetch(`${getStoredApiBase()}/skills/${id}`, {method: 'DELETE'});
    fetchSkills();
  };

  const executeSkillTest = async (id: number) => {
    setSkillExecRunning(true);
    setSkillExecResult(null);
    let params: any = {};
    try { params = JSON.parse(skillExecInput); } catch {}
    try {
      const res = await fetch(`${getStoredApiBase()}/skills/${id}/execute`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({input_params: params}),
      });
      const j = await res.json();
      if (j.code === 0) setSkillExecResult(j.data);
    } catch (e: any) {
      setSkillExecResult({success: false, errors: [{error: e.message}]});
    } finally {
      setSkillExecRunning(false);
    }
  };

  const openSkillModal = (skill?: any) => {
    if (skill) {
      setEditingSkill(skill);
      setSkillForm({
        name: skill.name,
        display_name: skill.display_name || '',
        description: skill.description || '',
        input_schema: JSON.stringify(skill.input_schema || {}, null, 2),
        steps: JSON.stringify(skill.steps || [], null, 2),
        output_schema: JSON.stringify(skill.output_schema || {}, null, 2),
        is_active: skill.is_active ?? true,
      });
    } else {
      setEditingSkill(null);
      setSkillForm({
        name: '', display_name: '', description: '',
        input_schema: '{}', steps: '[]', output_schema: '{}', is_active: true,
      });
    }
    setSkillStepsMode('json');
    setShowSkillModal(true);
  };

  const openSkillExecModal = (skill: any) => {
    setEditingSkill(skill);
    setSkillExecInput(JSON.stringify(skill.input_schema?.properties
      ? Object.fromEntries(Object.keys(skill.input_schema.properties).map(k => [k, '']))
      : {}, null, 2));
    setSkillExecResult(null);
    setShowSkillExecModal(true);
  };

  useEffect(() => { fetchSkills(); }, [fetchSkills]);
```

- [ ] **Step 3: Add Skill Definitions Card JSX**

```tsx
        {/* ── Skill Definitions ── */}
        <Card>
          <CardHeader>
            <CardTitle>⚡ Skill Definitions</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__llm-toolbar">
              <Button size="sm" onClick={() => openSkillModal()}>+ 新建 Skill</Button>
            </div>
            <div className="settings__llm-list">
              {skills.length === 0 && !skillsLoading && (
                <div className="settings__llm-empty">暂无 Skill 定义</div>
              )}
              {skills.map(sk => (
                <div key={sk.id} className="settings__llm-card">
                  <div className="settings__llm-card-header">
                    <span className="settings__llm-card-name">
                      {sk.display_name || sk.name}
                      <Badge variant="secondary">{(sk.steps || []).length} steps</Badge>
                      {sk.is_active
                        ? <span style={{color: 'var(--color-success)', fontSize: '0.75rem'}}>● Active</span>
                        : <span style={{color: 'var(--color-text-secondary)', fontSize: '0.75rem'}}>○ Inactive</span>
                      }
                    </span>
                    <div className="settings__llm-card-actions">
                      <Button variant="secondary" size="sm" onClick={() => openSkillExecModal(sk)}>执行</Button>
                      <Button variant="secondary" size="sm" onClick={() => openSkillModal(sk)}>编辑</Button>
                      <Button variant="secondary" size="sm" onClick={() => deleteSkill(sk.id)}>删除</Button>
                    </div>
                  </div>
                  <div className="settings__llm-card-meta">
                    <span>{sk.description}</span>
                  </div>
                </div>
              ))}
            </div>

            {showSkillModal && (
              <div className="settings__modal-overlay" onClick={() => setShowSkillModal(false)}>
                <div className="settings__modal settings__modal--wide" onClick={e => e.stopPropagation()}>
                  <h3 className="settings__modal-title">{editingSkill ? '编辑 Skill' : '新建 Skill'}</h3>
                  <div className="settings__field">
                    <label className="settings__label">名称 (唯一标识)</label>
                    <input className="settings__input" value={skillForm.name}
                      onChange={e => setSkillForm({...skillForm, name: e.target.value})} placeholder="web_article_reader" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">显示名称</label>
                    <input className="settings__input" value={skillForm.display_name}
                      onChange={e => setSkillForm({...skillForm, display_name: e.target.value})} placeholder="Web Article Reader" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">描述</label>
                    <input className="settings__input" value={skillForm.description}
                      onChange={e => setSkillForm({...skillForm, description: e.target.value})} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">Input Schema (JSON)</label>
                    <textarea className="settings__input settings__textarea"
                      value={skillForm.input_schema}
                      onChange={e => setSkillForm({...skillForm, input_schema: e.target.value})} rows={4} />
                  </div>
                  <div className="settings__field">
                    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem'}}>
                      <label className="settings__label" style={{marginBottom: 0}}>Steps</label>
                      <div style={{display: 'flex', gap: '0.25rem'}}>
                        <button className={`settings__theme-btn ${skillStepsMode === 'json' ? 'settings__theme-btn--active' : ''}`}
                          style={{padding: '0.25rem 0.5rem', fontSize: '0.75rem'}}
                          onClick={() => setSkillStepsMode('json')}>JSON</button>
                        <button className={`settings__theme-btn ${skillStepsMode === 'form' ? 'settings__theme-btn--active' : ''}`}
                          style={{padding: '0.25rem 0.5rem', fontSize: '0.75rem'}}
                          onClick={() => setSkillStepsMode('form')}>Form</button>
                      </div>
                    </div>
                    {skillStepsMode === 'json' ? (
                      <textarea className="settings__input settings__textarea"
                        value={skillForm.steps}
                        onChange={e => setSkillForm({...skillForm, steps: e.target.value})} rows={12} />
                    ) : (
                      <div className="settings__skill-steps-form">
                        {(() => {
                          let steps: any[] = [];
                          try { steps = JSON.parse(skillForm.steps); } catch {}
                          return steps.map((step, i) => (
                            <div key={i} className="settings__skill-step-card">
                              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                                <span style={{fontWeight: 600, fontSize: '0.8125rem'}}>Step {i + 1}: {step.type}</span>
                                <span style={{fontSize: '0.75rem', color: 'var(--color-text-secondary)'}}>
                                  → {step.output_key}
                                </span>
                              </div>
                            </div>
                          ));
                        })()}
                        <span className="settings__hint">
                          切换到 JSON 模式编辑步骤详情
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">Output Schema (JSON)</label>
                    <textarea className="settings__input settings__textarea"
                      value={skillForm.output_schema}
                      onChange={e => setSkillForm({...skillForm, output_schema: e.target.value})} rows={3} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">
                      <input type="checkbox" checked={skillForm.is_active}
                        onChange={e => setSkillForm({...skillForm, is_active: e.target.checked})} />
                      {' '}启用
                    </label>
                  </div>
                  <div className="settings__modal-actions">
                    <Button onClick={saveSkill}>保存</Button>
                    <Button variant="secondary" onClick={() => setShowSkillModal(false)}>取消</Button>
                  </div>
                </div>
              </div>
            )}

            {showSkillExecModal && editingSkill && (
              <div className="settings__modal-overlay" onClick={() => setShowSkillExecModal(false)}>
                <div className="settings__modal settings__modal--wide" onClick={e => e.stopPropagation()}>
                  <h3 className="settings__modal-title">执行 Skill: {editingSkill.display_name || editingSkill.name}</h3>
                  <div className="settings__field">
                    <label className="settings__label">Input Parameters (JSON)</label>
                    <textarea className="settings__input settings__textarea"
                      value={skillExecInput}
                      onChange={e => setSkillExecInput(e.target.value)} rows={6} />
                  </div>
                  <Button onClick={() => executeSkillTest(editingSkill.id)} disabled={skillExecRunning}>
                    {skillExecRunning ? '执行中...' : '▶ 执行'}
                  </Button>
                  {skillExecResult && (
                    <div className="settings__tool-result" style={{marginTop: '0.75rem'}}>
                      <div className="settings__tool-result-header">
                        <span>{skillExecResult.success ? '✓ Success' : '✗ Failed'}</span>
                        <span className="settings__hint">{skillExecResult.duration_ms}ms</span>
                      </div>
                      {skillExecResult.errors?.length > 0 && (
                        <div style={{padding: '0.5rem 0.75rem'}}>
                          {skillExecResult.errors.map((e: any, i: number) => (
                            <div key={i} className="settings__test-msg settings__test-msg--error">
                              Step {e.step_index} ({e.output_key}): {e.error}
                            </div>
                          ))}
                        </div>
                      )}
                      <pre className="settings__tool-result-json">
                        {JSON.stringify(skillExecResult.outputs, null, 2)}
                      </pre>
                    </div>
                  )}
                  <div className="settings__modal-actions">
                    <Button variant="secondary" onClick={() => setShowSkillExecModal(false)}>关闭</Button>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
```

- [ ] **Step 4: Add Skill CSS**

Append to `Settings.css`:

```css
/* Skill Steps Form */
.settings__skill-steps-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.settings__skill-step-card {
  padding: 0.5rem 0.75rem;
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}
```

- [ ] **Step 5: Verify frontend compiles**

```bash
cd frontend && pnpm --filter web build 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/pages/Settings.tsx frontend/apps/web/src/pages/Settings.css
git commit -m "feat(skill): add Skill Definitions Card with create/edit/execute"
```

---

## Post-Implementation Verification

After all tasks are complete, run these end-to-end checks:

### Backend

```bash
cd backend && python main.py &
sleep 3

# MCP Server CRUD
curl -s -X POST http://localhost:12100/api/v1/mcp/servers \
  -H 'Content-Type: application/json' \
  -d '{"name":"test_server","transport_type":"sse","url":"http://localhost:3001/sse"}' | python -m json.tool

curl -s http://localhost:12100/api/v1/mcp/servers | python -m json.tool

# Skill CRUD
curl -s -X POST http://localhost:12100/api/v1/skills \
  -H 'Content-Type: application/json' \
  -d '{"name":"test_skill","steps":[{"type":"llm_call","user_prompt":"hello","output_key":"greeting"}]}' | python -m json.tool

curl -s http://localhost:12100/api/v1/skills | python -m json.tool

kill %1
```

### Frontend

```bash
cd frontend && pnpm --filter web build
# Should complete with no errors
```

### Manual UI Test

1. Open Settings page in browser
2. Verify all 11 Cards render (6 existing + 5 new — Prompt Templates, Agent Config, MCP Servers, MCP Tool Console, Skill Definitions)
3. MCP Servers: Add a server → Test connection → Expand tools list
4. MCP Tool Console: Select server → Select tool → Fill args → Execute
5. Prompt Templates: Expand template → Edit → Preview
6. Agent Config: Expand agent → Edit → Save
7. Skill Definitions: Create skill → Edit steps → Execute test
