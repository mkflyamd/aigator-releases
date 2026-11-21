from __future__ import annotations

import re
import time

from skills.webpin import store

_LABEL_MAX = 60
_DISALLOWED = re.compile(r"[^\w .,:;\-()/%&#]")


def _ago(ts) -> str:
    try:
        secs = max(0, int(time.time() - float(ts)))
    except (TypeError, ValueError):
        return "at an unknown time"
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} d ago"


def _safe(value) -> str:
    text = re.sub(r"\s+", " ", str(value if value is not None else ""))
    return _DISALLOWED.sub("", text).strip()[:_LABEL_MAX].strip()


def _captured_at(pin_id: str, meta: dict):
    snap = store.read_snapshot(pin_id)
    if isinstance(snap, dict) and snap.get("captured_at") is not None:
        return snap["captured_at"]
    return meta.get("captured_at")


def web_pin_prompt_line(label: str, pin_id: str, meta: dict) -> str:
    try:
        store.web_pin_dir(pin_id)
    except ValueError:
        return ""
    app = _safe(meta.get("app_name")) or "a web app"
    when = _ago(_captured_at(pin_id, meta))
    return (
        f'- Web pin "{_safe(label)}" (pin_id: {pin_id}, from {app}, captured {when}) '
        f'→ call read_web_pin(pin_id="{pin_id}") to see the snapshot (page text + screenshot); '
        f'call recapture_web_pin(pin_id="{pin_id}") if the user says the view changed or asks for the latest. '
        f'This is a snapshot, not live data: open answers from it with "As of {when}, from {app}".'
    )
