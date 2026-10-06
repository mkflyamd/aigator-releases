# Secure Store on macOS and Linux Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `web/secure_store.py` work on macOS and Linux (vault-backed envelope encryption) so token and PAT storage no longer fails there.

**Architecture:** Keep the blob layer unchanged. On non-Windows, `_protect`/`_unprotect` use AES-256-GCM with a random 32-byte master key held in the OS vault via `keyring` (Keychain / Secret Service). Linux without a vault falls back to a `0600` key file; macOS fails closed. Spec: `docs/superpowers/specs/2026-10-05-secure-store-macos-linux-design.md`.

**Tech Stack:** Python 3.12, `keyring`, `cryptography` (AESGCM), FastAPI, vanilla JS Settings page, PyInstaller spec, pytest.

## Global Constraints

- Windows behaviour is unchanged: DPAPI via ctypes, no new import on Windows.
- `keyring` and `cryptography` are imported lazily inside the non-Windows path only.
- Never print or log secret or key values; log exception types only.
- Fake credential in tests and docs: `aigator-fake-api-key` only.
- Commit messages carry no `Co-Authored-By` line. Project name is "AI Gator", never "POC".
- `secure_store.set` shadows the builtin `set` inside `web/secure_store.py`; do not call `set(...)` as a builtin there.
- Tests must never touch the real home: `tests/conftest.py` already redirects HOME and fakes `_protect`/`_unprotect`; vault tests re-point `_protect`/`_unprotect` at the vault functions themselves.

---

### Task 1: Non-Windows backend in `secure_store`

**Files:**
- Modify: `web/secure_store.py` (imports; `_protect`/`_unprotect` at lines 77-82; new vault section)
- Create: `tests/test_secure_store_vault.py`

**Interfaces:**
- Produces: `_platform() -> str`, `_use_dpapi() -> bool`, `_VaultUnavailable(Exception)`, `_vault_get() -> str | None`, `_vault_set(value: str) -> None`, `_key_file() -> Path`, `_master_key() -> bytes`, `_vault_protect(data: bytes) -> bytes`, `_vault_unprotect(blob: bytes) -> bytes`, `protection_level() -> str` returning `"os-vault"`, `"key-file"` or `"unavailable"`. Module globals `_MASTER: bytes | None`, `_LEVEL: str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_secure_store_vault.py`:

```python
import base64
import os
import stat
import types

import pytest

import secure_store

FAKE = "aigator-fake-api-key"
NAME = "config/jira_pat"


@pytest.fixture
def vault(monkeypatch):
    store = {}
    state = {"available": True}

    def get():
        if not state["available"]:
            raise secure_store._VaultUnavailable("no keyring")
        return store.get("key")

    def put(value):
        if not state["available"]:
            raise secure_store._VaultUnavailable("no keyring")
        store["key"] = value

    monkeypatch.setattr(secure_store, "_vault_get", get)
    monkeypatch.setattr(secure_store, "_vault_set", put)
    monkeypatch.setattr(secure_store, "_MASTER", None)
    monkeypatch.setattr(secure_store, "_LEVEL", "os-vault")
    monkeypatch.setattr(secure_store, "_platform", lambda: "linux")
    monkeypatch.setattr(secure_store, "_protect", secure_store._vault_protect)
    monkeypatch.setattr(secure_store, "_unprotect", secure_store._vault_unprotect)
    return types.SimpleNamespace(store=store, state=state)


def test_round_trip_and_unique_nonce(vault):
    a = secure_store._vault_protect(b"hello")
    b = secure_store._vault_protect(b"hello")
    assert a != b
    assert a[:1] == b"\x02"
    assert secure_store._vault_unprotect(a) == b"hello"


def test_key_created_once_and_reused(vault):
    secure_store.set(NAME, FAKE)
    first = vault.store["key"]
    secure_store._MASTER = None
    assert secure_store.get(NAME) == FAKE
    assert vault.store["key"] == first


def test_tampered_blob_returns_none(vault):
    secure_store.set(NAME, FAKE)
    path = secure_store._path(NAME)
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))
    assert secure_store.get(NAME) is None


def test_lost_key_returns_none(vault):
    secure_store.set(NAME, FAKE)
    vault.store.clear()
    secure_store._MASTER = None
    assert secure_store.get(NAME) is None


def test_linux_without_vault_uses_user_only_key_file(vault):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    key_file = secure_store._key_file()
    assert key_file.exists()
    if os.name == "posix":
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert secure_store.protection_level() == "key-file"
    secure_store._MASTER = None
    assert secure_store.get(NAME) == FAKE


def test_macos_without_vault_fails_closed(vault, monkeypatch):
    monkeypatch.setattr(secure_store, "_platform", lambda: "darwin")
    vault.state["available"] = False
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.set(NAME, FAKE)
    assert secure_store.protection_level() == "unavailable"
    assert not secure_store._key_file().exists()


def test_key_file_is_adopted_when_vault_appears(vault):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    key_file = secure_store._key_file()
    file_key = key_file.read_text().strip()
    vault.state["available"] = True
    secure_store._MASTER = None
    assert secure_store.get(NAME) == FAKE
    assert vault.store["key"] == file_key
    assert not key_file.exists()
    assert secure_store.protection_level() == "os-vault"


def test_first_use_race_uses_the_key_the_vault_returns(vault, monkeypatch):
    other = base64.b64encode(b"\x07" * 32).decode()
    monkeypatch.setattr(
        secure_store, "_vault_set", lambda value: vault.store.__setitem__("key", other)
    )
    assert secure_store._master_key() == b"\x07" * 32


def test_invalid_vault_value_raises(vault):
    vault.store["key"] = "not-base64!!"
    with pytest.raises(secure_store.SecureStoreError):
        secure_store._master_key()


def test_windows_level_does_not_touch_the_vault(vault, monkeypatch):
    monkeypatch.setattr(secure_store, "_platform", lambda: "win32")
    monkeypatch.setattr(secure_store, "_vault_get", lambda: pytest.fail("vault touched"))
    assert secure_store.protection_level() == "os-vault"


def test_legacy_plaintext_migrates_through_the_vault_backend(vault, tmp_path):
    legacy = tmp_path / "home" / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"access_token": "%s"}' % FAKE)
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}
    assert not legacy.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_secure_store_vault.py -q`
Expected: FAIL (`AttributeError` for `_VaultUnavailable` / `_vault_protect`).

- [ ] **Step 3: Implement**

In `web/secure_store.py` change the imports to include `base64`:

```python
import base64
import json
```

Replace the `_protect` / `_unprotect` block (currently `return _dpapi(True, data)` / `return _dpapi(False, data)`) with:

```python
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


def _vault_get() -> str | None:
    try:
        import keyring
        from keyring.errors import KeyringError

        try:
            return keyring.get_password(_VAULT_SERVICE, _VAULT_USER)
        except KeyringError as exc:
            raise _VaultUnavailable(type(exc).__name__) from exc
    except ImportError as exc:
        raise _VaultUnavailable("keyring not installed") from exc


def _vault_set(value: str) -> None:
    try:
        import keyring
        from keyring.errors import KeyringError

        try:
            keyring.set_password(_VAULT_SERVICE, _VAULT_USER, value)
        except KeyringError as exc:
            raise _VaultUnavailable(type(exc).__name__) from exc
    except ImportError as exc:
        raise _VaultUnavailable("keyring not installed") from exc


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
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        other = _read_key_file()
        if other is None:
            raise SecureStoreError("master key file vanished during creation")
        return other
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(base64.b64encode(key).decode("ascii"))
    return key


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
                _vault_set(base64.b64encode(key).decode("ascii"))
                again = _vault_get()
                if again is None:
                    raise _VaultUnavailable("vault did not return the stored key")
                stored_key = _decode_key(again)
                if adopted is not None and stored_key == adopted:
                    try:
                        _key_file().unlink()
                    except OSError as exc:
                        _log.error("could not remove adopted key file: %s", type(exc).__name__)
                key = stored_key
            else:
                key = _decode_key(stored)
            level = "os-vault"
        except _VaultUnavailable as exc:
            if _platform() != "linux":
                raise SecureStoreError(f"OS credential vault unavailable: {exc}") from exc
            _log.warning("no OS keyring available; using a user-only key file (reduced protection)")
            key = _file_key()
            level = "key-file"
        _MASTER, _LEVEL = key, level
        return key


def _vault_protect(data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    return _VAULT_TAG + nonce + AESGCM(_master_key()).encrypt(nonce, data, _ENTROPY)


def _vault_unprotect(blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

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
```

Also update the module docstring's second paragraph to say: "On Windows blobs are DPAPI-protected; on macOS and Linux they are AES-GCM encrypted with a master key kept in the OS vault (Linux without a keyring uses a user-only key file)." and replace the sentence about non-Windows raising `SecureStoreError` with "If no OS vault is usable on macOS, operations that must encrypt or decrypt raise SecureStoreError; there is no plaintext fallback."

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_secure_store_vault.py tests/test_secure_store.py -q`
Expected: all pass (the real-DPAPI test still runs on Windows).

- [ ] **Step 5: Commit**

```bash
git add web/secure_store.py tests/test_secure_store_vault.py
git commit -m "feat: secure_store backend for macOS and Linux (vault-held AES-GCM key, Linux key-file fallback)"
```

---

### Task 2: Protection-level route and Settings notice

**Files:**
- Modify: `web/routes/auth.py` (add route after `clear_credentials`)
- Modify: `web/static/index.html` (Stored credentials row, around line 680-684)
- Modify: `web/static/app.js` (`_initClearCredentialsSettings`, around line 15784)
- Create: `tests/test_auth_storage_route.py`

**Interfaces:**
- Consumes: `secure_store.protection_level() -> str`.
- Produces: `GET /api/auth/storage` returning `{"level": "os-vault" | "key-file" | "unavailable"}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_auth_storage_route.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import secure_store
from app import app


@pytest.mark.parametrize("level", ["os-vault", "key-file", "unavailable"])
def test_storage_route_reports_protection_level(monkeypatch, level):
    monkeypatch.setattr(secure_store, "protection_level", lambda: level)
    res = TestClient(app).get("/api/auth/storage")
    assert res.status_code == 200
    assert res.json() == {"level": level}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_auth_storage_route.py -q`
Expected: FAIL (404).

- [ ] **Step 3: Implement**

In `web/routes/auth.py`, directly above `@router.post("/api/auth/clear", ...)`:

```python
@router.get("/api/auth/storage")
def storage_level():  # sync: protection_level() may call the OS vault
    return {"level": secure_store.protection_level()}


```

In `web/static/index.html`, inside the `srow-info` of the Stored credentials row, after the existing `srow-sub` div:

```html
                <div class="srow-sub" id="storage-level-notice" hidden></div>
```

In `web/static/app.js`, in `_initClearCredentialsSettings`, immediately after `function _initClearCredentialsSettings() {`:

```javascript
  const notice = document.getElementById('storage-level-notice');
  if (notice) {
    fetch('/api/auth/storage')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        const msg = {
          'key-file':
            'Linux keyring not found — credentials are protected at a reduced level (key stored in a user-only file). Install or unlock gnome-keyring or KWallet, then restart AI Gator to upgrade.',
          unavailable:
            'Secure credential storage is unavailable, so sign-in tokens cannot be saved. Unlock the system keychain and restart AI Gator.',
        }[d && d.level];
        if (msg) {
          notice.textContent = msg;
          notice.hidden = false;
        }
      })
      .catch(() => {});
  }
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_auth_storage_route.py tests/test_auth_clear_route.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add web/routes/auth.py web/static/index.html web/static/app.js tests/test_auth_storage_route.py
git commit -m "feat: report credential protection level and show a Settings notice when reduced"
```

---

### Task 3: Dependencies and packaging

**Files:**
- Modify: `pyproject.toml` (dependencies list, after the `pywinpty` line)
- Modify: `web/requirements.txt` (after the `pystray` line)
- Modify: `packaging/aigator-backend.spec`
- Modify: `uv.lock` (regenerated)
- Create: `tests/test_packaging_vault_imports.py`

- [ ] **Step 1: Write the failing guard test**

Create `tests/test_packaging_vault_imports.py`:

```python
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_spec_bundles_keyring_backends_off_windows():
    spec = (ROOT / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    assert "keyring.backends" in spec
    assert 'copy_metadata("keyring")' in spec
    assert 'sys.platform != "win32"' in spec


def test_dependencies_are_declared_for_non_windows():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    reqs = (ROOT / "web" / "requirements.txt").read_text(encoding="utf-8")
    assert "keyring" in pyproject and "cryptography" in pyproject
    assert "keyring" in reqs and "cryptography" in reqs
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_packaging_vault_imports.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`pyproject.toml`, add after the `pywinpty` line:

```toml
  "keyring>=25; sys_platform != 'win32'",
  "cryptography; sys_platform != 'win32'",
```

`web/requirements.txt`, add after the `pystray` line:

```
keyring>=25; sys_platform != "win32"
cryptography; sys_platform != "win32"
```

`packaging/aigator-backend.spec`: add `import sys` after `from pathlib import Path`, and after the `hiddenimports += ["httpx_sse", ...]` line add:

```python
if sys.platform != "win32":
    from PyInstaller.utils.hooks import copy_metadata

    datas += copy_metadata("keyring")
    hiddenimports += collect_submodules("keyring.backends")
    hiddenimports += ["cryptography.hazmat.primitives.ciphers.aead"]
    if sys.platform.startswith("linux"):
        hiddenimports += ["secretstorage"] + collect_submodules("jeepney")
```

Regenerate the lock: `uv lock`. If it cannot reach the network, stop and report; do not hand-edit `uv.lock`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_packaging_vault_imports.py -q && git diff --stat uv.lock`
Expected: pass; `uv.lock` shows only keyring-related additions (plus transitive packages such as SecretStorage, jeepney, jaraco.* for non-Windows markers).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml web/requirements.txt packaging/aigator-backend.spec uv.lock tests/test_packaging_vault_imports.py
git commit -m "build: add keyring and cryptography for non-Windows secure store and bundle keyring backends"
```

---

### Task 4: Documentation and full verification

**Files:**
- Modify: `docs/superpowers/specs/2026-10-05-secure-store-macos-linux-design.md` (upgrade wording)
- Modify: `docs/superpowers/specs/2026-10-05-oauth-token-storage-design.md` (supersession note)
- Modify: `docs/security/threatmodel-remediation.md` (OAuth row)

- [ ] **Step 1: Spec wording.** In the macOS/Linux spec, change "The upgrade is automatic on the next write/read once a vault appears (step 2 adoption)." to "The upgrade happens on the next AI Gator start once a vault appears (step 2 adoption), because the key is cached per process." In the Testing section, add `unavailable` to the route test.

- [ ] **Step 2: Older spec note.** At the top of `2026-10-05-oauth-token-storage-design.md` (after the title), add: `> **Update:** the Windows-only scope below is superseded for macOS and Linux by [2026-10-05-secure-store-macos-linux-design.md](2026-10-05-secure-store-macos-linux-design.md).`

- [ ] **Step 3: Tracker row.** In the OAuth row of `docs/security/threatmodel-remediation.md`: replace "Windows only (no Keychain/Secret Service backend);" with "macOS and Linux use a vault-held AES-GCM key (Keychain / Secret Service via `keyring`), implemented but not yet smoke-tested on a real Mac or Linux desktop; Linux without a keyring uses a user-only key file (reduced protection, shown in Settings); macOS fails closed if the Keychain is unavailable;". Add the macOS/Linux spec and plan links to the Spec cell.

- [ ] **Step 4: Full verification**

Run: `python -m pytest tests -q -x --deselect tests/test_marketplace_installer.py`
Expected: all pass except the two known unrelated `httpserver` errors (do not deselect if they are not collection errors; just confirm the failures are only those two).

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs docs/security/threatmodel-remediation.md
git commit -m "docs: record macOS/Linux secure store scope in specs and tracker"
```

---

## Self-Review

- **Spec coverage:** backend selection and blob format (Task 1), master key lifecycle including adoption, race re-read, Linux fallback, macOS fail closed, lost/tampered key (Task 1), protection level + route + Settings notice (Task 2), dependencies and PyInstaller (Task 3), docs and tracker (Task 4). The manual Mac/Linux smoke test and the docx correction are release gates handled outside this plan.
- **Placeholders:** none.
- **Type consistency:** `_master_key() -> bytes`, `protection_level() -> str`, `_VaultUnavailable` and the `vault` test fixture use the same names across tasks.
