"""Unit tests for OpenAI Response provider."""
from unittest.mock import MagicMock

import pytest

from src.domain.llm.models import LLMConfig
from src.infra.llm.providers.openai_response_provider import (
    OpenAIResponseProvider,
)


@pytest.fixture
def config():
    return LLMConfig(
        id="test",
        name="GPT-4o Response",
        provider_type="openai_response",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )


@pytest.fixture
def provider(config):
    return OpenAIResponseProvider(config)


@pytest.mark.asyncio
async def test_chat_returns_llm_response(provider):
    mock_response = MagicMock()
    mock_response.output_text = "Hello from responses API!"
    mock_response.model = "gpt-4o"
    mock_response.usage = MagicMock()
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_response.usage.total_tokens = 15
    mock_response.model_dump = MagicMock(return_value={})

    provider._client.responses.create = MagicMock(
        return_value=mock_response
    )

    result = await provider.chat(
        [{"role": "user", "content": "Hi"}]
    )
    assert result.content == "Hello from responses API!"
    assert result.model == "gpt-4o"


@pytest.mark.asyncio
async def test_complete_wraps_chat(provider):
    mock_response = MagicMock()
    mock_response.output_text = "42"
    mock_response.model = "gpt-4o"
    mock_response.usage = None
    mock_response.model_dump = MagicMock(return_value={})

    provider._client.responses.create = MagicMock(
        return_value=mock_response
    )

    result = await provider.complete("What is 6*7?")
    assert result.content == "42"
