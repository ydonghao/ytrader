"""OpenAI Chat Completions provider."""
from __future__ import annotations

from typing import AsyncIterator

from openai import AsyncOpenAI

from src.domain.llm.models import LLMChunk, LLMConfig, LLMResponse, TokenUsage
from src.domain.llm.provider_interface import LLMProvider


class OpenAIChatProvider(LLMProvider):
    """Provider using OpenAI Chat Completions API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    async def chat(
        self, messages: list[dict[str, str]], **kwargs
    ) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            **kwargs,
        )
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
        return LLMResponse(
            content=response.choices[0].message.content,
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
        stream = await self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield LLMChunk(
                    content=delta.content,
                    model=chunk.model,
                    finish_reason=(
                        chunk.choices[0].finish_reason
                        if chunk.choices
                        else None
                    ),
                )
