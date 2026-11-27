"""On-disk snapshot storage for web pins. One directory per pin id."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
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
    """Pin label: element label, then page title, then app name. Never a URL, hostname, app id or 'Untitled'."""
    candidates = (aria_label, strip_site_suffix(sanitize_label(title), app_name, url), app_name)
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


def read_image(pin_id: str, tile: int = 1) -> bytes | None:
    """Tile 1 is the snapshot image; a tall capture's later tiles follow top to bottom."""
    f = web_pin_dir(pin_id) / ("snapshot.png" if tile == 1 else f"tile-{tile}.png")
    return f.read_bytes() if f.exists() else None


def tile_count(pin_id: str) -> int:
    d = web_pin_dir(pin_id)
    return 1 + len(list(d.glob("tile-*.png"))) if (d / "snapshot.png").exists() else 0


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


def write_description(pin_id: str, image: bytes, text: str, model: str) -> None:
    d = web_pin_dir(pin_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "description.json").write_text(
        json.dumps({"image_sha": hashlib.sha256(image).hexdigest(), "text": text, "model": model}, ensure_ascii=False),
        encoding="utf-8",
    )


def write_snapshot(
    pin_id: str, *, image: bytes | None, text: str | None, meta: dict, tiles: list[bytes] | None = None
) -> dict:
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
        for old in d.glob("tile-*.png"):
            old.unlink()
        for n, tile in enumerate(tiles or [], start=2):
            (d / f"tile-{n}.png").write_bytes(tile)
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
