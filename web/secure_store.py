"""Per-user encrypted secret storage. Stdlib only.

Each secret is one DPAPI blob under ~/.gator/secrets/<name>.bin (current-user
scope). DPAPI stops other users and offline theft; it does not stop malware
running as the same user. On non-Windows platforms any operation that must
encrypt or decrypt raises SecureStoreError -- there is deliberately no
plaintext fallback. (get()/delete()/list_names() with nothing stored simply
return None / do nothing / return an empty list.)

Legacy plaintext token files are migrated on first read (see _LEGACY).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

_log = logging.getLogger("secure_store")
_LOCK = threading.RLock()
_ENTROPY = b"aigator-secure-store-v1"
_VERSION = b"\x01"
_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+(/[A-Za-z0-9_.\-]+)*$")


class SecureStoreError(RuntimeError):
    pass


# ── DPAPI backend ───────────────────────────────────────────────────────────


def _dpapi(protect: bool, data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecureStoreError("secure_store is only supported on Windows (DPAPI)")
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.restype = wintypes.BOOL

    def _blob(raw: bytes):
        buf = ctypes.create_string_buffer(raw, len(raw))
        return _Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    in_blob, _keep1 = _blob(data)
    ent_blob, _keep2 = _blob(_ENTROPY)
    out_blob = _Blob()
    UI_FORBIDDEN = 0x1
    if protect:
        ok = fn(ctypes.byref(in_blob), "AI Gator", ctypes.byref(ent_blob),
                None, None, UI_FORBIDDEN, ctypes.byref(out_blob))
    else:
        ok = fn(ctypes.byref(in_blob), None, ctypes.byref(ent_blob),
                None, None, UI_FORBIDDEN, ctypes.byref(out_blob))
    if not ok:
        raise OSError(f"DPAPI call failed: {ctypes.WinError()}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _protect(data: bytes) -> bytes:
    return _dpapi(True, data)


def _unprotect(data: bytes) -> bytes:
    return _dpapi(False, data)


# ── Paths ───────────────────────────────────────────────────────────────────


def _home() -> Path:
    return Path.home()


def _root() -> Path:
    return _home() / ".gator" / "secrets"


def _check(name: str) -> None:
    if (
        not isinstance(name, str)
        or not _NAME_RE.fullmatch(name)
        or any(seg.strip(".") == "" for seg in name.split("/"))
    ):
        raise ValueError(f"invalid secret name: {name!r}")


def _path(name: str) -> Path:
    _check(name)
    return _root() / (name.replace("/", "~") + ".bin")


def _legacy_files(name: str) -> list[Path]:
    h = _home()
    cfg = h / ".config"
    table = {
        "graph/token": [
            cfg / "microsoft-graph" / "token.json",
            cfg / "sharepoint-files" / "token.json",
        ],
        "graph/teams_token": [cfg / "microsoft-graph" / "teams_token.json"],
        "graph/skype_token": [
            cfg / "microsoft-graph" / "skype_token.json",
            cfg / "microsoft-graph" / "skypetoken.json",
        ],
        "slack/token": [cfg / "slack-mcp" / "token.json"],
        "slack/pkce": [cfg / "slack-mcp" / ".pkce_pending.json"],
    }
    if name in table:
        return table[name]
    if name.startswith("oauth/"):
        return [h / ".gator" / "oauth" / f"{name[len('oauth/'):]}.json"]
    return []


_STATIC_NAMES = ("graph/token", "graph/teams_token", "graph/skype_token",
                 "slack/token", "slack/pkce")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _shred(path: Path) -> None:
    """Overwrite then delete a plaintext file (overwrite is best effort on SSDs)."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as fh:
            fh.write(b"\0" * size)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        _log.error("could not remove legacy file %s: %s", path.name, exc)


def _write_blob(path: Path, value: str) -> None:
    blob = _protect(_VERSION + value.encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_blob(path: Path) -> str:
    plain = _unprotect(path.read_bytes())
    if not plain.startswith(_VERSION):
        raise ValueError("unknown blob version")
    return plain[len(_VERSION):].decode("utf-8")


def _migrate_legacy(name: str) -> str | None:
    existing = [p for p in _legacy_files(name) if p.exists()]
    if not existing:
        return None
    try:
        text = existing[0].read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _log.error("cannot read legacy file for %s: %s", name, exc)
        return None
    if not text.strip():
        return None
    target = _path(name)
    try:
        _write_blob(target, text)
        if _read_blob(target) != text:
            raise ValueError("verification mismatch")
    except SecureStoreError:
        raise
    except Exception as exc:
        _log.error("migration of %s failed verification, plaintext kept: %s", name, exc)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return text
    for p in existing:
        _shred(p)
    _log.info("migrated %s into encrypted storage", name)
    return text


# ── Public API ──────────────────────────────────────────────────────────────


def get(name: str) -> str | None:
    path = _path(name)
    with _LOCK:
        if path.exists():
            try:
                return _read_blob(path)
            except SecureStoreError:
                raise
            except Exception as exc:
                _log.error("cannot decrypt %s (re-authentication needed): %s", name, type(exc).__name__)
                return None
        return _migrate_legacy(name)


def set(name: str, value: str) -> None:  # noqa: A001 - public API name
    path = _path(name)
    with _LOCK:
        _write_blob(path, value)
        for legacy in _legacy_files(name):
            if legacy.exists():
                _shred(legacy)


def delete(name: str) -> None:
    path = _path(name)
    with _LOCK:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _log.error("could not delete %s: %s", name, exc)
        for legacy in _legacy_files(name):
            if legacy.exists():
                _shred(legacy)


def list_names(prefix: str = "") -> list[str]:
    root = _root()
    if not root.exists():
        return []
    names = sorted(p.stem.replace("~", "/") for p in root.glob("*.bin"))
    return [n for n in names if n.startswith(prefix)]


def get_json(name: str) -> dict | None:
    raw = get(name)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def set_json(name: str, data: dict) -> None:
    set(name, json.dumps(data))


def migrate_all() -> list[str]:
    """Migrate every known legacy plaintext file. Returns the names migrated."""
    names = list(_STATIC_NAMES)
    oauth_dir = _home() / ".gator" / "oauth"
    if oauth_dir.exists():
        names += [f"oauth/{p.stem}" for p in sorted(oauth_dir.glob("*.json"))
                  if re.fullmatch(r"[A-Za-z0-9_\-]+", p.stem)]
    migrated = []
    with _LOCK:
        for name in names:
            if _path(name).exists():
                legacy_present = [p for p in _legacy_files(name) if p.exists()]
                if not legacy_present:
                    continue
                try:
                    _read_blob(_path(name))
                except SecureStoreError:
                    raise
                except Exception as exc:
                    _log.error(
                        "encrypted blob for %s does not decrypt (%s); legacy plaintext kept",
                        name, type(exc).__name__,
                    )
                    continue
                for legacy in legacy_present:
                    _shred(legacy)
                continue
            if any(p.exists() for p in _legacy_files(name)) and _migrate_legacy(name) is not None:
                if _path(name).exists():
                    migrated.append(name)
    return migrated
