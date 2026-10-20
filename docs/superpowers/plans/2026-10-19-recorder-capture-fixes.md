# Recorder Capture Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Demo Recorder issue #55 items 1–5: resume keeps the selected screen/crop, failures are surfaced, stop never returns a bogus file, the prompt-bar Stop click is robust, and video analysis no longer depends on an LLM-built shell runner.

**Architecture:** `web/routes/recorder.py` stores the validated `StartRequest` at start and cleans up failed resume/stop; the recorder widget template in `SKILL.md` shows action failures and no longer emits `()`; `app.js` dispatches Stop through one persistent capture-phase click listener; `describe_images` gains a server-side `analyze_video` task and rejects more than 8 explicit frames. Design: `docs/superpowers/specs/2026-10-19-recorder-capture-fixes-design.md`.

**Tech Stack:** Python 3 / FastAPI / pytest (`asyncio_mode=auto`, `pythonpath = web .`), node `assert` + `vm` tests (`node --test`), vanilla JS (`web/static/app.js`), Markdown skill template (`web/skills/gator-demo-recorder/SKILL.md`).

## Global Constraints

- Do not add `Co-Authored-By` lines in commit messages. One commit per task, conventional commits (`fix:`, `refactor:`, `test:`).
- This project is called **AI Gator** — never refer to it as a POC.
- Use `aigator-fake-api-key` as the only fake credential in tests, examples, fixtures, and documentation. Do not invent alternate fake API keys, tokens, passwords, or secrets.
- Every new POST/PUT/PATCH/DELETE route must use `dependencies=[Depends(verify_csrf)]` from `web/security.py`. `tests/test_csrf_route_inventory.py` fails CI otherwise; do not add routes to `tests/csrf_route_baseline.txt`. This plan adds **no** routes.
- Email, Teams, and Slack messages must NEVER auto-send. Always draft-only and require explicit human approval before sending. (Not touched here.)
- All LLM calls go through `llm.gateway`. `analyze_video` reuses `_analyze_frame_sequence`, which already does; add no new LLM call site.
- Tests must not need ffmpeg: fake `subprocess.Popen`/`subprocess.run` and assert argv.
- Line numbers in this plan come from the tree with PRs #79/#82/#83/#84 merged; locate edits by the quoted code, not the number, because SP3 touches nearby lines (`_session_dir`/`_session_tag`/`OUT_DIR` use in `recorder_start` and `_start_segment`, `final_path`, `_write_latest_output`, the `path`/`session_dir` payload fields).
- Run from the repo root on branch `feat/issue-55-demo-recorder-overhaul`. Python: `uv run pytest <path> -v`. JS: `cd shell && node --test ../tests/<file>.test.js`.

---

## Group A — Item 1: resume keeps the selected screen and crop

### Task 1: `_IS_WINDOWS` test seam

**Files:**
- Modify: `web/routes/recorder.py` (every `os.name` check)
- Create: `tests/test_recorder_capture.py`

**Interfaces:**
- Produces: module constant `rec._IS_WINDOWS: bool` (`os.name == "nt"`), read at call time by every recorder function, so tests can `monkeypatch.setattr(rec, "_IS_WINDOWS", ...)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_recorder_capture.py`:

```python
import os

from routes import recorder as rec


def test_is_windows_constant_matches_platform():
    assert rec._IS_WINDOWS == (os.name == "nt")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_recorder_capture.py -v`
Expected: FAIL with `AttributeError: module 'routes.recorder' has no attribute '_IS_WINDOWS'`

- [ ] **Step 3: Add the constant and replace every check**

In `web/routes/recorder.py`, directly after `router = APIRouter()` add:

```python
_IS_WINDOWS = os.name == "nt"
```

Then replace all other checks mechanically (the definition line is excluded):

```bash
sed -i '/^_IS_WINDOWS = /!{s/os\.name == "nt"/_IS_WINDOWS/g; s/os\.name != "nt"/not _IS_WINDOWS/g}' web/routes/recorder.py
grep -n 'os\.name' web/routes/recorder.py
```

Expected `grep` output: exactly one line, `_IS_WINDOWS = os.name == "nt"`. If `git diff` shows CRLF-only churn on untouched lines, re-run the `sed` with the file's existing line endings preserved (the command above does not change them).

- [ ] **Step 4: Run tests to verify nothing changed**

Run: `uv run pytest tests/test_recorder_capture.py -v` → PASS.
Run: `uv run pytest tests -q -k "recorder"` → PASS (no recorder test regresses).

- [ ] **Step 5: Commit**

```bash
git add web/routes/recorder.py tests/test_recorder_capture.py
git commit -m "refactor: expose recorder platform check as _IS_WINDOWS for testing"
```

### Task 2: store the validated start request (issue #55 item 1)

**Files:**
- Modify: `web/routes/recorder.py` (`class StartRequest` area, `recorder_start`, stale declaration above `recorder_resume`)
- Modify: `tests/test_recorder_capture.py`

**Interfaces:**
- Consumes: `rec._IS_WINDOWS` (Task 1).
- Produces: module global `rec._last_start_req: StartRequest`, set by `recorder_start` to the post-validation (clamped) request; test fixtures `env` and `client` and helper `_start(client, **overrides)` that Tasks 3–4 reuse. `env` exposes `argvs` (Popen argv lists), `runs` (`subprocess.run` argv lists), `fail_next_start`, `segment_bytes`, `concat_returncode`, `concat_stderr`, `borders` (list of `(screen_label, crop_dict_or_None)`), `border_stops`, `latest` (payloads passed to `_write_latest_output`).

- [ ] **Step 1: Write the failing tests**

Add these imports to the top of `tests/test_recorder_capture.py` (merge with the existing `import os` / `from routes import recorder as rec`):

```python
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
```

Append:

```python
SCREENS = [
    {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "label": "Display 1", "primary": True},
    {"index": 1, "x": 1920, "y": 0, "width": 2560, "height": 1440, "label": "Display 2", "primary": False},
]
CROP = {"screen_index": 1, "crop_x": 100, "crop_y": 50, "crop_w": 640, "crop_h": 480}


class FakeProc:
    _next_pid = 4000

    def __init__(self, exit_code=None):
        FakeProc._next_pid += 1
        self.pid = FakeProc._next_pid
        self.exit_code = exit_code
        self.signals = []

    def poll(self):
        return self.exit_code

    def send_signal(self, sig):
        self.signals.append(sig)

    def terminate(self):
        self.exit_code = 0

    def kill(self):
        self.exit_code = -9

    def wait(self, timeout=None):
        if self.exit_code is None:
            self.exit_code = 0
        return self.exit_code


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = types.SimpleNamespace(
        argvs=[], runs=[], borders=[], border_stops=[], latest=[],
        fail_next_start=False, segment_bytes=b"segment-bytes",
        concat_returncode=0, concat_stderr="",
    )

    def fake_popen(cmd, **kwargs):
        e.argvs.append(list(cmd))
        if e.fail_next_start:
            e.fail_next_start = False
            return FakeProc(exit_code=1)
        Path(cmd[-1]).write_bytes(e.segment_bytes)
        return FakeProc()

    def fake_run(cmd, **kwargs):
        e.runs.append(list(cmd))
        if e.concat_returncode == 0:
            Path(cmd[-1]).write_bytes(b"joined-bytes")
        return types.SimpleNamespace(returncode=e.concat_returncode, stdout="", stderr=e.concat_stderr)

    monkeypatch.setattr(rec, "OUT_DIR", tmp_path / "gator_demos")
    monkeypatch.setattr(rec, "_FFMPEG", "ffmpeg")
    monkeypatch.setattr(rec, "_IS_WINDOWS", True)
    monkeypatch.setattr(rec, "_list_screens_windows", lambda: SCREENS)
    monkeypatch.setattr(rec, "_list_screens_mac", lambda: SCREENS)
    monkeypatch.setattr(rec.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rec.subprocess, "run", fake_run)
    monkeypatch.setattr(rec.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(rec.signal, "CTRL_BREAK_EVENT", 1, raising=False)
    monkeypatch.setattr(rec.signal, "SIGSTOP", 19, raising=False)
    monkeypatch.setattr(rec.signal, "SIGCONT", 18, raising=False)
    monkeypatch.setattr(rec, "_start_recording_border",
                        lambda screen, crop: e.borders.append((screen["label"], crop)))
    monkeypatch.setattr(rec, "_stop_recording_border", lambda: e.border_stops.append(1))
    monkeypatch.setattr(rec, "_write_latest_output", lambda data: e.latest.append(data))
    for name, value in {
        "_ffmpeg_proc": None, "_recording_path": None, "_recording_start": None,
        "_paused_at": None, "_paused_elapsed": 0.0, "_segments": [],
        "_session_dir": None, "_session_tag": None,
        "_last_screen_index": 0, "_last_crop": None,
        "_last_start_req": rec.StartRequest(),
    }.items():
        monkeypatch.setattr(rec, name, value, raising=False)
    return e


@pytest.fixture
def client(env):
    app = FastAPI()
    app.include_router(rec.router)
    return TestClient(app)


def _start(client, **overrides):
    r = client.post("/api/recorder/start", json={**CROP, **overrides})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    return r.json()


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_resume_restarts_on_selected_screen_and_crop(client, env):
    _start(client)
    assert client.post("/api/recorder/pause").json()["ok"] is True
    assert client.post("/api/recorder/resume").json()["ok"] is True

    first, resumed = env.argvs
    for argv in (first, resumed):
        assert _flag(argv, "-offset_x") == "2020"
        assert _flag(argv, "-offset_y") == "50"
        assert _flag(argv, "-video_size") == "640x480"
    assert resumed[-1].endswith("seg_01.mp4")


@pytest.mark.parametrize("is_windows", [True, False])
def test_resume_restores_border_on_selected_screen(client, env, monkeypatch, is_windows):
    monkeypatch.setattr(rec, "_IS_WINDOWS", is_windows)
    _start(client)
    assert client.post("/api/recorder/pause").json()["ok"] is True
    assert client.post("/api/recorder/resume").json()["ok"] is True

    expected = ("Display 2", {"x": 100, "y": 50, "w": 640, "h": 480})
    assert env.borders == [expected, expected]


def test_resume_uses_the_clamped_request(client, env):
    _start(client, crop_w=5000, crop_h=5000)
    assert client.post("/api/recorder/pause").json()["ok"] is True
    assert client.post("/api/recorder/resume").json()["ok"] is True

    first, resumed = env.argvs
    assert _flag(first, "-video_size") == "2460x1390"
    assert _flag(resumed, "-video_size") == "2460x1390"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_recorder_capture.py -v`
Expected: `test_resume_restarts_on_selected_screen_and_crop` FAILS on the resumed argv with `ValueError: '-offset_x' is not in list` (the resumed segment falls back to full-screen Display 1). `test_resume_restores_border_on_selected_screen` FAILS (`[('Display 2', ...), ('Display 1', None)] != ...`). `test_resume_uses_the_clamped_request` FAILS (`'1920x1080' != '2460x1390'`).

- [ ] **Step 3: Implement**

In `web/routes/recorder.py`:

1. Directly after `class StartRequest(BaseModel): ...` (ends with `force: bool = False  # ...`) add:

```python
_last_start_req: StartRequest = StartRequest()  # the request the active session started with; resume replays it
```

2. Delete the old declaration above `recorder_resume`:

```python
_last_start_req: StartRequest = StartRequest()
```

(and its now-redundant blank lines).

3. In `recorder_start`, change

```python
    global _last_screen_index, _last_crop
```
to
```python
    global _last_screen_index, _last_crop, _last_start_req
```

4. In `recorder_start`, immediately before the segment start, change

```python
    try:
        proc, seg_path = _start_segment(ffmpeg, req, screens, 0)
```
to
```python
    _last_start_req = req

    try:
        proc, seg_path = _start_segment(ffmpeg, req, screens, 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recorder_capture.py -v`
Expected: all PASS (4 tests + the parametrized pair).

- [ ] **Step 5: Commit**

```bash
git add web/routes/recorder.py tests/test_recorder_capture.py
git commit -m "fix: resume the recorder on the selected screen and crop (#55 item 1)"
```

---

## Group B — Items 2 and 3, backend: failed resume and failed stop are reported

### Task 3: stop never returns a bogus file (issue #55 item 3)

**Files:**
- Modify: `web/routes/recorder.py` (`_stitch_segments`, `recorder_stop`)
- Modify: `tests/test_recorder_capture.py`

**Interfaces:**
- Consumes: `env`, `client`, `_start` (Task 2).
- Produces: `recorder_stop` failure contract `500 {"ok": False, "status": "idle", "error": str, "segments": [str], "session_dir": str}` consumed by the widget in Task 5; success payload unchanged (`ok, status, path, size_bytes, elapsed, segments`). `_stitch_segments(ffmpeg, segments, out_path)` raises `RuntimeError` on a failed concat.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_recorder_capture.py`:

```python
def _pause_resume(client):
    assert client.post("/api/recorder/pause").json()["ok"] is True
    assert client.post("/api/recorder/resume").json()["ok"] is True


def test_stop_joins_segments_with_concat_and_cleans_up(client, env):
    _start(client)
    _pause_resume(client)
    r = client.post("/api/recorder/stop")
    body = r.json()

    assert r.status_code == 200 and body["ok"] is True and body["segments"] == 2
    argv = env.runs[0]
    assert argv[:6] == ["ffmpeg", "-y", "-f", "concat", "-safe", "0"]
    assert argv[-3:-1] == ["-c", "copy"] and argv[-1] == body["path"]
    assert body["size_bytes"] == len(b"joined-bytes")
    assert not (Path(body["path"]).parent / "concat_list.txt").exists()
    assert env.latest == [{"raw": body["path"], "final": body["path"]}]


def test_stop_with_one_segment_needs_no_ffmpeg_run(client, env):
    _start(client)
    body = client.post("/api/recorder/stop").json()

    assert body["ok"] is True and body["size_bytes"] == len(b"segment-bytes")
    assert env.runs == []


def test_stop_reports_concat_failure_and_writes_nothing(client, env):
    _start(client)
    _pause_resume(client)
    env.concat_returncode = 1
    env.concat_stderr = "Invalid data found when processing input"
    r = client.post("/api/recorder/stop")
    body = r.json()

    assert r.status_code == 500 and body["ok"] is False and body["status"] == "idle"
    assert "Invalid data found" in body["error"]
    assert len(body["segments"]) == 2
    assert body["session_dir"] == str(rec._session_dir)
    assert env.latest == []
    assert rec._paused_at is None and env.border_stops
    assert not (rec._session_dir / "concat_list.txt").exists()


def test_stop_with_no_captured_video_is_an_error(client, env):
    env.segment_bytes = b""
    _start(client)
    r = client.post("/api/recorder/stop")

    assert r.status_code == 500
    assert "No video was captured" in r.json()["error"]
    assert env.latest == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_recorder_capture.py -v -k "stop"`
Expected: `test_stop_reports_concat_failure_and_writes_nothing` FAILS (`assert 200 == 500`: the old code swallows the failure; also `check=True` makes the fake's `returncode` ignored so the old path never even sees the failure and reports ok), `test_stop_with_no_captured_video_is_an_error` FAILS (`200 == 500`), the others may PASS already.

- [ ] **Step 3: Implement**

Replace `_stitch_segments` in `web/routes/recorder.py` with:

```python
def _stitch_segments(ffmpeg: str, segments: list[Path], out_path: Path) -> Path:
    if len(segments) == 1:
        import shutil as _sh
        _sh.copy2(segments[0], out_path)
        return out_path
    concat_file = out_path.parent / "concat_list.txt"
    try:
        with open(concat_file, "w") as f:
            for s in segments:
                f.write(f"file '{s}'\n")
        result = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(out_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "").strip()[-400:] or f"ffmpeg exited with {result.returncode}")
    finally:
        concat_file.unlink(missing_ok=True)
    return out_path
```

In `recorder_stop`, replace everything from `ffmpeg = _FFMPEG or _find_ffmpeg()` down to the end of the function with:

```python
    ffmpeg = _FFMPEG or _find_ffmpeg()
    final_path = _session_dir / f"{_session_tag}_final.mp4"
    segments = [s for s in _segments if _file_size(s) > 0]

    error = None
    final = None
    if not segments:
        error = "No video was captured — check ffmpeg_log.txt"
    else:
        try:
            final = await asyncio.to_thread(_stitch_segments, ffmpeg, segments, final_path)
        except Exception as exc:
            error = f"Could not join recording segments: {exc}"

    _paused_at = None
    _paused_elapsed = 0.0
    _stop_recording_border()

    if error:
        return JSONResponse(status_code=500, content={
            "ok": False, "status": "idle", "error": error,
            "segments": [str(s) for s in _segments],
            "session_dir": str(_session_dir),
        })

    # Persist the raw recording path server-side so the Phase 3 narration widget
    # can fetch it via /api/recorder/latest-output without any path embedded in JS.
    _write_latest_output({"raw": str(final), "final": str(final)})

    return {
        "ok": True, "status": "idle",
        "path": str(final),
        "size_bytes": _file_size(final),
        "elapsed": elapsed,
        "segments": len(_segments),
    }
```

(Keep SP3's `final_path`/`_write_latest_output` edits if they have landed: only the stitch/error control flow above is this task's change.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recorder_capture.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/routes/recorder.py tests/test_recorder_capture.py
git commit -m "fix: report a failed recording join instead of returning the last segment (#55 item 3)"
```

### Task 4: a failed Windows resume leaves clean, retryable state (issue #55 item 2)

**Files:**
- Modify: `web/routes/recorder.py` (`recorder_resume`, Windows branch)
- Modify: `tests/test_recorder_capture.py`

**Interfaces:**
- Consumes: `env.fail_next_start`, `_start`, `_pause_resume` helpers (Tasks 2–3).
- Produces: resume failure contract `500 {"ok": False, "error": "ffmpeg failed to restart — check ffmpeg_log.txt", "log": "<session_dir>/ffmpeg_log.txt"}` consumed by the widget (Task 5); `_segments` only ever contains segments whose ffmpeg process survived start.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recorder_capture.py`:

```python
def test_failed_restart_stays_paused_and_can_be_retried(client, env):
    _start(client)
    assert client.post("/api/recorder/pause").json()["ok"] is True

    env.fail_next_start = True
    r = client.post("/api/recorder/resume")
    body = r.json()
    assert r.status_code == 500 and body["ok"] is False
    assert "ffmpeg_log.txt" in body["error"] and body["log"].endswith("ffmpeg_log.txt")
    assert len(rec._segments) == 1
    assert rec._paused_at is not None
    assert rec._ffmpeg_proc is None

    retry = client.post("/api/recorder/resume")
    assert retry.json()["ok"] is True
    assert len(rec._segments) == 2
    assert env.argvs[-1][-1].endswith("seg_01.mp4")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_recorder_capture.py::test_failed_restart_stays_paused_and_can_be_retried -v`
Expected: FAIL on `"ffmpeg_log.txt" in body["error"]` (current message is `"ffmpeg failed to restart"` with no `log`).

- [ ] **Step 3: Implement**

In `recorder_resume`, replace the Windows block

```python
        try:
            proc, seg_path = _start_segment(ffmpeg, _last_start_req, screens, seg_index)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
        _ffmpeg_proc = proc
        _recording_path = seg_path
        _segments.append(seg_path)
        await asyncio.sleep(0.4)
        if _ffmpeg_proc.poll() is not None:
            return JSONResponse(status_code=500, content={"ok": False, "error": "ffmpeg failed to restart"})
```

with:

```python
        try:
            proc, seg_path = _start_segment(ffmpeg, _last_start_req, screens, seg_index)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
        await asyncio.sleep(0.4)
        if proc.poll() is not None:
            _ffmpeg_proc = None
            return JSONResponse(status_code=500, content={
                "ok": False,
                "error": "ffmpeg failed to restart — check ffmpeg_log.txt",
                "log": str(_session_dir / "ffmpeg_log.txt"),
            })
        _ffmpeg_proc = proc
        _recording_path = seg_path
        _segments.append(seg_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recorder_capture.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/routes/recorder.py tests/test_recorder_capture.py
git commit -m "fix: keep a failed Windows resume paused and retryable (#55 item 2)"
```

---

## Group C — Items 2 and 3, widget: failures are visible, no `()`

### Task 5: recorder widget shows action failures and formats the completion message

**Files:**
- Modify: `web/skills/gator-demo-recorder/SKILL.md` (first `html:widget` block; the CRITICAL RULES "File path" bullet)
- Create: `tests/recorder_widget.test.js`

**Interfaces:**
- Consumes: backend contracts from Tasks 3–4 (`{ok:false, error, session_dir?}`).
- Produces: widget functions `actionFailed(err, data, label)` and variable `_actionError`; completion message `Recording complete. File: <path>[ (<size>MB)]. Please analyze it and draft a narration script.` consumed by SKILL.md Phase 2 (Task 10).

- [ ] **Step 1: Write the failing test**

Create `tests/recorder_widget.test.js`:

```js
// The recorder widget template is extracted from SKILL.md and run against a stub DOM/fetch.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const skill = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'skills', 'gator-demo-recorder', 'SKILL.md'), 'utf8');

function widgetScript() {
  const start = skill.indexOf('```html:widget');
  assert(start >= 0, 'first html:widget block found');
  const end = skill.indexOf('\n```', start + 1);
  const m = skill.slice(start, end).match(/<script>([\s\S]*?)<\/script>/);
  assert(m, 'widget <script> found');
  return m[1];
}

function makeEnv(routes) {
  const els = {};
  const el = (id) => els[id] || (els[id] = {
    id, textContent: '', className: '', innerHTML: '', style: {}, disabled: false,
    checked: true, value: '0', onclick: null, appendChild() {},
  });
  const posted = [];
  const fetched = [];
  const ctx = {
    document: {
      getElementById: el,
      createElement: () => ({ appendChild() {}, value: '', textContent: '' }),
      addEventListener() {},
      visibilityState: 'visible',
    },
    setInterval() {},
    fetch(url, opts) {
      const action = url.split('/api/recorder/')[1];
      fetched.push({ action, body: opts && opts.body });
      const body = routes[action] || (action === 'screens' ? { screens: [] } : { status: 'idle' });
      return Promise.resolve({ json: () => Promise.resolve(body) });
    },
    parent: { postMessage: (m) => posted.push(m) },
  };
  ctx.window = ctx;
  ctx.addEventListener = () => {};
  vm.createContext(ctx);
  vm.runInContext(widgetScript(), ctx);
  const flush = () => new Promise((r) => setImmediate(r));
  return { ctx, el, posted, fetched, routes, flush };
}

test('a failed resume is shown and survives the status poll until the next action', async () => {
  const { ctx, el, routes, flush } = makeEnv({
    resume: { ok: false, error: 'ffmpeg failed to restart — check ffmpeg_log.txt' },
  });
  await flush();
  ctx.render({ status: 'paused', elapsed: 5 });
  ctx.doResume();
  await flush();

  assert.strictEqual(el('status').className, 'status error');
  assert(el('status').textContent.includes('ffmpeg failed to restart'));

  ctx.render({ status: 'paused', elapsed: 5 });
  assert(el('status').textContent.includes('ffmpeg failed to restart'), 'poll must not erase the error');
  assert.strictEqual(el('btn-resume').style.display, '', 'Resume stays available for a retry');

  routes.resume = { ok: true, status: 'recording', elapsed: 5 };
  ctx.doResume();
  await flush();
  ctx.render({ status: 'recording', elapsed: 6 });
  assert.strictEqual(el('status').className, 'status recording');
});

test('a failed pause is shown', async () => {
  const { ctx, el, flush } = makeEnv({ pause: { ok: false, error: 'Not recording' } });
  await flush();
  ctx.render({ status: 'recording', elapsed: 3 });
  ctx.doPause();
  await flush();

  assert.strictEqual(el('status').className, 'status error');
  assert(el('status').textContent.includes('Not recording'));
});

test('stop success message carries the size, or no parentheses when it is unknown', async () => {
  const cases = [
    [3145728, ' (3.0MB)', '✓ Saved 3.0MB'],
    [0, '', '✓ Saved'],
  ];
  for (const [bytes, sizePart, saved] of cases) {
    const { ctx, el, posted, flush } = makeEnv({
      stop: { ok: true, path: 'C:\\demos\\final.mp4', size_bytes: bytes },
    });
    await flush();
    ctx.doStop();
    await flush();

    assert.strictEqual(el('status').textContent, saved);
    assert.strictEqual(
      posted[0].text,
      'Recording complete. File: C:\\demos\\final.mp4' + sizePart +
        '. Please analyze it and draft a narration script.');
    assert(!posted[0].text.includes('()'));
  }
});

test('a failed stop shows the error with the session folder and tells the chat nothing', async () => {
  const { ctx, el, posted, fetched, flush } = makeEnv({
    stop: { ok: false, error: 'Could not join recording segments: bad', session_dir: 'C:\\demos\\demo_1' },
  });
  await flush();
  ctx.doStop();
  await flush();

  assert.strictEqual(el('status').className, 'status error');
  assert(el('status').textContent.includes('Stop error: Could not join recording segments'));
  assert(el('status').textContent.includes('C:\\demos\\demo_1'));
  assert.strictEqual(posted.length, 0);
  assert(!fetched.some((f) => f.action === 'notify'));
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd shell && node --test ../tests/recorder_widget.test.js`
Expected: FAIL — e.g. `a failed resume is shown…`: `'status' !== 'status error'` (the old `doResume` ignores the response); the size test fails on `'✓ Saved '` vs `'✓ Saved'`.

- [ ] **Step 3: Implement (all edits in the first `html:widget` block of `SKILL.md`)**

1. State line:

```js
var _crop = null, _busy = false, _lastStatus = 'idle', _stopPath = '';
```
becomes
```js
var _crop = null, _busy = false, _lastStatus = 'idle', _stopPath = '';
var _actionError = '';
```

2. Insert directly above `function fmt(s) {`:

```js
function actionFailed(err, data, label) {
  if (!err && data && data.ok) return false;
  _actionError = label + ': ' + ((data && data.error) || (err && err.message) || 'request failed');
  if (data && data.session_dir) _actionError += ' (' + data.session_dir + ')';
  var st = document.getElementById('status');
  st.className = 'status error';
  st.textContent = _actionError;
  return true;
}

```

3. End of `render(s)`: change

```js
    br.disabled=false; bp.disabled=true; bp.style.display=''; bres.style.display='none'; bs.disabled=true;
  }
}
```
to
```js
    br.disabled=false; bp.disabled=true; bp.style.display=''; bres.style.display='none'; bs.disabled=true;
  }
  if (_actionError) { st.className = 'status error'; st.textContent = _actionError; }
}
```

4. `doRecord`: change `_busy = true; _stopPath = '';` to `_busy = true; _stopPath = ''; _actionError = '';`, and replace

```js
    _busy = false;
    if (err || !data || !data.ok) {
      document.getElementById('status').className = 'status error';
      document.getElementById('status').textContent = 'Error: ' + ((data&&data.error)||String(err));
    }
```
with
```js
    _busy = false;
    actionFailed(err, data, 'Error');
```

5. Replace `doPause` and `doResume`:

```js
function doPause() {
  _busy = true; _actionError = '';
  apiFetch('pause', null, function(err, data) { _busy = false; actionFailed(err, data, 'Pause error'); });
}

function doResume() {
  _busy = true; _actionError = '';
  apiFetch('resume', null, function(err, data) { _busy = false; actionFailed(err, data, 'Resume error'); });
}
```

6. `doStop`: change its first line `_busy = true;` to `_busy = true; _actionError = '';`; change `document.getElementById('status').textContent = '✓ Saved ' + mb;` to

```js
      document.getElementById('status').textContent = '✓ Saved' + (mb ? ' ' + mb : '');
```

change the message line to

```js
      var msg = 'Recording complete. File: '+_stopPath+(mb ? ' ('+mb+')' : '')+'. Please analyze it and draft a narration script.';
```

and replace the `else` branch

```js
    } else {
      document.getElementById('status').className = 'status error';
      document.getElementById('status').textContent = 'Stop error: ' + ((data&&data.error)||'');
    }
```
with
```js
    } else {
      actionFailed(err, data, 'Stop error');
    }
```

7. In the CRITICAL RULES section, change the "File path" bullet's last sentence `It is always the value between `"File: "` and `" ("`.` to ``It is the value between `"File: "` and `" ("` — or, when no size is shown, `". Please"`.``

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd shell && node --test ../tests/recorder_widget.test.js`
Expected: 4 tests pass, 0 fail.

- [ ] **Step 5: Commit**

```bash
git add web/skills/gator-demo-recorder/SKILL.md tests/recorder_widget.test.js
git commit -m "fix: show recorder action failures and omit empty size in the completion message (#55 items 2, 3)"
```

---

## Group D — Item 4: prompt-bar Stop click

### Task 6: diagnose on a real run (manual, no code, no commit)

**Files:** none (findings go in the PR description).

**Interfaces:** Produces: a recorded answer to "do mouse events reach the page while fullscreen and streaming?", which decides whether Task 7 is the whole fix.

- [ ] **Step 1: Start the app and begin a long streaming turn**

Run the Electron shell as usual, enter fullscreen (the existing fullscreen control), and send any prompt that streams for 30+ seconds.

- [ ] **Step 2: Attach the event trace in the renderer DevTools console**

```js
['pointerdown','mousedown','mouseup','click'].forEach(t =>
  window.addEventListener(t, e => console.log(t, e.target.id || e.target.tagName, e.clientX, e.clientY, e.isTrusted), true));
const r = document.getElementById('send-btn').getBoundingClientRect();
console.log('hit', document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.outerHTML.slice(0, 120), r);
```

- [ ] **Step 3: Click the red Stop control with the mouse; record what happened**

Expected observations to note in the PR, pick whichever applies:
- `hit` is not `#send-btn` or a child → an overlay is stealing the point (name it).
- `mousedown`/`mouseup` log but no `click` → press and release landed on different elements (Task 7 fixes this).
- Nothing logs → events never reach the page: a shell-level (Electron) issue. Open a separate GitHub issue for it; Task 7 still ships.
- `click` logs on `#send-btn` but the turn does not stop → `_onStop` was detached; Task 7's persistent listener fixes this.

---

### Task 7: delegated Stop click dispatcher (defensive fix)

**Files:**
- Modify: `web/static/app.js` (after `let history = [];`; `_onStop`; the `sendBtn.addEventListener('click', _onStop)` line; `_detachStop`)
- Create: `tests/stop_button_click.test.js`

**Interfaces:**
- Produces: `_shouldStopFromClick(e, btn, rect, streaming) -> boolean` (module-level function in `app.js`) and `_activeStops: Set<() => void>`; each turn registers with `_activeStops.add(_onStop)` and unregisters in `_detachStop`.

- [ ] **Step 1: Write the failing test**

Create `tests/stop_button_click.test.js`:

```js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function loadPredicate() {
  const m = source.match(/function _shouldStopFromClick\([^)]*\)\s*\{[\s\S]*?\n\}/);
  assert(m, '_shouldStopFromClick found in app.js');
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(m[0], ctx);
  return ctx._shouldStopFromClick;
}

const child = {};
const other = {};
const btn = { contains: (t) => t === btn || t === child };
const rect = { left: 100, right: 140, top: 200, bottom: 240 };
const ev = (o) => Object.assign({ button: 0, target: btn, clientX: 0, clientY: 0 }, o);

test('_shouldStopFromClick decides from target, position, button and streaming state', () => {
  const f = loadPredicate();
  assert.strictEqual(f(ev({}), btn, rect, true), true, 'target is the button');
  assert.strictEqual(f(ev({ target: child }), btn, rect, true), true, 'target is a child');
  assert.strictEqual(f(ev({ target: other, clientX: 120, clientY: 220 }), btn, rect, true), true,
    'press/release moved the click to an ancestor, but the point is on the button');
  assert.strictEqual(f(ev({ target: other, clientX: 10, clientY: 10 }), btn, rect, true), false, 'outside the button');
  assert.strictEqual(f(ev({}), btn, rect, false), false, 'not streaming');
  assert.strictEqual(f(ev({ button: 2 }), btn, rect, true), false, 'non-primary button');
});

test('stop is dispatched through one delegated listener, not a per-turn button listener', () => {
  assert(!source.includes("sendBtn.addEventListener('click', _onStop)"));
  assert(source.includes('_activeStops.add(_onStop)'));
  assert(source.includes('_activeStops.delete(_onStop)'));
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd shell && node --test ../tests/stop_button_click.test.js`
Expected: FAIL with `_shouldStopFromClick found in app.js`.

- [ ] **Step 3: Implement**

In `web/static/app.js`:

1. Directly after `let history = [];` (just below `const sendBtn = document.getElementById('send-btn');`) add:

```js
// Stop dispatch: one persistent capture-phase listener; click lands on the common ancestor of press and release.
const _activeStops = new Set();
function _shouldStopFromClick(e, btn, rect, streaming) {
  if (!streaming || e.button !== 0) return false;
  if (btn.contains(e.target)) return true;
  return e.clientX >= rect.left && e.clientX <= rect.right &&
         e.clientY >= rect.top && e.clientY <= rect.bottom;
}
document.addEventListener('click', (e) => {
  if (!_activeStops.size) return;
  const streaming = sendBtn.classList.contains('is-streaming');
  if (!_shouldStopFromClick(e, sendBtn, sendBtn.getBoundingClientRect(), streaming)) return;
  e.preventDefault();
  [..._activeStops].forEach((stop) => stop());
}, true);
```

2. In the chat-turn setup, change

```js
  const _onStop = () => {
    if (_activeTabId !== requestTabId) return;
    _userStopped = true;
```
to
```js
  const _onStop = () => {
    if (_userStopped) return;
    if (_activeTabId !== requestTabId) return;
    _userStopped = true;
```

3. Replace `sendBtn.addEventListener('click', _onStop);` with `_activeStops.add(_onStop);`.

4. In `_detachStop`, replace `sendBtn.removeEventListener('click', _onStop);` with `_activeStops.delete(_onStop);`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd shell && node --test ../tests/stop_button_click.test.js ../tests/chat_done_late.test.js`
Expected: all pass, 0 fail.

- [ ] **Step 5: Manual re-check, then commit**

Repeat Task 6 Steps 1 and 3 (without the trace) in fullscreen: the mouse click now stops the turn. Record the result in the PR.

```bash
git add web/static/app.js tests/stop_button_click.test.js
git commit -m "fix: dispatch the prompt-bar Stop click through one persistent capture listener (#55 item 4)"
```

---

## Group E — Item 5: video analysis without an LLM-built runner

### Task 8: `analyze_sequence` rejects more than 8 frames up front

**Files:**
- Modify: `web/skills/_always_on/tools.py` (`_tool_describe_images`, `_analyze_frame_sequence`, constants)
- Create: `tests/test_describe_images_video.py`

**Interfaces:**
- Produces: module constants `_MAX_SEQUENCE_FRAMES = 8` and `_FRAME_MIN_INTERVAL_SEC = 5`; `describe_images(task='analyze_sequence')` returns `{"ok": False, "error": "analyze_sequence accepts at most 8 frames, got N. For a video file use task='analyze_video' with video_path."}` when `len(image_paths) > 8`, before the existence check.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_describe_images_video.py`:

```python
from skills._always_on import tools as ao

HANDLER = ao.TOOL_HANDLERS["describe_images"]


async def test_analyze_sequence_rejects_more_than_eight_frames():
    paths = [f"/tmp/code_runner_out/frames/frame_{i:04d}.png" for i in range(42)]
    r = await HANDLER(task="analyze_sequence", image_paths=paths)

    assert r["ok"] is False
    assert "at most 8" in r["error"] and "analyze_video" in r["error"]
    assert "do not exist" not in r["error"]


async def test_analyze_sequence_with_eight_missing_frames_still_reports_missing():
    paths = [f"/tmp/code_runner_out/frames/frame_{i:04d}.png" for i in range(8)]
    r = await HANDLER(task="analyze_sequence", image_paths=paths)

    assert r["ok"] is False
    assert "do not exist" in r["error"]
```

- [ ] **Step 2: Run to verify the first fails**

Run: `uv run pytest tests/test_describe_images_video.py -v`
Expected: `test_analyze_sequence_rejects_more_than_eight_frames` FAILS (`'at most 8' in "Frame sequence analysis failed: 42 of 42 image path(s) do not exist…"`); the second PASSES.

- [ ] **Step 3: Implement**

In `web/skills/_always_on/tools.py`:

1. Below `_IMAGE_MEDIA_TYPES = {...}` add:

```python
_MAX_SEQUENCE_FRAMES = 8
_FRAME_MIN_INTERVAL_SEC = 5
```

2. In `_analyze_frame_sequence`, change `MAX_FRAMES = 8` to `MAX_FRAMES = _MAX_SEQUENCE_FRAMES`.

3. In `_tool_describe_images`, directly after the secrets check and before `if task == "analyze_sequence" and image_paths:` add:

```python
    if task == "analyze_sequence" and len(image_paths or []) > _MAX_SEQUENCE_FRAMES:
        return {
            "ok": False,
            "error": (
                f"analyze_sequence accepts at most {_MAX_SEQUENCE_FRAMES} frames, got {len(image_paths)}. "
                "For a video file use task='analyze_video' with video_path."
            ),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_describe_images_video.py tests/code_sandbox/test_secrets_guard.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_always_on/tools.py tests/test_describe_images_video.py
git commit -m "fix: reject analyze_sequence calls with more than 8 frames before touching the filesystem (#55 item 5)"
```

### Task 9: `describe_images(task='analyze_video')`

**Files:**
- Modify: `web/skills/_always_on/tools.py` (imports, `TOOL_DEFS` entry, `_tool_describe_images`, new `_extract_video_frames` and `_analyze_video`)
- Modify: `tests/test_describe_images_video.py`

**Interfaces:**
- Consumes: `_MAX_SEQUENCE_FRAMES`, `_FRAME_MIN_INTERVAL_SEC`, `_analyze_frame_sequence(image_paths: list, fps: float) -> dict | None`; `routes.recorder._FFMPEG`, `_FFPROBE`, `_find_ffmpeg()`, `_find_ffprobe()`.
- Produces: `_tool_describe_images(task, image_paths=None, fields=None, fps=0.2, video_path=None)`; `task='analyze_video'` returns the `_analyze_frame_sequence` result verbatim (`{"ok": True, "task": "analyze_sequence", "timeline": [...], ...}`) or `{"ok": False, "error": str}`. Consumed by SKILL.md Phase 2 (Task 10).

- [ ] **Step 1: Write the failing tests**

Replace the top of `tests/test_describe_images_video.py` (imports) with, and append the new tests after the Task 8 tests:

```python
import types
from pathlib import Path

import pytest

from routes import recorder as rec
from skills._always_on import tools as ao

HANDLER = ao.TOOL_HANDLERS["describe_images"]
```

```python
@pytest.fixture
def media(monkeypatch, tmp_path):
    video = tmp_path / "demo_final.mp4"
    video.write_bytes(b"video")
    state = types.SimpleNamespace(video=video, duration="210.0\n", calls=[], analyzed=[], frame_dirs=[],
                                  frame_returncode=0)

    def fake_run(cmd, **kwargs):
        state.calls.append((list(cmd), kwargs))
        if "ffprobe" in str(cmd[0]):
            return types.SimpleNamespace(returncode=0, stdout=state.duration, stderr="")
        if state.frame_returncode == 0:
            Path(cmd[-1]).write_bytes(b"png")
        return types.SimpleNamespace(returncode=state.frame_returncode, stdout="", stderr="decode error")

    async def fake_analyze(paths, fps):
        state.analyzed.append((list(paths), fps))
        state.frame_dirs.append(Path(paths[0]).parent)
        return {"ok": True, "task": "analyze_sequence", "timeline": []}

    monkeypatch.setattr(rec, "_FFMPEG", "ffmpeg-aigator")
    monkeypatch.setattr(rec, "_FFPROBE", "ffprobe-aigator")
    monkeypatch.setattr(ao.subprocess, "run", fake_run)
    monkeypatch.setattr(ao, "_analyze_frame_sequence", fake_analyze)
    return state


async def test_analyze_video_extracts_eight_evenly_spaced_frames(media):
    r = await HANDLER(task="analyze_video", video_path=str(media.video))

    assert r["ok"] is True
    paths, fps = media.analyzed[0]
    assert len(paths) == 8
    assert fps == pytest.approx(1 / 26.25)

    probe = media.calls[0][0]
    assert probe[0] == "ffprobe-aigator" and probe[-1] == str(media.video)
    frame_cmds = [c for c, _ in media.calls[1:]]
    assert [c[c.index("-ss") + 1] for c in frame_cmds] == [f"{i * 26.25:.3f}" for i in range(8)]
    for cmd, kwargs in media.calls:
        assert isinstance(cmd, list) and not kwargs.get("shell")
    assert not media.frame_dirs[0].exists(), "temporary frames are removed"


async def test_analyze_video_short_clip_uses_one_frame_per_five_seconds(media):
    media.duration = "12.0\n"
    await HANDLER(task="analyze_video", video_path=str(media.video))

    frame_cmds = [c for c, _ in media.calls[1:]]
    assert [c[c.index("-ss") + 1] for c in frame_cmds] == ["0.000", "4.000", "8.000"]


async def test_analyze_video_requires_video_path():
    r = await HANDLER(task="analyze_video")
    assert r["ok"] is False and "video_path" in r["error"]


async def test_analyze_video_reports_missing_file(media, tmp_path):
    r = await HANDLER(task="analyze_video", video_path=str(tmp_path / "nope.mp4"))
    assert r["ok"] is False and "not found" in r["error"].lower()
    assert media.calls == []


async def test_analyze_video_reports_missing_ffmpeg(media, monkeypatch):
    monkeypatch.setattr(rec, "_FFMPEG", None)
    monkeypatch.setattr(rec, "_FFPROBE", None)
    monkeypatch.setattr(rec, "_find_ffmpeg", lambda: None)
    monkeypatch.setattr(rec, "_find_ffprobe", lambda: None)
    r = await HANDLER(task="analyze_video", video_path=str(media.video))

    assert r["ok"] is False and "ffmpeg" in r["error"]
    assert media.calls == []


async def test_analyze_video_reports_frame_extraction_failure_and_cleans_up(media):
    media.frame_returncode = 1
    r = await HANDLER(task="analyze_video", video_path=str(media.video))

    assert r["ok"] is False and "could not extract a frame" in r["error"]
    assert media.analyzed == []


async def test_analyze_video_refuses_secrets_path(media, monkeypatch):
    import sandbox.paths as sp
    monkeypatch.setattr(sp, "is_secrets_path", lambda p: True)
    r = await HANDLER(task="analyze_video", video_path=str(media.video))

    assert r == {"ok": False, "error": sp.PROTECTED_MSG}
    assert media.calls == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_describe_images_video.py -v`
Expected: the `media`-based tests ERROR at fixture setup with `AttributeError: module 'skills._always_on.tools' has no attribute 'subprocess'`; `test_analyze_video_requires_video_path` FAILS with `TypeError: _tool_describe_images() got an unexpected keyword argument 'video_path'`.

- [ ] **Step 3: Implement**

In `web/skills/_always_on/tools.py`:

1. Imports: change

```python
import logging
import re
```
to
```python
import logging
import math
import re
import subprocess
import tempfile
```

2. `TOOL_DEFS` entry for `describe_images`: append to the description string

```python
            "task='analyze_video': analyze a screen-recording video file given video_path — frames are extracted for you "
            "(max 8, evenly spaced); prefer this over extracting frames yourself. "
```
(place it before the `"Use analyze_sequence for video keyframe analysis…"` sentence), add `"analyze_video"` to the `task` enum (`["describe", "compare", "extract_data", "assess", "analyze_sequence", "analyze_video"]`), and insert between the `image_paths` and `fields` properties:

```python
                "video_path": {
                    "type": "string",
                    "description": (
                        "For analyze_video: absolute path of the video file to analyze. "
                        "Frames are extracted server-side (at most 8, evenly spaced)."
                    ),
                },
```

3. Change the signature and the secrets check at the top of `_tool_describe_images`:

```python
async def _tool_describe_images(task: str, image_paths: list | None = None,
                               fields: list | None = None, fps: float = 0.2,
                               video_path: str | None = None) -> dict:
    from sandbox.paths import PROTECTED_MSG, is_secrets_path
    candidates = list(image_paths or []) + ([video_path] if video_path else [])
    if any(isinstance(p, str) and is_secrets_path(p) for p in candidates):
        return {"ok": False, "error": PROTECTED_MSG}
    if task == "analyze_video":
        if not video_path:
            return {"ok": False, "error": "analyze_video requires video_path."}
        return await _analyze_video(video_path)
```

(keep the Task 8 `analyze_sequence` >8 guard right after this block).

4. Add above `_tool_describe_images`:

```python
def _extract_video_frames(video: Path, ffmpeg: str, ffprobe: str, out_dir: Path) -> tuple[list[str], float]:
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True,
    )
    try:
        duration = float((probe.stdout or "").strip())
    except ValueError:
        duration = 0.0
    if probe.returncode != 0 or duration <= 0:
        raise RuntimeError(
            f"Could not read the video duration with ffprobe: {(probe.stderr or '').strip()[-300:]}")
    n = min(_MAX_SEQUENCE_FRAMES, max(1, math.ceil(duration / _FRAME_MIN_INTERVAL_SEC)))
    interval = duration / n
    paths = []
    for i in range(n):
        out = out_dir / f"frame_{i + 1:04d}.png"
        r = subprocess.run(
            [ffmpeg, "-y", "-ss", f"{i * interval:.3f}", "-i", str(video), "-frames:v", "1", str(out)],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(
                f"ffmpeg could not extract a frame at {i * interval:.1f}s: {(r.stderr or '').strip()[-300:]}")
        paths.append(str(out))
    return paths, interval


async def _analyze_video(video_path: str) -> dict:
    import asyncio
    import shutil
    from routes import recorder as _rec

    video = Path(video_path)
    if not video.is_file():
        return {"ok": False, "error": f"Video not found: {video_path}"}
    ffmpeg = _rec._FFMPEG or _rec._find_ffmpeg()
    ffprobe = _rec._FFPROBE or _rec._find_ffprobe()
    if not ffmpeg or not ffprobe:
        return {"ok": False, "error": (
            "ffmpeg/ffprobe not found. Install: `winget install Gyan.FFmpeg` (Windows) "
            "or `brew install ffmpeg` (macOS).")}
    frames_dir = Path(tempfile.mkdtemp(prefix="gator_frames_"))
    try:
        try:
            paths, interval = await asyncio.to_thread(_extract_video_frames, video, ffmpeg, ffprobe, frames_dir)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        result = await _analyze_frame_sequence(paths, 1 / interval)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
    if result is None:
        return {"ok": False, "error": "Frame analysis failed: no frame could be read."}
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_describe_images_video.py tests/code_sandbox/test_secrets_guard.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_always_on/tools.py tests/test_describe_images_video.py
git commit -m "feat: add describe_images analyze_video that extracts frames server-side (#55 item 5)"
```

### Task 10: SKILL.md Phase 2 uses `analyze_video`

**Files:**
- Modify: `web/skills/gator-demo-recorder/SKILL.md` (Phase 0/overview line ~15, Phase 2, Phase 5 cleanup lines ~909 and ~918)
- Modify: `tests/recorder_widget.test.js` (one guard test)

**Interfaces:**
- Consumes: `describe_images(task='analyze_video', video_path=...)` (Task 9) and the completion message format (Task 5).

- [ ] **Step 1: Write the failing test**

Append to `tests/recorder_widget.test.js`:

```js
test('Phase 2 analyzes the recording through analyze_video, not a runner script', () => {
  const phase2 = skill.slice(skill.indexOf('## Phase 2: Analyze'), skill.indexOf('## Phase 3'));
  assert(phase2.includes("describe_images(task='analyze_video'"));
  assert(!phase2.includes('subprocess.run'));
  assert(!phase2.includes('frame_%04d'));
  assert(!skill.includes('delete the `frames/`'));
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd shell && node --test ../tests/recorder_widget.test.js`
Expected: the new test FAILS (`Phase 2` still contains `subprocess.run`).

- [ ] **Step 3: Implement**

In `SKILL.md`:

1. Overview line `Phase 2: ANALYZE            — extract keyframes, describe_images, build scene summary` becomes `Phase 2: ANALYZE            — describe_images(analyze_video), build scene summary`.

2. In Phase 2, replace step 1's sentence and everything from the line starting `2. Get ffmpeg path:` through the line `Returns: `{timeline: [...], summary: "..."}`` (this removes the python snippet, "Step 2 — Analyze frames", and the `analyze_sequence` example) with:

```markdown
2. Proceed immediately — do not ask the user for the path, and do not run ffmpeg or ffprobe yourself.

**Step 1 — Analyze the video**: call `describe_images(task='analyze_video', video_path='<path>')`. The tool finds ffmpeg/ffprobe, extracts up to 8 evenly spaced keyframes (at least ~5 s apart) into a private temporary folder, analyzes them, and deletes them.

**Do not ask the user to upload or drag-and-drop frames.**

Returns: `{timeline: [{frame, time_sec, time_label, description}, ...], summary: "..."}`
```

and rewrite step 1 to: `1. Extract the video path: it is the text between `"File: "` and the next `" ("` — or, when the message shows no size, up to `". Please"`. Example: `"Recording complete. File: C:\Users\...\final.mp4 (46MB). Please analyze it…"` → path = `C:\Users\...\final.mp4``.

3. Rename `**Step 3 — Build scene summary**` to `**Step 2 — Build scene summary**`.

4. Phase 5: change the delete-intermediates message `Please delete the frames/ and tts_work/ intermediates for the current session.` to `Please delete the tts_work/ intermediates for the current session.`, and change `delete the `frames/` and `tts_work/` directories after delivery` to `delete the `tts_work/` directory after delivery`.

5. Confirm nothing else references the removed pieces:

```bash
grep -n "frames/\|Step 3 — Build\|analyze_sequence\|frame_%04d" web/skills/gator-demo-recorder/SKILL.md
```
Expected: no output. (`docs/demo-recorder-plan.md` is historical and stays as is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd shell && node --test ../tests/recorder_widget.test.js`
Expected: 5 tests pass, 0 fail.

- [ ] **Step 5: Commit**

```bash
git add web/skills/gator-demo-recorder/SKILL.md tests/recorder_widget.test.js
git commit -m "fix: have the demo recorder skill analyze the recording with analyze_video (#55 item 5)"
```

---

## Final verification

### Task 11: full suites and the manual item 2 diagnostic

**Files:** none.

- [ ] **Step 1: Run the Python suite as CI does**

Run: `uv run coverage run --source=web,packaging --omit='*/tests/*' -m pytest tests -q`
Expected: all PASS, including `tests/test_csrf_route_inventory.py` (no routes were added; `tests/csrf_route_baseline.txt` is untouched: `git diff --stat -- tests/csrf_route_baseline.txt` prints nothing).

- [ ] **Step 2: Run the JS suite**

Run: `cd shell && npm test`
Expected: 0 failures.

- [ ] **Step 3: Item 2 runtime confirmation (manual; paste results into the PR)**

On Windows with two monitors: select Display 2 with a region → Record → Pause → close the recorder widget → reopen it from the widget drawer → Resume. Expected: recording resumes on Display 2 inside the region and the border returns on Display 2. If Resume fails, the widget now shows the error and `ffmpeg_log.txt` in the session folder (`~/Downloads/gator_demos/<demo_tag>/`) holds the failing `[cmd seg01]` line: attach it to issue #55.

- [ ] **Step 4: Item 3 end-to-end check (manual)**

Record → Pause → Resume → Stop. Expected: one `*_final.mp4` that plays across the pause, and a completion message such as `Recording complete. File: …_final.mp4 (18.9MB). Please analyze it and draft a narration script.` followed by a single `describe_images(task='analyze_video', …)` call that returns a timeline of at most 8 frames.

---

## Self-Review

**Spec coverage**
- Item 1 (stale request; border) → Tasks 1–2. Test seam → Task 1.
- Item 2 backend (clean failed restart, log path) → Task 4; widget feedback → Task 5; runtime confirmation → Task 11 Step 3.
- Item 3 (stitch stderr, concat cleanup, no silent fallback, no `latest_output.json` on failure) → Task 3; empty `()` and error display → Task 5; path-extraction wording → Tasks 5 and 10.
- Item 4 (diagnose; delegated listener, `_activeStops` Set, `_userStopped` guard) → Tasks 6–7.
- Item 5 (reject >8; `analyze_video`; secrets guard; SKILL.md collapse; `frames/` cleanup removal) → Tasks 8–10.
- Spec Decisions 1–13 all map to a task step or a task boundary (Decision 4 and 12 are deliberate non-changes; Decision 11 is checked in Task 11 Step 1).
- Spec Testing bullets: item 1 (3 tests), item 2 (1), item 3 (4), widget (4 + 1), stop predicate (2), describe_images (2 + 7).

**Placeholder scan:** no TBD/TODO; every code step shows code; every run step has a command and expected result. Task 10 Step 3 names exact start/end markers for the Phase 2 block rather than quoting 35 lines of the text being deleted.

**Type consistency:** `_IS_WINDOWS` (Tasks 1→2,3,4 fixture), `_last_start_req` (Task 2; fixture sets it in the same task), `env` fields used in Tasks 3–4 (`runs`, `latest`, `segment_bytes`, `concat_returncode`, `concat_stderr`, `fail_next_start`, `border_stops`) are all defined in Task 2's fixture; stop failure keys `error/segments/session_dir` (Task 3) match widget `actionFailed` and its test (Task 5); resume failure keys `error/log` (Task 4) match its test; `_MAX_SEQUENCE_FRAMES`/`_FRAME_MIN_INTERVAL_SEC` defined in Task 8 and used in Task 9; `_extract_video_frames(video, ffmpeg, ffprobe, out_dir) -> (paths, interval)` matches its only caller `_analyze_video`; `_shouldStopFromClick(e, btn, rect, streaming)` and `_activeStops` names match between `app.js` and its test.
