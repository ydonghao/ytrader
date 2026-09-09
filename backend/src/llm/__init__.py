"""LLM client — DEPRECATED. Use src.infra.llm.manager.LLMManager instead."""
from .client import MiniMaxClient, get_llm_client

__all__ = ["MiniMaxClient", "get_llm_client"]
