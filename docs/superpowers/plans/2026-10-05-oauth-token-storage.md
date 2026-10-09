# OAuth Token Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every plaintext OAuth/PAT token from runtime directories by storing them DPAPI-encrypted behind one shared `secure_store` module, migrate existing plaintext on first read, and add a working "clear credentials" control.

**Architecture:** A new stdlib-only `web/secure_store.py` holds one DPAPI blob per secret under `~/.gator/secrets/`. It also owns a table of legacy plaintext locations, so `get()` migrates on read (encrypt, verify, shred plaintext) and `delete()`/`set()` also remove legacy files. Every reader and writer is switched to it; the web app imports it normally, skill scripts load it by file path (registering it as `sys.modules["secure_store"]` so there is one instance).

**Tech Stack:** Python 3.12 stdlib (`ctypes` for DPAPI), FastAPI, pytest. No new dependencies.

Spec: [2026-10-05-oauth-token-storage-design.md](../specs/2026-10-05-oauth-token-storage-design.md)

## Global Constraints

- `secure_store` is stdlib only; no third-party dependency (spec section 1).
- Windows-only backend (DPAPI, current-user scope, UI forbidden, fixed entropy). On any other OS the module raises `SecureStoreError`; it must never fall back to plaintext.
- Secrets live only at `~/.gator/secrets/<safe-name>.bin`. No code path may write token JSON (spec section 2).
- Migration order is encrypt, decrypt-verify, then delete plaintext (overwrite first, best effort). If verification fails, keep the plaintext and log an error. Idempotent and safe to interrupt.
- Out of scope: LLM API keys, `google_oauth_client_secret`, MCP `auth_value`, `mcp_spawn_specs` env, the environment-variable copy of PATs in `app.py`, macOS/Linux backends, Microsoft server-side revocation.
- Project is called **AI Gator**, never "POC".
- The only fake credential in tests/docs is `aigator-fake-api-key`. Use it (or values derived only by prefixing context, e.g. `"access_token": "aigator-fake-api-key"`) for every fake token/secret. Never print real token contents in logs.
- Commit messages must NOT contain `Co-Authored-By` lines.
- Email/Teams/Slack messages never auto-send (not touched by this work; do not change HITL gating).
- Keep names/signatures of `skills.slack.mcp_client._load_token` / `_save_token` and `oauth.storage.load/save/delete/update_token`: many tests patch them.
- Known limitation to state in docs: DPAPI protects against other users and offline theft, not malware running as the same user.

## Deviations from the spec (decided during planning)

1. `secure_store` gains `get_json(name) -> dict | None` and `set_json(name, data)`; every caller stores JSON.
2. A blob that cannot be decrypted makes `get()` log an error and return `None` (the user must re-authenticate); it never returns plaintext. This avoids 500s at ~20 call sites.
3. Migration lives in `secure_store.get()` via a legacy-path table, so the ~20 direct readers in `routes/teams.py` etc. migrate without bespoke code.
4. Tests get an autouse fixture (fake reversible backend, temp home) so CI on Linux works and a developer's real token files can never be touched by the test suite.

## File Structure

| File                                                                      | Responsibility                                                                                   |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `web/secure_store.py` (new)                                               | DPAPI blobs, legacy table + migration, `get/set/delete/list_names/get_json/set_json/migrate_all` |
| `tests/conftest.py` (modify)                                              | autouse fixture: temp home + fake backend for `secure_store`                                     |
| `tests/test_secure_store.py` (new)                                        | unit + migration tests                                                                           |
| `web/oauth/storage.py` (modify)                                           | same API, backed by `secure_store` (`oauth/<id>`)                                                |
| `web/oauth/provider.py`, `web/oauth/dcr.py` (modify)                      | capture optional `revocation_endpoint`                                                           |
| `web/skills/m365-email/graph_client.py` (modify)                          | token load/save via `secure_store`; `TOKEN_FILE` kept as legacy symbol for the 7 wrappers        |
| `web/skills/_m365/helpers.py` (modify)                                    | `get_teams_token()` via `secure_store`                                                           |
| `web/skills/m365-teams/scripts/read_chats.py` (modify)                    | graph token + skype cache via `secure_store`                                                     |
| `web/routes/auth.py` (modify)                                             | token writes/reads via `secure_store`; new `POST /api/auth/clear`                                |
| `web/routes/teams.py` (modify)                                            | direct `token.json`/`teams_token.json` reads via `secure_store`                                  |
| `web/skills/slack/mcp_client.py` (modify)                                 | token + PKCE via `secure_store`                                                                  |
| `web/config.py` (modify)                                                  | PAT overlay on load, split on write, `.bak`/`.damaged` scrub                                     |
| `web/app.py` (modify)                                                     | startup `migrate_all()` + config scrub                                                           |
| `web/static/index.html`, `web/static/app.js` (modify)                     | Settings "Clear stored credentials" button                                                       |
| `tests/test_token_storage_guard.py` (new)                                 | asserts no module writes token JSON                                                              |
| `tests/test_*_characterization*.py`, `tests/test_token_rotation.py` (new) | behavior locks                                                                                   |
| `docs/security/threatmodel-remediation.md`, `reset-auth.ps1` (modify)     | tracker + dev script                                                                             |

Paths from skill files to `web/`: `web/skills/m365-email/graph_client.py` -> `parents[2]`; `web/skills/_m365/helpers.py` -> `parents[2]`; `web/skills/slack/mcp_client.py` -> `parents[2]`; `web/skills/m365-teams/scripts/read_chats.py` -> `parents[3]`.

Skill loader snippet (used verbatim in each of those four files; adjust `parents[N]`):

```python
def _secure_store():
    import importlib.util
    import sys
    from pathlib import Path

    mod = sys.modules.get("secure_store")
    if mod is None:
        path = Path(__file__).resolve().parents[2] / "secure_store.py"
        spec = importlib.util.spec_from_file_location("secure_store", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["secure_store"] = mod
        spec.loader.exec_module(mod)
    return mod
```

---

### Task 1: `secure_store` module, test fixture, unit tests

**Files:**

- Create: `web/secure_store.py`
- Modify: `tests/conftest.py` (add one autouse fixture after the imports)
- Test: `tests/test_secure_store.py`

**Interfaces:**

- Produces:
  - `class SecureStoreError(RuntimeError)`
  - `get(name: str) -> str | None`, `set(name: str, value: str) -> None`, `delete(name: str) -> None`, `list_names(prefix: str = "") -> list[str]`
  - `get_json(name: str) -> dict | None`, `set_json(name: str, data: dict) -> None`
  - `migrate_all() -> list[str]` (names migrated)
  - Test seams: module globals `_protect(bytes)->bytes`, `_unprotect(bytes)->bytes`, `_home() -> Path`.

- [ ] **Step 1: Write the autouse fixture** in `tests/conftest.py`, directly after the `_JIRA_TEST_URL = ...` line:

```python
@pytest.fixture(autouse=True)
def _isolated_secure_store(tmp_path, monkeypatch):
    """Fake reversible backend + temp home so tests never touch real DPAPI or
    a developer's real ~/.config token files."""
    import secure_store

    monkeypatch.setattr(secure_store, "_home", lambda: tmp_path / "home")
    monkeypatch.setattr(secure_store, "_protect", lambda b: b"FAKE:" + b[::-1])
    monkeypatch.setattr(
        secure_store, "_unprotect", lambda b: b[len(b"FAKE:"):][::-1]
    )
    yield
```

(`tests/conftest.py` already puts `web/` on `sys.path` before fixtures run.)

- [ ] **Step 2: Write the failing tests** `tests/test_secure_store.py`:

```python
import json
import sys

import pytest

import secure_store

FAKE = "aigator-fake-api-key"


def _secrets_dir():
    return secure_store._home() / ".gator" / "secrets"


def test_round_trip_and_not_plaintext_on_disk():
    secure_store.set("slack/token", FAKE)
    assert secure_store.get("slack/token") == FAKE
    blob = (_secrets_dir() / "slack~token.bin").read_bytes()
    assert FAKE.encode() not in blob


def test_missing_returns_none_and_delete_is_idempotent():
    assert secure_store.get("graph/token") is None
    secure_store.delete("graph/token")
    secure_store.set("graph/token", FAKE)
    secure_store.delete("graph/token")
    assert secure_store.get("graph/token") is None


def test_json_helpers_round_trip():
    secure_store.set_json("graph/token", {"access_token": FAKE, "n": 1})
    assert secure_store.get_json("graph/token") == {"access_token": FAKE, "n": 1}
    secure_store.set("graph/teams_token", "not json")
    assert secure_store.get_json("graph/teams_token") is None


def test_list_names_prefix():
    secure_store.set("oauth/a", "1")
    secure_store.set("oauth/b", "2")
    secure_store.set("slack/token", "3")
    assert secure_store.list_names("oauth/") == ["oauth/a", "oauth/b"]
    assert secure_store.list_names() == ["oauth/a", "oauth/b", "slack/token"]


@pytest.mark.parametrize("bad", ["", "../x", "a/../b", "a//b", "a b", "a~b", "/a"])
def test_invalid_names_rejected(bad):
    with pytest.raises(ValueError):
        secure_store.set(bad, FAKE)


def test_corrupted_blob_returns_none_never_plaintext(caplog):
    secure_store.set("slack/token", FAKE)
    path = _secrets_dir() / "slack~token.bin"
    path.write_bytes(FAKE.encode())  # raw plaintext, not a valid blob
    assert secure_store.get("slack/token") is None
    assert FAKE not in caplog.text


def test_unsupported_platform_raises_and_never_writes(monkeypatch):
    monkeypatch.undo()  # drop the fake backend from the autouse fixture
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(secure_store, "_home", lambda: secure_store.Path("/nonexistent-aigator-home"))
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.set("slack/token", FAKE)


def test_migrates_legacy_plaintext_and_removes_it():
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE}))
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}
    assert not legacy.exists()
    # second read comes from the encrypted store
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}


def test_migration_keeps_plaintext_when_verification_fails(monkeypatch):
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE}))
    monkeypatch.setattr(secure_store, "_unprotect", lambda b: b"garbage")
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}
    assert legacy.exists()
    assert not (_secrets_dir() / "slack~token.bin").exists()


def test_old_sharepoint_token_location_migrates_into_graph_token():
    old = secure_store._home() / ".config" / "sharepoint-files" / "token.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"refresh_token": FAKE}))
    assert secure_store.get_json("graph/token") == {"refresh_token": FAKE}
    assert not old.exists()


def test_oauth_legacy_file_migrates():
    legacy = secure_store._home() / ".gator" / "oauth" / "mcp-atlassian.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"id": "mcp-atlassian"}))
    assert secure_store.get_json("oauth/mcp-atlassian") == {"id": "mcp-atlassian"}
    assert not legacy.exists()


def test_set_and_delete_remove_legacy_plaintext():
    legacy = secure_store._home() / ".config" / "microsoft-graph" / "teams_token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}")
    secure_store.set_json("graph/teams_token", {"access_token": FAKE})
    assert not legacy.exists()
    legacy.write_text("{}")
    secure_store.delete("graph/teams_token")
    assert not legacy.exists()
    assert secure_store.get("graph/teams_token") is None  # not resurrected


def test_migrate_all_sweeps_every_known_legacy_file():
    h = secure_store._home()
    files = {
        h / ".config" / "microsoft-graph" / "token.json": "graph/token",
        h / ".config" / "microsoft-graph" / "skype_token.json": "graph/skype_token",
        h / ".config" / "microsoft-graph" / "skypetoken.json": "graph/skype_token",
        h / ".config" / "slack-mcp" / ".pkce_pending.json": "slack/pkce",
        h / ".gator" / "oauth" / "prov1.json": "oauth/prov1",
    }
    for p in files:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
    migrated = secure_store.migrate_all()
    assert set(migrated) == set(files.values())
    assert not any(p.exists() for p in files)
    assert secure_store.migrate_all() == []  # idempotent


@pytest.mark.skipif(sys.platform != "win32", reason="real DPAPI is Windows-only")
def test_real_dpapi_round_trip(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setattr(secure_store, "_home", lambda: tmp_path)
    secure_store.set("config/jira_pat", FAKE)
    assert secure_store.get("config/jira_pat") == FAKE
    raw = next(secure_store._root().glob("*.bin")).read_bytes()
    assert FAKE.encode() not in raw
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `pytest tests/test_secure_store.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'secure_store'` (the fixture imports it).

- [ ] **Step 4: Implement `web/secure_store.py`**

```python
"""Per-user encrypted secret storage. Stdlib only.

Each secret is one DPAPI blob under ~/.gator/secrets/<name>.bin (current-user
scope). DPAPI stops other users and offline theft; it does not stop malware
running as the same user. On non-Windows platforms every operation raises
SecureStoreError -- there is deliberately no plaintext fallback.

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
    if not isinstance(name, str) or not _NAME_RE.match(name):
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
    except OSError as exc:
        _log.error("cannot read legacy file for %s: %s", name, exc)
        return None
    if not text.strip():
        return None
    target = _path(name)
    try:
        _write_blob(target, text)
        if _read_blob(target) != text:
            raise ValueError("verification mismatch")
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
                  if re.match(r"^[A-Za-z0-9_\-]+$", p.stem)]
    migrated = []
    with _LOCK:
        for name in names:
            if _path(name).exists():
                for legacy in _legacy_files(name):
                    if legacy.exists():
                        _shred(legacy)
                continue
            if any(p.exists() for p in _legacy_files(name)) and _migrate_legacy(name) is not None:
                if _path(name).exists():
                    migrated.append(name)
    return migrated
```

Notes: in `test_unsupported_platform_raises_and_never_writes` and the real-DPAPI test, `secure_store.Path` is the imported `pathlib.Path`; if the implementer prefers, replace with a local `from pathlib import Path` in the test file. In the real-DPAPI test replace the `importorskip("tempfile")` expression with a plain `tmp_path` fixture argument.

- [ ] **Step 5: Run tests, verify they pass**

Run: `pytest tests/test_secure_store.py -q`
Expected: all pass (real-DPAPI test passes on Windows, skipped elsewhere).

- [ ] **Step 6: Run the whole suite to confirm the autouse fixture broke nothing**

Run: `pytest tests -q -x`
Expected: same pass/fail set as before the change. Take the baseline by running `pytest tests -q` before Step 1 and noting any pre-existing failures; do not use `git stash` or `git checkout` to compare.

- [ ] **Step 7: Commit**

```bash
git add web/secure_store.py tests/conftest.py tests/test_secure_store.py
git commit -m "feat: add DPAPI-backed secure_store with legacy-file migration"
```

---

### Task 2: `oauth/storage.py` on `secure_store`

**Files:**

- Modify: `web/oauth/storage.py`
- Test: `tests/test_oauth_storage_characterization.py`

**Interfaces:**

- Consumes: `secure_store.get_json/set_json/delete` (Task 1).
- Produces: unchanged `storage.load(pid)->dict`, `save(pid, data)`, `delete(pid)`, `update_token(pid, token)`; `ValueError` on invalid id remains.

- [ ] **Step 1: Write characterization tests** (pass against the old file implementation AND the new one; they only use the public API). `tests/test_oauth_storage_characterization.py`:

```python
import pytest

from oauth import storage

FAKE = "aigator-fake-api-key"


@pytest.fixture(autouse=True)
def _tmp_oauth_dir(tmp_path, monkeypatch):
    # Old implementation reads _DIR; the new one has no such attribute.
    monkeypatch.setattr(storage, "_DIR", tmp_path / "oauth", raising=False)


def test_load_missing_is_empty():
    assert storage.load("p1") == {}


def test_save_load_round_trip():
    storage.save("p1", {"id": "p1", "client_id": "c"})
    assert storage.load("p1") == {"id": "p1", "client_id": "c"}


def test_update_token_merges_under_token_key():
    storage.save("p1", {"id": "p1"})
    storage.update_token("p1", {"access_token": FAKE})
    assert storage.load("p1") == {"id": "p1", "token": {"access_token": FAKE}}


def test_save_without_token_preserves_existing_token():
    storage.update_token("p1", {"access_token": FAKE})
    storage.save("p1", {"id": "p1", "client_id": "c2"})
    assert storage.load("p1")["token"] == {"access_token": FAKE}


def test_save_with_token_replaces_it():
    storage.update_token("p1", {"access_token": FAKE})
    storage.save("p1", {"id": "p1", "token": {"access_token": "aigator-fake-api-key-2"}})
    assert storage.load("p1")["token"]["access_token"] == "aigator-fake-api-key-2"


def test_delete_removes_record_and_is_idempotent():
    storage.update_token("p1", {"access_token": FAKE})
    storage.delete("p1")
    storage.delete("p1")
    assert storage.load("p1") == {}


@pytest.mark.parametrize("bad", ["../x", "a b", "a/b", ""])
def test_invalid_provider_id_rejected(bad):
    with pytest.raises(ValueError):
        storage.load(bad)
```

- [ ] **Step 2: Run on the old implementation to confirm they characterize current behavior**

Run: `pytest tests/test_oauth_storage_characterization.py -q`
Expected: PASS (old implementation, with `_DIR` patched).

- [ ] **Step 3: Replace the body of `web/oauth/storage.py`**

```python
"""Per-provider OAuth storage — provider config + token cache, DPAPI-encrypted via
secure_store under the name ``oauth/<provider_id>``."""

from __future__ import annotations

import re
import threading

import secure_store

# Reentrant — update_token holds the lock while calling save() which re-enters.
_LOCK = threading.RLock()
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _name_for(provider_id: str) -> str:
    if not _SAFE_ID.match(provider_id):
        raise ValueError(f"invalid provider id: {provider_id!r}")
    return f"oauth/{provider_id}"


def load(provider_id: str) -> dict:
    return secure_store.get_json(_name_for(provider_id)) or {}


def save(provider_id: str, data: dict) -> None:
    name = _name_for(provider_id)
    with _LOCK:
        # Preserve an existing token unless the caller explicitly provided one.
        # Re-registering a provider (DCR / BYOC / start_flow) rewrites the record
        # with provider config but no token — without this, a valid token would
        # be silently wiped, forcing the user to re-authorize every time.
        if "token" not in data:
            existing = load(provider_id)
            if existing.get("token"):
                data = {**data, "token": existing["token"]}
        secure_store.set_json(name, data)


def delete(provider_id: str) -> None:
    secure_store.delete(_name_for(provider_id))


def update_token(provider_id: str, token: dict) -> None:
    """Merge a token block into the stored provider record under key 'token'."""
    with _LOCK:
        data = load(provider_id)
        data["token"] = token
        save(provider_id, data)
```

- [ ] **Step 4: Run characterization tests plus existing oauth/mcp tests**

Run: `pytest tests/test_oauth_storage_characterization.py -q` then `pytest tests -q -k "oauth or mcp"`
Expected: PASS. If an existing test patches `storage._DIR`, update it to rely on the autouse `secure_store` fixture instead (the failing test names will point to it).

- [ ] **Step 5: Add a legacy-migration test** appended to the characterization file:

```python
def test_legacy_plaintext_record_is_migrated(tmp_path):
    import json

    import secure_store

    legacy = secure_store._home() / ".gator" / "oauth" / "p9.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"id": "p9", "token": {"access_token": FAKE}}))
    assert storage.load("p9")["token"]["access_token"] == FAKE
    assert not legacy.exists()
```

Run: `pytest tests/test_oauth_storage_characterization.py -q` — PASS.

- [ ] **Step 6: Commit**

```bash
git add web/oauth/storage.py tests/test_oauth_storage_characterization.py
git commit -m "feat: store MCP OAuth records in secure_store"
```

---

### Task 3: Graph canonical client + `_m365/helpers`

**Files:**

- Modify: `web/skills/m365-email/graph_client.py` (`_load_token` 94-129, `_save_token` 131-155, `complete_auth` ~251; add loader snippet)
- Modify: `web/skills/_m365/helpers.py:69-94` (`get_teams_token`)
- Test: `tests/test_graph_token_storage.py`

**Interfaces:**

- Consumes: `secure_store.get_json("graph/token")`, `set_json`, `get_json("graph/teams_token")`.
- Produces: `GraphClient` behavior unchanged. `TOKEN_FILE`/`OLD_TOKEN_FILE` remain as module symbols (the seven wrapper `graph_client.py` files re-export `TOKEN_FILE`; do not remove it) but are no longer read or written. `complete_auth` returns `"token_file": "secure_store:graph/token"`.

- [ ] **Step 1: Write the tests** `tests/test_graph_token_storage.py`:

```python
import importlib.util
import json
import time
from pathlib import Path

import pytest

import secure_store

FAKE = "aigator-fake-api-key"
SRC = Path(__file__).resolve().parents[1] / "web" / "skills" / "m365-email" / "graph_client.py"


@pytest.fixture
def gc(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("graph_client_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "TOKEN_FILE", tmp_path / "legacy" / "token.json")
    monkeypatch.setattr(mod, "OLD_TOKEN_FILE", tmp_path / "legacy" / "old.json")
    monkeypatch.delenv("MS_ACCESS_TOKEN", raising=False)
    return mod


def _seed(mod, **kw):
    c = mod.GraphClient()
    c._refresh_token = kw.get("refresh", "r1")
    c._tenant_id = "t"
    c._client_id = "c"
    c._access_token = kw.get("access", FAKE)
    c._expires_at = kw.get("expires_at", time.time() + 3600)
    c._save_token()
    return c


def test_save_then_new_client_loads_token(gc):
    _seed(gc)
    c2 = gc.GraphClient()
    assert (c2._refresh_token, c2._tenant_id, c2._access_token) == ("r1", "t", FAKE)


def test_token_is_not_written_as_plaintext_json(gc):
    _seed(gc)
    assert FAKE not in json.dumps(
        [str(p) for p in (secure_store._home()).rglob("*") if p.is_file() and p.suffix == ".json"]
    )
    assert not list(secure_store._home().rglob("*.json"))
    assert secure_store.get_json("graph/token")["refresh_token"] == "r1"


def test_legacy_token_file_is_migrated(gc):
    legacy = secure_store._home() / ".config" / "microsoft-graph" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"refresh_token": "legacy-r", "tenant_id": "t", "client_id": "c"}))
    c = gc.GraphClient()
    assert c._refresh_token == "legacy-r"
    assert not legacy.exists()


def test_refresh_adopts_rotated_refresh_token(gc, monkeypatch):
    c = _seed(gc, expires_at=0.0)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"access_token": "aigator-fake-api-key", "refresh_token": "r2", "expires_in": 3600}
            ).encode()

    monkeypatch.setattr(gc.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert c.get_token() == "aigator-fake-api-key"
    assert secure_store.get_json("graph/token")["refresh_token"] == "r2"
    assert gc.GraphClient()._refresh_token == "r2"
```

Note: the second test deliberately asserts there is no `.json` under the temp home at all; after Task 2's migration and with the legacy symbol patched elsewhere this must hold.

- [ ] **Step 2: Run, verify failures**

Run: `pytest tests/test_graph_token_storage.py -q`
Expected: `test_token_is_not_written_as_plaintext_json` and `test_legacy_token_file_is_migrated` FAIL; the round-trip and rotation tests pass on the old code (this proves they characterize behavior).

- [ ] **Step 3: Implement.** In `graph_client.py` add the loader snippet (from the File Structure section, `parents[2]`) near the top-level helpers, then:

Replace `_load_token` with:

```python
    def _load_token(self) -> None:
        data = _secure_store().get_json("graph/token") or {}
        if data:
            self._refresh_token = data.get("refresh_token", "")
            self._client_id = data.get("client_id", DEFAULT_CLIENT_ID)
            self._tenant_id = data.get("tenant_id", "")
            self._access_token = data.get("access_token", "")
            self._expires_at = data.get("expires_at", 0.0)
        env_token = os.environ.get("MS_ACCESS_TOKEN", "")
        if env_token and not self._access_token:
            self._access_token = env_token.removeprefix("Bearer ").strip()
            # Decode JWT exp claim for accurate expiry; fall back to 50 min
            try:
                payload = self._access_token.split(".")[1]
                payload += "=" * (4 - len(payload) % 4)
                claims = json.loads(base64.b64decode(payload))
                self._expires_at = float(claims.get("exp", time.time() + 3000))
            except Exception:
                self._expires_at = time.time() + 3000
```

Replace `_save_token` with:

```python
    def _save_token(self) -> None:
        _secure_store().set_json(
            "graph/token",
            {
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "tenant_id": self._tenant_id,
                "access_token": self._access_token,
                "expires_at": self._expires_at,
            },
        )
```

Change `complete_auth`'s `"token_file": str(TOKEN_FILE)` to `"token_file": "secure_store:graph/token"`. Add a one-line comment above `TOKEN_FILE`/`OLD_TOKEN_FILE`: `# Legacy plaintext locations; kept only because the m365-* wrappers re-export TOKEN_FILE.` Remove now-unused imports only if flake/ruff flags them (`shutil` was local).

In `web/skills/_m365/helpers.py` `get_teams_token()` replace the file read (69-94) with:

```python
    data = _secure_store().get_json("graph/teams_token") or {}
    token = data.get("access_token", "")
    if token and data.get("expires_at", 0) > time.time() + 60:
        return token
```

(then keep the existing fallthrough to `GraphClient().get_token()`; read the surrounding lines first and preserve the exact expiry check the old code used, adapting only the data source). Add the loader snippet with `parents[2]` to this file.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_graph_token_storage.py -q` then `pytest tests -q -k "graph or m365 or teams or email"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/m365-email/graph_client.py web/skills/_m365/helpers.py tests/test_graph_token_storage.py
git commit -m "feat: store Graph and Teams tokens in secure_store"
```

---

### Task 4: `routes/auth.py` and `routes/teams.py` token access

**Files:**

- Modify: `web/routes/auth.py` (writes at 64-75, 126-137, 189-207; reads at 233/242, 264/268, 298-307; `device_auth_poll` 403-426)
- Modify: `web/routes/teams.py` (reads at 73-75, 285-287, 1013-1014, 1357-1358, 1574-1575, 1807-1810, 2880-2886). Line 1753 (`teams_member_cache.json`) is not a token; leave it.
- Test: `tests/test_auth_token_routes.py`

**Interfaces:**

- Consumes: `secure_store.get_json/set_json` (`import secure_store` — web app imports normally).
- Produces: `routes.auth` no longer references `~/.config/...token*.json`; `auth_status` reports `"reason": "No token"` when `graph/token` is absent.

- [ ] **Step 1: Read every site first.** For each, note what happens when the file is missing/unparseable. Replace each `json.loads(<FILE>.read_text())` with `secure_store.get_json("graph/token")` (or `"graph/teams_token"`), and each `<FILE>.exists()` guard with `if data:`/`if not data:` preserving the old not-found behavior (including the `"No token file"` -> `"No token"` reason string in `auth_status`; grep `app.js` for `No token file` and update any consumer). The three teams-token writers become:

```python
    secure_store.set_json("graph/teams_token", {"access_token": token, "expires_at": expires_at})
```

using the variable names already present at each site; delete the `mkdir`, `write_text`, and `chmod` lines that belonged to the token file. In `device_auth_poll`, replace the diagnostic re-read of `token.json` (403-426) with a read of `secure_store.get_json("graph/token")` that logs only key _names_ and expiry, never values; if the block is purely diagnostic and adds nothing, remove it.

- [ ] **Step 2: Write tests** `tests/test_auth_token_routes.py` using FastAPI `TestClient` against the auth router (mirror how other `tests/test_*routes*.py` build the app; reuse their fixture if one exists):

```python
import secure_store

FAKE = "aigator-fake-api-key"


def test_teams_token_capture_stores_encrypted(client):  # `client` = TestClient with auth router
    r = client.post("/api/auth/token", json={"access_token": FAKE})
    assert r.status_code == 200
    stored = secure_store.get_json("graph/teams_token")
    assert stored["access_token"] == FAKE
    assert not list(secure_store._home().rglob("*teams_token*.json"))


def test_auth_status_reads_secure_store(client):
    secure_store.set_json("graph/token", {"access_token": FAKE, "expires_at": 9999999999,
                                           "refresh_token": "r", "tenant_id": "t", "client_id": "c"})
    body = client.get("/api/auth/status").json()
    assert body.get("authenticated") is True


def test_auth_status_without_token(client):
    body = client.get("/api/auth/status").json()
    assert body.get("authenticated") is False
```

Adjust payload field names/route paths to the real ones found in Step 1 (they are `POST /api/auth/token` at line ~64 and the status route near 298; keep the assertions about `secure_store`).

- [ ] **Step 3: Run**

Run: `pytest tests/test_auth_token_routes.py -q`; then `pytest tests -q -k "auth or teams"`
Expected: PASS.

- [ ] **Step 4: Verify no token-file references remain in these two files**

Run (Grep tool): pattern `token\.json|teams_token\.json` over `web/routes/auth.py` and `web/routes/teams.py`. Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add web/routes/auth.py web/routes/teams.py tests/test_auth_token_routes.py
git commit -m "feat: route auth and teams token access through secure_store"
```

---

### Task 5: `read_chats.py` (Graph token + skype cache)

**Files:**

- Modify: `web/skills/m365-teams/scripts/read_chats.py` (`TOKEN_FILE` 30, `SKYPE_TOKEN_FILE` 31, `_load_graph_tokens` 38-43, `_load_cached_skype_token` 46-55, `_save_skype_token` 58-73)
- Test: `tests/test_read_chats_token_storage.py`

**Interfaces:**

- Consumes: `secure_store` names `graph/teams_token` (what `_load_graph_tokens` read via `TOKEN_FILE`; confirm in Step 1) and `graph/skype_token`.
- Produces: `_load_graph_tokens() -> dict` raising `RuntimeError` if absent (unchanged contract), `_load_cached_skype_token()`/`_save_skype_token(skype_token, messaging_service, expires_in, global_service="")` unchanged signatures.

- [ ] **Step 1: Read lines 25-140.** Confirm which file `TOKEN_FILE` (line 30) points at (the plan assumes the Graph/Teams token file; map it to `graph/token` or `graph/teams_token` accordingly). Add the loader snippet with `parents[3]`.

- [ ] **Step 2: Write tests** `tests/test_read_chats_token_storage.py` (load module by path, like Task 3's `gc` fixture, with `SRC = web/skills/m365-teams/scripts/read_chats.py`):

```python
import importlib.util
import time
from pathlib import Path

import pytest

import secure_store

FAKE = "aigator-fake-api-key"
SRC = (Path(__file__).resolve().parents[1] / "web" / "skills" / "m365-teams"
       / "scripts" / "read_chats.py")


@pytest.fixture
def rc():
    spec = importlib.util.spec_from_file_location("read_chats_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_missing_graph_token_raises(rc):
    with pytest.raises(RuntimeError):
        rc._load_graph_tokens()


def test_skype_token_cache_round_trip_encrypted(rc):
    rc._save_skype_token(FAKE, "https://example.invalid/ms", 3600, "https://example.invalid/g")
    cached = rc._load_cached_skype_token()
    assert cached and FAKE in str(cached)
    assert not list(secure_store._home().rglob("*skype*token*.json"))
```

If `_load_cached_skype_token` returns a tuple/dict, adjust the second assertion to the actual shape after Step 1 (the invariant: round-trips, no plaintext file).

- [ ] **Step 3: Run, verify the encryption assertion fails, implement.** Replace the file I/O in the four functions with `_secure_store().get_json(...)` / `.set_json(...)`; drop the `chmod` in `_save_skype_token`; keep the expiry logic as-is. Keep `TOKEN_FILE`/`SKYPE_TOKEN_FILE` constants only if other modules import them (grep `TOKEN_FILE` in `web/` first; delete if unused).

- [ ] **Step 4: Run** `pytest tests/test_read_chats_token_storage.py -q` and `pytest tests -q -k "teams or chats"` — PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/m365-teams/scripts/read_chats.py tests/test_read_chats_token_storage.py
git commit -m "feat: keep Teams chat tokens and skype cache in secure_store"
```

---

### Task 6: Slack token and PKCE state

**Files:**

- Modify: `web/skills/slack/mcp_client.py` (`TOKEN_FILE` 38, `_load_token` 47-54, `_save_token` 57-76, `_PKCE_FILE` 171, `_load_pkce`/`_save_pkce`/`_clear_pkce` 174-192; add loader snippet with `parents[2]`)
- Test: `tests/test_slack_token_storage.py`

**Interfaces:**

- Consumes: `secure_store` names `slack/token`, `slack/pkce`.
- Produces: unchanged `_load_token() -> dict`, `_save_token(data: dict)` (still clears the display-name cache), `_load_pkce`, `_save_pkce`, `_clear_pkce` with existing signatures.

- [ ] **Step 1: Write tests** `tests/test_slack_token_storage.py`:

```python
import json
import time

import secure_store
from skills.slack import mcp_client as mc

FAKE = "aigator-fake-api-key"


def test_token_round_trip_encrypted():
    mc._save_token({"access_token": FAKE, "refresh_token": "r1", "expires_at": time.time() + 3600})
    assert mc._load_token()["access_token"] == FAKE
    assert secure_store.get_json("slack/token")["refresh_token"] == "r1"
    assert not list(secure_store._home().rglob("*.json"))


def test_load_token_missing_is_empty_dict():
    assert mc._load_token() == {}


def test_refresh_adopts_rotated_refresh_token(monkeypatch):
    mc._save_token({"access_token": "old", "refresh_token": "r1", "expires_at": 0})

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"ok": True, "access_token": FAKE, "refresh_token": "r2",
                               "expires_in": 3600}).encode()

    monkeypatch.setattr(mc.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert mc.get_oauth_token() == FAKE
    assert mc._load_token()["refresh_token"] == "r2"


def test_pkce_state_round_trip_and_clear():
    mc._save_pkce({"verifier": FAKE, "state": "s"})  # adjust arg shape to the real signature
    assert mc._load_pkce()
    mc._clear_pkce()
    assert not mc._load_pkce()
    assert not list(secure_store._home().rglob("*pkce*"))
```

Read lines 171-192 before finalizing the PKCE test and fix the argument shape of `_save_pkce` to the real signature.

- [ ] **Step 2: Run** `pytest tests/test_slack_token_storage.py -q` — plaintext/encryption tests FAIL, rotation test passes on old code.

- [ ] **Step 3: Implement.**

```python
def _load_token() -> dict:
    """Load stored Slack OAuth token (DPAPI-encrypted)."""
    return _secure_store().get_json("slack/token") or {}


def _save_token(data: dict) -> None:
    """Save the Slack OAuth token encrypted at rest.

    Also clears the user display-name cache so that workspace switches
    don't serve stale names from the previous workspace.
    """
    _secure_store().set_json("slack/token", data)
    # (keep the existing cache-clearing try/except block unchanged)
```

PKCE helpers follow the same pattern with `"slack/pkce"`; `_clear_pkce` calls `_secure_store().delete("slack/pkce")`. Remove `TOKEN_FILE`/`_PKCE_FILE` only after grepping that nothing else imports them (`web/routes/auth.py` was handled in Task 4).

- [ ] **Step 4: Run** `pytest tests/test_slack_token_storage.py -q` then `pytest tests -q -k slack` — PASS (existing tests patch `_load_token`/`_save_token` by name, which still exist).

- [ ] **Step 5: Commit**

```bash
git add web/skills/slack/mcp_client.py tests/test_slack_token_storage.py
git commit -m "feat: store Slack token and PKCE state in secure_store"
```

---

### Task 7: `config.json` PATs

**Files:**

- Modify: `web/config.py` (`load_config` 187-194, `_write_config_locked` 203-225; add helpers)
- Test: `tests/test_config_pat_storage.py`

**Interfaces:**

- Consumes: `secure_store.get/set/delete`, names `config/jira_api_token`, `config/jira_pat`, `config/confluence_pat`, `config/github_token`.
- Produces: `load_config()` returns the four PAT keys overlaid when present; `save_config`/`update_config` persist them to `secure_store` and never to `config.json`. A key absent or empty in the dict passed to a write is deleted from the store (full-replace semantics, matching the `save_jira_pat` sibling-key pops).

- [ ] **Step 1: Write the failing tests** `tests/test_config_pat_storage.py`:

```python
import json

import pytest

import config
import secure_store

FAKE = "aigator-fake-api-key"


@pytest.fixture
def cfgfile(tmp_path, monkeypatch):
    f = tmp_path / "gator" / "config.json"
    f.parent.mkdir()
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    return f


def test_save_moves_pats_out_of_json(cfgfile):
    config.save_config({"model": "x", "jira_pat": FAKE, "github_token": FAKE})
    on_disk = json.loads(cfgfile.read_text())
    assert on_disk == {"model": "x"}
    loaded = config.load_config()
    assert loaded["jira_pat"] == FAKE and loaded["github_token"] == FAKE
    assert secure_store.get("config/jira_pat") == FAKE


def test_backup_never_contains_pat(cfgfile):
    config.save_config({"jira_pat": FAKE})
    config.save_config({"jira_pat": FAKE, "x": 1})
    for p in cfgfile.parent.iterdir():
        assert FAKE not in p.read_text()


def test_absent_key_is_deleted_like_full_replace(cfgfile):
    config.save_config({"jira_pat": FAKE})
    cfg = config.load_config()
    cfg.pop("jira_pat")
    config.save_config(cfg)
    assert "jira_pat" not in config.load_config()
    assert secure_store.get("config/jira_pat") is None


def test_update_config_round_trip(cfgfile):
    config.update_config(lambda c: c.update({"confluence_pat": FAKE}))
    assert config.load_config()["confluence_pat"] == FAKE
    assert "confluence_pat" not in json.loads(cfgfile.read_text())


def test_legacy_plaintext_keys_migrate_and_backups_scrubbed(cfgfile):
    cfgfile.write_text(json.dumps({"model": "x", "jira_api_token": FAKE}))
    (cfgfile.parent / "config.json.bak").write_text(json.dumps({"jira_api_token": FAKE}))
    (cfgfile.parent / "config.json.bak2").write_text(json.dumps({"github_token": FAKE}))
    (cfgfile.parent / "config.corrupt.damaged").write_text('{"jira_pat": "' + FAKE + '" oops')
    cfg = config.load_config()
    assert cfg["jira_api_token"] == FAKE and cfg["model"] == "x"
    assert FAKE not in cfgfile.read_text()
    assert secure_store.get("config/jira_api_token") == FAKE
    for p in cfgfile.parent.iterdir():
        assert FAKE not in p.read_text(), p.name
    assert not (cfgfile.parent / "config.corrupt.damaged").exists()


def test_load_without_config_file_still_overlays(cfgfile):
    secure_store.set("config/github_token", FAKE)
    assert config.load_config()["github_token"] == FAKE
```

- [ ] **Step 2: Run, verify failures.** `pytest tests/test_config_pat_storage.py -q` — FAIL.

- [ ] **Step 3: Implement** in `web/config.py`. Add `import secure_store` with the other imports, then replace `load_config` and `_write_config_locked`:

```python
_PAT_KEYS = ("jira_api_token", "jira_pat", "confluence_pat", "github_token")


def _pat_name(key: str) -> str:
    return f"config/{key}"


def _read_config_file() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _scrub_config_copies() -> None:
    """Remove PAT keys from backup copies; delete unparseable *.damaged copies."""
    parent = CONFIG_FILE.parent
    if not parent.exists():
        return
    copies = list(parent.glob("config.json.bak*")) + list(parent.glob("config*.damaged"))
    for path in copies:
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = None
        if not isinstance(data, dict):
            try:
                path.unlink()
            except OSError as exc:
                _log.warning("Could not remove %s: %s", path.name, exc)
            continue
        if any(k in data for k in _PAT_KEYS):
            for key in _PAT_KEYS:
                data.pop(key, None)
            _write_json_locked(data, path, backup=False)


def _migrate_config_secrets(raw: dict) -> dict:
    """Move legacy plaintext PATs from config.json into secure_store (idempotent)."""
    with _CONFIG_LOCK:
        current = _read_config_file()
        legacy = {k: current[k] for k in _PAT_KEYS if k in current}
        if not legacy:
            return raw
        for key, value in legacy.items():
            if isinstance(value, str) and value.strip() and secure_store.get(_pat_name(key)) is None:
                secure_store.set(_pat_name(key), value)
        stripped = {k: v for k, v in current.items() if k not in _PAT_KEYS}
        _write_json_locked(stripped, CONFIG_FILE, backup=False)
        _scrub_config_copies()
        return stripped


def load_config() -> dict:
    """Load saved config; PATs are overlaid from secure_store."""
    raw = _read_config_file()
    if any(k in raw for k in _PAT_KEYS):
        raw = _migrate_config_secrets(raw)
    for key in _PAT_KEYS:
        value = secure_store.get(_pat_name(key))
        if value:
            raw[key] = value
    return raw


def save_config(data: dict) -> None:
    """Atomically write config and retain the prior complete file as backup."""
    with _CONFIG_LOCK:
        _write_config_locked(data)


def _write_config_locked(data: dict) -> None:
    for key in _PAT_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            secure_store.set(_pat_name(key), value)
        else:
            secure_store.delete(_pat_name(key))
    _write_json_locked({k: v for k, v in data.items() if k not in _PAT_KEYS}, CONFIG_FILE, backup=True)


def _write_json_locked(data: dict, target: Path, backup: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.exists():
        try:
            shutil.copy2(target, target.with_name(target.name + ".bak"))
        except OSError as exc:
            _log.warning("Could not refresh config backup: %s", exc)
    fd, tmp_name = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
```

Keep the original explanatory comment about the last-known-good backup above the `backup` block. Keep `update_config` unchanged (it calls `load_config` + `_write_config_locked`, so PATs round-trip). Ensure `Path` is imported in `config.py` (it already uses `Path` for `CONFIG_FILE`).

Pre-existing behavior note: previously `load_config()` returned `{}` for a non-dict JSON file; the new `_read_config_file` preserves that.

- [ ] **Step 4: Run** `pytest tests/test_config_pat_storage.py -q`, then the full suite `pytest tests -q` (config is imported everywhere; any failing test that wrote PATs straight into a temp `config.json` must now go through `save_config` or set `secure_store` — fix the test, not the code, unless it reveals a real regression).

- [ ] **Step 5: Verify the callers that matter.** Grep `jira_api_token|jira_pat|confluence_pat|github_token` across `web/` and confirm each reader uses `load_config()`/`cfg` (not the raw file). `routes/config_routes.py` `save_jira_pat` sibling-key pops (388-457), the Confluence save (~528) and GitHub save (~623) all hand a full dict to `save_config`/`update_config`, so no change is expected; if one passes a partial dict to `save_config`, that PAT would now be deleted — fix that caller to load first.

- [ ] **Step 6: Commit**

```bash
git add web/config.py tests/test_config_pat_storage.py
git commit -m "feat: keep config PATs in secure_store and scrub backups"
```

---

### Task 8: Startup migration sweep

**Files:**

- Modify: `web/app.py` (before the PAT-to-environment copy at ~95-116)
- Test: `tests/test_startup_secret_sweep.py`

**Interfaces:**

- Consumes: `secure_store.migrate_all()`, `config.load_config()` (which migrates PATs and scrubs backups).
- Produces: `app.py` imports/calls a small function `_sweep_legacy_secrets()` once at startup, exception-safe.

- [ ] **Step 1: Test** `tests/test_startup_secret_sweep.py`. Put the function in `secure_store`-adjacent code that is importable without running the whole app: define `sweep_legacy_secrets()` in `web/config.py` (it already owns config + imports `secure_store`):

```python
import json

import config
import secure_store

FAKE = "aigator-fake-api-key"


def test_sweep_migrates_tokens_and_config(tmp_path, monkeypatch):
    f = tmp_path / "gator" / "config.json"
    f.parent.mkdir()
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    f.write_text(json.dumps({"github_token": FAKE}))
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE}))

    config.sweep_legacy_secrets()

    assert not legacy.exists()
    assert FAKE not in f.read_text()
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}


def test_sweep_never_raises(monkeypatch):
    monkeypatch.setattr(secure_store, "migrate_all", lambda: 1 / 0)
    config.sweep_legacy_secrets()
```

- [ ] **Step 2: Run, verify failure.** Then implement in `web/config.py`:

```python
def sweep_legacy_secrets() -> None:
    """Startup pass: migrate any remaining plaintext tokens/PATs. Never raises."""
    try:
        secure_store.migrate_all()
    except Exception as exc:
        _log.error("legacy token sweep failed: %s", type(exc).__name__)
    try:
        load_config()  # migrates + scrubs legacy PATs and config backups
    except Exception as exc:
        _log.error("legacy config sweep failed: %s", type(exc).__name__)
```

In `web/app.py`, add `from config import sweep_legacy_secrets` alongside the existing `config` imports and call `sweep_legacy_secrets()` immediately before the block that copies PATs into `os.environ` (read ~80-120 first and place the call before any `load_config()` call that feeds that block).

- [ ] **Step 3: Run** `pytest tests/test_startup_secret_sweep.py -q` and `pytest tests -q -k "app or startup"` — PASS.

- [ ] **Step 4: Commit**

```bash
git add web/config.py web/app.py tests/test_startup_secret_sweep.py
git commit -m "feat: sweep legacy plaintext tokens at startup"
```

---

### Task 9: `POST /api/auth/clear`, revocation, Settings button

**Files:**

- Modify: `web/routes/auth.py` (new route; add `from security import verify_csrf` and `Depends`)
- Modify: `web/oauth/provider.py` (optional `revocation_endpoint: str = ""` field in the dataclass, `to_dict`, `from_dict`)
- Modify: `web/oauth/dcr.py` (pass `revocation_endpoint=meta.get("revocation_endpoint", "")` where `OAuthProvider(...)` is built, lines ~284 and ~376)
- Modify: `web/static/index.html` (new `srow` before the Google Workspace block at line ~678), `web/static/app.js` (click handler following the Google disconnect pattern ~15990-16035)
- Test: `tests/test_auth_clear_route.py`

**Interfaces:**

- Consumes: `secure_store.delete/list_names/get_json`, `routes.graph_client reset` (find the existing `reset_graph_client` via Grep and call it).
- Produces: `POST /api/auth/clear` with body `{"scope": "all" | "graph" | "slack" | "mcp" | "pats"}` (default `"all"`), CSRF-protected, returning `{"cleared": [<names>], "revoked": [<provider labels>]}`.

Scope mapping: `graph` -> `graph/token`, `graph/teams_token`, `graph/skype_token`; `slack` -> `slack/token`, `slack/pkce`; `mcp` -> every `oauth/*` name; `pats` -> `config/*` names (also `os.environ.pop` of `JIRA_API_TOKEN`, `JIRA_PAT_TOKEN`, `CONFLUENCE_PAT`, `GITHUB_TOKEN` so cleared credentials stop being used this session); `all` -> every name above.

- [ ] **Step 1: Write the tests** `tests/test_auth_clear_route.py` (build a `TestClient` the way other route tests do; grab a CSRF token from `/api/csrf`):

```python
import secure_store

FAKE = "aigator-fake-api-key"


def _seed():
    secure_store.set_json("graph/token", {"access_token": FAKE})
    secure_store.set_json("slack/token", {"access_token": FAKE})
    secure_store.set_json("oauth/p1", {"id": "p1", "token": {"access_token": FAKE}})
    secure_store.set("config/jira_pat", FAKE)


def test_clear_requires_csrf(client):
    _seed()
    assert client.post("/api/auth/clear", json={"scope": "all"}).status_code == 403
    assert secure_store.get_json("graph/token")


def test_clear_all(client, csrf_headers):
    _seed()
    r = client.post("/api/auth/clear", json={"scope": "all"}, headers=csrf_headers)
    assert r.status_code == 200
    assert secure_store.list_names() == []


def test_clear_single_scope_leaves_others(client, csrf_headers):
    _seed()
    client.post("/api/auth/clear", json={"scope": "slack"}, headers=csrf_headers)
    assert secure_store.get_json("slack/token") is None
    assert secure_store.get_json("graph/token")


def test_clear_revokes_slack_best_effort_and_survives_failure(client, csrf_headers, monkeypatch):
    import routes.auth as auth

    calls = []
    monkeypatch.setattr(auth, "_revoke_slack", lambda tok: calls.append(tok) or (_ for _ in ()).throw(RuntimeError("net")))
    _seed()
    r = client.post("/api/auth/clear", json={"scope": "slack"}, headers=csrf_headers)
    assert r.status_code == 200
    assert calls == [{"access_token": FAKE}]
    assert secure_store.get_json("slack/token") is None  # cleared locally even though revoke failed


def test_clear_invalid_scope_is_400(client, csrf_headers):
    assert client.post("/api/auth/clear", json={"scope": "nope"}, headers=csrf_headers).status_code == 400
```

Define the `client` and `csrf_headers` fixtures in the test file by copying the pattern from an existing route test that already exercises `verify_csrf` (Grep `tests/` for `X-CSRF-Token`); the invariants are what the tests above assert.

- [ ] **Step 2: Run, verify failure** (404 route missing).

- [ ] **Step 3: Implement the route** in `web/routes/auth.py`:

```python
_CLEAR_SCOPES = {
    "graph": ["graph/token", "graph/teams_token", "graph/skype_token"],
    "slack": ["slack/token", "slack/pkce"],
}
_PAT_ENV = ("JIRA_API_TOKEN", "JIRA_PAT_TOKEN", "CONFLUENCE_PAT", "GITHUB_TOKEN")


def _revoke_slack(token: dict) -> None:
    access = token.get("access_token", "")
    if not access:
        return
    req = urllib.request.Request(
        "https://slack.com/api/auth.revoke",
        data=urllib.parse.urlencode({"token": access}).encode(),
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10).read()


def _revoke_oauth(record: dict) -> None:
    prov = record.get("provider") or {}
    endpoint = prov.get("revocation_endpoint", "")
    token = record.get("token") or {}
    if not endpoint or not token.get("access_token"):
        return
    for hint, value in (("refresh_token", token.get("refresh_token")),
                        ("access_token", token.get("access_token"))):
        if value:
            body = urllib.parse.urlencode(
                {"token": value, "token_type_hint": hint, "client_id": prov.get("client_id", "")}
            ).encode()
            urllib.request.urlopen(urllib.request.Request(endpoint, data=body, method="POST"), timeout=10).read()


@router.post("/api/auth/clear", dependencies=[Depends(verify_csrf)])
async def clear_credentials(body: dict | None = None):
    scope = (body or {}).get("scope", "all")
    valid = {"all", "graph", "slack", "mcp", "pats"}
    if scope not in valid:
        raise HTTPException(400, f"scope must be one of {sorted(valid)}")
    names: list[str] = []
    if scope in ("all", "graph"):
        names += _CLEAR_SCOPES["graph"]
    if scope in ("all", "slack"):
        names += _CLEAR_SCOPES["slack"]
    if scope in ("all", "mcp"):
        names += secure_store.list_names("oauth/")
    if scope in ("all", "pats"):
        names += secure_store.list_names("config/")
    revoked: list[str] = []
    if scope in ("all", "slack"):
        tok = secure_store.get_json("slack/token")
        if tok:
            try:
                _revoke_slack(tok)
                revoked.append("slack")
            except Exception as exc:
                _log.warning("slack revoke failed: %s", type(exc).__name__)
    if scope in ("all", "mcp"):
        for name in secure_store.list_names("oauth/"):
            rec = secure_store.get_json(name)
            if rec:
                try:
                    _revoke_oauth(rec)
                    if (rec.get("provider") or {}).get("revocation_endpoint"):
                        revoked.append(name)
                except Exception as exc:
                    _log.warning("oauth revoke failed for %s: %s", name, type(exc).__name__)
    for name in names:
        secure_store.delete(name)
    if scope in ("all", "pats"):
        for var in _PAT_ENV:
            os.environ.pop(var, None)
    if scope in ("all", "graph"):
        reset_graph_client()  # name found via Grep; import it as the module already does elsewhere
    return {"cleared": sorted(set(names)), "revoked": revoked}
```

Use the module's existing `router`, logger name, and `HTTPException`/imports (add what is missing: `urllib.request`, `urllib.parse`, `os`, `secure_store`, `Depends`, `verify_csrf`). `test_clear_revokes_slack...` expects `_revoke_slack(tok)` to be called with the stored dict, which this does. Note the generic-OAuth record shape stores provider config under `"provider"` (see `oauth/flow.py` `data.get("provider")`), which is what `_revoke_oauth` reads.

`oauth/provider.py`: add field `revocation_endpoint: str = ""` after `registration_endpoint`, include it in `to_dict`, and `revocation_endpoint=d.get("revocation_endpoint", "")` in `from_dict`. `oauth/dcr.py`: add `revocation_endpoint=meta.get("revocation_endpoint", ""),` to both `OAuthProvider(...)` constructions that already read `meta[...]`.

- [ ] **Step 4: UI.** In `web/static/index.html`, insert before `<!-- ═══ Google Workspace ═══ -->` a row in the same markup style as its neighbors (copy the closest `srow` and its classes), labelled "Stored credentials" with a button `id="clear-credentials-btn"` and the text "Clear stored credentials" and a one-line hint "Removes saved sign-in tokens and API tokens from this computer. You will need to sign in again." In `web/static/app.js`, add a handler near the Google disconnect handler:

```javascript
document.getElementById('clear-credentials-btn')?.addEventListener('click', async () => {
  if (!confirm('Remove all stored sign-in tokens and API tokens from this computer?')) return;
  const post = () =>
    fetch('/api/auth/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.__CSRF_TOKEN__ },
      body: JSON.stringify({ scope: 'all' }),
    });
  let res = await post();
  if (res.status === 403) {
    const t = await (await fetch('/api/csrf')).json();
    window.__CSRF_TOKEN__ = t.token || t.csrf_token || window.__CSRF_TOKEN__;
    res = await post();
  }
  alert(res.ok ? 'Stored credentials cleared.' : 'Could not clear credentials.');
});
```

Mirror the exact CSRF-refetch code at `app.js` ~9634-9655 (use its field name for the `/api/csrf` response rather than the guess above) and use the app's existing toast helper instead of `alert` if one is used by the neighboring handlers.

- [ ] **Step 5: Run** `pytest tests/test_auth_clear_route.py -q` then `pytest tests -q`. Then start the dev server (`dev.ps1` / however the repo runs locally), open Settings, confirm the button renders, clears seeded entries, and the browser console shows no errors.

- [ ] **Step 6: Commit**

```bash
git add web/routes/auth.py web/oauth/provider.py web/oauth/dcr.py web/static/index.html web/static/app.js tests/test_auth_clear_route.py
git commit -m "feat: add clear-stored-credentials route and Settings control"
```

---

### Task 10: Guard test, rotation test for generic OAuth, docs

**Files:**

- Create: `tests/test_token_storage_guard.py`, `tests/test_oauth_rotation.py`
- Modify: `docs/security/threatmodel-remediation.md` (status row), `reset-auth.ps1`

- [ ] **Step 1: Guard test** — only an allowlist may mention the legacy token file names:

```python
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
PATTERN = re.compile(r"(?<![A-Za-z_])(teams_token|skype_token|skypetoken|\.pkce_pending)\.?json|token\.json")
ALLOWED = {
    "secure_store.py",                      # legacy migration table
    "graph_client.py",                      # legacy TOKEN_FILE symbols (canonical + 7 wrappers)
}


def test_no_module_references_plaintext_token_files():
    offenders = []
    for path in WEB.rglob("*.py"):
        if "tests" in path.parts or path.name in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if PATTERN.search(text):
            offenders.append(str(path.relative_to(WEB)))
    assert offenders == []
```

Run it; for each offender decide whether it is a genuine token-file access (convert to `secure_store`) or an unrelated string (tighten `PATTERN`; do NOT widen the allowlist for real accesses). `web/routes/auth.py` etc. must pass without being allowlisted.

- [ ] **Step 2: Generic OAuth rotation test** `tests/test_oauth_rotation.py`:

```python
import time

from oauth import flow, storage
from oauth.provider import OAuthProvider

FAKE = "aigator-fake-api-key"


def test_refresh_adopts_rotated_refresh_token(monkeypatch):
    prov = OAuthProvider(id="p1", mode="static", authorize_url="https://a.invalid/auth",
                         token_url="https://a.invalid/token", client_id="c")
    storage.save("p1", {"provider": prov.to_dict(),
                        "token": {"access_token": "old", "refresh_token": "r1", "expires_at": 0}})
    monkeypatch.setattr(
        flow, "_post_form",
        lambda url, params, secret="": {"access_token": FAKE, "refresh_token": "r2", "expires_in": 3600},
    )
    assert flow.get_access_token("p1") == FAKE
    assert storage.load("p1")["token"]["refresh_token"] == "r2"
```

- [ ] **Step 3: Run** `pytest tests/test_token_storage_guard.py tests/test_oauth_rotation.py -q` — PASS; then the whole suite `pytest tests -q` — PASS.

- [ ] **Step 4: Dev script and tracker.** Update `reset-auth.ps1` so it also removes `~\.gator\secrets` (keep its existing paths). In `docs/security/threatmodel-remediation.md`, change the OAuth row Status to **Implemented** and replace its Notes with: tokens and config PATs now DPAPI-encrypted under `~/.gator/secrets/`; legacy plaintext migrated on read and at startup; backups scrubbed; `POST /api/auth/clear` plus Settings button; rotation covered by tests. Known limitations: DPAPI does not stop same-user malware; Microsoft tokens cleared locally only (no server-side revocation); LLM API keys, `google_oauth_client_secret`, MCP `auth_value`/spawn env, and the env-var copy of PATs are second-pass; an unreadable blob (profile or password reset) requires re-authentication.

- [ ] **Step 5: Commit**

```bash
git add tests/test_token_storage_guard.py tests/test_oauth_rotation.py reset-auth.ps1 docs/security/threatmodel-remediation.md
git commit -m "test: guard against plaintext token files; docs: mark OAuth storage implemented"
```

---

## Self-Review

**Spec coverage:** section 1 -> Task 1; section 2 -> Tasks 2-7 (storage, Graph, Teams, Slack, config); section 3 migration -> Task 1 (`_migrate_legacy`, `migrate_all`), Task 7 (config scrub), Task 8 (startup sweep); section 4 rotation tests -> Tasks 3, 6, 10; section 5 -> Task 9 (and `/api/config/mcp/oauth/forget` is covered automatically by Task 2 because `flow.forget` calls `storage.delete`); testing section -> characterization tests inside Tasks 2/3/6/7, guard test in Task 10. Out-of-scope items are untouched.

**Placeholder scan:** The only deliberately deferred details are values the implementer must read from code before editing (Task 4 route paths/field names, Task 5 `TOKEN_FILE` mapping and return shapes, Task 6 PKCE argument shape, Task 9 CSRF helper/fixtures and `reset_graph_client` location); each is called out with where to read it and what invariant the test asserts.

**Type consistency:** `get/set/delete/list_names/get_json/set_json/migrate_all` names are identical wherever used; secret names are `graph/token`, `graph/teams_token`, `graph/skype_token`, `slack/token`, `slack/pkce`, `oauth/<id>`, `config/<key>` throughout; file stem for `oauth/p1` is `oauth~p1.bin`.
