"""Bridge: llm_config table -> LangChain ChatAnthropic instance.

Uses ChatAnthropic (not ChatOpenAI) because the configured API endpoint
(api.z.ai) speaks the Anthropic Messages protocol, not OpenAI chat/completions.
"""
import json
from typing import Optional, Union

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from loguru import logger


def create_chat_model(
    llm_config_id: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    callbacks=None,
) -> BaseChatModel:
    """Create a chat model from the llm_config table entry.

    Args:
        llm_config_id: Specific config ID, or None for default.
        temperature: Default temperature (overridden by config extra_params).
        max_tokens: Default max_tokens (overridden by config extra_params).

    Returns:
        Configured BaseChatModel instance (ChatAnthropic).

    Raises:
        ValueError: If no LLM config is found.
    """
    from src.infra.database.llm.repository import create_llm_repository

    repo = create_llm_repository()

    if llm_config_id:
        config = repo.get_decrypted_config(llm_config_id)
    else:
        config = repo.get_default_config()
        if config:
            config = repo.get_decrypted_config(config.id)

    if not config:
        raise ValueError(
            f"No LLM config found (requested id={llm_config_id})"
        )

    extra: dict = {}
    if config.extra_params:
        try:
            extra = json.loads(config.extra_params)
        except (json.JSONDecodeError, TypeError):
            pass

    return ChatAnthropic(
        anthropic_api_key=config.api_key,
        anthropic_api_url=config.base_url,
        model=config.model,
        temperature=extra.get("temperature", temperature),
        max_tokens=extra.get("max_tokens", max_tokens),
        callbacks=callbacks,
    )


def create_chat_model_for_agent(agent_name: str) -> BaseChatModel:
    """Create a chat model for a specific agent, using its DB config.

    Reads agent_config.llm_config_id to find the right LLM.
    Falls back to default config if agent has no specific config.
    """
    from src.infra.database.agent.repository import create_agent_repository

    repo = create_agent_repository()
    agent = repo.get_agent_config_by_name(agent_name)

    llm_config_id = None
    extra: dict = {}
    if agent:
        llm_config_id = agent.llm_config_id
        extra = agent.extra_params or {}

    from src.infra.tracing.llm_callback import make_llm_callback

    model = create_chat_model(
        llm_config_id=llm_config_id,
        temperature=extra.get("temperature", 0.3),
        max_tokens=extra.get("max_tokens", 4096),
        callbacks=[make_llm_callback(agent_name)],
    )

    logger.debug(
        f"[langchain_adapter] ChatAnthropic created for agent '{agent_name}'"
    )
    return model
