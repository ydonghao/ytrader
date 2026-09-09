"""Shared helpers for agent nodes: prompt rendering, error wrapping."""
import time
from typing import Any, Callable, Coroutine
from functools import wraps
from loguru import logger
from jinja2 import Template


def render_prompt(template_str: str, **variables: Any) -> str:
    """Render a Jinja2 prompt template with the given variables."""
    return Template(template_str).render(**variables)


def load_prompt_from_db(template_name: str) -> str:
    """Load prompt template text from DB by name.

    Returns the raw template string (not yet rendered).
    Raises ValueError if template not found.
    """
    from src.infra.database.agent.repository import create_agent_repository

    repo = create_agent_repository()
    tmpl = repo.get_prompt_template_by_name(template_name)
    if not tmpl:
        raise ValueError(f"Prompt template '{template_name}' not found")
    return tmpl.template


def load_prompt_from_db_or(template_name: str, fallback: str) -> str:
    """Load a prompt template by name, returning ``fallback`` if absent.

    Thin convenience over :func:`load_prompt_from_db` for call sites that
    keep an inline default (e.g. user-prompt strings). Existing rows —
    including user edits made via the Prompt console — are still honoured.
    """
    try:
        return load_prompt_from_db(template_name)
    except ValueError:
        return fallback


def agent_node(func: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
    """Decorator: wraps agent node with error handling, logging, and tracing.

    Catches exceptions, appends to state['errors'], and returns
    a safe partial state so the pipeline can continue. If a trace run is
    active (contextvar), records step start/end (input/output/duration/status).
    """

    @wraps(func)
    async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
        node_name = func.__name__
        node_short = node_name.replace("_node", "")
        from src.infra.tracing.recorder import (
            current_run_id,
            record_step_start,
            record_step_end,
        )
        from src.infra.tracing.run_registry import is_cancelled
        run_id = current_run_id()

        # 协作式取消：节点边界检查令牌。若 run 已被请求停止，跳过本节点，
        # 返回 cancelled partial state，让上游（LangGraph / 多选题循环）收尾。
        # 注意：这不会打断正在进行中的 LLM 调用——上一个节点的调用会跑完，
        # 这里只是阻止进入下一个节点。
        if is_cancelled(run_id):
            logger.info(f"[agent] {node_name} skipped (run cancelled)")
            return {
                "errors": [f"{node_name}: skipped (run cancelled)"],
                "processing_steps": [f"{node_name}: CANCELLED"],
            }

        if run_id:
            record_step_start(run_id, node_short, _brief_state(state))
        start_t = time.monotonic()
        try:
            logger.debug(f"[agent] {node_name} started")
            result = await func(state)
            logger.debug(f"[agent] {node_name} completed")
            if run_id:
                record_step_end(
                    run_id, node_short, "success",
                    _brief_result(result),
                    int((time.monotonic() - start_t) * 1000),
                )
            return result
        except Exception as e:
            error_msg = f"{node_name}: {type(e).__name__}: {e}"
            logger.error(f"[agent] {error_msg}")
            if run_id:
                record_step_end(
                    run_id, node_short, "failed", None,
                    int((time.monotonic() - start_t) * 1000),
                    error=str(e),
                )
            return {
                "errors": [error_msg],
                "processing_steps": [f"{node_name}: FAILED"],
            }

    return wrapper


def _brief_state(state: Any) -> dict:
    """Brief summary of node input state (avoid huge payload in trace)."""
    try:
        return {
            "topic": state.get("topic"),
            "candidate_news_count": len(
                state.get("candidate_news", []) or []
            ),
            "has_material": bool(state.get("material")),
            "title": (state.get("title") or "")[:120],
            "skip_topic_discovery": state.get("skip_topic_discovery"),
        }
    except Exception:
        return {}


def _brief_result(result: Any) -> dict:
    """Brief summary of node output (avoid huge payload in trace)."""
    try:
        if not isinstance(result, dict):
            return {}
        return {
            "keys": list(result.keys()),
            "title": (result.get("title") or "")[:120],
            "error_count": len(result.get("errors", []) or []),
        }
    except Exception:
        return {}


def truncate_content(content: str, max_chars: int = 3000) -> str:
    """Pass-through — no truncation. 1M context model handles full content.

    Kept as a no-op to avoid breaking callers. Will be removed later.
    """
    return content
