from __future__ import annotations

import time

from skills.webpin import store


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


def web_pin_prompt_line(label: str, pin_id: str, meta: dict) -> str:
    try:
        store.web_pin_dir(pin_id)
    except ValueError:
        return ""
    app = store.sanitize_label(meta.get("app_name", "")) or "a web app"
    when = _ago(meta.get("captured_at"))
    return (
        f'- Web pin "{store.sanitize_label(label)}" (pin_id: {pin_id}, from {app}, captured {when}) '
        f'→ call read_web_pin(pin_id="{pin_id}") to see the snapshot (page text + screenshot); '
        f'call recapture_web_pin(pin_id="{pin_id}") if the user says the view changed or asks for the latest. '
        f'This is a snapshot, not live data: open answers from it with "As of {when}, from {app}".'
    )
