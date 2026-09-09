"""LLM provider interface — all providers must implement this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from src.domain.llm.models import LLMResponse, LLMChunk


class LLMProvider(ABC):
    """Unified LLM calling interface."""

    @abstractmethod
    async def chat(
        self, messages: list[dict[str, str]], **kwargs
    ) -> LLMResponse:
        """Multi-turn chat. messages format: [{"role": "user", "content": "..."}]."""

    @abstractmethod
    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Single-prompt completion."""

    @abstractmethod
    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs
    ) -> AsyncIterator[LLMChunk]:
        """Streaming multi-turn chat."""
