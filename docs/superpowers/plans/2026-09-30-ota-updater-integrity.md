# OTA Updater Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OTA updater reject any installer that isn't checksum-verified, source-pinned, and signed by AI Gator's own code-signing certificate, closing finding `H_OTA_updater_supply_chain_compromise_due__02`.

**Architecture:** `build/release.bat` computes a SHA-256 of the built installer and embeds it in the `latest.json` manifest it publishes to `gh-pages`. `web/updater.py`'s state machine validates the manifest's `url`/`sha256` before entering `"available"`, and after downloading, verifies the file's SHA-256 and its Authenticode signature/thumbprint before entering `"ready"`. Any failure deletes the downloaded file and sets `"error"` with a specific reason, logged via the standard `logging.getLogger(__name__)` → `aigator.log` path already used throughout `web/`.

**Tech Stack:** Python 3.12 (`web/updater.py`), `httpx` (async download, already a dependency), stdlib `hashlib`/`subprocess`/`re`, Windows PowerShell `Get-AuthenticodeSignature` (built into every supported Windows version), Windows batch (`build/release.bat`, uses `certutil` which ships with Windows).

## Global Constraints

- Pinned installer URL pattern: `^https://github\.com/mkflyamd/aigator-releases/releases/download/v[^/]+/AIGatorInstaller\.exe$` (host, path prefix, and asset filename all fixed — from spec section "Manifest schema + URL/asset pinning").
- Pinned signing thumbprint: `B09F5EF43A1D7BF0F97C4883D723BA1AF67A7F42` — must stay identical to `SIGN_THUMBPRINT` in `build/build.bat:87`. Any future cert rotation requires updating both locations together (documented residual risk in the spec).
- `sha256` manifest field must match `^[0-9a-f]{64}$` (lowercase hex, 64 chars — matches `certutil`/`hashlib.hexdigest()` output).
- Error reason strings are fixed vocabulary, never include raw exception text that could leak file paths/internals: `"untrusted source URL"`, `"checksum mismatch"`, `"invalid signature"`, `"untrusted signer"`.
- Any verification failure must delete the downloaded file before returning (fail-closed — no exceptions).
- No changes to `web/routes/updater.py` — it already gates correctly on `_state.state`.

---

### Task 1: Embed SHA-256 checksum in the published manifest

**Files:**

- Modify: `build/release.bat:218-273`

**Interfaces:**

- Produces: `latest.json` manifest now contains a `"sha256"` field (lowercase 64-hex-char string) alongside `version`/`url`/`notes`. Task 2 depends on this field existing.

This is a release-ops batch script with no existing automated test coverage in this repo (no `.bat` tests exist); verification here is a manual dry run instead of TDD.

- [ ] **Step 1: Add checksum computation right after the installer existence check**

In `build/release.bat`, right after line 222 (`)` closing the `if not exist "%INSTALLER%" (...)` block for Step 5), insert:

```batch
:: ── Step 5b: Compute installer checksum ──────────────────────────────────────
echo [5b/8] Computing installer SHA-256 checksum...
set INSTALLER_SHA256=
set HASH_LINE=
for /f "skip=1 tokens=* delims=" %%A in ('certutil -hashfile "%INSTALLER%" SHA256') do (
    if not defined HASH_LINE set "HASH_LINE=%%A"
)
set "INSTALLER_SHA256=%HASH_LINE: =%"
if "%INSTALLER_SHA256%"=="" (
    echo ERROR: Could not compute installer checksum.
    exit /b 1
)
echo       SHA-256: %INSTALLER_SHA256%
```

- [ ] **Step 2: Embed the checksum in the manifest written to `gh-pages`**

In the same file, find the manifest heredoc-style block (originally lines 267-273):

```batch
(
echo {
echo   "version": "%NEW_VERSION%",
echo   "url": "https://github.com/%RELEASE_REPO%/releases/download/v%NEW_VERSION%/AIGatorInstaller.exe",
echo   "notes": "See release page for details"
echo }
) > "%MANIFEST_DIR%\latest.json"
```

Replace it with:

```batch
(
echo {
echo   "version": "%NEW_VERSION%",
echo   "url": "https://github.com/%RELEASE_REPO%/releases/download/v%NEW_VERSION%/AIGatorInstaller.exe",
echo   "sha256": "%INSTALLER_SHA256%",
echo   "notes": "See release page for details"
echo }
) > "%MANIFEST_DIR%\latest.json"
```

- [ ] **Step 3: Manual dry run**

Run (from a machine with an already-built installer at `build/dist/AIGatorInstaller.exe`):

```bash
cmd /c "certutil -hashfile build\dist\AIGatorInstaller.exe SHA256"
```

Confirm the output's hash line (second line, the one with hex pairs separated by spaces) is what Step 1's `for /f` logic extracts — i.e. the spaces-removed value is a 64-character lowercase hex string. Do **not** run the full `release.bat` (it tags/pushes/publishes a real release) — this is a static review of the batch logic plus the standalone `certutil` check above.

- [ ] **Step 4: Commit**

```bash
git add build/release.bat
git commit -m "build: embed installer SHA-256 checksum in OTA manifest"
```

---

### Task 2: Pin manifest URL/asset and validate checksum format before accepting an update

**Files:**

- Modify: `web/updater.py:1-83` (imports, `UpdateInfo` dataclass, `check_for_update()`)
- Test: `tests/test_updater.py`

**Interfaces:**

- Consumes: nothing from Task 1 at runtime (the manifest is fetched over HTTP; Task 1 only changes what's published).
- Produces: `UpdateInfo` gains a `sha256: str` field. `check_for_update()` only returns a non-`None` `UpdateInfo` (and only sets `_state.state = "available"`) when `url` matches the pinned pattern and `sha256` is well-formed. Task 3 and Task 4 consume `_state.info.sha256` and `_state.info.url`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_updater.py` (new imports `re` not needed in test file). First, **update** the existing `test_check_for_update_returns_info_when_newer` test — it currently uses a manifest with no `sha256` and a non-pinned `url`, which will now be correctly rejected. Replace its manifest fixture:

```python
@pytest.mark.asyncio
async def test_check_for_update_returns_info_when_newer(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.0.0")

    manifest_response = MagicMock()
    manifest_response.raise_for_status = MagicMock()
    manifest_response.json.return_value = {
        "version": "1.1.0",
        "url": "https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        "sha256": "a" * 64,
        "notes": "Bug fixes",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is not None
    assert result.version == "1.1.0"
    assert result.sha256 == "a" * 64
    assert updater._state.state == "available"
```

Then add two new tests at the end of the file:

```python
@pytest.mark.asyncio
async def test_check_for_update_rejects_untrusted_url(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.0.0")

    manifest_response = MagicMock()
    manifest_response.raise_for_status = MagicMock()
    manifest_response.json.return_value = {
        "version": "1.1.0",
        "url": "https://evil.example.com/AIGatorInstaller.exe",
        "sha256": "a" * 64,
        "notes": "",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.asyncio
async def test_check_for_update_rejects_malformed_sha256(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.0.0")

    manifest_response = MagicMock()
    manifest_response.raise_for_status = MagicMock()
    manifest_response.json.return_value = {
        "version": "1.1.0",
        "url": "https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        "sha256": "not-a-real-hash",
        "notes": "",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is None
    assert updater._state.state == "idle"
```

- [ ] **Step 2: Run tests to verify the new ones fail and the updated one fails**

Run: `python -m pytest tests/test_updater.py -v -k "check_for_update"`
Expected: `test_check_for_update_returns_info_when_newer` fails on `result.sha256` (attribute doesn't exist yet); `test_check_for_update_rejects_untrusted_url` and `test_check_for_update_rejects_malformed_sha256` fail because `result` is not `None` (no validation exists yet).

- [ ] **Step 3: Implement manifest validation**

In `web/updater.py`, add `re` to imports (top of file, alongside existing `import sys` etc.):

```python
import re
```

Add module-level constants right after `MANIFEST_URL = "..."` (line 14):

```python
# Pinned to the exact repo/path/asset this project publishes releases to.
_ALLOWED_INSTALLER_URL_RE = re.compile(
    r"^https://github\.com/mkflyamd/aigator-releases/releases/download/v[^/]+/AIGatorInstaller\.exe$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Must match build/build.bat's SIGN_THUMBPRINT. If the signing cert is ever
# rotated, update both locations together.
EXPECTED_SIGNING_THUMBPRINT = "B09F5EF43A1D7BF0F97C4883D723BA1AF67A7F42"  # pragma: allowlist secret
```

Update the `UpdateInfo` dataclass (lines 26-30):

```python
@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str
```

Update `check_for_update()` (lines 56-83), replacing the body of the `if Version(...) > Version(...)` branch:

```python
        if Version(data["version"]) > Version(get_current_version()):
            url = data.get("url", "")
            sha256 = data.get("sha256", "")
            if not _ALLOWED_INSTALLER_URL_RE.match(url) or not _SHA256_RE.match(sha256):
                _log.warning(
                    "Rejecting update manifest for v%s: untrusted source URL or malformed checksum",
                    data.get("version"),
                )
                _state.state = "idle"
                return None
            info = UpdateInfo(
                version=data["version"],
                url=url,
                sha256=sha256,
                notes=data.get("notes", ""),
            )
            _state.info = info
            _state.state = "available"
            return info
```

Add a module logger near the top of the file (after the imports block, before `MANIFEST_URL`):

```python
import logging

_log = logging.getLogger(__name__)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_updater.py -v -k "check_for_update"`
Expected: all `check_for_update` tests PASS, including the two new ones and the updated one.

- [ ] **Step 5: Run the full existing test file to check nothing else broke**

Run: `python -m pytest tests/test_updater.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add web/updater.py tests/test_updater.py
git commit -m "feat: pin OTA manifest URL and validate checksum format before accepting update"
```

---

### Task 3: Verify downloaded installer checksum before marking the update ready

**Files:**

- Modify: `web/updater.py:86-121` (`download_update()`)
- Test: `tests/test_updater.py`

**Interfaces:**

- Consumes: `_state.info.sha256` (produced by Task 2).
- Produces: `download_update()` now computes `hashlib.sha256(...)` of the downloaded file and only proceeds past that point on a match; on mismatch, deletes the file and sets `_state.state = "error"`, `_state.error = "checksum mismatch"`. Task 4 inserts its own check immediately after this one, before the final `_state.state = "ready"` assignment.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_updater.py`:

```python
@pytest.mark.asyncio
async def test_download_update_checksum_mismatch_sets_error_and_removes_file(tmp_path):
    import web.updater as updater

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        sha256="0" * 64,
        notes="",
    )

    async def fake_aiter_bytes(chunk_size=65536):
        yield b"not-the-real-installer-bytes"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.aiter_bytes = fake_aiter_bytes

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with (
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
        patch("web.updater.tempfile.gettempdir", return_value=str(tmp_path)),
    ):
        await updater.download_update()

    assert updater._state.state == "error"
    assert updater._state.error == "checksum mismatch"
    assert not (tmp_path / "AIGatorInstaller.exe").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_updater.py -v -k test_download_update_checksum_mismatch`
Expected: FAIL — today `download_update()` sets `state = "ready"` unconditionally after a successful stream, so `_state.state` is `"ready"`, not `"error"`.

- [ ] **Step 3: Implement checksum verification**

In `web/updater.py`, add `hashlib` to the imports:

```python
import hashlib
```

Modify `download_update()` (lines 86-121). Replace the end of the `try` block — everything from `_state._installer_path = str(tmp_path)` (line 110) through `_state.state = "ready"` (line 111) — with:

```python
        digest = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        if digest != _state.info.sha256:
            _log.warning(
                "OTA checksum mismatch for %s: expected %s, got %s",
                _state.info.url, _state.info.sha256, digest,
            )
            tmp_path.unlink(missing_ok=True)
            _state.state = "error"
            _state.error = "checksum mismatch"
            return

        _state._installer_path = str(tmp_path)
        _state.state = "ready"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_updater.py -v -k test_download_update_checksum_mismatch`
Expected: PASS

- [ ] **Step 5: Run the full test file**

Run: `python -m pytest tests/test_updater.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add web/updater.py tests/test_updater.py
git commit -m "feat: verify downloaded OTA installer checksum before marking it ready"
```

---

### Task 4: Verify Authenticode signature and pinned thumbprint before marking the update ready

**Files:**

- Modify: `web/updater.py:86-121,124-138` (`download_update()`, new `_verify_authenticode_signature()` helper, `launch_installer()` import cleanup)
- Test: `tests/test_updater.py`

**Interfaces:**

- Consumes: `EXPECTED_SIGNING_THUMBPRINT` (from Task 2), the checksum-verified file at `tmp_path` (from Task 3).
- Produces: `_verify_authenticode_signature(path: Path) -> tuple[bool, str]` — `(True, "")` on a valid signature matching the pinned thumbprint, else `(False, "invalid signature")` or `(False, "untrusted signer")`. `download_update()` calls this immediately after the checksum check and before setting `_state.state = "ready"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_updater.py`:

```python
@pytest.mark.asyncio
async def test_download_update_wrong_signer_sets_error_and_removes_file(tmp_path):
    import hashlib
    import web.updater as updater

    content = b"fake-installer-bytes"
    expected_sha = hashlib.sha256(content).hexdigest()

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        sha256=expected_sha,
        notes="",
    )

    async def fake_aiter_bytes(chunk_size=65536):
        yield content

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.aiter_bytes = fake_aiter_bytes

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_sig_result = MagicMock()
    mock_sig_result.returncode = 0
    mock_sig_result.stdout = "Valid|DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF\n"

    with (
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
        patch("web.updater.tempfile.gettempdir", return_value=str(tmp_path)),
        patch("web.updater.subprocess.run", return_value=mock_sig_result),
    ):
        await updater.download_update()

    assert updater._state.state == "error"
    assert updater._state.error == "untrusted signer"
    assert not (tmp_path / "AIGatorInstaller.exe").exists()


@pytest.mark.asyncio
async def test_download_update_invalid_signature_status_sets_error(tmp_path):
    import hashlib
    import web.updater as updater

    content = b"fake-installer-bytes"
    expected_sha = hashlib.sha256(content).hexdigest()

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        sha256=expected_sha,
        notes="",
    )

    async def fake_aiter_bytes(chunk_size=65536):
        yield content

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.aiter_bytes = fake_aiter_bytes

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_sig_result = MagicMock()
    mock_sig_result.returncode = 0
    mock_sig_result.stdout = "NotSigned|\n"

    with (
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
        patch("web.updater.tempfile.gettempdir", return_value=str(tmp_path)),
        patch("web.updater.subprocess.run", return_value=mock_sig_result),
    ):
        await updater.download_update()

    assert updater._state.state == "error"
    assert updater._state.error == "invalid signature"
    assert not (tmp_path / "AIGatorInstaller.exe").exists()


@pytest.mark.asyncio
async def test_download_update_valid_checksum_and_signature_sets_ready(tmp_path):
    import hashlib
    import web.updater as updater

    content = b"fake-installer-bytes"
    expected_sha = hashlib.sha256(content).hexdigest()

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        sha256=expected_sha,
        notes="",
    )

    async def fake_aiter_bytes(chunk_size=65536):
        yield content

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.aiter_bytes = fake_aiter_bytes

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_sig_result = MagicMock()
    mock_sig_result.returncode = 0
    mock_sig_result.stdout = f"Valid|{updater.EXPECTED_SIGNING_THUMBPRINT}\n"

    with (
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
        patch("web.updater.tempfile.gettempdir", return_value=str(tmp_path)),
        patch("web.updater.subprocess.run", return_value=mock_sig_result),
    ):
        await updater.download_update()

    assert updater._state.state == "ready"
    assert updater._state._installer_path == str(tmp_path / "AIGatorInstaller.exe")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_updater.py -v -k "signer or invalid_signature_status or valid_checksum_and_signature"`
Expected: FAIL — `_verify_authenticode_signature` doesn't exist yet, and `download_update()` doesn't call `subprocess.run` at all today, so `_state.state` ends up `"ready"` in all three cases (no signature gate exists).

- [ ] **Step 3: Implement signature verification**

In `web/updater.py`, add `subprocess` to the top-level imports (it's currently only imported locally inside `launch_installer`):

```python
import subprocess
```

Then remove the now-redundant `import subprocess` line inside `launch_installer()` (it becomes dead weight once the module-level import exists — delete that one line, function body otherwise unchanged).

Add the helper function right before `download_update()`:

```python
def _verify_authenticode_signature(path: Path) -> tuple[bool, str]:
    """Check the file's Authenticode signature via PowerShell. Returns (ok, reason)."""
    from proc_utils import no_window_kwargs

    try:
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                f"$sig = Get-AuthenticodeSignature -LiteralPath '{path}'; "
                "Write-Output \"$($sig.Status)|$($sig.SignerCertificate.Thumbprint)\"",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            **no_window_kwargs(),
        )
    except Exception:
        return False, "invalid signature"

    if result.returncode != 0:
        return False, "invalid signature"

    parts = result.stdout.strip().split("|")
    if len(parts) != 2:
        return False, "invalid signature"
    status, thumbprint = parts
    if status != "Valid":
        return False, "invalid signature"
    if thumbprint.strip().upper() != EXPECTED_SIGNING_THUMBPRINT:
        return False, "untrusted signer"
    return True, ""
```

Then update `download_update()` to call it right after the checksum check added in Task 3, before `_state._installer_path = str(tmp_path)`:

```python
        digest = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        if digest != _state.info.sha256:
            _log.warning(
                "OTA checksum mismatch for %s: expected %s, got %s",
                _state.info.url, _state.info.sha256, digest,
            )
            tmp_path.unlink(missing_ok=True)
            _state.state = "error"
            _state.error = "checksum mismatch"
            return

        sig_ok, sig_reason = _verify_authenticode_signature(tmp_path)
        if not sig_ok:
            _log.warning("OTA signature check failed for %s: %s", _state.info.url, sig_reason)
            tmp_path.unlink(missing_ok=True)
            _state.state = "error"
            _state.error = sig_reason
            return

        _state._installer_path = str(tmp_path)
        _state.state = "ready"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_updater.py -v -k "signer or invalid_signature_status or valid_checksum_and_signature"`
Expected: all PASS.

- [ ] **Step 5: Run the full test file**

Run: `python -m pytest tests/test_updater.py -v`
Expected: all tests PASS (should now be the original tests + the new ones from Tasks 2-4).

- [ ] **Step 6: Commit**

```bash
git add web/updater.py tests/test_updater.py
git commit -m "feat: verify Authenticode signature and pinned thumbprint before launching OTA installer"
```

---

### Task 5: Add route-level regression test for install-gating, then run the full suite

**Files:**

- Create: `tests/test_updater_routes.py`

**Interfaces:**

- Consumes: `web/routes/updater.py`'s existing `install_update()` endpoint (unmodified by this plan) and the bare `updater` module it imports (`web/routes/updater.py:5` does `import updater`, not `import web.updater` — this test must patch the same bare `updater` module, since pytest's `tests/conftest.py:12` puts `web/` on `sys.path` and a bare `import updater` resolves to a separate module object from `import web.updater`, used everywhere else in this plan).
- Produces: regression coverage proving `/api/update/install` refuses to launch anything unless state is `"ready"` — already true today via the early return in `install_update()`, and must stay true now that more paths can land in `"error"`.

This is a new test file (not appended to `tests/test_updater.py`) specifically to use the bare `import updater` / `from routes.updater import router` convention already established in `tests/test_files_route.py`, rather than mixing it with `tests/test_updater.py`'s `import web.updater as updater` convention in the same file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_updater_routes.py`:

```python
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from routes.updater import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_install_update_rejected_when_not_ready(client, monkeypatch):
    import updater

    updater._state = updater._UpdateState()
    updater._state.state = "error"

    called = {"launched": False}
    monkeypatch.setattr(updater, "launch_installer", lambda: called.__setitem__("launched", True))

    resp = client.post("/api/update/install")

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "reason": "Update not ready"}
    assert called["launched"] is False


def test_install_update_launches_when_ready(client, monkeypatch):
    import updater

    updater._state = updater._UpdateState()
    updater._state.state = "ready"

    called = {"launched": False}
    monkeypatch.setattr(updater, "launch_installer", lambda: called.__setitem__("launched", True))

    resp = client.post("/api/update/install")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert called["launched"] is True
```

- [ ] **Step 2: Run the test to verify it currently fails for the right reason**

Run: `python -m pytest tests/test_updater_routes.py -v`
Expected: both tests currently PASS already, since `install_update()`'s gating logic predates this plan and this task adds coverage rather than new behavior. Confirm this by temporarily commenting out the `if updater._state.state != "ready":` guard in `web/routes/updater.py:36` and re-running — `test_install_update_rejected_when_not_ready` must FAIL. Then restore the guard.

- [ ] **Step 3: Run the full test file to confirm both pass with the guard restored**

Run: `python -m pytest tests/test_updater_routes.py -v`
Expected: both tests PASS.

- [ ] **Step 4: Run the full project test suite to check for regressions elsewhere**

Run: `python -m pytest tests -q --tb=short --ignore=tests/mcp`
Expected: all tests PASS (matches the same invocation `build/release.bat:87` uses, minus the one deselected flaky test).

- [ ] **Step 5: Commit**

```bash
git add tests/test_updater_routes.py
git commit -m "test: add regression coverage for OTA install-gating on non-ready state"
```

---

## Post-implementation checklist

- [ ] Update `docs/security/threatmodel-remediation.md`'s row for `H_OTA_updater_supply_chain_compromise_due__02` to "Implemented" with a link to this plan and the spec.
- [ ] Move to the next finding in remediation order: Code-runner sandboxing (`H_Code_runner_skill_used_for_lateral_movem_06`) — brainstorm a new spec before planning/implementing.
