# Media Intake and Multi-Clip Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users attach existing video and audio files in chat, validate them, combine several clips into one trimmed timeline with an optional music bed, and feed that timeline through the unchanged Demo Recorder narration pipeline (issue #55 items 6 and 7, plan C item 4).

**Architecture:** Uploads stream into the SP3 project's `source/` folder and are probed with ffprobe against an allow-list. A clip registry in `project.json` `ext["clips"]` records order and trims. A backend single-worker scheduler normalizes and concatenates the clips into `work/timeline.mp4` (and audio assets into `work/soundtrack.m4a`), then points the project's `raw` at the timeline so Phases 2-5 of the skill work unchanged. The agent only reads project files; all mutating routes are browser-driven and CSRF-protected.

**Tech Stack:** Python 3 / FastAPI, ffmpeg + ffprobe subprocesses, pytest (`pythonpath = web .`, importlib mode), vanilla-JS plain scripts (no modules), node `assert` JS tests.

**Spec:** `docs/superpowers/specs/2026-10-19-media-intake-and-multiclip-design.md`. **Depends on:** SP3 (`web/demo_projects.py`, project layout) and SP2 (per-tab skill pin helpers used in Task 9, and the approval transaction whose media fingerprint covers the timeline). Implement after both have landed.

## Global Constraints

- Every new POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]` from `security`. Do not add routes to `tests/csrf_route_baseline.txt`.
- No inline `on*=` attributes (strict CSP); use `addEventListener`. `app.js` and `demo-media.js` are plain global scripts (no ES modules).
- XHR must set `X-CSRF-Token` from `window.__CSRF_TOKEN__` manually; `fetch` calls to `/api/` get it from the global wrapper.
- The agent (LLM-run code) never calls mutating routes; it reads `~/.gator/demo_projects.json` and `project.json` and runs ffmpeg/`tts_pipeline.py`.
- Use `aigator-fake-api-key` as the only fake credential in tests and examples.
- The product is "AI Gator"; never call it a POC.
- Commit messages carry no `Co-Authored-By` line (CLAUDE.md overrides any attribution reminder).
- Probe constants verbatim: `VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")`, `AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")`, `VIDEO_CODECS = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}`, `AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "pcm_f32le"}`, `MAX_FILE_BYTES = 2 * 1024**3`, `MAX_CLIP_SECONDS = 1800`, `MAX_VIDEO_CLIPS = 8`, `MAX_AUDIO_ASSETS = 4`, `MAX_DIMENSION = 7680`.
- Compose constants verbatim: `TARGET_FPS = 30`, `MAX_OUT_W = 1920`, `MAX_OUT_H = 1080`, `AUDIO_RATE = 48000`. Clip-registry constants: `MAX_FRAMES = 8`, `MIN_FRAME_GAP = 5.0`, `SPEC_VERSION = 1`, `MIN_CLIP_SECONDS = 0.5`.
- Soundtrack mix filter (used by `tts_pipeline.build_merge_argv`): `[2:a]volume=0.25[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]`.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `web/demo_media_probe.py` | Create | Allow-lists, `MediaRejected`, `probe_media` |
| `web/demo_clips.py` | Create | Registry in `ext["clips"]`: add/remove/reorder/trim, limits, `fingerprint`, `frame_times`, `ClipError` |
| `web/demo_compose.py` | Create | ffmpeg argv builders, `build`, scheduler, `ensure_current` |
| `web/routes/demo_clips.py` | Create | `/api/demo-media` routes |
| `web/app.py` | Modify | import + include the router |
| `web/static/demo-media.js` | Create | `DemoMedia` global: helpers, XHR upload, clip panel |
| `web/static/index.html` | Modify | panel container, script tag, file-input `accept` |
| `web/static/style.css` | Modify | `.demo-media-panel` styles |
| `web/static/app.js` | Modify | `processFiles` media branch, `_attachDemoMedia`, submit gate |
| `web/skills/gator-demo-recorder/scripts/tts_pipeline.py` | Modify | `build_merge_argv`, `--soundtrack` |
| `web/skills/gator-demo-recorder/SKILL.md` | Modify | Import Mode section, Phase 4 soundtrack |
| `tests/demo_media/{__init__,conftest,test_probe,test_clips,test_compose,test_routes,test_compose_integration,test_skill_clip_rules}.py` | Create | Python tests |
| `tests/demo_media_ui.test.js` | Create | JS helper tests |

Run Python tests with `python -m pytest tests/demo_media -v` from the repo root; JS with `node tests/demo_media_ui.test.js`.

---

### Task 1: Media probe and validation

**Files:**
- Create: `web/demo_media_probe.py`
- Create: `tests/demo_media/__init__.py` (empty)
- Create: `tests/demo_media/conftest.py`
- Test: `tests/demo_media/test_probe.py`

**Interfaces:**
- Produces (in `demo_media_probe`): the constants above; `class MediaRejected(Exception)` with `.code: str` and `.message: str`; `extension_kind(name: str) -> str | None` (`"video"`, `"audio"` or `None`); `ffprobe_path() -> str | None`; `_run_ffprobe(path: Path) -> dict` (raw ffprobe JSON, raises `MediaRejected`); `probe_media(path, name: str | None = None) -> dict` returning `{"kind", "duration", "width", "height", "has_audio", "video_codec", "audio_codec"}`.
- Produces (conftest fixtures): `store` (SP3 module with redirected paths), `fake_ffprobe(**kw)` installer (`kind="video"|"audio"`, `duration=10.0`, `width=1920`, `height=1080`, `vcodec="h264"`, `acodec="aac"`, `has_audio=True`, `attached_pic=False`).
- Consumes: `proc_utils.no_window_kwargs`, `routes.recorder._find_ffprobe` (lazy import).

- [ ] **Step 1: Write the fixtures and failing tests**

`tests/demo_media/conftest.py`:

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


def _ffprobe_json(kind="video", duration=10.0, width=1920, height=1080,
                  vcodec="h264", acodec="aac", has_audio=True, attached_pic=False):
    streams = []
    if kind == "video":
        streams.append({"codec_type": "video", "codec_name": vcodec, "width": width,
                        "height": height, "disposition": {"attached_pic": 0}})
        if has_audio:
            streams.append({"codec_type": "audio", "codec_name": acodec})
    else:
        streams.append({"codec_type": "audio", "codec_name": acodec})
        if attached_pic:
            streams.append({"codec_type": "video", "codec_name": "mjpeg", "width": 500,
                            "height": 500, "disposition": {"attached_pic": 1}})
    return {"streams": streams, "format": {"duration": str(duration)}}


@pytest.fixture
def fake_ffprobe(monkeypatch):
    import demo_media_probe as probe

    def install(**kwargs):
        data = _ffprobe_json(**kwargs)
        monkeypatch.setattr(probe, "_run_ffprobe", lambda path: data)

    return install
```

`tests/demo_media/test_probe.py`:

```python
import types
from pathlib import Path

import pytest

import demo_media_probe as probe


def test_extension_kind():
    assert probe.extension_kind("Demo.MP4") == "video"
    assert probe.extension_kind("a.flac") == "audio"
    assert probe.extension_kind("a.exe") is None
    assert probe.extension_kind("noext") is None


def test_video_accepted(fake_ffprobe):
    fake_ffprobe(duration=12.5)
    assert probe.probe_media("clip.mp4") == {
        "kind": "video", "duration": 12.5, "width": 1920, "height": 1080,
        "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
    }


def test_video_without_audio(fake_ffprobe):
    fake_ffprobe(has_audio=False)
    info = probe.probe_media("clip.mp4")
    assert info["has_audio"] is False and info["audio_codec"] is None


@pytest.mark.parametrize("kwargs,name,code", [
    ({}, "x.exe", "unsupported_type"),
    ({"kind": "audio"}, "x.mp4", "no_video_stream"),
    ({"kind": "audio", "attached_pic": True}, "x.mp4", "no_video_stream"),
    ({"vcodec": "prores"}, "x.mov", "codec_unsupported"),
    ({"duration": 0}, "x.mp4", "zero_duration"),
    ({"duration": 1801}, "x.mp4", "too_long"),
    ({"width": 7681}, "x.mp4", "too_big_dimensions"),
    ({"height": 7681}, "x.mp4", "too_big_dimensions"),
])
def test_video_rejections(fake_ffprobe, kwargs, name, code):
    fake_ffprobe(**kwargs)
    with pytest.raises(probe.MediaRejected) as exc:
        probe.probe_media(name)
    assert exc.value.code == code


def test_video_audio_codec_is_not_checked(fake_ffprobe):
    fake_ffprobe(acodec="wmav2")
    assert probe.probe_media("clip.mp4")["kind"] == "video"


def test_audio_accepted(fake_ffprobe):
    fake_ffprobe(kind="audio", duration=95.0, acodec="mp3")
    info = probe.probe_media("bed.mp3")
    assert info == {"kind": "audio", "duration": 95.0, "width": None, "height": None,
                    "has_audio": True, "video_codec": None, "audio_codec": "mp3"}


def test_audio_with_cover_art_accepted(fake_ffprobe):
    fake_ffprobe(kind="audio", attached_pic=True)
    assert probe.probe_media("bed.m4a")["kind"] == "audio"


def test_audio_rejections(fake_ffprobe):
    fake_ffprobe(kind="video", has_audio=False)
    with pytest.raises(probe.MediaRejected) as exc:
        probe.probe_media("bed.mp3")
    assert exc.value.code == "no_audio_stream"
    fake_ffprobe(kind="audio", acodec="wmav2")
    with pytest.raises(probe.MediaRejected) as exc:
        probe.probe_media("bed.mp3")
    assert exc.value.code == "codec_unsupported"


def test_name_overrides_path_for_extension(fake_ffprobe):
    fake_ffprobe()
    assert probe.probe_media(Path("x.part"), name="clip.mp4")["kind"] == "video"


def test_run_ffprobe_nonzero_is_unreadable(monkeypatch):
    monkeypatch.setattr(probe, "ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(probe.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="bad"))
    with pytest.raises(probe.MediaRejected) as exc:
        probe._run_ffprobe(Path("x.mp4"))
    assert exc.value.code == "unreadable"


def test_run_ffprobe_bad_json_is_unreadable(monkeypatch):
    monkeypatch.setattr(probe, "ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(probe.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="not json", stderr=""))
    with pytest.raises(probe.MediaRejected) as exc:
        probe._run_ffprobe(Path("x.mp4"))
    assert exc.value.code == "unreadable"


def test_run_ffprobe_missing_tool(monkeypatch):
    monkeypatch.setattr(probe, "ffprobe_path", lambda: None)
    with pytest.raises(probe.MediaRejected) as exc:
        probe._run_ffprobe(Path("x.mp4"))
    assert exc.value.code == "tools_missing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/demo_media/test_probe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'demo_media_probe'`.

- [ ] **Step 3: Write the implementation**

`web/demo_media_probe.py`:

```python
"""Validate user-supplied video/audio before it reaches ffmpeg."""

import json
import subprocess
from pathlib import Path

from proc_utils import no_window_kwargs

VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")
VIDEO_CODECS = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}
AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "pcm_f32le"}
MAX_FILE_BYTES = 2 * 1024**3
MAX_CLIP_SECONDS = 1800
MAX_VIDEO_CLIPS = 8
MAX_AUDIO_ASSETS = 4
MAX_DIMENSION = 7680


class MediaRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def extension_kind(name: str) -> str | None:
    ext = Path(str(name)).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def ffprobe_path() -> str | None:
    from routes.recorder import _find_ffprobe

    return _find_ffprobe()


def _run_ffprobe(path: Path) -> dict:
    exe = ffprobe_path()
    if not exe:
        raise MediaRejected("tools_missing", "ffprobe was not found. Install ffmpeg and try again.")
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, **no_window_kwargs(),
        )
    except subprocess.TimeoutExpired:
        raise MediaRejected("unreadable", "That file could not be read as media.") from None
    if proc.returncode != 0:
        raise MediaRejected("unreadable", "That file could not be read as media.")
    try:
        return json.loads(proc.stdout or "{}")
    except ValueError:
        raise MediaRejected("unreadable", "That file could not be read as media.") from None


def probe_media(path, name: str | None = None) -> dict:
    kind = extension_kind(name or str(path))
    if kind is None:
        raise MediaRejected(
            "unsupported_type",
            "Supported video: " + ", ".join(VIDEO_EXTS) + ". Supported audio: " + ", ".join(AUDIO_EXTS) + ".",
        )
    data = _run_ffprobe(Path(path))
    streams = data.get("streams") or []
    video = next(
        (s for s in streams
         if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    if kind == "video":
        if video is None:
            raise MediaRejected("no_video_stream", "That file has no video stream.")
        if video.get("codec_name") not in VIDEO_CODECS:
            raise MediaRejected("codec_unsupported", f"Video codec '{video.get('codec_name')}' is not supported.")
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            raise MediaRejected("too_big_dimensions", f"Video is larger than {MAX_DIMENSION}px on a side.")
    else:
        if audio is None:
            raise MediaRejected("no_audio_stream", "That file has no audio stream.")
        if audio.get("codec_name") not in AUDIO_CODECS:
            raise MediaRejected("codec_unsupported", f"Audio codec '{audio.get('codec_name')}' is not supported.")
        width = height = None

    if duration <= 0:
        raise MediaRejected("zero_duration", "That file has no playable duration.")
    if duration > MAX_CLIP_SECONDS:
        raise MediaRejected("too_long", f"Files longer than {MAX_CLIP_SECONDS // 60} minutes are not supported.")

    return {
        "kind": kind,
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name") if kind == "video" else None,
        "audio_codec": audio.get("codec_name") if audio is not None else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/demo_media/test_probe.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add web/demo_media_probe.py tests/demo_media/__init__.py tests/demo_media/conftest.py tests/demo_media/test_probe.py
git commit -m "feat: validate attached video/audio with an ffprobe allow-list"
```

---

### Task 2: Clip registry

**Files:**
- Create: `web/demo_clips.py`
- Test: `tests/demo_media/test_clips.py`

**Interfaces:**
- Consumes: `demo_projects` (`get_project`, `project_path`, `set_ext`), `demo_media_probe.MAX_VIDEO_CLIPS`, `MAX_AUDIO_ASSETS`.
- Produces (in `demo_clips`): `NAMESPACE = "clips"`, `SPEC_VERSION = 1`, `MAX_FRAMES = 8`, `MIN_FRAME_GAP = 5.0`, `MIN_CLIP_SECONDS = 0.5`, `LOCKED_STAGES = ("narration_approved", "delivered")`; `class ClipError(Exception)` with `.code`, `.message`; `safe_name(name: str) -> str`; `load(pid) -> dict`; `add_item(pid, tmp_path: Path, original_name: str, probe: dict) -> dict`; `remove_item(pid, item_id: str) -> None`; `reorder(pid, ids: list[str]) -> None`; `set_trim(pid, clip_id: str, start: float, end: float | None) -> None`; `effective_duration(clip: dict) -> float`; `fingerprint(pid, reg: dict) -> str`; `frame_times(durations: list[float]) -> list[float]`; `set_timeline(pid, **fields) -> dict`; `abs_path(pid, rel: str) -> Path`.

- [ ] **Step 1: Write the failing tests**

`tests/demo_media/test_clips.py`:

```python
import pytest

import demo_clips as clips


def _probe(kind="video", duration=10.0):
    video = kind == "video"
    return {"kind": kind, "duration": duration, "width": 1920 if video else None,
            "height": 1080 if video else None, "has_audio": True,
            "video_codec": "h264" if video else None, "audio_codec": "aac"}


@pytest.fixture
def pid(store):
    return store.create_project()["project_id"]


def _add(store, pid, name, kind="video", duration=10.0):
    part = store.project_path(pid) / "source" / f".upload_{name}.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"data-" + name.encode())
    return clips.add_item(pid, part, name, _probe(kind, duration))


def test_load_blank_registry(pid):
    reg = clips.load(pid)
    assert reg["clips"] == [] and reg["audio"] == []
    assert reg["timeline"]["state"] == "idle"


def test_add_video_and_audio(store, pid):
    c = _add(store, pid, "intro.mp4")
    a = _add(store, pid, "bed.mp3", kind="audio", duration=95.0)
    assert c["id"] == "c1" and c["file"] == "source/c1_intro.mp4"
    assert c["trim_start"] == 0.0 and c["trim_end"] is None and c["width"] == 1920
    assert a["id"] == "a2" and a["file"] == "source/a2_bed.mp3" and "trim_start" not in a
    assert clips.abs_path(pid, c["file"]).is_file()
    stored = store.get_project(pid)["ext"]["clips"]
    assert [x["id"] for x in stored["clips"]] == ["c1"] and [x["id"] for x in stored["audio"]] == ["a2"]


def test_safe_name_strips_unsafe_characters():
    assert clips.safe_name("my demo (v2).mp4") == "my_demo_v2_.mp4"
    assert clips.safe_name("../../evil.mp4") == "evil.mp4"
    assert len(clips.safe_name("a" * 200 + ".mp4")) == 80


def test_clip_limit(store, pid):
    for i in range(8):
        _add(store, pid, f"c{i}.mp4")
    with pytest.raises(clips.ClipError) as exc:
        _add(store, pid, "ninth.mp4")
    assert exc.value.code == "too_many"


def test_audio_limit(store, pid):
    for i in range(4):
        _add(store, pid, f"a{i}.mp3", kind="audio")
    with pytest.raises(clips.ClipError) as exc:
        _add(store, pid, "fifth.mp3", kind="audio")
    assert exc.value.code == "too_many"


def test_ids_are_not_reused(store, pid):
    _add(store, pid, "a.mp4")
    clips.remove_item(pid, "c1")
    assert _add(store, pid, "b.mp4")["id"] == "c2"


def test_remove_deletes_file_and_entry(store, pid):
    c = _add(store, pid, "a.mp4")
    path = clips.abs_path(pid, c["file"])
    clips.remove_item(pid, "c1")
    assert not path.exists() and clips.load(pid)["clips"] == []
    with pytest.raises(clips.ClipError) as exc:
        clips.remove_item(pid, "c1")
    assert exc.value.code == "not_found"


def test_reorder(store, pid):
    _add(store, pid, "a.mp4")
    _add(store, pid, "b.mp4")
    clips.reorder(pid, ["c2", "c1"])
    assert [c["id"] for c in clips.load(pid)["clips"]] == ["c2", "c1"]


@pytest.mark.parametrize("ids", [["c1"], ["c1", "c1"], ["c1", "c3"], ["c1", "c2", "c3"]])
def test_reorder_rejects_non_permutation(store, pid, ids):
    _add(store, pid, "a.mp4")
    _add(store, pid, "b.mp4")
    with pytest.raises(clips.ClipError) as exc:
        clips.reorder(pid, ids)
    assert exc.value.code == "bad_order"


def test_set_trim(store, pid):
    _add(store, pid, "a.mp4", duration=10.0)
    clips.set_trim(pid, "c1", 1.0, 9.5)
    c = clips.load(pid)["clips"][0]
    assert (c["trim_start"], c["trim_end"]) == (1.0, 9.5)
    assert clips.effective_duration(c) == 8.5
    clips.set_trim(pid, "c1", 2.0, None)
    c = clips.load(pid)["clips"][0]
    assert c["trim_end"] is None and clips.effective_duration(c) == 8.0


@pytest.mark.parametrize("start,end", [(-1, None), (5, 4), (0, 11), (0, 0.2), (9.9, None)])
def test_set_trim_rejects_bad_ranges(store, pid, start, end):
    _add(store, pid, "a.mp4", duration=10.0)
    with pytest.raises(clips.ClipError) as exc:
        clips.set_trim(pid, "c1", start, end)
    assert exc.value.code == "bad_trim"


def test_set_trim_unknown_clip(store, pid):
    with pytest.raises(clips.ClipError) as exc:
        clips.set_trim(pid, "c9", 0, None)
    assert exc.value.code == "not_found"


def test_locked_stage_blocks_mutations(store, pid):
    _add(store, pid, "a.mp4")
    store.update_project(pid, stage="narration_approved")
    for call in (
        lambda: _add(store, pid, "b.mp4"),
        lambda: clips.remove_item(pid, "c1"),
        lambda: clips.reorder(pid, ["c1"]),
        lambda: clips.set_trim(pid, "c1", 0, None),
    ):
        with pytest.raises(clips.ClipError) as exc:
            call()
        assert exc.value.code == "project_locked"


def test_set_timeline_works_when_locked(store, pid):
    _add(store, pid, "a.mp4")
    store.update_project(pid, stage="delivered")
    clips.set_timeline(pid, state="ready")
    assert clips.load(pid)["timeline"]["state"] == "ready"


def test_fingerprint_tracks_order_trim_and_audio(store, pid):
    _add(store, pid, "a.mp4")
    _add(store, pid, "b.mp4")
    base = clips.fingerprint(pid, clips.load(pid))
    assert base == clips.fingerprint(pid, clips.load(pid))
    clips.reorder(pid, ["c2", "c1"])
    swapped = clips.fingerprint(pid, clips.load(pid))
    assert swapped != base
    clips.set_trim(pid, "c1", 1.0, None)
    trimmed = clips.fingerprint(pid, clips.load(pid))
    assert trimmed != swapped
    _add(store, pid, "bed.mp3", kind="audio")
    assert clips.fingerprint(pid, clips.load(pid)) != trimmed


def test_frame_times_examples():
    assert clips.frame_times([10, 20]) == [2.5, 7.5, 12.5, 17.5, 22.5, 27.5]
    assert clips.frame_times([3.0]) == [1.5]
    assert clips.frame_times([]) == []
    long = clips.frame_times([100])
    assert len(long) == 8 and long[-1] == 93.75
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/demo_media/test_clips.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'demo_clips'`.

- [ ] **Step 3: Write the implementation**

`web/demo_clips.py`:

```python
"""Clip registry for multi-clip demo projects, stored in project.json ext["clips"]."""

import copy
import hashlib
import json
import os
import re
import threading
from pathlib import Path

import demo_projects as dp
from demo_media_probe import MAX_AUDIO_ASSETS, MAX_VIDEO_CLIPS

NAMESPACE = "clips"
SPEC_VERSION = 1
MAX_FRAMES = 8
MIN_FRAME_GAP = 5.0
MIN_CLIP_SECONDS = 0.5
LOCKED_STAGES = ("narration_approved", "delivered")

_LOCK = threading.RLock()


class ClipError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(str(name)).name)
    stem, ext = os.path.splitext(base)
    return stem[: max(1, 80 - len(ext))] + ext


def _blank() -> dict:
    return {
        "version": SPEC_VERSION, "next_id": 1, "clips": [], "audio": [],
        "timeline": {"state": "idle", "fingerprint": None, "file": None, "soundtrack": None,
                     "duration": 0.0, "clips": [], "frame_times": [], "error": None},
    }


def load(pid: str) -> dict:
    stored = dp.get_project(pid).get("ext", {}).get(NAMESPACE)
    return copy.deepcopy(stored) if stored else _blank()


def abs_path(pid: str, rel: str) -> Path:
    return dp.project_path(pid) / rel


def _assert_unlocked(pid: str) -> None:
    if dp.get_project(pid)["stage"] in LOCKED_STAGES:
        raise ClipError("project_locked", "This demo's narration is already approved. Start a new demo to change clips.")


def _find(reg: dict, item_id: str):
    for bucket in ("clips", "audio"):
        for index, item in enumerate(reg[bucket]):
            if item["id"] == item_id:
                return bucket, index
    raise ClipError("not_found", "No such clip or audio file in this project.")


def add_item(pid: str, tmp_path: Path, original_name: str, probe: dict) -> dict:
    with _LOCK:
        _assert_unlocked(pid)
        reg = load(pid)
        is_video = probe["kind"] == "video"
        bucket = reg["clips" if is_video else "audio"]
        limit = MAX_VIDEO_CLIPS if is_video else MAX_AUDIO_ASSETS
        if len(bucket) >= limit:
            raise ClipError("too_many", f"At most {limit} {'video clips' if is_video else 'audio files'} per demo.")
        item_id = f"{'c' if is_video else 'a'}{reg['next_id']}"
        reg["next_id"] += 1
        rel = f"source/{item_id}_{safe_name(original_name)}"
        dest = abs_path(pid, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, dest)
        item = {"id": item_id, "name": Path(original_name).name, "file": rel, "duration": probe["duration"]}
        if is_video:
            item.update(width=probe["width"], height=probe["height"], has_audio=probe["has_audio"],
                        trim_start=0.0, trim_end=None)
        bucket.append(item)
        dp.set_ext(pid, NAMESPACE, reg)
        return item


def remove_item(pid: str, item_id: str) -> None:
    with _LOCK:
        _assert_unlocked(pid)
        reg = load(pid)
        bucket, index = _find(reg, item_id)
        item = reg[bucket].pop(index)
        abs_path(pid, item["file"]).unlink(missing_ok=True)
        dp.set_ext(pid, NAMESPACE, reg)


def reorder(pid: str, ids: list) -> None:
    with _LOCK:
        _assert_unlocked(pid)
        reg = load(pid)
        current = [c["id"] for c in reg["clips"]]
        if len(ids) != len(current) or set(ids) != set(current):
            raise ClipError("bad_order", "The order must list every clip exactly once.")
        by_id = {c["id"]: c for c in reg["clips"]}
        reg["clips"] = [by_id[i] for i in ids]
        dp.set_ext(pid, NAMESPACE, reg)


def effective_duration(clip: dict) -> float:
    end = clip["duration"] if clip["trim_end"] is None else clip["trim_end"]
    return max(0.0, end - clip["trim_start"])


def set_trim(pid: str, clip_id: str, start: float, end: float | None) -> None:
    with _LOCK:
        _assert_unlocked(pid)
        reg = load(pid)
        bucket, index = _find(reg, clip_id)
        if bucket != "clips":
            raise ClipError("not_found", "Only video clips can be trimmed.")
        clip = reg["clips"][index]
        effective_end = clip["duration"] if end is None else end
        if start < 0 or effective_end > clip["duration"] + 0.001 or effective_end - start < MIN_CLIP_SECONDS:
            raise ClipError("bad_trim", f"Pick a range inside 0-{clip['duration']:.1f}s, at least {MIN_CLIP_SECONDS}s long.")
        clip["trim_start"] = round(float(start), 3)
        clip["trim_end"] = None if end is None else round(float(end), 3)
        dp.set_ext(pid, NAMESPACE, reg)


def set_timeline(pid: str, **fields) -> dict:
    with _LOCK:
        reg = load(pid)
        reg["timeline"].update(fields)
        dp.set_ext(pid, NAMESPACE, reg)
        return reg


def fingerprint(pid: str, reg: dict) -> str:
    parts: list = [SPEC_VERSION]
    for clip in reg["clips"]:
        stat = abs_path(pid, clip["file"]).stat()
        parts.append([clip["id"], stat.st_size, stat.st_mtime_ns, clip["trim_start"], clip["trim_end"]])
    for audio in reg["audio"]:
        stat = abs_path(pid, audio["file"]).stat()
        parts.append(["audio", audio["id"], stat.st_size, stat.st_mtime_ns])
    return hashlib.sha1(json.dumps(parts).encode("utf-8")).hexdigest()


def frame_times(durations: list) -> list:
    total = sum(durations)
    if total <= 0:
        return []
    count = min(MAX_FRAMES, max(1, int(total // MIN_FRAME_GAP)))
    return [round((i + 0.5) * total / count, 3) for i in range(count)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/demo_media/test_clips.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add web/demo_clips.py tests/demo_media/test_clips.py
git commit -m "feat: add clip registry for multi-clip demo projects"
```

---

### Task 3: Compose argv builders

**Files:**
- Create: `web/demo_compose.py` (pure builders only in this task)
- Test: `tests/demo_media/test_compose.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (in `demo_compose`): `TARGET_FPS = 30`, `MAX_OUT_W = 1920`, `MAX_OUT_H = 1080`, `AUDIO_RATE = 48000`; `canvas_size(clips: list[dict]) -> tuple[int, int]` (uses the first clip's `width`/`height`); `video_filter(w: int, h: int) -> str`; `normalize_argv(ffmpeg, src: Path, dst: Path, start: float, length: float, w: int, h: int) -> list[str]`; `normalized_name(clip: dict, src: Path, w: int, h: int) -> str`; `concat_list_text(files: list[Path]) -> str`; `concat_argv(ffmpeg, list_file: Path, dst: Path) -> list[str]`; `soundtrack_argv(ffmpeg, srcs: list[Path], dst: Path) -> list[str]`. Every argv ends with `dst`.

- [ ] **Step 1: Write the failing tests**

`tests/demo_media/test_compose.py`:

```python
from pathlib import Path

import demo_compose as compose

FILTER_720 = (
    "scale=1280:720:force_original_aspect_ratio=decrease,"
    "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
)


def test_canvas_size_scales_down_and_rounds_even():
    assert compose.canvas_size([{"width": 3840, "height": 2160}]) == (1920, 1080)
    assert compose.canvas_size([{"width": 1280, "height": 720}]) == (1280, 720)
    assert compose.canvas_size([{"width": 1001, "height": 501}]) == (1000, 500)
    assert compose.canvas_size([{"width": 1080, "height": 1920}]) == (606, 1080)


def test_canvas_uses_first_clip_only():
    clips = [{"width": 1280, "height": 720}, {"width": 3840, "height": 2160}]
    assert compose.canvas_size(clips) == (1280, 720)


def test_video_filter():
    assert compose.video_filter(1280, 720) == FILTER_720


def test_normalize_argv():
    argv = compose.normalize_argv("ff", Path("a.mp4"), Path("n.mp4"), 1.5, 8.0, 1280, 720)
    assert argv == ["ff", "-y", "-ss", "1.5", "-t", "8.0", "-i", "a.mp4", "-an", "-vf", FILTER_720,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "n.mp4"]


def test_normalized_name_depends_on_trim_and_canvas(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    base = {"id": "c1", "trim_start": 0.0, "trim_end": None}
    name = compose.normalized_name(base, src, 1280, 720)
    assert name.startswith("c1_") and name.endswith(".mp4") and len(name) == len("c1_") + 8 + len(".mp4")
    assert name == compose.normalized_name(dict(base), src, 1280, 720)
    assert name != compose.normalized_name({**base, "trim_start": 1.0}, src, 1280, 720)
    assert name != compose.normalized_name(base, src, 640, 360)


def test_concat_list_text_escapes_quotes():
    text = compose.concat_list_text([Path("a.mp4"), Path("it's.mp4")])
    assert text == "file 'a.mp4'\nfile 'it'\\''s.mp4'\n"


def test_concat_argv():
    assert compose.concat_argv("ff", Path("list.txt"), Path("t.mp4")) == [
        "ff", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy",
        "-movflags", "+faststart", "t.mp4"]


def test_soundtrack_argv():
    argv = compose.soundtrack_argv("ff", [Path("a.mp3"), Path("b.wav")], Path("s.m4a"))
    assert argv == [
        "ff", "-y", "-i", "a.mp3", "-i", "b.wav", "-filter_complex",
        "[0:a]aresample=48000,aformat=channel_layouts=stereo[a0];"
        "[1:a]aresample=48000,aformat=channel_layouts=stereo[a1];"
        "[a0][a1]concat=n=2:v=0:a=1[a]",
        "-map", "[a]", "-c:a", "aac", "-b:a", "128k", "s.m4a"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/demo_media/test_compose.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'demo_compose'`.

- [ ] **Step 3: Write the implementation**

`web/demo_compose.py`:

```python
"""Combine imported clips into one normalized timeline with ffmpeg."""

import hashlib
import json
from pathlib import Path

from demo_clips import SPEC_VERSION

TARGET_FPS = 30
MAX_OUT_W = 1920
MAX_OUT_H = 1080
AUDIO_RATE = 48000


def canvas_size(clips: list) -> tuple:
    width, height = clips[0]["width"], clips[0]["height"]
    scale = min(1.0, MAX_OUT_W / width, MAX_OUT_H / height)
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def video_filter(w: int, h: int) -> str:
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={TARGET_FPS},format=yuv420p"
    )


def normalize_argv(ffmpeg, src: Path, dst: Path, start: float, length: float, w: int, h: int) -> list:
    return [str(ffmpeg), "-y", "-ss", str(start), "-t", str(length), "-i", str(src), "-an",
            "-vf", video_filter(w, h), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(dst)]


def normalized_name(clip: dict, src: Path, w: int, h: int) -> str:
    stat = Path(src).stat()
    key = json.dumps([SPEC_VERSION, stat.st_size, stat.st_mtime_ns,
                      clip["trim_start"], clip["trim_end"], w, h])
    return f"{clip['id']}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}.mp4"


def concat_list_text(files: list) -> str:
    return "".join("file '" + Path(f).as_posix().replace("'", "'\\''") + "'\n" for f in files)


def concat_argv(ffmpeg, list_file: Path, dst: Path) -> list:
    return [str(ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart", str(dst)]


def soundtrack_argv(ffmpeg, srcs: list, dst: Path) -> list:
    argv = [str(ffmpeg), "-y"]
    for src in srcs:
        argv += ["-i", str(src)]
    legs = [f"[{i}:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo[a{i}]" for i in range(len(srcs))]
    joined = "".join(f"[a{i}]" for i in range(len(srcs)))
    graph = ";".join(legs) + f";{joined}concat=n={len(srcs)}:v=0:a=1[a]"
    return argv + ["-filter_complex", graph, "-map", "[a]", "-c:a", "aac", "-b:a", "128k", str(dst)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/demo_media/test_compose.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add web/demo_compose.py tests/demo_media/test_compose.py
git commit -m "feat: add ffmpeg argv builders for multi-clip timelines"
```

### Task 4: Timeline build and scheduler

**Files:**
- Modify: `web/demo_compose.py` (imports, then append the build and scheduler code)
- Test: `tests/demo_media/test_build.py`

**Interfaces:**
- Consumes (Task 2, `demo_clips`): `load`, `abs_path`, `fingerprint`, `effective_duration`, `frame_times`, `set_timeline`, `_LOCK`. Consumes (Task 3): `canvas_size`, `normalize_argv`, `normalized_name`, `concat_list_text`, `concat_argv`, `soundtrack_argv`. Consumes (SP3, `demo_projects`): `project_path`, `get_project`, `update_project`.
- Produces (in `demo_compose`): `ComposeError(Exception)`; `TIMELINE_REL = "work/timeline.mp4"`; `SOUNDTRACK_REL = "work/soundtrack.m4a"`; `_ffmpeg() -> str | None`; `_run(argv: list[str]) -> None` (raises `ComposeError` with the last 400 characters of stderr); `build(pid: str) -> str` returning one of `"idle"`, `"ready"`, `"failed"`, `"superseded"`; `schedule(pid: str) -> None`; `ensure_current(pid: str) -> None`.
- `schedule` never blocks: one background worker runs `build` and repeats while another `schedule` call arrived during a build or the build reported `"superseded"`.

- [ ] **Step 1: Write the failing tests**

`tests/demo_media/test_build.py`:

```python
from pathlib import Path

import pytest

import demo_clips as clips
import demo_compose as compose


class _Inline:
    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture
def env(store, tmp_path, monkeypatch):
    calls = []

    def fake_run(argv):
        calls.append(list(argv))
        Path(argv[-1]).write_bytes(b"out")

    monkeypatch.setattr(compose, "_ffmpeg", lambda: "ff")
    monkeypatch.setattr(compose, "_run", fake_run)
    monkeypatch.setattr(compose, "_EXECUTOR", _Inline())
    pid = store.create_project(name="Demo")["project_id"]
    return store, pid, calls, tmp_path


def _add(pid, tmp_path, name, kind="video", duration=10.0):
    tmp = tmp_path / f"upload_{name}"
    tmp.write_bytes(b"x" * 10)
    probe = {"kind": kind, "duration": duration, "width": 1280, "height": 720, "has_audio": True}
    return clips.add_item(pid, tmp, name, probe)


def test_build_with_no_clips_resets_to_idle(env):
    store, pid, calls, tmp_path = env
    assert compose.build(pid) == "idle"
    assert clips.load(pid)["timeline"]["state"] == "idle"
    assert calls == []


def test_build_publishes_timeline_and_raw(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4", duration=10.0)
    _add(pid, tmp_path, "b.mp4", duration=20.0)
    assert compose.build(pid) == "ready"
    tl = clips.load(pid)["timeline"]
    assert tl["state"] == "ready" and tl["file"] == "work/timeline.mp4"
    assert tl["duration"] == 30.0 and tl["soundtrack"] is None and tl["error"] is None
    assert [c["id"] for c in tl["clips"]] == ["c1", "c2"]
    assert (tl["clips"][1]["start"], tl["clips"][1]["end"]) == (10.0, 30.0)
    assert tl["frame_times"] == [2.5, 7.5, 12.5, 17.5, 22.5, 27.5]
    project = store.get_project(pid)
    assert (Path(project["path"]) / "work" / "timeline.mp4").read_bytes() == b"out"
    assert project["raw"] == str(Path(project["path"]) / "work" / "timeline.mp4")
    assert project["stage"] == "recorded"
    assert calls[-1][:4] == ["ff", "-y", "-f", "concat"]
    assert sum(1 for argv in calls if "-ss" in argv) == 2


def test_build_keeps_a_later_stage(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    store.update_project(pid, stage="recording")
    compose.build(pid)
    assert store.get_project(pid)["stage"] == "recording"


def test_second_build_is_cached(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    compose.build(pid)
    count = len(calls)
    assert compose.build(pid) == "ready"
    assert len(calls) == count


def test_trim_change_rebuilds_and_removes_stale_normalized(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    compose.build(pid)
    norm = Path(store.get_project(pid)["path"]) / "work" / "normalized"
    before = {p.name for p in norm.iterdir()}
    clips.set_trim(pid, "c1", 1.0, 6.0)
    assert compose.build(pid) == "ready"
    after = {p.name for p in norm.iterdir()}
    assert len(after) == 1 and after != before
    assert clips.load(pid)["timeline"]["duration"] == 5.0


def test_audio_builds_soundtrack_and_removal_deletes_it(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    audio = _add(pid, tmp_path, "m.mp3", kind="audio", duration=40.0)
    compose.build(pid)
    folder = Path(store.get_project(pid)["path"])
    assert clips.load(pid)["timeline"]["soundtrack"] == "work/soundtrack.m4a"
    assert (folder / "work" / "soundtrack.m4a").exists()
    clips.remove_item(pid, audio["id"])
    compose.build(pid)
    assert clips.load(pid)["timeline"]["soundtrack"] is None
    assert not (folder / "work" / "soundtrack.m4a").exists()


def test_failure_records_error_and_is_not_retried_until_inputs_change(env, monkeypatch):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")

    def boom(argv):
        raise compose.ComposeError("Invalid data found")

    monkeypatch.setattr(compose, "_run", boom)
    assert compose.build(pid) == "failed"
    tl = clips.load(pid)["timeline"]
    assert tl["state"] == "failed" and "Invalid data" in tl["error"]

    scheduled = []
    monkeypatch.setattr(compose, "schedule", scheduled.append)
    compose.ensure_current(pid)
    assert scheduled == []
    clips.set_trim(pid, "c1", 0.0, 5.0)
    compose.ensure_current(pid)
    assert scheduled == [pid]


def test_missing_ffmpeg_fails_the_build(env, monkeypatch):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    monkeypatch.setattr(compose, "_ffmpeg", lambda: None)
    assert compose.build(pid) == "failed"
    assert "ffmpeg" in clips.load(pid)["timeline"]["error"].lower()


def test_edit_during_build_is_superseded_then_rebuilt(env, monkeypatch):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    fired = []

    def edit_midway(argv):
        calls.append(list(argv))
        Path(argv[-1]).write_bytes(b"out")
        if not fired:
            fired.append(True)
            clips.set_trim(pid, "c1", 0.0, 4.0)

    monkeypatch.setattr(compose, "_run", edit_midway)
    assert compose.build(pid) == "superseded"
    assert clips.load(pid)["timeline"]["state"] == "building"

    compose.schedule(pid)
    tl = clips.load(pid)["timeline"]
    assert tl["state"] == "ready" and tl["duration"] == 4.0


def test_schedule_while_inflight_only_marks_dirty(env, monkeypatch):
    store, pid, calls, tmp_path = env
    submitted = []
    monkeypatch.setattr(compose, "_EXECUTOR", type("E", (), {"submit": lambda self, fn, *a: submitted.append(a)})())
    compose._inflight.add(pid)
    try:
        compose.schedule(pid)
        assert submitted == [] and pid in compose._dirty
    finally:
        compose._inflight.discard(pid)
        compose._dirty.discard(pid)


def test_ensure_current_schedules_a_stuck_building_state(env, monkeypatch):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    clips.set_timeline(pid, state="building")
    scheduled = []
    monkeypatch.setattr(compose, "schedule", scheduled.append)
    compose.ensure_current(pid)
    assert scheduled == [pid]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/demo_media/test_build.py -v`
Expected: FAIL with `AttributeError: module 'demo_compose' has no attribute 'ComposeError'` (or `_ffmpeg`).

- [ ] **Step 3: Write the implementation**

In `web/demo_compose.py` replace the import block at the top with:

```python
import hashlib
import json
import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import demo_clips as clips_mod
import demo_projects as dp
from demo_clips import SPEC_VERSION
from proc_utils import no_window_kwargs

log = logging.getLogger(__name__)
```

Append to the end of `web/demo_compose.py`:

```python
TIMELINE_REL = "work/timeline.mp4"
SOUNDTRACK_REL = "work/soundtrack.m4a"
RUN_TIMEOUT_SECONDS = 1800


class ComposeError(Exception):
    pass


def _ffmpeg():
    from routes.recorder import _find_ffmpeg
    return _find_ffmpeg()


def _run(argv: list) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                          timeout=RUN_TIMEOUT_SECONDS, **no_window_kwargs())
    if proc.returncode != 0:
        raise ComposeError((proc.stderr or "ffmpeg failed").strip()[-400:])


def _replace_via_part(final: Path, argv_builder) -> None:
    part = final.with_name(final.stem + ".part" + final.suffix)
    _run(argv_builder(part))
    os.replace(part, final)


def _compose(pid: str, reg: dict, ffmpeg: str) -> dict:
    folder = dp.project_path(pid)
    norm_dir = folder / "work" / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)
    width, height = canvas_size(reg["clips"])
    files, spans, cursor = [], [], 0.0
    for clip in reg["clips"]:
        src = clips_mod.abs_path(pid, clip["file"])
        dst = norm_dir / normalized_name(clip, src, width, height)
        length = clips_mod.effective_duration(clip)
        if not dst.exists():
            _replace_via_part(dst, lambda out, c=clip, s=src, n=length: normalize_argv(
                ffmpeg, s, out, c["trim_start"], n, width, height))
        files.append(dst)
        spans.append({"id": clip["id"], "name": clip["name"],
                      "start": round(cursor, 3), "end": round(cursor + length, 3), "length": length})
        cursor += length
    keep = {f.name for f in files}
    for stale in norm_dir.iterdir():
        if stale.name not in keep:
            stale.unlink(missing_ok=True)

    list_file = folder / "work" / "concat.txt"
    list_file.write_text(concat_list_text(files), encoding="utf-8")
    _replace_via_part(folder / TIMELINE_REL, lambda out: concat_argv(ffmpeg, list_file, out))

    soundtrack_final = folder / SOUNDTRACK_REL
    soundtrack = None
    if reg["audio"]:
        srcs = [clips_mod.abs_path(pid, a["file"]) for a in reg["audio"]]
        _replace_via_part(soundtrack_final, lambda out: soundtrack_argv(ffmpeg, srcs, out))
        soundtrack = SOUNDTRACK_REL
    else:
        soundtrack_final.unlink(missing_ok=True)

    return {"duration": round(cursor, 3), "soundtrack": soundtrack,
            "clips": [{k: s[k] for k in ("id", "name", "start", "end")} for s in spans],
            "frame_times": clips_mod.frame_times([s["length"] for s in spans])}


def build(pid: str) -> str:
    with clips_mod._LOCK:
        reg = clips_mod.load(pid)
        if not reg["clips"]:
            clips_mod.set_timeline(pid, state="idle", fingerprint=None, file=None, soundtrack=None,
                                   duration=0.0, clips=[], frame_times=[], error=None)
            return "idle"
        fp = clips_mod.fingerprint(pid, reg)
    tl = reg["timeline"]
    if tl["state"] == "ready" and tl["fingerprint"] == fp and clips_mod.abs_path(pid, tl["file"]).exists():
        return "ready"

    ffmpeg = _ffmpeg()
    if not ffmpeg:
        clips_mod.set_timeline(pid, state="failed", fingerprint=fp, error="ffmpeg was not found on this machine.")
        return "failed"

    clips_mod.set_timeline(pid, state="building", fingerprint=fp, error=None)
    try:
        result = _compose(pid, reg, ffmpeg)
    except (ComposeError, OSError, subprocess.SubprocessError) as exc:
        clips_mod.set_timeline(pid, state="failed", fingerprint=fp, error=str(exc)[-400:])
        return "failed"

    try:
        with clips_mod._LOCK:
            if clips_mod.fingerprint(pid, clips_mod.load(pid)) != fp:
                return "superseded"
            clips_mod.set_timeline(pid, state="ready", fingerprint=fp, file=TIMELINE_REL, error=None, **result)
    except OSError:
        return "superseded"

    fields = {"raw": dp.project_path(pid) / TIMELINE_REL}
    if dp.get_project(pid)["stage"] == "created":
        fields["stage"] = "recorded"
    dp.update_project(pid, **fields)
    return "ready"


_STATE = threading.Lock()
_inflight: set = set()
_dirty: set = set()
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="demo-compose")


def _mark_failed(pid: str, exc: Exception) -> None:
    try:
        clips_mod.set_timeline(pid, state="failed", error=str(exc)[-400:])
    except Exception:
        log.exception("could not record the compose failure for %s", pid)


def _job(pid: str) -> None:
    while True:
        try:
            outcome = build(pid)
        except Exception as exc:
            log.exception("demo timeline build crashed for %s", pid)
            _mark_failed(pid, exc)
            outcome = "failed"
        with _STATE:
            again = outcome == "superseded" or pid in _dirty
            _dirty.discard(pid)
            if not again:
                _inflight.discard(pid)
                return


def schedule(pid: str) -> None:
    with _STATE:
        if pid in _inflight:
            _dirty.add(pid)
            return
        _inflight.add(pid)
    _EXECUTOR.submit(_job, pid)


def ensure_current(pid: str) -> None:
    reg = clips_mod.load(pid)
    if not reg["clips"]:
        return
    tl = reg["timeline"]
    try:
        fp = clips_mod.fingerprint(pid, reg)
    except OSError:
        fp = None
    if fp is not None and tl["fingerprint"] == fp:
        if tl["state"] == "failed":
            return
        if tl["state"] == "ready" and tl["file"] and clips_mod.abs_path(pid, tl["file"]).exists():
            return
    schedule(pid)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/demo_media/test_build.py tests/demo_media/test_compose.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add web/demo_compose.py tests/demo_media/test_build.py
git commit -m "feat: build and schedule the combined timeline for multi-clip demos"
```

### Task 5: HTTP routes

**Files:**
- Create: `web/routes/demo_clips.py`
- Modify: `web/app.py` (import after line 92, include after line 881; line numbers are those on `main` today and shift, so locate `routes.recorder` instead)
- Test: `tests/demo_media/test_routes.py`

**Interfaces:**
- Consumes: `demo_clips` (`ClipError`, `LOCKED_STAGES`, `add_item`, `remove_item`, `reorder`, `set_trim`, `load`, `abs_path`), `demo_compose` (`schedule`, `ensure_current`), `demo_media_probe` (`MediaRejected`, `extension_kind`, `probe_media`, `MAX_FILE_BYTES`), `demo_projects` (`get_project`, `get_active_id`, `create_project`), `security.verify_csrf`.
- Produces (HTTP, prefix `/api/demo-media`): in every success body `clips` is the registry `{version, next_id, clips: [...], audio: [...], timeline: {...}}`. Errors are `{"ok": false, "code", "message"}`.
  - `POST /upload?filename=<name>[&project_id=<id>]` (raw body) returns `{ok, project_id, item, path, clips}` where `path` is the absolute saved file path.
  - `GET /{pid}` returns `{ok, project_id, name, stage, clips}` and calls `ensure_current`.
  - `PUT /{pid}/order` with `{"ids": [...]}`, `PATCH /{pid}/clips/{cid}` with `{"trim_start": float, "trim_end": float | null}`, `DELETE /{pid}/items/{iid}` each return `{ok, clips}` and call `schedule`.
- Status codes by error code: `unsupported_type` 415, `too_large` 413, `project_locked` 409, `too_many` 409, `not_found` 404, `tools_missing` 503, everything else 422.

- [ ] **Step 1: Write the failing tests**

`tests/demo_media/test_routes.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import demo_compose as compose
import demo_media_probe as probe

BASE = "/api/demo-media"


@pytest.fixture
def client(store):
    from app import app
    from security import get_csrf_token

    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


@pytest.fixture
def scheduled(monkeypatch):
    calls = []
    monkeypatch.setattr(compose, "schedule", calls.append)
    return calls


def _upload(client, name="a.mp4", data=b"x" * 64, **params):
    return client.post(f"{BASE}/upload", params={"filename": name, **params}, content=data,
                       headers={"Content-Type": "application/octet-stream"})


def test_mutating_routes_require_csrf(store):
    from app import app

    bare = TestClient(app)
    assert bare.post(f"{BASE}/upload", params={"filename": "a.mp4"}, content=b"x").status_code == 403
    assert bare.put(f"{BASE}/p/order", json={"ids": []}).status_code == 403
    assert bare.patch(f"{BASE}/p/clips/c1", json={}).status_code == 403
    assert bare.delete(f"{BASE}/p/items/c1").status_code == 403


def test_upload_creates_project_and_registers_clip(client, store, fake_ffprobe, scheduled):
    fake_ffprobe(duration=12.0)
    res = _upload(client)
    assert res.status_code == 200
    body = res.json()
    pid = body["project_id"]
    folder = Path(store.get_project(pid)["path"])
    assert pid == store.get_active_id()
    assert body["item"]["id"] == "c1" and body["item"]["duration"] == 12.0
    saved = folder / "source" / "c1_a.mp4"
    assert body["path"] == str(saved) and saved.read_bytes() == b"x" * 64
    assert [c["id"] for c in body["clips"]["clips"]] == ["c1"]
    assert list((folder / "source").glob(".upload_*")) == []
    assert scheduled == [pid]


def test_second_upload_joins_the_same_project(client, store, fake_ffprobe, scheduled):
    fake_ffprobe()
    first = _upload(client).json()
    second = _upload(client, name="b.mp4").json()
    assert second["project_id"] == first["project_id"]
    assert second["item"]["id"] == "c2"


def test_audio_upload_lands_in_audio_list(client, fake_ffprobe, scheduled):
    fake_ffprobe(kind="audio", duration=60.0, acodec="mp3")
    body = _upload(client, name="bed.mp3").json()
    assert body["item"]["id"] == "a1"
    assert [a["id"] for a in body["clips"]["audio"]] == ["a1"] and body["clips"]["clips"] == []


def test_upload_starts_a_new_project_after_recording_began(client, store, fake_ffprobe, scheduled):
    fake_ffprobe()
    old = store.create_project()["project_id"]
    store.update_project(old, stage="recording")
    assert _upload(client).json()["project_id"] != old


def test_upload_adopts_an_untouched_created_project(client, store, fake_ffprobe, scheduled):
    fake_ffprobe()
    existing = store.create_project()["project_id"]
    assert _upload(client).json()["project_id"] == existing


def test_unsupported_extension_is_415(client, scheduled):
    res = _upload(client, name="notes.txt")
    assert res.status_code == 415 and res.json()["code"] == "unsupported_type"
    assert res.json()["ok"] is False and scheduled == []


def test_oversize_body_is_413_and_cleans_up(client, store, fake_ffprobe, scheduled, monkeypatch):
    fake_ffprobe()
    monkeypatch.setattr(probe, "MAX_FILE_BYTES", 10)
    pid = store.create_project()["project_id"]
    res = _upload(client, project_id=pid)
    assert res.status_code == 413 and res.json()["code"] == "too_large"
    source = Path(store.get_project(pid)["path"]) / "source"
    assert list(source.iterdir()) == []


def test_probe_rejection_is_422_and_cleans_up(client, store, fake_ffprobe, scheduled):
    fake_ffprobe(kind="audio")
    pid = store.create_project()["project_id"]
    res = _upload(client, name="x.mp4", project_id=pid)
    assert res.status_code == 422 and res.json()["code"] == "no_video_stream"
    assert list((Path(store.get_project(pid)["path"]) / "source").iterdir()) == []
    assert scheduled == []


def test_locked_project_is_409(client, store, fake_ffprobe, scheduled):
    fake_ffprobe()
    pid = store.create_project()["project_id"]
    store.update_project(pid, stage="narration_approved")
    res = _upload(client, project_id=pid)
    assert res.status_code == 409 and res.json()["code"] == "project_locked"
    assert client.delete(f"{BASE}/{pid}/items/c1").status_code == 409


def test_ninth_clip_is_409(client, fake_ffprobe, scheduled):
    fake_ffprobe()
    for i in range(8):
        assert _upload(client, name=f"c{i}.mp4").status_code == 200
    res = _upload(client, name="extra.mp4")
    assert res.status_code == 409 and res.json()["code"] == "too_many"


def test_get_unknown_project_is_404(client):
    res = client.get(f"{BASE}/demo_19990101_000000")
    assert res.status_code == 404 and res.json()["code"] == "not_found"


def test_get_returns_registry_and_reschedules(client, fake_ffprobe, scheduled):
    fake_ffprobe()
    pid = _upload(client).json()["project_id"]
    scheduled.clear()
    body = client.get(f"{BASE}/{pid}").json()
    assert body["ok"] is True and body["project_id"] == pid and body["stage"] == "created"
    assert [c["id"] for c in body["clips"]["clips"]] == ["c1"]
    assert scheduled == [pid]


def test_get_without_clips_does_not_schedule(client, store, scheduled):
    pid = store.create_project()["project_id"]
    assert client.get(f"{BASE}/{pid}").json()["clips"]["clips"] == []
    assert scheduled == []


def test_order_trim_and_delete(client, store, fake_ffprobe, scheduled):
    fake_ffprobe(duration=10.0)
    pid = _upload(client).json()["project_id"]
    _upload(client, name="b.mp4")
    scheduled.clear()

    res = client.put(f"{BASE}/{pid}/order", json={"ids": ["c2", "c1"]})
    assert [c["id"] for c in res.json()["clips"]["clips"]] == ["c2", "c1"]
    bad = client.put(f"{BASE}/{pid}/order", json={"ids": ["c1"]})
    assert bad.status_code == 422 and bad.json()["code"] == "bad_order"

    res = client.patch(f"{BASE}/{pid}/clips/c1", json={"trim_start": 1.0, "trim_end": 6.0})
    clip = next(c for c in res.json()["clips"]["clips"] if c["id"] == "c1")
    assert (clip["trim_start"], clip["trim_end"]) == (1.0, 6.0)
    bad = client.patch(f"{BASE}/{pid}/clips/c1", json={"trim_start": 5.0, "trim_end": 5.2})
    assert bad.status_code == 422 and bad.json()["code"] == "bad_trim"
    assert client.patch(f"{BASE}/{pid}/clips/zz", json={"trim_start": 0.0}).status_code == 404

    res = client.delete(f"{BASE}/{pid}/items/c2")
    assert [c["id"] for c in res.json()["clips"]["clips"]] == ["c1"]
    assert not (Path(store.get_project(pid)["path"]) / "source" / "c2_b.mp4").exists()
    assert client.delete(f"{BASE}/{pid}/items/c2").status_code == 404
    assert scheduled == [pid] * 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/demo_media/test_routes.py -v`
Expected: FAIL (404 responses from the unmounted `/api/demo-media` prefix, or a collection error).

- [ ] **Step 3: Write the routes and mount them**

`web/routes/demo_clips.py`:

```python
"""Import clips and audio into demo projects and edit the combined timeline."""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import demo_clips as clips
import demo_compose as compose
import demo_media_probe as probe
import demo_projects as dp
from security import verify_csrf

router = APIRouter(prefix="/api/demo-media")

_STATUS = {
    "unsupported_type": 415, "too_large": 413, "project_locked": 409, "too_many": 409,
    "not_found": 404, "tools_missing": 503,
}
_TOO_LARGE = "That file is larger than the 2 GB limit."


def _fail(code: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "code": code, "message": message}, status_code=_STATUS.get(code, 422))


def _locked_message() -> str:
    return "This demo's narration is already approved. Start a new demo to change clips."


def _target_project(project_id: Optional[str]) -> str:
    if project_id:
        try:
            project = dp.get_project(project_id)
        except KeyError:
            raise clips.ClipError("not_found", "No such demo project.") from None
        if project["stage"] in clips.LOCKED_STAGES:
            raise clips.ClipError("project_locked", _locked_message())
        return project_id
    active = dp.get_active_id()
    if active:
        try:
            project = dp.get_project(active)
        except KeyError:
            project = None
        if project and project["stage"] not in clips.LOCKED_STAGES:
            reg = clips.load(active)
            if project["stage"] == "created" or reg["clips"] or reg["audio"]:
                return active
    return dp.create_project()["project_id"]


@router.post("/upload", dependencies=[Depends(verify_csrf)])
async def upload(request: Request, filename: str = Query(...), project_id: Optional[str] = Query(None)):
    part = None
    try:
        if probe.extension_kind(filename) is None:
            probe.probe_media(filename)
        if int(request.headers.get("content-length") or 0) > probe.MAX_FILE_BYTES:
            raise probe.MediaRejected("too_large", _TOO_LARGE)
        pid = await asyncio.to_thread(_target_project, project_id)
        part = clips.abs_path(pid, "source") / f".upload_{uuid.uuid4().hex}.part"
        part.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with open(part, "wb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > probe.MAX_FILE_BYTES:
                    raise probe.MediaRejected("too_large", _TOO_LARGE)
                await asyncio.to_thread(handle.write, chunk)
        info = await asyncio.to_thread(probe.probe_media, part, filename)
        item = await asyncio.to_thread(clips.add_item, pid, part, filename, info)
    except (clips.ClipError, probe.MediaRejected) as exc:
        return _fail(exc.code, exc.message)
    finally:
        if part is not None:
            part.unlink(missing_ok=True)
    compose.schedule(pid)
    return {"ok": True, "project_id": pid, "item": item,
            "path": str(clips.abs_path(pid, item["file"])), "clips": clips.load(pid)}


@router.get("/{pid}")
def get_media(pid: str):
    try:
        project = dp.get_project(pid)
    except KeyError:
        return _fail("not_found", "No such demo project.")
    compose.ensure_current(pid)
    return {"ok": True, "project_id": pid, "name": project["name"], "stage": project["stage"],
            "clips": clips.load(pid)}


def _apply(pid: str, action):
    try:
        _target_project(pid)
        action()
    except clips.ClipError as exc:
        return _fail(exc.code, exc.message)
    compose.schedule(pid)
    return {"ok": True, "clips": clips.load(pid)}


class OrderBody(BaseModel):
    ids: list[str]


class TrimBody(BaseModel):
    trim_start: float = 0.0
    trim_end: Optional[float] = None


@router.put("/{pid}/order", dependencies=[Depends(verify_csrf)])
def put_order(pid: str, body: OrderBody):
    return _apply(pid, lambda: clips.reorder(pid, body.ids))


@router.patch("/{pid}/clips/{cid}", dependencies=[Depends(verify_csrf)])
def patch_clip(pid: str, cid: str, body: TrimBody):
    return _apply(pid, lambda: clips.set_trim(pid, cid, body.trim_start, body.trim_end))


@router.delete("/{pid}/items/{iid}", dependencies=[Depends(verify_csrf)])
def delete_item(pid: str, iid: str):
    return _apply(pid, lambda: clips.remove_item(pid, iid))
```

In `web/app.py`, add directly under `from routes.recorder import router as recorder_router`:

```python
from routes.demo_clips import router as demo_clips_router
```

and directly under `app.include_router(recorder_router)`:

```python
app.include_router(demo_clips_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/demo_media/test_routes.py tests/test_csrf_route_inventory.py -v`
Expected: PASS (all). `tests/csrf_route_baseline.txt` stays untouched.

- [ ] **Step 5: Commit**

```bash
git add web/routes/demo_clips.py web/app.py tests/demo_media/test_routes.py
git commit -m "feat: add /api/demo-media routes for clip upload, order, trim and removal"
```

### Task 6: Soundtrack mix in `tts_pipeline.py`

**Files:**
- Modify: `web/skills/gator-demo-recorder/scripts/tts_pipeline.py` (`merge_audio_video`, `main`; add `build_merge_argv` directly above `merge_audio_video`)
- Test: `tests/demo_media/test_tts_merge.py`

**Interfaces:**
- Produces: `build_merge_argv(ffmpeg, video_path, audio_path, out_path, soundtrack=None) -> list[str]`; `merge_audio_video(video_path, audio_path, out_path, soundtrack=None)`; CLI flag `--soundtrack <path>` (default none).
- Without a soundtrack the output is today's command plus explicit `-map 0:v:0 -map 1:a:0`, so narration replaces any audio the video carries. With a soundtrack the music bed is mixed under the narration at volume 0.25.

- [ ] **Step 1: Write the failing tests**

`tests/demo_media/test_tts_merge.py`:

```python
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder" / "scripts" / "tts_pipeline.py"
MIX = "[2:a]volume=0.25[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"


def _load():
    spec = importlib.util.spec_from_file_location("tts_pipeline_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merge_argv_without_soundtrack_maps_narration_explicitly():
    mod = _load()
    assert mod.build_merge_argv("ff", "v.mp4", "n.mp3", "out.mp4") == [
        "ff", "-y", "-i", "v.mp4", "-i", "n.mp3", "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", "out.mp4"]


def test_merge_argv_with_soundtrack_mixes_under_narration():
    mod = _load()
    assert mod.build_merge_argv("ff", "v.mp4", "n.mp3", "out.mp4", soundtrack="s.m4a") == [
        "ff", "-y", "-i", "v.mp4", "-i", "n.mp3", "-i", "s.m4a", "-filter_complex", MIX,
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", "out.mp4"]


def _patched(mod, monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        Path(argv[-1]).write_bytes(b"x")

    monkeypatch.setattr(mod, "get_ffmpeg_path", lambda: "ff")
    monkeypatch.setattr(mod, "get_duration", lambda path: 10.0)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return seen


def test_merge_audio_video_passes_soundtrack(tmp_path, monkeypatch):
    mod = _load()
    seen = _patched(mod, monkeypatch)
    mod.merge_audio_video("v.mp4", "n.mp3", tmp_path / "out.mp4", soundtrack="s.m4a")
    assert seen[-1][seen[-1].index("-filter_complex") + 1] == MIX
    seen.clear()
    mod.merge_audio_video("v.mp4", "n.mp3", tmp_path / "out2.mp4")
    assert "-filter_complex" not in seen[-1] and "1:a:0" in seen[-1]


def test_cli_soundtrack_flag_reaches_merge(tmp_path, monkeypatch):
    mod = _load()
    (tmp_path / "t.json").write_text("[]", encoding="utf-8")
    (tmp_path / "n.json").write_text(json.dumps([]), encoding="utf-8")
    got = {}
    monkeypatch.setattr(mod, "build_synced_audio", lambda *a, **k: tmp_path / "a.mp3")
    monkeypatch.setattr(mod, "merge_audio_video", lambda video, audio, out, soundtrack=None: got.update(soundtrack=soundtrack))
    base = ["tts_pipeline.py", "--video", str(tmp_path / "v.mp4"), "--timeline", str(tmp_path / "t.json"),
            "--narration", str(tmp_path / "n.json"), "--output", str(tmp_path / "o.mp4")]
    monkeypatch.setattr(sys, "argv", base + ["--soundtrack", "s.m4a"])
    mod.main()
    assert got["soundtrack"] == "s.m4a"
    monkeypatch.setattr(sys, "argv", base)
    mod.main()
    assert got["soundtrack"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/demo_media/test_tts_merge.py -v`
Expected: FAIL with `AttributeError: module 'tts_pipeline_under_test' has no attribute 'build_merge_argv'`.

- [ ] **Step 3: Implement**

In `tts_pipeline.py`, insert directly above `def merge_audio_video(video_path, audio_path, out_path):`:

```python
_SOUNDTRACK_MIX = (
    "[2:a]volume=0.25[bg];"
    "[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"
)


def build_merge_argv(ffmpeg, video_path, audio_path, out_path, soundtrack=None):
    argv = [ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path)]
    if soundtrack:
        argv += ["-i", str(soundtrack), "-filter_complex", _SOUNDTRACK_MIX,
                 "-map", "0:v:0", "-map", "[aout]"]
    else:
        argv += ["-map", "0:v:0", "-map", "1:a:0"]
    argv += ["-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
             "-shortest", "-movflags", "+faststart", str(out_path)]
    return argv
```

Change the signature line to `def merge_audio_video(video_path, audio_path, out_path, soundtrack=None):` and replace the final `subprocess.run(` call (the one ending in `"-shortest", "-movflags", "+faststart", str(out_path)],` through `capture_output=True, check=True` and its closing `)`) with:

```python
    subprocess.run(
        build_merge_argv(ffmpeg, video_path, audio_path, out_path, soundtrack),
        capture_output=True, check=True
    )
```

In `main()` add after the `--work-dir` argument:

```python
    parser.add_argument("--soundtrack", default=None)
```

and replace `merge_audio_video(args.video, audio, args.output)` with:

```python
    merge_audio_video(args.video, audio, args.output, soundtrack=args.soundtrack)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/demo_media/test_tts_merge.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add web/skills/gator-demo-recorder/scripts/tts_pipeline.py tests/demo_media/test_tts_merge.py
git commit -m "feat: mix an optional soundtrack under demo narration"
```

### Task 7: Skill "Import Mode" and Phase 4 soundtrack

**Files:**
- Modify: `web/skills/gator-demo-recorder/SKILL.md` (pipeline intro, new `## Import Mode` section directly above `## Phase 2: Analyze`, Phase 4 command)
- Test: `tests/demo_media/test_skill_clip_rules.py`

**Interfaces:**
- Consumes: `project.json` `ext["clips"]` from Tasks 2 and 4 (`timeline.state`, `timeline.file`, `timeline.duration`, `timeline.frame_times`, `timeline.clips`, `timeline.error`); `tts_pipeline.py --soundtrack` from Task 6; SP3's `PROJECT_DIR` convention (the project folder).
- Produces: agent instructions only. The agent reads files and runs ffmpeg/`tts_pipeline.py`; it never calls a mutating `/api/demo-media` route.

- [ ] **Step 1: Write the failing test**

`tests/demo_media/test_skill_clip_rules.py`:

```python
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder" / "SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _import_section() -> str:
    return _text().split("## Import Mode", 1)[1].split("\n## ", 1)[0]


def test_import_mode_precedes_phase_2():
    text = _text()
    assert "## Import Mode" in text
    assert text.index("## Import Mode") < text.index("## Phase 2: Analyze")


def test_import_mode_reads_the_prepared_timeline():
    section = _import_section()
    for marker in ("project.json", 'ext["clips"]', "frame_times", "timeline", "[File:", "600"):
        assert marker in section, marker


def test_import_mode_never_mutates_via_api():
    section = _import_section()
    assert "/api/demo-media" in section
    assert "never call" in section.lower()


def test_phase_4_passes_the_soundtrack():
    text = _text()
    assert '"--soundtrack"' in text and "soundtrack.m4a" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/demo_media/test_skill_clip_rules.py -v`
Expected: FAIL with `IndexError: list index out of range` (no `## Import Mode` yet) and an assertion on `--soundtrack`.

- [ ] **Step 3: Edit SKILL.md**

3a. Directly after the closing triple backtick of the `## Pipeline` code block (the line after `Phase 5: DELIVER ...`), add this paragraph:

```markdown
**Import Mode:** when the user attached existing video or audio instead of recording, skip Phase 1 and follow `## Import Mode`. It produces the same inputs Phase 2 expects.
```

3b. Directly above the `---` line that precedes `## Phase 2: Analyze`, insert the following section followed by a `---` line:

````markdown
## Import Mode

Use this instead of Phase 1 when the message contains `[File: <path>]` chips whose paths end in a video or audio extension and sit inside a project's `source/` folder (`<PROJECT_DIR>/source/<id>_<name>`), or when the user asks you to narrate footage they already have. There is no recording to wait for.

The browser uploads each file and builds one combined, trimmed timeline in the background. The user orders and trims clips in the clips panel above the chat box. You only read the result: `<PROJECT_DIR>/project.json` holds it under `ext["clips"]` (`clips`, `audio`, and `timeline` with `state`, `file`, `duration`, `frame_times`, `clips`, `error`).

- **Never call** `/api/demo-media` routes that change anything (upload, order, trim, delete) — they are for the browser. To change clips, tell the user to use the clips panel.
- Audio-only attachments are a music bed. If there is no video clip yet, ask the user to attach one.

Run this once per request. It waits for the timeline, then extracts the frames:

```python
import json, subprocess, time, urllib.request
from pathlib import Path

chip = Path(r"<path inside the [File: ...] chip>")
PROJECT_DIR = chip.parent.parent

def timeline_state():
    project = json.loads((PROJECT_DIR / "project.json").read_text(encoding="utf-8"))
    return project.get("ext", {}).get("clips", {}).get("timeline", {})

tl = timeline_state()
deadline = time.time() + 600
while tl.get("state") == "building" and time.time() < deadline:
    time.sleep(5)
    tl = timeline_state()

if tl.get("state") == "failed":
    print("TIMELINE FAILED:", tl.get("error"))
elif tl.get("state") != "ready":
    print("TIMELINE NOT READY:", tl.get("state"))
else:
    status = json.loads(urllib.request.urlopen("http://localhost:8003/api/recorder/status").read())
    ffmpeg = status["ffmpeg_path"]
    video = PROJECT_DIR / tl["file"]
    frames_dir = PROJECT_DIR / "work" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()
    for n, t in enumerate(tl["frame_times"], start=1):
        subprocess.run([ffmpeg, "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                        str(frames_dir / f"frame_{n:04d}.png")], shell=False, check=True)
    frames = sorted(frames_dir.glob("frame_*.png"))
    fps = round(len(frames) / tl["duration"], 4)
    print(f"VIDEO={video}")
    print(f"FRAMES={len(frames)} FPS={fps} DIR={frames_dir}")
    print("CLIPS=", json.dumps(tl["clips"]))
```

Outcomes:

- `TIMELINE FAILED` → tell the user the `error` text and stop; they can remove or replace the clip in the panel.
- `TIMELINE NOT READY` → tell the user no video clip is attached yet, or the build has not started, and stop.
- Otherwise `VIDEO` is the file Phase 4 merges into (it is also the project's `raw`). Continue at **Phase 2, Step 2**: call `describe_images` with `task='analyze_sequence'`, the frame paths printed above (at most 8), and the `FPS` value printed above. Use the `CLIPS` boundaries (`start`/`end` seconds per source clip) to say which clip each frame belongs to in the scene summary, then continue to Phase 3.
- Phase 3 timing: narration `start_at` values are seconds on the combined timeline, so a segment about the second clip starts at or after that clip's `start`.
````

3c. In Phase 4, replace the opening of the TTS command

```python
result = subprocess.run([
    sys.executable,
    str(skill_dir / "tts_pipeline.py"),
```

through its closing line `], capture_output=True, text=True, timeout=600, shell=False)` with the form below. Keep every argument already in the list (SP2/SP3 changed some of them), and only restructure the call and add the soundtrack lines:

```python
cmd = [
    sys.executable,
    str(skill_dir / "tts_pipeline.py"),
    "--video", video_path,
    "--timeline", str(timeline_file),
    "--narration", str(narration_file),
    "--output", str(output_path),
    "--work-dir", str(session_dir / "tts_work"),
    "--voice", voice,
]
# Imported clips: the timeline folder holds the combined music bed, if any
soundtrack = Path(video_path).parent / "soundtrack.m4a"
if soundtrack.exists():
    cmd += ["--soundtrack", str(soundtrack)]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, shell=False)
```

The test looks for the literal `"--soundtrack"`, which the line `cmd += ["--soundtrack", str(soundtrack)]` contains.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/demo_media/test_skill_clip_rules.py -v`
Expected: PASS (all). Also run SP3's skill contract test if present (`python -m pytest tests -k "demo_project and skill" -v`); it must stay green.

- [ ] **Step 5: Commit**

```bash
git add web/skills/gator-demo-recorder/SKILL.md tests/demo_media/test_skill_clip_rules.py
git commit -m "feat: add Import Mode and soundtrack mixing to the Demo Recorder skill"
```

### Task 8: `DemoMedia` front-end module

**Files:**
- Create: `web/static/demo-media.js`
- Test: `tests/demo_media_ui.test.js`

**Interfaces:**
- Consumes (HTTP, from Task 5, base `/api/demo-media`): `POST /upload?filename=&project_id=` (raw body) returns `{ok, project_id, item, path, clips}`; `GET /{pid}` returns `{ok, project_id, name, stage, clips}`; `PUT /{pid}/order` body `{ids}`, `PATCH /{pid}/clips/{cid}` body `{trim_start, trim_end}`, `DELETE /{pid}/items/{iid}` each return `{ok, clips}`. Errors are `{ok: false, code, message}`. In every body `clips` is the registry `{version, next_id, clips: [{id, name, file, duration, width, height, trim_start, trim_end}], audio: [{id, name, file, duration}], timeline: {state, duration, error, ...}}`; `timeline.state` is `idle`, `building`, `ready` or `failed`.
- Produces (global `const DemoMedia`, loaded as a plain script before `app.js`):
  - `classify(name) -> 'video' | 'audio' | null`
  - `validateLocal(file) -> string | null` (error message or null)
  - `formatDuration(seconds) -> 'm:ss'`
  - `parseTrim(startText, endText, duration) -> {ok: true, trim_start, trim_end} | {ok: false, error}`
  - `moveId(ids, id, delta) -> string[]` (new array)
  - `upload(file, {projectId, onProgress}) -> Promise<body>` (rejects with `Error(message)`)
  - `setProject(projectId, registry)` where `registry` is the `clips` object from a response
  - `mountPanel(el)` and the read-only getter `currentProjectId`

- [ ] **Step 1: Write the failing test**

Create `tests/demo_media_ui.test.js`:

```javascript
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web', 'static', 'demo-media.js'), 'utf8');
const DemoMedia = vm.runInNewContext(source + '; DemoMedia;', { window: {}, document: {} });

// Objects built inside the vm have a different realm's prototypes; compare as plain JSON.
const plain = (value) => JSON.parse(JSON.stringify(value));

// classify
assert.strictEqual(DemoMedia.classify('Demo.MP4'), 'video');
assert.strictEqual(DemoMedia.classify('clip.webm'), 'video');
assert.strictEqual(DemoMedia.classify('bed.wav'), 'audio');
assert.strictEqual(DemoMedia.classify('report.docx'), null);
assert.strictEqual(DemoMedia.classify('noextension'), null);

// validateLocal
assert.strictEqual(DemoMedia.validateLocal({ name: 'a.mp4', size: 10 }), null);
assert.match(DemoMedia.validateLocal({ name: 'a.mp4', size: 0 }), /empty/i);
assert.match(DemoMedia.validateLocal({ name: 'a.mp4', size: 2 * 1024 ** 3 + 1 }), /2 GB/);

// formatDuration
assert.strictEqual(DemoMedia.formatDuration(0), '0:00');
assert.strictEqual(DemoMedia.formatDuration(65), '1:05');
assert.strictEqual(DemoMedia.formatDuration(599.6), '10:00');
assert.strictEqual(DemoMedia.formatDuration(3725), '62:05');

// parseTrim
assert.deepStrictEqual(plain(DemoMedia.parseTrim('', '', 10)), { ok: true, trim_start: 0, trim_end: null });
assert.deepStrictEqual(plain(DemoMedia.parseTrim('1', '6.5', 10)), { ok: true, trim_start: 1, trim_end: 6.5 });
assert.deepStrictEqual(plain(DemoMedia.parseTrim('2', '', 10)), { ok: true, trim_start: 2, trim_end: null });
for (const [s, e] of [['x', ''], ['-1', ''], ['0', 'abc'], ['0', '11'], ['2', '2.2'], ['9.8', '']]) {
  const r = DemoMedia.parseTrim(s, e, 10);
  assert.strictEqual(r.ok, false, `parseTrim(${s}, ${e}) should be rejected`);
  assert.ok(typeof r.error === 'string' && r.error.length > 0);
}

// moveId
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2', 'c3'], 'c2', -1)), ['c2', 'c1', 'c3']);
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2', 'c3'], 'c2', 1)), ['c1', 'c3', 'c2']);
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2'], 'c1', -1)), ['c1', 'c2']);
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2'], 'c2', 1)), ['c1', 'c2']);
assert.deepStrictEqual(plain(DemoMedia.moveId(['c1', 'c2'], 'zz', 1)), ['c1', 'c2']);

console.log('demo_media_ui: ok');
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/demo_media_ui.test.js`
Expected: FAIL with `ENOENT ... demo-media.js`.

- [ ] **Step 3: Write the helpers and upload**

Create `web/static/demo-media.js` (Step 4 appends the panel before the closing `})();`; write the file in this order so it stays valid):

```javascript
/* Demo clip intake: validation helpers, XHR upload and the clip panel. Plain global script. */
const DemoMedia = (() => {
  const VIDEO_EXTS = ['mp4', 'mov', 'm4v', 'webm'];
  const AUDIO_EXTS = ['mp3', 'm4a', 'wav', 'aac', 'ogg', 'flac'];
  const MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024;
  const MIN_CLIP_SECONDS = 0.5;
  const POLL_MS = 2000;
  const BASE = '/api/demo-media';

  let currentProjectId = null;
  let registry = null;
  let panelEl = null;
  let pollTimer = null;
  let statusText = '';

  function classify(name) {
    const m = /\.([^.\\/]+)$/.exec(String(name || ''));
    if (!m) return null;
    const ext = m[1].toLowerCase();
    if (VIDEO_EXTS.includes(ext)) return 'video';
    if (AUDIO_EXTS.includes(ext)) return 'audio';
    return null;
  }

  function validateLocal(file) {
    if (!file.size) return 'File is empty';
    if (file.size > MAX_FILE_BYTES) return 'File exceeds the 2 GB limit';
    return null;
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
  }

  function parseTrim(startText, endText, duration) {
    const s = String(startText == null ? '' : startText).trim();
    const e = String(endText == null ? '' : endText).trim();
    const start = s === '' ? 0 : Number(s);
    const end = e === '' ? null : Number(e);
    if (!Number.isFinite(start) || start < 0) {
      return { ok: false, error: 'Start must be 0 or more seconds' };
    }
    if (end !== null && !Number.isFinite(end)) {
      return { ok: false, error: 'End must be a number of seconds' };
    }
    const effectiveEnd = end === null ? duration : end;
    if (effectiveEnd > duration + 0.001) {
      return { ok: false, error: 'End is past the end of the clip' };
    }
    if (effectiveEnd - start < MIN_CLIP_SECONDS) {
      return { ok: false, error: 'Keep at least ' + MIN_CLIP_SECONDS + ' seconds of the clip' };
    }
    return { ok: true, trim_start: start, trim_end: end };
  }

  function moveId(ids, id, delta) {
    const out = ids.slice();
    const from = out.indexOf(id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= out.length) return out;
    out.splice(from, 1);
    out.splice(to, 0, id);
    return out;
  }

  function errorMessage(body, status) {
    return (body && (body.message || body.detail)) || 'Request failed (' + status + ')';
  }

  function upload(file, opts) {
    const o = opts || {};
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      let url = BASE + '/upload?filename=' + encodeURIComponent(file.name);
      if (o.projectId) url += '&project_id=' + encodeURIComponent(o.projectId);
      xhr.open('POST', url);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.setRequestHeader('X-CSRF-Token', window.__CSRF_TOKEN__ || '');
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && o.onProgress) o.onProgress(Math.round((ev.loaded * 100) / ev.total));
      };
      xhr.onerror = () => reject(new Error('Upload failed: connection error'));
      xhr.onload = () => {
        let body = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch (_) {
          body = null;
        }
        if (xhr.status >= 200 && xhr.status < 300 && body && body.ok) resolve(body);
        else reject(new Error(errorMessage(body, xhr.status)));
      };
      xhr.send(file);
    });
  }

  // PANEL-CONTINUES

  return {
    classify,
    validateLocal,
    formatDuration,
    parseTrim,
    moveId,
    upload,
    setProject,
    mountPanel,
    get currentProjectId() {
      return currentProjectId;
    },
  };
})();
```

- [ ] **Step 4: Write the panel**

In `web/static/demo-media.js`, replace the line `  // PANEL-CONTINUES` with:

```javascript
  async function call(method, path, body) {
    const init = { method, headers: {} };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const res = await fetch(BASE + '/' + path, init);
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok || !data || !data.ok) throw new Error(errorMessage(data, res.status));
    return data;
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function iconButton(label, title, disabled, onClick) {
    const b = el('button', 'demo-media-btn', label);
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.disabled = !!disabled;
    b.addEventListener('click', onClick);
    return b;
  }

  function summary(reg) {
    if (!reg.clips.length) return reg.audio.length ? 'Add a video clip to build the timeline' : 'No clips yet';
    const tl = reg.timeline || {};
    if (tl.state === 'ready') return 'Ready - ' + formatDuration(tl.duration) + ' total';
    if (tl.state === 'failed') return 'Build failed: ' + (tl.error || 'unknown error');
    return 'Building timeline...';
  }

  function needsPoll() {
    if (!registry || !registry.clips.length) return false;
    const state = (registry.timeline || {}).state;
    return state !== 'ready' && state !== 'failed';
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = null;
    if (!needsPoll() || !currentProjectId) return;
    const pid = currentProjectId;
    pollTimer = setTimeout(async () => {
      try {
        const data = await call('GET', encodeURIComponent(pid));
        if (pid === currentProjectId) {
          const changed = JSON.stringify(data.clips) !== JSON.stringify(registry);
          registry = data.clips;
          if (changed) render();
        }
      } catch (e) {
        statusText = e.message;
        render();
        return;
      }
      schedulePoll();
    }, POLL_MS);
  }

  async function mutate(method, path, body) {
    try {
      const data = await call(method, encodeURIComponent(currentProjectId) + '/' + path, body);
      registry = data.clips;
      statusText = '';
    } catch (e) {
      statusText = e.message;
    }
    render();
    schedulePoll();
  }

  function clipRow(clip, ids) {
    const row = el('div', 'demo-media-row');
    row.appendChild(el('span', 'demo-media-name', clip.name));
    row.appendChild(el('span', 'demo-media-dur', formatDuration(clip.duration)));
    const i = ids.indexOf(clip.id);
    row.appendChild(iconButton('↑', 'Move ' + clip.name + ' earlier', i === 0, () =>
      mutate('PUT', 'order', { ids: moveId(ids, clip.id, -1) })));
    row.appendChild(iconButton('↓', 'Move ' + clip.name + ' later', i === ids.length - 1, () =>
      mutate('PUT', 'order', { ids: moveId(ids, clip.id, 1) })));
    const start = el('input', 'demo-media-trim');
    start.type = 'text';
    start.value = String(clip.trim_start || 0);
    start.setAttribute('aria-label', 'Trim start seconds for ' + clip.name);
    const end = el('input', 'demo-media-trim');
    end.type = 'text';
    end.value = clip.trim_end == null ? '' : String(clip.trim_end);
    end.placeholder = 'end';
    end.setAttribute('aria-label', 'Trim end seconds for ' + clip.name);
    const applyTrim = () => {
      const t = parseTrim(start.value, end.value, clip.duration);
      if (!t.ok) {
        statusText = t.error;
        render();
        return;
      }
      mutate('PATCH', 'clips/' + encodeURIComponent(clip.id), {
        trim_start: t.trim_start,
        trim_end: t.trim_end,
      });
    };
    start.addEventListener('change', applyTrim);
    end.addEventListener('change', applyTrim);
    row.appendChild(start);
    row.appendChild(end);
    row.appendChild(removeButton(clip));
    return row;
  }

  function removeButton(item) {
    return iconButton('✕', 'Remove ' + item.name, false, () =>
      mutate('DELETE', 'items/' + encodeURIComponent(item.id)));
  }

  function audioRow(asset) {
    const row = el('div', 'demo-media-row demo-media-audio');
    row.appendChild(el('span', 'demo-media-name', '🎵 ' + asset.name));
    row.appendChild(el('span', 'demo-media-dur', formatDuration(asset.duration)));
    row.appendChild(removeButton(asset));
    return row;
  }

  function render() {
    if (!panelEl) return;
    panelEl.textContent = '';
    const has = registry && (registry.clips.length || registry.audio.length);
    panelEl.classList.toggle('hidden', !has);
    if (!has) return;
    const state = (registry.timeline || {}).state;
    const label = el('div', 'demo-media-state demo-media-' + (registry.clips.length ? state : 'idle'), summary(registry));
    label.setAttribute('role', 'status');
    panelEl.appendChild(label);
    const ids = registry.clips.map((c) => c.id);
    registry.clips.forEach((clip) => panelEl.appendChild(clipRow(clip, ids)));
    registry.audio.forEach((asset) => panelEl.appendChild(audioRow(asset)));
    if (statusText) {
      const err = el('div', 'demo-media-error', statusText);
      err.setAttribute('role', 'alert');
      panelEl.appendChild(err);
    }
  }

  function setProject(projectId, reg) {
    currentProjectId = projectId;
    registry = reg;
    statusText = '';
    render();
    schedulePoll();
  }

  function mountPanel(container) {
    panelEl = container;
    render();
  }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `node tests/demo_media_ui.test.js`
Expected: prints `demo_media_ui: ok`.

- [ ] **Step 6: Commit**

```bash
git add web/static/demo-media.js tests/demo_media_ui.test.js
git commit -m "feat: add DemoMedia front-end helpers, upload and clip panel"
```

### Task 9: Chat wiring (attach, panel, submit gate, tab pin)

**Files:**
- Modify: `web/static/index.html` (panel container near line 1633, file-input `accept` near line 1639, script tags near line 2002)
- Modify: `web/static/style.css` (append at end of file)
- Modify: `web/static/app.js` (`initAigatorUpload` / `processFiles` near line 12241, new `_attachDemoMedia` after `_showUploadError`, submit handler near line 12514)
- Test: `tests/demo_media_ui.test.js` (wiring assertions)

**Interfaces:**
- Consumes: Task 8's `DemoMedia.classify`, `validateLocal`, `upload`, `setProject`, `mountPanel`. From `app.js`: `_showUploadError(el, msg)`, `_wireChipRemove(removeBtn, chip, input)`, `_moveCaretToEnd(input)`, the `input` element constant used by the submit handler. From SP2 (guarded, because the pin helpers only exist once SP2 has landed): `_setTabPin(tabId, {skill, projectId})`, `_DEMO_RECORDER_SKILL`, `_activeTabId`.
- Produces: a media chip `<span class="pin-ref-chip file-ref-chip" data-media-uploading="1">` that gets `data-file-path` (absolute path from the upload response) when the upload succeeds. `_getInputText()` already turns chips with `data-file-path` into `[File: <path>]`, which is the trigger Import Mode (Task 7) looks for.

- [ ] **Step 1: Write the failing test**

In `tests/demo_media_ui.test.js`, insert before the final `console.log('demo_media_ui: ok');`:

```javascript
// wiring
const read = (...p) => fs.readFileSync(path.join(root, ...p), 'utf8');
const appJs = read('web', 'static', 'app.js');
const indexHtml = read('web', 'static', 'index.html');
const styleCss = read('web', 'static', 'style.css');
assert.ok(appJs.includes('DemoMedia.classify(file.name)'), 'processFiles routes media files');
assert.ok(appJs.includes('function _attachDemoMedia('), 'media chip helper exists');
assert.ok(appJs.includes('data-media-uploading'), 'submit gate checks uploading chips');
assert.ok(appJs.includes('Wait for the upload to finish'), 'submit gate message');
assert.ok(appJs.includes('DemoMedia.mountPanel('), 'panel is mounted');
assert.ok(indexHtml.includes('id="demo-media-panel"'), 'panel container');
assert.ok(indexHtml.includes('/static/demo-media.js'), 'script tag');
assert.ok(indexHtml.includes('.mp4,.mov,.m4v,.webm,.mp3,.m4a,.wav,.aac,.ogg,.flac'), 'file input accepts media');
assert.ok(styleCss.includes('.demo-media-panel'), 'panel styles');
assert.ok(
  indexHtml.indexOf('/static/demo-media.js') < indexHtml.indexOf('/static/app.js'),
  'demo-media.js loads before app.js',
);
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/demo_media_ui.test.js`
Expected: FAIL with `processFiles routes media files`.

- [ ] **Step 3: Edit `index.html`**

(a) After the line `<span class="aigator-drop-error hidden" id="aigator-drop-error" role="alert"></span>` and before `<div class="chat-input-row" id="chat-input-row">`, add:

```html
          <div
            id="demo-media-panel"
            class="demo-media-panel hidden"
            aria-label="Demo clips"
          ></div>
```

(b) In the `aigator-file-input` element, extend `accept` to end with the media extensions:

```html
              accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,.docx,.xlsx,.pptx,.doc,.xls,.ppt,.csv,.mp4,.mov,.m4v,.webm,.mp3,.m4a,.wav,.aac,.ogg,.flac"
```

(c) In the script block that writes `app.js`, add the `demo-media.js` line immediately before the `app.js` line:

```javascript
      document.write('<scr' + 'ipt src="/static/demo-media.js' + _cb + '"><\/scr' + 'ipt>');
      document.write('<scr' + 'ipt src="/static/app.js' + _cb + '"><\/scr' + 'ipt>');
```

- [ ] **Step 4: Append styles**

`style.css` contains non-ASCII comment characters, so do not rewrite the file with an editor that re-encodes it. Append with the shell (ASCII only):

```bash
cat >> web/static/style.css <<'EOF'

/* Demo media: clip panel above the chat input */
.demo-media-panel {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin: 0 0.85rem 0.4rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-card);
  font-size: 0.78rem;
  color: var(--text);
}
.demo-media-panel.hidden {
  display: none;
}
.demo-media-state {
  font-weight: 600;
  color: var(--text-dim);
}
.demo-media-state.demo-media-ready {
  color: var(--accent);
}
.demo-media-state.demo-media-failed {
  color: var(--danger);
}
.demo-media-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.demo-media-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.demo-media-dur {
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}
.demo-media-trim {
  width: 3.4rem;
  padding: 0.1rem 0.3rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--text);
  font: inherit;
}
.demo-media-btn {
  padding: 0.05rem 0.4rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
}
.demo-media-btn:disabled {
  opacity: 0.35;
  cursor: default;
}
.demo-media-error {
  color: var(--danger);
  font-weight: 600;
}
EOF
```

- [ ] **Step 5: Edit `app.js`**

(a) In `initAigatorUpload`, directly after `if (!attachBtn || !fileIn) return;`, add:

```javascript
  const mediaPanel = document.getElementById('demo-media-panel');
  if (mediaPanel && typeof DemoMedia !== 'undefined') DemoMedia.mountPanel(mediaPanel);
```

(b) In `processFiles`, directly after `const ext = file.name.split('.').pop().toLowerCase();` and before the `// Document files` comment, add (`DemoMedia` is a top-level `const` in a classic script, so test it with `typeof`):

```javascript
      // Video/audio → stream to the Demo Recorder project (Import Mode)
      if (typeof DemoMedia !== 'undefined' && DemoMedia.classify(file.name)) {
        _attachDemoMedia(file, errEl);
        continue;
      }
```

(c) Directly after the `_showUploadError` function, add:

```javascript
function _attachDemoMedia(file, errEl) {
  const problem = DemoMedia.validateLocal(file);
  if (problem) {
    _showUploadError(errEl, problem);
    return;
  }
  const input = document.getElementById('chat-input');
  const chip = document.createElement('span');
  chip.className = 'pin-ref-chip file-ref-chip';
  chip.contentEditable = 'false';
  chip.dataset.fileName = file.name;
  chip.dataset.mediaUploading = '1';
  chip.title = file.name;
  chip.appendChild(
    document.createTextNode(DemoMedia.classify(file.name) === 'video' ? '🎬 ' : '🎵 '),
  );
  const nameSpan = document.createElement('span');
  nameSpan.className = 'file-chip-name';
  nameSpan.textContent = file.name + ' (0%)';
  chip.appendChild(nameSpan);
  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'file-chip-remove';
  removeBtn.setAttribute('aria-label', 'Remove ' + file.name);
  removeBtn.title = 'Remove';
  removeBtn.textContent = '✕';
  _wireChipRemove(removeBtn, chip, input);
  chip.appendChild(removeBtn);
  input.appendChild(chip);
  input.appendChild(document.createTextNode(' '));
  input.focus();
  if (typeof _moveCaretToEnd === 'function') _moveCaretToEnd(input);

  DemoMedia.upload(file, {
    onProgress: (pct) => {
      nameSpan.textContent = file.name + ' (' + pct + '%)';
    },
  })
    .then((res) => {
      nameSpan.textContent = file.name;
      chip.dataset.filePath = res.path;
      delete chip.dataset.mediaUploading;
      DemoMedia.setProject(res.project_id, res.clips);
      if (typeof _setTabPin === 'function' && typeof _DEMO_RECORDER_SKILL !== 'undefined') {
        _setTabPin(_activeTabId, { skill: _DEMO_RECORDER_SKILL, projectId: res.project_id });
      }
    })
    .catch((err) => {
      chip.remove();
      _showUploadError(errEl, err.message);
    });
}
```

(d) In the `form.addEventListener('submit', ...)` handler, directly after the `if (_slashDropdown || _mentionDropdown || _pinDropdown || _channelDropdown) { ... return; }` block and before `closeMentionDropdown();`, add:

```javascript
  if (input.querySelector('[data-media-uploading]')) {
    _showUploadError(document.getElementById('aigator-drop-error'), 'Wait for the upload to finish');
    return;
  }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `node tests/demo_media_ui.test.js`
Expected: prints `demo_media_ui: ok`. Then run the repo's existing JS/lint checks that cover `app.js` (for example `node --check web/static/app.js web/static/demo-media.js`) and confirm no failures.

- [ ] **Step 7: Manual smoke test (Playwright MCP against a dev server)**

1. Make two small clips: `ffmpeg -f lavfi -i testsrc=size=640x360:rate=30 -t 6 -pix_fmt yuv420p a.mp4` and the same with `-t 4 b.mp4`; one tone: `ffmpeg -f lavfi -i sine=frequency=440 -t 10 bed.mp3`.
2. Start the app, open a chat tab, attach `a.mp4` with the paperclip. Expect: a chip with a progress percentage that settles to the file name; the "Demo clips" panel shows one row and `Building timeline...`, then `Ready - 0:06 total`.
3. Press Enter while a large upload is still running. Expect: "Wait for the upload to finish" and no message sent.
4. Drag `b.mp4` onto the input row, then `bed.mp3`. Expect: two clip rows plus one audio row; the total becomes `0:10`.
5. Click the down arrow on `a.mp4`; set its end to `3` and tab out. Expect: row order flips and the total drops to `0:07`.
6. Attach a `.txt` renamed to `x.mp4`. Expect: the chip disappears and the error "That file could not be read as media." appears; no row is added.
7. Send the message. Expect: the Demo Recorder skill runs Import Mode (Task 7) and reads the timeline without recording.

- [ ] **Step 8: Commit**

```bash
git add web/static/index.html web/static/style.css web/static/app.js tests/demo_media_ui.test.js
git commit -m "feat: attach demo clips and audio in chat with a clip panel"
```

### Task 10: Real-ffmpeg integration test and full verification

**Files:**
- Test: `tests/demo_media/test_compose_integration.py`

**Interfaces:**
- Consumes: `demo_media_probe.probe_media` / `_run_ffprobe` (Task 1), `demo_clips.add_item` / `set_trim` / `load` (Task 2), `demo_compose.build` / `_ffmpeg` (Task 4), the `store` fixture (Task 1). No new production code.

- [ ] **Step 1: Write the integration test**

`tests/demo_media/test_compose_integration.py` (runs only where ffmpeg and ffprobe exist; the mocked tests in Tasks 3-4 cover everything else):

```python
import subprocess
from pathlib import Path

import pytest

import demo_clips as clips
import demo_compose as compose
import demo_media_probe as probe

pytestmark = pytest.mark.skipif(
    not (compose._ffmpeg() and probe.ffprobe_path()), reason="ffmpeg/ffprobe not available"
)


def _make(out: Path, *args: str) -> Path:
    subprocess.run([compose._ffmpeg(), "-y", *args, str(out)], check=True, capture_output=True)
    return out


def _video(out: Path, size: str, seconds: int) -> Path:
    return _make(
        out,
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", str(seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
    )


def _tone(out: Path, seconds: int) -> Path:
    return _make(out, "-f", "lavfi", "-i", "sine=frequency=220", "-t", str(seconds))


def _add(pid, path: Path):
    return clips.add_item(pid, path, path.name, probe.probe_media(path))


@pytest.fixture
def pid(store):
    return store.create_project(name="Integration")["project_id"]


def test_two_clips_and_a_music_bed_build_one_timeline(store, pid, tmp_path):
    _add(pid, _video(tmp_path / "a.mp4", "640x360", 2))
    _add(pid, _video(tmp_path / "b.mp4", "320x240", 3))
    _add(pid, _tone(tmp_path / "bed.mp3", 5))

    assert compose.build(pid) == "ready"

    project = store.get_project(pid)
    timeline = Path(project["raw"])
    assert timeline.name == "timeline.mp4"
    info = probe._run_ffprobe(timeline)
    kinds = {s["codec_type"] for s in info["streams"]}
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert kinds == {"video"}
    assert video["codec_name"] == "h264"
    assert (video["width"], video["height"]) == (640, 360)
    assert float(info["format"]["duration"]) == pytest.approx(5.0, abs=0.4)

    soundtrack = Path(project["path"]) / "work" / "soundtrack.m4a"
    assert soundtrack.exists()
    assert {s["codec_type"] for s in probe._run_ffprobe(soundtrack)["streams"]} == {"audio"}


def test_trim_changes_the_timeline_length(store, pid, tmp_path):
    _add(pid, _video(tmp_path / "a.mp4", "640x360", 3))
    _add(pid, _video(tmp_path / "b.mp4", "640x360", 3))
    clips.set_trim(pid, "c1", 0.5, 1.5)

    assert compose.build(pid) == "ready"

    info = probe._run_ffprobe(Path(store.get_project(pid)["raw"]))
    assert float(info["format"]["duration"]) == pytest.approx(4.0, abs=0.4)
    assert clips.load(pid)["timeline"]["duration"] == pytest.approx(4.0, abs=0.01)
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/demo_media/test_compose_integration.py -v`
Expected: PASS (2 passed) where ffmpeg exists, otherwise 2 skipped. If a duration assertion misses by more than the tolerance, fix `normalize_argv` / `concat_argv` in `web/demo_compose.py` (the likely cause is `-ss`/`-t` placement), not the tolerance.

- [ ] **Step 3: Run the whole Python suite**

Run: `python -m pytest tests -q`
Expected: all pass. In particular confirm these stay green: `tests/test_csrf_route_inventory.py` (the four new mutating routes carry `verify_csrf`, and `tests/csrf_route_baseline.txt` is unchanged), SP3's SKILL.md contract tests, and SP2's approval and tab-pin tests. Any SKILL.md contract test that fails because of the Import Mode text means the new section broke an anchor it depends on; fix the section, not the test.

- [ ] **Step 4: Run the JS tests**

Run: `node tests/demo_media_ui.test.js` and the repo's other JS tests (`node --test tests` or the project's documented JS test command).
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/demo_media/test_compose_integration.py
git commit -m "test: build a real timeline and soundtrack with ffmpeg"
```

---

## Self-Review

**Spec coverage** (spec section, then the task that implements it):

| Spec requirement | Task |
|---|---|
| Allow-listed extensions, codecs, 2 GiB, 30 min, 8 clips, 4 audio assets, 7680 px; error codes | 1, 2 |
| Registry in `ext["clips"]`: order, trims, ids never reused, limits | 2 |
| Locked stages (`narration_approved`, `delivered`) reject edits; timeline writes still allowed | 2, 4 |
| Normalize to one canvas, concatenate, publish `work/timeline.mp4` as `raw` | 3, 4 |
| Combined music bed `work/soundtrack.m4a` | 3, 4 |
| Single-worker scheduler, fingerprint-guarded writes, dirty loop, failed builds not retried unless the fingerprint changes | 4 |
| `/api/demo-media` routes, CSRF, status codes, implicit-target rule, streaming upload | 5 |
| Soundtrack mixed under narration in Phase 4 | 6, 7 |
| Skill Import Mode: `[File: path]` trigger, wait for timeline, frames from `frame_times`, never call the API | 7 |
| Chat attach, progress, clip panel, reorder/trim/remove, submit blocked while uploading | 8, 9 |
| Tab pinned to the Demo Recorder skill and project after upload (SP2) | 9 |
| Works end to end with real ffmpeg | 10 |

Gaps found: none.

**Placeholder scan:** searched the plan for `TBD`, `TODO`, `implement later`, `similar to Task`, and un-coded steps. The only `PANEL-CONTINUES` marker is inside Task 8's Step 3 code and Step 4 tells the engineer to replace it, so it does not survive into the finished file.

**Type consistency:**
- Responses: `clips` in every body is the registry object, so the front end uses `res.clips` (registry), `registry.clips[]`, `registry.audio[]` and `registry.timeline.state` (Task 5 produces, Tasks 8-9 consume). `setProject(projectId, registry)` is called with `res.project_id, res.clips`.
- Names match across tasks: `DemoMedia.classify`, `validateLocal`, `upload`, `setProject`, `mountPanel` (Task 8 defines, Task 9 uses); `compose.build`, `compose.schedule`, `compose.ensure_current` (Task 4 defines, Tasks 5 and 10 use); `clips.set_trim(pid, cid, start, end)` (Task 2 defines, Tasks 5 and 10 use); `soundtrack.m4a` path (Task 4 produces, Tasks 6, 7 and 10 consume).
- Error shape: Task 5 returns `{ok: false, code, message}` and Task 8's `errorMessage` reads `message` then `detail` (FastAPI's CSRF 403 uses `detail`).
- Status codes: `bad_order` and `bad_trim` are 422 in Task 5 and in the spec.
