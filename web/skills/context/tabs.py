"""Server-side tab registry.

Mirrors the client's tab list (id ↔ name) so server-side code can resolve
tab names — needed for cross-tab queries from the LLM and for binding
scheduled jobs to a tab. Client is authoritative; server stores the latest
snapshot pushed via /api/tabs.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from threading import Lock

_TABS_FILE = Path.home() / ".config" / "gator" / "tabs.json"
_lock = Lock()


def _load() -> dict[str, dict]:
    try:
        if _TABS_FILE.exists():
            data = json.loads(_TABS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save(data: dict[str, dict]) -> None:
    try:
        _TABS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TABS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# {context_id: {"name": str, "updated_at": float}}
_tabs: dict[str, dict] = _load()


def sync(tab_list: list[dict]) -> dict:
    """Replace the registry with the client's current tab list.

    Each tab dict must have 'id' and 'name'. Tabs absent from the list are
    removed from the registry (the client deleted them).
    """
    now = time.time()
    with _lock:
        new_tabs: dict[str, dict] = {}
        for t in tab_list:
            tid = t.get("id")
            name = t.get("name") or t.get("title") or ""
            if tid:
                new_tabs[tid] = {"name": name, "updated_at": now}
        _tabs.clear()
        _tabs.update(new_tabs)
        _save(_tabs)
    return {"synced": len(_tabs)}


def list_tabs() -> list[dict]:
    with _lock:
        return [{"context_id": cid, "name": v["name"]} for cid, v in _tabs.items()]


def resolve_name(name: str) -> str | None:
    """Resolve a tab display name (case-insensitive, exact match) to context_id.

    Returns None if not found. If multiple tabs share a name, returns the
    most recently updated.
    """
    if not name:
        return None
    target = name.strip().lower()
    with _lock:
        candidates = [(cid, v) for cid, v in _tabs.items()
                      if v["name"].strip().lower() == target]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1].get("updated_at", 0), reverse=True)
    return candidates[0][0]


def get_name(context_id: str) -> str | None:
    with _lock:
        v = _tabs.get(context_id)
        return v["name"] if v else None
