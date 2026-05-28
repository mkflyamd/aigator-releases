"""Serve output files produced by the code_runner skill."""

import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import OUTPUTS_DIR

router = APIRouter()

_MAX_AGE_SECONDS = 24 * 3600  # 24 hours


def _safe_output_path(run_id: str, filename: str) -> Path:
    """Resolve path and assert it stays under OUTPUTS_DIR."""
    candidate = (OUTPUTS_DIR / run_id / filename).resolve()
    if not str(candidate).startswith(str(OUTPUTS_DIR.resolve())):
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
            except Exception:
                pass


@router.get("/api/files/{run_id}/{filename}")
async def serve_output_file(run_id: str, filename: str):
    try:
        path = _safe_output_path(run_id, filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)
