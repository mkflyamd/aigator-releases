"""Persisted remote-control state: last processed message id, ids Gator itself posted, chat window."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

_log = logging.getLogger(__name__)

POSTED_IDS_KEEP = 200
MASTER_KEY = "master"


def default_path() -> Path:
    return Path.home() / ".gator" / "remote_control_state.json"


class State:
    """One JSON file. A process shares one instance (`shared()`), so the lock covers every writer."""

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

    def channel_value(self, channel: str, key: str):
        with self._lock:
            return (self._load().get(channel) or {}).get(key)

    def set_channel_value(self, channel: str, key: str, value) -> None:
        with self._lock:
            data = self._load()
            self._channel(data, channel)[key] = value
            self._save(data)

    def master(self) -> dict | None:
        with self._lock:
            value = self._load().get(MASTER_KEY)
        return value if isinstance(value, dict) else None

    def set_master(self, record: dict | None) -> None:
        with self._lock:
            data = self._load()
            if record is None:
                data.pop(MASTER_KEY, None)
            else:
                data[MASTER_KEY] = record
            self._save(data)

    def mark_master_seen(self, armed_at: float, now: float) -> None:
        """Records the latest clock reading on the window that was armed at `armed_at`; a window
        that was closed or replaced in the meantime is left alone."""
        with self._lock:
            data = self._load()
            record = data.get(MASTER_KEY)
            if isinstance(record, dict) and record.get("armed_at") == armed_at:
                record["seen"] = now
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


_shared: State | None = None
_shared_lock = threading.Lock()


def shared() -> State:
    """The process-wide state: the loops and the routes must write through the same lock."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = State()
        return _shared
