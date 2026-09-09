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


@dataclass
class PromptTemplateHistory:
    """prompt_template 的历史快照, stored in prompt_template_history.

    Append-only: 每次编辑 template 前归档当前内容, 用于版本回滚与审计.
    """
    template_id: int
    name: str
    version: int
    template: str
    variables: dict = field(default_factory=dict)
    description: str = ""
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class AgentTool:
    """A tool an agent can call, stored in agent_tool.

    source: "builtin" (Python @tool) | "mcp" (MCP server tool) | "skill".
    ref_key: source-specific identifier (func name / "{server_id}:{tool}" / skill_id).
    args_schema: JSON-schema of the tool input (for mcp/skill).
    """
    name: str
    source: str
    ref_key: str
    display_name: str = ""
    description: str = ""
    args_schema: dict = field(default_factory=dict)
    is_active: bool = True
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
