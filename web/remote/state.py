"""Persisted remote-control state: last processed message id, ids Gator itself posted, chat window."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

_log = logging.getLogger(__name__)

POSTED_IDS_KEEP = 200
PROMPT_MESSAGES_KEEP = 50


def default_path() -> Path:
    return Path.home() / ".gator" / "remote_control_state.json"


class State:
    def __init__(self, path: Path | None = None):
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path or default_path()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)

    def _channel(self, data: dict, channel: str) -> dict:
        entry = data.setdefault(channel, {})
        return entry if isinstance(entry, dict) else data.setdefault(channel, {})

    def last_id(self, channel: str) -> str | None:
        with self._lock:
            value = (self._load().get(channel) or {}).get("last_id")
        return value if isinstance(value, str) else None

    def set_last_id(self, channel: str, message_id: str) -> None:
        with self._lock:
            data = self._load()
            self._channel(data, channel)["last_id"] = message_id
            self._save(data)

    def disarmed(self, channel: str) -> bool:
        with self._lock:
            return (self._load().get(channel) or {}).get("disarmed") is True

    def set_disarmed(self, channel: str, value: bool) -> None:
        with self._lock:
            data = self._load()
            self._channel(data, channel)["disarmed"] = value
            self._save(data)

    def window(self, channel: str) -> tuple[float, float] | None:
        """(opened_at, until) of the chat window, or None when it is closed."""
        with self._lock:
            value = (self._load().get(channel) or {}).get("window")
        if not isinstance(value, dict):
            return None
        opened, until = value.get("opened_at"), value.get("until")
        if isinstance(opened, (int, float)) and isinstance(until, (int, float)):
            return float(opened), float(until)
        return None

    def set_window(self, channel: str, opened_at: float, until: float) -> None:
        with self._lock:
            data = self._load()
            self._channel(data, channel)["window"] = {"opened_at": opened_at, "until": until}
            self._save(data)

    def clear_window(self, channel: str) -> None:
        with self._lock:
            data = self._load()
            entry = self._channel(data, channel)
            if entry.pop("window", None) is not None:
                self._save(data)

    def record_post(self, channel: str, message_id: str) -> None:
        with self._lock:
            data = self._load()
            entry = self._channel(data, channel)
            ids = [i for i in entry.get("posted_ids", []) if i != message_id]
            ids.append(message_id)
            entry["posted_ids"] = ids[-POSTED_IDS_KEEP:]
            self._save(data)

    def is_own_post(self, channel: str, message_id: str) -> bool:
        with self._lock:
            ids = (self._load().get(channel) or {}).get("posted_ids", [])
        return message_id in ids

    def record_prompt_message(
        self, channel: str, message_id: str, session_id: str, prompt_id: str, expires_at: float, now: float
    ) -> None:
        """Which posted message asked which session's prompt, so a reply to that message reaches that session."""
        with self._lock:
            data = self._load()
            entry = self._channel(data, channel)
            kept = [
                m
                for m in entry.get("prompt_messages", [])
                if isinstance(m, dict) and m.get("expires_at", 0) > now and m.get("message_id") != message_id
            ]
            kept.append(
                {"message_id": message_id, "session_id": session_id, "prompt_id": prompt_id, "expires_at": expires_at}
            )
            entry["prompt_messages"] = kept[-PROMPT_MESSAGES_KEEP:]
            self._save(data)

    def clear_prompt_messages(self, channel: str, session_id: str) -> None:
        with self._lock:
            data = self._load()
            entry = self._channel(data, channel)
            before = entry.get("prompt_messages", [])
            after = [m for m in before if not (isinstance(m, dict) and m.get("session_id") == session_id)]
            if len(after) != len(before):
                closed_at = time.time()
                gone = [
                    {**m, "closed_at": closed_at}
                    for m in before
                    if isinstance(m, dict) and m.get("session_id") == session_id
                ]
                entry["prompt_messages"] = after
                entry["prompt_closed"] = [*entry.get("prompt_closed", []), *gone][-PROMPT_MESSAGES_KEEP:]
                self._save(data)

    def prompt_messages(self, channel: str) -> list[dict]:
        with self._lock:
            found = (self._load().get(channel) or {}).get("prompt_messages", [])
        return [m for m in found if isinstance(m, dict)]

    def recently_closed_prompt_messages(self, channel: str, since: float) -> list[dict]:
        """Prompt messages whose prompt closed after `since` (unix seconds), for replies that still arrive."""
        with self._lock:
            found = (self._load().get(channel) or {}).get("prompt_closed", [])
        return [m for m in found if isinstance(m, dict) and m.get("closed_at", 0) > since]

    def find_prompt_message(self, channel: str, message_id: str, now: float) -> tuple[dict, bool] | None:
        """The record for a posted prompt message and whether it is still open, or None when this chat
        never posted it or it has expired. A closed one is a prompt that has been answered or replaced."""
        with self._lock:
            entry = self._load().get(channel) or {}
            for key, is_open in (("prompt_messages", True), ("prompt_closed", False)):
                for m in entry.get(key, []):
                    if isinstance(m, dict) and m.get("message_id") == message_id and m.get("expires_at", 0) > now:
                        return dict(m), is_open
        return None

    def advance_reply_cursor(self, channel: str, message_id: str, reply_ts: str) -> None:
        """Remembers the newest reply read in the thread of a prompt message, so each reply is read once."""
        with self._lock:
            data = self._load()
            entry = self._channel(data, channel)
            for m in [*entry.get("prompt_messages", []), *entry.get("prompt_closed", [])]:
                if isinstance(m, dict) and m.get("message_id") == message_id:
                    m["reply_ts"] = reply_ts
                    self._save(data)
                    return
