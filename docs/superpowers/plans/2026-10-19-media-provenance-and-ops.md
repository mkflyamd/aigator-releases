# Media Provenance and Ops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the demo recorder probe-backed media tools (frame inspection, interval replace, clip append, intro hold/title card, narration merge with video extension) that validate every time against the real duration and record exactly what they did, so the agent's media claims come from tool results and not guesses.

**Architecture:** One module, `web/demo_media.py`, probes every input with ffprobe, runs one ffmpeg command, probes the output, and returns a result built only from those probes; each operation is appended to `work/logs/media_ops.jsonl` and summarized in `project.json` `ext["media"]`. Five first-class tools in `web/skills/gator-demo-recorder/tools.py` expose it to the agent. `tts_pipeline.py` stays the TTS and audio-mux engine, run as a subprocess by `merge_narration`, which shifts narration start times by the intro length in one computed timeline.

**Tech Stack:** Python 3, ffmpeg and ffprobe (subprocess), pytest (`asyncio_mode=auto`, `--import-mode=importlib`, `pythonpath = web .`), the skill tool contract (`TOOL_DEFS` / `TOOL_HANDLERS` / `TOOL_STATUS` / `SKILL_ID`).

Spec: `docs/superpowers/specs/2026-10-19-media-provenance-and-ops-design.md`.

## Global Constraints

- The product is "AI Gator"; never write "POC".
- The only fake credential in tests, fixtures, examples and docs is `aigator-fake-api-key` (this work needs none).
- Commit messages carry no `Co-Authored-By` line.
- No new HTTP routes, so no `verify_csrf` work and no change to `tests/csrf_route_baseline.txt`.
- All media paths in tool arguments and results are project-relative (`source/recording.mp4`); files resolve through `dp.resolve_file`.
- A time must satisfy `0 <= t < probed duration`; an interval end may exceed the duration by at most 0.05 s (`EPS`) and is clamped. Out-of-range is an error carrying the real `duration_sec`, never a clamp.
- At most 8 frames per `demo_inspect_frames` call. `ext["media"].ops` keeps the last 50 summaries; the full record is `work/logs/media_ops.jsonl`.
- Edits and intros apply to silent video only (`base_has_audio` otherwise). Edit outputs go to `work/edits/`; the recording is never overwritten.
- Intro flags: `intro_mode` in `none` (default) | `hold` | `card`; `intro_duration_sec` 0.5-10, default 2; `intro_title` at most 80 characters, required for `card`. "Hold" freezes the first frame; "Title card" shows a title.
- Narration sync: `final_start_at = start_at + intro duration`, computed before TTS. Delivery requires video and audio streams within 1.0 s (`SYNC_TOL`), else `sync_mismatch`.
- Delivered files are `final/<project name>_v<N>.mp4` after `dp.archive_final`.
- The test directory is `tests/demo_media_ops/` (SP6 owns `tests/demo_media/`); test basenames are unique across `tests/`; tests need real ffmpeg and ffprobe (`GATOR_REQUIRE_FFMPEG=1` turns a missing binary into a failure instead of a skip).
- Prerequisites merged first: PRs #79, #82, #83, #84, SP3 (`web/demo_projects.py`), SP2 (`web/narration_approval.py`), SP6. Landing order of the sub-projects that edit `SKILL.md` Phase 4/5: SP3, SP2, SP6, SP7, then this plan.

---

## File Structure

| File                                                     | Action | Responsibility                                                                                                       |
| -------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------- |
| `web/demo_media.py`                                      | Create | Probing, time validation, ledger, manifest, frames, replace/append, intro, narration timeline, approval check, merge |
| `web/skills/gator-demo-recorder/tools.py`                | Create | Five agent tools over `demo_media`; error-dict wrapping                                                              |
| `web/skills/gator-demo-recorder/scripts/tts_pipeline.py` | Modify | Extended-video temp file goes beside the output                                                                      |
| `web/skills/gator-demo-recorder/SKILL.md`                | Modify | Truthful Media Claims, Phase 2 pointer, Phase 4 tool call, Phase 5 report rule                                       |
| `tests/demo_media_ops/`                                  | Create | `__init__.py`, `helpers.py`, `conftest.py`, four `test_demo_media_*.py` files                                        |
| `tests/approval_transaction/test_skill_contract.py`      | Modify | Phase 4 assertion follows the tool-based text                                                                        |
| `.github/workflows/tests.yml`                            | Modify | Install ffmpeg; require it                                                                                           |

---

### Task 1: Probing and time validation

**Files:**

- Create: `web/demo_media.py` (header, binaries, probing, time validation)
- Create: `tests/demo_media_ops/__init__.py` (empty)
- Create: `tests/demo_media_ops/helpers.py`
- Create: `tests/demo_media_ops/conftest.py`
- Test: `tests/demo_media_ops/test_demo_media_ops.py`

**Interfaces:**

- Consumes (SP3 `web/demo_projects.py`): `create_project`, `update_project`, `INDEX_PATH`, `DEFAULT_ROOT`, and `web/config.py` `load_config` / `save_config` (the `store` fixture patches these).
- Produces: `MediaError(code, message, **detail)` with `.code`, `.detail`, `.to_result() -> {"error": code, "message": ..., **detail}`; `find_binaries() -> (ffmpeg, ffprobe)`; `_run`, `_ffmpeg(args, cwd=None)`; `MediaInfo` and `probe(path) -> MediaInfo` (`duration_sec`, `video_duration_sec`, `audio_duration_sec`, `width`, `height`, `fps`, `fps_expr`, `has_video`, `has_audio`, `size_bytes`, `.to_dict()`); `check_time(value, duration, *, field, rel) -> float` (`0 <= t < duration`); `check_interval(start, end, duration, *, rel) -> (start, end)`; constants `EPS`, `DURATION_TOL`, `SYNC_TOL`, `MAX_FRAMES`, `INTRO_*`, `TTS_SCRIPT`. Test helper `make_video(path, seconds, *, color, size, fps, audio) -> Path` and fixtures `store`, `project` (a project whose raw recording is a 62.2 s silent video).

- [ ] **Step 1: Confirm the prerequisites**

Run: `grep -n "^def create_project\|^def update_project\|^def set_ext\|^def resolve_file\|^def archive_final\|^def atomic_write_json\|^def get_active_id\|^def project_path\|^INDEX_PATH\|^DEFAULT_ROOT" web/demo_projects.py && grep -n "^def canonical_hash\|^def media_fingerprint\|^def approve" web/narration_approval.py && ffmpeg -version && ffprobe -version`
Expected: every name is listed and both binaries print a version. If a name differs, adapt this plan's calls to the merged names before continuing. If ffmpeg is missing: `winget install Gyan.FFmpeg` (Windows) or `brew install ffmpeg` (macOS).

- [ ] **Step 2: Write the test support files**

`tests/demo_media_ops/__init__.py` is an empty file.

`tests/demo_media_ops/helpers.py`:

```python
import subprocess
from pathlib import Path

import demo_media as dm


def make_video(path: Path, seconds: float, *, color: str = "blue", size: str = "160x90",
               fps: int = 10, audio: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg, _ = dm.find_binaries()
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"color=c={color}:s={size}:r={fps}:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path
```

`tests/demo_media_ops/conftest.py`:

```python
import os
from pathlib import Path

import pytest

import demo_media as dm
import demo_projects as dp
from tests.demo_media_ops.helpers import make_video


def _need_ffmpeg():
    try:
        dm.find_binaries()
    except dm.MediaError:
        if os.environ.get("GATOR_REQUIRE_FFMPEG") == "1":
            raise
        pytest.skip("ffmpeg and ffprobe are not installed")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(dp, "DEFAULT_ROOT", tmp_path / "demos")
    cfg = {}
    monkeypatch.setattr(dp, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(dp, "save_config", lambda d: cfg.update(d))
    return tmp_path


@pytest.fixture
def project(store):
    _need_ffmpeg()
    info = dp.create_project("Slack Demo")
    pid = info["project_id"]
    raw = make_video(Path(info["path"]) / "source" / "recording.mp4", 62.2)
    dp.update_project(pid, raw=str(raw), stage="recorded")
    return pid, Path(info["path"])
```

- [ ] **Step 3: Write the failing tests**

`tests/demo_media_ops/test_demo_media_ops.py`:

```python
import json

import pytest

import demo_media as dm
import demo_projects as dp
from tests.demo_media_ops.helpers import make_video


def test_probe_reports_real_duration(project):
    pid, folder = project
    info = dm.probe(folder / "source" / "recording.mp4")
    assert info.duration_sec == pytest.approx(62.2, abs=0.2)
    assert info.has_video and not info.has_audio
    assert (info.width, info.height) == (160, 90)


def test_check_time_bounds():
    assert dm.check_time(0, 62.2, field="t", rel="a.mp4") == 0
    assert dm.check_time(62.1, 62.2, field="t", rel="a.mp4") == 62.1
    for bad in (-1, 62.2, 390):
        with pytest.raises(dm.MediaError) as exc:
            dm.check_time(bad, 62.2, field="t", rel="a.mp4")
        assert exc.value.code == "out_of_range"
        assert exc.value.detail["duration_sec"] == 62.2
    with pytest.raises(dm.MediaError) as exc:
        dm.check_time("5", 62.2, field="t", rel="a.mp4")
    assert exc.value.code == "bad_argument"


def test_check_interval_rules():
    assert dm.check_interval(10, 20, 62.2, rel="a.mp4") == (10, 20)
    assert dm.check_interval(60, 62.23, 62.2, rel="a.mp4") == (60, 62.2)
    for args, code in (((10, 405), "out_of_range"), ((390, 405), "out_of_range"), ((20, 10), "bad_interval")):
        with pytest.raises(dm.MediaError) as exc:
            dm.check_interval(*args, 62.2, rel="a.mp4")
        assert exc.value.code == code
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'demo_media'`.

- [ ] **Step 5: Create `web/demo_media.py`**

```python
"""Deterministic Demo project media operations with provenance.

FastAPI-free. Every operation probes its inputs with ffprobe, runs one ffmpeg
command, probes the output, and returns a result built only from those probes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import demo_projects as dp
import narration_approval

EPS = 0.05
DURATION_TOL = 0.30
SYNC_TOL = 1.0
MAX_FRAMES = 8
MAX_LEDGER_SUMMARIES = 50
INTRO_MODES = ("none", "hold", "card")
INTRO_MIN_SEC, INTRO_MAX_SEC, INTRO_DEFAULT_SEC = 0.5, 10.0, 2.0
INTRO_TITLE_MAX = 80
MEDIA_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".m4a", ".wav"}
TTS_SCRIPT = Path(__file__).parent / "skills" / "gator-demo-recorder" / "scripts" / "tts_pipeline.py"

_OP_LOCK = threading.RLock()
_EXT_LOCK = threading.Lock()

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)

_OPTIONS = [
    "Choose a start and end inside the real recording.",
    "Provide another clip to append or use as the replacement.",
    "Re-record the missing part.",
]


class MediaError(Exception):
    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail

    def to_result(self) -> dict:
        return {"error": self.code, "message": str(self), **self.detail}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

# ── binaries and subprocess seam ─────────────────────────────────────────────

def _find_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
        if base.exists():
            for candidate in sorted(base.glob(f"*/*/bin/{name}.exe"), reverse=True):
                return str(candidate)
    for folder in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        candidate = Path(folder) / name
        if candidate.exists():
            return str(candidate)
    return None


def find_binaries() -> tuple[str, str]:
    ffmpeg, ffprobe = _find_binary("ffmpeg"), _find_binary("ffprobe")
    if not ffmpeg or not ffprobe:
        raise MediaError(
            "ffmpeg_missing",
            "ffmpeg and ffprobe are required. Install with: winget install Gyan.FFmpeg (Windows) "
            "or brew install ffmpeg (macOS).",
        )
    return ffmpeg, ffprobe


def _run(cmd: list[str], timeout: int = 900, cwd: Path | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=flags, cwd=str(cwd) if cwd else None, env=env,
    )


def _ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    ffmpeg, _ = find_binaries()
    result = _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args], cwd=cwd)
    if result.returncode != 0:
        raise MediaError("ffmpeg_failed", "ffmpeg failed.", stderr_tail=(result.stderr or "")[-600:])

# ── probing ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MediaInfo:
    duration_sec: float
    video_duration_sec: float | None
    audio_duration_sec: float | None
    width: int
    height: int
    fps: float
    fps_expr: str
    has_video: bool
    has_audio: bool
    size_bytes: int

    def to_dict(self) -> dict:
        return {
            "duration_sec": round(self.duration_sec, 3), "width": self.width, "height": self.height,
            "fps": round(self.fps, 3), "has_video": self.has_video, "has_audio": self.has_audio,
            "size_bytes": self.size_bytes,
        }


def _float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out > 0 else None


def _fps(expr: str | None) -> tuple[float, str]:
    try:
        num, den = (expr or "0/1").split("/")
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return 0.0, "0/1"
    return value, expr or "0/1"


def probe(path: Path) -> MediaInfo:
    _, ffprobe = find_binaries()
    result = _run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if result.returncode != 0:
        raise MediaError("unreadable_media", f"ffprobe could not read {path.name}.",
                         stderr_tail=(result.stderr or "")[-300:])
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    video_dur = _float(video.get("duration")) if video else None
    audio_dur = _float(audio.get("duration")) if audio else None
    duration = _float((data.get("format") or {}).get("duration")) or video_dur or audio_dur
    if not duration:
        raise MediaError("unreadable_media", f"{path.name} has no readable duration.")
    fps, fps_expr = _fps(video.get("avg_frame_rate") if video else None)
    return MediaInfo(
        duration_sec=duration,
        video_duration_sec=video_dur or (duration if video else None),
        audio_duration_sec=audio_dur or (duration if audio else None),
        width=int(video.get("width", 0)) if video else 0,
        height=int(video.get("height", 0)) if video else 0,
        fps=fps, fps_expr=fps_expr,
        has_video=video is not None, has_audio=audio is not None,
        size_bytes=path.stat().st_size,
    )

# ── time validation ──────────────────────────────────────────────────────────

def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise MediaError("bad_argument", f"{field} must be a number of seconds.", field=field)
    return float(value)


def check_time(value, duration: float, *, field: str, rel: str) -> float:
    t = _number(value, field)
    if t < 0 or t >= duration:
        raise MediaError(
            "out_of_range",
            f"{field}={t:g}s is outside {rel}, which is {duration:.1f}s long.",
            field=field, requested_sec=t, duration_sec=round(duration, 3),
            valid_range_sec=[0, round(duration, 3)], file=rel, options=list(_OPTIONS),
        )
    return t


def check_interval(start, end, duration: float, *, rel: str) -> tuple[float, float]:
    s = check_time(start, duration, field="start_sec", rel=rel)
    e = _number(end, "end_sec")
    if e > duration + EPS:
        raise MediaError(
            "out_of_range",
            f"end_sec={e:g}s is outside {rel}, which is {duration:.1f}s long.",
            field="end_sec", requested_sec=e, duration_sec=round(duration, 3),
            valid_range_sec=[0, round(duration, 3)], file=rel, options=list(_OPTIONS),
        )
    if e <= s:
        raise MediaError("bad_interval", "end_sec must be greater than start_sec.",
                         start_sec=s, end_sec=e)
    return s, min(e, duration)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add web/demo_media.py tests/demo_media_ops/__init__.py tests/demo_media_ops/helpers.py tests/demo_media_ops/conftest.py tests/demo_media_ops/test_demo_media_ops.py
git commit -m "feat: add probe-backed media helpers with duration-validated seek times (#55 item 13)"
```

### Task 2: Project media state, ledger, and manifest

**Files:**

- Modify: `web/demo_media.py` (append the project-helper and manifest sections)
- Test: `tests/demo_media_ops/test_demo_media_ops.py` (append tests)

**Interfaces:**

- Consumes (Task 1): `probe`, `MediaError`, `MediaInfo`, `MEDIA_SUFFIXES`, `MAX_LEDGER_SUMMARIES`, `_OP_LOCK`, `_EXT_LOCK`, `_now`. Consumes (SP3): `dp.get_active_id`, `dp.project_path`, `dp.resolve_file`, `dp.get_project`, `dp.set_ext`.
- Produces: `project_for(project_id | None) -> (pid, folder)` (raises `no_project` / `project_not_found`); `project_file(pid, rel) -> Path` (raises `path_outside_project` / `file_not_found`); `rel_of(folder, path) -> str`; `read_media(pid) -> dict`; `update_media(pid, mutate) -> dict`; `raw_rel`, `current_rel(pid, folder) -> str | None` (the `ext.media.current` video only while `ext.media.current_base` equals the project's `raw`); `set_current(pid, folder, rel)`; `record_op(pid, folder, entry) -> dict` (adds `op_id`, `at`; appends to `work/logs/media_ops.jsonl`; keeps the last 50 in `ext.media.ops`); `_next_path`, `_partial`, `_finish(partial, out, expected_sec) -> MediaInfo` (raises `output_verification_failed`), `_out_block`; `manifest(project_id=None) -> {"ok", "project_id", "current", "files", "generated_at"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/demo_media_ops/test_demo_media_ops.py`:

```python
def test_record_op_appends_ledger_and_keeps_last_50(project):
    pid, folder = project
    for n in range(53):
        dm.record_op(pid, folder, {"operation": "inspect_frames", "n": n})
    lines = (folder / "work/logs/media_ops.jsonl").read_text().splitlines()
    assert len(lines) == 53
    ops = dm.read_media(pid)["ops"]
    assert len(ops) == 50 and ops[-1]["n"] == 52 and ops[0]["n"] == 3


def test_current_rel_follows_raw_until_an_edit_is_set(project):
    pid, folder = project
    assert dm.current_rel(pid, folder) == "source/recording.mp4"
    dm.set_current(pid, folder, "work/edits/edit_001.mp4")
    assert dm.current_rel(pid, folder) == "work/edits/edit_001.mp4"


def test_manifest_lists_real_files(project):
    pid, folder = project
    result = dm.manifest(pid)
    rels = [f["rel"] for f in result["files"]]
    assert "source/recording.mp4" in rels
    assert result["current"] == "source/recording.mp4"
    assert dm.read_media(pid)["manifest"]["files"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: the three new tests FAIL with `AttributeError: module 'demo_media' has no attribute ...`.

- [ ] **Step 3: Append to `web/demo_media.py`**

```python
# ── project helpers, media ext, ledger ───────────────────────────────────────

def project_for(project_id: str | None) -> tuple[str, Path]:
    pid = project_id or dp.get_active_id()
    if not pid:
        raise MediaError("no_project", "No active demo project. Record or open a demo first.")
    try:
        return pid, dp.project_path(pid)
    except KeyError:
        raise MediaError("project_not_found", f"Unknown demo project {pid}.", project_id=pid) from None


def project_file(pid: str, rel: str) -> Path:
    try:
        path = dp.resolve_file(pid, rel)
    except ValueError:
        raise MediaError("path_outside_project", f"{rel} is outside the project folder.", rel=rel) from None
    if not path.is_file():
        raise MediaError("file_not_found", f"{rel} does not exist in the project.", rel=rel)
    return path


def rel_of(folder: Path, path: Path) -> str:
    return path.resolve().relative_to(folder.resolve()).as_posix()


def read_media(pid: str) -> dict:
    return dict((dp.get_project(pid).get("ext") or {}).get("media") or {})


def update_media(pid: str, mutate) -> dict:
    with _EXT_LOCK:
        media = read_media(pid)
        mutate(media)
        dp.set_ext(pid, "media", media)
        return media


def raw_rel(pid: str, folder: Path) -> str | None:
    raw = dp.get_project(pid).get("raw")
    return rel_of(folder, Path(raw)) if raw else None


def current_rel(pid: str, folder: Path) -> str | None:
    media, raw = read_media(pid), raw_rel(pid, folder)
    if media.get("current") and media.get("current_base") == raw:
        return media["current"]
    return raw


def set_current(pid: str, folder: Path, rel: str) -> None:
    raw = raw_rel(pid, folder)
    update_media(pid, lambda m: m.update(current=rel, current_base=raw))


def record_op(pid: str, folder: Path, entry: dict) -> dict:
    entry = {"op_id": uuid.uuid4().hex[:8], "at": _now(), **entry}
    ledger = folder / "work" / "logs" / "media_ops.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with _EXT_LOCK:
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def mutate(media: dict) -> None:
        ops = media.setdefault("ops", [])
        ops.append(entry)
        del ops[:-MAX_LEDGER_SUMMARIES]

    update_media(pid, mutate)
    return entry


def _next_path(folder: Path, sub: str, stem: str, suffix: str) -> Path:
    target = folder / "work" / sub
    target.mkdir(parents=True, exist_ok=True)
    n = 1
    while (target / f"{stem}_{n:03d}{suffix}").exists():
        n += 1
    return target / f"{stem}_{n:03d}{suffix}"


def _finish(partial: Path, out: Path, expected_sec: float) -> MediaInfo:
    info = probe(partial)
    if abs(info.duration_sec - expected_sec) > max(DURATION_TOL, 2 / max(info.fps, 1.0)):
        partial.unlink(missing_ok=True)
        raise MediaError(
            "output_verification_failed",
            f"Output is {info.duration_sec:.2f}s but {expected_sec:.2f}s was expected; it was discarded.",
            actual_sec=round(info.duration_sec, 3), expected_sec=round(expected_sec, 3),
        )
    os.replace(partial, out)
    return probe(out)


def _partial(out: Path) -> Path:
    return out.with_name(out.stem + ".partial" + out.suffix)


def _out_block(folder: Path, out: Path, info: MediaInfo) -> dict:
    return {"rel": rel_of(folder, out), "path": str(out), "duration_sec": round(info.duration_sec, 3)}

# ── manifest ─────────────────────────────────────────────────────────────────

def manifest(project_id: str | None = None) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        files, seen = [], set()
        for sub in ("source", "work/normalized", "work/edits", "final"):
            for path in sorted((folder / sub).glob("*")) if (folder / sub).is_dir() else []:
                if not path.is_file() or path.suffix.lower() not in MEDIA_SUFFIXES or ".partial." in path.name:
                    continue
                rel = rel_of(folder, path)
                if rel in seen:
                    continue
                seen.add(rel)
                try:
                    files.append({"rel": rel, **probe(path).to_dict()})
                except MediaError as exc:
                    files.append({"rel": rel, "error": exc.code})
        current = current_rel(pid, folder)
        stamp = _now()
        update_media(pid, lambda m: m.update(manifest={"generated_at": stamp, "files": files}))
        return {"ok": True, "project_id": pid, "current": current, "files": files, "generated_at": stamp}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add web/demo_media.py tests/demo_media_ops/test_demo_media_ops.py
git commit -m "feat: record media operations in a per-project ledger and manifest (#55 item 13)"
```

### Task 3: Frame inspection that rejects impossible times

**Files:**

- Modify: `web/demo_media.py` (append the frames section)
- Test: `tests/demo_media_ops/test_demo_media_ops.py` (append tests)

**Interfaces:**

- Consumes (Tasks 1-2): `project_for`, `project_file`, `probe`, `check_time`, `_ffmpeg`, `record_op`, `rel_of`, `_OPTIONS`, `MAX_FRAMES`.
- Produces: `inspect_frames(project_id, source_rel, times_sec) -> {"ok", "operation": "inspect_frames", "source", "duration_sec", "frames": [{"time_sec", "rel", "path", "bytes"}], "op_id"}`. Rejects the whole call with `out_of_range` (`rejected`, `duration_sec`, `valid_range_sec`, `options`) when any time is outside the probed duration; `too_many_frames` above 8; `no_video`. PNGs are written to `work/frames/<stem>_<t>s.png`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/demo_media_ops/test_demo_media_ops.py`:

```python
def test_check_time_rejects_impossible_390s(project):
    pid, folder = project
    with pytest.raises(dm.MediaError) as exc:
        dm.inspect_frames(pid, "source/recording.mp4", [390])
    result = exc.value.to_result()
    assert result["error"] == "out_of_range"
    assert result["duration_sec"] == pytest.approx(62.2, abs=0.2)
    assert result["rejected"][0]["requested_sec"] == 390
    assert not list((folder / "work" / "frames").glob("*.png"))


def test_inspect_frames_returns_files_and_ledger(project):
    pid, folder = project
    result = dm.inspect_frames(pid, "source/recording.mp4", [0, 30.5])
    assert [f["time_sec"] for f in result["frames"]] == [0, 30.5]
    for f in result["frames"]:
        assert (folder / f["rel"]).stat().st_size > 0
    ledger = (folder / "work/logs/media_ops.jsonl").read_text().splitlines()
    assert json.loads(ledger[-1])["operation"] == "inspect_frames"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: the two new tests FAIL with `AttributeError: module 'demo_media' has no attribute 'inspect_frames'` (or `check_time` assertions for the 390 s test).

- [ ] **Step 3: Append to `web/demo_media.py`**

```python
# ── frames ───────────────────────────────────────────────────────────────────

def inspect_frames(project_id: str | None, source_rel: str, times_sec: list) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        if not isinstance(times_sec, list) or not times_sec:
            raise MediaError("bad_argument", "times_sec must be a non-empty list of seconds.", field="times_sec")
        if len(times_sec) > MAX_FRAMES:
            raise MediaError("too_many_frames", f"At most {MAX_FRAMES} frames per call.", max_frames=MAX_FRAMES)
        src = project_file(pid, source_rel)
        info = probe(src)
        if not info.has_video:
            raise MediaError("no_video", f"{source_rel} has no video stream.", rel=source_rel)
        times, rejected = [], []
        for value in times_sec:
            try:
                times.append(check_time(value, info.duration_sec, field="times_sec", rel=source_rel))
            except MediaError as exc:
                if exc.code != "out_of_range":
                    raise
                rejected.append({"requested_sec": exc.detail["requested_sec"]})
        if rejected:
            raise MediaError(
                "out_of_range",
                f"Requested times {[r['requested_sec'] for r in rejected]} are outside {source_rel}, "
                f"which is {info.duration_sec:.1f}s long. No frames were extracted.",
                file=source_rel, duration_sec=round(info.duration_sec, 3),
                valid_range_sec=[0, round(info.duration_sec, 3)], rejected=rejected, options=list(_OPTIONS),
            )
        frames_dir = folder / "work" / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for t in times:
            out = frames_dir / f"{src.stem}_{t:.2f}s.png"
            out.unlink(missing_ok=True)
            _ffmpeg(["-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", str(out)])
            if not out.is_file() or out.stat().st_size == 0:
                raise MediaError("frame_not_extracted", f"No frame could be read at {t:g}s in {source_rel}.",
                                 requested_sec=t, file=source_rel)
            frames.append({"time_sec": t, "rel": rel_of(folder, out), "path": str(out),
                           "bytes": out.stat().st_size})
        op = record_op(pid, folder, {
            "operation": "inspect_frames", "source": {"rel": source_rel, "duration_sec": round(info.duration_sec, 3)},
            "times_sec": times, "frames": [f["rel"] for f in frames],
        })
        return {"ok": True, "operation": "inspect_frames", "source": source_rel,
                "duration_sec": round(info.duration_sec, 3), "frames": frames, "op_id": op["op_id"]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: all tests in the file pass; the 390 s test shows `out_of_range` against the 62.2 s fixture.

- [ ] **Step 5: Commit**

```bash
git add web/demo_media.py tests/demo_media_ops/test_demo_media_ops.py
git commit -m "feat: extract frames only at times inside the real video duration (#55 item 13)"
```

### Task 4: Replace an interval and append a clip with proof of the source

**Files:**

- Modify: `web/demo_media.py` (append the splice section)
- Test: `tests/demo_media_ops/test_demo_media_ops.py` (append tests)

**Interfaces:**

- Consumes (Tasks 1-3): `project_for`, `project_file`, `probe`, `check_time`, `check_interval`, `current_rel`, `set_current`, `record_op`, `_next_path`, `_partial`, `_finish`, `_out_block`, `_ffmpeg`, `_OP_LOCK`, `_OPTIONS`, `EPS`.
- Produces:
  - `replace_interval(project_id, start_sec, end_sec, insert_rel, insert_start_sec=0.0, base_rel=None) -> {"ok", "operation": "replace_interval", "output": {"rel", "path", "duration_sec"}, "base": {"rel", "duration_sec"}, "replaced_interval_sec": [s, e], "inserted_from": {"rel", "interval_sec": [a, b]}, "inserted_audio_dropped", "timeline_shifted": False, "op_id"}`. Output duration equals the base duration.
  - `append_clip(project_id, clip_rel, clip_start_sec=0.0, clip_end_sec=None, base_rel=None) -> {"ok", "operation": "append_clip", "output", "base", "appended_from": {"rel", "interval_sec"}, "appended_at_sec", "inserted_audio_dropped", "timeline_shifted": False, "op_id"}`.
  - Both write `work/edits/edit_NNN.mp4`, call `set_current`, and fail with `base_has_audio`, `out_of_range` (insert too short: `needed_sec`), or `output_verification_failed`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/demo_media_ops/test_demo_media_ops.py`:

```python
def test_replace_interval_proves_source_and_keeps_duration(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 10, color="red")
    result = dm.replace_interval(pid, 20, 25, "source/fix.mp4", insert_start_sec=2)
    assert result["output"]["duration_sec"] == pytest.approx(62.2, abs=0.4)
    assert result["replaced_interval_sec"] == [20, 25]
    assert result["inserted_from"] == {"rel": "source/fix.mp4", "interval_sec": [2, 7]}
    assert result["timeline_shifted"] is False
    assert dm.read_media(pid)["current"] == result["output"]["rel"]
    entry = json.loads((folder / "work/logs/media_ops.jsonl").read_text().splitlines()[-1])
    assert entry["inserted_from"]["source_duration_sec"] == pytest.approx(10, abs=0.2)


def test_replace_rejects_out_of_range_interval_and_short_insert(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 3, color="red")
    with pytest.raises(dm.MediaError) as exc:
        dm.replace_interval(pid, 390, 405, "source/fix.mp4")
    assert exc.value.code == "out_of_range"
    with pytest.raises(dm.MediaError) as exc:
        dm.replace_interval(pid, 20, 25, "source/fix.mp4")
    assert exc.value.code == "out_of_range" and exc.value.detail["needed_sec"] == 5


def test_append_clip_extends_duration(project):
    pid, folder = project
    make_video(folder / "source" / "outro.mp4", 4, color="green")
    result = dm.append_clip(pid, "source/outro.mp4")
    assert result["output"]["duration_sec"] == pytest.approx(66.2, abs=0.4)
    assert result["appended_at_sec"] == pytest.approx(62.2, abs=0.2)


def test_base_with_audio_is_refused(project):
    pid, folder = project
    make_video(folder / "source" / "with_audio.mp4", 5, audio=True)
    make_video(folder / "source" / "x.mp4", 5)
    with pytest.raises(dm.MediaError) as exc:
        dm.append_clip(pid, "source/x.mp4", base_rel="source/with_audio.mp4")
    assert exc.value.code == "base_has_audio"


def _dominant(folder, rel):
    from PIL import Image
    r, g, b = Image.open(folder / rel).convert("RGB").getpixel((80, 45))
    return "red" if r > 150 and b < 100 else "blue" if b > 150 and r < 100 else f"other{(r, g, b)}"


def test_replaced_interval_pixels_come_from_the_insert(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 10, color="red")
    out = dm.replace_interval(pid, 20, 25, "source/fix.mp4")["output"]["rel"]
    frames = dm.inspect_frames(pid, out, [10, 22, 40])["frames"]
    assert [_dominant(folder, f["rel"]) for f in frames] == ["blue", "red", "blue"]


def test_edit_chain_is_discarded_when_the_raw_recording_changes(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 10, color="red")
    edited = dm.replace_interval(pid, 20, 25, "source/fix.mp4")["output"]["rel"]
    assert dm.current_rel(pid, folder) == edited
    make_video(folder / "work" / "timeline.mp4", 30)
    dp.update_project(pid, raw="work/timeline.mp4")
    assert dm.current_rel(pid, folder) == "work/timeline.mp4"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: the new tests FAIL with `AttributeError: module 'demo_media' has no attribute 'replace_interval'` (or `append_clip`).

- [ ] **Step 3: Append to `web/demo_media.py`**

```python
# ── splice (replace interval, append clip) ───────────────────────────────────

def _assemble(inputs: list[Path], pieces: list[tuple[int, float, float]], info: MediaInfo, out: Path) -> None:
    chains, labels = [], []
    for n, (idx, a, b) in enumerate(pieces):
        chains.append(
            f"[{idx}:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS,"
            f"scale={info.width}:{info.height}:force_original_aspect_ratio=decrease,"
            f"pad={info.width}:{info.height}:(ow-iw)/2:(oh-ih)/2,fps={info.fps_expr},setsar=1,format=yuv420p[p{n}]"
        )
        labels.append(f"[p{n}]")
    chains.append("".join(labels) + f"concat=n={len(pieces)}:v=1:a=0[v]")
    args: list[str] = []
    for path in inputs:
        args += ["-i", str(path)]
    args += ["-filter_complex", ";".join(chains), "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(out)]
    _ffmpeg(args)


def _edit_base(pid: str, folder: Path, base_rel: str | None) -> tuple[str, Path, MediaInfo]:
    rel = base_rel or current_rel(pid, folder)
    if not rel:
        raise MediaError("no_video", "The project has no recording to edit yet.")
    path = project_file(pid, rel)
    info = probe(path)
    if not info.has_video:
        raise MediaError("no_video", f"{rel} has no video stream.", rel=rel)
    if info.has_audio:
        raise MediaError(
            "base_has_audio",
            f"{rel} already has an audio track. Edit the silent recording, then run demo_merge_narration again.",
            rel=rel,
        )
    return rel, path, info


def replace_interval(project_id: str | None, start_sec, end_sec, insert_rel: str,
                     insert_start_sec=0.0, base_rel: str | None = None) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        base_rel, base, binfo = _edit_base(pid, folder, base_rel)
        ins = project_file(pid, insert_rel)
        iinfo = probe(ins)
        if not iinfo.has_video:
            raise MediaError("no_video", f"{insert_rel} has no video stream.", rel=insert_rel)
        s, e = check_interval(start_sec, end_sec, binfo.duration_sec, rel=base_rel)
        length = e - s
        i_start = check_time(insert_start_sec, iinfo.duration_sec, field="insert_start_sec", rel=insert_rel)
        if i_start + length > iinfo.duration_sec + EPS:
            raise MediaError(
                "out_of_range",
                f"{insert_rel} is {iinfo.duration_sec:.1f}s long; {length:.1f}s from {i_start:g}s needs "
                f"{i_start + length:.1f}s.",
                field="insert_start_sec", requested_sec=i_start, duration_sec=round(iinfo.duration_sec, 3),
                needed_sec=round(i_start + length, 3), file=insert_rel, options=list(_OPTIONS),
            )
        i_end = min(i_start + length, iinfo.duration_sec)
        pieces: list[tuple[int, float, float]] = []
        if s > EPS:
            pieces.append((0, 0.0, s))
        pieces.append((1, i_start, i_end))
        if e < binfo.duration_sec - EPS:
            pieces.append((0, e, binfo.duration_sec))
        expected = sum(b - a for _, a, b in pieces)
        out = _next_path(folder, "edits", "edit", ".mp4")
        partial = _partial(out)
        try:
            _assemble([base, ins], pieces, binfo, partial)
            oinfo = _finish(partial, out, expected)
        finally:
            partial.unlink(missing_ok=True)
        block = _out_block(folder, out, oinfo)
        op = record_op(pid, folder, {
            "operation": "replace_interval",
            "base": {"rel": base_rel, "duration_sec": round(binfo.duration_sec, 3)},
            "replaced_interval_sec": [round(s, 3), round(e, 3)],
            "inserted_from": {"rel": insert_rel, "interval_sec": [round(i_start, 3), round(i_end, 3)],
                              "source_duration_sec": round(iinfo.duration_sec, 3)},
            "inserted_audio_dropped": iinfo.has_audio,
            "output": block,
        })
        set_current(pid, folder, block["rel"])
        return {
            "ok": True, "operation": "replace_interval", "output": block,
            "base": {"rel": base_rel, "duration_sec": round(binfo.duration_sec, 3)},
            "replaced_interval_sec": [round(s, 3), round(e, 3)],
            "inserted_from": {"rel": insert_rel, "interval_sec": [round(i_start, 3), round(i_end, 3)]},
            "inserted_audio_dropped": iinfo.has_audio,
            "timeline_shifted": False, "op_id": op["op_id"],
        }


def append_clip(project_id: str | None, clip_rel: str, clip_start_sec=0.0, clip_end_sec=None,
                base_rel: str | None = None) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        base_rel, base, binfo = _edit_base(pid, folder, base_rel)
        clip = project_file(pid, clip_rel)
        cinfo = probe(clip)
        if not cinfo.has_video:
            raise MediaError("no_video", f"{clip_rel} has no video stream.", rel=clip_rel)
        c_start, c_end = check_interval(
            clip_start_sec, cinfo.duration_sec if clip_end_sec is None else clip_end_sec,
            cinfo.duration_sec, rel=clip_rel,
        )
        pieces = [(0, 0.0, binfo.duration_sec), (1, c_start, c_end)]
        expected = binfo.duration_sec + (c_end - c_start)
        out = _next_path(folder, "edits", "edit", ".mp4")
        partial = _partial(out)
        try:
            _assemble([base, clip], pieces, binfo, partial)
            oinfo = _finish(partial, out, expected)
        finally:
            partial.unlink(missing_ok=True)
        block = _out_block(folder, out, oinfo)
        appended = {"rel": clip_rel, "interval_sec": [round(c_start, 3), round(c_end, 3)]}
        op = record_op(pid, folder, {
            "operation": "append_clip",
            "base": {"rel": base_rel, "duration_sec": round(binfo.duration_sec, 3)},
            "appended_from": appended, "appended_at_sec": round(binfo.duration_sec, 3),
            "inserted_audio_dropped": cinfo.has_audio, "output": block,
        })
        set_current(pid, folder, block["rel"])
        return {
            "ok": True, "operation": "append_clip", "output": block,
            "base": {"rel": base_rel, "duration_sec": round(binfo.duration_sec, 3)},
            "appended_from": appended, "appended_at_sec": round(binfo.duration_sec, 3),
            "inserted_audio_dropped": cinfo.has_audio, "timeline_shifted": False, "op_id": op["op_id"],
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: all tests in the file pass, including the pixel test that reads frames from the replaced interval.

- [ ] **Step 5: Commit**

```bash
git add web/demo_media.py tests/demo_media_ops/test_demo_media_ops.py
git commit -m "feat: replace and append video intervals with recorded source provenance (#55 item 13)"
```

### Task 5: Intro hold and title card

**Files:**

- Modify: `web/demo_media.py` (append the intro section)
- Test: `tests/demo_media_ops/test_demo_media_ops.py` (append tests)

**Interfaces:**

- Consumes (Tasks 1-4): `project_for`, `project_file`, `probe`, `_number`, `_next_path`, `_partial`, `_finish`, `_out_block`, `_ffmpeg`, `record_op`, `_OP_LOCK`, `INTRO_*`.
- Produces: `normalize_intro(intro | None) -> {"mode", "duration_sec", "title"}` (mode `none|hold|card`; duration 0.5-10, default 2.0; title at most 80 characters; `card` requires a title; invalid input raises `bad_argument` with `field` `intro_mode` / `intro_duration_sec` / `intro_title`); `make_intro_video(project_id, video_rel, intro) -> {"ok", "operation": "intro", "intro", "output", "source", "offset_sec", "op_id"}` writing `work/edits/intro_NNN.mp4` that is `duration_sec` longer than the source (`hold` clones the first frame, `card` adds a dark card with the title drawn from a text file).

- [ ] **Step 1: Write the failing tests**

Append to `tests/demo_media_ops/test_demo_media_ops.py`:

```python
def test_intro_hold_extends_and_card_draws_title(project):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 5)
    hold = dm.make_intro_video(pid, "source/short.mp4", {"mode": "hold", "duration_sec": 2})
    assert hold["output"]["duration_sec"] == pytest.approx(7, abs=0.4)
    card = dm.make_intro_video(pid, "source/short.mp4",
                               {"mode": "card", "duration_sec": 2, "title": "Slack: it's 50% done"})
    assert card["output"]["duration_sec"] == pytest.approx(7, abs=0.4)
    assert not list((folder / "work/edits").glob("intro_title.txt"))


def test_normalize_intro_rules():
    assert dm.normalize_intro(None)["mode"] == "none"
    assert dm.normalize_intro({"mode": "hold"})["duration_sec"] == 2.0
    for bad in ({"mode": "card"}, {"mode": "hold", "duration_sec": 0.1},
                {"mode": "hold", "duration_sec": 11}, {"mode": "spin"},
                {"mode": "card", "title": "x" * 81}):
        with pytest.raises(dm.MediaError):
            dm.normalize_intro(bad)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: the two new tests FAIL with `AttributeError: module 'demo_media' has no attribute ...`.

- [ ] **Step 3: Append to `web/demo_media.py`**

```python
# ── intro (hold first frame / title card) ────────────────────────────────────

def normalize_intro(intro: dict | None) -> dict:
    intro = intro or {}
    mode = intro.get("mode") or "none"
    if mode not in INTRO_MODES:
        raise MediaError("bad_argument", f"intro mode must be one of {list(INTRO_MODES)}.", field="intro_mode")
    if mode == "none":
        return {"mode": "none", "duration_sec": 0.0, "title": ""}
    raw = intro.get("duration_sec")
    duration = INTRO_DEFAULT_SEC if raw is None else _number(raw, "intro_duration_sec")
    if not INTRO_MIN_SEC <= duration <= INTRO_MAX_SEC:
        raise MediaError("bad_argument", f"intro duration must be {INTRO_MIN_SEC}-{INTRO_MAX_SEC} seconds.",
                         field="intro_duration_sec")
    title = str(intro.get("title") or "").strip()
    if len(title) > INTRO_TITLE_MAX:
        raise MediaError("bad_argument", f"intro title is limited to {INTRO_TITLE_MAX} characters.",
                         field="intro_title")
    if mode == "card" and not title:
        raise MediaError("bad_argument", "A title card needs a title.", field="intro_title")
    return {"mode": mode, "duration_sec": round(duration, 3), "title": title}


def _find_font() -> str:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise MediaError("font_missing", "No system font was found to draw the title. Use 'hold' without a title.")


def make_intro_video(project_id: str | None, video_rel: str, intro: dict) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        intro = normalize_intro(intro)
        if intro["mode"] == "none":
            raise MediaError("bad_argument", "intro mode 'none' has nothing to render.", field="intro_mode")
        src = project_file(pid, video_rel)
        info = probe(src)
        if not info.has_video:
            raise MediaError("no_video", f"{video_rel} has no video stream.", rel=video_rel)
        d = intro["duration_sec"]
        if intro["mode"] == "card":
            pad = f"tpad=start_mode=add:start_duration={d}:color=0x111827"
        else:
            pad = f"tpad=start_mode=clone:start_duration={d}"
        chain = [pad]
        out = _next_path(folder, "edits", "intro", ".mp4")
        partial = _partial(out)
        title_file = out.parent / "intro_title.txt"
        font_file = out.parent / "intro_font.ttf"
        if intro["title"]:
            title_file.write_text(intro["title"], encoding="utf-8")
            shutil.copyfile(_find_font(), font_file)
            size = max(14, min(info.height // 14, int(info.width * 0.9 / (0.55 * len(intro["title"])))))
            chain.append(
                "drawtext=fontfile=intro_font.ttf:textfile=intro_title.txt:expansion=none:"
                f"fontcolor=white:fontsize={size}:borderw=2:bordercolor=black:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:enable=lt(t\\,{d})"
            )
        chain.append("format=yuv420p")
        try:
            _ffmpeg(["-i", str(src), "-vf", ",".join(chain), "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "20", "-an", "-movflags", "+faststart", str(partial)], cwd=out.parent)
            oinfo = _finish(partial, out, info.duration_sec + d)
        finally:
            partial.unlink(missing_ok=True)
            title_file.unlink(missing_ok=True)
            font_file.unlink(missing_ok=True)
        block = _out_block(folder, out, oinfo)
        op = record_op(pid, folder, {
            "operation": "intro", "source": {"rel": video_rel, "duration_sec": round(info.duration_sec, 3)},
            "intro": intro, "output": block,
        })
        return {"ok": True, "operation": "intro", "intro": intro, "output": block,
                "source": {"rel": video_rel, "duration_sec": round(info.duration_sec, 3)},
                "offset_sec": d, "op_id": op["op_id"]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add web/demo_media.py tests/demo_media_ops/test_demo_media_ops.py
git commit -m "feat: add hold and title-card intros with distinct rendering (#55 item 12)"
```

### Task 6: Narration timeline with intro offset, and the approval check

**Files:**

- Modify: `web/demo_media.py` (append the timeline and approval-loader code)
- Modify: `tests/demo_media_ops/helpers.py` (append `approve`)
- Test: `tests/demo_media_ops/test_demo_media_ops.py` (append tests; extend one import)

**Interfaces:**

- Consumes (Tasks 1-5): `normalize_intro`, `_number`, `MediaError`, `_OPTIONS`, `dp`. Consumes (SP2 `web/narration_approval.py`): `canonical_hash(segments, flags) -> str`, `media_fingerprint(path) -> str | None`, `approve(project_id, segments, flags) -> {"approval": {"approval_id", ...}}`, `project.json` `ext.approval = {"current_id", "version", "sha256", "approved_at", "media_fingerprint"}`, record `work/approvals/<id>.json` with `segments` and `flags`.
- Produces: `build_timeline(segments, source_duration, intro) -> {"intro", "offset_sec", "source_duration_sec", "segments": [{..., "start_at", "final_start_at"}]}` where `final_start_at = start_at + intro duration`; rejects empty text, missing/non-numeric/negative/decreasing starts and starts beyond `source_duration` (`out_of_range`). `load_approved_narration(pid, folder, approval_id=None) -> record` raising `narration_not_approved`, `approval_superseded`, `approval_corrupt`, `approval_stale_media`. Test helper `approve(pid, segments, intro=None) -> approval_id` where `intro` keys become flags `intro_<key>`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/demo_media_ops/helpers.py`:

```python
def approve(pid, segments, intro=None):
    import narration_approval
    flags = {f"intro_{k}": v for k, v in (intro or {}).items()}
    return narration_approval.approve(pid, segments, flags)["approval"]["approval_id"]
```

In `tests/demo_media_ops/test_demo_media_ops.py` change the import line

```python
from tests.demo_media_ops.helpers import make_video
```

to

```python
from tests.demo_media_ops.helpers import approve, make_video
```

Append to `tests/demo_media_ops/test_demo_media_ops.py`:

```python
def test_build_timeline_shifts_by_intro_and_validates():
    segs = [{"text": "a", "start_at": 0}, {"text": "b", "start_at": 10}]
    t = dm.build_timeline(segs, 62.2, {"mode": "hold", "duration_sec": 3})
    assert [s["final_start_at"] for s in t["segments"]] == [3, 13]
    assert dm.build_timeline(segs, 62.2, None)["offset_sec"] == 0
    with pytest.raises(dm.MediaError) as exc:
        dm.build_timeline([{"text": "late", "start_at": 390}], 62.2, None)
    assert exc.value.code == "out_of_range"
    with pytest.raises(dm.MediaError):
        dm.build_timeline([], 62.2, None)


def test_load_approved_narration_returns_the_verified_record(project):
    pid, folder = project
    aid = approve(pid, [{"text": "one", "start_at": 0}])
    record = dm.load_approved_narration(pid, folder)
    assert record["approval_id"] == aid and record["segments"][0]["text"] == "one"
    assert dm.load_approved_narration(pid, folder, aid)["approval_id"] == aid


def test_unapproved_narration_is_refused(project):
    pid, folder = project
    with pytest.raises(dm.MediaError) as exc:
        dm.load_approved_narration(pid, folder)
    assert exc.value.code == "narration_not_approved"


def test_superseded_and_corrupt_approvals_are_refused(project):
    pid, folder = project
    first = approve(pid, [{"text": "one", "start_at": 0}])
    approve(pid, [{"text": "changed", "start_at": 0}])
    with pytest.raises(dm.MediaError) as exc:
        dm.load_approved_narration(pid, folder, first)
    assert exc.value.code == "approval_superseded"
    current = dp.get_project(pid)["ext"]["approval"]["current_id"]
    (folder / "work" / "approvals" / f"{current}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(dm.MediaError) as exc:
        dm.load_approved_narration(pid, folder)
    assert exc.value.code == "approval_corrupt"


def test_recording_changed_after_approval_is_refused(project):
    pid, folder = project
    approve(pid, [{"text": "one", "start_at": 0}])
    make_video(folder / "source" / "other.mp4", 20, color="green")
    dp.update_project(pid, raw=str(folder / "source" / "other.mp4"))
    with pytest.raises(dm.MediaError) as exc:
        dm.load_approved_narration(pid, folder)
    assert exc.value.code == "approval_stale_media"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: the five new tests FAIL with `AttributeError: module 'demo_media' has no attribute ...`.

- [ ] **Step 3: Append to `web/demo_media.py`**

```python
# ── narration timeline and merge ─────────────────────────────────────────────

def build_timeline(segments: list, source_duration: float, intro: dict | None) -> dict:
    intro = normalize_intro(intro)
    offset = intro["duration_sec"]
    out, previous = [], 0.0
    for i, seg in enumerate(segments or []):
        text = str((seg or {}).get("text") or "").strip()
        if not text:
            raise MediaError("bad_argument", f"Narration segment {i} has no text.", field=f"segments[{i}].text")
        start = (seg or {}).get("start_at", (seg or {}).get("start"))
        if start is None:
            raise MediaError("bad_argument", f"Narration segment {i} has no start time.", field=f"segments[{i}].start_at")
        start = _number(start, f"segments[{i}].start_at")
        if start < 0 or start > source_duration:
            raise MediaError(
                "out_of_range",
                f"Narration segment {i} starts at {start:g}s but the recording is {source_duration:.1f}s long.",
                field=f"segments[{i}].start_at", requested_sec=start, duration_sec=round(source_duration, 3),
                valid_range_sec=[0, round(source_duration, 3)], options=list(_OPTIONS),
            )
        if start < previous:
            raise MediaError("bad_argument", "Narration start times must not decrease.", field=f"segments[{i}].start_at")
        previous = start
        out.append({**seg, "text": text, "start_at": start, "final_start_at": round(start + offset, 3)})
    if not out:
        raise MediaError("bad_argument", "There is no approved narration to merge.", field="segments")
    return {"intro": intro, "offset_sec": offset, "source_duration_sec": round(source_duration, 3), "segments": out}

def load_approved_narration(pid: str, folder: Path, approval_id: str | None = None) -> dict:
    approval = (dp.get_project(pid).get("ext") or {}).get("approval") or {}
    current = approval.get("current_id")
    if not current:
        raise MediaError("narration_not_approved", "No approved narration was found. Ask the user to approve it.")
    if approval_id and approval_id != current:
        raise MediaError("approval_superseded", "A newer narration approval exists; stop and let its turn handle it.",
                         requested=approval_id, current=current)
    if not re.fullmatch(r"appr_\d+_[0-9a-f]{8}", str(current)):
        raise MediaError("approval_corrupt", "The approval id is malformed.")
    try:
        record = json.loads((folder / "work" / "approvals" / f"{current}.json").read_text(encoding="utf-8"))
        digest = narration_approval.canonical_hash(record["segments"], record["flags"])
    except (OSError, ValueError, KeyError, TypeError):
        raise MediaError("approval_corrupt", "The approval record is unreadable. Ask the user to approve again.") from None
    if digest != approval.get("sha256"):
        raise MediaError("approval_corrupt", "The approval record does not match its hash. Ask the user to approve again.")
    expected = approval.get("media_fingerprint")
    if expected and narration_approval.media_fingerprint(dp.get_project(pid).get("raw")) != expected:
        raise MediaError("approval_stale_media", "The recording changed after the narration was approved. Ask the user to approve again.")
    return record
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_ops.py -v`
Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add web/demo_media.py tests/demo_media_ops/helpers.py tests/demo_media_ops/test_demo_media_ops.py
git commit -m "feat: shift narration by the intro length and verify the approval before merging (#55 items 12, 13)"
```

### Task 7: `merge_narration` with video extension, sync check, and progress

**Files:**

- Modify: `web/demo_media.py` (append the merge section)
- Modify: `web/skills/gator-demo-recorder/scripts/tts_pipeline.py` (one line)
- Test: `tests/demo_media_ops/test_demo_media_merge.py`

**Interfaces:**

- Consumes (Tasks 1-6): `project_for`, `project_file`, `probe`, `current_rel`, `build_timeline`, `make_intro_video`, `load_approved_narration`, `record_op`, `update_media`, `read_media`, `_out_block`, `_run`, `TTS_SCRIPT`, `SYNC_TOL`, `_OP_LOCK`; SP3 `dp.archive_final`, `dp.atomic_write_json`; SP6 `ext["clips"]["timeline"] = {"state", "soundtrack"}` (read only).
- Produces: `merge_narration(project_id=None, video_rel=None, intro_mode=None, intro_duration_sec=None, intro_title=None, voice=None, approval_id=None) -> {"ok", "operation": "merge_narration", "output": {"rel", "path", "duration_sec", "version"}, "video", "intro": {"mode", "duration_sec", "title", "applied", "source"}, "narration": {"segments", "offset_sec", "first_start_sec"}, "video_extended_by_sec", "video_stream_sec", "audio_stream_sec", "sync_ok": True, "approval_id", "op_id"}`. The intro comes from the tool arguments when `intro_mode` is given (`source: "tool_argument"`), otherwise from the approved flags `intro_mode`, `intro_duration_sec`, `intro_title` (`source: "approved_flags"`). Writes `final/<project name>_v<N>.mp4` after `dp.archive_final`, `work/timeline.json`, `work/narration_final.json`, and `work/logs/merge_progress.json` (`{approval_id, state: running|done|failed, stage, step, total, message, error, updated_at}`). Raises `sync_mismatch` (video and audio streams differ by more than 1.0 s), `output_verification_failed`, `tts_failed`. `_run_tts_pipeline(video, timeline_file, narration_file, out, work_dir, voice, soundtrack=None)` is the seam tests replace; it passes `--soundtrack` only when given. `_soundtrack(pid, folder) -> Path | None` returns the SP6 soundtrack only when `ext.clips.timeline.state == "ready"`.

- [ ] **Step 1: Write the failing tests**

`tests/demo_media_ops/test_demo_media_merge.py` (TTS is replaced by a generated sine track of the requested length; the real `merge_audio_video` from `tts_pipeline.py` still runs):

```python
import importlib.util
import subprocess
from pathlib import Path

import pytest

import demo_media as dm
import demo_projects as dp
from tests.demo_media_ops.helpers import approve, make_video


def _load_pipeline():
    spec = importlib.util.spec_from_file_location("tts_pipeline_under_test", dm.TTS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_tts(monkeypatch):
    """Replace Lemonade with a sine track of the requested length; run the real merge."""
    calls = {}

    def run(video, timeline_file, narration_file, out, work_dir, voice, soundtrack=None):
        import json
        narration = json.loads(Path(narration_file).read_text())
        calls["narration"] = narration
        calls["video"] = video
        ffmpeg, _ = dm.find_binaries()
        work_dir.mkdir(parents=True, exist_ok=True)
        audio = work_dir / "full_narration_synced.mp3"
        seconds = calls.get("audio_sec", narration[-1]["start_at"] + 3)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=300:duration={seconds}", str(audio)], check=True)
        _load_pipeline().merge_audio_video(video, audio, out)

    monkeypatch.setattr(dm, "_run_tts_pipeline", run)
    return calls


def test_narration_longer_than_source_extends_video(project, fake_tts):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 10)
    dp.update_project(pid, raw="source/short.mp4")
    approve(pid, [{"text": "one", "start_at": 1}, {"text": "two", "start_at": 8}])
    fake_tts["audio_sec"] = 16
    result = dm.merge_narration(pid)
    assert result["video_extended_by_sec"] == pytest.approx(6.0, abs=0.6)
    assert result["sync_ok"] is True
    final = Path(result["output"]["path"])
    assert final.parent == folder / "final" and final.name == "Slack_Demo_v1.mp4"
    info = dm.probe(final)
    assert info.has_video and info.has_audio
    assert info.duration_sec == pytest.approx(16, abs=0.6)
    assert dm.read_media(pid)["output_version"] == 1
    assert not (folder / "source" / "video_extended.mp4").exists()


def test_intro_hold_shifts_narration_and_adds_duration(project, fake_tts):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 10)
    dp.update_project(pid, raw="source/short.mp4")
    approve(pid, [{"text": "one", "start_at": 0}, {"text": "two", "start_at": 4}],
            intro={"mode": "hold", "duration_sec": 3})
    fake_tts["audio_sec"] = 10
    result = dm.merge_narration(pid)
    assert [s["start_at"] for s in fake_tts["narration"]] == [3, 7]
    assert result["intro"]["applied"] and result["intro"]["source"] == "approved_flags"
    assert result["narration"]["first_start_sec"] == 3
    assert result["output"]["duration_sec"] >= 13 - 0.6
    assert result["sync_ok"]


def test_second_merge_archives_previous_and_bumps_version(project, fake_tts):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 6)
    dp.update_project(pid, raw="source/short.mp4")
    approve(pid, [{"text": "one", "start_at": 0}])
    fake_tts["audio_sec"] = 4
    dm.merge_narration(pid)
    second = dm.merge_narration(pid)
    assert second["output"]["version"] == 2
    assert [f.name for f in (folder / "final").iterdir()] == ["Slack_Demo_v2.mp4"]
    assert any(f.name.endswith("Slack_Demo_v1.mp4") for f in (folder / "previous").iterdir())


def test_narration_start_past_source_is_rejected(project, fake_tts):
    pid, folder = project
    approve(pid, [{"text": "late", "start_at": 390}])
    with pytest.raises(dm.MediaError) as exc:
        dm.merge_narration(pid)
    assert exc.value.code == "out_of_range"
    assert not list((folder / "final").iterdir())


def test_progress_file_tracks_success_and_failure(project, fake_tts, monkeypatch):
    import json
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 6)
    dp.update_project(pid, raw="source/short.mp4")
    aid = approve(pid, [{"text": "one", "start_at": 0}])
    fake_tts["audio_sec"] = 4
    dm.merge_narration(pid)
    progress = json.loads((folder / "work/logs/merge_progress.json").read_text())
    assert (progress["approval_id"], progress["state"], progress["stage"]) == (aid, "done", "done")

    def boom(*a, **k):
        raise dm.MediaError("tts_failed", "Narration generation or merge failed.")

    monkeypatch.setattr(dm, "_run_tts_pipeline", boom)
    with pytest.raises(dm.MediaError):
        dm.merge_narration(pid)
    progress = json.loads((folder / "work/logs/merge_progress.json").read_text())
    assert progress["state"] == "failed" and "failed" in progress["error"]


def test_soundtrack_is_forwarded_only_when_timeline_ready(project):
    pid, folder = project
    assert dm._soundtrack(pid, folder) is None
    (folder / "work" / "soundtrack.m4a").write_bytes(b"x")
    dp.set_ext(pid, "clips", {"timeline": {"state": "building", "soundtrack": "work/soundtrack.m4a"}})
    assert dm._soundtrack(pid, folder) is None
    dp.set_ext(pid, "clips", {"timeline": {"state": "ready", "soundtrack": "work/soundtrack.m4a"}})
    assert dm._soundtrack(pid, folder) == folder / "work" / "soundtrack.m4a"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_merge.py -v`
Expected: FAIL because `demo_media` has no `_run_tts_pipeline` / `merge_narration` (the monkeypatch target is missing).

- [ ] **Step 3: Append to `web/demo_media.py`**

```python
def _write_progress(folder: Path, approval_id: str, state: str, stage: str, message: str,
                    step: int = 0, total: int = 0, error: str | None = None) -> None:
    path = folder / "work" / "logs" / "merge_progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    dp.atomic_write_json(path, {
        "approval_id": approval_id, "state": state, "stage": stage, "step": step, "total": total,
        "message": message, "error": error, "updated_at": _now(),
    })


def _run_tts_pipeline(video: Path, timeline_file: Path, narration_file: Path, out: Path,
                      work_dir: Path, voice: str, soundtrack: Path | None = None) -> None:
    cmd = [sys.executable, str(TTS_SCRIPT), "--video", str(video), "--timeline", str(timeline_file),
           "--narration", str(narration_file), "--output", str(out), "--work-dir", str(work_dir),
           "--voice", voice]
    if soundtrack:
        cmd += ["--soundtrack", str(soundtrack)]
    result = _run(cmd, timeout=900)
    if result.returncode != 0 or not out.is_file():
        raise MediaError("tts_failed", "Narration generation or merge failed.",
                         stderr_tail=((result.stderr or "") + (result.stdout or ""))[-600:])


def _intro_request(intro_mode, intro_duration_sec, intro_title, flags: dict) -> tuple[dict, str]:
    if intro_mode:
        return {"mode": intro_mode, "duration_sec": intro_duration_sec, "title": intro_title}, "tool_argument"
    return {"mode": flags.get("intro_mode"), "duration_sec": flags.get("intro_duration_sec"),
            "title": flags.get("intro_title")}, "approved_flags"


def _soundtrack(pid: str, folder: Path) -> Path | None:
    timeline = ((dp.get_project(pid).get("ext") or {}).get("clips") or {}).get("timeline") or {}
    rel = timeline.get("soundtrack")
    if timeline.get("state") != "ready" or not rel:
        return None
    path = folder / rel
    return path if path.is_file() else None


def merge_narration(project_id: str | None = None, video_rel: str | None = None, intro_mode: str | None = None,
                    intro_duration_sec=None, intro_title: str | None = None, voice: str | None = None,
                    approval_id: str | None = None) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        approved = load_approved_narration(pid, folder, approval_id)
        aid = approved["approval_id"]
        segments = approved.get("segments") or []
        total = len(segments)
        try:
            _write_progress(folder, aid, "running", "tts", f"Generating narration ({total} segments)...", 0, total)
            result = _merge(pid, folder, approved, video_rel, intro_mode, intro_duration_sec, intro_title, voice)
        except MediaError as exc:
            _write_progress(folder, aid, "failed", "done", str(exc), error=str(exc))
            raise
        except Exception as exc:
            _write_progress(folder, aid, "failed", "done", "Generation failed.", error=str(exc))
            raise
        _write_progress(folder, aid, "done", "done", "Done - your demo video is ready.", total, total)
        return result


def _merge(pid: str, folder: Path, approved: dict, video_rel, intro_mode, intro_duration_sec,
           intro_title, voice) -> dict:
    segments = approved.get("segments") or []
    intro_raw, intro_source = _intro_request(intro_mode, intro_duration_sec, intro_title,
                                             approved.get("flags") or {})
    voice = voice or (segments[0].get("voice") if segments else None) or "af_heart"
    if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", voice):
        raise MediaError("bad_argument", "voice must be letters, digits or underscores.", field="voice")
    rel = video_rel or current_rel(pid, folder)
    if not rel:
        raise MediaError("no_video", "The project has no recording to merge narration into.")
    src = project_file(pid, rel)
    sinfo = probe(src)
    if not sinfo.has_video:
        raise MediaError("no_video", f"{rel} has no video stream.", rel=rel)
    timeline = build_timeline(segments, sinfo.duration_sec, intro_raw)
    intro = timeline["intro"]
    video, video_info = src, sinfo
    if intro["mode"] != "none":
        video = project_file(pid, make_intro_video(pid, rel, intro)["output"]["rel"])
        video_info = probe(video)
    work = folder / "work"
    (work / "out").mkdir(parents=True, exist_ok=True)
    timeline_file, narration_file = work / "timeline.json", work / "narration_final.json"
    dp.atomic_write_json(timeline_file, timeline)
    dp.atomic_write_json(narration_file, [{**s, "start_at": s["final_start_at"]} for s in timeline["segments"]])
    candidate = work / "out" / "final_candidate.mp4"
    candidate.unlink(missing_ok=True)
    _run_tts_pipeline(video, timeline_file, narration_file, candidate, work / "tts", voice, _soundtrack(pid, folder))
    oinfo = probe(candidate)
    if not (oinfo.has_video and oinfo.has_audio):
        raise MediaError("output_verification_failed", "The merged file is missing its video or audio stream.",
                         candidate=str(candidate))
    v_sec = oinfo.video_duration_sec or oinfo.duration_sec
    a_sec = oinfo.audio_duration_sec or oinfo.duration_sec
    if abs(v_sec - a_sec) > SYNC_TOL:
        raise MediaError(
            "sync_mismatch", f"Video is {v_sec:.1f}s but audio is {a_sec:.1f}s; the file was not delivered.",
            video_stream_sec=round(v_sec, 3), audio_stream_sec=round(a_sec, 3), candidate=str(candidate),
        )
    version = int(read_media(pid).get("output_version", 0)) + 1
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", dp.get_project(pid).get("name") or pid).strip("_") or pid
    dp.archive_final(pid)
    final_path = folder / "final" / f"{safe}_v{version}.mp4"
    os.replace(candidate, final_path)
    block = {**_out_block(folder, final_path, probe(final_path)), "version": version}
    extended = round(max(0.0, v_sec - video_info.duration_sec), 3)
    narration = {"segments": len(segments), "offset_sec": timeline["offset_sec"],
                 "first_start_sec": timeline["segments"][0]["final_start_at"]}
    op = record_op(pid, folder, {
        "operation": "merge_narration", "approval_id": approved["approval_id"],
        "video": {"rel": rel, "duration_sec": round(sinfo.duration_sec, 3)},
        "intro": intro, "intro_source": intro_source, "narration": narration,
        "video_extended_by_sec": extended, "video_stream_sec": round(v_sec, 3),
        "audio_stream_sec": round(a_sec, 3), "output": block,
    })
    update_media(pid, lambda m: m.update(output_version=version))
    return {
        "ok": True, "operation": "merge_narration", "output": block,
        "video": {"rel": rel, "duration_sec": round(sinfo.duration_sec, 3)},
        "intro": {**intro, "applied": intro["mode"] != "none", "source": intro_source},
        "narration": narration, "video_extended_by_sec": extended,
        "video_stream_sec": round(v_sec, 3), "audio_stream_sec": round(a_sec, 3),
        "sync_ok": True, "approval_id": approved["approval_id"], "op_id": op["op_id"],
    }
```

- [ ] **Step 4: Keep the extended-video temp file out of the source folder**

In `web/skills/gator-demo-recorder/scripts/tts_pipeline.py`, locate the line with `grep -n 'video_extended.mp4' web/skills/gator-demo-recorder/scripts/tts_pipeline.py` (inside `merge_audio_video`) and change

```python
        temp_video = Path(video_path).parent / "video_extended.mp4"
```

to

```python
        temp_video = Path(out_path).parent / "video_extended.mp4"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops -v`
Expected: all tests pass; `test_narration_longer_than_source_extends_video` reports about 6 s of extension and leaves no `source/video_extended.mp4`.

- [ ] **Step 6: Commit**

```bash
git add web/demo_media.py web/skills/gator-demo-recorder/scripts/tts_pipeline.py tests/demo_media_ops/test_demo_media_merge.py
git commit -m "feat: merge approved narration with intro offset, extension reporting and sync verification (#55 items 12, 13)"
```

### Task 8: Skill tools

**Files:**

- Create: `web/skills/gator-demo-recorder/tools.py`
- Test: `tests/demo_media_ops/test_demo_media_tools.py`

**Interfaces:**

- Consumes (Tasks 1-7): `demo_media.manifest`, `inspect_frames`, `replace_interval`, `append_clip`, `merge_narration`, `MediaError`. Consumes the loader contract in `web/skills/_skill_utils.py`: `TOOL_DEFS`, `TOOL_HANDLERS`, `TOOL_STATUS`, `SKILL_ID`, checked by `validate_tool_contract`.
- Produces: `SKILL_ID = "gator-demo-recorder"` and five tools whose handler parameter names equal their schema properties: `demo_media_manifest(project_id="")`, `demo_inspect_frames(source, times_sec, project_id="")`, `demo_replace_interval(start_sec, end_sec, insert_source, insert_start_sec=0, base="", project_id="")`, `demo_append_clip(clip, clip_start_sec=0, clip_end_sec=None, base="", project_id="")`, `demo_merge_narration(intro_mode="", intro_duration_sec=None, intro_title="", voice="", video="", approval_id="", project_id="")`. Handlers never raise: `MediaError` becomes `{"error", "message", ...}`, `TimeoutExpired` becomes `ffmpeg_timeout`, anything else `media_op_failed`.

- [ ] **Step 1: Write the failing tests**

`tests/demo_media_ops/test_demo_media_tools.py`:

```python
import importlib
import inspect

import jsonschema
import pytest

from skills._skill_utils import validate_tool_contract
from tests.demo_media_ops.helpers import make_video

tools = importlib.import_module("skills.gator-demo-recorder.tools")


def test_tool_contract_is_valid():
    assert tools.SKILL_ID == "gator-demo-recorder"
    assert validate_tool_contract(tools, "gator-demo-recorder")


@pytest.mark.parametrize("tool", tools.TOOL_DEFS, ids=lambda t: t["name"])
def test_schema_matches_handler_signature(tool):
    jsonschema.Draft202012Validator.check_schema(tool["input_schema"])
    params = inspect.signature(tools.TOOL_HANDLERS[tool["name"]]).parameters
    props = tool["input_schema"]["properties"]
    assert set(props) == set(params)
    for name in tool["input_schema"]["required"]:
        assert params[name].default is inspect.Parameter.empty
    for name, p in params.items():
        assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_handlers_return_error_dict_not_exception(project):
    pid, _ = project
    result = tools.TOOL_HANDLERS["demo_inspect_frames"](
        source="source/recording.mp4", times_sec=[390, 405], project_id=pid)
    assert result["error"] == "out_of_range"
    assert result["duration_sec"] == pytest.approx(62.2, abs=0.2)
    assert tools.TOOL_HANDLERS["demo_media_manifest"](project_id="nope")["error"] == "project_not_found"


def test_replace_through_tool_layer(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 8, color="red")
    result = tools.TOOL_HANDLERS["demo_replace_interval"](
        start_sec=20, end_sec=25, insert_source="source/fix.mp4", project_id=pid)
    assert "error" not in result
    assert result["inserted_from"]["rel"] == "source/fix.mp4"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_tools.py -v`
Expected: FAIL with `ModuleNotFoundError` for the skill's `tools` module.

- [ ] **Step 3: Create the tools module**

`web/skills/gator-demo-recorder/tools.py`:

```python
"""Gator Demo Recorder tools: probe-backed media inspection, editing and narration merge."""

import logging
import subprocess

import demo_media

SKILL_ID = "gator-demo-recorder"

_PROJECT = {
    "type": "string",
    "description": "Demo project id (optional; defaults to the active project).",
}


def _call(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except demo_media.MediaError as exc:
        return exc.to_result()
    except subprocess.TimeoutExpired:
        return {"error": "ffmpeg_timeout", "message": "The media operation timed out."}
    except Exception as exc:
        logging.exception("demo media tool failed")
        return {"error": "media_op_failed", "message": str(exc)}


def _opt(value):
    return value if value not in ("", None) else None


def _tool_demo_media_manifest(project_id: str = "") -> dict:
    return _call(demo_media.manifest, _opt(project_id))


def _tool_demo_inspect_frames(source: str, times_sec: list, project_id: str = "") -> dict:
    return _call(demo_media.inspect_frames, _opt(project_id), source, times_sec)


def _tool_demo_replace_interval(start_sec: float, end_sec: float, insert_source: str,
                                insert_start_sec: float = 0, base: str = "", project_id: str = "") -> dict:
    return _call(demo_media.replace_interval, _opt(project_id), start_sec, end_sec, insert_source,
                 insert_start_sec, _opt(base))


def _tool_demo_append_clip(clip: str, clip_start_sec: float = 0, clip_end_sec: float = None,
                           base: str = "", project_id: str = "") -> dict:
    return _call(demo_media.append_clip, _opt(project_id), clip, clip_start_sec, clip_end_sec, _opt(base))


def _tool_demo_merge_narration(intro_mode: str = "", intro_duration_sec: float = None, intro_title: str = "",
                               voice: str = "", video: str = "", approval_id: str = "",
                               project_id: str = "") -> dict:
    return _call(demo_media.merge_narration, _opt(project_id), _opt(video), _opt(intro_mode),
                 intro_duration_sec, _opt(intro_title), _opt(voice), _opt(approval_id))


TOOL_DEFS = [
    {
        "name": "demo_media_manifest",
        "description": (
            "List the real media files in a demo project (source, work, final) with ffprobe-measured "
            "duration, size and streams. Call this before claiming anything about a video's length or contents."
        ),
        "input_schema": {"type": "object", "properties": {"project_id": _PROJECT}, "required": []},
    },
    {
        "name": "demo_inspect_frames",
        "description": (
            "Extract still frames at the given seconds from a project video and save them as PNGs. Times "
            "outside the video's real duration are rejected with the real duration. Max 8 frames per call. "
            "Pass the returned frame paths to describe_images. Only describe what the frames show."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Project-relative video path, e.g. source/recording.mp4"},
                "times_sec": {"type": "array", "items": {"type": "number"}, "description": "Seconds to sample."},
                "project_id": _PROJECT,
            },
            "required": ["source", "times_sec"],
        },
    },
    {
        "name": "demo_replace_interval",
        "description": (
            "Replace [start_sec, end_sec) of the silent recording with the same length from another project "
            "video. Duration is unchanged so narration timing stays valid. Rejects out-of-range times. "
            "The result lists the exact source interval used; quote it, never invent one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_sec": {"type": "number", "description": "Start of the interval to replace."},
                "end_sec": {"type": "number", "description": "End of the interval to replace."},
                "insert_source": {"type": "string", "description": "Project-relative path of the replacement video."},
                "insert_start_sec": {"type": "number", "description": "Where in the replacement video to start (default 0)."},
                "base": {"type": "string", "description": "Project-relative base video (default: the current recording)."},
                "project_id": _PROJECT,
            },
            "required": ["start_sec", "end_sec", "insert_source"],
        },
    },
    {
        "name": "demo_append_clip",
        "description": (
            "Append a clip (or part of it) to the end of the silent recording. The result gives the new "
            "duration and the exact appended interval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "clip": {"type": "string", "description": "Project-relative path of the clip to append."},
                "clip_start_sec": {"type": "number", "description": "Start inside the clip (default 0)."},
                "clip_end_sec": {"type": "number", "description": "End inside the clip (default: its end)."},
                "base": {"type": "string", "description": "Project-relative base video (default: the current recording)."},
                "project_id": _PROJECT,
            },
            "required": ["clip"],
        },
    },
    {
        "name": "demo_merge_narration",
        "description": (
            "Generate the approved narration with TTS and merge it into the recording, producing the final "
            "MP4. If narration is longer than the video the last frame is held and the result reports how "
            "much it was extended. intro_mode 'hold' freezes the first frame; 'card' shows a title card; both "
            "shift narration by the intro length. Omit intro_mode to use the approved narration's intro "
            "choice. Fails with the measured durations if audio and video do not line up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intro_mode": {"type": "string", "enum": ["none", "hold", "card"],
                               "description": "Intro style (optional)."},
                "intro_duration_sec": {"type": "number", "description": "Intro length, 0.5-10 (default 2)."},
                "intro_title": {"type": "string", "description": "Title text for 'card' (max 80 chars)."},
                "voice": {"type": "string", "description": "TTS voice id (optional)."},
                "video": {"type": "string", "description": "Project-relative video (default: the current recording)."},
                "approval_id": {"type": "string", "description": "Approval id from the trigger message; a newer approval is refused."},
                "project_id": _PROJECT,
            },
            "required": [],
        },
    },
]

TOOL_STATUS = {
    "demo_media_manifest": "Checking demo media...",
    "demo_inspect_frames": "Extracting video frames...",
    "demo_replace_interval": "Replacing video section...",
    "demo_append_clip": "Appending clip...",
    "demo_merge_narration": "Generating narration and merging video...",
}

TOOL_HANDLERS = {
    "demo_media_manifest": _tool_demo_media_manifest,
    "demo_inspect_frames": _tool_demo_inspect_frames,
    "demo_replace_interval": _tool_demo_replace_interval,
    "demo_append_clip": _tool_demo_append_clip,
    "demo_merge_narration": _tool_demo_merge_narration,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops tests/file_ops -v`
Expected: all tests pass (the `file_ops` run confirms the skill loader still discovers every skill).

- [ ] **Step 5: Commit**

```bash
git add web/skills/gator-demo-recorder/tools.py tests/demo_media_ops/test_demo_media_tools.py
git commit -m "feat: expose probe-backed demo media tools to the demo recorder skill (#55 item 13)"
```

### Task 9: SKILL.md rules and the contract test

Land this task after SP3, SP2, SP6 and SP7 are merged. Their SKILL.md edits touch Phase 4 and Phase 5; every anchor below is a heading or a sentence, never a line number.

**Files:**

- Modify: `web/skills/gator-demo-recorder/SKILL.md`
- Modify: `tests/approval_transaction/test_skill_contract.py` (one test)
- Test: `tests/demo_media_ops/test_demo_media_skill_contract.py`

**Interfaces:**

- Consumes: the five tools from Task 8 and the result fields they return; SP2's trigger-message phrase `approval (appr_\d+_[0-9a-f]{8})`; SP3's contract strings (`demo_projects.json`, `PROJECT_DIR`, `work/narration.json`, `final/`), which this task must not remove, and into which it must not reintroduce `latest-output`, `set-output`, `narration_pending.json` or `gator_demos`.
- Produces: a "Truthful Media Claims" section, a Phase 2 follow-up paragraph, a Phase 4 that calls `demo_merge_narration`, and a Phase 5 report rule.

- [ ] **Step 1: Write the failing contract test**

`tests/demo_media_ops/test_demo_media_skill_contract.py`:

````python
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder" / "SKILL.md"
TEXT = SKILL.read_text(encoding="utf-8")
TOOLS = ("demo_media_manifest", "demo_inspect_frames", "demo_replace_interval",
         "demo_append_clip", "demo_merge_narration")
MERGE_ERRORS = ("approval_superseded", "narration_not_approved", "approval_corrupt", "approval_stale_media",
                "out_of_range", "sync_mismatch", "output_verification_failed", "tts_failed")


def _between(start: str, end: str) -> str:
    i = TEXT.index(start)
    return TEXT[i:TEXT.index(end, i)]


def test_truthful_media_claims_section_names_every_tool_and_result_field():
    section = _between("## Truthful Media Claims", "## Phase 1")
    for name in TOOLS:
        assert name in section
    for field in ("inserted_from", "appended_from", "video_extended_by_sec", "out_of_range"):
        assert field in section


def test_phase2_points_to_frame_inspection():
    assert "demo_inspect_frames" in _between("## Phase 2: Analyze", "## Phase 3")


def test_phase4_merges_through_the_tool_not_inline_code():
    phase4 = _between("## Phase 4: TTS + Merge", "## Phase 5: Deliver")
    assert "demo_merge_narration" in phase4
    assert "```python" not in phase4
    assert "subprocess" not in phase4
    assert '"Hold" freezes the first frame' in phase4 and '"Title card"' in phase4
    for code in MERGE_ERRORS:
        assert f"`{code}`" in phase4


def test_phase5_reports_only_merge_result_facts():
    phase5 = TEXT[TEXT.index("## Phase 5: Deliver"):]
    assert "`demo_merge_narration` result" in phase5
````

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/demo_media_ops/test_demo_media_skill_contract.py -v`
Expected: FAIL because SKILL.md has no `Truthful Media Claims` section and still describes the `tts_pipeline.py` merge.

- [ ] **Step 3: Add the Truthful Media Claims section**

Insert the following immediately before the line `## Phase 1: Preflight → Render Widget` (after the `---` that ends the Audio/Video Quality Rules):

```markdown
## Truthful Media Claims — Non-negotiable

Every statement about a video's duration, a moment in it, or an edit must come from a `demo_*` tool result obtained in this turn. Never estimate, remember, or infer one.

- **Facts first:** call `demo_media_manifest` before stating a duration or listing files.
- **Moments:** to say what happens at a time, call `demo_inspect_frames` for that time, pass the returned `frames[].path` values to `describe_images`, and describe only what those frames show. Times must be inside `duration_sec`. On `out_of_range`, report its `duration_sec` and `options`; do not retry with another guessed time.
- **Edits:** use `demo_replace_interval` or `demo_append_clip`. Quote `replaced_interval_sec`, `inserted_from` / `appended_from` and `output.duration_sec` exactly as returned. Say an edit was made only after the result has `ok: true`.
- **Narration merge:** `demo_merge_narration` is the only way to produce the final video. Quote `video_extended_by_sec`, `video_stream_sec`, `audio_stream_sec` and `intro` from its result.
- **Intro wording:** "Hold" freezes the first frame; "Title card" shows the title text on a plain card. Use the word that matches `intro.mode`.
- **On any `error`:** relay `message` and the measured numbers, offer the listed `options`, and do not claim success.

---
```

- [ ] **Step 4: Add the Phase 2 follow-up paragraph**

At the end of Phase 2, immediately before the `---` separator that precedes `## Phase 3: Narration Edit`, insert:

```markdown
**Follow-up inspection:** to look at a specific moment after the first analysis, call `demo_inspect_frames(source='<project-relative path>', times_sec=[...])` (at most 8 times, all inside the video's duration) and pass the returned frame paths to `describe_images`. Do not write your own frame-extraction code.
```

- [ ] **Step 5: Replace Phase 4**

Replace everything from the line `## Phase 4: TTS + Merge` up to, but not including, the `---` separator that precedes `## Phase 5: Deliver` with:

```markdown
## Phase 4: TTS + Merge

When you receive `"Narration approved (N segments)..."` or `"✓ Approve..."`:

1. Call `demo_merge_narration`. The tool loads the approved narration itself and verifies it; do not read narration files, take segments from the trigger message, or run TTS, ffmpeg or ffprobe yourself. If the trigger message contains `approval (appr_\d+_[0-9a-f]{8})`, pass the captured id as `approval_id`.
2. Leave `intro_mode` out unless the user asked to change the intro; the approved narration already carries `intro_mode`, `intro_duration_sec` and `intro_title`. "Hold" freezes the first frame and "Title card" shows the title. The tool adds the intro length to every narration start time, so never adjust timestamps yourself.
3. Handle the result:
   - `ok: true`: go to Phase 5 with `output.path`. Report `video_extended_by_sec` (when above 0, say the last frame was held that long), the `intro`, and `video_stream_sec` / `audio_stream_sec` exactly as returned.
   - `approval_superseded`: stop; a newer approval has its own turn.
   - `narration_not_approved`, `approval_corrupt`, `approval_stale_media`: tell the user the narration must be approved again.
   - `out_of_range`: quote `message`, `duration_sec` and `options`, and ask which to take.
   - `sync_mismatch`, `output_verification_failed`, `tts_failed`, `ffmpeg_failed`, `ffmpeg_timeout`: report `message` and any measured durations, and offer to retry once or to deliver the video without narration. No file was delivered.
   - Any other `error`: report `message`.
     Do not retry in a loop and do not describe a video that was not produced.

If Lemonade TTS is unavailable (preflight `lemonade.ok` is false), tell the user and offer to deliver the video without narration. The TTS endpoint is `/v1/audio/speech` (OpenAI-compatible) and the model is `kokoro-v1` — both confirmed by preflight. Do not probe other endpoints.
```

- [ ] **Step 6: Update the Phase 5 report sentence**

Replace the sentence

```
After showing the widget, report the file path and size in plain text for reference.
```

with

```
After showing the widget, report the file path, size and `output.duration_sec` in plain text. State only facts that the `demo_merge_narration` result contains.
```

If SP7 or SP4 reworded it, append the new sentence to the end of the "After showing the widget" paragraph instead.

- [ ] **Step 7: Update SP2's Phase 4 contract test**

SP2's test asserts the loader text that Step 5 removes. In `tests/approval_transaction/test_skill_contract.py` replace

```python
def test_phase4_uses_the_verified_loader():
    assert "load_approval.py" in TEXT
    assert "approval (appr_\\d+_[0-9a-f]{8})" in TEXT
    for code in ("missing", "superseded", "corrupt", "stale_media"):
        assert f"`{code}`" in TEXT
```

with

```python
def test_phase4_merges_through_the_verifying_tool():
    assert "demo_merge_narration" in TEXT
    assert "approval (appr_\\d+_[0-9a-f]{8})" in TEXT
    for code in ("approval_superseded", "narration_not_approved", "approval_corrupt", "approval_stale_media"):
        assert f"`{code}`" in TEXT
```

`web/skills/gator-demo-recorder/scripts/load_approval.py` and its own tests stay as they are.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/demo_media_ops tests/approval_transaction tests/demo_project_state -v`
Expected: all tests pass, including SP3's `test_skill_no_singletons.py` and SP2's `test_skill_contract.py`.

Run: `grep -n "tts_pipeline.py\|subprocess" web/skills/gator-demo-recorder/SKILL.md`
Expected: no match inside the Phase 4 section.

- [ ] **Step 9: Commit**

```bash
git add web/skills/gator-demo-recorder/SKILL.md tests/approval_transaction/test_skill_contract.py tests/demo_media_ops/test_demo_media_skill_contract.py
git commit -m "feat: require tool-backed media claims and tool-based narration merge in the demo recorder skill (#55 items 12, 13)"
```

### Task 10: Run the real-ffmpeg tests in CI

**Files:**

- Modify: `.github/workflows/tests.yml` (add one step and one env var in the test job)

**Interfaces:**

- Consumes: `GATOR_REQUIRE_FFMPEG=1` makes `tests/demo_media_ops/conftest.py` fail instead of skip when ffmpeg or ffprobe is missing.
- Produces: ffmpeg and ffprobe on the Ubuntu, Windows and macOS runners.

- [ ] **Step 1: Add the install step**

In `.github/workflows/tests.yml`, directly before the step named `Run tests with coverage`, add:

```yaml
- name: Install ffmpeg
  shell: bash
  run: |
    case "$RUNNER_OS" in
      Linux) sudo apt-get update && sudo apt-get install -y ffmpeg ;;
      macOS) brew install ffmpeg ;;
      Windows) choco install ffmpeg -y --no-progress ;;
    esac
    ffmpeg -version | head -1
    ffprobe -version | head -1
```

- [ ] **Step 2: Require ffmpeg in the test step**

Add the environment variable to the `Run tests with coverage` step:

```yaml
- name: Run tests with coverage
  env:
    GATOR_REQUIRE_FFMPEG: '1'
  run: uv run coverage run --source=web,packaging --omit='*/tests/*' -m pytest tests -q
```

Keep the existing `run:` line exactly as it is in the file if it differs from the one shown.

- [ ] **Step 3: Verify**

Run: `GATOR_REQUIRE_FFMPEG=1 python -m pytest tests/demo_media_ops -q`
Expected: all tests pass. Then open the pull request and confirm the `Tests` workflow is green on Ubuntu, Windows and macOS; a failure on `test_intro_hold_extends_and_card_draws_title` names the ffmpeg filter error, and the fix is to install a full ffmpeg build on that runner.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: install ffmpeg so the demo media tests run on every runner (#55 item 13)"
```

---

## Self-Review

**Spec coverage**

| Spec requirement                                                                                | Task       |
| ----------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------- | --- |
| Tool-backed claims; tools not scripts; five tools and result shapes                             | 4, 5, 7, 8 |
| Seek times validated against probed duration; 390 s rejected                                    | 1, 3       |
| Replace proves its source interval; duration kept; append                                       | 4          |
| Verified outputs (`.partial`, duration check, `output_verification_failed`)                     | 2, 4       |
| Ledger `media_ops.jsonl` and `ext["media"]`; `current` honored only while `current_base == raw` | 2, 4       |
| Intro `none                                                                                     | hold       | card`, 0.5-10 s, title limits, distinct hold/card wording | 5   |
| Intro included in sync before timestamps are computed                                           | 6, 7       |
| Narration longer than the source extends the video and reports it; temp file beside output      | 7          |
| Approval check against SP2 hash, id, media fingerprint                                          | 6          |
| Sync tolerance and no delivery on mismatch; versioned finals after `archive_final`              | 7          |
| `merge_progress.json` for SP7; `--soundtrack` only when the SP6 timeline is ready               | 7          |
| Tool contract; schema equals handler signature                                                  | 8          |
| SKILL.md: Truthful Media Claims, Phase 2/4/5; SP2 test updated                                  | 9          |
| Required tests run in CI                                                                        | 10         |

**Placeholder scan:** every code step contains the full code; no step defers content.

**Type consistency:** `replace_interval`, `append_clip`, `inspect_frames` and `merge_narration` take `project_id` first in `demo_media`; result keys named in each task's Interfaces (`inserted_from`, `appended_from`, `video_extended_by_sec`, `sync_ok`, `op_id`) match the tests and the SKILL.md text; intro dict keys are `mode`, `duration_sec`, `title` inside `demo_media` and `intro_mode`, `intro_duration_sec`, `intro_title` at the flag and tool-argument boundary, bridged only by `_intro_request`.
