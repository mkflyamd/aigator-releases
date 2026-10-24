# Narration Approval Transaction and Skill Pinning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make narration approval an atomic, versioned, verifiable transaction and keep the Demo Recorder skill and project pinned to a chat tab, so approval never fires into a stale or wrong context (issue #55 items #10, #11, plan B 2-4, and the #12 routing aspect).

**Architecture:** A new backend module `web/narration_approval.py` writes an immutable approval record, mirrors it to `work/narration.json`, and commits by setting `project.json` `ext.approval`. The frontend awaits that POST, checks `res.ok`, and only then submits the chat trigger carrying the approval id. A client pin (`tab-pin-<tabId>`) sends `pinned_skill` and `pinned_project_id` on every turn; the server resolves it once and locks skill selection for the turn. The skill loads the approval through a stdlib-only script that re-verifies hash and media fingerprint.

**Tech Stack:** Python 3 / FastAPI / pytest, vanilla JS in `web/static/app.js` (tested with Node `vm`), Markdown skill file. Builds on SP3 (`web/demo_projects.py`, `/api/demo-projects/*`); does not redefine it.

Spec: `docs/superpowers/specs/2026-10-19-approval-transaction-design.md`

## Global Constraints

- Do not add `Co-Authored-By` lines in commit messages.
- This project is called **AI Gator**. Never refer to it as a POC.
- Use `aigator-fake-api-key` as the only fake credential in tests, examples, fixtures, and documentation. Do not invent alternate fake API keys, tokens, passwords, or secrets.
- Every new POST/PUT/PATCH/DELETE route must use `dependencies=[Depends(verify_csrf)]` from `web/security.py`. `tests/test_csrf_route_inventory.py` fails CI otherwise; do not add routes to `tests/csrf_route_baseline.txt`. This plan adds no new routes; the two existing narration routes keep their CSRF dependency.
- Email, Teams, and Slack messages must NEVER auto-send. Always draft-only and require explicit human approval before sending. (Narration approval is a human click; the agent never calls mutating routes.)
- All LLM calls go through `llm.gateway`. This plan adds no LLM call sites.
- SP3's contract test (`tests/demo_project_state/test_skill_no_singletons.py`) forbids `latest-output`, `set-output`, `latest_output.json`, `narration_pending.json` and `gator_demos` in SKILL.md and skill scripts, and requires `demo_projects.json`, `PROJECT_DIR`, `work/narration.json` and `final/` in SKILL.md. Every SKILL.md edit here must keep that test green.
- Prerequisite: PRs #79, #82, #83, #84 and SP3 are merged. Anchors in SKILL.md, app.js and chat.py are post-SP3 text; locate them with grep, not line numbers.

---

## File Structure

| File                                                      | Action | Responsibility                                                                          |
| --------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------- |
| `web/narration_approval.py`                               | Create | `approve()` transaction, `canonical_hash`, `media_fingerprint`, `ApprovalError`         |
| `web/routes/demo_projects.py`                             | Modify | SP3 narration route calls `approve()`                                                   |
| `web/routes/recorder.py`                                  | Modify | Legacy `narration-approved` shim calls `approve()`                                      |
| `web/skills/gator-demo-recorder/scripts/load_approval.py` | Create | Stdlib-only verified loader and CLI used by Phase 4                                     |
| `web/skill_pin.py`                                        | Create | `Pin`, `resolve_pin`, `PIN_CONTEXT_PROVIDERS`, `pin_context_block`                      |
| `web/routes/chat.py`                                      | Modify | `ChatRequest` pin fields, `_skills_locked`, pin context injection                       |
| `web/static/app.js`                                       | Modify | Pure approval/pin helpers, awaited approval handler, pin state and chip, doSend fields  |
| `web/static/style.css`                                    | Modify | `.skill-pin-chip`                                                                       |
| `web/skills/gator-demo-recorder/SKILL.md`                 | Modify | Widget `approve()`, `pin_skill`/`project_id` on messages, `load_approval.py` in Phase 4 |
| `tests/approval_transaction/conftest.py`                  | Create | `store` and `client` fixtures                                                           |
| `tests/approval_transaction/test_approval.py`             | Create | Transaction unit tests                                                                  |
| `tests/approval_transaction/test_routes.py`               | Create | Route and shim tests                                                                    |
| `tests/approval_transaction/test_load_approval.py`        | Create | Loader parity, codes, CLI                                                               |
| `tests/approval_transaction/test_pinning.py`              | Create | `resolve_pin`, provider, chat.py source assertions                                      |
| `tests/approval_transaction/test_skill_contract.py`       | Create | SKILL.md contract                                                                       |
| `tests/skill_pin.test.js`                                 | Create | Pin state pure functions and send-path source assertions (Task 5)                       |
| `tests/narration_approval.test.js`                        | Create | Approval parsing/trigger pure functions and bridge source assertions (Task 6)           |

---

### Task 1: Approval transaction module

**Files:**

- Create: `web/narration_approval.py`
- Create: `tests/approval_transaction/conftest.py`
- Test: `tests/approval_transaction/test_approval.py`

**Interfaces:**

- Consumes (SP3, `web/demo_projects.py`, imported as `import demo_projects as dp`): `dp.get_project(pid) -> dict` (keys `path`, `raw` absolute or None, `ext`; raises `KeyError` for an unknown id), `dp.update_project(pid, **fields)`, `dp.set_ext(pid, namespace, value)`, `dp.atomic_write_json(path, data)`, `dp.create_project(name=None, root=None) -> dict`, `dp.INDEX_PATH`.
- Produces:
  - `ApprovalError(ValueError)`
  - `canonical_hash(segments: list, flags: dict) -> str` (hex SHA-256)
  - `media_fingerprint(path: str | Path | None) -> str | None`
  - `approve(project_id: str, segments: list, flags: dict) -> dict` returning the SP3 project dict plus `approval: {approval_id, version, approved_at, sha256, segment_count, reused}`.
  - Files: `work/approvals/<approval_id>.json`, `work/narration.json` (with `approval_id`, `version`), `project.json` `ext.approval = {current_id, version, sha256, approved_at, media_fingerprint}`.

- [ ] **Step 1: Confirm SP3 signatures**

Run: `grep -n "^def get_project\|^def update_project\|^def set_ext\|^def atomic_write_json\|^def create_project\|^INDEX_PATH" web/demo_projects.py`
Expected: all six names present. If a name differs, adapt this task's code to SP3's actual names before continuing.

- [ ] **Step 2: Create the test fixtures**

`tests/approval_transaction/conftest.py` (the `store` fixture is copied from SP3's `tests/demo_project_state/conftest.py`; fixtures cannot be imported across test dirs):

```python
import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    import demo_projects as dp

    cfg: dict = {}
    monkeypatch.setattr(dp, "INDEX_PATH", tmp_path / "gator" / "demo_projects.json")
    monkeypatch.setattr(dp, "DEFAULT_ROOT", tmp_path / "demos")
    monkeypatch.setattr(dp, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(dp, "save_config", lambda d: (cfg.clear(), cfg.update(d)))
    return dp


@pytest.fixture
def client(store):
    from fastapi.testclient import TestClient

    from main import app
    from security import get_csrf_token

    c = TestClient(app)
    c.headers.update({"X-CSRF-Token": get_csrf_token("testserver")})
    return c
```

Run: `grep -n "^from\|^import" tests/test_csrf_route_inventory.py | head` and confirm the app import path (`main`/`app`) matches; use whatever that test uses to import the FastAPI app.

- [ ] **Step 3: Write the failing tests**

`tests/approval_transaction/test_approval.py`:

```python
import json
import os
from pathlib import Path

import pytest

import narration_approval as na

SEGS = [{"text": "Open the app", "start": 0.0}, {"text": "Click save", "start": 2.5}]
FLAGS = {"music": False}


def _project_with_raw(store, data=b"raw-bytes-one"):
    p = store.create_project()
    raw = Path(p["path"]) / "source" / "rec.mp4"
    raw.write_bytes(data)
    store.update_project(p["project_id"], raw=str(raw))
    return p["project_id"], raw


def test_canonical_hash_is_key_order_insensitive():
    a = na.canonical_hash([{"text": "x", "start": 1}], {"a": 1, "b": 2})
    b = na.canonical_hash([{"start": 1, "text": "x"}], {"b": 2, "a": 1})
    assert a == b and len(a) == 64


def test_canonical_hash_changes_with_text():
    assert na.canonical_hash(SEGS, FLAGS) != na.canonical_hash(
        [{"text": "Open the application", "start": 0.0}, SEGS[1]], FLAGS)


def test_fingerprint_none_without_file(tmp_path):
    assert na.media_fingerprint(None) is None
    assert na.media_fingerprint(tmp_path / "missing.mp4") is None


def test_fingerprint_ignores_mtime_and_tracks_content(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"A" * 200_000)
    first = na.media_fingerprint(f)
    os.utime(f, (1, 1))
    assert na.media_fingerprint(f) == first
    f.write_bytes(b"A" * 199_999 + b"B")
    assert na.media_fingerprint(f) != first


def test_fingerprint_small_file(tmp_path):
    f = tmp_path / "s.mp4"
    f.write_bytes(b"tiny")
    assert len(na.media_fingerprint(f)) == 64


def test_approve_writes_record_mirror_ext_and_stage(store):
    pid, _ = _project_with_raw(store)
    out = na.approve(pid, SEGS, FLAGS)
    a = out["approval"]
    assert a["version"] == 1 and a["reused"] is False and a["segment_count"] == 2
    assert a["approval_id"] == f"appr_1_{a['sha256'][:8]}"
    root = Path(out["path"])
    record = json.loads((root / "work" / "approvals" / f"{a['approval_id']}.json").read_text("utf-8"))
    assert record["segments"] == SEGS and record["project_id"] == pid
    assert record["media_fingerprint"] == na.media_fingerprint(out["raw"])
    mirror = json.loads((root / "work" / "narration.json").read_text("utf-8"))
    assert mirror["approval_id"] == a["approval_id"] and mirror["segments"] == SEGS
    ext = store.get_project(pid)["ext"]["approval"]
    assert ext["current_id"] == a["approval_id"] and ext["version"] == 1
    assert out["stage"] == "narration_approved"


def test_identical_reapproval_is_reused(store):
    pid, _ = _project_with_raw(store)
    first = na.approve(pid, SEGS, FLAGS)["approval"]
    second = na.approve(pid, SEGS, FLAGS)["approval"]
    assert second["reused"] is True
    assert second["approval_id"] == first["approval_id"] and second["version"] == 1


def test_text_change_bumps_version_and_keeps_old_record(store):
    pid, _ = _project_with_raw(store)
    first = na.approve(pid, SEGS, FLAGS)["approval"]
    second = na.approve(pid, [{"text": "Changed"}], FLAGS)["approval"]
    assert second["version"] == 2 and second["approval_id"] != first["approval_id"]
    root = Path(store.get_project(pid)["path"])
    assert (root / "work" / "approvals" / f"{first['approval_id']}.json").is_file()
    assert (root / "work" / "approvals" / f"{second['approval_id']}.json").is_file()


def test_media_change_bumps_version_even_with_same_text(store):
    pid, raw = _project_with_raw(store)
    first = na.approve(pid, SEGS, FLAGS)["approval"]
    raw.write_bytes(b"different raw bytes here")
    second = na.approve(pid, SEGS, FLAGS)["approval"]
    assert second["version"] == 2 and second["reused"] is False
    assert second["sha256"] == first["sha256"]


@pytest.mark.parametrize("segments,flags", [
    ([], {}),
    (None, {}),
    ("nope", {}),
    ([{"start": 1}], {}),
    ([{"text": 5}], {}),
    (["x"], {}),
    (SEGS, []),
])
def test_validation_rejects_bad_input(store, segments, flags):
    pid, _ = _project_with_raw(store)
    with pytest.raises(na.ApprovalError):
        na.approve(pid, segments, flags)


def test_unknown_project_raises_keyerror(store):
    with pytest.raises(KeyError):
        na.approve("demo_19990101_000000", SEGS, FLAGS)


def test_legacy_mirror_written_next_to_index(store):
    pid, _ = _project_with_raw(store)
    na.approve(pid, SEGS, FLAGS)
    legacy = store.INDEX_PATH.parent / "narration_pending.json"
    data = json.loads(legacy.read_text("utf-8"))
    assert data["segments"] == SEGS and data["flags"] == FLAGS


def test_approval_without_raw_has_null_fingerprint(store):
    p = store.create_project()
    out = na.approve(p["project_id"], SEGS, FLAGS)
    record = json.loads((Path(out["path"]) / "work" / "approvals" /
                         f"{out['approval']['approval_id']}.json").read_text("utf-8"))
    assert record["media_fingerprint"] is None
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/approval_transaction/test_approval.py -v`
Expected: FAIL / collection error `ModuleNotFoundError: No module named 'narration_approval'`.

- [ ] **Step 5: Implement the module**

`web/narration_approval.py`:

```python
"""Narration approval transaction: immutable, versioned approvals per demo project."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import demo_projects as dp

_LOCK = threading.Lock()
_EDGE = 65536


class ApprovalError(ValueError):
    pass


def canonical_hash(segments: list, flags: dict) -> str:
    blob = json.dumps({"segments": segments, "flags": flags}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def media_fingerprint(path) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    size = p.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(_EDGE))
        if size > _EDGE:
            f.seek(max(size - _EDGE, _EDGE))
            h.update(f.read(_EDGE))
    return h.hexdigest()


def _validate(segments, flags) -> None:
    if not isinstance(segments, list) or not segments:
        raise ApprovalError("segments must be a non-empty list")
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict) or not isinstance(seg.get("text"), str):
            raise ApprovalError(f"segment {i} needs a text string")
    if not isinstance(flags, dict):
        raise ApprovalError("flags must be an object")


def _write_legacy_mirror(segments: list, flags: dict, approved_at: str) -> None:
    try:
        dp.atomic_write_json(dp.INDEX_PATH.parent / "narration_pending.json",
                             {"segments": segments, "flags": flags, "timestamp": approved_at})
    except OSError:
        pass


def approve(project_id: str, segments: list, flags: dict) -> dict:
    _validate(segments, flags)
    sha = canonical_hash(segments, flags)
    with _LOCK:
        project = dp.get_project(project_id)
        root = Path(project["path"])
        fingerprint = media_fingerprint(project.get("raw"))
        current = (project.get("ext") or {}).get("approval") or {}
        approvals = root / "work" / "approvals"
        reusable = (
            current.get("current_id")
            and current.get("sha256") == sha
            and current.get("media_fingerprint") == fingerprint
            and (approvals / f"{current['current_id']}.json").is_file()
        )
        if reusable:
            reused = True
            version = current["version"]
            approval_id = current["current_id"]
            approved_at = current["approved_at"]
        else:
            reused = False
            version = int(current.get("version") or 0) + 1
            approval_id = f"appr_{version}_{sha[:8]}"
            approved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            approvals.mkdir(parents=True, exist_ok=True)
            dp.atomic_write_json(approvals / f"{approval_id}.json", {
                "approval_id": approval_id, "version": version, "project_id": project_id,
                "approved_at": approved_at, "segments": segments, "flags": flags,
                "sha256": sha, "media_fingerprint": fingerprint,
            })
            dp.atomic_write_json(root / "work" / "narration.json", {
                "segments": segments, "flags": flags, "timestamp": approved_at,
                "approval_id": approval_id, "version": version,
            })
            dp.update_project(project_id, stage="narration_approved",
                              narration={"approved_at": approved_at})
            dp.set_ext(project_id, "approval", {
                "current_id": approval_id, "version": version, "sha256": sha,
                "approved_at": approved_at, "media_fingerprint": fingerprint,
            })
    _write_legacy_mirror(segments, flags, approved_at)
    result = dp.get_project(project_id)
    result["approval"] = {
        "approval_id": approval_id, "version": version, "approved_at": approved_at,
        "sha256": sha, "segment_count": len(segments), "reused": reused,
    }
    return result
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/approval_transaction/test_approval.py -v`
Expected: PASS (all). If `test_media_change_bumps_version_even_with_same_text` fails on its last assertion, the assertion is only guarding against a same-id collision; version 2 with the same sha yields id `appr_2_<sha8>` which differs from `appr_1_<sha8>`, so it must pass.

- [ ] **Step 7: Commit**

```bash
git add web/narration_approval.py tests/approval_transaction/conftest.py tests/approval_transaction/test_approval.py
git commit -m "feat: versioned narration approval transaction"
```

---

### Task 2: Route and legacy shim wiring

**Files:**

- Modify: `web/routes/demo_projects.py` (the `POST /api/demo-projects/{project_id}/narration` handler)
- Modify: `web/routes/recorder.py` (the `POST /api/recorder/narration-approved` shim)
- Test: `tests/approval_transaction/test_routes.py`

**Interfaces:**

- Consumes: `narration_approval.approve`, `narration_approval.ApprovalError` (Task 1); SP3 route helpers `_get(project_id)` and `_bad(exc)` in `web/routes/demo_projects.py`, `NarrationRequest` model with `segments` and `flags`.
- Produces: both routes return the project dict plus an `approval` summary; invalid input returns 400; unknown project returns 404 (narration route); the shim returns `{"ok": True, "project_id": pid, "approval": {...}}` or a 400 `{"ok": False, "error": ...}`.

- [ ] **Step 1: Locate the SP3 handlers**

Run: `grep -n "narration" web/routes/demo_projects.py web/routes/recorder.py`
Expected: the SP3 narration route (currently calling `dp.save_narration`) and the legacy `narration-approved` shim. Note the helper names `_get` and `_bad` actually used in `demo_projects.py`; use those.

- [ ] **Step 2: Write the failing tests**

`tests/approval_transaction/test_routes.py`:

```python
import json
from pathlib import Path

SEGS = [{"text": "Open the app"}, {"text": "Click save"}]


def test_narration_route_returns_approval(client, store):
    pid = store.create_project()["project_id"]
    r = client.post(f"/api/demo-projects/{pid}/narration", json={"segments": SEGS, "flags": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["approval"]["version"] == 1 and body["approval"]["segment_count"] == 2
    assert body["stage"] == "narration_approved"


def test_narration_route_empty_segments_is_400(client, store):
    pid = store.create_project()["project_id"]
    r = client.post(f"/api/demo-projects/{pid}/narration", json={"segments": [], "flags": {}})
    assert r.status_code == 400


def test_narration_route_unknown_project_is_404(client):
    r = client.post("/api/demo-projects/demo_19990101_000000/narration",
                    json={"segments": SEGS, "flags": {}})
    assert r.status_code == 404


def test_narration_route_requires_csrf(client, store):
    pid = store.create_project()["project_id"]
    r = client.post(f"/api/demo-projects/{pid}/narration", json={"segments": SEGS, "flags": {}},
                    headers={"X-CSRF-Token": ""})
    assert r.status_code == 403


def test_reapproval_same_content_reports_reused(client, store):
    pid = store.create_project()["project_id"]
    client.post(f"/api/demo-projects/{pid}/narration", json={"segments": SEGS, "flags": {}})
    r = client.post(f"/api/demo-projects/{pid}/narration", json={"segments": SEGS, "flags": {}})
    assert r.json()["approval"]["reused"] is True


def test_legacy_shim_uses_transaction(client, store):
    pid = store.create_project()["project_id"]
    r = client.post("/api/recorder/narration-approved", json={"segments": SEGS, "flags": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["project_id"] == pid
    assert body["approval"]["version"] == 1
    root = Path(store.get_project(pid)["path"])
    mirror = json.loads((root / "work" / "narration.json").read_text("utf-8"))
    assert mirror["approval_id"] == body["approval"]["approval_id"]


def test_legacy_shim_rejects_empty_segments(client, store):
    store.create_project()
    r = client.post("/api/recorder/narration-approved", json={"segments": [], "flags": {}})
    assert r.status_code == 400 and r.json()["ok"] is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/approval_transaction/test_routes.py -v`
Expected: FAIL (`approval` key missing, empty-segments not 400).

- [ ] **Step 4: Edit the SP3 narration route**

In `web/routes/demo_projects.py` add `import narration_approval` next to the other imports and replace the handler body so it reads:

```python
@router.post("/api/demo-projects/{project_id}/narration", dependencies=[Depends(verify_csrf)])
async def narration(project_id: str, req: NarrationRequest):
    _get(project_id)
    try:
        return narration_approval.approve(project_id, req.segments, req.flags)
    except narration_approval.ApprovalError as exc:
        raise _bad(exc)
```

Keep the existing decorator, function name and request model as SP3 defined them; only the body and the import change.

- [ ] **Step 5: Edit the legacy shim**

In `web/routes/recorder.py` add `import narration_approval` and replace the shim body with:

```python
    pid = dp.get_active_id()
    if not pid:
        return {"ok": True}
    try:
        approval = narration_approval.approve(pid, req.segments, req.flags)["approval"]
    except narration_approval.ApprovalError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "project_id": pid, "approval": approval}
```

Keep the shim's existing decorator (with `verify_csrf`), signature and request model. Ensure `JSONResponse` is imported from `fastapi.responses` in that file. `req.segments` and `req.flags` must match the shim's actual request model field names; adjust to SP3's model if different.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/approval_transaction tests/demo_project_state tests/test_csrf_route_inventory.py -v`
Expected: PASS. The CSRF inventory test passes unchanged because no routes were added.

- [ ] **Step 7: Commit**

```bash
git add web/routes/demo_projects.py web/routes/recorder.py tests/approval_transaction/test_routes.py
git commit -m "feat: route narration approval through the transaction"
```

---

### Task 3: Verified approval loader for the skill

**Files:**

- Create: `web/skills/gator-demo-recorder/scripts/load_approval.py`
- Test: `tests/approval_transaction/test_load_approval.py`

**Interfaces:**

- Consumes: the on-disk format from Task 1 (`project.json` `ext.approval`, `work/approvals/<id>.json`, `raw` relative to the project dir). It must not import from `web/` (skill scripts run as a standalone subprocess), so the hash and fingerprint code is duplicated and a parity test guards drift.
- Produces:
  - `ApprovalError(code, message)` with `code` in `missing | superseded | corrupt | stale_media`
  - `canonical_hash(segments, flags) -> str`, `media_fingerprint(path) -> str | None`
  - `load(project_dir, approval_id=None) -> dict` (the verified approval record)
  - CLI: `python load_approval.py --project-dir DIR [--approval-id ID] [--segments-out FILE]`. Exit 0 prints `{"ok": true, "approval_id", "version", "approved_at", "segment_count", "flags", "segments_out"}`. Exit 2 prints `{"ok": false, "code", "error"}`. `--segments-out` writes the segments list as JSON.

- [ ] **Step 1: Write the failing tests**

`tests/approval_transaction/test_load_approval.py`:

```python
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

import narration_approval as na

SCRIPT = (Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder"
          / "scripts" / "load_approval.py")
spec = importlib.util.spec_from_file_location("load_approval_under_test", SCRIPT)
la = importlib.util.module_from_spec(spec)
spec.loader.exec_module(la)

SEGS = [{"text": "Open the app"}, {"text": "Naïve café — ünïcode 日本語"}]


def _approved(store, data=b"raw-one"):
    p = store.create_project()
    raw = Path(p["path"]) / "source" / "rec.mp4"
    raw.write_bytes(data)
    store.update_project(p["project_id"], raw=str(raw))
    out = na.approve(p["project_id"], SEGS, {"music": False})
    return Path(out["path"]), out["approval"], raw


def test_hash_parity_with_backend():
    for segs, flags in [(SEGS, {"music": True}), ([{"text": "a", "start": 1.5}], {})]:
        assert la.canonical_hash(segs, flags) == na.canonical_hash(segs, flags)


@pytest.mark.parametrize("size", [0, 10, 65536, 65537, 200_000])
def test_fingerprint_parity_with_backend(tmp_path, size):
    f = tmp_path / "m.bin"
    f.write_bytes(bytes(i % 251 for i in range(size)))
    assert la.media_fingerprint(f) == na.media_fingerprint(f)


def test_load_returns_verified_record(store):
    root, approval, _ = _approved(store)
    rec = la.load(root, approval["approval_id"])
    assert rec["segments"] == SEGS and rec["version"] == 1


def test_load_without_id_uses_current(store):
    root, approval, _ = _approved(store)
    assert la.load(root)["approval_id"] == approval["approval_id"]


def test_missing_when_no_approval(store):
    p = store.create_project()
    with pytest.raises(la.ApprovalError) as e:
        la.load(p["path"])
    assert e.value.code == "missing"


def test_superseded_when_id_is_old(store):
    root, approval, _ = _approved(store)
    na.approve(Path(root).name, [{"text": "New words"}], {})
    with pytest.raises(la.ApprovalError) as e:
        la.load(root, approval["approval_id"])
    assert e.value.code == "superseded"


def test_corrupt_when_record_tampered(store):
    root, approval, _ = _approved(store)
    rec_path = root / "work" / "approvals" / f"{approval['approval_id']}.json"
    rec = json.loads(rec_path.read_text("utf-8"))
    rec["segments"][0]["text"] = "tampered"
    rec_path.write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(la.ApprovalError) as e:
        la.load(root)
    assert e.value.code == "corrupt"


def test_corrupt_when_record_file_missing(store):
    root, approval, _ = _approved(store)
    (root / "work" / "approvals" / f"{approval['approval_id']}.json").unlink()
    with pytest.raises(la.ApprovalError) as e:
        la.load(root)
    assert e.value.code == "corrupt"


def test_stale_media_when_raw_changes(store):
    root, _, raw = _approved(store)
    raw.write_bytes(b"a completely different recording")
    with pytest.raises(la.ApprovalError) as e:
        la.load(root)
    assert e.value.code == "stale_media"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, encoding="utf-8")


def test_cli_success_writes_segments(store, tmp_path):
    root, approval, _ = _approved(store)
    out = tmp_path / "segments.json"
    r = _run("--project-dir", str(root), "--approval-id", approval["approval_id"],
             "--segments-out", str(out))
    assert r.returncode == 0
    body = json.loads(r.stdout)
    assert body["ok"] is True and body["segment_count"] == 2
    assert json.loads(out.read_text("utf-8")) == SEGS


def test_cli_failure_exit_2_with_code(store):
    p = store.create_project()
    r = _run("--project-dir", p["path"])
    assert r.returncode == 2
    body = json.loads(r.stdout)
    assert body["ok"] is False and body["code"] == "missing" and body["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/approval_transaction/test_load_approval.py -v`
Expected: FAIL at import (the script does not exist).

- [ ] **Step 3: Implement the script**

`web/skills/gator-demo-recorder/scripts/load_approval.py`:

```python
#!/usr/bin/env python3
"""Load and verify the current narration approval for a demo project. Standard library only."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

_EDGE = 65536


class ApprovalError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def canonical_hash(segments, flags):
    blob = json.dumps({"segments": segments, "flags": flags}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def media_fingerprint(path):
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    size = p.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(_EDGE))
        if size > _EDGE:
            f.seek(max(size - _EDGE, _EDGE))
            h.update(f.read(_EDGE))
    return h.hexdigest()


def _read_json(path, code, message):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ApprovalError(code, message) from None


def load(project_dir, approval_id=None):
    root = Path(project_dir)
    project = _read_json(root / "project.json", "missing", "project.json not found or unreadable")
    ext = (project.get("ext") or {}).get("approval")
    if not ext or not ext.get("current_id"):
        raise ApprovalError("missing", "no narration approval is recorded for this project")
    current = ext["current_id"]
    if approval_id and approval_id != current:
        raise ApprovalError("superseded", f"approval {approval_id} was replaced by {current}")
    record = _read_json(root / "work" / "approvals" / f"{current}.json", "corrupt",
                        f"approval record {current} is missing or unreadable")
    segments, flags = record.get("segments"), record.get("flags")
    if (not isinstance(segments, list) or not isinstance(flags, dict)
            or canonical_hash(segments, flags) != record.get("sha256")):
        raise ApprovalError("corrupt", f"approval record {current} failed its integrity check")
    raw = project.get("raw")
    if media_fingerprint(root / raw if raw else None) != record.get("media_fingerprint"):
        raise ApprovalError("stale_media",
                            "the recording changed after this approval; approve the narration again")
    return record


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--approval-id")
    ap.add_argument("--segments-out")
    args = ap.parse_args(argv)
    try:
        record = load(args.project_dir, args.approval_id)
    except ApprovalError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}))
        return 2
    if args.segments_out:
        out = Path(args.segments_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record["segments"], ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "ok": True, "approval_id": record["approval_id"], "version": record["version"],
        "approved_at": record["approved_at"], "segment_count": len(record["segments"]),
        "flags": record["flags"], "segments_out": args.segments_out,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/approval_transaction/test_load_approval.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/gator-demo-recorder/scripts/load_approval.py tests/approval_transaction/test_load_approval.py
git commit -m "feat: verified approval loader for the demo recorder skill"
```

---

### Task 4: Server-side skill pin

**Files:**

- Create: `web/skill_pin.py`
- Modify: `web/routes/chat.py` (`ChatRequest`; skill-prompt block before `_active_sids = set()`; `_explicit_skill_ids`; four `req.scoped_skill` gates; the `scoped_skill` injection)
- Test: `tests/approval_transaction/test_pinning.py`

**Interfaces:**

- Consumes: `demo_projects.get_project(pid)` (SP3) for the Demo Recorder context provider; `shared.SKILL_PROMPTS` (dict keyed by skill id) in chat.py.
- Produces:
  - `Pin(skill: str, project_id: str | None)` frozen dataclass
  - `resolve_pin(pinned_skill, pinned_project_id, known_skills, slash_active=False) -> Pin | None`
  - `PIN_CONTEXT_PROVIDERS: dict[str, Callable[[str], str]]`
  - `pin_context_block(pin: Pin | None) -> str` (empty string when nothing applies; never raises)
  - `ChatRequest.pinned_skill`, `ChatRequest.pinned_project_id` (both `str | None = None`)
  - Inside `chat()`: `_pin`, `_skills_locked`, `_inject_skill`.

- [ ] **Step 1: Confirm the skill id and the anchors**

Run: `grep -rn "gator-demo-recorder" web/*.py web/routes/*.py | head; grep -n "scoped_skill\|_active_sids = set\|_explicit_skill_ids: set" web/routes/chat.py`
Expected: the registered skill id is `gator-demo-recorder`. If `shared.SKILL_PROMPTS` keys it differently, use that key wherever this plan says `gator-demo-recorder` (in `skill_pin.py`, tests, and app.js). Expected anchors: one `class ChatRequest`, one `_active_sids = set()`, four `req.scoped_skill` gates and one injection.

- [ ] **Step 2: Write the failing tests**

`tests/approval_transaction/test_pinning.py`:

```python
from pathlib import Path

import pytest

import narration_approval as na
import skill_pin as sp

CHAT_SRC = (Path(__file__).resolve().parents[2] / "web" / "routes" / "chat.py").read_text("utf-8")
KNOWN = {"gator-demo-recorder": "prompt", "jira": "prompt"}


def test_resolve_pin_accepts_known_skill_and_valid_id():
    pin = sp.resolve_pin("gator-demo-recorder", "demo_20261019_101500", KNOWN)
    assert pin == sp.Pin("gator-demo-recorder", "demo_20261019_101500")


def test_resolve_pin_drops_unknown_skill():
    assert sp.resolve_pin("not-a-skill", "demo_1", KNOWN) is None
    assert sp.resolve_pin(None, None, KNOWN) is None
    assert sp.resolve_pin(5, None, KNOWN) is None


@pytest.mark.parametrize("bad", ["../etc", "a/b", "a b", "x" * 81, "", "demo\n1"])
def test_resolve_pin_drops_bad_project_id_but_keeps_skill(bad):
    assert sp.resolve_pin("gator-demo-recorder", bad, KNOWN) == sp.Pin("gator-demo-recorder", None)


def test_resolve_pin_inactive_for_slash_commands():
    assert sp.resolve_pin("gator-demo-recorder", "demo_1", KNOWN, slash_active=True) is None


def test_context_block_for_demo_project(store):
    p = store.create_project()
    na.approve(p["project_id"], [{"text": "hello"}], {})
    block = sp.pin_context_block(sp.Pin("gator-demo-recorder", p["project_id"]))
    assert f"PINNED PROJECT: {p['name']} ({p['project_id']})" in block
    assert f"PROJECT_DIR: {p['path']}" in block
    assert "Current narration approval: appr_1_" in block
    assert "Do not look up the active project." in block


def test_context_block_empty_cases(store):
    assert sp.pin_context_block(None) == ""
    assert sp.pin_context_block(sp.Pin("gator-demo-recorder", None)) == ""
    assert sp.pin_context_block(sp.Pin("jira", "x")) == ""
    assert sp.pin_context_block(sp.Pin("gator-demo-recorder", "demo_19990101_000000")) == ""


def test_chat_request_has_pin_fields():
    from routes.chat import ChatRequest
    fields = getattr(ChatRequest, "model_fields", None) or ChatRequest.__fields__
    assert "pinned_skill" in fields and "pinned_project_id" in fields


def test_chat_source_wires_the_pin():
    assert "pinned_skill: str | None = None" in CHAT_SRC
    assert "pinned_project_id: str | None = None" in CHAT_SRC
    assert "_resolve_pin(req.pinned_skill, req.pinned_project_id" in CHAT_SRC
    assert "_skills_locked = bool(req.scoped_skill or _pin)" in CHAT_SRC
    assert "_pin_context_block(_pin)" in CHAT_SRC
    assert "_inject_skill = req.scoped_skill or (_pin.skill if _pin else None)" in CHAT_SRC


def test_chat_source_gates_use_skills_locked():
    assert "not req.scoped_skill" not in CHAT_SRC
    assert CHAT_SRC.count("_skills_locked") >= 5
    assert "if _skills_locked:\n        print(f\"[classifier] skipped" in CHAT_SRC
    assert "if not _classifier_inherited and not _skills_locked:" in CHAT_SRC
    assert "_image_analysis_requested = not _skills_locked and" in CHAT_SRC
    assert "    if not _skills_locked:\n        _inferred = _ensure_image_fetch_skill(" in CHAT_SRC
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/approval_transaction/test_pinning.py -v`
Expected: FAIL (`ModuleNotFoundError: skill_pin`).

- [ ] **Step 4: Create `web/skill_pin.py`**

```python
"""Per-tab skill pin: validate it and build the context block for the pinned skill."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


@dataclass(frozen=True)
class Pin:
    skill: str
    project_id: str | None = None


PIN_CONTEXT_PROVIDERS: dict[str, Callable[[str], str]] = {}


def resolve_pin(pinned_skill, pinned_project_id, known_skills, slash_active: bool = False) -> Pin | None:
    if slash_active or not isinstance(pinned_skill, str) or pinned_skill not in known_skills:
        return None
    valid = isinstance(pinned_project_id, str) and _PROJECT_ID.fullmatch(pinned_project_id)
    return Pin(pinned_skill, pinned_project_id if valid else None)


def pin_context_block(pin: Pin | None) -> str:
    if not pin or not pin.project_id:
        return ""
    provider = PIN_CONTEXT_PROVIDERS.get(pin.skill)
    if not provider:
        return ""
    try:
        text = provider(pin.project_id)
    except Exception:
        return ""
    return f"\n\n{text}" if text else ""


def _demo_recorder_context(project_id: str) -> str:
    import demo_projects as dp

    p = dp.get_project(project_id)
    lines = [
        f"PINNED PROJECT: {p['name']} ({p['project_id']})",
        f"PROJECT_DIR: {p['path']}",
        f"Stage: {p['stage']}",
    ]
    approval = (p.get("ext") or {}).get("approval") or {}
    if approval.get("current_id"):
        lines.append(f"Current narration approval: {approval['current_id']} (version {approval['version']}).")
    lines.append("Use this PROJECT_DIR for every path. Do not look up the active project.")
    return "\n".join(lines)


PIN_CONTEXT_PROVIDERS["gator-demo-recorder"] = _demo_recorder_context
```

- [ ] **Step 5: Edit `web/routes/chat.py`**

5a. With the other local imports near the top, add:

```python
from skill_pin import pin_context_block as _pin_context_block, resolve_pin as _resolve_pin
```

5b. In `ChatRequest`, directly after the `scoped_skill` line add:

```python
    pinned_skill: str | None = None           # per-tab skill pin (client); activates and locks skill selection
    pinned_project_id: str | None = None      # project the pinned skill is working on
```

5c. Immediately before `_active_sids = set()` insert:

```python
    _pin = _resolve_pin(req.pinned_skill, req.pinned_project_id, shared.SKILL_PROMPTS,
                        slash_active=bool(slash_cmd))
    _skills_locked = bool(req.scoped_skill or _pin)
```

5d. Directly after the `for _sid in (req.active_skills or []):` loop that fills `_active_sids` (before the "Include SKILL.md prompts for dependency skills" comment) insert:

```python
    if _pin:
        _active_sids.add(_pin.skill)
```

5e. After the `for _sid in sorted(_active_sids):` loop that calls `_append_skill_prompt` insert:

```python
    system += _pin_context_block(_pin)
```

5f. After the `for _sid in (req.active_skills or []): _explicit_skill_ids.add(_sid)` loop under `_explicit_skill_ids: set[str] = set()` insert:

```python
    if _pin:
        _explicit_skill_ids.add(_pin.skill)
```

5g. Replace the four gates:

| Before                                                                                       | After                                                                                                                                                                          |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `if req.scoped_skill:` followed by the `[classifier] skipped` print                          | `if _skills_locked:`; the print becomes `print(f"[classifier] skipped — skills locked (scoped_skill={req.scoped_skill!r}, pin={_pin.skill if _pin else None!r})", flush=True)` |
| `if not _classifier_inherited and not req.scoped_skill:`                                     | `if not _classifier_inherited and not _skills_locked:`                                                                                                                         |
| `_image_analysis_requested = not req.scoped_skill and _is_image_analysis_request(_msg_text)` | `_image_analysis_requested = not _skills_locked and _is_image_analysis_request(_msg_text)`                                                                                     |
| `if not req.scoped_skill:` (the one before `_inferred = _ensure_image_fetch_skill(`)         | `if not _skills_locked:`                                                                                                                                                       |

Update the comment above the classifier ("Skip entirely for scoped requests ... fully controlled by scoped_skill") to say `scoped_skill or a pinned skill`.

5h. Replace the injection block:

```python
    if req.scoped_skill and req.scoped_skill not in _all_active:
        _all_active.append(req.scoped_skill)
```

with:

```python
    _inject_skill = req.scoped_skill or (_pin.skill if _pin else None)
    if _inject_skill and _inject_skill not in _all_active:
        _all_active.append(_inject_skill)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/approval_transaction/test_pinning.py -v`
Expected: PASS.

- [ ] **Step 7: Run the existing chat and skill tests**

Run: `pytest tests -k "chat or skill" -q`
Expected: PASS (no behavior change when no pin is sent).

- [ ] **Step 8: Commit**

```bash
git add web/skill_pin.py web/routes/chat.py tests/approval_transaction/test_pinning.py
git commit -m "feat: server-side skill pin with project context"
```

---

### Task 5: Client pin state, chip, and send fields

**Files:**

- Modify: `web/static/app.js` (pin helpers placed directly above `function _restoreChipsForTab`; call sites in `_restoreChipsForTab`, `doSend`, tab close, and the `gator:send-message` bridge)
- Modify: `web/static/style.css` (new `.skill-pin-chip` rule directly after the `.chat-chip` rule)
- Test: `tests/skill_pin.test.js`

**Interfaces:**

- Consumes: server fields from Task 4 (`pinned_skill`, `pinned_project_id` on `/api/chat`); existing app.js globals `_activeTabId`, `_tabs`, `SKILL_MAP`, `finalText`, `requestTabId` (inside `doSend`).
- Produces (all in app.js, top level):
  - `const _DEMO_RECORDER_SKILL = 'gator-demo-recorder';`
  - Pure: `_pinFromMessage(d, text) -> {skill, projectId} | null`, `_mergePin(existing, incoming) -> pin | null`, `_pinForSend(pin, text) -> pin | null`
  - Tab state: `_tabPins` (Map), `_loadTabPin(tabId)`, `_getTabPin(tabId)`, `_setTabPin(tabId, pin | null)`, `_renderPinChip(tabId)`
  - A pin is `{ skill: string, projectId: string | null }`, stored in `localStorage['tab-pin-<tabId>']`.

- [ ] **Step 1: Write the failing test**

`tests/skill_pin.test.js`:

```js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const m = source.match(new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(m, `${name} not found in app.js`);
  return m[0];
}
const constLine = source.match(/const _DEMO_RECORDER_SKILL = '[^']+';/);
assert(constLine, '_DEMO_RECORDER_SKILL not found in app.js');

const names = ['_pinFromMessage', '_mergePin', '_pinForSend'];
const fns = vm.runInNewContext(
  `${constLine[0]}\n${names.map(extract).join('\n')}\n({ ${names.join(', ')} });`,
  {},
);
const plain = (v) => JSON.parse(JSON.stringify(v));
const DR = 'gator-demo-recorder';

// _pinFromMessage: explicit pin_skill wins
assert.deepStrictEqual(
  plain(fns._pinFromMessage({ pin_skill: DR, project_id: 'demo_20261019_101500' }, 'anything')),
  { skill: DR, projectId: 'demo_20261019_101500' },
);
// invalid project ids are dropped but the skill pin is kept
assert.deepStrictEqual(plain(fns._pinFromMessage({ pin_skill: DR, project_id: '../x' }, 'hi')), {
  skill: DR,
  projectId: null,
});
assert.deepStrictEqual(plain(fns._pinFromMessage({ pin_skill: DR }, 'hi')), {
  skill: DR,
  projectId: null,
});
// legacy prefix inference
for (const prefix of [
  'Recording complete. Output: x',
  'NARRATION_APPROVED:[{"text":"a"}]',
  'NARRATION_REEDIT:[{"text":"a"}]',
  'Please delete the frames/ and tts_work/ folders',
]) {
  assert.deepStrictEqual(
    plain(fns._pinFromMessage({ project_id: 'demo_1' }, prefix)),
    { skill: DR, projectId: 'demo_1' },
    prefix,
  );
}
// ordinary widget messages do not pin
assert.strictEqual(fns._pinFromMessage({}, 'Show my calendar'), null);
assert.strictEqual(fns._pinFromMessage(null, 'Show my calendar'), null);

// _mergePin
const existing = { skill: DR, projectId: 'demo_1' };
assert.deepStrictEqual(plain(fns._mergePin(existing, null)), existing);
assert.strictEqual(fns._mergePin(null, null), null);
assert.deepStrictEqual(plain(fns._mergePin(existing, { skill: DR, projectId: null })), existing);
assert.deepStrictEqual(plain(fns._mergePin(existing, { skill: DR, projectId: 'demo_2' })), {
  skill: DR,
  projectId: 'demo_2',
});
assert.deepStrictEqual(plain(fns._mergePin(existing, { skill: 'jira', projectId: null })), {
  skill: 'jira',
  projectId: null,
});

// _pinForSend: slash commands escape the pin
assert.strictEqual(fns._pinForSend(null, 'hello'), null);
assert.deepStrictEqual(plain(fns._pinForSend(existing, 'hello')), existing);
assert.strictEqual(fns._pinForSend(existing, '/jira list'), null);
assert.strictEqual(fns._pinForSend(existing, '  /jira list'), null);

// source wiring
assert(
  /localStorage\.removeItem\('tab-pin-' \+ tabId\)/.test(source),
  'tab close must drop the pin',
);
assert(/_tabPins\.delete\(tabId\)/.test(source), 'tab close must clear the pin map');
assert(
  /pinned_skill: _sendPin\.skill/.test(source) &&
    /pinned_project_id: _sendPin\.projectId/.test(source),
  'doSend must send the pin',
);
assert(
  (source.match(/\.\.\._sendPinFields/g) || []).length === 2,
  'pin fields must be in both the resend payload and the post body',
);

console.log('skill_pin: all assertions passed');
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/skill_pin.test.js`
Expected: FAIL with `_DEMO_RECORDER_SKILL not found in app.js`.

- [ ] **Step 3: Add the pure helpers and tab state to app.js**

Directly above `function _restoreChipsForTab(tabId) {` insert:

```js
const _DEMO_RECORDER_SKILL = 'gator-demo-recorder';
const _tabPins = new Map(); // tabId -> { skill, projectId } | null

function _pinFromMessage(d, text) {
  const cleanId = (v) => (typeof v === 'string' && /^[A-Za-z0-9_.-]{1,80}$/.test(v) ? v : null);
  if (d && typeof d.pin_skill === 'string' && d.pin_skill) {
    return { skill: d.pin_skill, projectId: cleanId(d.project_id) };
  }
  if (
    /^(Recording complete\.|NARRATION_APPROVED:|NARRATION_REEDIT:|Please delete the frames\/ and tts_work\/)/.test(
      text,
    )
  ) {
    return { skill: _DEMO_RECORDER_SKILL, projectId: cleanId(d && d.project_id) };
  }
  return null;
}

function _mergePin(existing, incoming) {
  if (!incoming) return existing || null;
  if (existing && existing.skill === incoming.skill && !incoming.projectId) {
    return { skill: incoming.skill, projectId: existing.projectId || null };
  }
  return { skill: incoming.skill, projectId: incoming.projectId || null };
}

function _pinForSend(pin, text) {
  if (!pin || !pin.skill) return null;
  if (String(text).trimStart().startsWith('/')) return null;
  return pin;
}

function _loadTabPin(tabId) {
  try {
    const v = JSON.parse(localStorage.getItem('tab-pin-' + tabId) || 'null');
    return v && typeof v.skill === 'string'
      ? { skill: v.skill, projectId: v.projectId || null }
      : null;
  } catch {
    return null;
  }
}

function _getTabPin(tabId) {
  if (!_tabPins.has(tabId)) _tabPins.set(tabId, _loadTabPin(tabId));
  return _tabPins.get(tabId);
}

function _setTabPin(tabId, pin) {
  if (!tabId) return;
  _tabPins.set(tabId, pin || null);
  try {
    if (pin) localStorage.setItem('tab-pin-' + tabId, JSON.stringify(pin));
    else localStorage.removeItem('tab-pin-' + tabId);
  } catch (e) {
    console.warn('tab pin not saved for tab', tabId, e);
  }
  if (tabId === _activeTabId) _renderPinChip(tabId);
}

function _renderPinChip(tabId) {
  const chipRow = document.getElementById('chat-chip-row');
  if (!chipRow) return;
  chipRow.querySelectorAll('.skill-pin-chip').forEach((el) => el.remove());
  const pin = _getTabPin(tabId);
  if (!pin) return;
  const label = SKILL_MAP[pin.skill]?.label || pin.skill;
  const chip = document.createElement('span');
  chip.className = 'skill-pin-chip';
  const text = document.createElement('span');
  text.textContent = `Pinned: ${label}`;
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'chip-remove';
  remove.setAttribute('aria-label', `Unpin ${label}`);
  remove.textContent = '✕';
  remove.addEventListener('click', (ev) => {
    ev.stopPropagation();
    _setTabPin(tabId, null);
  });
  chip.append(text, remove);
  chipRow.prepend(chip);
  chipRow.classList.remove('hidden');
}
```

- [ ] **Step 4: Render the chip when chips are restored**

At the end of `_restoreChipsForTab(tabId)`, after `_updatePlaceholder?.();` add:

```js
_renderPinChip(tabId);
```

- [ ] **Step 5: Clear pin state on tab close**

Directly after `localStorage.removeItem('tab-chips-' + tabId);` in the tab-close handler add:

```js
localStorage.removeItem('tab-pin-' + tabId);
_tabPins.delete(tabId);
```

- [ ] **Step 6: Wire `doSend`**

6a. In `doSend`, after `_ensureAddSkillBtn();` that follows the chip re-add block (the one directly before `_updatePlaceholder();`), add:

```js
_renderPinChip(_activeTabId || _tabs[0]?.id || 'default');
```

(`requestTabId` is not defined yet at that point, so the expression is repeated.)

6b. Directly after `const requestContextId = requestTabId || 'default';` add:

```js
const _sendPin = _pinForSend(_getTabPin(requestTabId), finalText);
const _sendPinFields = _sendPin
  ? {
      pinned_skill: _sendPin.skill,
      ...(_sendPin.projectId ? { pinned_project_id: _sendPin.projectId } : {}),
    }
  : {};
```

The source assertion in the test expects the literal text `pinned_skill: _sendPin.skill` and `pinned_project_id: _sendPin.projectId`; keep those exact spellings.

6c. In `_permissionResendPayload`, after `model: window._currentModel || '',` add `..._sendPinFields,`.

6d. In `_postBody` (the non-`overridePayload` object), after the `...(_wSuffix ? { system_prompt_suffix: _wSuffix } : {}),` line add `..._sendPinFields,`.

- [ ] **Step 7: Pin from other widget messages in the bridge**

In the `case 'gator:send-message'` block, directly before `const input = document.getElementById('chat-input');` that follows the NARRATION_APPROVED `if` block (the generic path), add:

```js
const _pin = _pinFromMessage(d, _text);
if (_pin) _setTabPin(_activeTabId, _mergePin(_getTabPin(_activeTabId), _pin));
```

- [ ] **Step 8: Add the CSS**

In `web/static/style.css`, directly after the `.chat-chip { ... }` rule add:

```css
.skill-pin-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.72rem;
  font-weight: 500;
  padding: 2px 6px 2px 8px;
  border-radius: 6px;
  border: 1px dashed rgba(74, 222, 128, 0.35);
  background: rgba(74, 222, 128, 0.06);
  color: var(--accent);
  white-space: nowrap;
  letter-spacing: 0.01em;
}
```

- [ ] **Step 9: Run the tests**

Run: `node tests/skill_pin.test.js && node tests/submit_gate.test.js`
Expected: both print "all assertions passed".

- [ ] **Step 10: Commit**

```bash
git add web/static/app.js web/static/style.css tests/skill_pin.test.js
git commit -m "feat: per-tab skill pin with chip and chat request fields"
```

---

### Task 6: Awaited approval handler in the widget bridge

**Files:**

- Modify: `web/static/app.js` (new functions directly above `window.addEventListener('message'`; replace the `NARRATION_APPROVED` block in the bridge)
- Test: `tests/narration_approval.test.js`

**Interfaces:**

- Consumes: Task 5's `_setTabPin`, `_DEMO_RECORDER_SKILL`; Task 2's `POST /api/demo-projects/{id}/narration` returning `{..., approval: {approval_id, segment_count, ...}}`; SP3's `GET /api/demo-projects/active` (404 when none; otherwise a project dict with `project_id`). The existing `window.fetch` wrapper adds `X-CSRF-Token` to same-origin mutating `/api` calls.
- Produces (app.js, top level):
  - Pure: `_parseNarrationApproval(text) -> {segments, flags, projectId}` (throws on a missing array, bad JSON, or an empty list; `PROJECT_ID` is removed from `flags`), `_approvalTrigger(approval, flags) -> string`
  - Async: `_handleNarrationApproved(text, source)`, `_activeDemoProjectId()`, `_errorDetail(res)`
  - Sync: `_replyApproval(source, payload)`, `_submitApprovalTurn(trigger)`
  - Widget reply message: `{type: 'gator:narration-approval-result', ok: true, approval}` or `{type: 'gator:narration-approval-result', ok: false, error}`.

- [ ] **Step 1: Write the failing test**

`tests/narration_approval.test.js`:

```js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const m = source.match(new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(m, `${name} not found in app.js`);
  return m[0];
}
const names = ['_parseNarrationApproval', '_approvalTrigger'];
const fns = vm.runInNewContext(`${names.map(extract).join('\n')}\n({ ${names.join(', ')} });`, {});
const plain = (v) => JSON.parse(JSON.stringify(v));

// parse: segments, flags, project id
let r = fns._parseNarrationApproval(
  'NARRATION_APPROVED:[{"text":"a"},{"text":"b"}] ADD_BACKGROUND_MUSIC:true PROJECT_ID:demo_20261019_101500',
);
assert.deepStrictEqual(plain(r), {
  segments: [{ text: 'a' }, { text: 'b' }],
  flags: { ADD_BACKGROUND_MUSIC: 'true' },
  projectId: 'demo_20261019_101500',
});
r = fns._parseNarrationApproval('NARRATION_APPROVED:[{"text":"a"}]');
assert.deepStrictEqual(plain(r), { segments: [{ text: 'a' }], flags: {}, projectId: null });

// brackets and flag-looking text inside a segment do not confuse the parser
r = fns._parseNarrationApproval(
  'NARRATION_APPROVED:[{"text":"use ] and PROJECT_ID:evil"}] PROJECT_ID:demo_1',
);
assert.strictEqual(r.segments[0].text, 'use ] and PROJECT_ID:evil');
assert.strictEqual(r.projectId, 'demo_1');

// parse failures
assert.throws(() => fns._parseNarrationApproval('NARRATION_APPROVED:no array here'));
assert.throws(() => fns._parseNarrationApproval('NARRATION_APPROVED:[]'));
assert.throws(() => fns._parseNarrationApproval('NARRATION_APPROVED:[{bad json}]'));

// trigger text carries the approval id
const approval = { approval_id: 'appr_2_0a1b2c3d', segment_count: 3 };
assert.strictEqual(
  fns._approvalTrigger(approval, {}),
  'Narration approved (3 segments, approval appr_2_0a1b2c3d). Please generate TTS and merge.',
);
assert.strictEqual(
  fns._approvalTrigger({ approval_id: 'appr_1_ffffffff', segment_count: 1 }, {}),
  'Narration approved (1 segment, approval appr_1_ffffffff). Please generate TTS and merge.',
);
assert.strictEqual(
  fns._approvalTrigger(approval, { ADD_BACKGROUND_MUSIC: 'true' }),
  'Narration approved (3 segments, approval appr_2_0a1b2c3d) with background music requested. Please generate TTS, add background music, and merge.',
);

// bridge source structure
const bridgeStart = source.indexOf("case 'gator:send-message'");
assert(bridgeStart > -1, 'bridge not found');
const bridge = source.slice(bridgeStart, bridgeStart + 3000);
assert(/_handleNarrationApproved\(_text, e\.source\)/.test(bridge), 'bridge must call the handler');
assert(
  !source.includes('/api/recorder/narration-approved'),
  'frontend must not call the legacy route',
);
assert(
  !/sessionStorage\.setItem\('gator_narration/.test(source),
  'no sessionStorage fallback writes',
);

const handlerMatch = source.match(
  /async function _handleNarrationApproved\([^)]*\)\s*\{[\s\S]*?\n\}/,
);
assert(handlerMatch, '_handleNarrationApproved not found');
const handler = handlerMatch[0];
assert(
  /await fetch\('\/api\/demo-projects\/' \+ encodeURIComponent\(projectId\) \+ '\/narration'/.test(
    handler,
  ),
);
assert(/if \(!res\.ok\)/.test(handler), 'handler must check res.ok');
assert(!/\.catch\(\(\) => \{\}\)/.test(handler), 'handler must not swallow errors');
const okIdx = handler.indexOf('if (!res.ok)');
const submitIdx = handler.indexOf('_submitApprovalTurn(');
assert(
  okIdx > -1 && submitIdx > okIdx,
  'chat turn is submitted only after the response is checked',
);
assert(
  /_replyApproval\(source, \{ ok: false/.test(handler),
  'failure must be reported to the widget',
);

console.log('narration_approval: all assertions passed');
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/narration_approval.test.js`
Expected: FAIL with `_parseNarrationApproval not found in app.js`.

- [ ] **Step 3: Add the functions above the bridge**

Directly above the `/* ── postMessage bridge — iframe widgets → Gator agent ──` comment insert:

```js
function _parseNarrationApproval(text) {
  const raw = String(text).slice('NARRATION_APPROVED:'.length).trim();
  const start = raw.indexOf('[');
  const end = raw.lastIndexOf(']');
  if (start === -1 || end === -1) throw new Error('no JSON array');
  const segments = JSON.parse(raw.slice(start, end + 1));
  if (!Array.isArray(segments) || !segments.length) throw new Error('no segments');
  const flags = {};
  for (const part of raw
    .slice(end + 1)
    .trim()
    .split(/\s+/)) {
    const m = part.match(/^([A-Z_]+):(.+)$/);
    if (m) flags[m[1]] = m[2];
  }
  const projectId = flags.PROJECT_ID || null;
  delete flags.PROJECT_ID;
  return { segments, flags, projectId };
}

function _approvalTrigger(approval, flags) {
  const n = approval.segment_count;
  const head = `Narration approved (${n} segment${n !== 1 ? 's' : ''}, approval ${approval.approval_id})`;
  if (flags.ADD_BACKGROUND_MUSIC === 'true') {
    return `${head} with background music requested. Please generate TTS, add background music, and merge.`;
  }
  return `${head}. Please generate TTS and merge.`;
}

async function _activeDemoProjectId() {
  const res = await fetch('/api/demo-projects/active');
  if (!res.ok) return null;
  const data = await res.json();
  return data.project_id || null;
}

async function _errorDetail(res) {
  try {
    const body = await res.json();
    const detail = body.detail ?? body.error;
    if (typeof detail === 'string') return detail;
    if (detail) return JSON.stringify(detail);
  } catch (_) {}
  return `Approval failed (HTTP ${res.status})`;
}

function _replyApproval(source, payload) {
  try {
    source?.postMessage({ type: 'gator:narration-approval-result', ...payload }, '*');
  } catch (_) {}
}

function _submitApprovalTurn(trigger) {
  const input = document.getElementById('chat-input');
  if (!input) return;
  input.textContent = trigger;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  document
    .getElementById('chat-form')
    ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
}

async function _handleNarrationApproved(text, source) {
  const tabId = _activeTabId;
  let parsed;
  try {
    parsed = _parseNarrationApproval(text);
  } catch (err) {
    _replyApproval(source, { ok: false, error: 'Could not read the narration: ' + err.message });
    return;
  }
  try {
    const projectId = parsed.projectId || (await _activeDemoProjectId());
    if (!projectId)
      throw new Error('No demo project is active. Record again or reopen the project.');
    const res = await fetch('/api/demo-projects/' + encodeURIComponent(projectId) + '/narration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments: parsed.segments, flags: parsed.flags }),
    });
    if (!res.ok) throw new Error(await _errorDetail(res));
    const approval = (await res.json()).approval;
    if (!approval || !approval.approval_id)
      throw new Error('The server did not confirm the approval.');
    if (_activeTabId !== tabId) {
      throw new Error(
        'You switched tabs. Return to the original tab and approve again; nothing is lost.',
      );
    }
    _setTabPin(tabId, { skill: _DEMO_RECORDER_SKILL, projectId });
    _replyApproval(source, { ok: true, approval });
    _submitApprovalTurn(_approvalTrigger(approval, parsed.flags));
  } catch (err) {
    _replyApproval(source, { ok: false, error: String((err && err.message) || err) });
  }
}
```

- [ ] **Step 4: Replace the bridge block**

In `case 'gator:send-message'`, replace the entire `if (_text.startsWith('NARRATION_APPROVED:')) { ... return; }` block and the comment above it (from `// Intercept NARRATION_APPROVED` through that block's closing `return;\n      }`) with:

```js
// Narration approval is a transaction: the handler awaits the server commit
// and submits the chat turn only after it succeeds.
if (_text.startsWith('NARRATION_APPROVED:')) {
  _handleNarrationApproved(_text, e.source);
  return;
}
```

- [ ] **Step 5: Run the tests**

Run: `node tests/narration_approval.test.js && node tests/skill_pin.test.js && node tests/submit_gate.test.js`
Expected: all print "all assertions passed".

- [ ] **Step 6: Commit**

```bash
git add web/static/app.js tests/narration_approval.test.js
git commit -m "feat: await narration approval before submitting the chat turn"
```

---

### Task 7: Skill file edits and contract test

**Files:**

- Modify: `web/skills/gator-demo-recorder/SKILL.md`
- Test: `tests/approval_transaction/test_skill_contract.py`

**Interfaces:**

- Consumes: widget bridge from Tasks 5-6 (`pin_skill`, `project_id` message fields; `gator:narration-approval-result` reply); `load_approval.py` CLI from Task 3; SP3's "Project folder" section that defines `PROJECT_DIR` in SKILL.md.
- Produces: SKILL.md that (a) pins every widget message, (b) fills `PROJECT_ID_PLACEHOLDER`, (c) awaits the approval result in the widget, (d) loads narration through `load_approval.py` in Phase 4. It must keep SP3's contract test green: no `narration_pending.json`, and still contains `work/narration.json`, `final/`, `PROJECT_DIR`, `demo_projects.json`.

Anchors below are post-SP3 text. Find each with `grep -n` rather than trusting line numbers.

- [ ] **Step 1: Write the failing contract test**

`tests/approval_transaction/test_skill_contract.py`:

```python
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder"
TEXT = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def test_every_widget_message_pins_the_skill():
    sends = [m.start() for m in re.finditer(r"type:'gator:send-message'", TEXT)]
    assert len(sends) >= 4
    for start in sends:
        assert "pin_skill:'gator-demo-recorder'" in TEXT[start:start + 260], TEXT[start:start + 120]


def test_recording_complete_carries_project_id():
    i = TEXT.index("'Recording complete. File: '")
    assert "project_id:(data&&data.project_id)||''" in TEXT[i:i + 600]


def test_widget_approve_is_a_guarded_transaction():
    assert "PROJECT_ID_PLACEHOLDER" in TEXT
    assert 'id="btn-approve"' in TEXT
    assert "_approving" in TEXT
    assert "gator:narration-approval-result" in TEXT
    assert "/^demo_\\d/" in TEXT
    assert "' PROJECT_ID:'" in TEXT


def test_phase4_uses_the_verified_loader():
    assert "load_approval.py" in TEXT
    assert "approval (appr_\\d+_[0-9a-f]{8})" in TEXT
    for code in ("missing", "superseded", "corrupt", "stale_media"):
        assert f"`{code}`" in TEXT


def test_no_pending_file_singleton_remains():
    assert "narration_pending.json" not in TEXT
    for script in (SKILL_DIR / "scripts").glob("*.py"):
        assert "narration_pending.json" not in script.read_text(encoding="utf-8"), script.name


def test_sp3_contract_strings_survive():
    for needle in ("demo_projects.json", "PROJECT_DIR", "work/narration.json", "final/"):
        assert needle in TEXT, needle
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/approval_transaction/test_skill_contract.py -v`
Expected: FAIL on the pin, placeholder and loader tests.

- [ ] **Step 3: Pin every widget message**

3a. Recording complete. Replace

```js
try {
  parent.postMessage({ type: 'gator:send-message', text: msg }, '*');
} catch (e) {}
```

with

```js
try {
  parent.postMessage(
    {
      type: 'gator:send-message',
      pin_skill: 'gator-demo-recorder',
      project_id: (data && data.project_id) || '',
      text: msg,
    },
    '*',
  );
} catch (e) {}
```

3b. Re-edit and cleanup in the Phase 5 widget. Replace the two calls so they read:

```js
function editNarration() {
  parent.postMessage(
    {
      type: 'gator:send-message',
      pin_skill: 'gator-demo-recorder',
      project_id: _PROJECT_ID,
      text: 'NARRATION_REEDIT: Re-show the Phase 3 narration editor widget now.',
    },
    '*',
  );
}
function cleanup() {
  parent.postMessage(
    {
      type: 'gator:send-message',
      pin_skill: 'gator-demo-recorder',
      project_id: _PROJECT_ID,
      text: 'Please delete the frames/ and tts_work/ intermediates for the current session.',
    },
    '*',
  );
}
```

and in the Phase 5 widget's script, next to its other top-level `var`s, add `var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER';` (the Phase 5 widget instructions get the same placeholder rule as Phase 3, Step 4). If `cleanup()` keeps SP3's wording, keep SP3's text and only add the two fields.

- [ ] **Step 4: Phase 3 widget, placeholder rules**

4a. In the global rules, in the bullet that says "only replacing `SEGMENTS_PLACEHOLDER`" (the "Use the EXACT Phase 3 widget template" rule) and in the Phase 3 paragraph "The only modification allowed is replacing `SEGMENTS_PLACEHOLDER` with the narration JSON array.", change the allowed modification to "replacing `SEGMENTS_PLACEHOLDER` with the narration JSON array and `PROJECT_ID_PLACEHOLDER` with the project id (`PROJECT_DIR.name`)".

4b. Under the "Replace:" list in Phase 3 add:

```markdown
- `PROJECT_ID_PLACEHOLDER` with the project id, which is `PROJECT_DIR.name` (for example `demo_20261019_101500`). The widget sends it with the approval so the approval lands on the project being edited, not whichever project is active.
```

4c. Change the Approve button markup from `<button class="btn-approve" onclick="approve()">` to `<button class="btn-approve" id="btn-approve" onclick="approve()">`.

4d. Add the project id variable next to `var data = SEGMENTS_PLACEHOLDER;`:

```js
var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER';
var _approving = false;
```

4e. Replace the whole `approve()` function with:

```js
function approve() {
  if (_approving) return;
  var voice = getVoice();
  var speed = getSpeed();
  var out = data.map(function (s, i) {
    return {
      start_at: s.start_at || s.start || 0,
      text: document.getElementById('s' + i).value,
      voice: voice,
      speed: speed,
    };
  });
  var pid = /^demo_\d/.test(_PROJECT_ID) ? _PROJECT_ID : '';
  _approving = true;
  document.getElementById('btn-approve').disabled = true;
  setStatus('Approving...', '#f97316');
  parent.postMessage(
    {
      type: 'gator:send-message',
      pin_skill: 'gator-demo-recorder',
      project_id: _PROJECT_ID,
      text: 'NARRATION_APPROVED:' + JSON.stringify(out) + (pid ? ' PROJECT_ID:' + pid : ''),
    },
    '*',
  );
}
window.addEventListener('message', function (ev) {
  var m = ev.data;
  if (ev.source !== parent || !m || m.type !== 'gator:narration-approval-result') return;
  _approving = false;
  document.getElementById('btn-approve').disabled = false;
  if (m.ok) setStatus('✓ Approved (' + m.approval.segment_count + ' segments)', '#4ade80');
  else setStatus('Approval failed: ' + m.error, '#f87171');
});
```

- [ ] **Step 5: Phase 4, load the approval through the verified loader**

5a. Replace the Phase 4 intro line `When you receive "Narration approved (N segments)..."` so it reads:

```markdown
When you receive `"Narration approved (N segments, approval appr_<n>_<hash>). ..."`:
```

5b. Replace step 1 (the step that reads the approved segments from the pending file or from `work/narration.json`) with:

```markdown
1. Load the approval with the verified loader. The approval record under `PROJECT_DIR/work/approvals/` is the source of truth; `work/narration.json` is its mirror. Take the approval id from the trigger text (`approval appr_<n>_<hash>`) and run `load_approval.py`, which re-checks the record's hash and that the recording has not changed since the user approved. Do not read narration from any other file and do not parse segments out of the trigger message.
```

5c. Replace the code block's opening lines (everything from the `video_path =` assignment down to and including the `narration_file.write_text(json.dumps(segments))` line; keep the `timeline_file`, `output_path` and later lines as SP3 left them) with the following, and move the `_skill_dirs` / `skill_dir` lookup above it because `load_approval.py` sits next to `tts_pipeline.py`:

```python
import subprocess, sys, json, re
from pathlib import Path

video_path = r"<path from 'Recording complete' message>"
trigger = r"<the 'Narration approved ...' message text>"

# Locate the skill scripts — check both built-in and user-installed locations
_skill_dirs = [
    Path.home() / ".gator/skills/mine/gator-demo-recorder/scripts",
    Path(__file__).parent / "scripts" if "__file__" in dir() else None,
    Path.cwd() / "web/skills/gator-demo-recorder/scripts",
]
skill_dir = next((d for d in _skill_dirs if d and d.exists()), _skill_dirs[0])

m = re.search(r"approval (appr_\d+_[0-9a-f]{8})", trigger)
narration_file = PROJECT_DIR / "work" / "tts" / "segments.json"
cmd = [sys.executable, str(skill_dir / "load_approval.py"),
       "--project-dir", str(PROJECT_DIR), "--segments-out", str(narration_file)]
if m:
    cmd += ["--approval-id", m.group(1)]
check = subprocess.run(cmd, capture_output=True, text=True, timeout=60, shell=False)
verdict = json.loads(check.stdout or '{"ok": false, "code": "missing", "error": "loader printed nothing"}')
print(verdict)
if not verdict["ok"]:
    raise SystemExit("approval check failed: " + verdict["code"])
flags = verdict["flags"]
segments = json.loads(narration_file.read_text(encoding="utf-8"))
```

Then the existing `voice = ...` / `speed = ...` lines and the `subprocess.run([... "--narration", str(narration_file) ...])` call continue unchanged (they already pass `narration_file`).

5d. Directly after the code block add the failure table:

```markdown
If `load_approval.py` reports `"ok": false`, do NOT generate audio. Act on `code`:

| code          | Meaning                                                        | What to do                                                                                                     |
| ------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `missing`     | No approval is recorded for this project                       | Tell the user to click Approve in the narration widget.                                                        |
| `superseded`  | A newer approval replaced the one in the trigger               | Tell the user a newer approval exists and ask them to approve again from the current widget.                   |
| `corrupt`     | The approval record is unreadable or fails its integrity check | Re-show the Phase 3 widget so the user approves again.                                                         |
| `stale_media` | The recording changed after the user approved                  | Re-draft the narration against the current recording, re-show the Phase 3 widget, and wait for a new approval. |
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/approval_transaction tests/demo_project_state -q`
Expected: PASS, including SP3's `test_skill_no_singletons.py` (no `narration_pending.json`, still has `work/narration.json` and `final/`).

- [ ] **Step 7: Commit**

```bash
git add web/skills/gator-demo-recorder/SKILL.md tests/approval_transaction/test_skill_contract.py
git commit -m "feat: demo recorder skill approves through the transaction and loads it verified"
```

---

### Task 8: Final verification

**Files:** none modified (fix forward in the owning task's files if anything fails).

- [ ] **Step 1: Python suites**

Run: `pytest tests/approval_transaction tests/demo_project_state tests/test_csrf_route_inventory.py -q`
Expected: PASS. `tests/csrf_route_baseline.txt` is unchanged (`git diff --stat tests/csrf_route_baseline.txt` prints nothing).

- [ ] **Step 2: Full suite**

Run: `pytest tests -q`
Expected: PASS.

- [ ] **Step 3: JS suites**

Run: `for f in tests/*.test.js; do node "$f" || exit 1; done`
Expected: every file prints its "all assertions passed" line.

- [ ] **Step 4: Commit hygiene**

Run: `git log -8 --format=%B | grep -c "Co-Authored-By"`
Expected: `0`.

- [ ] **Step 5: Manual smoke test in the running app**

Start the app, open it in a browser, and use a project that has a `source/recording.mp4`.

1. Open the Demo Recorder widget, finish a recording, and ask Gator to draft a narration. Expected: the chat tab shows a "Pinned: Demo Recorder ×" chip.
2. Click Approve. Expected: the button disables and shows "Approving...", then "✓ Approved (N segments)"; the chat turn "Narration approved (N segments, approval appr_1_xxxxxxxx). Please generate TTS and merge." is submitted; the agent runs `load_approval.py` (visible in the tool call) and produces `final/<name>.mp4`.
3. Edit one sentence in the widget and Approve again. Expected: approval `appr_2_...`; `work/approvals/` holds both records.
4. Click Approve a second time without editing. Expected: the same approval id (reused) and a fresh chat turn.
5. Failure path: in the browser console run `window.postMessage({type:'gator:send-message', text:'NARRATION_APPROVED:[{"text":"x"}] PROJECT_ID:demo_19990101_000000'}, '*')`. Expected: no chat turn is submitted, and (from a widget) the status shows the 404 text.
6. Send `/jira list` in the pinned tab. Expected: Jira activates, the Demo Recorder prompt does not.
7. Click the chip's ✕, then send "hello". Expected: no `pinned_skill` in the `/api/chat` request (DevTools Network); reload the page and the chip stays gone.
8. Reload with a pin set. Expected: the chip reappears for that tab only; a second tab has no chip.

- [ ] **Step 6: Report**

Report the commands run and their results. Do not push; the integration branch is pushed by the coordinator.

---
