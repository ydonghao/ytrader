"""Unit tests for OpenAI Chat provider."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.llm.models import LLMConfig
from src.infra.llm.providers.openai_chat_provider import OpenAIChatProvider


@pytest.fixture
def config():
    return LLMConfig(
        id="test",
        name="GPT-4o",
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )


@pytest.fixture
def provider(config):
    return OpenAIChatProvider(config)


def test_provider_creates_client(provider):
    assert provider._client is not None


@pytest.mark.asyncio
async def test_chat_returns_llm_response(provider):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello!"
    mock_response.model = "gpt-4o"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5
    mock_response.usage.total_tokens = 15
    mock_response.model_dump = MagicMock(return_value={})

    provider._client.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    result = await provider.chat([{"role": "user", "content": "Hi"}])
    assert result.content == "Hello!"
    assert result.model == "gpt-4o"
    assert result.usage.total_tokens == 15


@pytest.mark.asyncio
async def test_complete_wraps_chat(provider):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "2+2=4"
    mock_response.model = "gpt-4o"
    mock_response.usage = None
    mock_response.model_dump = MagicMock(return_value={})

    provider._client.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    result = await provider.complete("What is 2+2?")
    assert result.content == "2+2=4"


@pytest.mark.asyncio
async def test_chat_with_kwargs(provider):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "creative answer"
    mock_response.model = "gpt-4o"
    mock_response.usage = None
    mock_response.model_dump = MagicMock(return_value={})

    provider._client.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    result = await provider.chat(
        [{"role": "user", "content": "Be creative"}],
        temperature=0.9,
        max_tokens=500,
    )
    assert result.content == "creative answer"
    provider._client.chat.completions.create.assert_called_once()
