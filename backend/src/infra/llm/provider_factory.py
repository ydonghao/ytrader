"""Factory for creating LLM provider instances."""
from __future__ import annotations

from src.domain.llm.models import LLMConfig
from src.domain.llm.provider_interface import LLMProvider
from src.infra.llm.providers.openai_chat_provider import OpenAIChatProvider
from src.infra.llm.providers.openai_response_provider import OpenAIResponseProvider
from src.infra.llm.providers.anthropic_provider import AnthropicProvider

PROVIDER_MAP: dict[str, type[LLMProvider]] = {
    "openai_chat": OpenAIChatProvider,
    "openai_response": OpenAIResponseProvider,
    "anthropic": AnthropicProvider,
}


def create_provider(config: LLMConfig) -> LLMProvider:
    """Create a provider instance based on config.provider_type."""
    provider_cls = PROVIDER_MAP.get(config.provider_type)
    if not provider_cls:
        raise ValueError(
            f"Unknown provider type: {config.provider_type}. "
            f"Supported: {list(PROVIDER_MAP.keys())}"
        )
    return provider_cls(config)
