"""Persisted remote-control state: last processed message id, ids Gator itself posted, chat window,
and each channel's lanes (one remote session per project, live, sleeping or failed)."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

_log = logging.getLogger(__name__)

POSTED_IDS_KEEP = 200
LANE_STATES = ("live", "sleeping", "failed")


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

    def lanes(self, channel: str) -> dict[str, dict]:
        """The channel's lanes by project id. A lane is the project's one remote session, live or
        asleep; it outlives the process and a backend restart."""
        with self._lock:
            stored = (self._load().get(channel) or {}).get("lanes")
        if not isinstance(stored, dict):
            return {}
        return {pid: lane for pid, lane in stored.items() if _valid_lane(pid, lane)}

    def put_lane(self, channel: str, lane: dict) -> None:
        """Adds the lane, or replaces the one the project already has: never two per project."""
        with self._lock:
            data = self._load()
            entry = self._channel(data, channel)
            lanes = entry.get("lanes")
            if not isinstance(lanes, dict):
                lanes = entry["lanes"] = {}
            if lanes.get(lane["project_id"]) != lane:
                lanes[lane["project_id"]] = lane
                self._save(data)

    def drop_lane(self, channel: str, project_id: str) -> None:
        with self._lock:
            data = self._load()
            lanes = self._channel(data, channel).get("lanes")
            if isinstance(lanes, dict) and lanes.pop(project_id, None) is not None:
                self._save(data)


def _valid_lane(project_id: str, lane) -> bool:
    return (
        isinstance(lane, dict)
        and lane.get("project_id") == project_id
        and all(isinstance(lane.get(k), str) and lane[k] for k in ("pty_id", "short", "repo_path"))
        and lane.get("state") in LANE_STATES
    )
