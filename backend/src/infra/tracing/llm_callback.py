"""LLMCallback — langchain callback that records each LLM call (spec 4.2).

Attached to chat models created by create_chat_model_for_agent. Each LLM
call is recorded to agent_run_llm, attributed to the current run/step via
contextvar. If no run is active (current_run_id is None), recording is skipped.
"""
import json
import time
from typing import Any, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from loguru import logger

from src.infra.tracing.recorder import current_run_id, current_step_node


def _extract_block_text(block: dict) -> str:
    """Extract readable text from a single content block.

    Plain text blocks expose ``text``. Tool-call blocks produced by
    ``with_structured_output(method="function_calling")`` carry the parsed
    payload in ``input`` (GLM/Anthropic) or ``function.arguments`` (OpenAI)
    instead of ``text`` — serialize those to JSON so the trace shows the
    real structured output rather than a raw ``AIMessage`` repr.
    """
    if "text" in block:
        return block.get("text", "") or ""
    payload = None
    if "input" in block:                       # tool_use / GLM-style
        payload = block["input"]
    elif "function" in block:                 # OpenAI-style function call
        payload = block.get("function", {}).get("arguments")
    elif "arguments" in block:
        payload = block["arguments"]
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)


# Generous per-section cap for traced prompts. System prompts often embed
# bulk data (e.g. the full hotlist in trend_spotter); 50k keeps virtually
# all real prompts whole while bounding pathological cases. The user
# message is never capped (it is the short editable instruction).
_SYSTEM_CAP = 50000


class LLMCallback(BaseCallbackHandler):
    """Records each LLM call to agent_run_llm."""

    def __init__(self, agent_name: str = ""):
        self.agent_name = agent_name
        self._start_times: dict = {}
        self._prompts: dict = {}

    # ── chat model (primary path for ChatAnthropic etc.) ──
    def on_chat_model_start(
        self, serialized: dict, messages: list, *, run_id: UUID = None, **kwargs,
    ) -> None:
        try:
            self._start_times[run_id] = time.monotonic()
            # Partition messages by role so a long system prompt never
            # starves the user message in the trace. System is capped
            # generously (it often embeds bulk data like the hotlist);
            # user is kept whole (it's the short editable instruction).
            system_parts: list[str] = []
            user_parts: list[str] = []
            other_parts: list[str] = []
            for batch in (messages or []):
                for m in batch:
                    role = getattr(m, "type", "") or "unknown"
                    content = getattr(m, "content", "")
                    if not isinstance(content, str):
                        content = str(content)
                    if role == "system":
                        system_parts.append(content)
                    elif role == "user":
                        user_parts.append(content)
                    else:
                        other_parts.append(f"[{role}] {content}")
            sections: list[str] = []
            if system_parts:
                sections.append(
                    "[system]\n" + "\n".join(system_parts)[:_SYSTEM_CAP]
                )
            if user_parts:
                sections.append("[user]\n" + "\n".join(user_parts))
            if other_parts:
                sections.append("\n".join(other_parts)[:_SYSTEM_CAP])
            prompt_str = "\n\n".join(sections)
            self._prompts[run_id] = prompt_str
            logger.info(
                f"[LLM] agent='{self.agent_name}' "
                f"step='{current_step_node() or '-'}' "
                f"prompt_len={len(prompt_str)}"
            )
            logger.debug(f"[LLM] prompt preview: {prompt_str[:200]}")
        except Exception as e:
            logger.warning(f"[tracing] on_chat_model_start failed: {e}")

    # ── plain LLM (non-chat) fallback ──
    def on_llm_start(
        self, serialized: dict, prompts: list, *, run_id: UUID = None, **kwargs,
    ) -> None:
        try:
            self._start_times[run_id] = time.monotonic()
            prompt_str = (prompts[0] if prompts else "")[:4000]
            self._prompts[run_id] = prompt_str
            logger.info(
                f"[LLM] agent='{self.agent_name}' "
                f"step='{current_step_node() or '-'}' "
                f"prompt_len={len(prompt_str)} (llm_start)"
            )
        except Exception as e:
            logger.warning(f"[tracing] on_llm_start failed: {e}")

    def on_llm_end(self, response, *, run_id: UUID = None, **kwargs) -> None:
        run_id_ctx = current_run_id()
        if not run_id_ctx:
            self._start_times.pop(run_id, None)
            self._prompts.pop(run_id, None)
            return
        try:
            started = self._start_times.pop(run_id, None)
            duration_ms = (
                int((time.monotonic() - started) * 1000) if started else 0
            )
            response_text = ""
            try:
                gens = response.generations
                if gens and gens[0]:
                    gen = gens[0][0]
                    # Primary path: .text (works for string content in
                    # current langchain; may return "" for list content
                    # in older versions)
                    response_text = getattr(gen, "text", "") or ""
                    # Fallback: extract from message.content
                    if not response_text:
                        msg = getattr(gen, "message", None)
                        if msg:
                            content = getattr(msg, "content", "")
                            if isinstance(content, str):
                                response_text = content
                            elif isinstance(content, list):
                                parts: list[str] = []
                                for block in content:
                                    if isinstance(block, str):
                                        parts.append(block)
                                    elif isinstance(block, dict):
                                        parts.append(
                                            _extract_block_text(block)
                                        )
                                response_text = "".join(parts)
                    # Last resort: stringify the generation
                    if not response_text:
                        response_text = str(gen)[:2000]
            except Exception as extract_err:
                logger.debug(
                    f"[tracing] response extraction failed: {extract_err}"
                )
            tokens = {}
            try:
                raw = response.llm_output or {}
                # ChatAnthropic uses input_tokens/output_tokens; others use prompt/completion
                u = raw.get("usage") or raw.get("token_usage") or {}
                p = (
                    u.get("prompt_tokens")
                    or u.get("input_tokens")
                    or 0
                )
                c = (
                    u.get("completion_tokens")
                    or u.get("output_tokens")
                    or 0
                )
                tokens = {
                    "prompt": p,
                    "completion": c,
                    "total": u.get("total_tokens") or (p + c),
                }
            except Exception:
                pass
            from src.infra.database.tracing.repository import (
                create_tracing_repository,
            )
            create_tracing_repository().add_llm_call(
                run_id=run_id_ctx,
                step_node=current_step_node() or "",
                agent_name=self.agent_name,
                prompt=self._prompts.pop(run_id, ""),
                response=response_text,
                tokens=tokens,
                duration_ms=duration_ms,
                status="success",
            )
            logger.info(
                f"[LLM] agent='{self.agent_name}' DONE "
                f"{duration_ms}ms tokens={tokens.get('total', 0)} "
                f"resp_len={len(response_text)}"
            )
            logger.debug(
                f"[LLM] response preview: {response_text[:200]}"
            )
        except Exception as e:
            logger.warning(f"[tracing] on_llm_end failed: {e}")

    def on_llm_error(
        self, error, *, run_id: UUID = None, **kwargs,
    ) -> None:
        run_id_ctx = current_run_id()
        if not run_id_ctx:
            self._start_times.pop(run_id, None)
            self._prompts.pop(run_id, None)
            return
        try:
            started = self._start_times.pop(run_id, None)
            duration_ms = (
                int((time.monotonic() - started) * 1000) if started else 0
            )
            from src.infra.database.tracing.repository import (
                create_tracing_repository,
            )
            create_tracing_repository().add_llm_call(
                run_id=run_id_ctx,
                step_node=current_step_node() or "",
                agent_name=self.agent_name,
                prompt=self._prompts.pop(run_id, ""),
                response="",
                tokens={},
                duration_ms=duration_ms,
                status="failed",
                error=str(error)[:2000],
            )
            logger.error(
                f"[LLM] agent='{self.agent_name}' FAILED "
                f"{duration_ms}ms error={str(error)[:200]}"
            )
        except Exception as e:
            logger.warning(f"[tracing] on_llm_error failed: {e}")


def make_llm_callback(agent_name: str = "") -> LLMCallback:
    """Factory used by langchain_adapter to attach a callback per agent model."""
    return LLMCallback(agent_name=agent_name)
