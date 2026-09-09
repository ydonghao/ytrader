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


# ── Agent Tool Binding ──

class ToolBindingRequest(BaseModel):
    """Set which agent_tool ids an agent has enabled (full overwrite)."""
    tool_ids: list[int] = Field(
        default_factory=list,
        description="agent_tool IDs to bind (enabled). Any not listed are unbound.",
    )


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

