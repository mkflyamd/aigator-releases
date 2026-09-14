"""Serve output files produced by the code_runner skill and tool overflow store."""

import hmac
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import OUTPUTS_DIR

router = APIRouter()

_MAX_AGE_SECONDS = 24 * 3600  # 24 hours
_overflow_capabilities: dict[tuple[str, str], str] = {}


def register_overflow_file(run_id: str, filename: str, token: str) -> None:
    """Require ``token`` to download one sensitive tool-overflow artifact."""
    _overflow_capabilities[(run_id, filename)] = token


def _safe_output_path(run_id: str, filename: str) -> Path:
    """Resolve path and assert it stays under OUTPUTS_DIR."""
    candidate = (OUTPUTS_DIR / run_id / filename).resolve()
    try:
        candidate.relative_to(OUTPUTS_DIR.resolve())
    except ValueError:
        raise ValueError("Path escapes outputs directory")
    return candidate


def cleanup_old_outputs() -> None:
    """Delete output subdirectories older than 24 hours."""
    if not OUTPUTS_DIR.exists():
        return
    cutoff = time.time() - _MAX_AGE_SECONDS
    for run_dir in OUTPUTS_DIR.iterdir():
        if run_dir.is_dir() and run_dir.stat().st_mtime < cutoff:
            try:
                shutil.rmtree(run_dir)
                for key in [key for key in _overflow_capabilities if key[0] == run_dir.name]:
                    _overflow_capabilities.pop(key, None)
            except Exception:
                pass


@router.get("/api/files/{run_id}/{filename}")
async def serve_output_file(run_id: str, filename: str, token: str = ""):
    try:
        path = _safe_output_path(run_id, filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    required_token = _overflow_capabilities.get((run_id, filename))
    # Overflow files are always named tool_output.txt. If the process has
    # restarted, their in-memory capabilities are intentionally unavailable;
    # fail closed instead of exposing a private file for its remaining TTL.
    if filename == "tool_output.txt" and required_token is None:
        raise HTTPException(status_code=403, detail="Download capability expired")
    if required_token and not hmac.compare_digest(token, required_token):
        raise HTTPException(status_code=403, detail="Invalid download capability")
    return FileResponse(path, filename=filename)
