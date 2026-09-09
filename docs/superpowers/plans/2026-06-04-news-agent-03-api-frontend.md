# News Agent Deep Analysis — Plan 3: API, Scheduler & Frontend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the agent system via REST API, integrate with the scheduler for auto-trigger, and add frontend pages for managing agents, celebrities, and prompts.

**Architecture:** FastAPI routers following existing `llm_config_router.py` pattern. Frontend pages in `pages/` with `.tsx` + `.css` pairs. Scheduler job registered in `scheduler.py`.

**Tech Stack:** FastAPI, React, APScheduler

**Depends on:** Plan 1 (Foundation) + Plan 2 (Agent Core) must be fully implemented.
**Required by:** Nothing (this is the final plan)

---

## File Structure

```
backend/
├── src/
│   ├── api/
│   │   ├── router/
│   │   │   ├── agent_router.py              # CREATE — agent config + execution API
│   │   │   ├── celebrity_router.py           # CREATE — celebrity CRUD API
│   │   │   └── prompt_router.py              # CREATE — prompt template CRUD API
│   │   └── model/
│   │       └── agent_api_model.py            # CREATE — request/response Pydantic models
│   └── infra/
│       └── scheduler.py                      # MODIFY — add agent analysis job
├── main.py                                   # MODIFY — register 3 new routers

frontend/apps/web/src/
├── pages/
│   ├── AgentConfig.tsx                       # CREATE — agent/pipeline/prompt management
│   ├── AgentConfig.css                       # CREATE
│   ├── Celebrity.tsx                         # CREATE — celebrity knowledge base management
│   └── Celebrity.css                         # CREATE
├── App.tsx                                   # MODIFY — add 2 routes
└── components/Layout.tsx                     # MODIFY — add 2 nav items
```

---

### Task 1: Create API Request/Response Models

**Files:**
- Create: `backend/src/api/model/agent_api_model.py`

- [ ] **Step 1: Create Pydantic models for all agent-related API requests/responses**

```python
# backend/src/api/model/agent_api_model.py
"""Pydantic request/response models for agent API endpoints."""
from pydantic import BaseModel, Field
from typing import Optional


# ── Agent Config ──

class AgentConfigUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    llm_config_id: Optional[str] = None
    extra_params: Optional[dict] = None
    is_active: Optional[bool] = None


class AgentConfigResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    agent_type: str
    system_prompt: str
    output_schema: dict
    llm_config_id: Optional[str]
    extra_params: dict
    is_active: bool


# ── Pipeline ──

class PipelineUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    graph_config: Optional[dict] = None
    debate_max_rounds: Optional[int] = None
    is_active: Optional[bool] = None


class PipelineResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    graph_config: dict
    debate_max_rounds: int
    is_active: bool


# ── Prompt Template ──

class PromptTemplateUpdateRequest(BaseModel):
    description: Optional[str] = None
    template: Optional[str] = None
    variables: Optional[dict] = None
    is_active: Optional[bool] = None


class PromptTemplateResponse(BaseModel):
    id: int
    name: str
    description: str
    template: str
    variables: dict
    category: str
    version: int
    is_active: bool


# ── Celebrity ──

class CelebrityCreateRequest(BaseModel):
    name: str
    display_name: str
    domain: str = Field(description="tech/finance/science/politics/other")
    title: str = ""
    bio: str = ""
    viewpoints: str = ""
    analysis_style: str = ""
    avatar_url: str = ""
    sort_order: int = 0


class CelebrityUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    domain: Optional[str] = None
    title: Optional[str] = None
    bio: Optional[str] = None
    viewpoints: Optional[str] = None
    analysis_style: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class CelebrityResponse(BaseModel):
    id: int
    name: str
    display_name: str
    domain: str
    title: str
    bio: str
    viewpoints: str
    analysis_style: str
    avatar_url: str
    is_active: bool
    sort_order: int


# ── Analysis ──

class AnalysisResponse(BaseModel):
    news_id: int
    deep_analysis: Optional[dict] = None


class BatchAnalysisRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)
```

- [ ] **Step 2: Verify import**

Run: `cd backend && uv run python -c "from src.api.model.agent_api_model import *; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/api/model/agent_api_model.py
git commit -m "feat(agents): add API request/response models"
```

---

### Task 2: Create Agent Config & Execution Router

**Files:**
- Create: `backend/src/api/router/agent_router.py`

- [ ] **Step 1: Create the router**

```python
# backend/src/api/router/agent_router.py
"""Agent configuration, pipeline, and execution API."""
from fastapi import APIRouter, HTTPException
from loguru import logger

from src.api.model.agent_api_model import (
    AgentConfigUpdateRequest,
    AgentConfigResponse,
    PipelineUpdateRequest,
    PipelineResponse,
    AnalysisResponse,
    BatchAnalysisRequest,
)
from src.infra.database.impl.agent_db import create_agent_repository


router = APIRouter(prefix="/agent", tags=["agent"])
_repo = create_agent_repository()


def _ok(data) -> dict:
    return {"code": 0, "msg": "ok", "data": data}


# ── Agent Config ──

@router.get("/configs")
def list_configs():
    configs = _repo.list_agent_configs()
    return _ok([{
        "id": c.id,
        "name": c.name,
        "display_name": c.display_name,
        "description": c.description,
        "agent_type": c.agent_type,
        "system_prompt": c.system_prompt,
        "output_schema": c.output_schema,
        "llm_config_id": c.llm_config_id,
        "extra_params": c.extra_params,
        "is_active": c.is_active,
    } for c in configs])


@router.get("/configs/{config_id}")
def get_config(config_id: int):
    c = _repo.get_agent_config(config_id)
    if not c:
        raise HTTPException(404, "Agent config not found")
    return _ok({
        "id": c.id,
        "name": c.name,
        "display_name": c.display_name,
        "description": c.description,
        "agent_type": c.agent_type,
        "system_prompt": c.system_prompt,
        "output_schema": c.output_schema,
        "llm_config_id": c.llm_config_id,
        "extra_params": c.extra_params,
        "is_active": c.is_active,
    })


@router.put("/configs/{config_id}")
def update_config(config_id: int, req: AgentConfigUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    c = _repo.update_agent_config(config_id, updates)
    if not c:
        raise HTTPException(404, "Agent config not found")
    return _ok({"id": c.id, "name": c.name, "updated": True})


# ── Pipeline ──

@router.get("/pipelines")
def list_pipelines():
    pipelines = _repo.list_pipelines()
    return _ok([{
        "id": p.id,
        "name": p.name,
        "display_name": p.display_name,
        "description": p.description,
        "graph_config": p.graph_config,
        "debate_max_rounds": p.debate_max_rounds,
        "is_active": p.is_active,
    } for p in pipelines])


@router.put("/pipelines/{pipeline_id}")
def update_pipeline(pipeline_id: int, req: PipelineUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    p = _repo.update_pipeline(pipeline_id, updates)
    if not p:
        raise HTTPException(404, "Pipeline not found")
    return _ok({"id": p.id, "name": p.name, "updated": True})


# ── Analysis Execution ──

@router.post("/analyze/{news_id}")
async def analyze_news(news_id: int):
    """Trigger deep analysis for a single news item."""
    from src.domain.market.intel.agents.graph import run_analysis
    try:
        result = await run_analysis(news_id)
        return _ok({
            "news_id": news_id,
            "final_report": result.get("final_report"),
            "errors": result.get("errors", []),
        })
    except Exception as e:
        logger.error(f"[agent_router] Analysis failed for news_id={news_id}: {e}")
        raise HTTPException(500, f"Analysis failed: {e}")


@router.post("/analyze/batch")
async def batch_analyze(req: BatchAnalysisRequest):
    """Trigger analysis for news items without deep_analysis."""
    from src.domain.market.intel.agents.graph import run_analysis
    news_list = _repo.find_news_without_analysis(limit=req.limit)
    results = []
    for news in news_list:
        try:
            await run_analysis(news["id"])
            results.append({"news_id": news["id"], "status": "ok"})
        except Exception as e:
            results.append({"news_id": news["id"], "status": "error", "error": str(e)})
    return _ok({"processed": results})


@router.get("/analysis/{news_id}")
def get_analysis(news_id: int):
    """Get deep analysis result for a news item."""
    analysis = _repo.get_deep_analysis(news_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    return _ok(analysis)
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/api/router/agent_router.py
git commit -m "feat(agents): add agent config and execution API router"
```

---

### Task 3: Create Celebrity Router

**Files:**
- Create: `backend/src/api/router/celebrity_router.py`

- [ ] **Step 1: Create the router**

```python
# backend/src/api/router/celebrity_router.py
"""Celebrity knowledge base CRUD API."""
from fastapi import APIRouter, HTTPException

from src.api.model.agent_api_model import (
    CelebrityCreateRequest,
    CelebrityUpdateRequest,
    CelebrityResponse,
)
from src.domain.market.intel.agents.models import Celebrity
from src.infra.database.impl.agent_db import create_agent_repository


router = APIRouter(prefix="/celebrities", tags=["celebrities"])
_repo = create_agent_repository()


def _ok(data) -> dict:
    return {"code": 0, "msg": "ok", "data": data}


def _celebrity_to_dict(c: Celebrity) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "display_name": c.display_name,
        "domain": c.domain,
        "title": c.title,
        "bio": c.bio,
        "viewpoints": c.viewpoints,
        "analysis_style": c.analysis_style,
        "avatar_url": c.avatar_url,
        "is_active": c.is_active,
        "sort_order": c.sort_order,
    }


@router.get("")
def list_celebrities(active_only: bool = False):
    celebs = _repo.list_celebrities(active_only=active_only)
    return _ok([_celebrity_to_dict(c) for c in celebs])


@router.post("", status_code=201)
def create_celebrity(req: CelebrityCreateRequest):
    celebrity = Celebrity(
        name=req.name,
        display_name=req.display_name,
        domain=req.domain,
        title=req.title,
        bio=req.bio,
        viewpoints=req.viewpoints,
        analysis_style=req.analysis_style,
        avatar_url=req.avatar_url,
        sort_order=req.sort_order,
    )
    created = _repo.create_celebrity(celebrity)
    return _ok(_celebrity_to_dict(created))


@router.put("/{celebrity_id}")
def update_celebrity(celebrity_id: int, req: CelebrityUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    c = _repo.update_celebrity(celebrity_id, updates)
    if not c:
        raise HTTPException(404, "Celebrity not found")
    return _ok(_celebrity_to_dict(c))


@router.delete("/{celebrity_id}")
def delete_celebrity(celebrity_id: int):
    ok = _repo.delete_celebrity(celebrity_id)
    if not ok:
        raise HTTPException(404, "Celebrity not found")
    return _ok({"deleted": True})


@router.patch("/{celebrity_id}/toggle")
def toggle_celebrity(celebrity_id: int):
    c = _repo.get_celebrity(celebrity_id)
    if not c:
        raise HTTPException(404, "Celebrity not found")
    updated = _repo.update_celebrity(celebrity_id, {
        "is_active": not c.is_active,
    })
    return _ok(_celebrity_to_dict(updated))
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/api/router/celebrity_router.py
git commit -m "feat(agents): add celebrity CRUD API router"
```

---

### Task 4: Create Prompt Template Router

**Files:**
- Create: `backend/src/api/router/prompt_router.py`

- [ ] **Step 1: Create the router**

```python
# backend/src/api/router/prompt_router.py
"""Prompt template CRUD API."""
from fastapi import APIRouter, HTTPException
from jinja2 import Template

from src.api.model.agent_api_model import (
    PromptTemplateUpdateRequest,
    PromptTemplateResponse,
)
from src.infra.database.impl.agent_db import create_agent_repository


router = APIRouter(prefix="/prompts", tags=["prompts"])
_repo = create_agent_repository()


def _ok(data) -> dict:
    return {"code": 0, "msg": "ok", "data": data}


@router.get("")
def list_templates():
    templates = _repo.list_prompt_templates()
    return _ok([{
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "template": t.template,
        "variables": t.variables,
        "category": t.category,
        "version": t.version,
        "is_active": t.is_active,
    } for t in templates])


@router.put("/{template_id}")
def update_template(template_id: int, req: PromptTemplateUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    t = _repo.update_prompt_template(template_id, updates)
    if not t:
        raise HTTPException(404, "Template not found")
    return _ok({
        "id": t.id,
        "name": t.name,
        "version": t.version,
        "updated": True,
    })


@router.get("/{name}/render")
def render_template(name: str, variables: dict | None = None):
    """Preview a rendered template with sample variables."""
    t = _repo.get_prompt_template_by_name(name)
    if not t:
        raise HTTPException(404, f"Template '{name}' not found")
    try:
        rendered = Template(t.template).render(**(variables or t.variables))
        return _ok({"name": name, "rendered": rendered})
    except Exception as e:
        raise HTTPException(400, f"Render failed: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/api/router/prompt_router.py
git commit -m "feat(agents): add prompt template CRUD API router"
```

---

### Task 5: Register Routers in main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add imports**

At the top of `main.py`, in the router import block, add:

```python
from src.api.router.agent_router import router as agent_router
from src.api.router.celebrity_router import router as celebrity_router
from src.api.router.prompt_router import router as prompt_router
```

- [ ] **Step 2: Register in `create_app()`**

In the router registration section, add:

```python
    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(celebrity_router, prefix="/api/v1")
    app.include_router(prompt_router, prefix="/api/v1")
```

- [ ] **Step 3: Verify startup**

Run: `cd backend && uv run python -c "from main import create_app; app = create_app(); routes = [r.path for r in app.routes if hasattr(r, 'path')]; agent_routes = [r for r in routes if '/agent' in r or '/celebrit' in r or '/prompt' in r]; print(agent_routes)"`
Expected: Routes containing `/agent/`, `/celebrities`, `/prompts`.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(agents): register agent, celebrity, prompt routers in main.py"
```

---

### Task 6: Add Scheduler Job

**Files:**
- Modify: `backend/src/infra/scheduler.py`

- [ ] **Step 1: Add the agent analysis scheduled job**

In `setup_scheduler()`, after the existing intel collection jobs, add:

```python
    # Agent deep analysis — trigger 30 min after collection
    def _run_agent_analysis():
        import asyncio
        from src.domain.market.intel.agents.graph import run_analysis
        from src.infra.database.impl.agent_db import create_agent_repository
        repo = create_agent_repository()
        news_list = repo.find_news_without_analysis(limit=5)
        loop = asyncio.new_event_loop()
        for news in news_list:
            try:
                loop.run_until_complete(run_analysis(news["id"]))
            except Exception as e:
                logging.getLogger(__name__).error(
                    f"Agent analysis failed for news_id={news['id']}: {e}"
                )
        loop.close()

    sched.add_job(
        _run_agent_analysis,
        CronTrigger(minute="*/30", timezone="Asia/Shanghai"),
        id="intel_agent_analysis",
        name="资讯深度分析 (Agent)",
        replace_existing=True,
        misfire_grace_time=600,
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/infra/scheduler.py
git commit -m "feat(agents): add scheduled job for auto deep analysis every 30 min"
```

---

### Task 7: Frontend — AgentConfig Page

**Files:**
- Create: `frontend/apps/web/src/pages/AgentConfig.tsx`
- Create: `frontend/apps/web/src/pages/AgentConfig.css`

- [ ] **Step 1: Create `AgentConfig.tsx`**

```tsx
// frontend/apps/web/src/pages/AgentConfig.tsx
/**
 * AgentConfig — manage agents, pipelines, and prompt templates
 */
import React, {useState, useEffect, useCallback} from 'react';
import {getApiBase} from '../lib/api';
import './AgentConfig.css';

type Tab = 'agents' | 'pipeline' | 'prompts';

interface AgentConfig {
  id: number;
  name: string;
  display_name: string;
  description: string;
  agent_type: string;
  system_prompt: string;
  llm_config_id: string | null;
  extra_params: Record<string, unknown>;
  is_active: boolean;
}

interface PromptTemplate {
  id: number;
  name: string;
  description: string;
  template: string;
  variables: Record<string, string>;
  category: string;
  version: number;
  is_active: boolean;
}

interface Pipeline {
  id: number;
  name: string;
  display_name: string;
  description: string;
  graph_config: Record<string, unknown>;
  debate_max_rounds: number;
  is_active: boolean;
}

export const AgentConfig: React.FC = () => {
  const [tab, setTab] = useState<Tab>('agents');
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState('');
  const [loading, setLoading] = useState(false);

  const apiBase = getApiBase();

  const fetchAgents = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/agent/configs`);
      const json = await res.json();
      if (json.code === 0) setAgents(json.data);
    } catch {}
  }, [apiBase]);

  const fetchPrompts = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/prompts`);
      const json = await res.json();
      if (json.code === 0) setPrompts(json.data);
    } catch {}
  }, [apiBase]);

  const fetchPipelines = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/agent/pipelines`);
      const json = await res.json();
      if (json.code === 0) setPipelines(json.data);
    } catch {}
  }, [apiBase]);

  useEffect(() => {
    fetchAgents();
    fetchPrompts();
    fetchPipelines();
  }, [fetchAgents, fetchPrompts, fetchPipelines]);

  const saveAgentPrompt = async (id: number) => {
    await fetch(`${apiBase}/agent/configs/${id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({system_prompt: editValue}),
    });
    setEditingId(null);
    fetchAgents();
  };

  const savePromptTemplate = async (id: number) => {
    await fetch(`${apiBase}/prompts/${id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({template: editValue}),
    });
    setEditingId(null);
    fetchPrompts();
  };

  const savePipeline = async (id: number, field: string, value: unknown) => {
    await fetch(`${apiBase}/agent/pipelines/${id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({[field]: value}),
    });
    fetchPipelines();
  };

  const runAnalysis = async () => {
    setLoading(true);
    try {
      await fetch(`${apiBase}/agent/analyze/batch`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({limit: 5}),
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="agent-config">
      <div className="agent-config__header">
        <h2>Agent Configuration</h2>
        <button
          className="agent-config__run-btn"
          onClick={runAnalysis}
          disabled={loading}
        >
          {loading ? 'Running...' : 'Run Analysis'}
        </button>
      </div>

      <div className="agent-config__tabs">
        {(['agents', 'pipeline', 'prompts'] as Tab[]).map((t) => (
          <button
            key={t}
            className={`agent-config__tab ${tab === t ? 'agent-config__tab--active' : ''}`}
            onClick={() => setTab(t)}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'agents' && (
        <div className="agent-config__list">
          {agents.map((agent) => (
            <div key={agent.id} className="agent-config__card">
              <div className="agent-config__card-header">
                <span className="agent-config__card-name">{agent.display_name}</span>
                <span className="agent-config__card-type">{agent.agent_type}</span>
                <span className={`agent-config__card-status ${agent.is_active ? 'active' : 'inactive'}`}>
                  {agent.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <p className="agent-config__card-desc">{agent.description}</p>
              {editingId === agent.id ? (
                <div className="agent-config__editor">
                  <textarea
                    className="agent-config__textarea"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    rows={10}
                  />
                  <div className="agent-config__editor-actions">
                    <button onClick={() => saveAgentPrompt(agent.id)}>Save</button>
                    <button onClick={() => setEditingId(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <pre
                  className="agent-config__prompt-preview"
                  onClick={() => {
                    setEditingId(agent.id);
                    setEditValue(agent.system_prompt);
                  }}
                  title="Click to edit"
                >
                  {agent.system_prompt.slice(0, 200)}
                  {agent.system_prompt.length > 200 ? '...' : ''}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'pipeline' && (
        <div className="agent-config__list">
          {pipelines.map((p) => (
            <div key={p.id} className="agent-config__card">
              <div className="agent-config__card-header">
                <span className="agent-config__card-name">{p.display_name}</span>
                <span className={`agent-config__card-status ${p.is_active ? 'active' : 'inactive'}`}>
                  {p.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <p className="agent-config__card-desc">{p.description}</p>
              <div className="agent-config__pipeline-controls">
                <label>
                  Debate rounds:
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={p.debate_max_rounds}
                    onChange={(e) => savePipeline(p.id, 'debate_max_rounds', parseInt(e.target.value, 10))}
                  />
                </label>
              </div>
              <pre className="agent-config__graph-config">
                {JSON.stringify(p.graph_config, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}

      {tab === 'prompts' && (
        <div className="agent-config__list">
          {prompts.map((pt) => (
            <div key={pt.id} className="agent-config__card">
              <div className="agent-config__card-header">
                <span className="agent-config__card-name">{pt.name}</span>
                <span className="agent-config__card-version">v{pt.version}</span>
                <span className="agent-config__card-type">{pt.category}</span>
              </div>
              <p className="agent-config__card-desc">{pt.description}</p>
              {editingId === pt.id ? (
                <div className="agent-config__editor">
                  <textarea
                    className="agent-config__textarea"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    rows={12}
                  />
                  <div className="agent-config__editor-actions">
                    <button onClick={() => savePromptTemplate(pt.id)}>Save</button>
                    <button onClick={() => setEditingId(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <pre
                  className="agent-config__prompt-preview"
                  onClick={() => {
                    setEditingId(pt.id);
                    setEditValue(pt.template);
                  }}
                  title="Click to edit"
                >
                  {pt.template.slice(0, 200)}
                  {pt.template.length > 200 ? '...' : ''}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 2: Create `AgentConfig.css`**

```css
.agent-config {
  max-width: 900px;
}

.agent-config__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.agent-config__header h2 {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--color-text);
  margin: 0;
}

.agent-config__run-btn {
  padding: 8px 16px;
  background: var(--color-accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
}

.agent-config__run-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.agent-config__tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 0;
}

.agent-config__tab {
  padding: 8px 16px;
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.agent-config__tab--active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}

.agent-config__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-config__card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 16px;
}

.agent-config__card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.agent-config__card-name {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--color-text);
}

.agent-config__card-type {
  font-size: 0.6875rem;
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.agent-config__card-version {
  font-size: 0.6875rem;
  color: var(--color-accent);
  font-family: var(--font-mono);
}

.agent-config__card-status {
  font-size: 0.6875rem;
  margin-left: auto;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

.agent-config__card-status.active {
  color: var(--color-success);
  background: rgba(63, 185, 80, 0.1);
}

.agent-config__card-status.inactive {
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
}

.agent-config__card-desc {
  font-size: 0.8125rem;
  color: var(--color-text-secondary);
  margin: 0 0 10px;
}

.agent-config__prompt-preview {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  background: var(--color-background);
  padding: 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 100px;
  overflow: hidden;
  margin: 0;
}

.agent-config__prompt-preview:hover {
  background: var(--color-surface-hover);
}

.agent-config__editor {
  margin-top: 8px;
}

.agent-config__textarea {
  width: 100%;
  background: var(--color-background);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 10px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  line-height: 1.5;
  resize: vertical;
}

.agent-config__editor-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.agent-config__editor-actions button {
  padding: 6px 14px;
  border-radius: var(--radius-md);
  font-size: 0.8125rem;
  cursor: pointer;
}

.agent-config__editor-actions button:first-child {
  background: var(--color-accent);
  color: #fff;
  border: none;
}

.agent-config__editor-actions button:last-child {
  background: none;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.agent-config__pipeline-controls label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8125rem;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
}

.agent-config__pipeline-controls input {
  width: 60px;
  padding: 4px 8px;
  background: var(--color-background);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 0.8125rem;
}

.agent-config__graph-config {
  font-size: 0.6875rem;
  color: var(--color-text-secondary);
  background: var(--color-background);
  padding: 8px;
  border-radius: var(--radius-md);
  overflow-x: auto;
  margin: 0;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/pages/AgentConfig.tsx frontend/apps/web/src/pages/AgentConfig.css
git commit -m "feat(agents): add AgentConfig frontend page (agents/pipeline/prompts tabs)"
```

---

### Task 8: Frontend — Celebrity Page

**Files:**
- Create: `frontend/apps/web/src/pages/Celebrity.tsx`
- Create: `frontend/apps/web/src/pages/Celebrity.css`

- [ ] **Step 1: Create `Celebrity.tsx`**

```tsx
// frontend/apps/web/src/pages/Celebrity.tsx
/**
 * Celebrity — manage the celebrity knowledge base
 */
import React, {useState, useEffect, useCallback} from 'react';
import {getApiBase} from '../lib/api';
import './Celebrity.css';

interface CelebrityItem {
  id: number;
  name: string;
  display_name: string;
  domain: string;
  title: string;
  bio: string;
  viewpoints: string;
  analysis_style: string;
  avatar_url: string;
  is_active: boolean;
  sort_order: number;
}

const EMPTY_FORM = {
  name: '',
  display_name: '',
  domain: 'tech',
  title: '',
  bio: '',
  viewpoints: '',
  analysis_style: '',
  avatar_url: '',
  sort_order: 0,
};

export const Celebrity: React.FC = () => {
  const [celebrities, setCelebrities] = useState<CelebrityItem[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);

  const apiBase = getApiBase();

  const fetchCelebrities = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/celebrities`);
      const json = await res.json();
      if (json.code === 0) setCelebrities(json.data);
    } catch {}
  }, [apiBase]);

  useEffect(() => {
    fetchCelebrities();
  }, [fetchCelebrities]);

  const handleCreate = async () => {
    await fetch(`${apiBase}/celebrities`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(form),
    });
    setShowForm(false);
    setForm(EMPTY_FORM);
    fetchCelebrities();
  };

  const handleToggle = async (id: number) => {
    await fetch(`${apiBase}/celebrities/${id}/toggle`, {method: 'PATCH'});
    fetchCelebrities();
  };

  const handleDelete = async (id: number) => {
    await fetch(`${apiBase}/celebrities/${id}`, {method: 'DELETE'});
    fetchCelebrities();
  };

  const domainColors: Record<string, string> = {
    tech: '#58a6ff',
    finance: '#3fb950',
    science: '#d29922',
    politics: '#f85149',
    other: '#8b949e',
  };

  return (
    <div className="celebrity">
      <div className="celebrity__header">
        <h2>Celebrity Knowledge Base</h2>
        <button
          className="celebrity__add-btn"
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? 'Cancel' : '+ Add Celebrity'}
        </button>
      </div>

      {showForm && (
        <div className="celebrity__form">
          <div className="celebrity__form-row">
            <input placeholder="Name (e.g. Elon Musk)" value={form.name} onChange={(e) => setForm({...form, name: e.target.value})} />
            <input placeholder="Display Name (e.g. 马斯克)" value={form.display_name} onChange={(e) => setForm({...form, display_name: e.target.value})} />
            <select value={form.domain} onChange={(e) => setForm({...form, domain: e.target.value})}>
              <option value="tech">Tech</option>
              <option value="finance">Finance</option>
              <option value="science">Science</option>
              <option value="politics">Politics</option>
              <option value="other">Other</option>
            </select>
          </div>
          <input placeholder="Title" value={form.title} onChange={(e) => setForm({...form, title: e.target.value})} />
          <textarea placeholder="Bio" value={form.bio} onChange={(e) => setForm({...form, bio: e.target.value})} rows={3} />
          <textarea placeholder="Core Viewpoints" value={form.viewpoints} onChange={(e) => setForm({...form, viewpoints: e.target.value})} rows={3} />
          <textarea placeholder="Analysis Style" value={form.analysis_style} onChange={(e) => setForm({...form, analysis_style: e.target.value})} rows={2} />
          <div className="celebrity__form-actions">
            <button onClick={handleCreate} disabled={!form.name || !form.display_name}>
              Create
            </button>
          </div>
        </div>
      )}

      <div className="celebrity__list">
        {celebrities.map((c) => (
          <div key={c.id} className={`celebrity__card ${!c.is_active ? 'celebrity__card--inactive' : ''}`}>
            <div className="celebrity__card-header">
              <div className="celebrity__card-avatar" style={{borderColor: domainColors[c.domain] || '#8b949e'}}>
                {c.display_name[0]}
              </div>
              <div className="celebrity__card-info">
                <span className="celebrity__card-name">{c.display_name}</span>
                <span className="celebrity__card-title">{c.title || c.name}</span>
              </div>
              <span className="celebrity__card-domain" style={{color: domainColors[c.domain] || '#8b949e'}}>
                {c.domain}
              </span>
            </div>
            <p className="celebrity__card-bio">{c.bio}</p>
            {c.viewpoints && (
              <p className="celebrity__card-viewpoints">{c.viewpoints}</p>
            )}
            <div className="celebrity__card-actions">
              <button onClick={() => handleToggle(c.id)}>
                {c.is_active ? 'Deactivate' : 'Activate'}
              </button>
              <button className="celebrity__card-delete" onClick={() => handleDelete(c.id)}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Create `Celebrity.css`**

```css
.celebrity {
  max-width: 900px;
}

.celebrity__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.celebrity__header h2 {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0;
}

.celebrity__add-btn {
  padding: 8px 16px;
  background: var(--color-accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: 0.8125rem;
  cursor: pointer;
}

.celebrity__form {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 16px;
  margin-bottom: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.celebrity__form-row {
  display: flex;
  gap: 10px;
}

.celebrity__form input,
.celebrity__form textarea,
.celebrity__form select {
  width: 100%;
  padding: 8px 10px;
  background: var(--color-background);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 0.8125rem;
  font-family: inherit;
}

.celebrity__form-actions button {
  padding: 8px 20px;
  background: var(--color-accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
}

.celebrity__form-actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.celebrity__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.celebrity__card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 16px;
}

.celebrity__card--inactive {
  opacity: 0.5;
}

.celebrity__card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.celebrity__card-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 2px solid;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  font-weight: 700;
  flex-shrink: 0;
}

.celebrity__card-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.celebrity__card-name {
  font-size: 0.9375rem;
  font-weight: 600;
}

.celebrity__card-title {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
}

.celebrity__card-domain {
  margin-left: auto;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.celebrity__card-bio {
  font-size: 0.8125rem;
  color: var(--color-text-secondary);
  margin: 0 0 6px;
}

.celebrity__card-viewpoints {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  background: var(--color-background);
  padding: 8px;
  border-radius: var(--radius-md);
  margin: 0 0 10px;
  white-space: pre-wrap;
}

.celebrity__card-actions {
  display: flex;
  gap: 8px;
}

.celebrity__card-actions button {
  padding: 4px 12px;
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  cursor: pointer;
  border: 1px solid var(--color-border);
  background: none;
  color: var(--color-text-secondary);
}

.celebrity__card-delete {
  color: var(--color-danger) !important;
  border-color: var(--color-danger) !important;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/pages/Celebrity.tsx frontend/apps/web/src/pages/Celebrity.css
git commit -m "feat(agents): add Celebrity management frontend page"
```

---

### Task 9: Register Frontend Routes + Nav

**Files:**
- Modify: `frontend/apps/web/src/App.tsx`
- Modify: `frontend/apps/web/src/components/Layout.tsx`

- [ ] **Step 1: Add imports in `App.tsx`**

Add to the existing imports:

```tsx
import {AgentConfig} from './pages/AgentConfig';
import {Celebrity} from './pages/Celebrity';
```

Add routes inside `<Routes>`:

```tsx
<Route path="/agent-config" element={<AgentConfig />} />
<Route path="/celebrities" element={<Celebrity />} />
```

- [ ] **Step 2: Add nav items in `Layout.tsx`**

In the `navGroups` array, add to the **System** group's `items` array:

```tsx
  {path: '/agent-config', label: 'Agent Config', icon: Icon.copilot},
  {path: '/celebrities', label: 'Celebrities', icon: Icon.reports},
```

Place them before the Settings item.

- [ ] **Step 3: Verify in browser**

Navigate to `http://localhost:12000/agent-config` and `http://localhost:12000/celebrities`. Both pages should render.

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(agents): register AgentConfig and Celebrity routes and nav items"
```

---

### Task 10: End-to-End Smoke Test

- [ ] **Step 1: Start backend + frontend**

Run both servers (or use `dev-start.sh`).

- [ ] **Step 2: Verify API endpoints**

```bash
curl http://localhost:12100/api/v1/agent/configs | python -m json.tool
curl http://localhost:12100/api/v1/celebrities | python -m json.tool
curl http://localhost:12100/api/v1/prompts | python -m json.tool
curl http://localhost:12100/api/v1/agent/pipelines | python -m json.tool
```

Expected: All return `{"code": 0, "data": [...]}` with seeded data.

- [ ] **Step 3: Verify frontend pages load**

- `http://localhost:12000/agent-config` — should show agents, pipeline, prompts tabs
- `http://localhost:12000/celebrities` — should show 4 celebrity cards

- [ ] **Step 4: Test celebrity CRUD**

```bash
curl -X POST http://localhost:12100/api/v1/celebrities \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test Person","display_name":"测试","domain":"other","bio":"test"}'
```

Expected: `{"code": 0, "data": {...}}`

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix(agents): address smoke test issues"
```
