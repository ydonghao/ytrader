"""Anthropic Messages API provider."""
from __future__ import annotations

from typing import AsyncIterator

import anthropic

from src.domain.llm.models import LLMChunk, LLMConfig, LLMResponse, TokenUsage
from src.domain.llm.provider_interface import LLMProvider


class AnthropicProvider(LLMProvider):
    """Provider using Anthropic Messages API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = anthropic.Anthropic(
            api_key=config.api_key,
            base_url=(
                config.base_url
                if config.base_url != "https://api.anthropic.com"
                else None
            ),
        )

    async def chat(
        self, messages: list[dict[str, str]], **kwargs
    ) -> LLMResponse:
        max_tokens = kwargs.pop("max_tokens", 1024)
        temperature = kwargs.pop("temperature", None)

        params: dict = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            params["temperature"] = temperature

        response = self._client.messages.create(**params)

        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=(
                    response.usage.input_tokens
                    + response.usage.output_tokens
                ),
            )

        return LLMResponse(
            content=(
                response.content[0].text if response.content else ""
            ),
            model=response.model,
            usage=usage,
            raw_response=(
                response.model_dump()
                if hasattr(response, "model_dump")
                else None
            ),
        )

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        return await self.chat(
            [{"role": "user", "content": prompt}], **kwargs
        )

    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs
    ) -> AsyncIterator[LLMChunk]:
        max_tokens = kwargs.pop("max_tokens", 1024)

        with self._client.messages.stream(
            model=self._config.model,
            messages=messages,
            max_tokens=max_tokens,
        ) as stream:
            for text in stream.text_stream:
                yield LLMChunk(
                    content=text,
                    model=self._config.model,
                    finish_reason=None,
                )
