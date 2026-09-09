"""Unit tests for LLM Manager."""
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.domain.llm.models import LLMConfig, TestResult
from src.domain.llm.provider_interface import LLMProvider
from src.infra.llm.manager import LLMManager


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    return repo


@pytest.fixture
def sample_config():
    return LLMConfig(
        id="cfg-1",
        name="Test GPT",
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
        is_default=True,
    )


@pytest.fixture
def mock_provider():
    provider = MagicMock(spec=LLMProvider)
    return provider


def test_get_provider_returns_none_when_no_default(mock_repo):
    mock_repo.get_default_config.return_value = None
    manager = LLMManager(mock_repo)
    assert manager.get_provider() is None


def test_get_provider_returns_provider(
    mock_repo, sample_config, mock_provider
):
    mock_repo.get_default_config.return_value = sample_config
    mock_repo.get_decrypted_config.return_value = sample_config
    manager = LLMManager(mock_repo)
    with patch(
        "src.infra.llm.manager.create_provider",
        return_value=mock_provider,
    ):
        provider = manager.get_provider()
    assert provider is not None


def test_get_provider_by_id(mock_repo, sample_config, mock_provider):
    mock_repo.get_decrypted_config.return_value = sample_config
    manager = LLMManager(mock_repo)
    with patch(
        "src.infra.llm.manager.create_provider",
        return_value=mock_provider,
    ):
        provider = manager.get_provider("cfg-1")
    assert provider is not None
    mock_repo.get_decrypted_config.assert_called_once_with("cfg-1")


def test_get_provider_caches(
    mock_repo, sample_config, mock_provider
):
    mock_repo.get_default_config.return_value = sample_config
    mock_repo.get_decrypted_config.return_value = sample_config
    manager = LLMManager(mock_repo)
    with patch(
        "src.infra.llm.manager.create_provider",
        return_value=mock_provider,
    ):
        p1 = manager.get_provider()
        p2 = manager.get_provider()
    assert p1 is p2


def test_refresh_clears_cache(
    mock_repo, sample_config, mock_provider
):
    mock_repo.get_default_config.return_value = sample_config
    mock_repo.get_decrypted_config.return_value = sample_config
    manager = LLMManager(mock_repo)
    another_provider = MagicMock(spec=LLMProvider)
    with patch(
        "src.infra.llm.manager.create_provider",
        return_value=mock_provider,
    ):
        p1 = manager.get_provider()
    manager.refresh()
    with patch(
        "src.infra.llm.manager.create_provider",
        return_value=another_provider,
    ):
        p2 = manager.get_provider()
    assert p1 is not p2


@pytest.mark.asyncio
async def test_test_connection_success(
    mock_repo, sample_config
):
    mock_repo.get_decrypted_config.return_value = sample_config
    mock_provider = MagicMock(spec=LLMProvider)
    mock_provider.complete = AsyncMock(
        return_value=MagicMock(content="Hi there!", model="gpt-4o")
    )

    manager = LLMManager(mock_repo)
    with patch(
        "src.infra.llm.manager.create_provider",
        return_value=mock_provider,
    ):
        result = await manager.test_connection("cfg-1")
    assert result.success is True
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_test_connection_failure(mock_repo):
    mock_repo.get_decrypted_config.return_value = None
    manager = LLMManager(mock_repo)
    result = await manager.test_connection("nonexistent")
    assert result.success is False
