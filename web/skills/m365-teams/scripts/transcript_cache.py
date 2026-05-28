"""On-disk cache for transcript VTT content. One file per transcript_id."""
from __future__ import annotations
import os
import re
from pathlib import Path

from transcript_config import ensure_cache_dir

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _path_for(transcript_id: str) -> Path:
    if not _SAFE_ID.match(transcript_id):
        raise ValueError(f"unsafe transcript_id: {transcript_id!r}")
    return ensure_cache_dir() / f"{transcript_id}.vtt"


def read(transcript_id: str) -> str | None:
    p = _path_for(transcript_id)
    if not p.is_file():
        return None
    return p.read_bytes().decode("utf-8")


def write(transcript_id: str, vtt_text: str) -> Path:
    p = _path_for(transcript_id)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(vtt_text.encode("utf-8"))
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    tmp.replace(p)
    return p
