"""
Agent system SQLModel table definitions.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field


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


class PromptTemplateHistoryTable(SQLModel, table=True):
    """Append-only snapshot of a prompt_template row before each edit.

    Written by the repository whenever `template` changes, so every
    version is recoverable for audit / rollback. Never updated in place.
    """
    __tablename__ = "prompt_template_history"
    id: Optional[int] = Field(default=None, primary_key=True)
    template_id: int = Field(foreign_key="prompt_template.id", index=True)
    name: str = Field(index=True)  # denormalized for audit readability
    version: int  # the version number this snapshot represents
    template: str = Field(sa_column=Column(Text))
    variables: dict = Field(default={}, sa_column=Column(JSONB))
    description: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AgentToolTable(SQLModel, table=True):
    """Registry of every tool an agent can call.

    A row is either a built-in Python tool (source="builtin"), a tool
    discovered from an MCP server (source="mcp"), or a skill wrapped as a
    single tool (source="skill"). `ref_key` is source-specific:
      - builtin → function name (e.g. "discover_trends")
      - mcp     → f"{server_id}:{tool_name}"
      - skill   → str(skill_id)
    `args_schema` holds the JSON-schema of the tool's input (for mcp/skill),
    so the LLM can see how to call it.
    """
    __tablename__ = "agent_tool"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    display_name: str = Field(default="")
    description: str = Field(default="", sa_column=Column(Text))
    source: str = Field(index=True)  # "builtin" | "mcp" | "skill"
    ref_key: str = Field(unique=True, index=True)
    args_schema: dict = Field(default={}, sa_column=Column(JSONB))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentToolBindingTable(SQLModel, table=True):
    """Many-to-many: which agent_config has which agent_tool enabled.

    One row per (agent_config, tool) pair. `set_bindings` rewrites this
    table for an agent on every save (delete-then-insert the diff), so the
    enabled set is always exactly what the user ticked in the console.
    """
    __tablename__ = "agent_tool_binding"
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_config_id: int = Field(foreign_key="agent_config.id", index=True)
    agent_tool_id: int = Field(foreign_key="agent_tool.id", index=True)
    is_enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))