"""In-memory session store for the agentic setup wizard.

One session per open wizard. Holds the draft config (left pane state) and an
event queue (frontend polls). No persistence — closing the wizard discards
the session per spec section 9.
"""
from __future__ import annotations

import threading
import uuid
from typing import Any


class SessionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}

    def create(self, extension_type: str, initial: dict | None = None) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = {
                "extension_type": extension_type,
                "draft": dict(initial or {}),
                "events": [],
            }
        return sid

    def get(self, sid: str) -> dict:
        with self._lock:
            if sid not in self._sessions:
                raise KeyError(f"Unknown session: {sid}")
            return dict(self._sessions[sid]["draft"])

    def set(self, sid: str, field_path: str, value: Any) -> None:
        with self._lock:
            if sid not in self._sessions:
                raise KeyError(f"Unknown session: {sid}")
            self._sessions[sid]["draft"][field_path] = value
            self._sessions[sid]["events"].append(
                {"type": "field_update", "field_path": field_path, "value": value}
            )

    def merge(self, sid: str, fields: dict) -> None:
        """Merge multiple fields into the draft at once (no per-field events)."""
        with self._lock:
            if sid not in self._sessions:
                raise KeyError(f"Unknown session: {sid}")
            self._sessions[sid]["draft"].update(fields)

    def extension_type(self, sid: str) -> str:
        with self._lock:
            return self._sessions[sid]["extension_type"]

    def emit(self, sid: str, event: dict) -> None:
        with self._lock:
            self._sessions[sid]["events"].append(event)

    def drain_events(self, sid: str) -> list[dict]:
        with self._lock:
            if sid not in self._sessions:
                raise KeyError(f"Unknown session: {sid}")
            evs = self._sessions[sid]["events"]
            self._sessions[sid]["events"] = []
            return evs

    def discard(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)
