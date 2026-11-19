"""Universal context pinning — shared across all skills, scoped per tab (context_id).
Persisted to disk so pins survive server restarts."""

from __future__ import annotations
import json
import os
import threading
from pathlib import Path

_PINS_FILE = Path.home() / ".config" / "gator" / "pinned_contexts.json"

GLOBAL_CONTEXT_ID = "__global__"


def _load() -> dict[str, dict[str, dict]]:
    try:
        if _PINS_FILE.exists():
            return json.loads(_PINS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"default": {}}


# Pin tools run on agent threads while routes run on the event loop; one lock
# serializes mutation + write so neither interleaves with the other.
_lock = threading.RLock()


def _save() -> bool:
    tmp = _PINS_FILE.with_name(_PINS_FILE.name + ".tmp")
    try:
        _PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(pinned_contexts, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _PINS_FILE)
        return True
    except Exception:
        return False


# {context_id: {key: {source, id, label, meta}}}
pinned_contexts: dict[str, dict[str, dict]] = _load()


def get_pins(context_id: str = "default", include_global: bool = True) -> list[dict]:
    tab_entries = pinned_contexts.get(context_id, {})
    global_entries = pinned_contexts.get(GLOBAL_CONTEXT_ID, {})
    if not include_global or context_id == GLOBAL_CONTEXT_ID or not global_entries:
        return list(tab_entries.values())
    tab_only = [e for k, e in tab_entries.items() if k not in global_entries]
    return [{**e, "scope": "global"} for e in global_entries.values()] + tab_only


def find_slack_channel_for_ts(message_ts: str) -> str:
    """Search ALL contexts for a Slack pin with this message_ts and return its channel_id.

    Used to recover a missing channel_id when a pin was captured without one (e.g. in the
    Threads dock where __gatorCurrentCtx.channel was null at pin time). Scans cross-context
    so a pin created in one tab can recover its channel from a healthy pin in another tab.
    """
    for ctx in pinned_contexts.values():
        for entry in ctx.values():
            if entry.get("source") != "slack":
                continue
            pin_id = entry.get("id", "")
            candidate = pin_id.split(":")[0] if ":" in pin_id else ""
            if not candidate:
                continue
            meta = entry.get("meta", {})
            if meta.get("message_ts") == message_ts:
                return candidate
    return ""


def set_pin(
    source: str,
    item_id: str,
    label: str,
    meta: dict | None = None,
    context_id: str = "default",
) -> dict:
    key = f"{source}::{item_id}"
    entry = {"source": source, "id": item_id, "label": label, "meta": meta or {}}
    with _lock:
        pinned_contexts.setdefault(context_id, {})[key] = entry
        _save()
        total = len(pinned_contexts[context_id])
    return {"pinned": True, "label": label, "source": source, "id": item_id, "total": total}


def set_pin_scope(
    source: str, item_id: str, scope: str, context_id: str = "default"
) -> dict:
    key = f"{source}::{item_id}"
    if scope == "global":
        src_id, dst_id = context_id, GLOBAL_CONTEXT_ID
    else:
        src_id, dst_id = GLOBAL_CONTEXT_ID, context_id
    with _lock:
        entry = pinned_contexts.get(src_id, {}).pop(key, None)
        if entry is not None:
            pinned_contexts.setdefault(dst_id, {})[key] = entry
        moved = key in pinned_contexts.get(dst_id, {})
        if moved and not _save():
            if entry is not None:
                pinned_contexts[dst_id].pop(key, None)
                pinned_contexts[src_id][key] = entry
            moved = False
    return {"moved": moved, "scope": scope, "source": source, "id": item_id}


def remove_pin(
    source: str, item_id: str, context_id: str = "default", scope: str = "tab"
) -> dict:
    key = f"{source}::{item_id}"
    # Global removal also drops tabs' own copies, which get_pins hides behind the global pin
    buckets = list(pinned_contexts) if scope == "global" else [context_id]
    removed = False
    with _lock:
        for bucket in buckets:
            if pinned_contexts.get(bucket, {}).pop(key, None) is not None:
                removed = True
        _save()
    return {"unpinned": removed, "source": source, "id": item_id}


def clear_pins(context_id: str = "default") -> dict:
    with _lock:
        count = len(pinned_contexts.pop(context_id, {}))
        _save()
    return {"cleared": count, "context_id": context_id}
