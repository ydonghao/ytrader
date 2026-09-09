"""
MiniMax LLM Client
==================
OpenAI-compatible interface for MiniMax models.
Base URL: https://api.minimaxi.com/v1 (Chinese platform)
"""
import os
import warnings
from typing import Any, Optional

from openai import OpenAI

warnings.warn(
    "src.llm.client is deprecated. Use src.infra.llm.manager.LLMManager instead.",
    DeprecationWarning,
    stacklevel=2,
)


class MiniMaxClient:
    """MiniMax OpenAI-compatible LLM client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "MiniMax-M2.7",
        base_url: str = "https://api.minimaxi.com/v1",
    ) -> None:
        """
        Initialize the MiniMax client.

        Args:
            api_key: MiniMax API key. Falls back to MINIMAX_API_KEY env var.
            model: Model name. Defaults to MiniMax-M2.7.
            base_url: API base URL. Defaults to the Chinese platform endpoint.
        """
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        if not self.api_key:
            raise ValueError("MINIMAX_API_KEY environment variable is not set")
        self.model = model
        self.base_url = base_url
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        """
        Send a chat completion request to MiniMax.

        Args:
            messages: List of message dicts with keys 'role' and 'content'.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters passed to the API.

        Returns:
            The assistant's reply text.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    def complete(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        """
        Simple single-prompt completion.

        Args:
            prompt: The user prompt string.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters.

        Returns:
            The assistant's reply text.
        """
        return self.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )


# Singleton accessor
_client: Optional["MiniMaxClient"] = None


def get_llm_client() -> "MiniMaxClient":
    """Return the global MiniMax client instance."""
    global _client
    if _client is None:
        _client = MiniMaxClient()
    return _client
