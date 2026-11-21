"""On-disk snapshot storage for web pins. One directory per pin id."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

_ROOT: Path | None = None
_UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_LABEL_MAX = 120


def _root() -> Path:
    return _ROOT or (Path.home() / ".config" / "gator" / "web_pins")


def web_pin_dir(pin_id: str) -> Path:
    if not isinstance(pin_id, str) or not _UUID4.fullmatch(pin_id):
        raise ValueError("invalid web pin id")
    return _root() / pin_id


def sanitize_label(s: str) -> str:
    s = re.sub(r"[\r\n\t]+", " ", s or "")
    s = s.replace('"', "").replace("'", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:_LABEL_MAX]


def read_snapshot(pin_id: str) -> dict | None:
    f = web_pin_dir(pin_id) / "snapshot.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_image(pin_id: str) -> bytes | None:
    f = web_pin_dir(pin_id) / "snapshot.png"
    return f.read_bytes() if f.exists() else None


def write_snapshot(pin_id: str, *, image: bytes | None, text: str | None, meta: dict) -> dict:
    d = web_pin_dir(pin_id)
    d.mkdir(parents=True, exist_ok=True)
    prev = read_snapshot(pin_id)
    new_text = text if text is not None else (prev or {}).get("text", "")
    text_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
    changed = prev is None or prev.get("text_hash") != text_hash
    merged_meta = {**((prev or {}).get("meta") or {}), **(meta or {})}
    captured_at = time.time()
    if image is not None:
        (d / "snapshot.png").write_bytes(image)
    (d / "snapshot.json").write_text(
        json.dumps(
            {"text": new_text, "meta": merged_meta, "captured_at": captured_at, "text_hash": text_hash},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"captured_at": captured_at, "text_hash": text_hash, "changed": changed}


def delete_if_unreferenced(pin_id: str) -> bool:
    from skills.context import state

    try:
        d = web_pin_dir(pin_id)
    except ValueError:
        return False
    with state._lock:
        if pin_id in json.dumps(state.pinned_contexts, default=str):
            return False
        shutil.rmtree(d, ignore_errors=True)
    return True
