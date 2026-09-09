"""TraceRecorder — contextvar-scoped run/step/llm tracing (spec 4.1).

All record_* calls are wrapped in try/except so tracing NEVER blocks the
pipeline. current_run_id()/current_step_node() are read by the LLM callback.
"""
from __future__ import annotations

import contextvars
import uuid
from typing import Any, Optional

from loguru import logger

_run_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_run_id", default=None
)
_step_node_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_step_node", default=None
)
_seq_counter: contextvars.ContextVar[int] = contextvars.ContextVar(
    "trace_seq", default=0
)


def current_run_id() -> Optional[str]:
    return _run_id_var.get()


def set_run_id(run_id: Optional[str]) -> None:
    """Set current run_id in the contextvar (for background threads)."""
    _run_id_var.set(run_id)


def current_step_node() -> Optional[str]:
    return _step_node_var.get()


def _next_seq() -> int:
    n = _seq_counter.get() + 1
    _seq_counter.set(n)
    return n


def _truncate(obj: Any, limit: int = 1500) -> str:
    try:
        s = str(obj)
        return s[:limit] + ("...(truncated)" if len(s) > limit else "")
    except Exception:
        return "<unrepr>"


def record_run_start(pipeline: str, topic: str = "") -> Optional[str]:
    """Start a run, set contextvar. Returns run_id (or None on failure)."""
    try:
        from src.infra.database.tracing.repository import (
            create_tracing_repository,
        )
        run_id = uuid.uuid4().hex
        create_tracing_repository().create_run(
            run_id=run_id, pipeline=pipeline, topic=topic, status="running",
        )
        _run_id_var.set(run_id)
        _seq_counter.set(0)
        return run_id
    except Exception as e:
        logger.warning(f"[tracing] record_run_start failed: {e}")
        return None


def record_run_end(
    run_id: Optional[str], status: str, draft_id: Optional[int] = None,
    error: Optional[str] = None, duration_ms: int = 0,
) -> None:
    if not run_id:
        return
    try:
        from src.infra.database.tracing.repository import (
            create_tracing_repository,
        )
        create_tracing_repository().end_run(
            run_id=run_id, status=status, draft_id=draft_id,
            error=error, duration_ms=duration_ms,
        )
    except Exception as e:
        logger.warning(f"[tracing] record_run_end failed: {e}")


def record_step_start(
    run_id: Optional[str], node: str, input_summary: Any,
) -> Optional[int]:
    """Record step start; set contextvar.step_node so the LLM callback
    can attribute its calls to this node."""
    if not run_id:
        return None
    try:
        from src.infra.database.tracing.repository import (
            create_tracing_repository,
        )
        _step_node_var.set(node)
        seq = _next_seq()
        step_id = create_tracing_repository().create_step(
            run_id=run_id, node=node, seq=seq,
            input_summary={"value": _truncate(input_summary)},
        )
        return step_id
    except Exception as e:
        logger.warning(f"[tracing] record_step_start failed: {e}")
        return None


def record_step_end(
    run_id: Optional[str], node: str, status: str, output_summary: Any,
    duration_ms: int, error: Optional[str] = None,
) -> None:
    if not run_id:
        return
    try:
        from src.infra.database.tracing.repository import (
            create_tracing_repository,
        )
        create_tracing_repository().end_step(
            run_id=run_id, node=node, status=status,
            output_summary={"value": _truncate(output_summary)},
            duration_ms=duration_ms, error=error,
        )
    except Exception as e:
        logger.warning(f"[tracing] record_step_end failed: {e}")
