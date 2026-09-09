"""LLM config repository interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.llm.models import LLMConfig


class ILLMConfigRepository(ABC):

    @abstractmethod
    def list_configs(self) -> list[LLMConfig]:
        """List all configs. API keys are masked (****)."""

    @abstractmethod
    def get_config(self, config_id: str) -> LLMConfig | None:
        """Get a single config by ID. API key is masked."""

    @abstractmethod
    def get_default_config(self) -> LLMConfig | None:
        """Get the default config. API key is decrypted (plaintext)."""

    @abstractmethod
    def get_decrypted_config(self, config_id: str) -> LLMConfig | None:
        """Get a config with decrypted API key. Used internally by LLMManager."""

    @abstractmethod
    def create_config(self, config: LLMConfig) -> LLMConfig:
        """Create a new config. Encrypts api_key before storing."""

    @abstractmethod
    def update_config(self, config_id: str, updates: dict) -> LLMConfig | None:
        """Update fields. If api_key is empty/None, keeps existing."""

    @abstractmethod
    def delete_config(self, config_id: str) -> bool:
        """Delete a config. Returns True if deleted."""

    @abstractmethod
    def set_default(self, config_id: str) -> None:
        """Set a config as default. Clears other defaults first."""
