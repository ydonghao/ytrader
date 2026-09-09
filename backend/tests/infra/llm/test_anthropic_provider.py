"""Unit tests for Anthropic provider."""
from unittest.mock import MagicMock

import pytest

from src.domain.llm.models import LLMConfig
from src.infra.llm.providers.anthropic_provider import AnthropicProvider


@pytest.fixture
def config():
    return LLMConfig(
        id="test",
        name="Claude Sonnet",
        provider_type="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
    )


@pytest.fixture
def provider(config):
    return AnthropicProvider(config)


def test_provider_creates_client(provider):
    assert provider._client is not None


@pytest.mark.asyncio
async def test_chat_returns_llm_response(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "Hello from Claude!"
    mock_response.model = "claude-sonnet-4-20250514"
    mock_response.usage = MagicMock()
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_response.model_dump = MagicMock(return_value={})

    provider._client.messages.create = MagicMock(
        return_value=mock_response
    )

    result = await provider.chat([{"role": "user", "content": "Hi"}])
    assert result.content == "Hello from Claude!"
    assert result.model == "claude-sonnet-4-20250514"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5


@pytest.mark.asyncio
async def test_complete_wraps_chat(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "42"
    mock_response.model = "claude-sonnet-4-20250514"
    mock_response.usage = None
    mock_response.model_dump = MagicMock(return_value={})

    provider._client.messages.create = MagicMock(
        return_value=mock_response
    )

    result = await provider.complete("6*7?")
    assert result.content == "42"


@pytest.mark.asyncio
async def test_chat_passes_max_tokens(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "short"
    mock_response.model = "claude-sonnet-4-20250514"
    mock_response.usage = None
    mock_response.model_dump = MagicMock(return_value={})

    provider._client.messages.create = MagicMock(
        return_value=mock_response
    )

    await provider.chat([{"role": "user", "content": "Hi"}], max_tokens=100)
    call_kwargs = provider._client.messages.create.call_args[1]
    assert call_kwargs["max_tokens"] == 100
