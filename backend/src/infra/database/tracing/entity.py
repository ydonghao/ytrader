"""Agent tracing SQLModel tables (spec section 3)."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field


class AgentRunTable(SQLModel, table=True):
    """One pipeline run (e.g. one blog_topic generation)."""
    __tablename__ = "agent_run"
    __table_args__ = (
        # 覆盖 list_runs ORDER BY started_at DESC 的反向排序（避免 filesort）
        Index("idx_agent_run_started", "started_at"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True)  # uuid hex
    pipeline: str = Field(default="", max_length=50, index=True)
    topic: str = Field(default="", max_length=50)
    status: str = Field(default="running", max_length=20, index=True)
    draft_id: Optional[int] = Field(default=None)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ended_at: Optional[datetime] = None
    duration_ms: int = Field(default=0)
    error: Optional[str] = Field(default=None, sa_column=Column(Text))


class AgentRunStepTable(SQLModel, table=True):
    """One node execution within a run."""
    __tablename__ = "agent_run_step"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    node: str = Field(default="", max_length=50, index=True)
    seq: int = Field(default=0)
    status: str = Field(default="running", max_length=20)
    input: dict = Field(default={}, sa_column=Column(JSONB))
    output: dict = Field(default={}, sa_column=Column(JSONB))
    duration_ms: int = Field(default=0)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ended_at: Optional[datetime] = None
    error: Optional[str] = Field(default=None, sa_column=Column(Text))


class AgentRunLlmTable(SQLModel, table=True):
    """One LLM call within a step."""
    __tablename__ = "agent_run_llm"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    step_node: str = Field(default="", max_length=50, index=True)
    agent_name: str = Field(default="", max_length=50)
    prompt: str = Field(default="", sa_column=Column(Text))
    response: str = Field(default="", sa_column=Column(Text))
    tokens_prompt: int = Field(default=0)
    tokens_completion: int = Field(default=0)
    tokens_total: int = Field(default=0)
    duration_ms: int = Field(default=0)
    status: str = Field(default="running", max_length=20)
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
