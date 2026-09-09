"""
LLM config SQLModel table definition.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import SQLModel, Field


class LLMConfigTable(SQLModel, table=True):
    __tablename__ = "llm_config"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), primary_key=True
    )
    name: str = Field(index=True)
    provider_type: str  # "openai_chat" | "openai_response" | "anthropic"
    base_url: str
    api_key_encrypted: str  # Fernet-encrypted ciphertext
    model: str
    is_default: bool = Field(default=False, index=True)
    extra_params: str = Field(default="{}")  # JSON string
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
