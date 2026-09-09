"""Request/response models for LLM config API."""
from __future__ import annotations

from typing import Literal, Any
from pydantic import BaseModel


class LLMConfigCreate(BaseModel):
    name: str
    provider_type: Literal["openai_chat", "openai_response", "anthropic"]
    base_url: str
    api_key: str
    model: str
    is_default: bool = False
    extra_params: dict[str, Any] = {}


class LLMConfigUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    is_default: bool | None = None
    extra_params: dict[str, Any] | None = None


class LLMConfigResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: str
    api_key: str
    model: str
    is_default: bool
    extra_params: dict[str, Any]
    created_at: str | None = None
    updated_at: str | None = None


class LLMTestRequest(BaseModel):
    config_id: str | None = None


class LLMTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: float | None = None
