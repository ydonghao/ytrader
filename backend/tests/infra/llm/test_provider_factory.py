"""Unit tests for LLM provider factory."""
import pytest

from src.domain.llm.models import LLMConfig
from src.infra.llm.providers.openai_chat_provider import OpenAIChatProvider
from src.infra.llm.providers.openai_response_provider import OpenAIResponseProvider
from src.infra.llm.providers.anthropic_provider import AnthropicProvider
from src.infra.llm.provider_factory import create_provider


def test_create_openai_chat_provider():
    config = LLMConfig(
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )
    provider = create_provider(config)
    assert isinstance(provider, OpenAIChatProvider)


def test_create_openai_response_provider():
    config = LLMConfig(
        provider_type="openai_response",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )
    provider = create_provider(config)
    assert isinstance(provider, OpenAIResponseProvider)


def test_create_anthropic_provider():
    config = LLMConfig(
        provider_type="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
    )
    provider = create_provider(config)
    assert isinstance(provider, AnthropicProvider)


def test_create_unknown_provider_raises():
    config = LLMConfig(
        provider_type="unknown_type",
        base_url="http://example.com",
        api_key="key",
        model="model",
    )
    with pytest.raises(ValueError, match="Unknown provider type"):
        create_provider(config)
