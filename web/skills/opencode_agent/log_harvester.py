"""Harvest OpenCode's own structured log for connection/stream failures and
mirror them into AiGator's server log.

Why this exists (issue #156): OpenCode's LLM calls happen inside the opencode
subprocess and talk to the gateway directly, so their failures never surface
as HTTP errors to AiGator — they only appear in OpenCode's own log
(``~/.local/share/opencode/log/opencode.log``) as structured lines like::

    level=ERROR ... message="stream error" providerID=gator-gateway
      modelID=GLM-5.2-FP8 ... error.error="AI_APICallError: ...GatewayTimeout.
      Reason: stream timeout"

An earlier client-side beacon tried to detect these by regex-matching the
TUI's rendered error text, but that only caught two hard-coded phrasings and
missed everything else (e.g. the GatewayTimeout / "Error while copying content
to a stream" cases). Reading OpenCode's *structured* log instead is reliable
and complete — no guessing at TUI rendering — so it replaced the beacon.

Design: a lightweight forward-only tail. On startup the offset is seeked to
the current end of the file (we don't replay historical errors); each poll
reads the newly-appended bytes, extracts the error lines, and logs a concise
one-liner. Handles truncation/rotation by resetting the offset when the file
shrinks below it.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

_log = logging.getLogger(__name__)

HARVEST_INTERVAL_SECONDS = 20

# Only these ERROR shapes are connectivity/stream failures worth surfacing.
_STREAM_ERROR = 'message="stream error"'
_MODELS_DEV = "Failed to fetch models.dev"

_RX_PROVIDER = re.compile(r"providerID=(\S+)")
_RX_MODEL = re.compile(r"modelID=(\S+)")
_RX_SESSION = re.compile(r"session\.id=(\S+)")
_RX_TS = re.compile(r"timestamp=(\S+)")
# error.error value can itself contain quotes; grab through the final quote.
_RX_ERR = re.compile(r'error\.error="(.*)"')

_offset: int = 0


def _log_path() -> Path:
    """Resolve OpenCode's log file, honoring XDG_DATA_HOME (OpenCode uses the
    XDG data dir on all platforms, including Windows)."""
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "opencode" / "log" / "opencode.log"


def init_offset() -> None:
    """Seek to the current end of the log so we surface only NEW failures, not
    the whole backlog. Best-effort: if the file doesn't exist yet, start at 0
    and the first harvest picks up from the beginning once OpenCode creates it."""
    global _offset
    try:
        p = _log_path()
        _offset = p.stat().st_size if p.exists() else 0
    except Exception:
        _offset = 0


def harvest_stream_errors() -> int:
    """Read newly-appended log lines, mirror any connectivity/stream failures
    into the server log, and advance the offset. Returns the count surfaced
    (0 on any error or when nothing new). SYNC — call via asyncio.to_thread."""
    global _offset
    try:
        p = _log_path()
        if not p.exists():
            return 0
        size = p.stat().st_size
        if size < _offset:
            # Truncated/rotated — start over from the top of the new file.
            _offset = 0
        if size == _offset:
            return 0
        with p.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(_offset)
            chunk = f.read()
            _offset = f.tell()
    except Exception as exc:
        _log.debug("[opencode][harvest] read failed: %s", exc)
        return 0

    count = 0
    for line in chunk.splitlines():
        if "level=ERROR" not in line:
            continue
        is_stream = _STREAM_ERROR in line
        is_models_dev = _MODELS_DEV in line
        if not (is_stream or is_models_dev):
            continue
        ts = _first(_RX_TS, line)
        if is_models_dev:
            _log.warning(
                "[opencode][stream-error] ts=%s kind=models.dev "
                "(OpenCode couldn't reach models.dev — usually a corp-network "
                "block of the model catalog, cosmetic)", ts,
            )
        else:
            _log.warning(
                "[opencode][stream-error] ts=%s kind=api provider=%s model=%s session=%s error=%s",
                ts, _first(_RX_PROVIDER, line), _first(_RX_MODEL, line),
                _first(_RX_SESSION, line), _first(_RX_ERR, line)[:300],
            )
        count += 1
    return count


def _first(rx: re.Pattern, line: str) -> str:
    m = rx.search(line)
    return m.group(1) if m else "?"
