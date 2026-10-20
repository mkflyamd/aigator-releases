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
    try:
        return json.loads((folder / "project.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KeyError(folder.name) from None


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


_LEGACY_RE = re.compile(r"^demo_\d{8}_\d{6}$")


def adopt_legacy_folder(folder: Path) -> dict:
    with _LOCK:
        if (folder / "project.json").exists():
            data = _read_project(folder)
            if not any(p["project_id"] == data["project_id"] for p in _read_index()["projects"]):
                _upsert_index(data["project_id"], data["name"], folder, data["updated_at"])
            return _expand(folder, data)
        pid = folder.name
        mtime = datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat()
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
