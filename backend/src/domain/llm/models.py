"""LLM domain models — provider-agnostic data classes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: TokenUsage | None = None
    raw_response: dict[str, Any] | None = None


@dataclass
class LLMChunk:
    content: str
    model: str
    finish_reason: str | None = None


@dataclass
class LLMConfig:
    """A single model configuration (domain model, api_key is plaintext)."""
    id: str = ""
    name: str = ""
    provider_type: str = ""  # "openai_chat" | "openai_response" | "anthropic"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    is_default: bool = False
    extra_params: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class TestResult:
    success: bool
    message: str
    latency_ms: float | None = None


# Sentinel value for masked API keys in read responses
MASKED_KEY = "****"
