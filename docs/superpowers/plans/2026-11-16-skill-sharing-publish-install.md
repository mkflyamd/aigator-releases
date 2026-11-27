# Skill Sharing: Publish and Install (Plan 1A, backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Mine skill can be published to a OneDrive folder as an immutable, hash-verified bundle, and a recipient can review and install it, entirely through backend routes (no UI yet).

**Architecture:** A new helper package `web/skills/_sharing/` holds the pure logic (deterministic bundle, manifest, share link, message text, publisher, receiver) behind a provider object; `GraphSharingProvider` (Microsoft Graph, OneDrive) is the only implementation, and tests use an in-memory `FakeProvider` with the same methods. A new route module `web/routes/skill_sharing.py` wires the publisher and receiver to the existing marketplace install pipeline (tier policy, digest allow-list, grants, audit) instead of reimplementing it.

**Tech Stack:** Python 3.12, FastAPI, pytest (importlib mode, `pythonpath = web .`), Microsoft Graph through `skills._m365.helpers.GraphClient`.

Spec: `docs/superpowers/specs/2026-11-15-skill-sharing-design.md` (on branch `docs/skill-sharing-design`).

## Global Constraints

- The product is called **AI Gator**; never call it a POC.
- The only fake credential in tests, examples and docs is `aigator-fake-api-key`.
- Commit messages carry no `Co-Authored-By` line.
- Every new POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]` from `web/security.py`. Never add to `tests/csrf_route_baseline.txt`. Routes that create, send or delete go in `SENSITIVE_ROUTES` in `web/security.py`.
- No hosted backend: everything runs in the local FastAPI process and Microsoft Graph.
- People are in-tenant, the only role is "can use" (Graph `read`), and `sendInvitation` is `false`.
- Email, Teams and Slack messages are never sent automatically (this plan only builds the message text).
- The helper package is `web/skills/_sharing/` (leading underscore): non-underscore directories under `web/skills` are scanned as skills.
- State keys on `installed-skills.json` entries are `share_source`, `published_version`, `published_digest`, `shared_version`, `files_digest`, `shared_by`. Never use `source` (reserved for plugin-cache paths).
- A Mine entry is never a valid install target for a shared skill, even though the author's Mine entry also carries `share_source`.
- Digests: `bundle_sha256` verifies the download; `files_digest` (from `marketplace.permissions.files_digest`) is what the admin allow-list compares and what recipients pin; `has_scripts` and `requested_tools` are always recomputed from the extracted files, never trusted from the manifest.
- Run tests with `.venv/Scripts/python -m pytest` from `C:\Users\maykulka\POCs\aigator-skill-sharing-dev`.
- Do not push and do not open a PR.

## File Structure

Create:

- `web/skills/_sharing/__init__.py`: empty package marker.
- `web/skills/_sharing/errors.py`: `ShareError(code, message)`.
- `web/skills/_sharing/bundle.py`: deterministic zip, directory reader, manifest builder, `has_scripts`.
- `web/skills/_sharing/messages.py`: `aigator://share` link build/parse and the share message text.
- `web/skills/_sharing/provider.py`: `GraphSharingProvider`, the Graph-backed folder/file/permission operations.
- `web/skills/_sharing/publisher.py`: `publish(provider, skill_id, ...)`.
- `web/skills/_sharing/receiver.py`: `review(provider, ref, version=None)` and `install(provider, ref, *, version, digest)`.
- `web/routes/skill_sharing.py`: `/api/skills/share/{publish,review,install}`.
- `tests/skill_sharing/__init__.py`, `conftest.py` (FakeProvider plus the tier-policy fixture), and one `test_*.py` per module.

Modify:

- `web/skills/_files/errors.py`: map 412 to `conflict`.
- `web/skills/m365-email/graph_client.py`: `get_bytes`, `put_binary(extra_headers=)`.
- `web/skills/_m365/file_transfer.py`: `replace_in_folder` and a shared `_store_in_folder`.
- `web/skills/skill_manager/tools.py`: refuse edits to a skill that has a `share_source` and is not Mine.
- `web/app.py`: include the new router.
- `web/security.py`: `SENSITIVE_ROUTES` entries.

---

### Task 1: Deterministic bundle and manifest

**Files:**

- Create: `web/skills/_sharing/__init__.py`, `web/skills/_sharing/errors.py`, `web/skills/_sharing/bundle.py`
- Create: `tests/skill_sharing/__init__.py`, `tests/skill_sharing/conftest.py`, `tests/skill_sharing/test_bundle.py`

**Interfaces:**

- Consumes: `marketplace.permissions.declared_permissions(files) -> Permissions`, `marketplace.permissions.files_digest(files) -> str`, `marketplace.registry._parse_skill_md_frontmatter(text) -> dict`, `marketplace.installer.preview_package(local_zip_bytes=...) -> {"ok", "files"}`, `marketplace.github_fetcher.MAX_FILES`, `MAX_TOTAL_BYTES`.
- Produces:
  - `ShareError(code: str, message: str)` with attributes `.code`, `.message`.
  - `bundle.SCHEMA = 1`
  - `bundle.build_zip(files: dict[str, bytes]) -> bytes`
  - `bundle.bundle_sha256(data: bytes) -> str`
  - `bundle.has_scripts(files: dict[str, bytes]) -> bool`
  - `bundle.read_skill_dir(skill_dir: Path) -> dict[str, bytes]` (raises `ShareError("too_large", ...)` or `ShareError("invalid", ...)`)
  - `bundle.build_manifest(skill_id: str, version: int, files: dict[str, bytes], zip_bytes: bytes, *, author: str, created_at: str) -> dict`

- [ ] **Step 1: Create the package markers and the error type**

Create empty `web/skills/_sharing/__init__.py` and empty `tests/skill_sharing/__init__.py`.

Create `web/skills/_sharing/errors.py`:

```python
class ShareError(Exception):
    """A sharing failure the user can act on. ``code`` is a short stable slug."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
```

- [ ] **Step 2: Create the test conftest**

Create `tests/skill_sharing/conftest.py` (the tier-policy fixture is copied from `tests/marketplace/conftest.py`; the FakeProvider is added in Task 5):

```python
import json

import pytest


@pytest.fixture(autouse=True)
def _all_tiers_allowed(tmp_path):
    from sandbox import policy

    (tmp_path / "sandbox-policy.json").write_text(
        json.dumps({"marketplace_allowed_tiers": ["Native", "Verified", "Community", "Mine"]}), encoding="utf-8"
    )
    policy._reset_cache()
    yield
    policy._reset_cache()
```

- [ ] **Step 3: Write the failing tests**

Create `tests/skill_sharing/test_bundle.py`:

```python
import zipfile
import io

import pytest

from marketplace import installer
from marketplace.permissions import files_digest
from skills._sharing import bundle
from skills._sharing.errors import ShareError

SKILL_MD = b"---\nname: Weekly Report\ndescription: Summarise the week\n---\n\n# Weekly Report\n"


def test_zip_is_deterministic_regardless_of_dict_order():
    a = {"SKILL.md": SKILL_MD, "notes/ref.md": b"ref"}
    b = {"notes/ref.md": b"ref", "SKILL.md": SKILL_MD}
    assert bundle.build_zip(a) == bundle.build_zip(b)


def test_zip_round_trips_through_the_installer_reader():
    files = {"SKILL.md": SKILL_MD, "notes/ref.md": b"ref"}
    out = installer.preview_package(local_zip_bytes=bundle.build_zip(files))
    assert out["ok"] is True
    assert out["files"] == files


def test_zip_entries_use_fixed_timestamp_and_mode():
    data = bundle.build_zip({"SKILL.md": SKILL_MD})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        info = zf.getinfo("SKILL.md")
    assert info.date_time == (1980, 1, 1, 0, 0, 0)
    assert info.compress_type == zipfile.ZIP_STORED
    assert info.external_attr >> 16 == 0o644


def test_bundle_sha256_is_hex_sha256():
    assert bundle.bundle_sha256(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"  # pragma: allowlist secret


@pytest.mark.parametrize(
    "paths, expected",
    [
        (["SKILL.md"], False),
        (["SKILL.md", "reference/notes.md"], False),
        (["SKILL.md", "tools.py"], True),
        (["SKILL.md", "scripts/run.sh"], True),
        (["SKILL.md", "bin/tool"], True),
        (["SKILL.md", "helper.ps1"], True),
    ],
)
def test_has_scripts(paths, expected):
    assert bundle.has_scripts({p: b"x" for p in paths}) is expected


def test_read_skill_dir_reads_files_and_skips_junk(tmp_path):
    (tmp_path / "SKILL.md").write_bytes(SKILL_MD)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "ref.md").write_bytes(b"ref")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"junk")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_bytes(b"ref")
    assert bundle.read_skill_dir(tmp_path) == {"SKILL.md": SKILL_MD, "notes/ref.md": b"ref"}


def test_read_skill_dir_skips_symlinks(tmp_path):
    (tmp_path / "SKILL.md").write_bytes(SKILL_MD)
    outside = tmp_path.parent / "outside.txt"
    outside.write_bytes(b"secret")
    try:
        (tmp_path / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks need privileges on this machine")
    assert "link.txt" not in bundle.read_skill_dir(tmp_path)


def test_read_skill_dir_requires_skill_md(tmp_path):
    (tmp_path / "notes.md").write_bytes(b"x")
    with pytest.raises(ShareError) as err:
        bundle.read_skill_dir(tmp_path)
    assert err.value.code == "invalid"


def test_read_skill_dir_refuses_oversized_skill(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.github_fetcher.MAX_TOTAL_BYTES", 10)
    (tmp_path / "SKILL.md").write_bytes(SKILL_MD)
    with pytest.raises(ShareError) as err:
        bundle.read_skill_dir(tmp_path)
    assert err.value.code == "too_large"


def test_build_manifest_records_digests_and_recomputable_facts():
    files = {"SKILL.md": SKILL_MD, "tools.py": b"x = 1\n"}
    zip_bytes = bundle.build_zip(files)
    manifest = bundle.build_manifest(
        "weekly-report", 2, files, zip_bytes, author="Mayuresh Kulkarni", created_at="2026-11-16T10:00:00Z"
    )
    assert manifest == {
        "schema": 1,
        "name": "weekly-report",
        "title": "Weekly Report",
        "description": "Summarise the week",
        "version": 2,
        "author": "Mayuresh Kulkarni",
        "created_at": "2026-11-16T10:00:00Z",
        "bundle": "bundle.zip",
        "bundle_sha256": bundle.bundle_sha256(zip_bytes),
        "files_digest": files_digest(files),
        "has_scripts": True,
        "requested_tools": {"filesystem": [], "network": [], "invalid": False},
    }
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_bundle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._sharing.bundle'`.

- [ ] **Step 5: Implement `bundle.py`**

Create `web/skills/_sharing/bundle.py`:

```python
"""Deterministic skill bundles: the same files always produce the same zip bytes."""

import hashlib
import io
import zipfile
from pathlib import Path

from marketplace.permissions import declared_permissions, files_digest
from marketplace.registry import _parse_skill_md_frontmatter

from .errors import ShareError

SCHEMA = 1
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_SCRIPT_SUFFIXES = (".py", ".sh", ".ps1", ".bat", ".cmd", ".exe", ".js")
_SKIP_DIRS = {"__pycache__", ".git"}


def build_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[path])
    return buf.getvalue()


def bundle_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_scripts(files: dict[str, bytes]) -> bool:
    for path in files:
        if path.startswith(("scripts/", "bin/")) or "/scripts/" in path or "/bin/" in path:
            return True
        if path.lower().endswith(_SCRIPT_SUFFIXES):
            return True
    return False


def read_skill_dir(skill_dir: Path) -> dict[str, bytes]:
    from marketplace import github_fetcher

    files: dict[str, bytes] = {}
    total = 0
    for item in sorted(skill_dir.rglob("*")):
        rel = item.relative_to(skill_dir)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if item.is_symlink() or not item.is_file():
            continue
        data = item.read_bytes()
        total += len(data)
        if len(files) + 1 > github_fetcher.MAX_FILES or total > github_fetcher.MAX_TOTAL_BYTES:
            raise ShareError("too_large", "This skill is too large to share.")
        files[rel.as_posix()] = data
    if "SKILL.md" not in files:
        raise ShareError("invalid", "This skill has no SKILL.md, so it cannot be shared.")
    return files


def build_manifest(
    skill_id: str,
    version: int,
    files: dict[str, bytes],
    zip_bytes: bytes,
    *,
    author: str,
    created_at: str,
) -> dict:
    front = _parse_skill_md_frontmatter(files["SKILL.md"].decode("utf-8", errors="replace"))
    return {
        "schema": SCHEMA,
        "name": skill_id,
        "title": str(front.get("name") or skill_id),
        "description": str(front.get("description") or ""),
        "version": version,
        "author": author,
        "created_at": created_at,
        "bundle": "bundle.zip",
        "bundle_sha256": bundle_sha256(zip_bytes),
        "files_digest": files_digest(files),
        "has_scripts": has_scripts(files),
        "requested_tools": declared_permissions(files).to_dict(),
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_bundle.py -v`
Expected: PASS (the symlink test may skip).

If `test_build_manifest_records_digests_and_recomputable_facts` fails on `title`/`description`, print `_parse_skill_md_frontmatter(SKILL_MD.decode())` and adjust only the expected strings in the test to what the parser really returns for this frontmatter.

- [ ] **Step 7: Commit**

```bash
git add web/skills/_sharing/__init__.py web/skills/_sharing/errors.py web/skills/_sharing/bundle.py tests/skill_sharing/__init__.py tests/skill_sharing/conftest.py tests/skill_sharing/test_bundle.py
git commit -m "Add deterministic skill bundle and manifest builder for sharing"
```

---

### Task 2: Graph plumbing (412 mapping, byte download, If-Match upload, replace upload)

**Files:**

- Modify: `web/skills/_files/errors.py`
- Modify: `web/skills/m365-email/graph_client.py` (`put_binary` at about line 461, add `get_bytes` next to `get_text`)
- Modify: `web/skills/_m365/file_transfer.py` (`_put_small` at about line 127, `store_in_folder` at about line 265)
- Test: `tests/skill_sharing/test_plumbing.py`

**Interfaces:**

- Consumes: existing `GraphClient._request(method, url, *, headers, content, label)`, `_headers()`, `_encode_path()`; `file_transfer.Source`, `bytes_source`, `_put_small`, `_folder_item_path`, `safe_filename`, `SIMPLE_UPLOAD_MAX`.
- Produces:
  - `classify_status(412) == "conflict"`
  - `GraphClient.get_bytes(path: str) -> bytes`
  - `GraphClient.put_binary(path, data, content_type="application/octet-stream", extra_headers: dict | None = None)`
  - `file_transfer.replace_in_folder(gc, source, drive_id, folder_id, if_match: str = "") -> dict` returning the same result dict shape as `store_in_folder` (`status` of `saved` or `error`, with `id`, `name`, `web_url`, `size`, `drive_id`, `sha256`, and for errors `error_code`). With `if_match` set the source must be at most `SIMPLE_UPLOAD_MAX`; otherwise it returns an error result `error="if_match_needs_small_file"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/skill_sharing/test_plumbing.py`:

```python
from skills._files.errors import classify_status
from skills._m365 import file_transfer as ft
from skills._m365.helpers import GraphClient


class _FakeResponse:
    def __init__(self, content=b"", json_body=None):
        self.content = content
        self._json = json_body

    def json(self):
        return self._json


def _client(monkeypatch, calls, response):
    gc = object.__new__(GraphClient)
    monkeypatch.setattr(gc, "_headers", lambda: {"Authorization": "Bearer aigator-fake-api-key"}, raising=False)

    def fake_request(method, url, *, headers=None, content=None, label=""):
        calls.append({"method": method, "url": url, "headers": headers, "content": content})
        return response

    monkeypatch.setattr(gc, "_request", fake_request, raising=False)
    return gc


def test_412_is_a_conflict():
    assert classify_status(412) == "conflict"


def test_get_bytes_returns_raw_content(monkeypatch):
    calls = []
    gc = _client(monkeypatch, calls, _FakeResponse(content=b"PK\x03\x04data"))
    assert gc.get_bytes("/drives/d1/items/i1/content") == b"PK\x03\x04data"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/drives/d1/items/i1/content")


def test_put_binary_merges_extra_headers(monkeypatch):
    calls = []
    gc = _client(monkeypatch, calls, _FakeResponse(content=b"", json_body=None))
    gc.put_binary("/drives/d/items/f:/skill.json:/content", b"{}", "application/json", extra_headers={"If-Match": '"e1"'})
    headers = calls[0]["headers"]
    assert headers["If-Match"] == '"e1"'
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer aigator-fake-api-key"


def test_put_binary_without_extra_headers_is_unchanged(monkeypatch):
    calls = []
    gc = _client(monkeypatch, calls, _FakeResponse(content=b"", json_body=None))
    gc.put_binary("/drives/d/items/f:/a:/content", b"x")
    assert set(calls[0]["headers"]) == {"Authorization", "Content-Type"}


class _FakeGc:
    def __init__(self, error=None):
        self.error = error
        self.puts = []

    def put_binary(self, path, data, content_type="application/octet-stream", extra_headers=None):
        self.puts.append({"path": path, "data": data, "extra_headers": extra_headers})
        if self.error:
            raise self.error
        return {"id": "item1", "name": "skill.json", "webUrl": "https://x/skill.json", "size": len(data)}


class _Status(Exception):
    def __init__(self, status):
        super().__init__(f"http {status}")
        self.status_code = status


def test_replace_in_folder_uses_replace_conflict_behavior():
    gc = _FakeGc()
    out = ft.replace_in_folder(gc, ft.bytes_source("bundle.zip", b"abc"), "d1", "f1")
    assert out["status"] == "saved"
    assert out["id"] == "item1"
    assert "conflictBehavior=replace" in gc.puts[0]["path"]
    assert gc.puts[0]["extra_headers"] is None


def test_replace_in_folder_sends_if_match():
    gc = _FakeGc()
    ft.replace_in_folder(gc, ft.bytes_source("skill.json", b"{}"), "d1", "f1", if_match='"e1"')
    assert gc.puts[0]["extra_headers"] == {"If-Match": '"e1"'}


def test_replace_in_folder_412_is_a_conflict():
    gc = _FakeGc(error=_Status(412))
    out = ft.replace_in_folder(gc, ft.bytes_source("skill.json", b"{}"), "d1", "f1", if_match='"e1"')
    assert out["status"] == "error"
    assert out["error_code"] == "conflict"


def test_replace_in_folder_if_match_needs_a_small_file():
    gc = _FakeGc()
    big = ft.Source(name="big.bin", size=ft.SIMPLE_UPLOAD_MAX + 1, open=lambda: iter([]))
    out = ft.replace_in_folder(gc, big, "d1", "f1", if_match='"e1"')
    assert out["status"] == "error"
    assert out["error"] == "if_match_needs_small_file"
    assert gc.puts == []


def test_store_in_folder_still_renames_on_clash():
    gc = _FakeGc()
    ft.store_in_folder(gc, ft.bytes_source("a.txt", b"x"), "d1", "f1")
    assert "conflictBehavior=rename" in gc.puts[0]["path"]
    assert gc.puts[0]["extra_headers"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_plumbing.py -v`
Expected: FAIL (`412` returns `unknown`, `get_bytes` missing, `replace_in_folder` missing).

- [ ] **Step 3: Map 412 to conflict**

In `web/skills/_files/errors.py`, change the 409 branch to:

```python
    if status in (409, 412):
        return "conflict"
```

- [ ] **Step 4: Add `get_bytes` and `put_binary(extra_headers=)` to the Graph client**

In `web/skills/m365-email/graph_client.py`, add directly after `get_text`:

```python
    def get_bytes(self, path: str) -> bytes:
        """GET returning raw response bytes (for file content endpoints)."""
        url = f"{GRAPH_BASE}{self._encode_path(path)}"
        return self._request("GET", url, headers=self._headers(), label=path).content
```

Replace `put_binary` with:

```python
    def put_binary(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Upload raw bytes via PUT — used for OneDrive simple upload (<4 MB)."""
        url = f"{GRAPH_BASE}{self._encode_path(path)}"
        headers = {**self._headers(), "Content-Type": content_type, **(extra_headers or {})}
        resp = self._request("PUT", url, headers=headers, content=data, label=path)
        return resp.json() if resp.content else {"status": "ok"}
```

- [ ] **Step 5: Add `replace_in_folder` to `file_transfer.py`**

Change `_put_small` so it can send headers, passing the keyword only when there are headers (existing fakes keep working):

```python
def _put_small(gc, source, item_path, conflict, headers=None):
    data = b"".join(source.open())
    if len(data) != source.size:
        return None, "source_size_mismatch", hashlib.sha256(data).hexdigest()
    path = item_path + f":/content?@microsoft.graph.conflictBehavior={conflict}"
    item = gc.put_binary(path, data, extra_headers=headers) if headers else gc.put_binary(path, data)
    return item, "", hashlib.sha256(data).hexdigest()
```

Replace `store_in_folder` with these two functions plus the shared body:

```python
def _store_in_folder(gc, source: Source, drive_id: str, folder_id: str, conflict: str, if_match: str = "") -> dict:
    from .._files.errors import classify_graph_error

    name = safe_filename(source.name)
    if if_match and source.size > SIMPLE_UPLOAD_MAX:
        return _result("error", error="if_match_needs_small_file", error_code="unknown", name=name)
    item_path = _folder_item_path(drive_id, folder_id, name)
    try:
        if source.size <= SIMPLE_UPLOAD_MAX:
            headers = {"If-Match": if_match} if if_match else None
            item, err, sha = _put_small(gc, source, item_path, conflict, headers)
        else:
            item, err, sha = _put_large(gc, source, item_path, conflict, name)
    except Exception as e:
        return _result(
            "error",
            error="transfer_failed",
            detail=str(e)[:300],
            error_code=classify_graph_error(e),
            name=name,
        )
    if err:
        return _result("error", error=err, error_code="unknown", name=name)
    if (item or {}).get("size") != source.size:
        return _result(
            "error",
            error="size_mismatch",
            error_code="unknown",
            name=name,
            expected_size=source.size,
            reported_size=(item or {}).get("size"),
            hint="The stored file does not match the source size. Do not report it as saved.",
        )
    return _result("saved", sha256=sha, **{**_existing(item, drive_id), "size": source.size})


def store_in_folder(gc, source: Source, drive_id: str, folder_id: str, on_conflict: str = "rename") -> dict:
    """Upload into a folder addressed by drive and item ID. Never overwrites: a clash renames."""
    if on_conflict not in ("rename", "fail"):
        raise ValueError(f"on_conflict must be 'rename' or 'fail', got {on_conflict!r}")
    return _store_in_folder(gc, source, drive_id, folder_id, on_conflict)


def replace_in_folder(gc, source: Source, drive_id: str, folder_id: str, if_match: str = "") -> dict:
    """Upload into a folder, replacing a file of the same name. With ``if_match`` (an eTag) the
    replace fails with error_code ``conflict`` when the stored file changed since it was read."""
    return _store_in_folder(gc, source, drive_id, folder_id, "replace", if_match)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_plumbing.py tests/test_onedrive_provider.py -v`
Expected: PASS. If other tests exercise `store_in_folder`, also run `.venv/Scripts/python -m pytest tests -k "file_transfer or onedrive or file_ops" -q`.

- [ ] **Step 7: Commit**

```bash
git add web/skills/_files/errors.py web/skills/m365-email/graph_client.py web/skills/_m365/file_transfer.py tests/skill_sharing/test_plumbing.py
git commit -m "Add byte download, If-Match upload and replace-in-folder to the Graph file plumbing"
```

---

### Task 3: Graph sharing provider

**Files:**

- Create: `web/skills/_sharing/provider.py`
- Test: `tests/skill_sharing/test_provider.py`

**Interfaces:**

- Consumes: `ShareError` (Task 1); `skills._m365.file_transfer.bytes_source`, `store_in_folder(gc, source, drive_id, folder_id, on_conflict)`, `replace_in_folder(gc, source, drive_id, folder_id, if_match)` (Task 2); `GraphClient.get/post/get_bytes`; `skills._files.errors.classify_graph_error`, `http_status`.
- Produces: `provider.ROOT_FOLDER_NAME = "AI Gator Skills"` and `provider.GraphSharingProvider(gc)` with these methods. A _folder ref_ is the dict `{"drive_id": str, "folder_id": str, "web_url": str, "name": str}`. Every method raises `ShareError(code, message)` on failure, where `code` is one of `forbidden`, `not_found`, `conflict`, `throttled`, `locked`, `invalid`, `unknown`.
  - `default_root() -> folder ref`: the `AI Gator Skills` folder in the signed-in user's OneDrive, created if missing.
  - `child_folder(parent: dict, name: str, create: bool = True) -> dict | None`: the named subfolder; `None` when missing and `create` is false.
  - `read_file(folder: dict, name: str) -> tuple[bytes, str] | None`: `(content, eTag)` or `None` when the file is not there.
  - `read_json(folder: dict, name: str) -> tuple[dict, str] | None`: the same, parsed.
  - `write_file(folder: dict, name: str, data: bytes) -> None`: create or replace.
  - `write_json_create(folder: dict, name: str, doc: dict) -> None`: fails with `conflict` when the file exists.
  - `write_json_replace(folder: dict, name: str, doc: dict, etag: str) -> None`: fails with `conflict` when the stored eTag differs.
  - `grant_read(folder: dict, emails: list[str]) -> None`: "can use" for people in the tenant, no invitation email.

- [ ] **Step 1: Write the failing tests**

Create `tests/skill_sharing/test_provider.py`:

```python
import json
from urllib.parse import quote

import pytest

from skills._sharing.errors import ShareError
from skills._sharing.provider import ROOT_FOLDER_NAME, GraphSharingProvider


def q(value):
    return quote(value, safe="")


class _Err(Exception):
    def __init__(self, status):
        super().__init__(f"http {status}")
        self.status_code = status


class FakeGc:
    def __init__(self):
        self.items = {}
        self.blobs = {}
        self.get_errors = {}
        self.post_errors = {}
        self.posts = []
        self.puts = []
        self.put_error = None

    def get(self, path, params=None):
        if path in self.get_errors:
            raise self.get_errors[path]
        if path in self.items:
            return self.items[path]
        raise _Err(404)

    def get_bytes(self, path):
        return self.blobs[path]

    def post(self, path, body):
        self.posts.append((path, body))
        if path in self.post_errors:
            raise self.post_errors[path]
        return {
            "id": "new-" + body.get("name", "x"),
            "name": body.get("name", ""),
            "webUrl": "https://onedrive.example/" + body.get("name", ""),
            "folder": {},
            "parentReference": {"driveId": "d1"},
        }

    def put_binary(self, path, data, content_type="application/octet-stream", extra_headers=None):
        self.puts.append({"path": path, "data": data, "extra_headers": extra_headers})
        if self.put_error:
            raise self.put_error
        return {"id": "file1", "name": "x", "webUrl": "https://x", "size": len(data)}


def _folder_item(item_id, name):
    return {"id": item_id, "name": name, "webUrl": f"https://onedrive.example/{name}", "folder": {}, "parentReference": {"driveId": "d1"}}


ROOT_GET = f"/me/drive/root:/{q(ROOT_FOLDER_NAME)}"


def test_default_root_creates_the_folder_when_missing():
    gc = FakeGc()
    root = GraphSharingProvider(gc).default_root()
    assert root["drive_id"] == "d1"
    assert root["folder_id"] == "new-AI Gator Skills"
    assert gc.posts[0][0] == "/me/drive/root/children"
    assert gc.posts[0][1]["@microsoft.graph.conflictBehavior"] == "fail"


def test_default_root_reuses_an_existing_folder():
    gc = FakeGc()
    gc.items[ROOT_GET] = _folder_item("root1", ROOT_FOLDER_NAME)
    root = GraphSharingProvider(gc).default_root()
    assert root["folder_id"] == "root1"
    assert gc.posts == []


def test_default_root_survives_a_creation_race():
    gc = FakeGc()
    gets = iter([_Err(404), _folder_item("root1", ROOT_FOLDER_NAME)])

    def racing_get(path, params=None):
        out = next(gets)
        if isinstance(out, Exception):
            raise out
        return out

    gc.get = racing_get
    gc.post_errors["/me/drive/root/children"] = _Err(409)
    assert GraphSharingProvider(gc).default_root()["folder_id"] == "root1"


def test_a_file_in_the_way_of_a_folder_is_a_conflict():
    gc = FakeGc()
    gc.items[ROOT_GET] = {"id": "f1", "name": ROOT_FOLDER_NAME, "file": {}, "parentReference": {"driveId": "d1"}}
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).default_root()
    assert err.value.code == "conflict"


def test_child_folder_creates_under_the_parent():
    gc = FakeGc()
    parent = {"drive_id": "d1", "folder_id": "p1", "web_url": "", "name": "p"}
    child = GraphSharingProvider(gc).child_folder(parent, "weekly-report")
    assert child["drive_id"] == "d1"
    assert gc.posts[0][0] == "/drives/d1/items/p1/children"


def test_child_folder_without_create_returns_none_when_missing():
    gc = FakeGc()
    parent = {"drive_id": "d1", "folder_id": "p1", "web_url": "", "name": "p"}
    assert GraphSharingProvider(gc).child_folder(parent, "nope", create=False) is None
    assert gc.posts == []


def test_ids_are_percent_encoded():
    gc = FakeGc()
    parent = {"drive_id": "b!x/y", "folder_id": "01/AB=", "web_url": "", "name": "p"}
    seen = []
    gc.get = lambda path, params=None: seen.append(path) or (_ for _ in ()).throw(_Err(404))
    GraphSharingProvider(gc).child_folder(parent, "v1", create=False)
    assert seen == [f"/drives/{q('b!x/y')}/items/{q('01/AB=')}:/v1"]


def test_read_json_returns_document_and_etag():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    gc.items["/drives/d1/items/f1:/skill.json"] = {"id": "j1", "eTag": '"e1"', "file": {}}
    gc.blobs["/drives/d1/items/j1/content"] = json.dumps({"latest": 2}).encode()
    assert GraphSharingProvider(gc).read_json(folder, "skill.json") == ({"latest": 2}, '"e1"')


def test_read_json_returns_none_when_the_file_is_missing():
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    assert GraphSharingProvider(FakeGc()).read_json(folder, "skill.json") is None


def test_read_json_rejects_garbage():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    gc.items["/drives/d1/items/f1:/skill.json"] = {"id": "j1", "eTag": '"e1"', "file": {}}
    gc.blobs["/drives/d1/items/j1/content"] = b"not json"
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).read_json(folder, "skill.json")
    assert err.value.code == "invalid"


def test_forbidden_is_reported_with_a_code():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    gc.get_errors["/drives/d1/items/f1:/skill.json"] = _Err(403)
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).read_json(folder, "skill.json")
    assert err.value.code == "forbidden"


def test_write_file_replaces():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    GraphSharingProvider(gc).write_file(folder, "bundle.zip", b"abc")
    assert "conflictBehavior=replace" in gc.puts[0]["path"]


def test_write_json_create_fails_when_the_file_exists():
    gc = FakeGc()
    gc.put_error = _Err(409)
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).write_json_create(folder, "skill.json", {"latest": 1})
    assert err.value.code == "conflict"
    assert "conflictBehavior=fail" in gc.puts[0]["path"]


def test_write_json_replace_sends_if_match_and_maps_412():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    GraphSharingProvider(gc).write_json_replace(folder, "skill.json", {"latest": 2}, '"e1"')
    assert gc.puts[0]["extra_headers"] == {"If-Match": '"e1"'}
    gc.put_error = _Err(412)
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).write_json_replace(folder, "skill.json", {"latest": 3}, '"e1"')
    assert err.value.code == "conflict"


def test_grant_read_is_read_only_and_silent():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    GraphSharingProvider(gc).grant_read(folder, ["a@contoso.com", "b@contoso.com"])
    path, body = gc.posts[0]
    assert path == "/drives/d1/items/f1/invite"
    assert body == {
        "recipients": [{"email": "a@contoso.com"}, {"email": "b@contoso.com"}],
        "roles": ["read"],
        "requireSignIn": True,
        "sendInvitation": False,
    }


def test_grant_read_with_nobody_does_nothing():
    gc = FakeGc()
    GraphSharingProvider(gc).grant_read({"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}, [])
    assert gc.posts == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._sharing.provider'`.

- [ ] **Step 3: Implement the provider**

Create `web/skills/_sharing/provider.py`:

```python
"""Graph-backed storage for shared skills: folders, small files and permissions.

Every method raises ShareError. Nothing here deletes anything.
"""

import json
from urllib.parse import quote

from .._files.errors import classify_graph_error, http_status
from .._m365 import file_transfer as ft
from .errors import ShareError

ROOT_FOLDER_NAME = "AI Gator Skills"

_MESSAGES = {
    "forbidden": "You do not have permission to do that in this OneDrive folder.",
    "not_found": "That OneDrive folder or file could not be found.",
    "conflict": "The shared skill was changed by someone else. Reload it and try again.",
    "throttled": "OneDrive is busy. Try again in a minute.",
    "locked": "The file is locked in OneDrive. Try again later.",
}


def _q(value: str) -> str:
    return quote(value or "", safe="")


def _fail(exc: Exception) -> ShareError:
    code = classify_graph_error(exc)
    return ShareError(code, _MESSAGES.get(code) or f"OneDrive request failed: {str(exc)[:200]}")


def _ref(item: dict, drive_id: str = "") -> dict:
    drive_id = drive_id or (item.get("parentReference") or {}).get("driveId", "")
    if not drive_id or not item.get("id"):
        raise ShareError("unknown", "OneDrive returned a folder without an ID.")
    return {
        "drive_id": drive_id,
        "folder_id": item["id"],
        "web_url": item.get("webUrl", ""),
        "name": item.get("name", ""),
    }


class GraphSharingProvider:
    def __init__(self, gc):
        self._gc = gc

    def _get_or_create_folder(self, get_path: str, post_path: str, name: str, create: bool) -> dict | None:
        try:
            item = self._gc.get(get_path)
        except Exception as e:
            if http_status(e) != 404:
                raise _fail(e) from e
            if not create:
                return None
            body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
            try:
                item = self._gc.post(post_path, body)
            except Exception as e2:
                if http_status(e2) != 409:
                    raise _fail(e2) from e2
                try:
                    item = self._gc.get(get_path)
                except Exception as e3:
                    raise _fail(e3) from e3
        if not isinstance(item, dict) or "folder" not in item:
            raise ShareError("conflict", f"'{name}' already exists in OneDrive and is not a folder.")
        return item

    def default_root(self) -> dict:
        item = self._get_or_create_folder(
            f"/me/drive/root:/{_q(ROOT_FOLDER_NAME)}", "/me/drive/root/children", ROOT_FOLDER_NAME, True
        )
        return _ref(item)

    def child_folder(self, parent: dict, name: str, create: bool = True) -> dict | None:
        base = f"/drives/{_q(parent['drive_id'])}/items/{_q(parent['folder_id'])}"
        item = self._get_or_create_folder(f"{base}:/{_q(name)}", f"{base}/children", name, create)
        return _ref(item, parent["drive_id"]) if item else None

    def read_file(self, folder: dict, name: str) -> tuple[bytes, str] | None:
        drive = _q(folder["drive_id"])
        try:
            item = self._gc.get(f"/drives/{drive}/items/{_q(folder['folder_id'])}:/{_q(name)}")
        except Exception as e:
            if http_status(e) == 404:
                return None
            raise _fail(e) from e
        if not isinstance(item, dict) or not item.get("id"):
            return None
        try:
            data = self._gc.get_bytes(f"/drives/{drive}/items/{_q(item['id'])}/content")
        except Exception as e:
            raise _fail(e) from e
        return data, item.get("eTag", "")

    def read_json(self, folder: dict, name: str) -> tuple[dict, str] | None:
        found = self.read_file(folder, name)
        if found is None:
            return None
        data, etag = found
        try:
            doc = json.loads(data.decode("utf-8"))
        except ValueError as e:
            raise ShareError("invalid", f"{name} in the shared folder is not valid.") from e
        if not isinstance(doc, dict):
            raise ShareError("invalid", f"{name} in the shared folder is not valid.")
        return doc, etag

    def _check(self, out: dict) -> None:
        if out.get("status") == "saved":
            return
        code = out.get("error_code") or "unknown"
        raise ShareError(code, _MESSAGES.get(code) or f"Upload to OneDrive failed: {out.get('detail') or out.get('error')}")

    def write_file(self, folder: dict, name: str, data: bytes) -> None:
        self._check(ft.replace_in_folder(self._gc, ft.bytes_source(name, data), folder["drive_id"], folder["folder_id"]))

    def write_json_create(self, folder: dict, name: str, doc: dict) -> None:
        source = ft.bytes_source(name, json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"))
        self._check(ft.store_in_folder(self._gc, source, folder["drive_id"], folder["folder_id"], on_conflict="fail"))

    def write_json_replace(self, folder: dict, name: str, doc: dict, etag: str) -> None:
        source = ft.bytes_source(name, json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"))
        self._check(ft.replace_in_folder(self._gc, source, folder["drive_id"], folder["folder_id"], if_match=etag))

    def grant_read(self, folder: dict, emails: list[str]) -> None:
        if not emails:
            return
        body = {
            "recipients": [{"email": e} for e in emails],
            "roles": ["read"],
            "requireSignIn": True,
            "sendInvitation": False,
        }
        try:
            self._gc.post(f"/drives/{_q(folder['drive_id'])}/items/{_q(folder['folder_id'])}/invite", body)
        except Exception as e:
            raise _fail(e) from e
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_provider.py -v`
Expected: PASS.

If `test_write_json_create_fails_when_the_file_exists` fails because `FakeGc.put_error` raises on the first PUT only, confirm `store_in_folder` catches the exception and returns `error_code="conflict"` (it does through `classify_graph_error`, which uses the exception's `status_code`).

- [ ] **Step 5: Commit**

```bash
git add web/skills/_sharing/provider.py tests/skill_sharing/test_provider.py
git commit -m "Add the Graph-backed sharing provider for folders, small files and permissions"
```

---

### Task 4: Share link and message text

**Files:**

- Create: `web/skills/_sharing/messages.py`
- Test: `tests/skill_sharing/test_messages.py`

**Interfaces:**

- Consumes: `ShareError` (Task 1).
- Produces:
  - `messages.make_share_link(folder: dict) -> str`: `aigator://share?d=<base64url of {"v":1,"drive_id":...,"folder_id":...}>` (no padding).
  - `messages.parse_share_link(url: str) -> dict`: returns `{"drive_id": str, "folder_id": str}`; raises `ShareError("invalid_link", ...)` for anything else.
  - `messages.share_message(title: str, author: str, description: str, link: str, web_url: str = "") -> str`: the one plain-text body used for the email, Teams and Slack drafts. It is text only; nothing here sends anything.

- [ ] **Step 1: Write the failing tests**

Create `tests/skill_sharing/test_messages.py`:

```python
import base64
import json

import pytest

from skills._sharing import messages
from skills._sharing.errors import ShareError

FOLDER = {"drive_id": "b!abc", "folder_id": "01XYZ", "web_url": "https://onedrive.example/f", "name": "weekly-report"}


def _link_with(payload: bytes) -> str:
    return "aigator://share?d=" + base64.urlsafe_b64encode(payload).decode().rstrip("=")


def test_link_round_trips():
    link = messages.make_share_link(FOLDER)
    assert link.startswith("aigator://share?d=")
    assert "=" not in link.split("?d=", 1)[1]
    assert messages.parse_share_link(link) == {"drive_id": "b!abc", "folder_id": "01XYZ"}


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://share?d=abc",
        "aigator://other?d=abc",
        "aigator://share",
        "aigator://share?d=",
        "aigator://share?d=%%%",
        "aigator://share?d=abc&d=def",
        "aigator://share?x=1",
    ],
)
def test_bad_links_are_refused(url):
    with pytest.raises(ShareError) as err:
        messages.parse_share_link(url)
    assert err.value.code == "invalid_link"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        json.dumps({"v": 2, "drive_id": "d", "folder_id": "f"}).encode(),
        json.dumps({"v": 1, "drive_id": "d"}).encode(),
        json.dumps({"v": 1, "drive_id": "d", "folder_id": 5}).encode(),
        json.dumps({"v": 1, "drive_id": "d", "folder_id": "f", "extra": "x"}).encode(),
        json.dumps({"v": 1, "drive_id": "", "folder_id": "f"}).encode(),
        json.dumps({"v": 1, "drive_id": "d" * 600, "folder_id": "f"}).encode(),
    ],
)
def test_bad_payloads_are_refused(payload):
    with pytest.raises(ShareError) as err:
        messages.parse_share_link(_link_with(payload))
    assert err.value.code == "invalid_link"


def test_oversized_links_are_refused():
    with pytest.raises(ShareError):
        messages.parse_share_link("aigator://share?d=" + "A" * 5000)


def test_message_has_title_author_link_and_fallback():
    text = messages.share_message(
        "Weekly Report", "Mayuresh Kulkarni", "Summarise the week", "aigator://share?d=abc", "https://onedrive.example/f"
    )
    assert "Mayuresh Kulkarni" in text
    assert '"Weekly Report"' in text
    assert "Summarise the week" in text
    assert "aigator://share?d=abc" in text
    assert "https://onedrive.example/f" in text
    assert "review" in text.lower()


def test_message_without_description_or_web_url_has_no_blank_gaps():
    text = messages.share_message("Weekly Report", "Mayuresh Kulkarni", "", "aigator://share?d=abc")
    assert "\n\n\n" not in text
    assert "OneDrive" not in text


def test_message_flattens_whitespace_in_user_text():
    text = messages.share_message("Weekly\nReport", "May\r\nur", "line one\nline two", "aigator://share?d=abc")
    assert '"Weekly Report"' in text
    assert "line one line two" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_messages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._sharing.messages'`.

- [ ] **Step 3: Implement `messages.py`**

Create `web/skills/_sharing/messages.py`:

```python
"""The aigator://share link and the one message text used by every draft channel."""

import base64
import binascii
import json
from urllib.parse import parse_qs, urlparse

from .errors import ShareError

_MAX_LINK = 2048
_MAX_ID = 512
_MAX_DESCRIPTION = 300


def _invalid() -> ShareError:
    return ShareError("invalid_link", "This is not a valid AI Gator share link.")


def make_share_link(folder: dict) -> str:
    payload = json.dumps(
        {"v": 1, "drive_id": folder["drive_id"], "folder_id": folder["folder_id"]},
        separators=(",", ":"),
        sort_keys=True,
    )
    return "aigator://share?d=" + base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def parse_share_link(url: str) -> dict:
    if not isinstance(url, str) or len(url) > _MAX_LINK:
        raise _invalid()
    parts = urlparse(url)
    if parts.scheme != "aigator" or parts.netloc != "share" or parts.path not in ("", "/"):
        raise _invalid()
    values = parse_qs(parts.query).get("d") or []
    if len(values) != 1 or not values[0]:
        raise _invalid()
    encoded = values[0]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        doc = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError):
        raise _invalid() from None
    if not isinstance(doc, dict) or set(doc) != {"v", "drive_id", "folder_id"} or doc["v"] != 1:
        raise _invalid()
    drive_id, folder_id = doc["drive_id"], doc["folder_id"]
    for value in (drive_id, folder_id):
        if not isinstance(value, str) or not value or len(value) > _MAX_ID:
            raise _invalid()
    return {"drive_id": drive_id, "folder_id": folder_id}


def _flat(text: str, limit: int = 0) -> str:
    out = " ".join(str(text or "").split())
    return out[:limit] if limit else out


def share_message(title: str, author: str, description: str, link: str, web_url: str = "") -> str:
    lines = [f'{_flat(author)} shared the AI Gator skill "{_flat(title)}" with you.']
    summary = _flat(description, _MAX_DESCRIPTION)
    if summary:
        lines += ["", summary]
    lines += [
        "",
        "Open it in AI Gator. You can review what it does before anything is installed:",
        link,
    ]
    if web_url:
        lines += ["", f"If the link does not open, the skill is in OneDrive: {web_url}"]
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_messages.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_sharing/messages.py tests/skill_sharing/test_messages.py
git commit -m "Add the aigator share link parser and the shared draft message text"
```

---

### Task 5: Publisher

**Files:**

- Create: `web/skills/_sharing/publisher.py`
- Modify: `tests/skill_sharing/conftest.py` (add `FakeProvider`, `provider`, `skills_dir`, `make_mine` fixtures)
- Test: `tests/skill_sharing/test_publisher.py`

**Interfaces:**

- Consumes: `bundle.read_skill_dir/build_zip/build_manifest` (Task 1); the provider methods `default_root`, `child_folder`, `read_json`, `write_file`, `write_json_create`, `write_json_replace`, `grant_read` (Task 3); `messages.make_share_link` (Task 4); `marketplace.state.get_entry/update_entry`; `marketplace.installer.INSTALLED_SKILLS_DIR`; `marketplace.permissions.files_digest`.
- Produces: `publisher.publish(provider, skill_id: str, *, author: str, root: dict | None = None, people: Sequence[str] = ()) -> dict` returning:

```python
{
    "skill_id": str,
    "version": int,        # the published (or reused) version
    "reused": bool,        # True when the content was already published as `version`
    "digest": str,         # files_digest of the published content
    "folder": dict,        # folder ref of <chosen folder>/<skill-name>
    "link": str,           # aigator://share?d=...
    "web_url": str,        # OneDrive URL of the skill folder
}
```

`publisher.checked_doc(doc: dict) -> dict` is also public: it returns `doc` or raises `ShareError("invalid", ...)` unless `latest` is an int and `versions` is a list of objects. Task 6 reuses it.

Behaviour: refuses anything that is not a Mine entry (`ShareError("not_mine", ...)`); the destination is fixed on the entry's `share_source` after the first publish (a different `root` is ignored); identical content republished reuses the latest version and writes nothing; a new version writes `vN/bundle.zip`, then `vN/manifest.json`, then `skill.json` last (create-only the first time, `If-Match` after); the entry only gains `share_source`, `published_version` and `published_digest` after `skill.json` is written.

- [ ] **Step 1: Add the shared fixtures to the conftest**

Replace `tests/skill_sharing/conftest.py` with:

```python
import json

import pytest

from skills._sharing.errors import ShareError


@pytest.fixture(autouse=True)
def _all_tiers_allowed(tmp_path):
    from sandbox import policy

    (tmp_path / "sandbox-policy.json").write_text(
        json.dumps({"marketplace_allowed_tiers": ["Native", "Verified", "Community", "Mine"]}), encoding="utf-8"
    )
    policy._reset_cache()
    yield
    policy._reset_cache()


class FakeProvider:
    """In-memory stand-in for GraphSharingProvider with the same method names and error codes."""

    def __init__(self):
        self.folders = {}
        self.files = {}
        self.grants = []
        self.writes = []
        self.fail_on = {}
        self._n = 0

    def _maybe_fail(self, op):
        err = self.fail_on.pop(op, None)
        if err:
            raise err

    def _folder(self, parent_id, name, create):
        key = (parent_id, name)
        if key not in self.folders:
            if not create:
                return None
            self._n += 1
            self.folders[key] = {
                "drive_id": "d1",
                "folder_id": f"f{self._n}",
                "web_url": f"https://onedrive.example/{name}",
                "name": name,
            }
        return dict(self.folders[key])

    def default_root(self):
        return self._folder("", "AI Gator Skills", True)

    def child_folder(self, parent, name, create=True):
        return self._folder(parent["folder_id"], name, create)

    def read_file(self, folder, name):
        self._maybe_fail("read_file")
        return self.files.get((folder["folder_id"], name))

    def read_json(self, folder, name):
        found = self.read_file(folder, name)
        return (json.loads(found[0]), found[1]) if found else None

    def _put(self, folder, name, data):
        self._n += 1
        self.files[(folder["folder_id"], name)] = (data, f'"e{self._n}"')
        self.writes.append((folder["name"], name))

    def write_file(self, folder, name, data):
        self._maybe_fail("write_file")
        self._put(folder, name, data)

    def write_json_create(self, folder, name, doc):
        self._maybe_fail("write_json_create")
        if (folder["folder_id"], name) in self.files:
            raise ShareError("conflict", "exists")
        self._put(folder, name, json.dumps(doc).encode())

    def write_json_replace(self, folder, name, doc, etag):
        self._maybe_fail("write_json_replace")
        current = self.files.get((folder["folder_id"], name))
        if current is None or current[1] != etag:
            raise ShareError("conflict", "changed")
        self._put(folder, name, json.dumps(doc).encode())

    def grant_read(self, folder, emails):
        if emails:
            self.grants.append((folder["folder_id"], list(emails)))


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    from marketplace import installer

    root = tmp_path / "installed"
    root.mkdir()
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", root)
    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")
    return root


@pytest.fixture
def make_mine(skills_dir):
    from marketplace import installer

    def make(name="Weekly Report", instructions="Do the thing", extra=None):
        skill_id = installer.create_user_skill(name, "Summarise the week", instructions)["skill_id"]
        for rel, data in (extra or {}).items():
            path = skills_dir / "mine" / skill_id / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return skill_id

    return make
```

- [ ] **Step 2: Write the failing tests**

Create `tests/skill_sharing/test_publisher.py`:

```python
import json

import pytest

from marketplace import installer
from marketplace import state as skill_state
from marketplace.permissions import files_digest
from skills._sharing import bundle, messages, publisher
from skills._sharing.errors import ShareError


def _stored_doc(provider, folder, name):
    return json.loads(provider.files[(folder["folder_id"], name)][0])


def _skill_folder(provider, skill_id):
    root = provider.default_root()
    return provider.child_folder(root, skill_id, create=False)


def test_first_publish_writes_bundle_manifest_and_skill_json(provider, make_mine):
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="Mayuresh Kulkarni")

    assert out["version"] == 1
    assert out["reused"] is False
    folder = _skill_folder(provider, skill_id)
    v1 = provider.child_folder(folder, "v1", create=False)
    zip_bytes = provider.files[(v1["folder_id"], "bundle.zip")][0]
    manifest = _stored_doc(provider, v1, "manifest.json")
    assert manifest["bundle_sha256"] == bundle.bundle_sha256(zip_bytes)
    assert manifest["name"] == skill_id
    assert manifest["files_digest"] == out["digest"]
    doc = _stored_doc(provider, folder, "skill.json")
    assert doc["latest"] == 1
    assert doc["author"] == "Mayuresh Kulkarni"
    assert [v["version"] for v in doc["versions"]] == [1]
    assert messages.parse_share_link(out["link"]) == {"drive_id": "d1", "folder_id": folder["folder_id"]}


def test_skill_json_is_written_last(provider, make_mine):
    publisher.publish(provider, make_mine(), author="A")
    assert [name for _folder, name in provider.writes] == ["bundle.zip", "manifest.json", "skill.json"]


def test_entry_records_the_share_state(provider, make_mine):
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="A")
    entry = skill_state.get_entry(skill_id)
    assert entry["tier"] == "Mine"
    assert entry["published_version"] == 1
    assert entry["published_digest"] == out["digest"]
    assert entry["share_source"] == {
        "drive_id": "d1",
        "folder_id": out["folder"]["folder_id"],
        "web_url": out["web_url"],
    }


def test_republishing_unchanged_content_reuses_the_version(provider, make_mine):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author="A")
    writes = list(provider.writes)
    again = publisher.publish(provider, skill_id, author="A")
    assert again["version"] == 1
    assert again["reused"] is True
    assert provider.writes == writes


def test_changed_content_publishes_a_new_version_and_keeps_the_old_one(provider, make_mine, skills_dir):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    second = publisher.publish(provider, skill_id, author="A")

    assert second["version"] == 2
    assert second["digest"] != first["digest"]
    folder = _skill_folder(provider, skill_id)
    doc = _stored_doc(provider, folder, "skill.json")
    assert doc["latest"] == 2
    assert [v["version"] for v in doc["versions"]] == [1, 2]
    v1 = provider.child_folder(folder, "v1", create=False)
    assert (v1["folder_id"], "bundle.zip") in provider.files
    assert skill_state.get_entry(skill_id)["published_version"] == 2


def test_the_destination_is_fixed_after_the_first_publish(provider, make_mine, skills_dir):
    skill_id = make_mine()
    first = publisher.publish(provider, skill_id, author="A")
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    elsewhere = provider.child_folder(provider.default_root(), "Elsewhere")
    second = publisher.publish(provider, skill_id, author="A", root=elsewhere)
    assert second["folder"]["folder_id"] == first["folder"]["folder_id"]


def test_a_chosen_root_is_used_on_the_first_publish(provider, make_mine):
    chosen = provider.child_folder(provider.default_root(), "Team Skills")
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="A", root=chosen)
    assert provider.child_folder(chosen, skill_id, create=False)["folder_id"] == out["folder"]["folder_id"]


def test_only_mine_skills_can_be_published(provider, skills_dir):
    installer.save_installed([{"id": "someone-elses", "tier": "Community", "version": "1"}])
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, "someone-elses", author="A")
    assert err.value.code == "not_mine"
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, "does-not-exist", author="A")
    assert err.value.code == "not_mine"


def test_a_failed_skill_json_write_leaves_the_entry_alone_and_a_retry_succeeds(provider, make_mine):
    skill_id = make_mine()
    provider.fail_on["write_json_create"] = ShareError("forbidden", "no")
    with pytest.raises(ShareError):
        publisher.publish(provider, skill_id, author="A")
    assert "share_source" not in skill_state.get_entry(skill_id)
    out = publisher.publish(provider, skill_id, author="A")
    assert out["version"] == 1
    assert skill_state.get_entry(skill_id)["published_version"] == 1


def test_a_concurrent_edit_of_skill_json_is_a_conflict(provider, make_mine, skills_dir):
    skill_id = make_mine()
    publisher.publish(provider, skill_id, author="A")
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    provider.fail_on["write_json_replace"] = ShareError("conflict", "changed")
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A")
    assert err.value.code == "conflict"
    assert skill_state.get_entry(skill_id)["published_version"] == 1


def test_people_are_granted_read_on_the_skill_folder(provider, make_mine):
    out = publisher.publish(provider, make_mine(), author="A", people=["a@contoso.com", "b@contoso.com"])
    assert provider.grants == [(out["folder"]["folder_id"], ["a@contoso.com", "b@contoso.com"])]


def test_no_people_means_no_grant(provider, make_mine):
    publisher.publish(provider, make_mine(), author="A")
    assert provider.grants == []


def test_a_damaged_skill_json_is_refused(provider, make_mine):
    skill_id = make_mine()
    out = publisher.publish(provider, skill_id, author="A")
    provider.files[(out["folder"]["folder_id"], "skill.json")] = (b'{"latest": "two"}', '"e9"')
    with pytest.raises(ShareError) as err:
        publisher.publish(provider, skill_id, author="A")
    assert err.value.code == "invalid"


def test_published_files_digest_matches_the_local_files(provider, make_mine, skills_dir):
    skill_id = make_mine(extra={"notes/ref.md": b"ref"})
    out = publisher.publish(provider, skill_id, author="A")
    local = bundle.read_skill_dir(skills_dir / "mine" / skill_id)
    assert out["digest"] == files_digest(local)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_publisher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._sharing.publisher'`.

- [ ] **Step 4: Implement `publisher.py`**

Create `web/skills/_sharing/publisher.py`:

```python
"""Publish a Mine skill as an immutable version in a OneDrive folder."""

import json
from datetime import datetime, timezone
from typing import Sequence

from marketplace import installer
from marketplace import state as skill_state
from marketplace.permissions import files_digest

from . import bundle, messages
from .errors import ShareError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_bytes(doc: dict) -> bytes:
    return json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")


def checked_doc(doc: dict) -> dict:
    versions = doc.get("versions")
    if (
        not isinstance(doc.get("latest"), int)
        or isinstance(doc.get("latest"), bool)
        or not isinstance(versions, list)
        or not all(isinstance(v, dict) for v in versions)
    ):
        raise ShareError("invalid", "The shared skill's skill.json is damaged, so it was not changed.")
    return doc


def _latest_digest(doc: dict) -> str:
    for v in doc["versions"]:
        if v.get("version") == doc["latest"]:
            return v.get("files_digest", "")
    return ""


def _skill_folder(provider, entry: dict, skill_id: str, root: dict | None) -> dict:
    fixed = entry.get("share_source") or {}
    if fixed.get("folder_id") and fixed.get("drive_id"):
        return {
            "drive_id": fixed["drive_id"],
            "folder_id": fixed["folder_id"],
            "web_url": fixed.get("web_url", ""),
            "name": skill_id,
        }
    return provider.child_folder(root or provider.default_root(), skill_id)


def publish(provider, skill_id: str, *, author: str, root: dict | None = None, people: Sequence[str] = ()) -> dict:
    entry = skill_state.get_entry(skill_id)
    if not entry or entry.get("tier") != "Mine" or entry.get("id") != skill_id:
        raise ShareError("not_mine", "Only skills you created can be shared.")
    skill_dir = installer.INSTALLED_SKILLS_DIR / "mine" / skill_id
    if not skill_dir.is_dir():
        raise ShareError("not_found", "The skill's files could not be found.")

    files = bundle.read_skill_dir(skill_dir)
    digest = files_digest(files)
    folder = _skill_folder(provider, entry, skill_id, root)

    current = provider.read_json(folder, "skill.json")
    doc, etag = (checked_doc(current[0]), current[1]) if current else (None, "")

    if doc is not None and _latest_digest(doc) == digest:
        version, reused = doc["latest"], True
    else:
        version, reused = (doc["latest"] if doc else 0) + 1, False
        created_at = _now()
        zip_bytes = bundle.build_zip(files)
        manifest = bundle.build_manifest(skill_id, version, files, zip_bytes, author=author, created_at=created_at)
        version_folder = provider.child_folder(folder, f"v{version}")
        provider.write_file(version_folder, "bundle.zip", zip_bytes)
        provider.write_file(version_folder, "manifest.json", _json_bytes(manifest))
        new_doc = {
            "schema": bundle.SCHEMA,
            "name": skill_id,
            "title": manifest["title"],
            "description": manifest["description"],
            "author": author,
            "latest": version,
            "versions": [*(doc["versions"] if doc else []), {"version": version, "files_digest": digest, "created_at": created_at}],
            "updated_at": created_at,
        }
        if doc is None:
            provider.write_json_create(folder, "skill.json", new_doc)
        else:
            provider.write_json_replace(folder, "skill.json", new_doc, etag)

    provider.grant_read(folder, list(people))
    skill_state.update_entry(
        skill_id,
        {
            "share_source": {"drive_id": folder["drive_id"], "folder_id": folder["folder_id"], "web_url": folder["web_url"]},
            "published_version": version,
            "published_digest": digest,
        },
    )
    return {
        "skill_id": skill_id,
        "version": version,
        "reused": reused,
        "digest": digest,
        "folder": folder,
        "link": messages.make_share_link(folder),
        "web_url": folder["web_url"],
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_publisher.py -v`
Expected: PASS.

Note on `test_entry_records_the_share_state`: `get_entry` returns the entry from `installed-skills.json`; `create_user_skill` already wrote the Mine entry into the patched `skills_dir`.

- [ ] **Step 6: Commit**

```bash
git add web/skills/_sharing/publisher.py tests/skill_sharing/conftest.py tests/skill_sharing/test_publisher.py
git commit -m "Add the publisher: immutable versions, skill.json written last, destination fixed per skill"
```

---

### Task 6: Receiver

**Files:**

- Create: `web/skills/_sharing/receiver.py`
- Test: `tests/skill_sharing/test_receiver.py`

**Interfaces:**

- Consumes: `publisher.checked_doc` (Task 5); `bundle.bundle_sha256/has_scripts/SCHEMA` (Task 1); the provider methods `read_json`, `read_file`, `child_folder(parent, name, create=False)` (Task 3); `marketplace.installer.preview_package/install_skill_md`; `marketplace.permissions.files_digest/declared_permissions/summarize_package`; `marketplace.state.get_entry/update_entry`. A folder `ref` is the dict from `messages.parse_share_link` (`{"drive_id", "folder_id"}`) or a full folder ref from the provider.
- Produces:
  - `receiver.review(provider, ref: dict, version: int | None = None) -> dict` with keys `skill_id`, `title`, `description`, `author`, `version`, `latest`, `created_at`, `digest`, `has_scripts`, `requested_tools` (`{filesystem, network, invalid}`), `summary` (the `summarize_package` dict), `collision` (`""`, `"mine"`, `"installed"` or `"native"`). Writes nothing.
  - `receiver.install(provider, ref: dict, *, version: int, digest: str) -> dict`. Returns the installer's result dict unchanged on an installer failure (`{"ok": False, "error": ...}`, so the route can pass it to `_install_failure`), otherwise `{"ok": True, "skill_id", "permissions", "version", "digest", "shared_by"}`.
  - Both raise `ShareError` with the codes `not_found`, `invalid`, `tampered`, `content_changed`, `collision`, plus whatever the provider raises.

Behaviour: the downloaded zip must match the manifest's `bundle_sha256`, the extracted files must match the manifest's `files_digest`, and `has_scripts` and `requested_tools` are recomputed from the files, never read from the manifest. `install` re-fetches and re-verifies, and refuses unless the verified digest equals the digest the user approved. A skill whose name is already used by any installed entry (Mine included) or by a built-in skill is refused. The installed entry is a Community skill with `share_source`, `shared_version`, `files_digest` and `shared_by`.

- [ ] **Step 1: Write the failing tests**

Create `tests/skill_sharing/test_receiver.py`:

```python
import json
import shutil

import pytest

from marketplace import installer
from marketplace import state as skill_state
from sandbox import policy as _policy
from skills._sharing import messages, publisher, receiver
from skills._sharing.errors import ShareError


def _published(provider, make_mine, name="Weekly Report", **kwargs):
    skill_id = make_mine(name, **kwargs)
    return skill_id, publisher.publish(provider, skill_id, author="Mayuresh Kulkarni")


def _ref(out):
    return messages.parse_share_link(out["link"])


def _recipient(skills_dir):
    installer.save_installed([])
    shutil.rmtree(skills_dir / "mine")


def _version_folder(provider, out, version=1):
    return provider.child_folder(out["folder"], f"v{version}", create=False)


def _edit_manifest(provider, out, **changes):
    key = (_version_folder(provider, out)["folder_id"], "manifest.json")
    doc = json.loads(provider.files[key][0])
    doc.update(changes)
    provider.files[key] = (json.dumps(doc).encode(), '"edited"')


def test_review_returns_the_card_facts(provider, make_mine, skills_dir):
    skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    card = receiver.review(provider, _ref(out))

    assert card["skill_id"] == skill_id
    assert card["title"] == "Weekly Report"
    assert card["description"] == "Summarise the week"
    assert card["author"] == "Mayuresh Kulkarni"
    assert card["version"] == 1
    assert card["latest"] == 1
    assert card["digest"] == out["digest"]
    assert card["has_scripts"] is False
    assert card["requested_tools"] == {"filesystem": [], "network": [], "invalid": False}
    assert card["summary"]["digest"] == out["digest"]
    assert card["collision"] == ""


def test_review_writes_nothing(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    receiver.review(provider, _ref(out))
    assert installer.load_installed() == []
    assert not (skills_dir / "weekly-report").exists()


def test_review_defaults_to_the_latest_version_and_can_pick_an_older_one(provider, make_mine, skills_dir):
    skill_id, first = _published(provider, make_mine)
    (skills_dir / "mine" / skill_id / "SKILL.md").write_text("---\nname: Weekly Report\n---\n\nChanged\n", encoding="utf-8")
    second = publisher.publish(provider, skill_id, author="Mayuresh Kulkarni")
    _recipient(skills_dir)

    assert receiver.review(provider, _ref(second))["version"] == 2
    old = receiver.review(provider, _ref(second), version=1)
    assert old["version"] == 1
    assert old["latest"] == 2
    assert old["digest"] == first["digest"]


def test_review_recomputes_has_scripts_instead_of_trusting_the_manifest(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine, extra={"tools.py": b"x = 1\n"})
    _edit_manifest(provider, out, has_scripts=False, requested_tools={"filesystem": [], "network": [], "invalid": False})
    _recipient(skills_dir)
    assert receiver.review(provider, _ref(out))["has_scripts"] is True


def test_a_missing_skill_json_is_not_found(provider):
    with pytest.raises(ShareError) as err:
        receiver.review(provider, {"drive_id": "d1", "folder_id": "nothing-here"})
    assert err.value.code == "not_found"


def test_an_unknown_version_is_not_found(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    for version in (0, 2, -1):
        with pytest.raises(ShareError) as err:
            receiver.review(provider, _ref(out), version=version)
        assert err.value.code == "not_found"


def test_an_incomplete_version_is_not_found(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    del provider.files[(_version_folder(provider, out)["folder_id"], "bundle.zip")]
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "not_found"


def test_a_modified_bundle_is_tampered(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    key = (_version_folder(provider, out)["folder_id"], "bundle.zip")
    provider.files[key] = (provider.files[key][0] + b"x", '"edited"')
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "tampered"


def test_a_manifest_digest_that_does_not_match_the_files_is_tampered(provider, make_mine):
    _skill_id, out = _published(provider, make_mine)
    _edit_manifest(provider, out, files_digest="0" * 64)
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "tampered"


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "mine"},
        {"name": "../escape"},
        {"name": "Upper Case"},
        {"name": 7},
        {"schema": 2},
        {"version": 5},
        {"bundle_sha256": None},
    ],
)
def test_an_invalid_manifest_is_refused(provider, make_mine, changes):
    _skill_id, out = _published(provider, make_mine)
    _edit_manifest(provider, out, **changes)
    with pytest.raises(ShareError) as err:
        receiver.review(provider, _ref(out))
    assert err.value.code == "invalid"


def test_review_reports_a_name_collision(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    assert receiver.review(provider, _ref(out))["collision"] == "mine"

    installer.save_installed([{"id": "weekly-report", "tier": "Community", "version": "1"}])
    assert receiver.review(provider, _ref(out))["collision"] == "installed"


def test_review_reports_a_collision_with_a_built_in_skill(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine, name="Email")
    _recipient(skills_dir)
    assert receiver.review(provider, _ref(out))["collision"] == "native"


def test_install_writes_the_skill_and_records_where_it_came_from(provider, make_mine, skills_dir):
    skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)

    result = receiver.install(provider, _ref(out), version=1, digest=out["digest"])

    assert result["ok"] is True
    assert result["skill_id"] == skill_id
    assert result["shared_by"] == "Mayuresh Kulkarni"
    assert (skills_dir / skill_id / "SKILL.md").is_file()
    entry = skill_state.get_entry(skill_id)
    assert entry["tier"] == "Community"
    assert entry["version"] == "1"
    assert entry["shared_version"] == 1
    assert entry["files_digest"] == out["digest"]
    assert entry["shared_by"] == "Mayuresh Kulkarni"
    assert entry["share_source"] == {"drive_id": "d1", "folder_id": out["folder"]["folder_id"]}
    assert "source" not in entry


def test_install_refuses_when_the_content_is_not_what_was_approved(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest="0" * 64)
    assert err.value.code == "content_changed"
    assert installer.load_installed() == []
    assert not (skills_dir / "weekly-report").exists()


def test_install_refuses_a_tampered_bundle(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    key = (_version_folder(provider, out)["folder_id"], "bundle.zip")
    provider.files[key] = (provider.files[key][0] + b"x", '"edited"')
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "tampered"
    assert installer.load_installed() == []


def test_install_never_replaces_the_authors_own_skill(provider, make_mine, skills_dir):
    skill_id, out = _published(provider, make_mine)
    before = (skills_dir / "mine" / skill_id / "SKILL.md").read_bytes()
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "collision"
    assert (skills_dir / "mine" / skill_id / "SKILL.md").read_bytes() == before
    assert skill_state.get_entry(skill_id)["tier"] == "Mine"


def test_install_never_replaces_another_installed_skill(provider, make_mine, skills_dir):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    installer.save_installed([{"id": "weekly-report", "tier": "Community", "version": "9"}])
    with pytest.raises(ShareError) as err:
        receiver.install(provider, _ref(out), version=1, digest=out["digest"])
    assert err.value.code == "collision"
    assert skill_state.get_entry("weekly-report")["version"] == "9"


def test_install_passes_an_admin_block_through_as_the_installer_result(provider, make_mine, skills_dir, tmp_path):
    _skill_id, out = _published(provider, make_mine)
    _recipient(skills_dir)
    (tmp_path / "sandbox-policy.json").write_text(json.dumps({"approved_digests": []}), encoding="utf-8")
    _policy._reset_cache()

    result = receiver.install(provider, _ref(out), version=1, digest=out["digest"])

    assert result == {"ok": False, "error": "digest_not_approved", "digest": out["digest"]}
    assert installer.load_installed() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_receiver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._sharing.receiver'`.

- [ ] **Step 3: Implement `receiver.py`**

Create `web/skills/_sharing/receiver.py`:

```python
"""Review and install a shared skill. Nothing is trusted except the digest the user approved."""

import re
from pathlib import Path

from marketplace import installer
from marketplace import state as skill_state
from marketplace.permissions import declared_permissions, files_digest, summarize_package

from . import bundle
from .errors import ShareError
from .publisher import checked_doc

_NATIVE_DIR = Path(__file__).resolve().parent.parent
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RESERVED_IDS = {"mine"}
_COLLISION_TEXT = {
    "mine": "You already have a skill of your own with this name.",
    "installed": "A skill with this name is already installed.",
    "native": "This name is used by a built-in skill.",
}


def _invalid(message: str) -> ShareError:
    return ShareError("invalid", message)


def _check_manifest(manifest, version: int) -> None:
    ok = (
        isinstance(manifest, dict)
        and manifest.get("schema") == bundle.SCHEMA
        and manifest.get("version") == version
        and isinstance(manifest.get("name"), str)
        and bool(_ID.match(manifest["name"]))
        and manifest["name"] not in _RESERVED_IDS
        and isinstance(manifest.get("bundle_sha256"), str)
        and isinstance(manifest.get("files_digest"), str)
    )
    if not ok:
        raise _invalid("This shared skill's manifest is not valid, so it was not opened.")


def _fetch(provider, ref: dict, version: int | None) -> dict:
    found = provider.read_json(ref, "skill.json")
    if found is None:
        raise ShareError("not_found", "This shared skill could not be found. It may have been removed.")
    doc = checked_doc(found[0])
    wanted = doc["latest"] if version is None else version
    if isinstance(wanted, bool) or not isinstance(wanted, int) or not 1 <= wanted <= doc["latest"]:
        raise ShareError("not_found", "That version of the shared skill is not available.")

    version_folder = provider.child_folder(ref, f"v{wanted}", create=False)
    manifest_read = provider.read_json(version_folder, "manifest.json") if version_folder else None
    bundle_read = provider.read_file(version_folder, "bundle.zip") if version_folder else None
    if manifest_read is None or bundle_read is None:
        raise ShareError("not_found", f"Version {wanted} of this shared skill is incomplete.")
    manifest, zip_bytes = manifest_read[0], bundle_read[0]
    _check_manifest(manifest, wanted)

    if bundle.bundle_sha256(zip_bytes) != manifest["bundle_sha256"]:
        raise ShareError("tampered", "The downloaded skill does not match what the author published.")
    preview = installer.preview_package(local_zip_bytes=zip_bytes)
    if not preview.get("ok"):
        raise _invalid(preview.get("error", "The shared skill could not be read."))
    files = preview["files"]
    if "SKILL.md" not in files:
        raise _invalid("The shared skill has no SKILL.md.")
    digest = files_digest(files)
    if digest != manifest["files_digest"]:
        raise ShareError("tampered", "The skill's files do not match what the author published.")
    return {
        "doc": doc,
        "manifest": manifest,
        "version": wanted,
        "zip_bytes": zip_bytes,
        "files": files,
        "digest": digest,
    }


def _collision(skill_id: str) -> str:
    entry = skill_state.get_entry(skill_id)
    if entry:
        return "mine" if entry.get("tier") == "Mine" else "installed"
    if (_NATIVE_DIR / skill_id).exists():
        return "native"
    return ""


def _author(manifest: dict) -> str:
    return str(manifest.get("author") or "")[:200]


def review(provider, ref: dict, version: int | None = None) -> dict:
    got = _fetch(provider, ref, version)
    manifest, files = got["manifest"], got["files"]
    return {
        "skill_id": manifest["name"],
        "title": str(manifest.get("title") or manifest["name"]),
        "description": str(manifest.get("description") or ""),
        "author": _author(manifest),
        "version": got["version"],
        "latest": got["doc"]["latest"],
        "created_at": str(manifest.get("created_at") or ""),
        "digest": got["digest"],
        "has_scripts": bundle.has_scripts(files),
        "requested_tools": declared_permissions(files).to_dict(),
        "summary": summarize_package(files),
        "collision": _collision(manifest["name"]),
    }


def install(provider, ref: dict, *, version: int, digest: str) -> dict:
    got = _fetch(provider, ref, version)
    if not digest or got["digest"] != digest:
        raise ShareError("content_changed", "The skill changed since you reviewed it. Review it again before installing.")
    skill_id = got["manifest"]["name"]
    collision = _collision(skill_id)
    if collision:
        raise ShareError("collision", _COLLISION_TEXT[collision])

    result = installer.install_skill_md(
        skill_id, "", str(got["version"]), "Community", "", got["zip_bytes"], expected_digest=digest
    )
    if not result.get("ok"):
        return result
    author = _author(got["manifest"])
    skill_state.update_entry(
        result["skill_id"],
        {
            "share_source": {"drive_id": ref["drive_id"], "folder_id": ref["folder_id"]},
            "shared_version": got["version"],
            "files_digest": digest,
            "shared_by": author,
        },
    )
    return {**result, "version": got["version"], "digest": digest, "shared_by": author}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_receiver.py -v`
Expected: PASS.

Two facts the tests rely on: `installer.install_skill_md` derives nothing from the empty `skill_md` argument when it is given zip bytes, and `skill_id` is passed explicitly so the installed folder name always equals the manifest `name`. If `test_review_reports_a_collision_with_a_built_in_skill` fails because `email` is no longer a built-in skill folder, pick any directory name that exists under `web/skills/` and has no underscore prefix.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_sharing/receiver.py tests/skill_sharing/test_receiver.py
git commit -m "Add the receiver: verify digests, recompute facts, refuse name collisions, install pinned to the approved digest"
```

---

### Task 7: Routes, registration and the CSRF inventory

**Files:**

- Create: `web/routes/skill_sharing.py`
- Modify: `web/app.py` (import near line 89, `include_router` near line 940)
- Modify: `web/security.py` (`SENSITIVE_ROUTES`, between the `scheduler` and `slack` entries)
- Test: `tests/skill_sharing/test_routes.py`

**Interfaces:**

- Consumes: `publisher.publish`, `receiver.review`, `receiver.install`, `messages.parse_share_link`, `provider.GraphSharingProvider`, `errors.ShareError`; from `routes.marketplace`: `_enforce_tier(skill_id, tier)`, `_require_digest(digest)`, `_install_failure(result) -> HTTPException`, `_record_grants(result, skill_id)`, `_note_tools_error(result, loaded)`; `marketplace.skill_audit.log_install(skill_id, tier, source, digest)`; `shared.load_installed_skill_prompts`; `marketplace.loader.load_skill_tools(skill_id, skill_dir, tier)`; `skills._m365.helpers.GraphClient`.
- Produces three routes, all `POST` with `dependencies=[Depends(verify_csrf)]`:
  - `/api/skills/share/publish` takes `{"skill_id": str, "people": [email, ...] (at most 50), "root": {"drive_id", "folder_id", "web_url"?, "name"?} | null}` and returns the dict from `publisher.publish`.
  - `/api/skills/share/review` takes `{"link": str, "version": int | null}` and returns the dict from `receiver.review`. Nothing is installed.
  - `/api/skills/share/install` takes `{"link": str, "version": int, "digest": str}` and returns the installer result plus `version`, `digest`, `shared_by`. A failure is `{"detail": {"error": code, "message": text}}`.
  - Module-level seams the tests patch: `_provider() -> GraphSharingProvider` and `_author_name() -> str`.
  - Error status mapping (403 is not used for sharing errors, because the app already answers 403 for CSRF and policy): `not_found` 404; `invalid`, `invalid_link`, `too_large`, `not_mine` 400; `conflict`, `collision`, `content_changed`, `tampered` 409; `throttled` 429; `locked` 423; `forbidden` 422; anything else 502. The install route keeps the marketplace's own mapping for installer failures, so an admin block is still 403 `digest_not_approved`.

- [ ] **Step 1: Write the failing tests**

Create `tests/skill_sharing/test_routes.py`:

```python
import json
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marketplace import installer
from marketplace import state as skill_state
from routes.skill_sharing import router
from sandbox import policy as _policy
from security import get_csrf_token
from skills._sharing import messages
from skills._sharing.errors import ShareError

PUBLISH = "/api/skills/share/publish"
REVIEW = "/api/skills/share/review"
INSTALL = "/api/skills/share/install"


@pytest.fixture
def env(provider, skills_dir):
    app = FastAPI()
    app.include_router(router)
    with (
        patch("routes.skill_sharing._provider", return_value=provider),
        patch("routes.skill_sharing._author_name", return_value="Mayuresh Kulkarni"),
        patch("routes.skill_sharing.load_installed_skill_prompts") as prompts,
        patch("routes.skill_sharing.load_skill_tools", return_value={"ok": True}) as tools,
        patch("routes.skill_sharing.skill_audit.log_install") as audit,
    ):
        yield SimpleNamespace(
            http=TestClient(app), provider=provider, skills_dir=skills_dir, prompts=prompts, tools=tools, audit=audit
        )


def _post(env, path, body, headers=True):
    return env.http.post(path, json=body, headers={"X-CSRF-Token": get_csrf_token("testserver")} if headers else {})


def _published_for_a_recipient(env, make_mine):
    skill_id = make_mine()
    body = _post(env, PUBLISH, {"skill_id": skill_id}).json()
    installer.save_installed([])
    shutil.rmtree(env.skills_dir / "mine")
    return skill_id, body


@pytest.mark.parametrize("path", [PUBLISH, REVIEW, INSTALL])
def test_every_route_rejects_a_missing_csrf_token(env, path):
    assert _post(env, path, {}, headers=False).status_code == 403


def test_publish_returns_the_link_and_records_the_share(env, make_mine):
    skill_id = make_mine()
    res = _post(env, PUBLISH, {"skill_id": skill_id, "people": ["a@contoso.com"]})

    assert res.status_code == 200
    body = res.json()
    assert body["version"] == 1
    assert body["reused"] is False
    assert messages.parse_share_link(body["link"])["folder_id"] == body["folder"]["folder_id"]
    assert env.provider.grants == [(body["folder"]["folder_id"], ["a@contoso.com"])]
    assert skill_state.get_entry(skill_id)["published_version"] == 1


def test_publish_refuses_a_skill_that_is_not_mine(env):
    installer.save_installed([{"id": "someone-elses", "tier": "Community", "version": "1"}])
    res = _post(env, PUBLISH, {"skill_id": "someone-elses"})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "not_mine"


@pytest.mark.parametrize("people", [["not-an-email"], ["a@b"], ["a@contoso.com, b@contoso.com"], ["a@c.com"] * 51])
def test_publish_rejects_bad_people(env, make_mine, people):
    res = _post(env, PUBLISH, {"skill_id": make_mine(), "people": people})
    assert res.status_code == 422
    assert env.provider.writes == []


def test_review_returns_the_card_and_installs_nothing(env, make_mine):
    skill_id, shared = _published_for_a_recipient(env, make_mine)
    res = _post(env, REVIEW, {"link": shared["link"]})

    assert res.status_code == 200
    card = res.json()
    assert card["skill_id"] == skill_id
    assert card["digest"] == shared["digest"]
    assert card["collision"] == ""
    assert installer.load_installed() == []


def test_review_rejects_a_bad_link(env):
    res = _post(env, REVIEW, {"link": "https://example.com/not-ours"})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "invalid_link"


def test_review_of_a_removed_skill_is_a_404(env):
    link = messages.make_share_link({"drive_id": "d1", "folder_id": "gone"})
    res = _post(env, REVIEW, {"link": link})
    assert res.status_code == 404
    assert res.json()["detail"]["error"] == "not_found"


@pytest.mark.parametrize(
    "failure, status",
    [
        (ShareError("forbidden", "no access"), 422),
        (ShareError("throttled", "slow down"), 429),
        (ShareError("locked", "locked"), 423),
        (ShareError("conflict", "changed"), 409),
        (RuntimeError("boom"), 502),
    ],
)
def test_provider_failures_never_surface_as_403(env, make_mine, failure, status):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    env.provider.fail_on["read_file"] = failure
    res = _post(env, REVIEW, {"link": shared["link"]})
    assert res.status_code == status
    assert "message" in res.json()["detail"]


def test_install_pins_the_reviewed_digest_and_keeps_the_share_state(env, make_mine):
    skill_id, shared = _published_for_a_recipient(env, make_mine)
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": shared["digest"]})

    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert (env.skills_dir / skill_id / "SKILL.md").is_file()
    entry = skill_state.get_entry(skill_id)
    assert entry["shared_version"] == 1
    assert entry["share_source"]["folder_id"] == shared["folder"]["folder_id"]
    assert entry["tier"] == "Community"
    env.prompts.assert_called_once()
    env.tools.assert_called_once()
    env.audit.assert_called_once_with(skill_id, "Community", "share", shared["digest"])


def test_install_requires_a_digest(env, make_mine):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": ""})
    assert res.status_code == 400
    assert installer.load_installed() == []


def test_install_of_changed_content_is_a_409(env, make_mine):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": "0" * 64})
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "content_changed"
    assert installer.load_installed() == []


def test_install_refuses_a_name_collision(env, make_mine):
    skill_id = make_mine()
    shared = _post(env, PUBLISH, {"skill_id": skill_id}).json()
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": shared["digest"]})
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "collision"
    assert skill_state.get_entry(skill_id)["tier"] == "Mine"


def test_install_keeps_the_admin_allow_list(env, make_mine, tmp_path):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    (tmp_path / "sandbox-policy.json").write_text(json.dumps({"approved_digests": []}), encoding="utf-8")
    _policy._reset_cache()
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": shared["digest"]})
    assert res.status_code == 403
    assert res.json()["detail"]["error"] == "digest_not_approved"
    assert installer.load_installed() == []


def test_install_keeps_the_tier_policy(env, make_mine, tmp_path):
    _skill_id, shared = _published_for_a_recipient(env, make_mine)
    (tmp_path / "sandbox-policy.json").write_text(
        json.dumps({"marketplace_allowed_tiers": ["Native", "Verified"]}), encoding="utf-8"
    )
    _policy._reset_cache()
    res = _post(env, INSTALL, {"link": shared["link"], "version": 1, "digest": shared["digest"]})
    assert res.status_code == 403
    assert installer.load_installed() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'routes.skill_sharing'`.

- [ ] **Step 3: Implement the route module**

Create `web/routes/skill_sharing.py`:

```python
"""Share a Mine skill through OneDrive and install one that was shared with you."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from marketplace import installer, skill_audit
from marketplace.loader import load_skill_tools
from routes.marketplace import (
    _enforce_tier,
    _install_failure,
    _note_tools_error,
    _record_grants,
    _require_digest,
)
from security import verify_csrf
from shared import load_installed_skill_prompts
from skills._sharing import messages, publisher, receiver
from skills._sharing.errors import ShareError
from skills._sharing.provider import GraphSharingProvider

router = APIRouter()
logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")

# 403 is not used here: the app already answers 403 for a bad CSRF token and for policy blocks.
_STATUS = {
    "not_found": 404,
    "invalid": 400,
    "invalid_link": 400,
    "too_large": 400,
    "not_mine": 400,
    "conflict": 409,
    "collision": 409,
    "content_changed": 409,
    "tampered": 409,
    "throttled": 429,
    "locked": 423,
    "forbidden": 422,
}


class FolderRef(BaseModel):
    drive_id: str = Field(min_length=1, max_length=512)
    folder_id: str = Field(min_length=1, max_length=512)
    web_url: str = Field(default="", max_length=2048)
    name: str = Field(default="", max_length=256)


class PublishRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=128)
    people: list[str] = Field(default_factory=list, max_length=50)
    root: FolderRef | None = None

    @field_validator("people")
    @classmethod
    def _emails(cls, people: list[str]) -> list[str]:
        for person in people:
            if not _EMAIL.match(person):
                raise ValueError(f"not an email address: {person!r}")
        return people


class ReviewRequest(BaseModel):
    link: str = Field(max_length=2048)
    version: int | None = Field(default=None, ge=1)


class InstallRequest(BaseModel):
    link: str = Field(max_length=2048)
    version: int = Field(ge=1)
    digest: str = ""


def _provider() -> GraphSharingProvider:
    from skills._m365.helpers import GraphClient

    return GraphSharingProvider(GraphClient())


def _author_name() -> str:
    from skills._m365.helpers import GraphClient

    me = GraphClient().get("/me", params={"$select": "displayName,userPrincipalName"})
    return me.get("displayName") or me.get("userPrincipalName") or ""


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ShareError as err:
        raise HTTPException(
            status_code=_STATUS.get(err.code, 502), detail={"error": err.code, "message": err.message}
        ) from err
    except Exception as exc:
        logger.warning("skill sharing request failed: %s", exc)
        raise HTTPException(
            status_code=502, detail={"error": "unknown", "message": "Could not complete that with OneDrive."}
        ) from exc


@router.post("/api/skills/share/publish", dependencies=[Depends(verify_csrf)])
def publish_skill(req: PublishRequest):
    provider = _call(_provider)
    author = _call(_author_name)
    root = req.root.model_dump() if req.root else None
    return _call(publisher.publish, provider, req.skill_id, author=author, root=root, people=req.people)


@router.post("/api/skills/share/review", dependencies=[Depends(verify_csrf)])
def review_shared_skill(req: ReviewRequest):
    ref = _call(messages.parse_share_link, req.link)
    provider = _call(_provider)
    return _call(receiver.review, provider, ref, req.version)


@router.post("/api/skills/share/install", dependencies=[Depends(verify_csrf)])
def install_shared_skill(req: InstallRequest):
    _enforce_tier("shared-skill", "Community")
    _require_digest(req.digest)
    ref = _call(messages.parse_share_link, req.link)
    provider = _call(_provider)
    result = _call(receiver.install, provider, ref, version=req.version, digest=req.digest)
    if not result.get("ok"):
        raise _install_failure(result)
    skill_id = result["skill_id"]
    _record_grants(result, skill_id)
    skill_audit.log_install(skill_id, "Community", "share", req.digest)
    load_installed_skill_prompts()
    _note_tools_error(result, load_skill_tools(skill_id, installer.INSTALLED_SKILLS_DIR / skill_id, "Community"))
    return result
```

- [ ] **Step 4: Register the router**

In `web/app.py`, add the import directly under the existing marketplace import (near line 89):

```python
from routes.marketplace import router as marketplace_router
from routes.skill_sharing import router as skill_sharing_router
```

and the registration directly under the existing one (near line 940):

```python
app.include_router(marketplace_router)
app.include_router(skill_sharing_router)
```

- [ ] **Step 5: List the routes as sensitive**

In `web/security.py`, add these two entries to `SENSITIVE_ROUTES` between `"POST /api/scheduler/jobs/{job_id}/run-now",` and `"POST /api/slack/channels/{channel_id}/post",` (the list is ordered by path):

```python
    "POST /api/skills/share/install",
    "POST /api/skills/share/publish",
```

- [ ] **Step 6: Run the new tests and the CSRF inventory**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing tests/test_csrf_route_inventory.py -v`
Expected: PASS. If `test_install_keeps_the_tier_policy` returns 200, the user's own `config.json` is widening the tier list; `_allowed_tiers` only narrows a policy, so the test should still pass. If it fails for another reason, read `routes.marketplace._allowed_tiers` before changing anything.

- [ ] **Step 7: Run the marketplace tests to check nothing regressed**

Run: `.venv/Scripts/python -m pytest tests/marketplace -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add web/routes/skill_sharing.py web/app.py web/security.py tests/skill_sharing/test_routes.py
git commit -m "Add the publish, review and install routes for shared skills"
```

---

### Task 8: Keep a received skill read-only

A skill someone shared with you is pinned to the reviewed `files_digest`. If the assistant could rewrite it through `update_skill`, the pinned digest and the files on disk would no longer match. The author's own copy also carries `share_source` (set by Task 5), and that one must stay editable, so the guard only applies to entries whose tier is not `Mine`.

**Files:**

- Modify: `web/skills/skill_manager/tools.py` (`_tool_update_skill`, after the "not found" branch, around line 183)
- Test: `tests/skill_sharing/test_edit_guard.py`

**Interfaces:**

- Consumes: `marketplace.installer.load_installed` and `save_installed` (already imported in `tools.py`); the `share_source` key that `receiver.install` and `publisher.publish` write on the entry.
- Produces: `update_skill` returns `{"error": "..."}` and writes nothing when the entry has a `share_source` and its tier is not `Mine`.

- [ ] **Step 1: Write the failing tests**

Create `tests/skill_sharing/test_edit_guard.py`:

```python
import importlib

import pytest

from marketplace import installer

SHARE_SOURCE = {"drive_id": "d1", "folder_id": "f1"}


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setattr("config.INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import skills.skill_manager.tools as m

    importlib.reload(m)
    yield m
    importlib.reload(m)


def _install(tmp_path, skill_id, tier, share_source=None):
    folder = tmp_path / ("mine" if tier == "Mine" else "") / skill_id
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f'---\nname: {skill_id}\ndescription: "d"\nversion: "1"\n---\n\nOriginal.', encoding="utf-8")
    entry = {"id": skill_id, "version": "1", "tier": tier}
    if share_source:
        entry["share_source"] = share_source
    installer.save_installed([*installer.load_installed(), entry])
    return folder / "SKILL.md"


def test_a_received_skill_cannot_be_edited(tools, tmp_path):
    skill_md = _install(tmp_path, "weekly-report", "Community", SHARE_SOURCE)
    before = skill_md.read_text(encoding="utf-8")

    result = tools._tool_update_skill("weekly-report", "Changed.")

    assert "error" in result
    assert "shared with you" in result["error"]
    assert skill_md.read_text(encoding="utf-8") == before


def test_the_authors_own_shared_skill_can_still_be_edited(tools, tmp_path):
    skill_md = _install(tmp_path, "weekly-report", "Mine", SHARE_SOURCE)

    result = tools._tool_update_skill("weekly-report", "Changed.")

    assert result.get("ok") is True, result
    assert skill_md.read_text(encoding="utf-8").endswith("Changed.")


def test_a_mine_skill_that_was_never_shared_can_be_edited(tools, tmp_path):
    skill_md = _install(tmp_path, "weekly-report", "Mine")

    assert tools._tool_update_skill("weekly-report", "Changed.").get("ok") is True
    assert skill_md.read_text(encoding="utf-8").endswith("Changed.")


def test_an_installed_skill_that_was_not_shared_keeps_its_old_behaviour(tools, tmp_path):
    skill_md = _install(tmp_path, "from-marketplace", "Community")

    assert tools._tool_update_skill("from-marketplace", "Changed.").get("ok") is True
    assert skill_md.read_text(encoding="utf-8").endswith("Changed.")
```

- [ ] **Step 2: Run the tests to verify the first one fails**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_edit_guard.py -v`
Expected: `test_a_received_skill_cannot_be_edited` FAILS (the update succeeds, so `"error" in result` is false). The other three PASS already.

- [ ] **Step 3: Add the guard**

In `web/skills/skill_manager/tools.py`, add this helper directly above `_tool_update_skill`:

```python
def _received_from_a_share(skill_id: str) -> bool:
    entry = next((e for e in load_installed() if e.get("id") == skill_id), None)
    return bool(entry and entry.get("share_source") and entry.get("tier") != "Mine")
```

and in `_tool_update_skill`, directly after the `if skill_md is None:` block (before `existing = skill_md.read_text(...)`):

```python
    if _received_from_a_share(skill_id):
        return {
            "error": f"Skill '{skill_id}' was shared with you, so it is read-only. "
            "Ask the author for a new version, or write your own skill with create_skill."
        }
```

- [ ] **Step 4: Run the guard tests and the existing skill-manager tests**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing/test_edit_guard.py web/tests/test_skill_manager_frontmatter.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole sharing suite**

Run: `.venv/Scripts/python -m pytest tests/skill_sharing tests/marketplace tests/test_csrf_route_inventory.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/skills/skill_manager/tools.py tests/skill_sharing/test_edit_guard.py
git commit -m "Keep a skill that was shared with you read-only in update_skill"
```
