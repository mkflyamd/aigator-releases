from __future__ import annotations

import re
import time

from skills.webpin import store

_LABEL_MAX = 60
_DISALLOWED = re.compile(r"[^\w .,:;\-()/%&#]")


_STALE_SECS = 30 * 60  # matches STALE_MS in web/static/web-pins.js


def _age_secs(ts) -> int | None:
    try:
        return max(0, int(time.time() - float(ts)))
    except (TypeError, ValueError):
        return None


def _ago(ts) -> str:
    secs = _age_secs(ts)
    if secs is None:
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
    captured = _captured_at(pin_id, meta)
    when = _ago(captured)
    age = _age_secs(captured)
    source = _safe(label)
    if not source or source == store.GENERIC_LABEL:
        source = "your pinned page"
    if age is None or age >= _STALE_SECS:
        freshness = (
            f'It is older than 30 minutes: lead the answer with "From {source} (captured {when}): ..." and offer to refresh it. '
            "Never say \"currently\" or \"right now\" about it."
        )
    else:
        freshness = (
            "It is fresh: answer directly with no lead-in, and do not mention its age or source unless the user asks where it came from "
            f'or how current it is (then say "That\'s from a snapshot of {source} taken {when}.").'
        )
    return (
        f'- Web pin "{_safe(label)}" (pin_id: {pin_id}, captured {when}) '
        f'→ call read_web_pin(pin_id="{pin_id}") to see the snapshot (page text plus the screenshot, or a description of it if you cannot see images); '
        f'if the user asks for the latest or says the view changed, call recapture_web_pin(pin_id="{pin_id}") straight away (it only reads, so it needs no approval). '
        f'This is a snapshot, not live data. {freshness} '
        'When one answer uses several pins, label each figure inline with its pin label ("from <label>, ...").'
    )


def web_pin_compare_line(pins: list[dict]) -> str:
    apps: dict[str, str] = {}
    other_sources: list[str] = []
    for p in pins:
        if p.get("source") == "webpin":
            meta = p.get("meta") or {}
            key = meta.get("app_id") or ""
            if key:
                apps.setdefault(key, _safe(meta.get("app_name")) or "a web app")
        else:
            src = _safe(p.get("source"))
            if src and src not in other_sources:
                other_sources.append(src)
    if not apps:
        return ""
    if len(apps) >= 2:
        names = ", ".join(sorted(apps.values()))
        scope = f"come from different apps ({names})"
    elif other_sources:
        scope = f"sit alongside pins from other sources ({', '.join(sorted(other_sources))}) next to {next(iter(apps.values()))}"
    else:
        return ""
    return (
        f"WEB PIN COMPARISON: the pinned items {scope}. When the user asks to compare, reconcile or cross-check them, "
        "read every relevant pin first. Line figures up by what they measure, not by position. State each figure's "
        "source and capture time, and say which is older. Call out unit, period or scope differences before concluding "
        "two figures disagree. Never blend numbers from two sources without naming both."
    )
