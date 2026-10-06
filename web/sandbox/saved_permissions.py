"""Permissions the user saved with "Always allow this".

Kept in the encrypted credential store, not in a file: the file tools can write
anywhere, so a plain file would let a tricked model grant itself access. An
unreadable, malformed or unknown-version blob means no saved permissions.
Created only by the CSRF-guarded approve route; removed only by the Settings routes.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid

from .paths import paths_covered

_NAME = "sandbox/saved-permissions"
_VERSION = 1
_LOCK = threading.Lock()
_log = logging.getLogger(__name__)


def _valid(entry) -> bool:
    if not (isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("network"), bool)
            and isinstance(entry.get("created"), (int, float)) and not isinstance(entry["created"], bool)):
        return False
    for key in ("read_paths", "write_paths", "programs"):
        if not isinstance(entry.get(key), list) or not all(isinstance(v, str) and v for v in entry[key]):
            return False
    return all(os.path.isabs(p) for k in ("read_paths", "write_paths") for p in entry[k])


def _load() -> list[dict] | None:
    """The valid entries; [] when nothing is stored; None when the store is unreadable or not ours."""
    try:
        import secure_store
        data = secure_store.get_json(_NAME)
    except Exception as exc:
        _log.warning("saved permissions unreadable (%s); treating as none", type(exc).__name__)
        return None
    if data is None:
        return []
    if not isinstance(data, dict) or data.get("version") != _VERSION or not isinstance(data.get("entries"), list):
        return None
    return [e for e in data["entries"] if _valid(e)]


def list_entries() -> list[dict]:
    return _load() or []


def _save(entries: list[dict]) -> None:
    import secure_store
    secure_store.set_json(_NAME, {"version": _VERSION, "entries": entries})


def add(read, write, network: bool, programs) -> dict:
    entry = {
        "id": uuid.uuid4().hex,
        "read_paths": sorted({str(p) for p in read}),
        "write_paths": sorted({str(p) for p in write}),
        "network": bool(network),
        "programs": sorted({str(p) for p in programs}) if network else [],
        "created": time.time(),
    }
    with _LOCK:
        entries = _load()
        if entries is None:
            raise RuntimeError("saved permissions are unreadable; not overwriting them")
        for existing in entries:
            if all(existing[k] == entry[k] for k in ("read_paths", "write_paths", "network", "programs")):
                return existing
        _save(entries + [entry])
    return entry


def covers(read, write, hosts, programs) -> bool:
    entries = list_entries()
    if not entries:
        return False
    if not hosts:
        granted_read = [p for e in entries for p in e["read_paths"]]
        granted_write = [p for e in entries for p in e["write_paths"]]
        return paths_covered(read, write, granted_read, granted_write)
    wanted = set(programs or ())
    if not wanted:
        return False
    return any(e["network"] and wanted <= set(e["programs"])
               and paths_covered(read, write, e["read_paths"], e["write_paths"]) for e in entries)


def remove(entry_id: str) -> bool:
    with _LOCK:
        entries = _load()
        if entries is None:
            return False
        kept = [e for e in entries if e["id"] != entry_id]
        if len(kept) == len(entries):
            return False
        _save(kept)
    return True


def remove_all() -> None:
    with _LOCK:
        _save([])


def describe(entry: dict) -> str:
    parts = []
    if entry["write_paths"]:
        parts.append("Write to " + ", ".join(entry["write_paths"]))
    if entry["read_paths"]:
        parts.append("Read from " + ", ".join(entry["read_paths"]))
    if entry["network"]:
        parts.append("Use the network with: " + ", ".join(sorted(entry["programs"])))
    return "; ".join(parts) or "No access"
