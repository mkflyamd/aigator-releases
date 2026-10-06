"""Per-user encrypted secret storage. Stdlib only.

Each secret is one encrypted blob under ~/.gator/secrets/<name>.bin
(current-user scope). On Windows blobs are DPAPI-protected; on macOS and Linux
they are AES-GCM encrypted with a master key kept in the OS vault (Linux
without a keyring uses a user-only key file). This stops other users and
offline theft; it does not stop malware running as the same user. If no OS
vault is usable on macOS, operations that must encrypt or decrypt raise
SecureStoreError; there is no plaintext fallback. (get()/delete()/list_names()
with nothing stored simply return None / do nothing / return an empty list.)

Legacy plaintext token files are migrated on first read (see _LEGACY).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
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


def _platform() -> str:
    return sys.platform


def _use_dpapi() -> bool:
    return _platform() == "win32"


def _protect(data: bytes) -> bytes:
    return _dpapi(True, data) if _use_dpapi() else _vault_protect(data)


def _unprotect(data: bytes) -> bytes:
    return _dpapi(False, data) if _use_dpapi() else _vault_unprotect(data)


# ── macOS / Linux backend: AES-GCM with a master key held in the OS vault ───

_VAULT_SERVICE = "AI Gator"
_VAULT_USER = "secure-store-master-key"
_VAULT_TAG = b"\x02"
_MASTER: bytes | None = None
_LEVEL = "os-vault"


class _VaultUnavailable(Exception):
    pass


# Only real OS vaults may hold the master key. PYTHON_KEYRING_BACKEND or
# keyrings.alt can select a plaintext-file backend that would still look like
# "os-vault" to the rest of this module.
_ALLOWED_BACKENDS = (
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.libsecret",
)
_CHAINER = "keyring.backends.chainer"


def _backend_allowed(backend) -> bool:
    module = type(backend).__module__ or ""
    if module.startswith(_CHAINER):
        # The chainer tries its backends in priority order; judge it by the first.
        subs = list(getattr(backend, "backends", ()))
        return bool(subs) and type(subs[0]).__module__.startswith(_ALLOWED_BACKENDS)
    return module.startswith(_ALLOWED_BACKENDS)


def _vault_call(fn_name: str, *args):
    try:
        import keyring
    except ImportError as exc:
        raise _VaultUnavailable("keyring not installed") from exc
    try:
        if not _backend_allowed(keyring.get_keyring()):
            raise _VaultUnavailable("keyring backend is not an OS vault")
        return getattr(keyring, fn_name)(_VAULT_SERVICE, _VAULT_USER, *args)
    except _VaultUnavailable:
        raise
    except Exception as exc:  # any backend failure (D-Bus, locked, no backend, ...)
        raise _VaultUnavailable(type(exc).__name__) from exc


def _vault_get() -> str | None:
    return _vault_call("get_password")


def _vault_set(value: str) -> None:
    _vault_call("set_password", value)


def _key_file() -> Path:
    return _root() / ".master.key"


def _read_key_file() -> bytes | None:
    try:
        text = _key_file().read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SecureStoreError(f"master key file unreadable: {type(exc).__name__}") from exc
    try:
        key = base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise SecureStoreError("master key file is invalid; delete it to reset (credentials must be re-entered)") from exc
    if len(key) != 32:
        raise SecureStoreError("master key file is invalid; delete it to reset (credentials must be re-entered)")
    return key


def _file_key() -> bytes:
    key = _read_key_file()
    if key is not None:
        return key
    key = os.urandom(32)
    path = _key_file()
    _ensure_root()
    # Write a complete temp file first (mkstemp creates it 0600), then publish it
    # atomically so a reader never sees an empty or partial key file.
    fd, tmp = tempfile.mkstemp(prefix=".tmp_master_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(base64.b64encode(key).decode("ascii"))
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass  # another process won the race; use its key
        except OSError:
            # Filesystem without hard links: replace only if nobody published yet.
            if not path.exists():
                os.replace(tmp, path)
        winner = _read_key_file()
        if winner is None:
            raise SecureStoreError("master key file vanished during creation")
        return winner
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _decode_key(text: str) -> bytes:
    try:
        key = base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise SecureStoreError("vault master key is invalid") from exc
    if len(key) != 32:
        raise SecureStoreError("vault master key is invalid")
    return key


def _master_key() -> bytes:
    global _MASTER, _LEVEL
    with _LOCK:
        if _MASTER is not None:
            return _MASTER
        try:
            stored = _vault_get()
            if stored is None:
                adopted = _read_key_file()
                key = adopted if adopted is not None else os.urandom(32)
                if adopted is None:
                    _warn_orphans()
                _vault_set(base64.b64encode(key).decode("ascii"))
                again = _vault_get()
                if again is None:
                    raise _VaultUnavailable("vault did not return the stored key")
                stored_key = _decode_key(again)
                if adopted is not None and stored_key == adopted:
                    _remove_key_file("adopted")
                elif adopted is not None:
                    _warn_orphans()
                key = stored_key
            else:
                key = _decode_key(stored)
                try:
                    leftover = _read_key_file()
                except SecureStoreError:
                    leftover = None
                if leftover is not None and leftover == key:
                    _remove_key_file("leftover")
            level = "os-vault"
        except _VaultUnavailable as exc:
            if _platform() != "linux":
                raise SecureStoreError(f"OS credential vault unavailable: {exc}") from exc
            if not _key_file().exists() and list_names():
                # The vault probably holds the key for existing blobs but is
                # transiently unavailable; a fresh key would orphan them.
                raise SecureStoreError(
                    "OS keyring unavailable and encrypted credentials already exist; "
                    "unlock/start the keyring and retry, or use Settings > Clear stored "
                    "credentials to reset (you will need to sign in again)"
                ) from exc
            _log.warning("no OS keyring available; using a user-only key file (reduced protection)")
            try:
                key = _file_key()
            except OSError as exc:
                raise SecureStoreError(f"cannot create master key file: {type(exc).__name__}") from exc
            level = "key-file"
        _MASTER, _LEVEL = key, level
        return key


def _remove_key_file(why: str) -> None:
    try:
        _key_file().unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        _log.error("could not remove %s key file: %s", why, type(exc).__name__)


def _warn_orphans() -> None:
    count = len(list_names())
    if count:
        _log.warning(
            "master key changed while %d existing encrypted credential(s) are stored; "
            "they may become unreadable and need re-authentication", count,
        )


def reset_key_material() -> None:
    """Forget the cached master key and delete the fallback key file (used after
    'clear all credentials' so the next write starts from a clean state)."""
    global _MASTER, _LEVEL
    with _LOCK:
        _MASTER, _LEVEL = None, "os-vault"
        _remove_key_file("fallback")


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise SecureStoreError("the cryptography package is not installed") from exc
    return AESGCM


def _vault_protect(data: bytes) -> bytes:
    AESGCM = _aesgcm()

    nonce = os.urandom(12)
    return _VAULT_TAG + nonce + AESGCM(_master_key()).encrypt(nonce, data, _ENTROPY)


def _vault_unprotect(blob: bytes) -> bytes:
    AESGCM = _aesgcm()

    if not blob.startswith(_VAULT_TAG) or len(blob) < 1 + 12 + 16:
        raise ValueError("unknown blob format")
    return AESGCM(_master_key()).decrypt(blob[1:13], blob[13:], _ENTROPY)


def protection_level() -> str:
    """'os-vault', 'key-file' (reduced) or 'unavailable'."""
    if _use_dpapi():
        return "os-vault"
    try:
        _master_key()
    except SecureStoreError:
        return "unavailable"
    return _LEVEL


# ── Paths ───────────────────────────────────────────────────────────────────


def _home() -> Path:
    return Path.home()


def _root() -> Path:
    return _home() / ".gator" / "secrets"


def _ensure_root() -> None:
    root = _root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if _platform() != "win32":
        os.chmod(root, 0o700)


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
    _ensure_root()
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows sharing violation: another process has the blob open.
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
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
    # A file another process is mid-shred reads as NULs; treat it as empty.
    if not text.strip("\0 \t\r\n"):
        return None
    target = _path(name)
    if target.exists():
        # Another process finished migrating while we were reading.
        try:
            return _read_blob(target)
        except SecureStoreError:
            raise
        except Exception:
            pass
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
    try:
        names = sorted(p.stem.replace("~", "/") for p in root.glob("*.bin"))
    except OSError as exc:
        raise SecureStoreError(f"cannot list stored credentials: {exc}") from exc
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
