# File Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Moving, copying and uploading files between OneDrive/SharePoint locations works even when the source is locked, and the ask-user option card and permission-approval UI stop failing.

**Architecture:** Two new tools in the existing `onedrive` skill, `file_transfer` (move or copy with a locked-file fallback) and `file_upload` (local file to a drive folder by ID). Provider-neutral orchestration lives in `web/skills/_files/`; the OneDrive provider lives in `web/skills/_m365/onedrive_provider.py` and wraps the existing tool functions plus the existing upload primitives in `web/skills/_m365/file_transfer.py`. Existing tools keep their names, arguments and results; they only gain an additive `error_code` and a fixed copy poll.

**Tech Stack:** Python 3 (FastAPI app, Microsoft Graph via the skill `GraphClient`), pytest, vanilla JS front end, `node --test` for JS tests.

## Global Constraints

- No delete in any form. No tool, fallback or cleanup step removes a file, local or remote.
- Existing OneDrive tools (`read/list/search/download/move/copy/get_onedrive_item`, `resolve_teams_attachment`) are not renamed, retired or changed in arguments or result shape. Only additive keys.
- New tools are registered in `web/skills/onedrive/tools.py` (not a new skill) so the per-tab "SharePoint and OneDrive" data-source approval keeps gating them.
- `web/skills/onedrive/tools.py` is loaded by file path in `tests/test_onedrive_file_routing.py`: it must not import `skills._files` or `skills._m365` at module top level. Import them inside functions.
- Local path arguments go through `guard_path_args(..., "local_path")`.
- Graph IDs and names put into URL paths are percent-encoded with `_eid` / `quote(v, safe="")` (the client's `_encode_path` preserves `%`).
- The copy monitor URL and upload-session URL are pre-authenticated: never send `Authorization` to them.
- Git commits: no `Co-Authored-By` lines. The project is called AI Gator, never a POC.
- The only fake credential in tests and docs is `aigator-fake-api-key`.
- Do not add POST/PUT/PATCH/DELETE web routes (none are needed; if one ever is, it needs `dependencies=[Depends(verify_csrf)]`).
- Run tests from the repo root. `tests/conftest.py` adds `web/` to `sys.path` and redirects the home directory to a temp dir.

## File Structure

| File                                       | Action | Responsibility                                                                    |
| ------------------------------------------ | ------ | --------------------------------------------------------------------------------- |
| `web/static/style.css`                     | modify | `.ask-user-option` wraps instead of overflowing                                   |
| `web/static/app.js`                        | modify | Failed permission grant re-sends the message instead of dropping it               |
| `tests/ask_user_option_wrap.test.js`       | create | CSS wrap guard                                                                    |
| `tests/permission_gate_approval.test.js`   | modify | Resend-on-failed-grant guard                                                      |
| `web/skills/_files/__init__.py`            | create | Package marker (loader skips `_` dirs)                                            |
| `web/skills/_files/errors.py`              | create | `classify_status`, `classify_graph_error`                                         |
| `web/skills/_files/transfer.py`            | create | Provider-neutral `transfer()` orchestration                                       |
| `web/skills/_m365/file_transfer.py`        | modify | Add `store_in_folder`, `file_source`; generalise private put helpers              |
| `web/skills/_m365/onedrive_provider.py`    | create | `OneDriveProvider` implementing the provider interface                            |
| `web/skills/onedrive/tools.py`             | modify | `error_code` additions, copy poll fix, register `file_upload` and `file_transfer` |
| `web/skills/onedrive/SKILL.md`             | modify | Move/copy/lock/Teams-attachment/upload guidance                                   |
| `web/skills/m365-onedrive/SKILL.md`        | modify | Cross-reference                                                                   |
| `tests/test_file_errors.py`                | create | Error classification                                                              |
| `tests/test_onedrive_copy_hardening.py`    | create | Copy poll fix and `error_code`                                                    |
| `tests/test_file_store_in_folder.py`       | create | Upload-by-folder-ID primitives                                                    |
| `tests/test_files_transfer_core.py`        | create | Orchestration with a fake provider                                                |
| `tests/test_onedrive_provider.py`          | create | Provider against a fake Graph client                                              |
| `tests/test_file_tools_registration.py`    | create | Tool registration, no-delete guard, guide content                                 |
| `tests/code_sandbox/test_secrets_guard.py` | modify | Add `file_upload` to the guarded-handler cases                                    |

---

### Task 0: Isolated branch

The current working tree has unrelated uncommitted edits (`shell/main.js`, `shell/package.json`, `tests/test_desktop_packaging.py`, `web/static/third-pane.js`) on `fix/jira-confluence-github-setup-redirect`. Do not touch them. Work in a worktree off `main`.

- [ ] **Step 1: Create the worktree**

```bash
git worktree add ../aigator-file-transfer -b feat/file-transfer main
```

- [ ] **Step 2: Copy the spec and plan into it and commit them**

```bash
cp docs/superpowers/specs/2026-10-29-file-transfer-design.md ../aigator-file-transfer/docs/superpowers/specs/
cp docs/superpowers/plans/2026-10-29-file-transfer.md ../aigator-file-transfer/docs/superpowers/plans/
cd ../aigator-file-transfer
git add docs/superpowers/specs/2026-10-29-file-transfer-design.md docs/superpowers/plans/2026-10-29-file-transfer.md
git commit -m "docs: add file transfer design and implementation plan"
```

If `docs/superpowers/specs/` or `plans/` does not exist on `main`, `mkdir -p` it first. All later paths are relative to `../aigator-file-transfer`.

---

### Task 1: Ask-user option card wraps long text

**Files:**

- Modify: `web/static/style.css:6153-6160`
- Test: `tests/ask_user_option_wrap.test.js` (create)

**Interfaces:**

- Consumes: nothing.
- Produces: nothing other tasks use.

Cause: `.btn-secondary { white-space: nowrap }` (`style.css:2651`) applies to the option button; `.ask-user-option` never overrides it.

- [ ] **Step 1: Write the failing test**

```js
// The ask_user option buttons carry long label+description text; the shared .btn-secondary
// rule sets white-space: nowrap, so the option rule must turn wrapping back on.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { test } = require('node:test');

const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'style.css'), 'utf8');

function block(selector) {
  const m = css.match(
    new RegExp('(^|\\n)' + selector.replace(/[.]/g, '\\.') + '\\s*\\{([^}]*)\\}'),
  );
  assert(m, selector + ' rule exists');
  return m[2];
}

test('ask-user option button wraps long text', () => {
  const b = block('.ask-user-option');
  assert(/white-space:\s*normal/.test(b), 'white-space: normal');
  assert(/overflow-wrap:\s*anywhere/.test(b), 'overflow-wrap: anywhere');
});

test('ask-user option label and description wrap', () => {
  assert(/overflow-wrap:\s*anywhere/.test(block('.ask-user-option-label')));
  assert(/overflow-wrap:\s*anywhere/.test(block('.ask-user-option-desc')));
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node --test tests/ask_user_option_wrap.test.js`
Expected: FAIL (`white-space: normal` not found).

- [ ] **Step 3: Implement**

Replace the three rules at `style.css:6153-6167` with:

```css
.ask-user-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  text-align: left;
  width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
}
.ask-user-option-label {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.ask-user-option-desc {
  font-size: 0.75rem;
  opacity: 0.75;
  overflow-wrap: anywhere;
}
```

- [ ] **Step 4: Run the new and existing card tests**

Run: `node --test tests/ask_user_option_wrap.test.js tests/ask_user_card.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/static/style.css tests/ask_user_option_wrap.test.js
git commit -m "fix: wrap long text in ask-user option cards"
```

---

### Task 2: Failed permission grant re-sends instead of dropping the message

**Files:**

- Modify: `web/static/app.js:14210-14229`
- Test: `tests/permission_gate_approval.test.js`

**Interfaces:**

- Consumes: `/api/chat/approve-deps` (unchanged), `_permissionResendPayload`, `doSend`.
- Produces: nothing other tasks use.

Cause: `_PENDING_DEP_APPROVALS` (`web/routes/chat.py:330`) is in memory, one-shot, 600s TTL. A backend reload, a long wait or a double click returns 404, and the client then discards the saved request and tells the user to retype. Fix: on a refused grant, nothing is granted, and the client re-sends the saved request so the server issues a fresh permission card. Nothing is auto-granted, so the gate is unchanged.

- [ ] **Step 1: Add the failing tests** (append to `tests/permission_gate_approval.test.js`)

```js
test('a refused grant re-sends the saved request instead of dropping it', () => {
  const i = app.indexOf("fetch('/api/chat/approve-deps'");
  const handler = app.slice(i, i + 1400);
  assert(!/Send your message again/.test(app), 'no "retype your message" dead end');
  assert(
    !/if \(!grant \|\| !grant\.ok\)\s*\{[^}]*return;/.test(handler),
    'failed grant must not return early',
  );
  assert(/doSend\(resendPayload\)/.test(handler), 'saved payload is re-sent');
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test tests/permission_gate_approval.test.js`
Expected: the new test FAILS; the two existing tests pass.

- [ ] **Step 3: Implement** (replace `app.js:14210-14229`, the body of the first callback passed to `_renderPermissionCard`)

```js
                async () => {
                  // The server records the grant for this tab; the client cannot grant itself.
                  // A refused grant (restart, expiry) grants nothing: re-sending the same request
                  // makes the server issue a fresh permission card, so the message is never lost.
                  await fetch('/api/chat/approve-deps', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ approval_id: msg.approval_id }),
                  }).catch(() => null);
                  // Re-submit using the saved payload — call doSend fresh so post-stream
                  // work (history, action bar, suggested actions) runs normally
                  if (!_permissionResendPayload) return;
                  const resendPayload = _permissionResendPayload;
                  _permissionResendPayload = null;
                  await doSend(resendPayload);
                },
```

The existing test `Allow on the permission card posts the server-issued approval id` slices 400 chars from `fetch('/api/chat/approve-deps'` and must still see `method: 'POST'` and `approval_id: msg.approval_id`; the layout above keeps both within 400 chars.

- [ ] **Step 4: Run the tests**

Run: `node --test tests/permission_gate_approval.test.js`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add web/static/app.js tests/permission_gate_approval.test.js
git commit -m "fix: re-send the message when a permission grant is refused instead of dropping it"
```

---

### Task 3: Error classification helper

**Files:**

- Create: `web/skills/_files/__init__.py` (empty)
- Create: `web/skills/_files/errors.py`
- Test: `tests/test_file_errors.py` (create)

**Interfaces:**

- Produces: `classify_status(status: int) -> str` and `classify_graph_error(exc: Exception) -> str`. Return one of `"locked" | "forbidden" | "not_found" | "throttled" | "unknown"`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from skills._files.errors import classify_graph_error, classify_status


@pytest.mark.parametrize(
    "status,code",
    [(423, "locked"), (401, "forbidden"), (403, "forbidden"), (404, "not_found"),
     (429, "throttled"), (500, "unknown"), (0, "unknown")],
)
def test_classify_status(status, code):
    assert classify_status(status) == code


def test_classify_graph_error_reads_status_code_attribute():
    class GraphLike(Exception):
        status_code = 423

    assert classify_graph_error(GraphLike("Graph API 423: locked")) == "locked"


def test_classify_graph_error_reads_httpx_response():
    class Resp:
        status_code = 404

    class HttpxLike(Exception):
        response = Resp()

    assert classify_graph_error(HttpxLike("x")) == "not_found"


def test_classify_graph_error_plain_exception_is_unknown():
    assert classify_graph_error(RuntimeError("boom")) == "unknown"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_file_errors.py -v`
Expected: FAIL (`ModuleNotFoundError: skills._files`).

- [ ] **Step 3: Implement**

`web/skills/_files/__init__.py`: empty file.

`web/skills/_files/errors.py`:

```python
"""Map Graph/HTTP failures to the short codes the file tools report."""


def classify_status(status: int) -> str:
    if status == 423:
        return "locked"
    if status in (401, 403):
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 429:
        return "throttled"
    return "unknown"


def classify_graph_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if not status:
        status = getattr(getattr(exc, "response", None), "status_code", 0)
    return classify_status(int(status or 0))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_file_errors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_files/__init__.py web/skills/_files/errors.py tests/test_file_errors.py
git commit -m "feat: classify Graph failures into locked/forbidden/not_found/throttled codes"
```

---

### Task 4: Harden copy and add `error_code` to existing tool errors

**Files:**

- Modify: `web/skills/onedrive/tools.py` (`_tool_move_onedrive_file` ~L1505, `_tool_copy_onedrive_file` ~L1537, `_tool_get_onedrive_item` ~L1618)
- Test: `tests/test_onedrive_copy_hardening.py` (create)

**Interfaces:**

- Consumes: `classify_status`, `classify_graph_error` from `skills._files.errors` (Task 3), imported lazily inside each function.
- Produces: error dicts from these three tools carry `"error_code"` next to `"error"`. A completed copy returns `{"status": "completed", "item_id", "dest_drive_id", ...}`; a copy still running returns `{"status": "pending", "monitor_url", "note"}` plus `"poll_error"` when polling raised.

Existing keys and shapes are untouched; `tests/test_graph_id_encoding.py` and `tests/test_onedrive_file_routing.py` must stay green.

- [ ] **Step 1: Write the failing tests**

```python
import time
from unittest.mock import MagicMock, patch

import httpx

from skills.onedrive import tools as od


class _Resp:
    def __init__(self, status=200, data=None, headers=None, text=""):
        self.status_code = status
        self._data = data if data is not None else {}
        self.headers = headers or {}
        self.content = b"x"
        self.text = text

    def json(self):
        return self._data


def _gc():
    gc = MagicMock()
    gc.get_token.return_value = "aigator-fake-api-key"
    return gc


def _copy(monkeypatch, poll):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(202, headers={"Location": "https://monitor.example/m1"}))
    monkeypatch.setattr(httpx, "get", poll)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with patch("skills._m365.helpers.get_skill_client", return_value=_gc()):
        return od._tool_copy_onedrive_file("d1", "i1", "d2", "f2")


def test_copy_poll_sends_no_authorization(monkeypatch):
    seen = []

    def poll(url, **kw):
        seen.append(kw.get("headers"))
        return _Resp(200, {"status": "completed", "resourceId": "NEW1"})

    out = _copy(monkeypatch, poll)
    assert out["status"] == "completed" and out["item_id"] == "NEW1"
    assert not seen[0], "monitor URL is pre-authenticated; no headers may be sent"


def test_copy_poll_bare_item_json_counts_as_completed(monkeypatch):
    out = _copy(monkeypatch, lambda url, **kw: _Resp(200, {"id": "NEW2", "name": "a.docx", "parentReference": {"driveId": "d2"}}))
    assert out == {"status": "completed", "item_id": "NEW2", "dest_drive_id": "d2", "name": "a.docx"}


def test_copy_poll_errors_are_surfaced_not_swallowed(monkeypatch):
    def poll(url, **kw):
        raise RuntimeError("boom")

    out = _copy(monkeypatch, poll)
    assert out["status"] == "pending"
    assert out["poll_error"] == "boom"


def test_copy_failed_status_has_error_code(monkeypatch):
    out = _copy(monkeypatch, lambda url, **kw: _Resp(200, {"status": "failed", "error": {"message": "nope"}}))
    assert out["error"].startswith("Copy failed")
    assert out["error_code"] == "unknown"


def test_copy_request_http_error_has_error_code(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(404, text="not here"))
    with patch("skills._m365.helpers.get_skill_client", return_value=_gc()):
        out = od._tool_copy_onedrive_file("d1", "i1", "d2", "f2")
    assert out["error_code"] == "not_found"
    assert "404" in out["error"]


def test_move_locked_has_error_code_and_keeps_message():
    class Locked(Exception):
        status_code = 423

    gc = MagicMock()
    gc.patch.side_effect = Locked("Graph API 423: resourceLocked")
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        out = od._tool_move_onedrive_file("d1", "i1", "d2", "f2")
    assert out["error"].startswith("Move failed:")
    assert out["error_code"] == "locked"


def test_get_item_error_has_error_code():
    class Missing(Exception):
        status_code = 404

    gc = MagicMock()
    gc.get.side_effect = Missing("Graph API 404")
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        out = od._tool_get_onedrive_item("d1", "i1")
    assert out["error_code"] == "not_found"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_onedrive_copy_hardening.py -v`
Expected: FAIL (headers are sent; `poll_error` / `error_code` missing).

- [ ] **Step 3: Implement**

In `_tool_move_onedrive_file`, add `from .._files.errors import classify_graph_error` after the `get_skill_client` import, and change the except:

```python
    except Exception as e:
        return {"error": f"Move failed: {e}", "error_code": classify_graph_error(e)}
```

In `_tool_get_onedrive_item`, same import, and:

```python
    except Exception as e:
        return {
            "error": f"Could not get item {item_id} on drive {drive_id}: {e}",
            "error_code": classify_graph_error(e),
        }
```

In `_tool_copy_onedrive_file`, add `from .._files.errors import classify_graph_error, classify_status` after the `get_skill_client` import, then change these returns:

```python
    except Exception as e:
        return {"error": f"Copy request failed: {e}", "error_code": classify_graph_error(e)}

    if r.status_code not in (202, 200, 201):
        return {
            "error": f"Copy request returned HTTP {r.status_code}: {r.text[:300]}",
            "error_code": classify_status(r.status_code),
        }
```

Replace the poll loop and the trailing pending return (from `for _ in range(30):` to the end of the function) with:

```python
    last_poll_error = ""
    for _ in range(30):
        _time.sleep(2)
        try:
            poll = _httpx.get(monitor_url, follow_redirects=True, timeout=15)
            data = poll.json()
        except Exception as e:
            last_poll_error = str(e)
            continue
        status = data.get("status", "")
        if status == "completed":
            ri = data.get("resourceId", "")
            resource_url = data.get("resourceLocation", "")
            return {
                "status": "completed",
                "item_id": ri,
                "dest_drive_id": dest_drive_id,
                "resource_url": resource_url,
            }
        if status in ("failed", "cancelled"):
            return {
                "error": f"Copy {status}: {data.get('error', {}).get('message', '')}",
                "error_code": "unknown",
            }
        if not status and data.get("id"):
            pr = data.get("parentReference") or {}
            return {
                "status": "completed",
                "item_id": data["id"],
                "dest_drive_id": pr.get("driveId", dest_drive_id),
                "name": data.get("name", ""),
            }

    out = {
        "status": "pending",
        "monitor_url": monitor_url,
        "note": "Copy still in progress after 60s. Check the destination folder.",
    }
    if last_poll_error:
        out["poll_error"] = last_poll_error
    return out
```

The `token` variable is still used for the initial POST. The monitor URL is pre-authenticated, so the poll no longer sends it.

- [ ] **Step 4: Run the new and existing tests**

Run: `python -m pytest tests/test_onedrive_copy_hardening.py tests/test_graph_id_encoding.py tests/test_onedrive_file_routing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/onedrive/tools.py tests/test_onedrive_copy_hardening.py
git commit -m "fix: poll the copy monitor without auth, surface poll errors, add error_code to move/copy/get item errors"
```

---

### Task 5: Upload by folder ID in the existing transfer module

**Files:**

- Modify: `web/skills/_m365/file_transfer.py`
- Test: `tests/test_file_store_in_folder.py` (create); `tests/test_file_transfer.py` and `tests/test_transcript_review_followups.py` must stay green.

**Interfaces:**

- Consumes: existing `Source`, `safe_filename`, `_rechunk`, `_cancel`, `_result`, `_existing`, `SIMPLE_UPLOAD_MAX`, `CHUNK`; `classify_graph_error` from `skills._files.errors`.
- Produces:
  - `file_source(path: str, name: str = "") -> Source` (streams the local file in `CHUNK` pieces; `size` from `os.stat`).
  - `store_in_folder(gc, source: Source, drive_id: str, folder_id: str, on_conflict: str = "rename") -> dict`. Success: `{"status": "saved", "sha256", "name", "id", "web_url", "size", "drive_id"}`. Failure: `{"status": "error", "error": <code str>, "detail"?, "error_code", ...}`.

Existing `store()` keeps its exact behaviour: its path-building and `conflictBehavior=fail` stay; only the private put helpers are generalised and the old names delegate to them.

- [ ] **Step 1: Write the failing tests**

```python
import hashlib

import pytest

from skills._m365 import file_transfer as ft


class Err(Exception):
    def __init__(self, status_code, msg=""):
        super().__init__(f"Graph API {status_code}: {msg}")
        self.status_code = status_code


class Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeGC:
    def __init__(self, reported_size=None, put_error=None):
        self.reported_size = reported_size
        self.put_error = put_error
        self.put_paths = []
        self.sessions = []
        self.chunks = []
        self.received = b""

    def put_binary(self, path, data, content_type="application/octet-stream"):
        if self.put_error:
            raise self.put_error
        self.put_paths.append(path)
        size = self.reported_size if self.reported_size is not None else len(data)
        return {"id": "N1", "name": "a.txt", "size": size, "webUrl": "https://od/a.txt"}

    def post(self, path, body):
        self.sessions.append((path, body))
        return {"uploadUrl": "https://upload.example/s1"}

    def _request(self, method, url, headers=None, content=None, label=""):
        assert url.startswith("https://upload.example/")
        assert "Authorization" not in (headers or {}), "uploadUrl is pre-authenticated"
        start, rest = headers["Content-Range"].split(" ")[1].split("-")
        end, total = rest.split("/")
        self.chunks.append((int(start), int(end), int(total)))
        self.received += content
        if int(end) + 1 == int(total):
            return Resp({"id": "N2", "name": "big.bin", "size": int(total), "webUrl": "https://od/big.bin"})
        return Resp({"nextExpectedRanges": [f"{int(end) + 1}-"]})


def test_small_file_put_into_folder_by_id_with_rename_conflict(tmp_path):
    f = tmp_path / "my file.txt"
    f.write_bytes(b"hello")
    gc = FakeGC()
    out = ft.store_in_folder(gc, ft.file_source(str(f)), "drive/1", "folder+2")
    assert out["status"] == "saved"
    assert out["id"] == "N1" and out["drive_id"] == "drive/1" and out["size"] == 5
    assert out["sha256"] == hashlib.sha256(b"hello").hexdigest()
    path = gc.put_paths[0]
    assert path.startswith("/drives/drive%2F1/items/folder%2B2:/my%20file.txt:/content")
    assert path.endswith("?@microsoft.graph.conflictBehavior=rename")


def test_large_file_uses_upload_session_in_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "SIMPLE_UPLOAD_MAX", 4)
    monkeypatch.setattr(ft, "CHUNK", 4)
    f = tmp_path / "big.bin"
    f.write_bytes(b"0123456789")
    gc = FakeGC()
    out = ft.store_in_folder(gc, ft.file_source(str(f)), "d2", "f2")
    assert out["status"] == "saved" and out["size"] == 10
    assert gc.chunks == [(0, 3, 10), (4, 7, 10), (8, 9, 10)]
    assert gc.received == b"0123456789"
    session_path, body = gc.sessions[0]
    assert session_path == "/drives/d2/items/f2:/big.bin:/createUploadSession"
    assert body["item"]["@microsoft.graph.conflictBehavior"] == "rename"


def test_size_mismatch_is_an_error(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    out = ft.store_in_folder(FakeGC(reported_size=3), ft.file_source(str(f)), "d", "f")
    assert out["status"] == "error" and out["error"] == "size_mismatch"


def test_graph_failure_is_reported_with_error_code(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    out = ft.store_in_folder(FakeGC(put_error=Err(403, "denied")), ft.file_source(str(f)), "d", "f")
    assert out["status"] == "error" and out["error"] == "transfer_failed"
    assert out["error_code"] == "forbidden"
    assert "403" in out["detail"]


def test_unsafe_characters_in_name_are_sanitised(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    gc = FakeGC()
    ft.store_in_folder(gc, ft.file_source(str(f), name='q3: "plan".txt'), "d", "f")
    assert ":/q3_%20_plan_.txt:/content" not in gc.put_paths[0]
    assert "/q3_%20_plan_.txt:/content" in gc.put_paths[0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_file_store_in_folder.py -v`
Expected: FAIL (`store_in_folder` / `file_source` not defined).

- [ ] **Step 3: Implement**

At the top of `web/skills/_m365/file_transfer.py`, add imports after `import urllib.parse`:

```python
import os
```

Replace `_upload_small` and `_upload_large` (lines 126-169) with generalised helpers plus delegating wrappers. The wrapper bodies produce the same Graph calls as before:

```python
def _put_small(gc, source, item_path, conflict):
    data = b"".join(source.open())
    if len(data) != source.size:
        return None, "source_size_mismatch", hashlib.sha256(data).hexdigest()
    path = item_path + f":/content?@microsoft.graph.conflictBehavior={conflict}"
    item = gc.put_binary(path, data)
    return item, "", hashlib.sha256(data).hexdigest()


def _put_large(gc, source, item_path, conflict, name):
    session = gc.post(
        item_path + ":/createUploadSession",
        {"item": {"@microsoft.graph.conflictBehavior": conflict, "name": name}},
    )
    url = session["uploadUrl"]
    digest = hashlib.sha256()
    sent = 0
    item = None
    try:
        for block in _rechunk(source.open(), CHUNK):
            if sent + len(block) > source.size:
                break
            end = sent + len(block) - 1
            resp = gc._request(
                "PUT",
                url,
                headers={
                    "Content-Length": str(len(block)),
                    "Content-Range": f"bytes {sent}-{end}/{source.size}",
                },
                content=block,
                label="upload-session",
            )
            digest.update(block)
            sent += len(block)
            if sent == source.size:
                item = resp.json()
    except Exception:
        _cancel(gc, url)
        raise
    if sent != source.size:
        _cancel(gc, url)
        return None, "source_size_mismatch", digest.hexdigest()
    return item, "", digest.hexdigest()


def _upload_small(gc, source, drive_id, folder_path, name):
    return _put_small(gc, source, _item_path(drive_id, folder_path, name), "fail")


def _upload_large(gc, source, drive_id, folder_path, name):
    return _put_large(gc, source, _item_path(drive_id, folder_path, name), "fail", name)
```

Append at the end of the file:

```python
def file_source(path: str, name: str = "") -> Source:
    p = os.path.expanduser(path)

    def _open():
        with open(p, "rb") as f:
            while True:
                block = f.read(CHUNK)
                if not block:
                    return
                yield block

    return Source(name=name or os.path.basename(p), size=os.path.getsize(p), open=_open)


def _folder_item_path(drive_id: str, folder_id: str, name: str) -> str:
    q = lambda v: urllib.parse.quote(v or "", safe="")  # noqa: E731 - graph client keeps '%' as-is
    return f"/drives/{q(drive_id)}/items/{q(folder_id)}:/{q(name)}"


def store_in_folder(gc, source: Source, drive_id: str, folder_id: str, on_conflict: str = "rename") -> dict:
    """Upload into a folder addressed by drive and item ID. Never overwrites: a clash renames."""
    from .._files.errors import classify_graph_error

    name = safe_filename(source.name)
    item_path = _folder_item_path(drive_id, folder_id, name)
    try:
        if source.size <= SIMPLE_UPLOAD_MAX:
            item, err, sha = _put_small(gc, source, item_path, on_conflict)
        else:
            item, err, sha = _put_large(gc, source, item_path, on_conflict, name)
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
```

- [ ] **Step 4: Run the new tests and the existing transfer tests**

Run: `python -m pytest tests/test_file_store_in_folder.py tests/test_file_transfer.py tests/test_transcript_review_followups.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_m365/file_transfer.py tests/test_file_store_in_folder.py
git commit -m "feat: upload a local file into a OneDrive folder by drive and folder ID without overwriting"
```

---

### Task 6: Provider-neutral transfer orchestration

**Files:**

- Create: `web/skills/_files/transfer.py`
- Test: `tests/test_files_transfer_core.py` (create)

**Interfaces:**

- Consumes: a provider object with these methods (refs are dicts: `ref = {"drive_id", "item_id"}`, `dest_folder = {"drive_id", "folder_id"}`; every method returns a dict, and on failure a dict containing `"error"` and `"error_code"`):
  - `stat(ref) -> {"item_id","drive_id","name","size","web_url"} | error`
  - `is_foreign_owner(ref) -> bool`
  - `move(ref, dest_folder, new_name) -> {"item_id","drive_id","name","web_url"} | error`
  - `copy(ref, dest_folder, new_name) -> {"status": "completed","item_id","dest_drive_id"} | {"status": "pending", "monitor_url"} | error`
  - `find_in_folder(dest_folder, name, size) -> {"item_id","drive_id","name","web_url"} | None`
  - `download(ref, local_path: str) -> {"saved_to": str} | error`
  - `upload(local_path: str, dest_folder, name: str) -> {"item_id","drive_id","name","web_url"} | error`
- Produces: `transfer(provider, source: dict, dest_folder: dict, mode: str = "move", new_name: str = "", sleep=time.sleep, downloads_dir=None) -> dict`, `LOCK_RETRY_DELAYS = (3, 6)`. Result keys: `status` (`moved|copied|pending|failed`), `method` (`native_move|server_copy|download_upload|None`), `original_remains` (bool), `reason` (`locked|not_owner|None`), `dest` (dict or None), `local_copy` (path or None), `message` (str), plus `error` and `error_code` on failure.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from skills._files import transfer as tr

SRC = {"drive_id": "d1", "item_id": "i1"}
DEST = {"drive_id": "d2", "folder_id": "f2"}
META = {"item_id": "i1", "drive_id": "d1", "name": "report.docx", "size": 10, "web_url": "u1"}
MOVED = {"item_id": "i1", "drive_id": "d2", "name": "report.docx", "web_url": "u2"}
LOCKED = {"error": "Move failed: 423", "error_code": "locked"}
DONE = {"status": "completed", "item_id": "n1", "dest_drive_id": "d2"}


class FakeProvider:
    def __init__(self, move=(), copy=None, foreign=False, stat=META, find=None, download=None, upload=None, stat_new=None):
        self.moves = list(move)
        self.copy_result = copy
        self.foreign = foreign
        self.stat_result = stat
        self.stat_new = stat_new or {"item_id": "n1", "drive_id": "d2", "name": "report.docx", "web_url": "u3", "size": 10}
        self.find = find
        self.download_result = download
        self.upload_result = upload
        self.calls = []

    def stat(self, ref):
        self.calls.append("stat")
        return self.stat_new if ref["item_id"] == "n1" else self.stat_result

    def is_foreign_owner(self, ref):
        self.calls.append("is_foreign_owner")
        return self.foreign

    def move(self, ref, dest, new_name):
        self.calls.append("move")
        return self.moves.pop(0)

    def copy(self, ref, dest, new_name):
        self.calls.append("copy")
        return self.copy_result

    def find_in_folder(self, dest, name, size):
        self.calls.append("find")
        return self.find

    def download(self, ref, local_path):
        self.calls.append(("download", local_path))
        return self.download_result

    def upload(self, local_path, dest, name):
        self.calls.append(("upload", local_path, name))
        return self.upload_result


def run(p, **kw):
    sleeps = []
    out = tr.transfer(p, SRC, DEST, sleep=sleeps.append, **kw)
    return out, sleeps


def test_move_success_is_native_move():
    p = FakeProvider(move=[MOVED])
    out, sleeps = run(p)
    assert out["status"] == "moved" and out["method"] == "native_move"
    assert out["original_remains"] is False and out["reason"] is None
    assert out["dest"] == {"drive_id": "d2", "item_id": "i1", "name": "report.docx", "web_url": "u2"}
    assert p.calls == ["stat", "is_foreign_owner", "move"] and sleeps == []


def test_locked_then_free_retries_with_backoff():
    p = FakeProvider(move=[LOCKED, LOCKED, MOVED])
    out, sleeps = run(p)
    assert out["status"] == "moved" and sleeps == [3, 6]
    assert p.calls.count("move") == 3


def test_still_locked_falls_back_to_server_copy():
    p = FakeProvider(move=[LOCKED, LOCKED, LOCKED], copy=DONE)
    out, sleeps = run(p)
    assert (out["status"], out["method"], out["reason"]) == ("copied", "server_copy", "locked")
    assert out["original_remains"] is True
    assert out["dest"]["item_id"] == "n1" and out["dest"]["web_url"] == "u3"
    assert sleeps == [3, 6]
    assert "original" in out["message"].lower()


def test_non_lock_move_error_fails_without_copy():
    p = FakeProvider(move=[{"error": "Move failed: 403", "error_code": "forbidden"}])
    out, _ = run(p)
    assert out["status"] == "failed" and out["error_code"] == "forbidden"
    assert "copy" not in p.calls and out["original_remains"] is True


def test_foreign_owner_copies_instead_of_moving():
    p = FakeProvider(foreign=True, copy=DONE)
    out, _ = run(p)
    assert (out["status"], out["method"], out["reason"]) == ("copied", "server_copy", "not_owner")
    assert out["original_remains"] is True and "move" not in p.calls


def test_copy_mode_skips_owner_check_and_move():
    p = FakeProvider(copy=DONE)
    out, _ = run(p, mode="copy")
    assert out["status"] == "copied" and out["reason"] is None and out["original_remains"] is True
    assert p.calls == ["stat", "copy", "stat"]


def test_pending_copy_resolved_by_finding_item_in_destination():
    found = {"item_id": "n9", "drive_id": "d2", "name": "report.docx", "web_url": "u9"}
    p = FakeProvider(copy={"status": "pending", "monitor_url": "m"}, find=found)
    out, _ = run(p, mode="copy")
    assert out["status"] == "copied" and out["dest"] == found


def test_pending_copy_not_found_stays_pending_and_does_not_fall_back():
    p = FakeProvider(copy={"status": "pending", "monitor_url": "m"}, find=None)
    out, _ = run(p, mode="copy")
    assert out["status"] == "pending" and out["original_remains"] is True
    assert not any(isinstance(c, tuple) for c in p.calls)


def test_copy_error_falls_back_to_download_and_upload(tmp_path):
    up = {"item_id": "n5", "drive_id": "d2", "name": "report.docx", "web_url": "u5"}
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "report.docx")}, upload=up)
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert (out["status"], out["method"]) == ("copied", "download_upload")
    assert out["local_copy"] == str(tmp_path / "report.docx") and out["dest"] == up
    assert ("download", str(tmp_path / "report.docx")) in p.calls
    assert ("upload", str(tmp_path / "report.docx"), "report.docx") in p.calls


def test_download_path_never_overwrites_existing_local_file(tmp_path):
    (tmp_path / "report.docx").write_bytes(b"mine")
    up = {"item_id": "n5", "drive_id": "d2", "name": "report (1).docx", "web_url": "u5"}
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "report (1).docx")}, upload=up)
    run(p, mode="copy", downloads_dir=tmp_path)
    assert ("download", str(tmp_path / "report (1).docx")) in p.calls


@pytest.mark.parametrize("code", ["forbidden", "not_found"])
def test_copy_forbidden_or_missing_does_not_fall_back(code, tmp_path):
    p = FakeProvider(copy={"error": "x", "error_code": code})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["error_code"] == code
    assert not any(isinstance(c, tuple) for c in p.calls)


def test_upload_failure_after_download_reports_local_copy(tmp_path):
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "report.docx")},
                     upload={"error": "no space", "error_code": "unknown"})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["local_copy"] == str(tmp_path / "report.docx")
    assert out["original_remains"] is True


def test_download_failure_fails_the_transfer(tmp_path):
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"error": "dl failed", "error_code": "unknown"})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["local_copy"] is None


def test_bad_mode_fails_before_any_call():
    p = FakeProvider()
    out, _ = run(p, mode="delete")
    assert out["status"] == "failed" and p.calls == []


def test_stat_error_fails():
    p = FakeProvider(stat={"error": "gone", "error_code": "not_found"})
    out, _ = run(p)
    assert out["status"] == "failed" and out["error_code"] == "not_found"
    assert p.calls == ["stat"]


def test_new_name_is_used_for_lookup_and_upload(tmp_path):
    up = {"item_id": "n5", "drive_id": "d2", "name": "renamed.docx", "web_url": "u5"}
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "report.docx")}, upload=up)
    run(p, mode="copy", new_name="renamed.docx", downloads_dir=tmp_path)
    assert ("upload", str(tmp_path / "report.docx"), "renamed.docx") in p.calls
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_files_transfer_core.py -v`
Expected: FAIL (`skills._files.transfer` missing).

- [ ] **Step 3: Implement** `web/skills/_files/transfer.py`

```python
"""Provider-neutral file transfer: move or copy a file into a folder, riding out locks.

A provider is any object with stat, is_foreign_owner, move, copy, find_in_folder,
download and upload (see tests/test_files_transfer_core.py for the exact shapes).
Nothing here deletes anything: when a move is impossible the original stays and the
result says so.
"""

import time
from pathlib import Path

LOCK_RETRY_DELAYS = (3, 6)
_NO_FALLBACK = ("forbidden", "not_found")


def _result(status, method=None, original_remains=True, reason=None, dest=None, local_copy=None, **extra):
    return {
        "status": status,
        "method": method,
        "original_remains": original_remains,
        "reason": reason,
        "dest": dest,
        "local_copy": local_copy,
        **extra,
    }


def _failed(error, error_code="unknown", reason=None, local_copy=None):
    return _result(
        "failed",
        reason=reason,
        local_copy=local_copy,
        error=error,
        error_code=error_code,
        message=f"The file was not transferred: {error}",
    )


def _dest(d):
    return {
        "drive_id": d.get("drive_id", ""),
        "item_id": d.get("item_id", ""),
        "name": d.get("name", ""),
        "web_url": d.get("web_url", ""),
    }


def _copied_message(reason):
    why = {
        "locked": "the file is open or locked, so it could not be moved",
        "not_owner": "the file is in another person's OneDrive, so it was copied rather than moved",
    }.get(reason)
    head = f"Copied to the destination because {why}." if why else "Copied to the destination."
    return head + " The original is still in place. Gator never deletes files, so the user can remove it themselves."


def _unique_local_path(downloads_dir, name):
    base = Path(downloads_dir)
    candidate = base / name
    stem, suffix, n = candidate.stem, candidate.suffix, 1
    while candidate.exists():
        candidate = base / f"{stem} ({n}){suffix}"
        n += 1
    return str(candidate)


def _move_with_lock_retry(provider, source, dest_folder, new_name, sleep):
    moved = provider.move(source, dest_folder, new_name)
    for delay in LOCK_RETRY_DELAYS:
        if "error" not in moved or moved.get("error_code") != "locked":
            break
        sleep(delay)
        moved = provider.move(source, dest_folder, new_name)
    return moved


def _copied_dest(provider, copied, dest_folder, name, size):
    item_id = copied.get("item_id")
    drive_id = copied.get("dest_drive_id") or dest_folder["drive_id"]
    if item_id:
        meta = provider.stat({"drive_id": drive_id, "item_id": item_id})
        if "error" not in meta:
            return _dest(meta)
        return {"drive_id": drive_id, "item_id": item_id, "name": name, "web_url": ""}
    found = provider.find_in_folder(dest_folder, name, size)
    return _dest(found) if found else None


def transfer(provider, source, dest_folder, mode="move", new_name="", sleep=time.sleep, downloads_dir=None):
    if mode not in ("move", "copy"):
        return _failed("mode must be 'move' or 'copy'")
    info = provider.stat(source)
    if "error" in info:
        return _failed(info["error"], info.get("error_code", "unknown"))
    name = new_name or info.get("name", "")
    size = info.get("size")

    reason = None
    if mode == "move":
        if provider.is_foreign_owner(source):
            reason = "not_owner"
        else:
            moved = _move_with_lock_retry(provider, source, dest_folder, new_name, sleep)
            if "error" not in moved:
                return _result("moved", "native_move", False, None, _dest(moved), message="Moved. The file is now only at the destination.")
            if moved.get("error_code") != "locked":
                return _failed(moved["error"], moved.get("error_code", "unknown"))
            reason = "locked"

    copied = provider.copy(source, dest_folder, new_name)
    if "error" not in copied:
        if copied.get("status") == "pending":
            found = provider.find_in_folder(dest_folder, name, size)
            dest = _dest(found) if found else None
        else:
            dest = _copied_dest(provider, copied, dest_folder, name, size)
        if dest:
            return _result("copied", "server_copy", True, reason, dest, message=_copied_message(reason))
        return _result(
            "pending",
            "server_copy",
            True,
            reason,
            monitor_url=copied.get("monitor_url", ""),
            message="The copy is still running in OneDrive. Do not retry it; check the destination folder shortly.",
        )
    if copied.get("error_code") in _NO_FALLBACK:
        return _failed(copied["error"], copied["error_code"], reason)

    local = _unique_local_path(downloads_dir or Path.home() / "Downloads", name or "file")
    dl = provider.download(source, local)
    if "error" in dl:
        return _failed(dl["error"], dl.get("error_code", "unknown"), reason)
    up = provider.upload(dl["saved_to"], dest_folder, name)
    if "error" in up:
        return _failed(up["error"], up.get("error_code", "unknown"), reason, local_copy=dl["saved_to"])
    return _result(
        "copied",
        "download_upload",
        True,
        reason,
        _dest(up),
        local_copy=dl["saved_to"],
        message=_copied_message(reason) + f" A local copy is at {dl['saved_to']}.",
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_files_transfer_core.py -v`
Expected: PASS (all tests). If `test_download_path_never_overwrites_existing_local_file` fails, check that `_unique_local_path` is given `name="report.docx"` and `downloads_dir=tmp_path`.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_files/transfer.py tests/test_files_transfer_core.py
git commit -m "feat: provider-neutral file transfer with locked-file retry and copy fallback"
```

---

### Task 7: OneDrive provider

**Files:**

- Create: `web/skills/_m365/onedrive_provider.py`
- Test: `tests/test_onedrive_provider.py` (create)

**Interfaces:**

- Consumes: the provider contract from Task 6; `ft.store_in_folder` / `ft.file_source` (Task 5); `classify_graph_error` (Task 3); the four existing tool functions, injected.
- Produces: `OneDriveProvider(*, get_item, download, copy, move, client)` where `get_item(drive_id, item_id)`, `download(file_id=, drive_id=, local_path=)`, `copy(...)`, `move(...)` are the existing `_tool_*` callables (positional order as in `tools.py`) and `client()` returns a Graph client.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock

from skills._m365.onedrive_provider import OneDriveProvider


class Err(Exception):
    def __init__(self, status_code):
        super().__init__(f"Graph API {status_code}")
        self.status_code = status_code


def provider(gc=None, **ops):
    gc = gc or MagicMock()
    base = dict(get_item=MagicMock(), download=MagicMock(), copy=MagicMock(), move=MagicMock(), client=lambda: gc)
    base.update(ops)
    return OneDriveProvider(**base), gc


def _drives(gc, drive_type, drive_id="d1", mine="mine"):
    def get(path, params=None, **kw):
        if path == "/me/drive":
            return {"id": mine}
        return {"id": drive_id, "driveType": drive_type}
    gc.get.side_effect = get


def test_foreign_owner_true_for_someone_elses_onedrive():
    p, gc = provider()
    _drives(gc, "business", drive_id="theirs")
    assert p.is_foreign_owner({"drive_id": "theirs", "item_id": "i"}) is True


def test_own_onedrive_is_not_foreign():
    p, gc = provider()
    _drives(gc, "business", drive_id="mine")
    assert p.is_foreign_owner({"drive_id": "mine", "item_id": "i"}) is False


def test_sharepoint_library_is_not_foreign():
    p, gc = provider()
    _drives(gc, "documentLibrary", drive_id="lib")
    assert p.is_foreign_owner({"drive_id": "lib", "item_id": "i"}) is False


def test_unverifiable_owner_is_treated_as_foreign():
    p, gc = provider()
    gc.get.side_effect = Err(403)
    assert p.is_foreign_owner({"drive_id": "x", "item_id": "i"}) is True


def test_find_in_folder_matches_name_and_size_with_encoded_path():
    p, gc = provider()
    gc.get.return_value = {"id": "X", "name": "a b.docx", "size": 10, "webUrl": "u", "parentReference": {"driveId": "d2"}}
    found = p.find_in_folder({"drive_id": "d/2", "folder_id": "f+2"}, "a b.docx", 10)
    assert found == {"item_id": "X", "drive_id": "d2", "name": "a b.docx", "web_url": "u"}
    assert gc.get.call_args.args[0] == "/drives/d%2F2/items/f%2B2:/a%20b.docx"


def test_find_in_folder_none_on_size_mismatch_or_error():
    p, gc = provider()
    gc.get.return_value = {"id": "X", "name": "a.docx", "size": 99, "webUrl": "u", "parentReference": {}}
    assert p.find_in_folder({"drive_id": "d", "folder_id": "f"}, "a.docx", 10) is None
    gc.get.side_effect = Err(404)
    assert p.find_in_folder({"drive_id": "d", "folder_id": "f"}, "a.docx", 10) is None


def test_download_success_and_failure():
    dl = MagicMock(return_value={"saved_to": "C:/x/a.docx", "name": "a.docx", "size_bytes": 3})
    p, _ = provider(download=dl)
    out = p.download({"drive_id": "d", "item_id": "i"}, "C:/x/a.docx")
    assert out["saved_to"] == "C:/x/a.docx"
    dl.assert_called_once_with(file_id="i", drive_id="d", local_path="C:/x/a.docx")
    dl.side_effect = Err(423)
    out = p.download({"drive_id": "d", "item_id": "i"}, "C:/x/a.docx")
    assert out["error_code"] == "locked" and "error" in out


class UploadGC:
    def __init__(self):
        self.paths = []

    def put_binary(self, path, data, content_type="application/octet-stream"):
        self.paths.append(path)
        return {"id": "N1", "name": "a.txt", "size": len(data), "webUrl": "https://od/a.txt"}


def test_upload_returns_item_fields(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    gc = UploadGC()
    p, _ = provider(gc=gc)
    out = p.upload(str(f), {"drive_id": "d2", "folder_id": "f2"}, "")
    assert out == {"item_id": "N1", "drive_id": "d2", "name": "a.txt", "web_url": "https://od/a.txt", "size": 5}
    assert gc.paths[0].startswith("/drives/d2/items/f2:/a.txt:/content")


def test_upload_missing_local_file_is_not_found(tmp_path):
    p, _ = provider()
    out = p.upload(str(tmp_path / "nope.txt"), {"drive_id": "d", "folder_id": "f"}, "")
    assert out["error_code"] == "not_found"


def test_move_copy_stat_delegate_with_positional_ids():
    move, copy, get_item = MagicMock(return_value={"item_id": "m"}), MagicMock(return_value={"status": "completed"}), MagicMock(return_value={"name": "n"})
    p, _ = provider(move=move, copy=copy, get_item=get_item)
    src, dest = {"drive_id": "d1", "item_id": "i1"}, {"drive_id": "d2", "folder_id": "f2"}
    p.move(src, dest, "new.docx")
    move.assert_called_once_with("d1", "i1", "d2", "f2", "new.docx")
    p.copy(src, dest, "")
    copy.assert_called_once_with("d1", "i1", "d2", "f2", "")
    p.stat(src)
    get_item.assert_called_once_with("d1", "i1")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_onedrive_provider.py -v`
Expected: FAIL (`onedrive_provider` missing).

- [ ] **Step 3: Implement** `web/skills/_m365/onedrive_provider.py`

```python
"""OneDrive/SharePoint provider for skills._files.transfer.

Wraps the existing OneDrive tool functions (passed in, so this module never imports the
skill) and the shared upload primitives; nothing is reimplemented.
"""

import os
from urllib.parse import quote

from .._files.errors import classify_graph_error
from . import file_transfer as ft


def _q(value: str) -> str:
    return quote(value or "", safe="")


class OneDriveProvider:
    def __init__(self, *, get_item, download, copy, move, client):
        self._get_item = get_item
        self._download = download
        self._copy = copy
        self._move = move
        self._client = client

    def stat(self, ref):
        return self._get_item(ref["drive_id"], ref["item_id"])

    def is_foreign_owner(self, ref):
        """True when the file sits in another person's OneDrive, or that cannot be checked."""
        gc = self._client()
        try:
            drive = gc.get(f"/drives/{_q(ref['drive_id'])}", params={"$select": "id,driveType"})
            mine = gc.get("/me/drive", params={"$select": "id"})
        except Exception:
            return True
        return drive.get("driveType") in ("business", "personal") and drive.get("id") != mine.get("id")

    def move(self, ref, dest_folder, new_name):
        return self._move(ref["drive_id"], ref["item_id"], dest_folder["drive_id"], dest_folder["folder_id"], new_name)

    def copy(self, ref, dest_folder, new_name):
        return self._copy(ref["drive_id"], ref["item_id"], dest_folder["drive_id"], dest_folder["folder_id"], new_name)

    def find_in_folder(self, dest_folder, name, size):
        try:
            item = self._client().get(f"/drives/{_q(dest_folder['drive_id'])}/items/{_q(dest_folder['folder_id'])}:/{_q(name)}")
        except Exception:
            return None
        if size is not None and item.get("size") != size:
            return None
        pr = item.get("parentReference") or {}
        return {
            "item_id": item.get("id", ""),
            "drive_id": pr.get("driveId", dest_folder["drive_id"]),
            "name": item.get("name", name),
            "web_url": item.get("webUrl", ""),
        }

    def download(self, ref, local_path):
        try:
            return self._download(file_id=ref["item_id"], drive_id=ref["drive_id"], local_path=local_path)
        except Exception as e:
            return {"error": f"Download failed: {e}", "error_code": classify_graph_error(e)}

    def upload(self, local_path, dest_folder, name=""):
        path = os.path.expanduser(local_path)
        if not os.path.isfile(path):
            return {"error": f"Local file not found: {local_path}", "error_code": "not_found"}
        out = ft.store_in_folder(
            self._client(), ft.file_source(path, name), dest_folder["drive_id"], dest_folder["folder_id"]
        )
        if out.get("status") == "saved":
            return {
                "item_id": out["id"],
                "drive_id": out["drive_id"],
                "name": out["name"],
                "web_url": out["web_url"],
                "size": out["size"],
            }
        return {
            "error": out.get("detail") or out.get("hint") or out.get("error", "Upload failed"),
            "error_code": out.get("error_code", "unknown"),
        }
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_onedrive_provider.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_m365/onedrive_provider.py tests/test_onedrive_provider.py
git commit -m "feat: OneDrive provider for file transfer"
```

---

### Task 8: Register `file_transfer` and `file_upload` in the onedrive skill

**Files:**

- Modify: `web/skills/onedrive/tools.py` (TOOL_DEFS ~L539, TOOL_STATUS ~L1642, TOOL_HANDLERS ~L1649-1660, new handlers before `TOOL_STATUS.update`)
- Modify: `tests/code_sandbox/test_secrets_guard.py:163`
- Test: `tests/test_file_tools_registration.py` (create)

**Interfaces:**

- Consumes: `transfer()` (Task 6), `OneDriveProvider` (Task 7), the existing `_tool_*` functions, `get_skill_client`, `ONEDRIVE_SKILLS_DIR`.
- Produces: tools `file_transfer(source_drive_id, source_item_id, dest_drive_id, dest_folder_id, mode="move", new_name="")` and `file_upload(local_path, dest_drive_id, dest_folder_id, name="")`.

- [ ] **Step 1: Write the failing tests**

```python
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from skills.onedrive import tools as od

SKILLS = Path(__file__).parent.parent / "web" / "skills"


def _def(name):
    return next(t for t in od.TOOL_DEFS if t["name"] == name)


def test_new_tools_are_registered_everywhere():
    for name in ("file_transfer", "file_upload"):
        assert name in {t["name"] for t in od.TOOL_DEFS}
        assert callable(od.TOOL_HANDLERS[name])
        assert od.TOOL_STATUS[name]


def test_file_transfer_schema():
    s = _def("file_transfer")["input_schema"]
    assert set(s["required"]) == {"source_drive_id", "source_item_id", "dest_drive_id", "dest_folder_id"}
    assert s["properties"]["mode"]["enum"] == ["move", "copy"]
    assert "new_name" in s["properties"]


def test_file_upload_schema():
    s = _def("file_upload")["input_schema"]
    assert set(s["required"]) == {"local_path", "dest_drive_id", "dest_folder_id"}
    assert "name" in s["properties"]


def test_existing_tools_still_registered():
    names = {t["name"] for t in od.TOOL_DEFS}
    for n in ("read_onedrive_file", "list_onedrive_files", "search_onedrive_files", "download_onedrive_file",
              "resolve_teams_attachment", "move_onedrive_file", "copy_onedrive_file", "get_onedrive_item"):
        assert n in names and n in od.TOOL_HANDLERS


def test_no_delete_tool_exists():
    assert not [t["name"] for t in od.TOOL_DEFS if "delete" in t["name"].lower() or "remove" in t["name"].lower()]


def test_file_transfer_handler_moves_through_the_provider():
    gc = MagicMock()
    gc.get.side_effect = lambda path, params=None, **kw: (
        {"id": "mine"} if path == "/me/drive" else {"id": "mine", "driveType": "business"}
    )
    moved = {"item_id": "i1", "drive_id": "d2", "name": "a.docx", "web_url": "u"}
    with patch("skills._m365.helpers.get_skill_client", return_value=gc), \
         patch.object(od, "_tool_get_onedrive_item", return_value={"item_id": "i1", "drive_id": "mine", "name": "a.docx", "size": 1, "web_url": "u0"}), \
         patch.object(od, "_tool_move_onedrive_file", return_value=moved):
        out = od.TOOL_HANDLERS["file_transfer"](
            source_drive_id="mine", source_item_id="i1", dest_drive_id="d2", dest_folder_id="f2")
    assert out["status"] == "moved" and out["method"] == "native_move" and out["original_remains"] is False


def test_file_transfer_rejects_unknown_mode():
    out = od.TOOL_HANDLERS["file_transfer"](
        source_drive_id="d1", source_item_id="i1", dest_drive_id="d2", dest_folder_id="f2", mode="delete")
    assert out["status"] == "failed"


def test_skill_guide_covers_move_copy_lock_and_upload():
    text = (SKILLS / "onedrive" / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("file_transfer", "file_upload", "original_remains", "resolve_teams_attachment", "never deletes"):
        assert needle in text, needle
    assert "file_transfer" in (SKILLS / "m365-onedrive" / "SKILL.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_file_tools_registration.py -v`
Expected: FAIL (tools not registered). The guide test fails until Task 9 — leave it failing and finish it there, but note it now so it is not mistaken for a regression.

- [ ] **Step 3: Implement**

Append to the second `TOOL_DEFS.extend([...])` list (before its closing `])` at ~L539):

```python
    {
        "name": "file_transfer",
        "description": (
            "Move or copy a OneDrive/SharePoint file into a folder, including a Teams attachment. "
            "Use this instead of move_onedrive_file/copy_onedrive_file when the user asks to move or copy a file: "
            "if the file is locked (open in Word or Teams) or lives in someone else's OneDrive, it copies instead and "
            "tells you so. Gator never deletes files, so when original_remains is true the original is still in place "
            "and the user can remove it themselves. Result: status (moved|copied|pending|failed), method, "
            "original_remains, reason (locked|not_owner|null), dest {drive_id,item_id,name,web_url}, local_copy, message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_drive_id": {"type": "string", "description": "Drive ID of the source file"},
                "source_item_id": {"type": "string", "description": "Item ID of the source file"},
                "dest_drive_id": {"type": "string", "description": "Drive ID of the destination folder"},
                "dest_folder_id": {"type": "string", "description": "Item ID of the destination folder"},
                "mode": {"type": "string", "enum": ["move", "copy"], "description": "move (default) or copy"},
                "new_name": {"type": "string", "description": "Optional new filename at the destination"},
            },
            "required": ["source_drive_id", "source_item_id", "dest_drive_id", "dest_folder_id"],
        },
    },
    {
        "name": "file_upload",
        "description": (
            "Upload a local file into a OneDrive/SharePoint folder identified by drive_id and folder item ID. "
            "Never overwrites: if the name is taken the upload is renamed. Handles large files. "
            "Returns item_id, drive_id, name, web_url, size. Use list_onedrive_files to find folder IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "description": "Path of the local file to upload"},
                "dest_drive_id": {"type": "string", "description": "Drive ID of the destination folder"},
                "dest_folder_id": {"type": "string", "description": "Item ID of the destination folder"},
                "name": {"type": "string", "description": "Optional file name at the destination. Omit to keep the local name."},
            },
            "required": ["local_path", "dest_drive_id", "dest_folder_id"],
        },
    },
```

Insert before `TOOL_STATUS.update({` (~L1642):

```python
def _od_provider():
    from .._m365.helpers import get_skill_client
    from .._m365.onedrive_provider import OneDriveProvider

    return OneDriveProvider(
        get_item=_tool_get_onedrive_item,
        download=_tool_download_onedrive_file,
        copy=_tool_copy_onedrive_file,
        move=_tool_move_onedrive_file,
        client=lambda: get_skill_client(ONEDRIVE_SKILLS_DIR),
    )


def _tool_file_transfer(source_drive_id: str, source_item_id: str,
                        dest_drive_id: str, dest_folder_id: str,
                        mode: str = "move", new_name: str = "") -> dict:
    """Move or copy a file into a folder, copying instead when the source is locked."""
    from .._files.transfer import transfer
    return transfer(
        _od_provider(),
        {"drive_id": source_drive_id, "item_id": source_item_id},
        {"drive_id": dest_drive_id, "folder_id": dest_folder_id},
        mode=mode,
        new_name=new_name,
    )


def _tool_file_upload(local_path: str, dest_drive_id: str, dest_folder_id: str, name: str = "") -> dict:
    """Upload a local file into a OneDrive/SharePoint folder by ID, never overwriting."""
    return _od_provider().upload(local_path, {"drive_id": dest_drive_id, "folder_id": dest_folder_id}, name)
```

Add to `TOOL_STATUS.update({...})`:

```python
    "file_transfer": "\U0001f500 Transferring file...",
    "file_upload": "\U0001f4e4 Uploading file...",
```

Add to `TOOL_HANDLERS = {...}`:

```python
    "file_transfer": _tool_file_transfer,
```

Replace the final guard call so `file_upload` is guarded too:

```python
TOOL_HANDLERS.update(guard_path_args(
    {
        "download_onedrive_file": _tool_download_onedrive_file,
        "file_upload": _tool_file_upload,
    },
    "local_path",
))
```

In `tests/code_sandbox/test_secrets_guard.py`, add after line 163:

```python
        (od.TOOL_HANDLERS["file_upload"], {"local_path": target, "dest_drive_id": "d", "dest_folder_id": "f"}),
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_file_tools_registration.py tests/test_onedrive_file_routing.py tests/test_graph_id_encoding.py tests/code_sandbox/test_secrets_guard.py -v`
Expected: PASS except `test_skill_guide_covers_move_copy_lock_and_upload` (fixed in Task 9). The loader contract is also exercised by importing the app; run `python -m pytest tests -k "skill and (loader or contract or registry)" -q` and expect PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/onedrive/tools.py tests/test_file_tools_registration.py tests/code_sandbox/test_secrets_guard.py
git commit -m "feat: add file_transfer and file_upload tools to the OneDrive skill"
```

---

### Task 9: Skill guides

**Files:**

- Modify: `web/skills/onedrive/SKILL.md`
- Modify: `web/skills/m365-onedrive/SKILL.md`
- Test: `tests/test_file_tools_registration.py::test_skill_guide_covers_move_copy_lock_and_upload` (written in Task 8)

**Interfaces:** none.

- [ ] **Step 1: Confirm the guide test fails**

Run: `python -m pytest tests/test_file_tools_registration.py::test_skill_guide_covers_move_copy_lock_and_upload -v`
Expected: FAIL.

- [ ] **Step 2: Edit `web/skills/onedrive/SKILL.md`**

Keep the front matter and existing bullets. Add these bullets after the "Download a file to disk" bullet, before "Always present file names...":

```markdown
- "Move a file to a folder" / "put this in my X folder" → find the source with search_onedrive_files, list_onedrive_files or get_onedrive_item (use resolve_teams_attachment first for a Teams chat attachment), find the destination folder's drive_id and item id with list_onedrive_files, then call file_transfer with mode "move". Do not ask the user to move the file by hand and do not improvise with move_onedrive_file, download and upload: file_transfer already retries a locked file and falls back to a copy.
- "Copy a file" → file_transfer with mode "copy".
- Read the file_transfer result before answering. status "moved": the file is now only at the destination. status "copied" with original_remains true: the original is still in place. Say so in one sentence, give the reason (reason "locked": the file is open somewhere; reason "not_owner": it is in someone else's OneDrive; otherwise a plain copy), and tell the user they can remove the original themselves. Gator never deletes files, so never offer to delete it. status "pending": the copy is still running in OneDrive; say so and do not retry. status "failed": report the error in plain words.
- A Teams chat attachment lives in the sender's OneDrive or a SharePoint site, so file_transfer will usually copy it rather than move it. That is expected.
- "Upload a local file" / "save this file to my OneDrive folder" → file_upload with local_path, dest_drive_id and dest_folder_id. It never overwrites; a name clash gets a numeric suffix.
- Always give the user the destination web_url from the result.
```

- [ ] **Step 3: Edit `web/skills/m365-onedrive/SKILL.md`**

Add under `## Rules`:

```markdown
- To upload into a folder by drive and folder ID, or to move or copy a file between folders or drives, use the onedrive skill's `file_upload` and `file_transfer` tools.
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_file_tools_registration.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add web/skills/onedrive/SKILL.md web/skills/m365-onedrive/SKILL.md
git commit -m "docs: teach the OneDrive skill guide about file_transfer, file_upload and locked files"
```

---

### Task 10: Full regression run and real-tenant and browser verification

**Files:** none modified unless a check fails.

- [ ] **Step 1: Run the full Python suite and the JS tests**

```bash
python -m pytest tests -q
node --test tests/
```

Expected: no new failures against `main`. Pre-existing failures must be confirmed identical with `git stash`-free comparison: run the same commands on `main` in the original checkout and compare.

- [ ] **Step 2: Browser check of the option card**

Start the dev server with `powershell -File dev.ps1` from the worktree, open Gator, and trigger an ask_user card with long labels and descriptions (ask Gator: "Ask me which of these three long options I prefer using ask_user, each with a 200 character description"). Confirm no horizontal overflow at the normal width and at a narrow window (about 400 px) and screenshot both.

- [ ] **Step 3: Browser check of the permission resend**

Trigger a permission card (ask Gator to run a Python snippet). Before clicking Allow, restart the dev server so the in-memory approval is gone. Click Allow. Expected: no "expired" dead end; the message is re-sent and a fresh permission card appears; clicking Allow on it runs the snippet.

- [ ] **Step 4: Real-tenant locked-file check**

Using a Teams chat that has a `.docx` attachment sent to you:

1. Open the attachment in Word desktop and leave it open.
2. In Gator: "Move the file attached in <chat> to my OneDrive folder <folder>."
3. Expected: Gator calls `resolve_teams_attachment` then `file_transfer`; the result is `copied` with `original_remains: true` (reason `not_owner` or `locked`); Gator tells you the original is still in place and does not offer to delete it; the file opens from the returned `web_url`.
4. Repeat with a file in your own OneDrive held open in Word. Expected: retries for about 9 seconds, then `copied` with reason `locked`. Record whether Graph's `/copy` succeeded on the locked file or the download+upload fallback ran (`method`).
5. Repeat with the file closed. Expected: `moved`, `original_remains: false`.
6. `file_upload` check: "Upload C:\path\to\small.txt to <folder>" then upload it again. Expected: the second upload gets a numeric suffix and nothing is overwritten.
7. Large upload check: upload a file over 4 MB. Expected: `size` in the result equals the local size.

Also confirm the unverified assumptions from the design: whether copy and download work for a SharePoint check-out lock and for a sensitivity-labelled file, and whether the label carries to the copy. Report findings; change nothing for them unless a test shows a failure.

- [ ] **Step 5: Report**

Summarise results (tests, screenshots, tenant outcomes) to the user. Do not push or open a PR unless asked.

---

## Self-Review

**Spec coverage**

- Existing tools stay; copy poll fix and `error_code` on move/copy/get item: Task 4.
- Tools in the onedrive skill with lazy imports and neutral core in `_files`: Tasks 6-8.
- File ref and provider interface: Task 6 (contract) and Task 7 (OneDrive provider).
- Upload (encoding, simple vs session, `rename`, never overwrite): Task 5.
- `file_transfer` flow (copy mode, foreign owner via driveType, lock retry 3s/6s, copy fallback, download+upload to `~/Downloads`, verification, `pending` status, result schema): Task 6, Task 7.
- Safety (path guard, no delete, destinations named by the user): Task 8 guard + secrets test, `test_no_delete_tool_exists`.
- Skill guides: Task 9.
- UI: card wrap Task 1; approval resend Task 2.
- Testing section (mocked Graph cases, existing tests unchanged, real tenant, browser): Tasks 4-8, 10.
- Spec deviation recorded in the spec: stat and download stay as `get_onedrive_item` and `download_onedrive_file` rather than new `file_info`/`file_download` aliases.

**Placeholder scan:** no TBD/TODO; every code step has code.

**Type consistency:** `transfer(provider, source, dest_folder, mode, new_name, sleep, downloads_dir)` is called identically in Task 6 tests and Task 8's `_tool_file_transfer`. Provider method names (`stat`, `is_foreign_owner`, `move`, `copy`, `find_in_folder`, `download`, `upload`) match across Tasks 6 and 7. `OneDriveProvider` kwargs (`get_item`, `download`, `copy`, `move`, `client`) match Task 8's `_od_provider`. `store_in_folder` / `file_source` signatures match Task 5 and Task 7. `error_code` values are the same five strings everywhere.
