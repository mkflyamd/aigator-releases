"""Universal context pinning — shared across all skills, scoped per tab (context_id).
Persisted to disk so pins survive server restarts."""

from __future__ import annotations
import json
from pathlib import Path

_PINS_FILE = Path.home() / ".config" / "gator" / "pinned_contexts.json"

def _load() -> dict[str, dict[str, dict]]:
    try:
        if _PINS_FILE.exists():
            return json.loads(_PINS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"default": {}}

def _save():
    try:
        _PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PINS_FILE.write_text(json.dumps(pinned_contexts, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

# {context_id: {key: {source, id, label, meta}}}
pinned_contexts: dict[str, dict[str, dict]] = _load()


def get_pins(context_id: str = "default") -> list[dict]:
    return list(pinned_contexts.get(context_id, {}).values())


def set_pin(source: str, item_id: str, label: str, meta: dict | None = None,
            context_id: str = "default") -> dict:
    pinned_contexts.setdefault(context_id, {})
    key = f"{source}::{item_id}"
    entry = {"source": source, "id": item_id, "label": label, "meta": meta or {}}
    pinned_contexts[context_id][key] = entry
    _save()
    return {"pinned": True, "label": label, "source": source, "id": item_id,
            "total": len(pinned_contexts[context_id])}


def remove_pin(source: str, item_id: str, context_id: str = "default") -> dict:
    key = f"{source}::{item_id}"
    removed = pinned_contexts.get(context_id, {}).pop(key, None)
    _save()
    return {"unpinned": bool(removed), "source": source, "id": item_id}


def clear_pins(context_id: str = "default") -> dict:
    count = len(pinned_contexts.pop(context_id, {}))
    _save()
    return {"cleared": count, "context_id": context_id}
