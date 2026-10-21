# Durable Demo Project State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Demo Recorder demo a durable project (ID, `project.json`, fixed folder layout, configurable root, recent index) and replace the `latest-output` singleton with a project-keyed API.

**Architecture:** A FastAPI-free store module `web/demo_projects.py` owns layout, `project.json`, the recent index and root config. A thin router `web/routes/demo_projects.py` exposes it (CSRF on every mutating route). `web/routes/recorder.py` creates/continues a project on start and records it on stop; legacy singleton routes become shims. The agent never calls mutating routes: it reads `~/.gator/demo_projects.json` and writes files into the project folder.

**Tech Stack:** Python 3 / FastAPI / pydantic, pytest (asyncio_mode=auto, `--import-mode=importlib`, `pythonpath = web .`), Electron IPC, vanilla JS, node `assert` tests.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-19-demo-project-state-design.md`.
- Project ID shape `demo_YYYYMMDD_HHMMSS`, `_2`, `_3` appended on collision. Default root `~/Downloads/gator_demos/`.
- Layout: `project.json`, `final/`, `previous/`, `source/`, `work/{normalized,frames,tts,logs}`.
- `project.json` stores paths relative to the project folder; `final` is never stored (derived from `final/`).
- Config key for the global default root: `demo_projects_root`.
- Every new POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]` from `web/security.py`. Do not add routes to `tests/csrf_route_baseline.txt`.
- Fake credential in tests and docs: `aigator-fake-api-key` only.
- No `Co-Authored-By` lines in commits. The product is "AI Gator", never "POC".
- Tests must not touch the real `~/.gator` or `~/Downloads`; use the `store` fixture from Task 1.
- Run Python tests from the repo root: `python -m pytest <path> -v`.

## File Structure

| File                                                            | Responsibility                                                              |
| --------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `web/demo_projects.py` (new)                                    | Layout, `project.json`, index, active project, root config, legacy adoption |
| `web/routes/demo_projects.py` (new)                             | `/api/demo-projects/*` routes                                               |
| `web/app.py` (modify, near line 100 and 915)                    | import and include the router                                               |
| `web/routes/recorder.py` (modify)                               | project-aware start/stop/status, shims, serve-file                          |
| `shell/main.js`, `shell/preload.js` (modify)                    | `demo:pick-folder` IPC                                                      |
| `web/static/app.js`, `web/static/index.html` (modify)           | `gator:pick-demo-folder` bridge case, Settings → General row                |
| `web/skills/gator-demo-recorder/SKILL.md`, `scripts/*` (modify) | agent uses project folder                                                   |
| `tests/demo_project_state/` (new)                               | store and route tests                                                       |
| `tests/demo_project_bridge.test.js` (new)                       | bridge case test                                                            |

---

### Task 1: Store core — layout, project.json, index, active

**Files:**

- Create: `web/demo_projects.py`
- Create: `tests/demo_project_state/__init__.py` (empty)
- Create: `tests/demo_project_state/conftest.py`
- Test: `tests/demo_project_state/test_store.py`

**Interfaces:**

- Produces (all in `demo_projects`): `DEFAULT_ROOT: Path`, `INDEX_PATH: Path`, `atomic_write_json(path: Path, data: dict) -> None`, `create_project(name: str | None = None, root: Path | None = None) -> dict`, `get_project(project_id: str) -> dict`, `project_path(project_id: str) -> Path`, `update_project(project_id: str, **fields) -> dict`, `set_ext(project_id: str, namespace: str, value: dict) -> dict`, `get_active_id() -> str | None`, `set_active(project_id: str) -> None`, `resolve_file(project_id: str, rel: str) -> Path`, `archive_final(project_id: str) -> list[Path]`, `begin_session(project_id: str | None = None) -> dict`, `save_narration(project_id: str, segments: list, flags: dict) -> dict`.
- `get_project` returns the `project.json` fields plus `path`, `final_dir`, `final` (abs path of newest file in `final/` or `None`), `raw` (abs or `None`), `segments` (abs). `stage` reads `delivered` when `final` exists and stored stage is `recorded` or `narration_approved`.
- Consumes: `config.GATOR_DIR`, `config.load_config`, `config.save_config`.

- [ ] **Step 1: Write the fixture and failing tests**

`tests/demo_project_state/conftest.py`:

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
```

`tests/demo_project_state/test_store.py`:

```python
import json
import re

import pytest


def test_create_builds_layout_and_project_json(store, tmp_path):
    p = store.create_project()
    assert re.fullmatch(r"demo_\d{8}_\d{6}", p["project_id"])
    folder = tmp_path / "demos" / p["project_id"]
    for sub in ("final", "previous", "source", "work/normalized", "work/frames", "work/tts", "work/logs"):
        assert (folder / sub).is_dir(), sub
    data = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["stage"] == "created"
    assert data["segments"] == [] and data["raw"] is None and data["ext"] == {}
    assert store.get_active_id() == p["project_id"]


def test_create_collision_gets_suffix(store, monkeypatch):
    class _Fixed:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime(2026, 10, 19, 14, 30, 12)
    monkeypatch.setattr(store, "datetime", _Fixed)
    a = store.create_project()
    b = store.create_project()
    assert a["project_id"] == "demo_20261019_143012"
    assert b["project_id"] == "demo_20261019_143012_2"


def test_create_with_custom_root_is_found_via_index(store, tmp_path):
    root = tmp_path / "elsewhere"
    p = store.create_project(root=root)
    assert store.project_path(p["project_id"]) == root / p["project_id"]


def test_atomic_write_leaves_no_temp_files(store, tmp_path):
    target = tmp_path / "x" / "a.json"
    store.atomic_write_json(target, {"a": 1})
    store.atomic_write_json(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    assert [f.name for f in target.parent.iterdir()] == ["a.json"]


def test_update_stores_relative_paths_and_get_expands(store):
    p = store.create_project()
    pid = p["project_id"]
    folder = store.project_path(pid)
    (folder / "source" / "seg_00.mp4").write_bytes(b"x")
    store.update_project(pid, segments=[folder / "source" / "seg_00.mp4"],
                         raw=folder / "source" / "seg_00.mp4", stage="recorded")
    on_disk = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    assert on_disk["segments"] == ["source/seg_00.mp4"]
    assert on_disk["raw"] == "source/seg_00.mp4"
    got = store.get_project(pid)
    assert got["segments"] == [str(folder / "source" / "seg_00.mp4")]
    assert got["raw"] == str(folder / "source" / "seg_00.mp4")
    assert got["final"] is None and got["stage"] == "recorded"


def test_update_rejects_unknown_field_and_bad_stage(store):
    pid = store.create_project()["project_id"]
    with pytest.raises(ValueError):
        store.update_project(pid, bogus=1)
    with pytest.raises(ValueError):
        store.update_project(pid, stage="nope")


def test_update_rejects_path_outside_project(store, tmp_path):
    pid = store.create_project()["project_id"]
    with pytest.raises(ValueError):
        store.update_project(pid, raw=tmp_path / "elsewhere.mp4")


def test_final_is_derived_from_disk_and_marks_delivered(store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    store.update_project(pid, stage="recorded")
    (folder / "final" / "demo.mp4").write_bytes(b"x")
    got = store.get_project(pid)
    assert got["final"] == str(folder / "final" / "demo.mp4")
    assert got["stage"] == "delivered"
    assert got["final_dir"] == str(folder / "final")


def test_archive_final_moves_files_to_previous(store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    (folder / "final" / "demo.mp4").write_bytes(b"x")
    moved = store.archive_final(pid)
    assert len(moved) == 1 and moved[0].parent == folder / "previous"
    assert moved[0].name.endswith("_demo.mp4")
    assert list((folder / "final").iterdir()) == []


def test_set_ext_namespaces(store):
    pid = store.create_project()["project_id"]
    store.set_ext(pid, "approval", {"ok": True})
    store.set_ext(pid, "media", {"n": 2})
    assert store.get_project(pid)["ext"] == {"approval": {"ok": True}, "media": {"n": 2}}


def test_resolve_file_blocks_traversal(store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    assert store.resolve_file(pid, "source/seg_00.mp4") == (folder / "source" / "seg_00.mp4").resolve()
    for bad in ("../x.mp4", "source/../../x.mp4", "/etc/passwd"):
        with pytest.raises(ValueError):
            store.resolve_file(pid, bad)


def test_set_active_unknown_project_raises(store):
    with pytest.raises(KeyError):
        store.set_active("demo_19990101_000000")


def test_index_trims_to_50_and_drops_missing_folders(store):
    ids = []
    for i in range(52):
        ids.append(store._register_for_test(f"demo_20260101_{i:06d}"))
    idx = json.loads(store.INDEX_PATH.read_text(encoding="utf-8"))
    assert len(idx["projects"]) == 50


def test_begin_session_creates_then_reuses(store):
    a = store.begin_session()
    assert store.get_active_id() == a["project_id"]
    other = store.create_project()
    again = store.begin_session(a["project_id"])
    assert again["project_id"] == a["project_id"]
    assert store.get_active_id() == a["project_id"]
    assert other["project_id"] != a["project_id"]


def test_save_narration_writes_file_and_stage(store):
    pid = store.create_project()["project_id"]
    out = store.save_narration(pid, [{"text": "hi"}], {"music": True})
    folder = store.project_path(pid)
    data = json.loads((folder / "work" / "narration.json").read_text(encoding="utf-8"))
    assert data["segments"] == [{"text": "hi"}] and data["flags"] == {"music": True}
    assert out["stage"] == "narration_approved"
    assert out["narration"]["approved_at"]
```

The `_register_for_test` helper used in the index-trim test is defined in Step 3 (index entry for an existing folder with a `project.json`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/demo_project_state/test_store.py -v`
Expected: collection FAIL, `ModuleNotFoundError: No module named 'demo_projects'`.

- [ ] **Step 3: Write the store module**

`web/demo_projects.py`:

```python
"""Durable Demo project state: layout, project.json, recent index, active project.

FastAPI-free so recorder.py and the routes can both import it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import GATOR_DIR, load_config, save_config

SCHEMA_VERSION = 1
MAX_RECENT = 50
DEFAULT_ROOT = Path.home() / "Downloads" / "gator_demos"
INDEX_PATH = GATOR_DIR / "demo_projects.json"
CONFIG_ROOT_KEY = "demo_projects_root"
SUBDIRS = ("final", "previous", "source", "work/normalized", "work/frames", "work/tts", "work/logs")
STAGES = ("created", "recording", "recorded", "narration_approved", "delivered")
_UPDATABLE = {"name", "stage", "segments", "raw", "narration"}
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── index ─────────────────────────────────────────────────────────────────────

def _read_index() -> dict:
    try:
        idx = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(idx, dict) and isinstance(idx.get("projects"), list):
            return idx
    except (OSError, ValueError):
        pass
    return {"schema_version": SCHEMA_VERSION, "active_project_id": None, "projects": []}


def _write_index(idx: dict) -> None:
    idx["projects"] = idx["projects"][:MAX_RECENT]
    atomic_write_json(INDEX_PATH, idx)


def _upsert_index(project_id: str, name: str, folder: Path, updated_at: str) -> None:
    with _LOCK:
        idx = _read_index()
        idx["projects"] = [p for p in idx["projects"] if p["project_id"] != project_id]
        idx["projects"].insert(0, {
            "project_id": project_id, "name": name, "path": str(folder), "updated_at": updated_at,
        })
        _write_index(idx)


def _register_for_test(project_id: str) -> str:
    folder = DEFAULT_ROOT / project_id
    _make_layout(folder)
    now = _now()
    atomic_write_json(folder / "project.json", _blank(project_id, project_id, now))
    _upsert_index(project_id, project_id, folder, now)
    return project_id


def project_path(project_id: str) -> Path:
    for entry in _read_index()["projects"]:
        if entry["project_id"] == project_id:
            return Path(entry["path"])
    raise KeyError(project_id)


def get_active_id() -> str | None:
    return _read_index().get("active_project_id")


def set_active(project_id: str) -> None:
    with _LOCK:
        project_path(project_id)
        idx = _read_index()
        idx["active_project_id"] = project_id
        _write_index(idx)


# ── project.json ──────────────────────────────────────────────────────────────

def _make_layout(folder: Path) -> None:
    for sub in SUBDIRS:
        (folder / sub).mkdir(parents=True, exist_ok=True)


def _blank(project_id: str, name: str, now: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "project_id": project_id, "name": name,
        "created_at": now, "updated_at": now, "stage": "created",
        "segments": [], "raw": None, "narration": None, "ext": {},
    }


def _read_project(folder: Path) -> dict:
    return json.loads((folder / "project.json").read_text(encoding="utf-8"))


def _rel(folder: Path, value) -> str:
    p = Path(value)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(folder.resolve()).as_posix()
        except ValueError:
            raise ValueError(f"path is outside the project folder: {value}") from None
    return p.as_posix()


def _expand(folder: Path, data: dict) -> dict:
    final_dir = folder / "final"
    finals = sorted((f for f in final_dir.glob("*") if f.is_file()), key=lambda f: f.stat().st_mtime) \
        if final_dir.is_dir() else []
    out = dict(data)
    out.update(
        path=str(folder), final_dir=str(final_dir),
        final=str(finals[-1]) if finals else None,
        raw=str(folder / data["raw"]) if data.get("raw") else None,
        segments=[str(folder / s) for s in data.get("segments", [])],
    )
    if finals and data.get("stage") in ("recorded", "narration_approved"):
        out["stage"] = "delivered"
    return out


def get_project(project_id: str) -> dict:
    folder = project_path(project_id)
    return _expand(folder, _read_project(folder))


def _write_project(folder: Path, data: dict) -> dict:
    data["updated_at"] = _now()
    atomic_write_json(folder / "project.json", data)
    _upsert_index(data["project_id"], data["name"], folder, data["updated_at"])
    return _expand(folder, data)


def update_project(project_id: str, **fields) -> dict:
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"unknown project fields: {sorted(unknown)}")
    if "stage" in fields and fields["stage"] not in STAGES:
        raise ValueError(f"invalid stage: {fields['stage']}")
    with _LOCK:
        folder = project_path(project_id)
        data = _read_project(folder)
        if "segments" in fields:
            fields["segments"] = [_rel(folder, s) for s in fields["segments"]]
        if fields.get("raw") is not None:
            fields["raw"] = _rel(folder, fields["raw"])
        data.update(fields)
        return _write_project(folder, data)


def set_ext(project_id: str, namespace: str, value: dict) -> dict:
    with _LOCK:
        folder = project_path(project_id)
        data = _read_project(folder)
        data.setdefault("ext", {})[namespace] = value
        return _write_project(folder, data)


def _new_id(root: Path) -> str:
    base = datetime.now().strftime("demo_%Y%m%d_%H%M%S")
    known = {p["project_id"] for p in _read_index()["projects"]}
    pid, n = base, 1
    while (root / pid).exists() or pid in known:
        n += 1
        pid = f"{base}_{n}"
    return pid


def create_project(name: str | None = None, root: Path | None = None) -> dict:
    with _LOCK:
        base = _validate_root(Path(root)) if root is not None else _validate_root(get_default_root())
        pid = _new_id(base)
        folder = base / pid
        _make_layout(folder)
        data = _blank(pid, name or pid, _now())
        atomic_write_json(folder / "project.json", data)
        _upsert_index(pid, data["name"], folder, data["updated_at"])
        set_active(pid)
        return _expand(folder, data)


def begin_session(project_id: str | None = None) -> dict:
    if project_id:
        set_active(project_id)
        return get_project(project_id)
    return create_project()


def save_narration(project_id: str, segments: list, flags: dict) -> dict:
    folder = project_path(project_id)
    now = _now()
    atomic_write_json(folder / "work" / "narration.json",
                      {"segments": segments, "flags": flags, "timestamp": now})
    return update_project(project_id, stage="narration_approved", narration={"approved_at": now})


def resolve_file(project_id: str, rel: str) -> Path:
    folder = project_path(project_id).resolve()
    p = (folder / rel).resolve()
    try:
        p.relative_to(folder)
    except ValueError:
        raise ValueError("path is outside the project folder") from None
    return p


def archive_final(project_id: str) -> list[Path]:
    folder = project_path(project_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    moved = []
    for f in sorted((folder / "final").glob("*")):
        if f.is_file():
            dest = folder / "previous" / f"{stamp}_{f.name}"
            shutil.move(str(f), str(dest))
            moved.append(dest)
    return moved


# ── root config (Task 2) ──────────────────────────────────────────────────────

def _validate_root(root: Path) -> Path:
    if not root.is_absolute():
        raise ValueError("root must be an absolute path")
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".gator_probe_{os.getpid()}"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ValueError(f"root is not writable: {exc}") from exc
    return root


def get_default_root() -> Path:
    configured = load_config().get(CONFIG_ROOT_KEY)
    return Path(configured) if configured else DEFAULT_ROOT
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/demo_project_state/test_store.py -v`
Expected: all PASS. If the `_Fixed` datetime monkeypatch test fails because `create_project` calls `datetime.now()` with no `tz`, the fixed stub already accepts `tz=None`; `_now()` also calls `datetime.now(timezone.utc)` and the stub returns a naive value whose `isoformat()` still works.

- [ ] **Step 5: Commit**

```bash
git add web/demo_projects.py tests/demo_project_state
git commit -m "feat(recorder): add durable demo project store"
```

---

### Task 2: Root configuration

**Files:**

- Modify: `web/demo_projects.py` (add `set_default_root`)
- Test: `tests/demo_project_state/test_root.py`

**Interfaces:**

- Produces: `set_default_root(root: str | None) -> Path`. `None` removes the config key and returns `DEFAULT_ROOT`. `get_default_root()` and `_validate_root()` already exist from Task 1.

- [ ] **Step 1: Write the failing tests**

`tests/demo_project_state/test_root.py`:

```python
import pytest


def test_default_root_when_unset(store, tmp_path):
    assert store.get_default_root() == tmp_path / "demos"


def test_set_default_root_persists_and_is_used(store, tmp_path):
    target = tmp_path / "mine"
    assert store.set_default_root(str(target)) == target
    assert store.get_default_root() == target
    p = store.create_project()
    assert store.project_path(p["project_id"]).parent == target


def test_reset_default_root(store, tmp_path):
    store.set_default_root(str(tmp_path / "mine"))
    assert store.set_default_root(None) == tmp_path / "demos"
    assert store.get_default_root() == tmp_path / "demos"


def test_relative_root_rejected(store):
    with pytest.raises(ValueError):
        store.set_default_root("relative/path")


def test_unwritable_root_rejected(store, tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        store.set_default_root(str(blocker / "sub"))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/demo_project_state/test_root.py -v`
Expected: FAIL, `AttributeError: ... has no attribute 'set_default_root'`.

- [ ] **Step 3: Implement**

Append to `web/demo_projects.py`:

```python
def set_default_root(root: str | None) -> Path:
    with _LOCK:
        cfg = load_config()
        if root is None:
            cfg.pop(CONFIG_ROOT_KEY, None)
            save_config(cfg)
            return DEFAULT_ROOT
        path = _validate_root(Path(root))
        cfg[CONFIG_ROOT_KEY] = str(path)
        save_config(cfg)
        return path
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/demo_project_state -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/demo_projects.py tests/demo_project_state/test_root.py
git commit -m "feat(recorder): configurable demo project root"
```

---

### Task 3: Legacy folder adoption and project listing

**Files:**

- Modify: `web/demo_projects.py`
- Test: `tests/demo_project_state/test_legacy.py`

**Interfaces:**

- Produces: `adopt_legacy_folder(folder: Path) -> dict` (returns expanded project), `list_projects() -> list[dict]` (expanded projects, newest `updated_at` first; adopts legacy folders under the default root; drops index entries whose folder is gone).
- Legacy mapping: `seg_*.mp4` → `source/`; `ffmpeg_log.txt` → `work/logs/`; `<id>_final.mp4` (the old stitched recording) → `source/recording.mp4` and becomes `raw`. Stage `recorded` when a stitched file exists, else `created`. Other files stay where they are.

- [ ] **Step 1: Write the failing tests**

`tests/demo_project_state/test_legacy.py`:

```python
import json


def _legacy(root, pid="demo_20260101_101010"):
    d = root / pid
    d.mkdir(parents=True)
    (d / "seg_00.mp4").write_bytes(b"a")
    (d / "seg_01.mp4").write_bytes(b"b")
    (d / "ffmpeg_log.txt").write_text("log", encoding="utf-8")
    (d / f"{pid}_final.mp4").write_bytes(b"stitched")
    (d / "notes.txt").write_text("keep", encoding="utf-8")
    return d


def test_adopt_moves_files_into_layout(store, tmp_path):
    d = _legacy(tmp_path / "demos")
    p = store.adopt_legacy_folder(d)
    assert (d / "source" / "seg_00.mp4").read_bytes() == b"a"
    assert (d / "source" / "seg_01.mp4").read_bytes() == b"b"
    assert (d / "work" / "logs" / "ffmpeg_log.txt").read_text(encoding="utf-8") == "log"
    assert (d / "source" / "recording.mp4").read_bytes() == b"stitched"
    assert (d / "notes.txt").exists()
    assert not (d / "seg_00.mp4").exists()
    data = json.loads((d / "project.json").read_text(encoding="utf-8"))
    assert data["segments"] == ["source/seg_00.mp4", "source/seg_01.mp4"]
    assert data["raw"] == "source/recording.mp4" and data["stage"] == "recorded"
    assert p["project_id"] == "demo_20260101_101010"


def test_adopt_is_idempotent(store, tmp_path):
    d = _legacy(tmp_path / "demos")
    store.adopt_legacy_folder(d)
    before = (d / "project.json").read_text(encoding="utf-8")
    store.adopt_legacy_folder(d)
    assert (d / "project.json").read_text(encoding="utf-8") == before


def test_list_adopts_legacy_and_orders_recent_first(store, tmp_path):
    _legacy(tmp_path / "demos", "demo_20260101_101010")
    new = store.create_project()
    ids = [p["project_id"] for p in store.list_projects()]
    assert set(ids) == {"demo_20260101_101010", new["project_id"]}
    assert ids[0] == new["project_id"]


def test_list_drops_entries_for_missing_folders(store, tmp_path):
    p = store.create_project()
    import shutil
    shutil.rmtree(store.project_path(p["project_id"]))
    assert store.list_projects() == []


def test_list_ignores_non_demo_folders(store, tmp_path):
    (tmp_path / "demos" / "random").mkdir(parents=True)
    assert store.list_projects() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/demo_project_state/test_legacy.py -v`
Expected: FAIL, `AttributeError: ... 'adopt_legacy_folder'`.

- [ ] **Step 3: Implement**

Append to `web/demo_projects.py`:

```python
_LEGACY_RE = re.compile(r"^demo_\d{8}_\d{6}$")


def adopt_legacy_folder(folder: Path) -> dict:
    with _LOCK:
        if (folder / "project.json").exists():
            data = _read_project(folder)
            if not any(p["project_id"] == data["project_id"] for p in _read_index()["projects"]):
                _upsert_index(data["project_id"], data["name"], folder, data["updated_at"])
            return _expand(folder, data)
        pid = folder.name
        _make_layout(folder)
        for seg in sorted(folder.glob("seg_*.mp4")):
            shutil.move(str(seg), str(folder / "source" / seg.name))
        log = folder / "ffmpeg_log.txt"
        if log.exists():
            shutil.move(str(log), str(folder / "work" / "logs" / log.name))
        stitched = folder / f"{pid}_final.mp4"
        raw = None
        if stitched.exists():
            shutil.move(str(stitched), str(folder / "source" / "recording.mp4"))
            raw = "source/recording.mp4"
        mtime = datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat()
        data = _blank(pid, pid, mtime)
        data["segments"] = [f"source/{s.name}" for s in sorted((folder / "source").glob("seg_*.mp4"))]
        data["raw"] = raw
        data["stage"] = "recorded" if raw else "created"
        atomic_write_json(folder / "project.json", data)
        _upsert_index(pid, pid, folder, mtime)
        return _expand(folder, data)


def list_projects() -> list[dict]:
    with _LOCK:
        root = get_default_root()
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if d.is_dir() and _LEGACY_RE.match(d.name) and not (d / "project.json").exists():
                    adopt_legacy_folder(d)
        idx = _read_index()
        kept = [p for p in idx["projects"] if (Path(p["path"]) / "project.json").exists()]
        if len(kept) != len(idx["projects"]):
            idx["projects"] = kept
            _write_index(idx)
        kept.sort(key=lambda p: p["updated_at"], reverse=True)
        return [get_project(p["project_id"]) for p in kept]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/demo_project_state -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/demo_projects.py tests/demo_project_state/test_legacy.py
git commit -m "feat(recorder): adopt legacy flat demo folders into projects"
```

---

### Task 4: `/api/demo-projects` routes

**Files:**

- Create: `web/routes/demo_projects.py`
- Modify: `web/app.py` (import near line 100, include near line 915)
- Test: `tests/demo_project_state/test_routes.py`

**Interfaces:**

- Consumes: everything from Tasks 1-3, `security.verify_csrf`, `security.get_csrf_token(host)`.
- Produces routes: `GET /api/demo-projects/settings`, `PUT /api/demo-projects/settings`, `GET /api/demo-projects`, `POST /api/demo-projects`, `GET /api/demo-projects/active`, `GET /api/demo-projects/{id}`, `POST /api/demo-projects/{id}/activate`, `POST /api/demo-projects/{id}/narration`, `GET /api/demo-projects/{id}/file?rel=`.
- Error mapping: unknown ID 404, `ValueError` 400, outside-folder file 403.

- [ ] **Step 1: Write the failing tests**

`tests/demo_project_state/test_routes.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token


@pytest.fixture
def client(store):
    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


def test_create_list_get_active(client):
    r = client.post("/api/demo-projects", json={"name": "Quarterly demo"})
    assert r.status_code == 200
    pid = r.json()["project_id"]
    assert r.json()["name"] == "Quarterly demo"
    assert client.get("/api/demo-projects/active").json()["project_id"] == pid
    assert client.get(f"/api/demo-projects/{pid}").json()["stage"] == "created"
    assert [p["project_id"] for p in client.get("/api/demo-projects").json()["projects"]] == [pid]


def test_settings_not_shadowed_and_round_trip(client, tmp_path):
    r = client.get("/api/demo-projects/settings")
    assert r.status_code == 200 and r.json()["is_default"] is True
    target = tmp_path / "chosen"
    r = client.put("/api/demo-projects/settings", json={"root": str(target)})
    assert r.status_code == 200 and r.json()["default_root"] == str(target)
    assert client.get("/api/demo-projects/settings").json()["is_default"] is False
    assert client.put("/api/demo-projects/settings", json={"root": None}).json()["is_default"] is True


def test_settings_rejects_relative_root(client):
    assert client.put("/api/demo-projects/settings", json={"root": "rel/dir"}).status_code == 400


def test_unknown_project_404(client):
    assert client.get("/api/demo-projects/demo_19990101_000000").status_code == 404
    assert client.post("/api/demo-projects/demo_19990101_000000/activate").status_code == 404


def test_activate(client):
    a = client.post("/api/demo-projects", json={}).json()["project_id"]
    b = client.post("/api/demo-projects", json={}).json()["project_id"]
    assert client.get("/api/demo-projects/active").json()["project_id"] == b
    assert client.post(f"/api/demo-projects/{a}/activate").status_code == 200
    assert client.get("/api/demo-projects/active").json()["project_id"] == a


def test_narration_writes_file_and_stage(client, store):
    pid = client.post("/api/demo-projects", json={}).json()["project_id"]
    r = client.post(f"/api/demo-projects/{pid}/narration",
                    json={"segments": [{"text": "hi"}], "flags": {"music": False}})
    assert r.status_code == 200 and r.json()["stage"] == "narration_approved"
    assert (store.project_path(pid) / "work" / "narration.json").exists()


def test_file_route_serves_inside_and_blocks_outside(client, store):
    pid = client.post("/api/demo-projects", json={}).json()["project_id"]
    (store.project_path(pid) / "final" / "demo.mp4").write_bytes(b"vid")
    ok = client.get(f"/api/demo-projects/{pid}/file", params={"rel": "final/demo.mp4"})
    assert ok.status_code == 200 and ok.content == b"vid"
    assert ok.headers["content-type"] == "video/mp4"
    assert client.get(f"/api/demo-projects/{pid}/file", params={"rel": "../x"}).status_code == 403
    assert client.get(f"/api/demo-projects/{pid}/file", params={"rel": "final/none.mp4"}).status_code == 404


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/demo-projects", {}),
    ("put", "/api/demo-projects/settings", {"root": None}),
    ("post", "/api/demo-projects/demo_19990101_000000/activate", None),
    ("post", "/api/demo-projects/demo_19990101_000000/narration", {"segments": []}),
])
def test_mutating_routes_require_csrf(store, method, path, body):
    c = TestClient(app)
    r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
    assert r.status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/demo_project_state/test_routes.py -v`
Expected: FAIL (404s: routes not registered).

- [ ] **Step 3: Implement the router**

`web/routes/demo_projects.py`:

```python
"""Demo project routes — see docs/superpowers/specs/2026-10-19-demo-project-state-design.md."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import demo_projects as dp
from security import verify_csrf

router = APIRouter()

_MEDIA = {".mp4": "video/mp4", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}


class CreateProjectRequest(BaseModel):
    name: str | None = None
    root: str | None = None


class SettingsRequest(BaseModel):
    root: str | None = None


class NarrationRequest(BaseModel):
    segments: list
    flags: dict = {}


def _settings() -> dict:
    root = dp.get_default_root()
    return {"default_root": str(root), "is_default": root == dp.DEFAULT_ROOT}


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _get(project_id: str) -> dict:
    try:
        return dp.get_project(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None


@router.get("/api/demo-projects/settings")
async def get_settings():
    return _settings()


@router.put("/api/demo-projects/settings", dependencies=[Depends(verify_csrf)])
async def put_settings(req: SettingsRequest):
    try:
        dp.set_default_root(req.root)
    except ValueError as exc:
        raise _bad(exc)
    return _settings()


@router.get("/api/demo-projects")
async def list_projects():
    return {"projects": dp.list_projects(), "active_project_id": dp.get_active_id()}


@router.post("/api/demo-projects", dependencies=[Depends(verify_csrf)])
async def create_project(req: CreateProjectRequest):
    try:
        return dp.create_project(name=req.name, root=Path(req.root) if req.root else None)
    except ValueError as exc:
        raise _bad(exc)


@router.get("/api/demo-projects/active")
async def get_active():
    pid = dp.get_active_id()
    if not pid:
        raise HTTPException(status_code=404, detail="No active project")
    return _get(pid)


@router.get("/api/demo-projects/{project_id}")
async def get_project(project_id: str):
    return _get(project_id)


@router.post("/api/demo-projects/{project_id}/activate", dependencies=[Depends(verify_csrf)])
async def activate(project_id: str):
    try:
        dp.set_active(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return dp.get_project(project_id)


@router.post("/api/demo-projects/{project_id}/narration", dependencies=[Depends(verify_csrf)])
async def narration(project_id: str, req: NarrationRequest):
    _get(project_id)
    return dp.save_narration(project_id, req.segments, req.flags)


@router.get("/api/demo-projects/{project_id}/file")
async def serve_file(project_id: str, rel: str):
    _get(project_id)
    try:
        p = dp.resolve_file(project_id, rel)
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside project") from None
    if not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(p), media_type=_MEDIA.get(p.suffix.lower(), "application/octet-stream"))
```

In `web/app.py`, after line 100 (`from routes.recorder import router as recorder_router`) add:

```python
from routes.demo_projects import router as demo_projects_router
```

and after line 915 (`app.include_router(recorder_router)`) add:

```python
app.include_router(demo_projects_router)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/demo_project_state tests/test_csrf_route_inventory.py -v`
Expected: all PASS; the CSRF inventory test sees no unprotected new route.

- [ ] **Step 5: Commit**

```bash
git add web/routes/demo_projects.py web/app.py tests/demo_project_state/test_routes.py
git commit -m "feat(recorder): add /api/demo-projects routes"
```

---

### Task 5: Recorder wiring

**Files:**

- Modify: `web/routes/recorder.py` (lines are for the reference tree; locate by the quoted code)
- Test: `tests/demo_project_state/test_recorder_shims.py`

**Interfaces:**

- Consumes: `demo_projects.begin_session`, `get_project`, `update_project`, `get_active_id`, `list_projects`, `save_narration`, `project_path`.
- Produces in `recorder.py`: `_raw_path() -> Path | None` (`_session_dir / "source" / "recording.mp4"`), `_log_path() -> Path | None` (`_session_dir / "work" / "logs" / "ffmpeg_log.txt"`). `StartRequest.project_id: Optional[str] = None`. Start/stop/status responses gain `project_id`.

- [ ] **Step 1: Write the failing shim tests**

`tests/demo_project_state/test_recorder_shims.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token


@pytest.fixture
def client(store):
    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


def test_latest_output_404_without_project(client):
    assert client.get("/api/recorder/latest-output").status_code == 404


def test_latest_output_derived_from_active_project(client, store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    (folder / "source" / "recording.mp4").write_bytes(b"r")
    store.update_project(pid, raw=folder / "source" / "recording.mp4", stage="recorded")
    (folder / "final" / "demo.mp4").write_bytes(b"f")
    body = client.get("/api/recorder/latest-output").json()
    assert body["project_id"] == pid
    assert body["raw"] == str(folder / "source" / "recording.mp4")
    assert body["final"] == str(folder / "final" / "demo.mp4")


def test_narration_approved_writes_project_and_legacy_file(client, store, tmp_path, monkeypatch):
    import routes.recorder as rec
    monkeypatch.setattr(rec.Path, "home", classmethod(lambda cls: tmp_path))
    pid = store.create_project()["project_id"]
    r = client.post("/api/recorder/narration-approved", json={"segments": [{"text": "hi"}], "flags": {}})
    assert r.status_code == 200
    assert (store.project_path(pid) / "work" / "narration.json").exists()
    legacy = json.loads((tmp_path / ".gator" / "narration_pending.json").read_text(encoding="utf-8"))
    assert legacy["segments"] == [{"text": "hi"}]


def test_set_output_shim(client, store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    assert client.post("/api/recorder/set-output", json={"final": str(folder / "final" / "d.mp4")}).status_code == 200
    assert client.post("/api/recorder/set-output", json={"final": "C:/elsewhere/d.mp4"}).status_code == 400


def test_serve_file_allows_any_project_folder(client, store, tmp_path):
    pid = store.create_project(root=tmp_path / "other")["project_id"]
    f = store.project_path(pid) / "final" / "d.mp4"
    f.write_bytes(b"vid")
    assert client.get("/api/recorder/serve-file", params={"path": str(f)}).status_code == 200
    assert client.get("/api/recorder/serve-file", params={"path": str(tmp_path / "x.mp4")}).status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/demo_project_state/test_recorder_shims.py -v`
Expected: FAIL (singleton routes still read `~/.gator/latest_output.json`).

- [ ] **Step 3: Edit recorder.py**

3a. Imports and helpers. After `router = APIRouter()` (line 18) add `import demo_projects as dp` with the other imports at the top, and below the session globals (after line 105) add:

```python
def _raw_path() -> Path | None:
    return _session_dir / "source" / "recording.mp4" if _session_dir else None


def _log_path() -> Path | None:
    return _session_dir / "work" / "logs" / "ffmpeg_log.txt" if _session_dir else None
```

3b. `StartRequest` (line ~575): add `project_id: Optional[str] = None`.

3c. `_start_segment` (lines 655-659): replace

```python
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seg_path = _session_dir / f"seg_{seg_index:02d}.mp4"
    log_path = _session_dir / "ffmpeg_log.txt"
```

with

```python
    seg_path = _session_dir / "source" / f"seg_{seg_index:02d}.mp4"
    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
```

3d. `recorder_start` (lines 756-771). Replace the block from `_session_tag = datetime.now()...` through `_segments = []` and the `_start_segment(ffmpeg, req, screens, 0)` call:

```python
    try:
        project = dp.begin_session(req.project_id)
    except KeyError:
        return JSONResponse(status_code=404, content={"ok": False, "error": "project not found"})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    _session_tag = project["project_id"]
    _session_dir = Path(project["path"])
    _segments = [Path(s) for s in project["segments"]]
    _paused_elapsed = 0.0
    _paused_at = None

    try:
        proc, seg_path = _start_segment(ffmpeg, req, screens, len(_segments))
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
```

After `_segments.append(seg_path)` add `dp.update_project(_session_tag, stage="recording", segments=_segments)`.
In the early-exit error response replace `"log": str(_session_dir / "ffmpeg_log.txt")` with `"log": str(_log_path())`. In the success response replace `"path": str(_session_dir / f"{_session_tag}_final.mp4"),` with `"path": str(_raw_path()), "project_id": _session_tag,`.

3e. `recorder_stop` (lines 937-954). Replace `final_path = _session_dir / f"{_session_tag}_final.mp4"` with `final_path = _raw_path()`. Replace the `_write_latest_output(...)` block with:

```python
    if final and _session_tag:
        try:
            dp.update_project(_session_tag, stage="recorded", segments=_segments, raw=final)
        except (KeyError, ValueError):
            pass
```

Add `"project_id": _session_tag,` to the stop response dict.

3f. Delete `_write_latest_output` (lines 965-981).

3g. `recorder_status` (lines 984-1021): replace `log_path = str(_session_dir / "ffmpeg_log.txt") if _session_dir else None` with `log_path = str(_log_path()) if _session_dir else None`; replace both `str(_session_dir / f"{_session_tag}_final.mp4") if _session_dir else None` with `str(_raw_path()) if _session_dir else None`; add `"project_id": _session_tag,` to the paused and recording dicts, and to the idle dict.

3h. Replace the three singleton routes (lines 1033-1087):

```python
@router.get("/api/recorder/latest-output")
async def recorder_latest_output():
    """Legacy shim: raw/final of the active demo project."""
    pid = dp.get_active_id()
    if not pid:
        return JSONResponse(status_code=404, content={"error": "no output yet"})
    p = dp.get_project(pid)
    return JSONResponse({"raw": p["raw"], "final": p["final"], "project_id": pid,
                         "timestamp": p["updated_at"]})


class SetOutputRequest(BaseModel):
    final: str
    raw: str = ""


@router.post("/api/recorder/set-output")
async def recorder_set_output(req: SetOutputRequest):
    """Legacy shim: the deliverable is whatever is in the project's final/ folder."""
    pid = dp.get_active_id()
    if not pid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "no active project"})
    try:
        Path(req.final).resolve().relative_to(dp.project_path(pid).resolve())
    except ValueError:
        return JSONResponse(status_code=400, content={"ok": False, "error": "final must be inside the project folder"})
    return {"ok": True}


class NarrationApprovedRequest(BaseModel):
    segments: list
    flags: dict = {}


@router.post("/api/recorder/narration-approved")
async def recorder_narration_approved(req: NarrationApprovedRequest):
    """Store approved narration on the active project (and the legacy pending file)."""
    pid = dp.get_active_id()
    if pid:
        dp.save_narration(pid, req.segments, req.flags)
    gator_dir = Path.home() / ".gator"
    gator_dir.mkdir(exist_ok=True)
    pending = gator_dir / "narration_pending.json"
    pending.write_text(json.dumps({
        "segments": req.segments,
        "flags": req.flags,
        "timestamp": datetime.utcnow().isoformat(),
    }), encoding="utf-8")
    return {"ok": True, "path": str(pending), "project_id": pid}
```

3i. `recorder_serve_file` (lines 1144-1161): replace the single `OUT_DIR` check with:

```python
    p = Path(path).resolve()
    roots = [OUT_DIR.resolve()] + [Path(proj["path"]).resolve() for proj in dp.list_projects()]
    if not any(p.is_relative_to(r) for r in roots):
        return JSONResponse(status_code=403, content={"error": "path outside demo projects"})
```

(remove the old `out`/`try: p.relative_to(out)` lines; keep the `exists()` and media-type lines).

3j. `recorder_debug` (line ~1095): replace `_session_dir / "ffmpeg_log.txt"` with `_log_path()`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/demo_project_state tests/test_csrf_route_inventory.py -v`
Expected: all PASS. Also run `python -m pytest tests -x -q -k "recorder or demo"` to catch any other recorder test.

- [ ] **Step 5: Manual smoke (real ffmpeg)**

Start the app, `POST /api/recorder/start` (via the Demo Recorder widget), record 3 seconds, stop. Expected: `<root>/demo_<ts>/source/seg_00.mp4`, `source/recording.mp4`, `work/logs/ffmpeg_log.txt`, `project.json` with stage `recorded`. Start again with `{"project_id": "<id>"}`: new segment is `seg_01.mp4`, stop re-stitches both.

- [ ] **Step 6: Commit**

```bash
git add web/routes/recorder.py tests/demo_project_state/test_recorder_shims.py
git commit -m "feat(recorder): record into durable demo projects"
```

---

### Task 6: Native folder picker, bridge case, Settings row

**Files:**

- Modify: `shell/main.js` (after the `skill:pick-local` handler, which ends near line 4960)
- Modify: `shell/preload.js` (after `pickLocalSkill`, line 129)
- Modify: `web/static/app.js` (new `case` after `gator:recorder`, ~line 18311; Settings wiring appended near the existing settings code)
- Modify: `web/static/index.html` (row inside `#spanel-general`, after the `spanel-title` at line 999)
- Test: `tests/demo_project_bridge.test.js`

**Interfaces:**

- Produces: `window.gatorShell.pickDemoFolder(): Promise<{ok: true, path: string} | {ok: false, cancelled: true}>`; postMessage in `{type: 'gator:pick-demo-folder'}`, out `{type: 'gator:pick-demo-folder-result', data}`.

- [ ] **Step 1: Write the failing JS test**

`tests/demo_project_bridge.test.js`:

```javascript
// gator:pick-demo-folder replies to the widget with the native picker result.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function caseBlock() {
  const start = source.indexOf("case 'gator:pick-demo-folder': {");
  assert(start > 0, 'bridge case found');
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error('case block not closed');
}

const code = `(function (d, e, window) { switch (d.type) { ${caseBlock()} } })`;
const run = vm.runInNewContext(code, {});

async function main() {
  const sent = [];
  const e = { source: { postMessage: (m) => sent.push(m) } };
  run({ type: 'gator:pick-demo-folder' }, e, {
    gatorShell: { pickDemoFolder: async () => ({ ok: true, path: 'C:/demos' }) },
  });
  await new Promise((r) => setTimeout(r, 0));
  assert.deepStrictEqual(sent[0], {
    type: 'gator:pick-demo-folder-result',
    data: { ok: true, path: 'C:/demos' },
  });

  const sent2 = [];
  run({ type: 'gator:pick-demo-folder' }, { source: { postMessage: (m) => sent2.push(m) } }, {});
  await new Promise((r) => setTimeout(r, 0));
  assert.strictEqual(sent2[0].data.ok, false);
  console.log('demo_project_bridge: ok');
}
main();
```

- [ ] **Step 2: Run to verify failure**

Run: `node tests/demo_project_bridge.test.js`
Expected: FAIL, `AssertionError: bridge case found`.

- [ ] **Step 3: Implement**

`shell/main.js`, after the `skill:pick-local` handler:

```javascript
ipcMain.handle('demo:pick-folder', async () => {
  const { dialog: _dialog } = require('electron');
  const { filePaths, canceled } = await _dialog.showOpenDialog(win, {
    title: 'Save project to…',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (canceled || !filePaths.length) return { ok: false, cancelled: true };
  return { ok: true, path: filePaths[0] };
});
```

`shell/preload.js`, after `pickLocalSkill`:

```javascript
  // Demo projects — native "Save project to…" folder picker.
  pickDemoFolder: () => ipcRenderer.invoke('demo:pick-folder'),
```

`web/static/app.js`, directly after the `gator:recorder` case's closing `}`:

```javascript
    case 'gator:pick-demo-folder': {
      const pick = window.gatorShell && window.gatorShell.pickDemoFolder;
      const reply = (data) => {
        if (e.source)
          try {
            e.source.postMessage({ type: 'gator:pick-demo-folder-result', data }, '*');
          } catch (_) {}
      };
      if (!pick) {
        reply({ ok: false, error: 'folder picker unavailable' });
        break;
      }
      pick().then(reply).catch((err) => reply({ ok: false, error: String(err) }));
      break;
    }
```

Settings row. `web/static/index.html`, inside `#spanel-general` immediately after `<div class="spanel-title">General</div>` (and its sub line, if present):

```html
<div class="srow" id="demo-root-row">
  <div class="section-status st-ok"></div>
  <div class="srow-info">
    <div class="srow-label">Demo projects folder</div>
    <div class="srow-sub" id="demo-root-path">Loading…</div>
  </div>
  <div class="srow-actions">
    <button class="btn-secondary" id="demo-root-change">Change</button>
    <button class="btn-secondary" id="demo-root-reset">Reset</button>
  </div>
</div>
```

`web/static/app.js`, appended near the end of the file:

```javascript
// ── Settings → General: demo projects folder ─────────────────────────────────
async function demoRootRefresh() {
  const label = document.getElementById('demo-root-path');
  if (!label) return;
  try {
    const s = await fetch('/api/demo-projects/settings').then((r) => r.json());
    label.textContent = s.default_root + (s.is_default ? ' (default)' : '');
  } catch (_) {
    label.textContent = 'unavailable';
  }
}

async function demoRootSet(root) {
  const resp = await fetch('/api/demo-projects/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.__CSRF_TOKEN__ || '' },
    body: JSON.stringify({ root }),
  });
  if (!resp.ok) alert((await resp.json()).detail || 'Could not use that folder');
  demoRootRefresh();
}

document.getElementById('settings-trigger')?.addEventListener('click', demoRootRefresh);
document.getElementById('demo-root-change')?.addEventListener('click', async () => {
  const picked = window.gatorShell?.pickDemoFolder
    ? await window.gatorShell.pickDemoFolder()
    : null;
  if (picked && picked.ok) demoRootSet(picked.path);
});
document.getElementById('demo-root-reset')?.addEventListener('click', () => demoRootSet(null));
```

- [ ] **Step 4: Run to verify pass, then smoke**

Run: `node tests/demo_project_bridge.test.js`
Expected: `demo_project_bridge: ok`.
Smoke in the Electron app: Settings → General shows the default path; Change opens the native picker with "Save project to…", the label updates; Reset restores the default.

- [ ] **Step 5: Commit**

```bash
git add shell/main.js shell/preload.js web/static/app.js web/static/index.html tests/demo_project_bridge.test.js
git commit -m "feat(recorder): native demo folder picker and Settings row"
```

---

### Task 7: Skill uses the project folder

**Files:**

- Modify: `web/skills/gator-demo-recorder/SKILL.md` (lines 34, 485, 722, 757, 765, 808, 829-834, 881-899)
- Modify: `web/skills/gator-demo-recorder/scripts/tts_pipeline.py`, `scripts/preflight.py` (only if they contain `gator_demos`, `latest_output` or `set-output`)
- Test: `tests/demo_project_state/test_skill_no_singletons.py`

**Interfaces:**

- Consumes: `~/.gator/demo_projects.json` (`active_project_id`, `projects[].path`), `<project>/work/narration.json`.

- [ ] **Step 1: Write the failing test**

`tests/demo_project_state/test_skill_no_singletons.py`:

```python
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder"
FORBIDDEN = ("latest-output", "set-output", "latest_output.json", "narration_pending.json", "gator_demos")


def test_skill_has_no_singleton_or_hardcoded_root_references():
    offenders = []
    for f in [SKILL / "SKILL.md", *(SKILL / "scripts").glob("*.py")]:
        text = f.read_text(encoding="utf-8")
        offenders += [f"{f.name}: {needle}" for needle in FORBIDDEN if needle in text]
    assert offenders == []


def test_skill_documents_project_folder_resolver():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "demo_projects.json" in text and "PROJECT_DIR" in text
    assert "work/narration.json" in text and "final/" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/demo_project_state/test_skill_no_singletons.py -v`
Expected: FAIL, listing the current offenders.

- [ ] **Step 3: Edit the skill**

1. Add a "Project folder" section near the top of `SKILL.md` (after the intro, before Phase 1) containing the resolver snippet from the spec and the rules: every demo lives in `PROJECT_DIR`; the agent reads `work/narration.json` for approved narration; writes TTS audio under `work/tts/`, logs under `work/logs/`, and the delivered video as `final/<name>.mp4`; never calls a mutating `/api/` route.
2. At each reference (`grep -n "latest-output\|set-output\|latest_output\|narration_pending\|gator_demos" web/skills/gator-demo-recorder/SKILL.md`): replace reads of `latest-output` with `PROJECT_DIR / "source" / "recording.mp4"`; replace reads of `narration_pending.json` with `PROJECT_DIR / "work" / "narration.json"`; delete the `set-output` call and tell the agent the file in `final/` is the registration; replace `~/Downloads/gator_demos/...` paths with `PROJECT_DIR` subpaths.
3. In `scripts/tts_pipeline.py` and `scripts/preflight.py`, replace any `gator_demos` literal or singleton file reference with a required `--project-dir` CLI argument (argparse) and derive output locations from it.
4. Re-run the grep from step 2; expect no matches.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/demo_project_state/test_skill_no_singletons.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/gator-demo-recorder tests/demo_project_state/test_skill_no_singletons.py
git commit -m "feat(recorder): skill reads and writes the demo project folder"
```

---

### Task 8: Final verification

**Files:** none modified.

- [ ] **Step 1: Run the full relevant suites**

Run: `python -m pytest tests/demo_project_state tests/test_csrf_route_inventory.py -v` then `node tests/demo_project_bridge.test.js`, then `python -m pytest tests -x -q`.
Expected: all PASS; `tests/csrf_route_baseline.txt` unchanged (`git diff --stat tests/csrf_route_baseline.txt` empty).

- [ ] **Step 2: End-to-end smoke**

In the app: start a recording with no project (a `demo_<ts>` project appears under the default root), pause/resume, stop, confirm `project.json` and layout; restart the app and `GET /api/demo-projects/active` still returns the project; place a file in `final/` and confirm `GET /api/demo-projects/<id>` reports `stage: delivered` and `final`. Place a legacy flat `demo_20250101_000000` folder in the default root and confirm `GET /api/demo-projects` adopts it.

- [ ] **Step 3: Confirm shims**

`GET /api/recorder/latest-output` returns `raw`, `final`, `project_id` for the active project.
