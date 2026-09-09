"""OpenAI Responses API provider."""
from __future__ import annotations

from typing import AsyncIterator

from openai import OpenAI

from src.domain.llm.models import LLMConfig, LLMResponse, TokenUsage, LLMChunk
from src.domain.llm.provider_interface import LLMProvider


class OpenAIResponseProvider(LLMProvider):
    """Provider using OpenAI Responses API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    async def chat(
        self, messages: list[dict[str, str]], **kwargs
    ) -> LLMResponse:
        # Responses API takes a single input string
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg["content"]
                break
        if not last_user_msg:
            last_user_msg = messages[-1]["content"] if messages else ""

        response = self._client.responses.create(
            model=self._config.model,
            input=last_user_msg,
            **kwargs,
        )
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = TokenUsage(
                prompt_tokens=getattr(
                    response.usage, "input_tokens", 0
                ),
                completion_tokens=getattr(
                    response.usage, "output_tokens", 0
                ),
                total_tokens=getattr(
                    response.usage, "total_tokens", 0
                ),
            )
        return LLMResponse(
            content=getattr(response, "output_text", "") or "",
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
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg["content"]
                break

        stream = self._client.responses.create(
            model=self._config.model,
            input=last_user_msg,
            stream=True,
            **kwargs,
        )
        for event in stream:
            if hasattr(event, "delta") and event.delta:
                yield LLMChunk(
                    content=event.delta,
                    model=self._config.model,
                    finish_reason=None,
                )
