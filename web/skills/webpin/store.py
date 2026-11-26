"""On-disk snapshot storage for web pins. One directory per pin id."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

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


_HOSTLIKE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://\S*|(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:[/:?#]\S*)?)$", re.I)
_SITE_SUFFIX = re.compile(r"\s+[-|–—·]\s+([^-|–—·]+)$")
GENERIC_LABEL = "Web view"


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def strip_site_suffix(title: str, app_name: str = "", url: str = "") -> str:
    """Drop a trailing ' - Power BI' style suffix, but only when it names the app or the site itself."""
    m = _SITE_SUFFIX.search(title)
    if not m:
        return title
    suffix = _alnum(m.group(1))
    host = _alnum(urlparse(url).hostname or "")
    if len(suffix) < 3 or not (suffix == _alnum(app_name) or suffix in host):
        return title
    return title[: m.start()].strip() or title


def _usable_label(s: str, app_id: str) -> str:
    s = sanitize_label(s)
    if not s or s.lower().startswith("untitled") or s == app_id or _HOSTLIKE.match(s):
        return ""
    return s


def derive_label(aria_label: str, title: str, app_name: str, app_id: str = "", url: str = "") -> str:
    """Pin label: element label, then page title, else 'Web view'. Never the app name, a URL, hostname, app id or 'Untitled'."""
    candidates = (aria_label, strip_site_suffix(sanitize_label(title), app_name, url))
    for c in candidates:
        label = _usable_label(c, app_id)
        if label:
            return label
    return GENERIC_LABEL


def read_snapshot(pin_id: str) -> dict | None:
    f = web_pin_dir(pin_id) / "snapshot.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_image(pin_id: str) -> bytes | None:
    """The screenshot, only if it is the one this snapshot was written with."""
    d = web_pin_dir(pin_id)
    snap = read_snapshot(pin_id)
    expected = (snap or {}).get("image_sha")
    if not expected:
        return None
    try:
        data = (d / "snapshot.png").read_bytes()
    except OSError:
        return None
    return data if hashlib.sha256(data).hexdigest() == expected else None


def read_description(pin_id: str, image: bytes) -> dict | None:
    """Cached screenshot description, valid only for this exact image."""
    f = web_pin_dir(pin_id) / "description.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("image_sha") != hashlib.sha256(image).hexdigest():
        return None
    return data if data.get("text") else None


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_description(pin_id: str, image: bytes, text: str, model: str) -> None:
    d = web_pin_dir(pin_id)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"image_sha": hashlib.sha256(image).hexdigest(), "text": text, "model": model}
    _atomic_write(d / "description.json", json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def write_snapshot(pin_id: str, *, image: bytes | None, text: str | None, meta: dict) -> dict:
    """Write one capture. The text and the screenshot always come from the same capture: an omitted image removes the
    previous one. snapshot.json is written last and records the image hash, so a write that stops half way leaves the
    previous snapshot readable and a mismatched image is never served."""
    d = web_pin_dir(pin_id)
    d.mkdir(parents=True, exist_ok=True)
    prev = read_snapshot(pin_id)
    new_text = text if text is not None else (prev or {}).get("text", "")
    text_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
    changed = prev is None or prev.get("text_hash") != text_hash
    merged_meta = {**((prev or {}).get("meta") or {}), **(meta or {})}
    captured_at = time.time()
    if image is not None:
        _atomic_write(d / "snapshot.png", image)
    body = {
        "text": new_text,
        "meta": merged_meta,
        "captured_at": captured_at,
        "text_hash": text_hash,
        "image_sha": hashlib.sha256(image).hexdigest() if image is not None else None,
    }
    _atomic_write(d / "snapshot.json", json.dumps(body, ensure_ascii=False).encode("utf-8"))
    if image is None:
        (d / "snapshot.png").unlink(missing_ok=True)
    return {"captured_at": captured_at, "text_hash": text_hash, "changed": changed}


def update_meta(pin_id: str, meta: dict) -> bool:
    """Change snapshot metadata only; the text, screenshot and capture time stay as they were."""
    snap = read_snapshot(pin_id)
    if snap is None:
        return False
    snap["meta"] = {**(snap.get("meta") or {}), **meta}
    _atomic_write(web_pin_dir(pin_id) / "snapshot.json", json.dumps(snap, ensure_ascii=False).encode("utf-8"))
    return True


def delete_if_unreferenced(pin_id: str) -> bool:
    from skills.context import state

    try:
        d = web_pin_dir(pin_id)
    except ValueError:
        return False
    with state._lock:
        if any(
            isinstance(e, dict) and e.get("source") == "webpin" and e.get("id") == pin_id
            for entries in state.pinned_contexts.values()
            for e in entries.values()
        ):
            return False
        shutil.rmtree(d, ignore_errors=True)
    return True
