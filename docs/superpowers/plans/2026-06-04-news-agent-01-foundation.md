# News Agent Deep Analysis — Plan 1: Foundation & Data Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add all dependencies, domain models, DB tables, repository layer, LLM adapter, and seed data needed by the Agent system.

**Architecture:** DDD layered — domain models + repo interface in `domain/`, SQLModel tables + repo impl in `infra/database/impl/`, LLM bridge in `infra/llm/`. Follows existing intel/ module patterns exactly.

**Tech Stack:** langgraph, langchain-openai, langchain-core, jinja2, SQLModel, PostgreSQL JSONB

**Depends on:** Nothing (this is the first plan)
**Required by:** Plan 2 (Agent Core), Plan 3 (API & Frontend)

---

## File Structure

```
backend/
├── pyproject.toml                                    # MODIFY
├── src/
│   ├── domain/market/intel/agents/
│   │   ├── __init__.py                               # CREATE
│   │   ├── models.py                                 # CREATE — domain dataclasses
│   │   ├── schemas.py                                # CREATE — Pydantic LLM output schemas
│   │   ├── state.py                                  # CREATE — LangGraph TypedDict states
│   │   └── repository_interface.py                   # CREATE — IAgentRepository ABC
│   ├── infra/
│   │   ├── database/impl/
│   │   │   ├── agent_db.py                           # CREATE — tables + repo + seed
│   │   │   └── intel_db.py                           # MODIFY — add deep_analysis column
│   │   └── llm/
│   │       └── langchain_adapter.py                  # CREATE — ChatOpenAI bridge
│   └── data/ddl/
│       └── 001_add_deep_analysis.sql                 # CREATE — migration script
tests/
└── agents/
    ├── __init__.py                                   # CREATE
    └── conftest.py                                   # CREATE — shared fixtures
```

---

### Task 1: Add Dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add langgraph, langchain, jinja2 to dependencies**

In `backend/pyproject.toml`, append to the `dependencies` list (after `psycopg2-binary`):

```toml
    "langgraph>=0.4.0",
    "langchain-openai>=0.3.0",
    "langchain-core>=0.3.0",
    "jinja2>=3.1.0",
```

- [ ] **Step 2: Sync and verify**

Run: `cd backend && uv sync`
Expected: packages installed without errors.

- [ ] **Step 3: Verify import works**

Run: `cd backend && uv run python -c "import langgraph; import langchain_openai; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore: add langgraph, langchain-openai, jinja2 dependencies"
```

---

### Task 2: Create Domain Models

**Files:**
- Create: `backend/src/domain/market/intel/agents/__init__.py`
- Create: `backend/src/domain/market/intel/agents/models.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# backend/src/domain/market/intel/agents/__init__.py
```

(Empty file — marks directory as Python package.)

- [ ] **Step 2: Create `models.py` with all domain dataclasses**

```python
# backend/src/domain/market/intel/agents/models.py
"""Agent domain models — dataclasses for domain-layer data transfer."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class AgentConfig:
    """Agent definition, stored in agent_config table."""
    name: str
    display_name: str
    description: str
    agent_type: str  # single / persona / debate / synthesis
    system_prompt: str
    output_schema: dict = field(default_factory=dict)
    llm_config_id: Optional[str] = None
    extra_params: dict = field(default_factory=dict)
    is_active: bool = True
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Celebrity:
    """名人知识库, stored in celebrity table."""
    name: str
    display_name: str
    domain: str  # tech / finance / science / politics / other
    title: str
    bio: str
    viewpoints: str
    analysis_style: str
    avatar_url: str = ""
    is_active: bool = True
    sort_order: int = 0
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class PromptTemplate:
    """Prompt 模板, stored in prompt_template table."""
    name: str
    description: str
    template: str
    variables: dict = field(default_factory=dict)
    category: str = "system"  # system / user / debate
    version: int = 1
    is_active: bool = True
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class AgentPipeline:
    """Pipeline 编排配置, stored in agent_pipeline table."""
    name: str
    display_name: str
    description: str
    graph_config: dict = field(default_factory=dict)
    debate_max_rounds: int = 3
    is_active: bool = True
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

- [ ] **Step 3: Verify import**

Run: `cd backend && uv run python -c "from src.domain.market.intel.agents.models import AgentConfig, Celebrity, PromptTemplate, AgentPipeline; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/src/domain/market/intel/agents/
git commit -m "feat(agents): add domain models for agent config, celebrity, prompt, pipeline"
```

---

### Task 3: Create LangGraph State Definitions & Output Schemas

**Files:**
- Create: `backend/src/domain/market/intel/agents/state.py`
- Create: `backend/src/domain/market/intel/agents/schemas.py`

- [ ] **Step 1: Create `state.py`**

```python
# backend/src/domain/market/intel/agents/state.py
"""LangGraph State definitions for the news analysis pipeline."""
import operator
from typing import Annotated, Any, TypedDict


class NewsAnalysisState(TypedDict, total=False):
    """Main pipeline state — flows through all agent nodes."""
    # Input
    news_id: int
    news_title: str
    news_content: str
    news_category: str

    # TaggingAgent output
    tags: list[str]
    industry: str
    sentiment: float

    # CelebrityAgent output
    persona_analyses: Annotated[list[dict[str, Any]], operator.add]
    debate_history: list[dict[str, Any]]
    celebrity_consensus: dict[str, Any]

    # TrendAgent output
    related_events: list[dict[str, Any]]
    trend_analysis: dict[str, Any]

    # ReportAgent output
    final_report: dict[str, Any]

    # Meta
    errors: Annotated[list[str], operator.add]
    processing_steps: Annotated[list[str], operator.add]


class PersonaState(TypedDict, total=False):
    """State for a single celebrity persona analysis node."""
    news_title: str
    news_content: str
    celebrity: dict[str, Any]
    persona_analyses: Annotated[list[dict[str, Any]], operator.add]


class CelebritySubgraphState(TypedDict, total=False):
    """State for the CelebrityAgent subgraph (fan-out/fan-in/debate)."""
    news_title: str
    news_content: str
    celebrities: list[dict[str, Any]]
    persona_analyses: Annotated[list[dict[str, Any]], operator.add]
    debate_history: list[dict[str, Any]]
    debate_round: int
    celebrity_consensus: dict[str, Any]
    errors: Annotated[list[str], operator.add]
    processing_steps: Annotated[list[str], operator.add]
```

- [ ] **Step 2: Create `schemas.py` — Pydantic models for LLM structured output**

```python
# backend/src/domain/market/intel/agents/schemas.py
"""Pydantic schemas for LLM structured output parsing."""
from pydantic import BaseModel, Field


class TaggingResult(BaseModel):
    """TaggingAgent output schema."""
    tags: list[str] = Field(description="新闻主题标签, 3-8 个")
    industry: str = Field(description="主要行业分类")
    sentiment: float = Field(
        description="情感分数, -1.0(极度悲观) 到 1.0(极度乐观)",
        ge=-1.0,
        le=1.0,
    )
    confidence: float = Field(
        description="分析置信度, 0.0 到 1.0",
        ge=0.0,
        le=1.0,
    )


class PersonaAnalysisResult(BaseModel):
    """单个名人的分析结果."""
    celebrity_name: str = Field(description="名人英文名")
    perspective: str = Field(description="从该名人视角对新闻的观点, 100-300 字")
    key_insights: list[str] = Field(description="3-5 个关键洞察")
    investment_implication: str = Field(description="投资含义/建议")
    confidence: float = Field(ge=0.0, le=1.0, description="分析置信度")


class DebateResponse(BaseModel):
    """辩论中单个名人的回应."""
    celebrity_name: str = Field(description="名人英文名")
    agrees_with: list[str] = Field(description="同意的其他名人观点摘要")
    disagrees_with: list[str] = Field(description="不同意的观点及理由")
    rebuttal: str = Field(description="反驳或补充论述, 100-200 字")
    adjusted_view: str = Field(description="调整后的个人观点")


class SynthesisResult(BaseModel):
    """名人辩论综合结果."""
    consensus_points: list[str] = Field(description="共识要点")
    disagreements: list[str] = Field(description="分歧要点")
    overall_sentiment: str = Field(description="综合情感: bullish/bearish/neutral")
    key_takeaway: str = Field(description="一句话总结")


class TrendResult(BaseModel):
    """TrendAgent output schema."""
    related_events: list[dict[str, str]] = Field(
        description="关联的近期事件, 每个含 title/relevance/reason"
    )
    trend_direction: str = Field(
        description="趋势方向: rising/declining/stable/volatile"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    analysis: str = Field(description="趋势分析正文, 200-400 字")
    time_horizon: str = Field(description="影响时间跨度: short/medium/long")


class ReportResult(BaseModel):
    """ReportAgent output schema."""
    executive_summary: str = Field(description="执行摘要, 100-200 字")
    key_findings: list[str] = Field(description="5-8 个关键发现")
    celebrity_consensus_summary: str = Field(description="名人观点共识摘要")
    trend_outlook: str = Field(description="趋势展望")
    risk_factors: list[str] = Field(description="3-5 个风险因素")
    investment_recommendation: str = Field(description="投资建议")
    confidence_level: str = Field(description="high/medium/low")
```

- [ ] **Step 3: Verify imports**

Run: `cd backend && uv run python -c "from src.domain.market.intel.agents.state import NewsAnalysisState, PersonaState, CelebritySubgraphState; from src.domain.market.intel.agents.schemas import TaggingResult, ReportResult; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/src/domain/market/intel/agents/state.py backend/src/domain/market/intel/agents/schemas.py
git commit -m "feat(agents): add LangGraph state definitions and Pydantic output schemas"
```

---

### Task 4: Create Repository Interface

**Files:**
- Create: `backend/src/domain/market/intel/agents/repository_interface.py`

- [ ] **Step 1: Create the ABC**

```python
# backend/src/domain/market/intel/agents/repository_interface.py
"""Agent repository interface — domain layer contract."""
from abc import ABC, abstractmethod
from src.domain.market.intel.agents.models import (
    AgentConfig,
    AgentPipeline,
    Celebrity,
    PromptTemplate,
)


class IAgentRepository(ABC):
    """Agent 系统 CRUD 接口, 覆盖 agent_config/pipeline/template/celebrity 四张表."""

    # ── Agent Config ──
    @abstractmethod
    def list_agent_configs(self) -> list[AgentConfig]:
        ...

    @abstractmethod
    def get_agent_config(self, config_id: int) -> AgentConfig | None:
        ...

    @abstractmethod
    def get_agent_config_by_name(self, name: str) -> AgentConfig | None:
        ...

    @abstractmethod
    def update_agent_config(self, config_id: int, updates: dict) -> AgentConfig | None:
        ...

    # ── Pipeline ──
    @abstractmethod
    def list_pipelines(self) -> list[AgentPipeline]:
        ...

    @abstractmethod
    def get_pipeline(self, pipeline_id: int) -> AgentPipeline | None:
        ...

    @abstractmethod
    def get_active_pipeline(self) -> AgentPipeline | None:
        ...

    @abstractmethod
    def update_pipeline(self, pipeline_id: int, updates: dict) -> AgentPipeline | None:
        ...

    # ── Prompt Template ──
    @abstractmethod
    def list_prompt_templates(self) -> list[PromptTemplate]:
        ...

    @abstractmethod
    def get_prompt_template(self, template_id: int) -> PromptTemplate | None:
        ...

    @abstractmethod
    def get_prompt_template_by_name(self, name: str) -> PromptTemplate | None:
        ...

    @abstractmethod
    def update_prompt_template(
        self, template_id: int, updates: dict
    ) -> PromptTemplate | None:
        ...

    # ── Celebrity ──
    @abstractmethod
    def list_celebrities(self, active_only: bool = False) -> list[Celebrity]:
        ...

    @abstractmethod
    def get_celebrity(self, celebrity_id: int) -> Celebrity | None:
        ...

    @abstractmethod
    def create_celebrity(self, celebrity: Celebrity) -> Celebrity:
        ...

    @abstractmethod
    def update_celebrity(
        self, celebrity_id: int, updates: dict
    ) -> Celebrity | None:
        ...

    @abstractmethod
    def delete_celebrity(self, celebrity_id: int) -> bool:
        ...

    # ── Deep Analysis ──
    @abstractmethod
    def save_deep_analysis(self, news_id: int, analysis: dict) -> bool:
        ...

    @abstractmethod
    def get_deep_analysis(self, news_id: int) -> dict | None:
        ...

    @abstractmethod
    def find_news_without_analysis(self, limit: int = 10) -> list[dict]:
        ...
```

- [ ] **Step 2: Verify import**

Run: `cd backend && uv run python -c "from src.domain.market.intel.agents.repository_interface import IAgentRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/domain/market/intel/agents/repository_interface.py
git commit -m "feat(agents): add IAgentRepository interface for agent CRUD operations"
```

---

### Task 5: Create DB Tables + Repository Implementation

**Files:**
- Create: `backend/src/infra/database/impl/agent_db.py`

This is a large file — 4 SQLModel tables + 1 repository class + factory + seed data. All in one file following the existing `intel_db.py` pattern.

- [ ] **Step 1: Create `agent_db.py`**

```python
# backend/src/infra/database/impl/agent_db.py
"""Agent system SQLModel tables, repository implementation, and seed data."""
import json
import threading
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import Column, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field, select

from src.domain.market.intel.agents.models import (
    AgentConfig,
    AgentPipeline,
    Celebrity,
    PromptTemplate,
)
from src.domain.market.intel.agents.repository_interface import IAgentRepository
from src.infra.database.db_helper import DBConnection, create_db_connection


# ═══════════════════════════════════════════
# SQLModel Table Definitions
# ═══════════════════════════════════════════

class AgentConfigTable(SQLModel, table=True):
    __tablename__ = "agent_config"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    display_name: str
    description: str = Field(default="", sa_column=Column(Text))
    agent_type: str  # single / persona / debate / synthesis
    system_prompt: str = Field(sa_column=Column(Text))
    output_schema: dict = Field(default={}, sa_column=Column(JSONB))
    llm_config_id: Optional[str] = Field(
        default=None, foreign_key="llm_config.id"
    )
    extra_params: dict = Field(default={}, sa_column=Column(JSONB))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentPipelineTable(SQLModel, table=True):
    __tablename__ = "agent_pipeline"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    display_name: str
    description: str = Field(default="", sa_column=Column(Text))
    graph_config: dict = Field(default={}, sa_column=Column(JSONB))
    debate_max_rounds: int = Field(default=3)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PromptTemplateTable(SQLModel, table=True):
    __tablename__ = "prompt_template"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str = Field(default="", sa_column=Column(Text))
    template: str = Field(sa_column=Column(Text))
    variables: dict = Field(default={}, sa_column=Column(JSONB))
    category: str = Field(default="system")  # system / user / debate
    version: int = Field(default=1)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CelebrityTable(SQLModel, table=True):
    __tablename__ = "celebrity"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    display_name: str
    domain: str  # tech / finance / science / politics / other
    title: str = Field(default="")
    bio: str = Field(default="", sa_column=Column(Text))
    viewpoints: str = Field(default="", sa_column=Column(Text))
    analysis_style: str = Field(default="", sa_column=Column(Text))
    avatar_url: str = Field(default="")
    is_active: bool = Field(default=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════
# Row → Domain Model Helpers
# ═══════════════════════════════════════════

def _row_to_agent_config(row: AgentConfigTable) -> AgentConfig:
    return AgentConfig(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        agent_type=row.agent_type,
        system_prompt=row.system_prompt,
        output_schema=row.output_schema or {},
        llm_config_id=row.llm_config_id,
        extra_params=row.extra_params or {},
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_pipeline(row: AgentPipelineTable) -> AgentPipeline:
    return AgentPipeline(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        graph_config=row.graph_config or {},
        debate_max_rounds=row.debate_max_rounds,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_template(row: PromptTemplateTable) -> PromptTemplate:
    return PromptTemplate(
        id=row.id,
        name=row.name,
        description=row.description,
        template=row.template,
        variables=row.variables or {},
        category=row.category,
        version=row.version,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_celebrity(row: CelebrityTable) -> Celebrity:
    return Celebrity(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        domain=row.domain,
        title=row.title,
        bio=row.bio,
        viewpoints=row.viewpoints,
        analysis_style=row.analysis_style,
        avatar_url=row.avatar_url,
        is_active=row.is_active,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ═══════════════════════════════════════════
# Repository Implementation
# ═══════════════════════════════════════════

class AgentRepository(IAgentRepository):
    def __init__(self, db_connection: DBConnection) -> None:
        self._db = db_connection

    # ── Agent Config ──

    def list_agent_configs(self) -> list[AgentConfig]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(AgentConfigTable).order_by(AgentConfigTable.id)
            ).all()
            return [_row_to_agent_config(r) for r in rows]

    def get_agent_config(self, config_id: int) -> AgentConfig | None:
        with self._db.session_scope() as session:
            row = session.get(AgentConfigTable, config_id)
            return _row_to_agent_config(row) if row else None

    def get_agent_config_by_name(self, name: str) -> AgentConfig | None:
        with self._db.session_scope() as session:
            row = session.exec(
                select(AgentConfigTable).where(AgentConfigTable.name == name)
            ).first()
            return _row_to_agent_config(row) if row else None

    def update_agent_config(
        self, config_id: int, updates: dict
    ) -> AgentConfig | None:
        with self._db.session_scope() as session:
            row = session.get(AgentConfigTable, config_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_agent_config(row)

    # ── Pipeline ──

    def list_pipelines(self) -> list[AgentPipeline]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(AgentPipelineTable).order_by(AgentPipelineTable.id)
            ).all()
            return [_row_to_pipeline(r) for r in rows]

    def get_pipeline(self, pipeline_id: int) -> AgentPipeline | None:
        with self._db.session_scope() as session:
            row = session.get(AgentPipelineTable, pipeline_id)
            return _row_to_pipeline(row) if row else None

    def get_active_pipeline(self) -> AgentPipeline | None:
        with self._db.session_scope() as session:
            row = session.exec(
                select(AgentPipelineTable).where(
                    AgentPipelineTable.is_active == True  # noqa: E712
                )
            ).first()
            return _row_to_pipeline(row) if row else None

    def update_pipeline(
        self, pipeline_id: int, updates: dict
    ) -> AgentPipeline | None:
        with self._db.session_scope() as session:
            row = session.get(AgentPipelineTable, pipeline_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_pipeline(row)

    # ── Prompt Template ──

    def list_prompt_templates(self) -> list[PromptTemplate]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(PromptTemplateTable).order_by(PromptTemplateTable.id)
            ).all()
            return [_row_to_template(r) for r in rows]

    def get_prompt_template(self, template_id: int) -> PromptTemplate | None:
        with self._db.session_scope() as session:
            row = session.get(PromptTemplateTable, template_id)
            return _row_to_template(row) if row else None

    def get_prompt_template_by_name(self, name: str) -> PromptTemplate | None:
        with self._db.session_scope() as session:
            row = session.exec(
                select(PromptTemplateTable).where(
                    PromptTemplateTable.name == name
                )
            ).first()
            return _row_to_template(row) if row else None

    def update_prompt_template(
        self, template_id: int, updates: dict
    ) -> PromptTemplate | None:
        with self._db.session_scope() as session:
            row = session.get(PromptTemplateTable, template_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key == "template":
                    row.version += 1
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_template(row)

    # ── Celebrity ──

    def list_celebrities(self, active_only: bool = False) -> list[Celebrity]:
        with self._db.session_scope() as session:
            stmt = select(CelebrityTable).order_by(CelebrityTable.sort_order)
            if active_only:
                stmt = stmt.where(CelebrityTable.is_active == True)  # noqa: E712
            rows = session.exec(stmt).all()
            return [_row_to_celebrity(r) for r in rows]

    def get_celebrity(self, celebrity_id: int) -> Celebrity | None:
        with self._db.session_scope() as session:
            row = session.get(CelebrityTable, celebrity_id)
            return _row_to_celebrity(row) if row else None

    def create_celebrity(self, celebrity: Celebrity) -> Celebrity:
        with self._db.session_scope() as session:
            row = CelebrityTable(
                name=celebrity.name,
                display_name=celebrity.display_name,
                domain=celebrity.domain,
                title=celebrity.title,
                bio=celebrity.bio,
                viewpoints=celebrity.viewpoints,
                analysis_style=celebrity.analysis_style,
                avatar_url=celebrity.avatar_url,
                is_active=celebrity.is_active,
                sort_order=celebrity.sort_order,
            )
            session.add(row)
            session.flush()
            return _row_to_celebrity(row)

    def update_celebrity(
        self, celebrity_id: int, updates: dict
    ) -> Celebrity | None:
        with self._db.session_scope() as session:
            row = session.get(CelebrityTable, celebrity_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_celebrity(row)

    def delete_celebrity(self, celebrity_id: int) -> bool:
        with self._db.session_scope() as session:
            row = session.get(CelebrityTable, celebrity_id)
            if not row:
                return False
            session.delete(row)
            return True

    # ── Deep Analysis ──

    def save_deep_analysis(self, news_id: int, analysis: dict) -> bool:
        with self._db.session_scope() as session:
            session.execute(
                text(
                    "UPDATE intel_news SET deep_analysis = :analysis "
                    "WHERE id = :news_id"
                ),
                {"analysis": json.dumps(analysis, ensure_ascii=False), "news_id": news_id},
            )
            return True

    def get_deep_analysis(self, news_id: int) -> dict | None:
        with self._db.session_scope() as session:
            result = session.execute(
                text(
                    "SELECT deep_analysis FROM intel_news WHERE id = :news_id"
                ),
                {"news_id": news_id},
            ).first()
            if result and result[0]:
                return result[0] if isinstance(result[0], dict) else json.loads(result[0])
            return None

    def find_news_without_analysis(self, limit: int = 10) -> list[dict]:
        with self._db.session_scope() as session:
            rows = session.execute(
                text(
                    "SELECT id, title, content, category FROM intel_news "
                    "WHERE deep_analysis IS NULL AND processed = true "
                    "ORDER BY published_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
            return [
                {"id": r[0], "title": r[1], "content": r[2], "category": r[3]}
                for r in rows
            ]


# ═══════════════════════════════════════════
# Singleton + Factory
# ═══════════════════════════════════════════

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection()
    return _db_connection


def create_agent_repository(
    db_connection: DBConnection | None = None,
) -> AgentRepository:
    return AgentRepository(db_connection or _get_db_connection())


# ═══════════════════════════════════════════
# Migration: add deep_analysis column to intel_news
# ═══════════════════════════════════════════

def migrate_add_deep_analysis_column() -> None:
    """Add deep_analysis JSONB column to intel_news if not exists."""
    db = _get_db_connection()
    with db.session_scope() as session:
        session.execute(text(
            "ALTER TABLE intel_news "
            "ADD COLUMN IF NOT EXISTS deep_analysis JSONB"
        ))
    logger.info("[agent_db] Migration: deep_analysis column ensured")


# ═══════════════════════════════════════════
# Seed Data
# ═══════════════════════════════════════════

def seed_agent_data() -> None:
    """Insert default agent configs, pipeline, prompt templates, celebrities."""
    db = _get_db_connection()
    with db.session_scope() as session:
        # Only seed if empty
        existing = session.exec(
            select(AgentConfigTable)
        ).first()
        if existing:
            return

        logger.info("[agent_db] Seeding default agent data...")

        # ── Agent Configs ──
        configs = [
            AgentConfigTable(
                name="tagging",
                display_name="Tagging Agent",
                description="为新闻打标签：主题、行业、情感分析",
                agent_type="single",
                system_prompt="tagging_system",
                extra_params={"temperature": 0.2},
            ),
            AgentConfigTable(
                name="celebrity",
                display_name="Celebrity Agent",
                description="多名人视角分析 + 辩论 + 综合",
                agent_type="persona",
                system_prompt="celebrity_persona_system",
                extra_params={"temperature": 0.7},
            ),
            AgentConfigTable(
                name="trend",
                display_name="Trend Agent",
                description="事件关联与趋势分析",
                agent_type="single",
                system_prompt="trend_system",
                extra_params={"temperature": 0.3},
            ),
            AgentConfigTable(
                name="report",
                display_name="Report Agent",
                description="综合报告生成",
                agent_type="synthesis",
                system_prompt="report_system",
                extra_params={"temperature": 0.4},
            ),
        ]
        for c in configs:
            session.add(c)

        # ── Pipeline ──
        pipeline = AgentPipelineTable(
            name="default",
            display_name="Default News Analysis Pipeline",
            description="Tagging → Celebrity Debate → Trend → Report",
            graph_config={
                "nodes": [
                    {"id": "tagging", "agent_config_name": "tagging"},
                    {"id": "celebrity", "agent_config_name": "celebrity", "subgraph": True},
                    {"id": "trend", "agent_config_name": "trend"},
                    {"id": "report", "agent_config_name": "report"},
                ],
                "edges": [
                    {"from": "START", "to": "tagging"},
                    {"from": "tagging", "to": "celebrity"},
                    {"from": "celebrity", "to": "trend"},
                    {"from": "trend", "to": "report"},
                    {"from": "report", "to": "END"},
                ],
            },
            debate_max_rounds=2,
        )
        session.add(pipeline)

        # ── Prompt Templates ──
        templates = [
            PromptTemplateTable(
                name="tagging_system",
                description="TaggingAgent 系统提示词",
                template=(
                    "你是一名专业的金融新闻分析师。你的任务是为新闻文章打标签。\n"
                    "分析新闻的标题和正文，输出以下结构化信息：\n"
                    "- tags: 3-8 个主题标签（中文+英文混合，如 \"AI\", \"半导体\", \"美联储\"）\n"
                    "- industry: 主要行业分类（Technology/Finance/Healthcare/Energy/"
                    "Consumer/Industrial/RealEstate/Telecom/Utilities/Other）\n"
                    "- sentiment: 情感分数 -1.0 到 1.0\n"
                    "- confidence: 分析置信度 0.0 到 1.0\n\n"
                    "注意：\n"
                    "- 标签应具体而非笼统\n"
                    "- 情感分数反映对市场的潜在影响方向\n"
                    "- 如果新闻内容不足以判断，confidence 应较低"
                ),
                variables={"news_title": "str", "news_content": "str"},
                category="system",
            ),
            PromptTemplateTable(
                name="celebrity_persona_system",
                description="名人视角分析系统提示词",
                template=(
                    "你现在要以 {{ display_name }} ({{ name }}) 的视角来分析一条新闻。\n\n"
                    "你的背景：\n"
                    "头衔: {{ title }}\n"
                    "简介: {{ bio }}\n"
                    "核心观点: {{ viewpoints }}\n"
                    "分析风格: {{ analysis_style }}\n\n"
                    "请从你的专业视角出发，对这条新闻进行分析：\n"
                    "- perspective: 你的观点（100-300字）\n"
                    "- key_insights: 3-5个关键洞察\n"
                    "- investment_implication: 投资含义\n"
                    "- confidence: 置信度\n\n"
                    "保持你独特的分析风格和思维模式。"
                ),
                variables={
                    "display_name": "str", "name": "str", "title": "str",
                    "bio": "str", "viewpoints": "str", "analysis_style": "str",
                    "news_title": "str", "news_content": "str",
                },
                category="system",
            ),
            PromptTemplateTable(
                name="debate_user",
                description="辩论轮次用户提示词",
                template=(
                    "以下是其他名人对同一新闻的观点：\n\n"
                    "{{ other_viewpoints }}\n\n"
                    "请以 {{ display_name }} 的身份回应：\n"
                    "1. 你同意哪些观点？为什么？\n"
                    "2. 你不同意哪些观点？给出你的理由。\n"
                    "3. 补充或修正你之前的分析。"
                ),
                variables={
                    "display_name": "str", "other_viewpoints": "str",
                    "news_title": "str", "news_content": "str",
                },
                category="debate",
            ),
            PromptTemplateTable(
                name="synthesis_system",
                description="名人观点综合提示词",
                template=(
                    "你是一名中立的金融分析主持人。以下是多名投资界名人对同一新闻的辩论记录：\n\n"
                    "{{ debate_history }}\n\n"
                    "请综合以上讨论，输出：\n"
                    "- consensus_points: 所有人都同意的要点\n"
                    "- disagreements: 主要分歧点\n"
                    "- overall_sentiment: 综合情感 (bullish/bearish/neutral)\n"
                    "- key_takeaway: 一句话总结共识"
                ),
                variables={"debate_history": "str"},
                category="system",
            ),
            PromptTemplateTable(
                name="trend_system",
                description="TrendAgent 系统提示词",
                template=(
                    "你是一名专业的趋势分析师。基于以下新闻内容及其分析结果，进行事件关联和趋势分析。\n\n"
                    "新闻标签: {{ tags }}\n"
                    "行业: {{ industry }}\n"
                    "名人共识: {{ celebrity_consensus }}\n\n"
                    "请输出：\n"
                    "- related_events: 关联的近期事件（推断可能相关的宏观/行业事件）\n"
                    "- trend_direction: 趋势方向 (rising/declining/stable/volatile)\n"
                    "- confidence: 置信度\n"
                    "- analysis: 趋势分析正文（200-400字）\n"
                    "- time_horizon: 影响时间跨度 (short/medium/long)\n\n"
                    "注意基于已知信息进行推理，对不确定的部分标注低置信度。"
                ),
                variables={
                    "tags": "list", "industry": "str",
                    "celebrity_consensus": "dict",
                    "news_title": "str", "news_content": "str",
                },
                category="system",
            ),
            PromptTemplateTable(
                name="report_system",
                description="ReportAgent 系统提示词",
                template=(
                    "你是一名高级投资研究报告撰写人。请基于以下所有分析结果，撰写一份综合报告。\n\n"
                    "新闻: {{ news_title }}\n\n"
                    "标签与情感: {{ tags }}, sentiment={{ sentiment }}\n"
                    "名人观点综合: {{ celebrity_consensus }}\n"
                    "趋势分析: {{ trend_analysis }}\n\n"
                    "请输出结构化报告：\n"
                    "- executive_summary: 执行摘要（100-200字）\n"
                    "- key_findings: 5-8个关键发现\n"
                    "- celebrity_consensus_summary: 名人观点共识摘要\n"
                    "- trend_outlook: 趋势展望\n"
                    "- risk_factors: 3-5个风险因素\n"
                    "- investment_recommendation: 投资建议\n"
                    "- confidence_level: 整体置信度 (high/medium/low)\n\n"
                    "报告应客观、专业，突出不确定性。"
                ),
                variables={
                    "news_title": "str", "tags": "list", "sentiment": "float",
                    "celebrity_consensus": "dict", "trend_analysis": "dict",
                },
                category="system",
            ),
        ]
        for t in templates:
            session.add(t)

        # ── Celebrities ──
        celebrities = [
            CelebrityTable(
                name="Elon Musk",
                display_name="马斯克",
                domain="tech",
                title="Tesla / SpaceX / xAI CEO",
                bio="科技企业家，以大胆创新和跨界思维著称。涉足电动车、航天、AI、脑机接口等领域。",
                viewpoints=(
                    "1. AI 是人类面临的最大机遇和风险\n"
                    "2. 电动车和可持续能源是必然趋势\n"
                    "3. 人口崩溃比人口过剩是更大的威胁\n"
                    "4. 多行星物种是人类长期生存的关键"
                ),
                analysis_style="大胆前瞻，关注颠覆性创新和技术拐点，偏好高风险高回报逻辑",
                sort_order=1,
            ),
            CelebrityTable(
                name="Warren Buffett",
                display_name="巴菲特",
                domain="finance",
                title="Berkshire Hathaway CEO",
                bio="价值投资之父，被誉为"奥马哈先知"。长期坚持基本面投资，强调安全边际和护城河。",
                viewpoints=(
                    "1. 别人贪婪时恐惧，别人恐惧时贪婪\n"
                    "2. 只投资你能理解的公司（能力圈原则）\n"
                    "3. 优秀公司的合理价格好于平庸公司的便宜价格\n"
                    "4. 长期持有，忽略短期波动"
                ),
                analysis_style="注重基本面和安全边际，偏好稳健价值股，回避热点炒作",
                sort_order=2,
            ),
            CelebrityTable(
                name="Ray Dalio",
                display_name="达利欧",
                domain="finance",
                title="Bridgewater Associates Founder",
                bio="全球最大对冲基金创始人，宏观投资大师。提倡"原则"思维和经济机器模型。",
                viewpoints=(
                    "1. 理解经济机器的运行规律\n"
                    "2. 长期债务周期决定了大趋势\n"
                    "3. 分散化是最重要的投资原则\n"
                    "4. 痛苦+反思=进步"
                ),
                analysis_style="宏观视角，关注经济周期、货币政策和地缘政治的交互影响",
                sort_order=3,
            ),
            CelebrityTable(
                name="Cathie Wood",
                display_name="木头姐",
                domain="tech",
                title="ARK Invest CEO",
                bio="颠覆性创新投资的代表人物，管理ARK系列主动ETF，重仓AI、基因编辑、区块链等前沿领域。",
                viewpoints=(
                    "1. 创新平台（AI/基因/区块链/机器人）正在融合加速\n"
                    "2. 传统价值投资低估了颠覆性创新的价值\n"
                    "3. 5年投资视野，关注指数级增长机会\n"
                    "4. 比特币和区块链将重塑金融体系"
                ),
                analysis_style="高成长偏好，重视技术融合的乘数效应，5年远期估值",
                sort_order=4,
            ),
        ]
        for c in celebrities:
            session.add(c)

        logger.info("[agent_db] Default agent data seeded")
```

- [ ] **Step 2: Verify tables create and import works**

Run: `cd backend && uv run python -c "from src.infra.database.impl.agent_db import create_agent_repository, migrate_add_deep_analysis_column, seed_agent_data; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/database/impl/agent_db.py
git commit -m "feat(agents): add SQLModel tables, AgentRepository, and seed data"
```

---

### Task 6: Modify intel_db.py — Add deep_analysis Column

**Files:**
- Modify: `backend/src/infra/database/impl/intel_db.py`

- [ ] **Step 1: Add `deep_analysis` JSONB column to `IntelNewsTable`**

In `intel_db.py`, find the `IntelNewsTable` class. Add this field after `processed`:

```python
    deep_analysis: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
```

You also need to add the JSONB import. Check if `JSONB` and `Column` are already imported from sqlalchemy. If `JSONB` is not imported, add it to the existing import line:

```python
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, insert as pg_insert
```

Change to:

```python
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, insert as pg_insert
```

(If `JSONB` is already imported, no change needed.)

And add `Column` to the sqlalchemy import if not present:

```python
from sqlalchemy import Column, Index, String, Text, text, func, or_
```

- [ ] **Step 2: Run migration at startup**

In `backend/main.py`, inside the `lifespan` function, after the existing intel repository warm-up block (look for `[DB] Intel repository warmed up`), add:

```python
            # Agent system: ensure tables and seed data
            from src.infra.database.impl.agent_db import (
                migrate_add_deep_analysis_column,
                seed_agent_data,
            )
            migrate_add_deep_analysis_column()
            seed_agent_data()
            app_logger.info("[Agent] tables migrated and seeded")
```

- [ ] **Step 3: Verify startup**

Run: `cd backend && uv run python -c "from src.infra.database.impl.intel_db import IntelNewsTable; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/src/infra/database/impl/intel_db.py backend/main.py
git commit -m "feat(agents): add deep_analysis JSONB column to intel_news"
```

---

### Task 7: Create LLM Adapter

**Files:**
- Create: `backend/src/infra/llm/langchain_adapter.py`

- [ ] **Step 1: Create the adapter**

```python
# backend/src/infra/llm/langchain_adapter.py
"""Bridge: llm_config table → LangChain ChatOpenAI instance."""
import json
from typing import Optional

from langchain_openai import ChatOpenAI
from loguru import logger


def create_chat_model(
    llm_config_id: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> ChatOpenAI:
    """Create a ChatOpenAI from the llm_config table entry.

    Args:
        llm_config_id: Specific config ID, or None for default.
        temperature: Default temperature (overridden by config extra_params).
        max_tokens: Default max_tokens (overridden by config extra_params).

    Returns:
        Configured ChatOpenAI instance.

    Raises:
        ValueError: If no LLM config is found.
    """
    from src.infra.database.impl.llm_db import create_llm_repository

    repo = create_llm_repository()

    if llm_config_id:
        config = repo.get_decrypted_config(llm_config_id)
    else:
        config = repo.get_default_config()
        if config:
            config = repo.get_decrypted_config(config.id)

    if not config:
        raise ValueError(
            f"No LLM config found (requested id={llm_config_id})"
        )

    extra: dict = {}
    if config.extra_params:
        try:
            extra = json.loads(config.extra_params)
        except (json.JSONDecodeError, TypeError):
            pass

    model_kwargs = {
        k: v
        for k, v in extra.items()
        if k not in ("temperature", "max_tokens", "model")
    }

    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        temperature=extra.get("temperature", temperature),
        max_tokens=extra.get("max_tokens", max_tokens),
        **model_kwargs,
    )


def create_chat_model_for_agent(agent_name: str) -> ChatOpenAI:
    """Create a ChatOpenAI for a specific agent, using its DB config.

    Reads agent_config.llm_config_id to find the right LLM.
    Falls back to default config if agent has no specific config.
    """
    from src.infra.database.impl.agent_db import create_agent_repository

    repo = create_agent_repository()
    agent = repo.get_agent_config_by_name(agent_name)

    llm_config_id = None
    extra: dict = {}
    if agent:
        llm_config_id = agent.llm_config_id
        extra = agent.extra_params or {}

    model = create_chat_model(
        llm_config_id=llm_config_id,
        temperature=extra.get("temperature", 0.3),
        max_tokens=extra.get("max_tokens", 4096),
    )

    logger.debug(
        f"[langchain_adapter] ChatOpenAI created for agent '{agent_name}'"
    )
    return model
```

- [ ] **Step 2: Verify import**

Run: `cd backend && uv run python -c "from src.infra.llm.langchain_adapter import create_chat_model, create_chat_model_for_agent; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/llm/langchain_adapter.py
git commit -m "feat(agents): add LangChain ChatOpenAI adapter bridging llm_config table"
```

---

### Task 8: Create Test Fixtures

**Files:**
- Create: `backend/tests/agents/__init__.py`
- Create: `backend/tests/agents/conftest.py`

- [ ] **Step 1: Create `__init__.py`**

Empty file.

- [ ] **Step 2: Create `conftest.py`**

```python
# backend/tests/agents/conftest.py
"""Shared fixtures for agent tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def sample_news():
    """Sample news item for testing."""
    return {
        "news_id": 1,
        "news_title": "NVIDIA 发布新一代 AI 芯片，性能提升 3 倍",
        "news_content": (
            "NVIDIA 在 GTC 大会上发布了基于 Blackwell Ultra 架构的新一代 GPU，"
            "AI 训练性能较上一代提升 3 倍，推理性能提升 5 倍。"
            "新芯片采用 3nm 制程，集成 2080 亿个晶体管，"
            "支持 12TB/s 的内存带宽。黄仁勋表示这将加速 AGI 的到来。"
            "受此影响，NVIDIA 股价盘后上涨 5%，AMD 和 Intel 股价小幅下跌。"
        ),
        "news_category": "future_tech",
    }


@pytest.fixture
def sample_celebrities():
    """Sample celebrity list for testing."""
    return [
        {
            "name": "Elon Musk",
            "display_name": "马斯克",
            "domain": "tech",
            "title": "Tesla / SpaceX / xAI CEO",
            "bio": "科技企业家，以大胆创新和跨界思维著称。",
            "viewpoints": "AI 是最大机遇和风险；电动车是必然趋势",
            "analysis_style": "大胆前瞻，关注颠覆性创新",
        },
        {
            "name": "Warren Buffett",
            "display_name": "巴菲特",
            "domain": "finance",
            "title": "Berkshire Hathaway CEO",
            "bio": "价值投资之父，长期坚持基本面投资。",
            "viewpoints": "别人贪婪时恐惧，别人恐惧时贪婪",
            "analysis_style": "注重基本面和安全边际",
        },
        {
            "name": "Ray Dalio",
            "display_name": "达利欧",
            "domain": "finance",
            "title": "Bridgewater Associates Founder",
            "bio": "宏观投资大师，提倡原则思维。",
            "viewpoints": "理解经济机器运行规律；分散化是核心原则",
            "analysis_style": "宏观视角，关注经济周期",
        },
    ]


@pytest.fixture
def mock_chat_model():
    """Mock ChatOpenAI that returns configurable structured responses."""
    model = MagicMock()
    model.ainvoke = AsyncMock()
    model.invoke = MagicMock()
    return model


@pytest.fixture
def tagging_result():
    """Expected TaggingAgent output."""
    return {
        "tags": ["AI芯片", "NVIDIA", "GPU", "半导体", "Blackwell"],
        "industry": "Technology",
        "sentiment": 0.7,
        "confidence": 0.9,
    }


@pytest.fixture
def persona_analysis_result():
    """Expected single persona analysis output."""
    return {
        "celebrity_name": "Elon Musk",
        "perspective": "这是AI硬件领域的重大突破...",
        "key_insights": [
            "3nm制程是业界领先",
            "AI训练性能3倍提升将加速模型迭代",
            "对AGI时间线有重大影响",
        ],
        "investment_implication": "利好NVIDIA及整个AI产业链",
        "confidence": 0.85,
    }
```

- [ ] **Step 3: Verify fixtures load**

Run: `cd backend && uv run python -m pytest tests/agents/ --co -q 2>&1 | head -5`
Expected: no errors (may show "no tests collected" which is fine).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/agents/
git commit -m "test(agents): add test fixtures for agent unit tests"
```

---

### Task 9: Smoke Test — Start Server, Verify Tables

- [ ] **Step 1: Start the backend**

Run: `cd backend && uv run python main.py &`

Wait for startup to complete (look for `App startup complete` in logs).

- [ ] **Step 2: Verify new tables exist**

Run:
```bash
psql "$YTRADER_DB_DSN" -c "\dt agent_*" -c "\dt celebrity" -c "\dt prompt_template" -c "\d intel_news" | grep deep_analysis
```

Expected: Tables `agent_config`, `agent_pipeline`, `prompt_template`, `celebrity` exist, and `intel_news` has `deep_analysis` column.

- [ ] **Step 3: Verify seed data**

Run:
```bash
psql "$YTRADER_DB_DSN" -c "SELECT name, agent_type FROM agent_config" -c "SELECT name FROM celebrity" -c "SELECT name FROM prompt_template"
```

Expected: 4 agent configs, 4 celebrities, 6 prompt templates.

- [ ] **Step 4: Kill the test server**

Kill the background process.

---

### Task 10: Final Commit

- [ ] **Step 1: Ensure all files are committed**

```bash
git status
```

Expected: All new/modified files committed, no uncommitted changes related to this plan.

- [ ] **Step 2: Verify no import errors**

Run: `cd backend && uv run python -c "from src.domain.market.intel.agents.models import *; from src.domain.market.intel.agents.state import *; from src.domain.market.intel.agents.schemas import *; from src.domain.market.intel.agents.repository_interface import *; from src.infra.database.impl.agent_db import *; from src.infra.llm.langchain_adapter import *; print('ALL IMPORTS OK')"`
Expected: `ALL IMPORTS OK`
