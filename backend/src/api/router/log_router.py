"""
Logs Router — read-only system log viewer.
==========================================
GET /logs/files                 → list *.log files (size, mtime)
GET /logs/content               → static read w/ date + level filters + tail
GET /logs/stream                → SSE follow mode (real-time tail)

The backend logs under backend/logs/ are per-source files (app.log, error.log,
scheduler logs) rotated by size — not by date. Each log line embeds a timestamp
(e.g. "[2026-06-24 17:17:15] [INFO] ..."). "By date" is therefore implemented as
content filtering by the in-line timestamp, not by separate dated files.
"""
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.pkg import responses
from src.pkg.logging.logger import app_logger
from src.pkg.responses.sse import SseResponse

router = APIRouter(prefix="/logs", tags=["logs"])

# backend/logs/ — three parents up from this file (router → api → src → backend)
LOG_DIR: Path = Path(__file__).resolve().parents[3] / "logs"

# Match a leading date at the start of a log line. Handles both formats:
#   "[2026-06-24 17:17:15] [INFO] ..."   (current configured format)
#   "2026-06-24 17:17:15.137 | INFO ..."  (older loguru default)
_DATE_RE = re.compile(r"^[\[\{]?(\d{4}-\d{2}-\d{2})")
# Level token — matches "INFO", "WARNING", "ERROR", "DEBUG" anywhere in the line.
_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\b")

_MAX_TAIL = 5000
_DEFAULT_TAIL = 1000
_STREAM_INTERVAL = 1.0  # seconds between file-growth polls


def _resolve_file(name: str) -> Path:
    """Resolve a bare filename to a path inside LOG_DIR, guarding traversal."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="invalid file name")
    candidate = (LOG_DIR / name).resolve()
    # Ensure the resolved path is still inside LOG_DIR
    try:
        candidate.relative_to(LOG_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid file name")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"log file '{name}' not found")
    return candidate


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@router.get("/files")
def list_log_files():
    """List every *.log file under the logs directory, newest first."""
    if not LOG_DIR.is_dir():
        return responses.success(data=[])
    files = []
    for p in sorted(LOG_DIR.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True):
        st = p.stat()
        files.append({
            "name": p.name,
            "size_bytes": st.st_size,
            "size_human": _human_size(st.st_size),
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return responses.success(data=files)


def _iter_lines(path: Path):
    """Yield decoded lines from a file, lazily (memory-friendly)."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            yield line.rstrip("\n")


@router.get("/content")
def get_log_content(
    file: str = Query(..., description="log file name"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD filter; omit = latest lines"),
    level: Optional[str] = Query(None, description="DEBUG/INFO/WARNING/ERROR/CRITICAL"),
    tail: int = Query(_DEFAULT_TAIL, ge=1, le=_MAX_TAIL),
):
    """Return log lines for a file, optionally filtered by date and level.

    Date filtering keeps a "carry-over" date: lines without a timestamp
    (e.g. traceback continuations) inherit the last seen date so they stay
    grouped with their error.
    """
    path = _resolve_file(file)
    level_upper = level.upper() if level else None

    matching: list[str] = []
    cur_date: Optional[str] = None
    total_lines = 0

    for line in _iter_lines(path):
        total_lines += 1
        dm = _DATE_RE.match(line)
        if dm:
            cur_date = dm.group(1)
        line_date = cur_date  # may be None for pre-first-timestamp lines

        if date and line_date != date:
            continue
        if level_upper:
            lm = _LEVEL_RE.search(line)
            if not lm or lm.group(1).upper() != level_upper:
                continue
        matching.append(line)

    st = path.stat()
    truncated = len(matching) > tail
    out = matching[-tail:] if truncated else matching
    return responses.success(data={
        "file": file,
        "lines": out,
        "matched": len(matching),
        "shown": len(out),
        "truncated": truncated,
        "total_lines": total_lines,
        "size_bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    })


@router.get("/stream")
async def stream_log(
    file: str = Query(..., description="log file name"),
    tail: int = Query(200, ge=0, le=_MAX_TAIL),
):
    """SSE follow-mode: emit the last `tail` lines, then new lines as they arrive.

    Uses the project's SseResponse helper. Polls file size every ~1s; if the
    file shrinks (rotation), reopens from the start.
    """
    path = _resolve_file(file)

    async def event_generator():
        # 1) initial tail
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()
            for line in all_lines[-tail:]:
                yield SseResponse.message({"line": line.rstrip("\n")}).to_sse_string()
            offset = path.stat().st_size if path.exists() else 0
        except FileNotFoundError:
            offset = 0

        # 2) follow loop
        while True:
            await asyncio.sleep(_STREAM_INTERVAL)
            try:
                if not path.exists():
                    continue
                size = path.stat().st_size
                if size < offset:
                    # rotated / truncated → reopen from start
                    offset = 0
                if size == offset:
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(offset)
                    chunk = fh.read()
                    offset = fh.tell()
                for line in chunk.splitlines():
                    if line:
                        yield SseResponse.message({"line": line}).to_sse_string()
            except Exception as e:  # noqa: BLE001 — keep the stream alive
                app_logger.warning(f"[log_router] stream error on {file}: {e}")
                yield SseResponse.error(code=500, msg=str(e)).to_sse_string()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
