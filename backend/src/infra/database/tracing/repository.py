"""Tracing repository — persist & query agent run / step / llm-call."""
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from src.infra.database.tracing.entity import (
    AgentRunTable,
    AgentRunStepTable,
    AgentRunLlmTable,
)
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn

_db_connection: Optional[DBConnection] = None
_db_lock = threading.Lock()


def _get_db() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def _iso(dt):
    return dt.isoformat() if dt else None


class TracingRepository:
    def __init__(self, db: DBConnection | None = None) -> None:
        self._db = db or _get_db()

    # ── run ──
    def create_run(
        self, run_id: str, pipeline: str, topic: str = "", status: str = "running",
    ) -> int:
        with self._db.session_scope() as s:
            row = AgentRunTable(
                run_id=run_id, pipeline=pipeline, topic=topic, status=status,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def end_run(
        self, run_id: str, status: str, draft_id: Optional[int] = None,
        error: Optional[str] = None, duration_ms: int = 0,
    ) -> None:
        with self._db.session_scope() as s:
            row = s.exec(
                select(AgentRunTable).where(AgentRunTable.run_id == run_id)
            ).first()
            if row:
                row.status = status
                row.ended_at = datetime.now(timezone.utc)
                row.duration_ms = duration_ms
                if draft_id is not None:
                    row.draft_id = draft_id
                if error:
                    row.error = error[:2000]
                s.add(row)
                s.commit()

    # ── step ──
    def create_step(
        self, run_id: str, node: str, seq: int,
        input_summary: Any, status: str = "running",
    ) -> int:
        with self._db.session_scope() as s:
            row = AgentRunStepTable(
                run_id=run_id, node=node, seq=seq, status=status,
                input=input_summary or {},
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def end_step(
        self, run_id: str, node: str, status: str, output_summary: Any,
        duration_ms: int, error: Optional[str] = None,
    ) -> Optional[int]:
        with self._db.session_scope() as s:
            row = s.exec(
                select(AgentRunStepTable)
                .where(AgentRunStepTable.run_id == run_id,
                       AgentRunStepTable.node == node)
                .order_by(AgentRunStepTable.id.desc())
            ).first()
            if row:
                row.status = status
                row.output = output_summary or {}
                row.duration_ms = duration_ms
                row.ended_at = datetime.now(timezone.utc)
                if error:
                    row.error = error[:2000]
                s.add(row)
                s.commit()
                return row.id
            return None

    # ── llm call ──
    def add_llm_call(
        self, run_id: str, step_node: str, agent_name: str, prompt: str,
        response: str, tokens: dict, duration_ms: int, status: str,
        error: Optional[str] = None,
    ) -> int:
        with self._db.session_scope() as s:
            row = AgentRunLlmTable(
                run_id=run_id, step_node=step_node, agent_name=agent_name,
                # prompt is already section-capped in the LLM callback
                # (system generous, user whole); response gets the same
                # generous bound so structured cluster JSON isn't cut.
                prompt=prompt or "",
                response=(response or "")[:50000],
                tokens_prompt=tokens.get("prompt", 0),
                tokens_completion=tokens.get("completion", 0),
                tokens_total=tokens.get("total", 0),
                duration_ms=duration_ms, status=status,
                error=(error[:2000] if error else None),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    # ── query ──
    def get_run_trace(self, run_id: str) -> dict:
        with self._db.session_scope() as s:
            run = s.exec(
                select(AgentRunTable).where(AgentRunTable.run_id == run_id)
            ).first()
            steps = s.exec(
                select(AgentRunStepTable)
                .where(AgentRunStepTable.run_id == run_id)
                .order_by(AgentRunStepTable.seq)
            ).all()
            llms = s.exec(
                select(AgentRunLlmTable)
                .where(AgentRunLlmTable.run_id == run_id)
                .order_by(AgentRunLlmTable.id)
            ).all()
            return {
                "run": _run_dict(run) if run else None,
                "steps": [_step_dict(st) for st in steps],
                "llm_calls": [_llm_dict(lm) for lm in llms],
            }

    def list_runs(
        self, pipeline: str | None = None, limit: int = 50,
    ) -> list[dict]:
        """List recent agent runs, newest first, with step/llm counts."""
        with self._db.session_scope() as s:
            q = select(AgentRunTable)
            if pipeline:
                q = q.where(AgentRunTable.pipeline == pipeline)
            q = q.order_by(AgentRunTable.started_at.desc()).limit(limit)
            runs = s.exec(q).all()
            # Batch-count steps + llms per run
            run_ids = [r.run_id for r in runs]
            step_counts: dict[str, int] = {}
            llm_counts: dict[str, int] = {}
            if run_ids:
                from sqlalchemy import func
                step_rows = s.exec(
                    select(
                        AgentRunStepTable.run_id,
                        func.count(AgentRunStepTable.id),
                    )
                    .where(AgentRunStepTable.run_id.in_(run_ids))
                    .group_by(AgentRunStepTable.run_id)
                ).all()
                step_counts = {rid: cnt for rid, cnt in step_rows}
                llm_rows = s.exec(
                    select(
                        AgentRunLlmTable.run_id,
                        func.count(AgentRunLlmTable.id),
                    )
                    .where(AgentRunLlmTable.run_id.in_(run_ids))
                    .group_by(AgentRunLlmTable.run_id)
                ).all()
                llm_counts = {rid: cnt for rid, cnt in llm_rows}
            result = []
            for r in runs:
                d = _run_dict(r)
                d["step_count"] = step_counts.get(r.run_id, 0)
                d["llm_call_count"] = llm_counts.get(r.run_id, 0)
                result.append(d)
            return result


def _run_dict(r: AgentRunTable) -> dict:
    return {
        "run_id": r.run_id, "pipeline": r.pipeline, "topic": r.topic,
        "status": r.status, "draft_id": r.draft_id,
        "started_at": _iso(r.started_at), "ended_at": _iso(r.ended_at),
        "duration_ms": r.duration_ms, "error": r.error,
    }


def _step_dict(s: AgentRunStepTable) -> dict:
    return {
        "node": s.node, "seq": s.seq, "status": s.status,
        "input": s.input, "output": s.output, "duration_ms": s.duration_ms,
        "started_at": _iso(s.started_at), "ended_at": _iso(s.ended_at),
        "error": s.error,
    }


def _llm_dict(l: AgentRunLlmTable) -> dict:
    return {
        "step_node": l.step_node, "agent_name": l.agent_name,
        "prompt": l.prompt, "response": l.response,
        "tokens_prompt": l.tokens_prompt,
        "tokens_completion": l.tokens_completion,
        "tokens_total": l.tokens_total, "duration_ms": l.duration_ms,
        "status": l.status, "error": l.error,
    }


def create_tracing_repository(db: DBConnection | None = None) -> TracingRepository:
    return TracingRepository(db)
