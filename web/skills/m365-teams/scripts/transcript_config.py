"""Tunable constants for Teams meeting transcripts. Adjust here, not inline."""
from __future__ import annotations
import os
from pathlib import Path

RECURRING_OCCURRENCES_CAP = 5
FULL_FETCH_TOKEN_THRESHOLD = 50_000
SEARCH_CONTEXT_SECONDS = 30

TRANSCRIPT_CACHE_DIR = Path(
    os.environ.get(
        "GATOR_TRANSCRIPT_CACHE_DIR",
        str(Path.home() / ".config" / "microsoft-graph" / "transcripts"),
    )
)


def ensure_cache_dir() -> Path:
    TRANSCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return TRANSCRIPT_CACHE_DIR


def estimate_tokens_from_vtt_bytes(byte_len: int) -> int:
    """Coarse estimate: ~3.5 chars per token for VTT speaker-attributed text."""
    return int(byte_len / 3.5)
