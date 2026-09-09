"""LLM Manager — unified entry point for LLM operations."""
from __future__ import annotations

import time

from loguru import logger

from src.domain.llm.models import TestResult
from src.domain.llm.provider_interface import LLMProvider
from src.domain.llm.repository_interface import ILLMConfigRepository
from src.infra.llm.provider_factory import create_provider


class LLMManager:
    """Manages LLM provider instances with caching and lifecycle."""

    def __init__(self, repo: ILLMConfigRepository) -> None:
        self._repo = repo
        self._cache: dict[str, LLMProvider] = {}

    def get_provider(
        self, config_id: str | None = None
    ) -> LLMProvider | None:
        """Get a provider instance. None=config_id -> default model."""
        if config_id is not None:
            return self._get_or_create(config_id)

        default = self._repo.get_default_config()
        if default is None:
            return None
        return self._get_or_create(default.id)

    def _get_or_create(self, config_id: str) -> LLMProvider | None:
        if config_id in self._cache:
            return self._cache[config_id]

        config = self._repo.get_decrypted_config(config_id)
        if config is None:
            return None

        provider = create_provider(config)
        self._cache[config_id] = provider
        return provider

    async def test_connection(self, config_id: str) -> TestResult:
        """Test a model connection by sending 'Hi'."""
        config = self._repo.get_decrypted_config(config_id)
        if config is None:
            return TestResult(success=False, message="Configuration not found")

        try:
            provider = create_provider(config)
            start = time.monotonic()
            response = await provider.complete("Hi", max_tokens=50)
            elapsed = (time.monotonic() - start) * 1000

            if response.content:
                return TestResult(
                    success=True,
                    message=(
                        f"Connected to {config.name}. "
                        f"Response: {response.content[:50]}"
                    ),
                    latency_ms=round(elapsed, 1),
                )
            return TestResult(
                success=False, message="Empty response from model"
            )
        except Exception as e:
            logger.error(
                f"LLM connection test failed for {config_id}: {e}"
            )
            return TestResult(
                success=False,
                message=f"Connection failed: {str(e)[:200]}",
            )

    def refresh(self) -> None:
        """Clear provider cache. Call after config changes."""
        self._cache.clear()
        logger.debug("LLM provider cache cleared")
