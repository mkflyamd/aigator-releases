# Media Intake and Multi-Clip Projects — Design (Sub-project 6)

Issue #55 items 6 and 7, plan C item 4. Branch: `feat/issue-55-demo-recorder-overhaul`.

## Problem

1. **Item 7 — media cannot be attached.** The chat attach control only accepts documents (`_DOC_EXTENSIONS`) and images/PDF (`_IMAGE_TYPES`) in `initAigatorUpload` (`web/static/app.js`). An `.mp4` hits `Unsupported file type: .mp4` (`processFiles`). Audio is rejected the same way. The only server upload routes are `/api/file-upload-temp` (Downloads, no size or type limit, grandfathered in `tests/csrf_route_baseline.txt`) and `/api/image-upload-temp`. A user who already has a screen recording cannot hand it to the Demo Recorder skill.
2. **Item 6 — one video per pipeline.** SKILL.md Phase 2 and Phase 4 take a single `video_path`. `set-output` / `latest-output` hold a single raw and final path. There is no way to narrate a demo built from several clips, to trim a clip, or to put a music bed under the narration.
3. **Plan C item 4 — media safety.** Nothing validates what is handed to ffmpeg: no extension allow-list, codec check, size cap, duration cap, or dimension cap. A 2-hour 8K file would be accepted and run through ffmpeg with no bound.

## Design

### Overview

```
chat attach (video/audio)  ──XHR upload──▶  POST /api/demo-media/upload
                                              │ stream to <project>/source/, size-capped
                                              │ ffprobe validate (demo_media_probe)
                                              ▼
                                   ext["clips"] in project.json (demo_clips)
                                              │ every mutation
                                              ▼
                      background compose (demo_compose, single worker)
                      normalize each clip → concat → work/timeline.mp4
                      audio assets → work/soundtrack.m4a
                                              │ on success
                                              ▼
              project.raw = work/timeline.mp4 ; ext.clips.timeline.state = "ready"
                                              │
        agent (SKILL.md "Import Mode") reads project.json, runs Phase 2–5 unchanged
        on the timeline; Phase 4 passes --soundtrack to tts_pipeline.py
```

The compose step runs inside the backend because the agent cannot call mutating routes (it holds no CSRF token). The agent only reads `~/.gator/demo_projects.json`, `project.json` and files.

### Modules

| File | Responsibility |
|---|---|
| `web/demo_media_probe.py` | Extension allow-list, `ffprobe` JSON → validated `dict`, `MediaRejected(code, message)`. No project knowledge. |
| `web/demo_clips.py` | Clip registry in `ext["clips"]`: add / remove / reorder / trim, limits, fingerprint, `frame_times`. FastAPI-free. |
| `web/demo_compose.py` | ffmpeg argv builders, `build(pid)`, single-worker scheduler, restart recovery (`ensure_current`). FastAPI-free. |
| `web/routes/demo_clips.py` | HTTP surface under `/api/demo-media`. |
| `web/static/demo-media.js` | Allow-list, local validation, XHR upload, clip panel, pure helpers (`classify`, `parseTrim`, `moveId`, `formatDuration`). |
| `web/skills/gator-demo-recorder/scripts/tts_pipeline.py` | `build_merge_argv` with explicit `-map`, optional `--soundtrack`. |
| `web/skills/gator-demo-recorder/SKILL.md` | "Import Mode" section, Phase 2 and Phase 4 import branches. |

### Probe constants (`demo_media_probe.py`)

```python
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")
VIDEO_CODECS = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}
AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "pcm_f32le"}
MAX_FILE_BYTES = 2 * 1024**3
MAX_CLIP_SECONDS = 1800
MAX_VIDEO_CLIPS = 8
MAX_AUDIO_ASSETS = 4
MAX_DIMENSION = 7680
```

`probe_media(path) -> {"kind": "video"|"audio", "duration": float, "width": int|None, "height": int|None, "has_audio": bool, "video_codec": str|None, "audio_codec": str|None}`. It raises `MediaRejected` with one of the codes in [Error handling](#error-handling).

### Registry schema (`project.json` → `ext["clips"]`)

Namespace `clips` (SP5 owns `ext["media"]`; the names do not collide).

```json
{
  "version": 1,
  "next_id": 3,
  "clips": [
    {"id": "c1", "name": "intro.mp4", "file": "source/c1_intro.mp4",
     "duration": 12.3, "width": 1920, "height": 1080, "has_audio": true,
     "trim_start": 0.0, "trim_end": null}
  ],
  "audio": [
    {"id": "a2", "name": "bed.mp3", "file": "source/a2_bed.mp3", "duration": 95.0}
  ],
  "timeline": {
    "state": "idle|building|ready|failed",
    "fingerprint": "<sha1 hex>",
    "file": "work/timeline.mp4",
    "soundtrack": "work/soundtrack.m4a",
    "duration": 30.0,
    "clips": [{"id": "c1", "name": "intro.mp4", "start": 0.0, "end": 10.0}],
    "frame_times": [2.5, 7.5, 12.5, 17.5, 22.5, 27.5],
    "error": null
  }
}
```

Paths are project-relative POSIX strings. `trim_end: null` means "to the end". `soundtrack` is `null` when there are no audio assets. `id` is `c<n>` / `a<n>` from the shared `next_id` counter, never reused.

### Compose (`demo_compose.py`)

Constants: `TARGET_FPS = 30`, `MAX_OUT_W = 1920`, `MAX_OUT_H = 1080`, `AUDIO_RATE = 48000`, `MAX_FRAMES = 8`, `MIN_FRAME_GAP = 5.0`, `SPEC_VERSION = 1`.

- **Canvas:** width/height of the first clip, scaled down (never up) to fit 1920×1080, each rounded down to even.
- **Normalize** each clip to a canvas-sized, 30 fps, silent H.264 file `work/normalized/<id>_<fp8>.mp4` (`fp8` = first 8 hex of sha1 of file size, mtime_ns, trim, canvas). An existing file is reused. Video filter:
  `scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p`
  argv: `[ffmpeg, -y, -ss, start, -t, length, -i, src, -an, -vf, FILTER, -c:v, libx264, -preset, veryfast, -crf, 20, dst]`.
- **Concat:** list file `work/normalized/concat.txt` (`file '<abs path>'`, `'` escaped as `'\''`); argv `[ffmpeg, -y, -f, concat, -safe, 0, -i, list, -c, copy, -movflags, +faststart, work/timeline.mp4]`.
- **Soundtrack:** all audio assets, in order, resampled to 48 kHz stereo and concatenated by `concat=n=N:v=0:a=1`, encoded AAC to `work/soundtrack.m4a`. Clip audio is always dropped; narration replaces it.
- **Fingerprint:** sha1 over `SPEC_VERSION`, each clip's (id, size, mtime_ns, trim_start, trim_end) in order, and each audio asset's (id, size, mtime_ns).
- **`frame_times(durations)`:** `total = sum(durations)`; `n = min(MAX_FRAMES, max(1, int(total // MIN_FRAME_GAP)))`; times = `round((i + 0.5) * total / n, 3)`. `[10, 20]` → `[2.5, 7.5, 12.5, 17.5, 22.5, 27.5]`; `[3.0]` → `[1.5]`. Times are on the concatenated timeline so frame extraction works on `timeline.mp4` unchanged.
- **Scheduler:** one `ThreadPoolExecutor(max_workers=1)`. `schedule(pid)` is idempotent per project via an in-flight set. `build(pid)` re-reads the registry after the ffmpeg work and discards its result when the fingerprint changed (a mutation landed mid-build), then re-schedules.
- **On success:** `timeline.state = "ready"`, `update_project(pid, raw=<absolute path of work/timeline.mp4>)`, and `stage="recorded"` when the stage is still `created`. With zero clips the timeline resets to `idle` and `raw` is left alone.
- **Restart recovery:** `ensure_current(pid)` schedules a build when clips exist and the timeline is not `ready` with a matching fingerprint and an existing file. `GET /api/demo-media/{pid}` calls it, so a backend restart mid-build heals on the next panel load.
- **Failed builds:** `ensure_current` does not retry a `failed` build whose fingerprint is unchanged, so a broken input does not loop. Any mutation changes the fingerprint and schedules a fresh build.
- **Serialization:** every read-modify-write of `ext["clips"]` runs under the module-level `demo_clips._LOCK` (an `RLock`), because SP3's `set_ext` replaces a whole namespace. `build` takes the same lock for its snapshot and its fingerprint re-check.

### HTTP surface (`/api/demo-media`)

| Route | Body / query | Result |
|---|---|---|
| `POST /upload` | raw body; `?filename=` required; `?project_id=` optional | `{ok, project_id, item, path, clips}` (`path` = absolute saved file) |
| `GET /{pid}` | | `{ok, project_id, name, stage, clips}` and `ensure_current` |
| `PUT /{pid}/order` | `{"ids": ["c2","c1"]}` | `{ok, clips}` |
| `PATCH /{pid}/clips/{cid}` | `{"trim_start": 1.0, "trim_end": 9.5 \| null}` | `{ok, clips}` |
| `DELETE /{pid}/items/{iid}` | | `{ok, clips}` |

In every body, `clips` is the whole registry object `{version, next_id, clips: [...], audio: [...], timeline: {...}}`, not just the clip list.

All non-GET routes carry `dependencies=[Depends(verify_csrf)]` (`security`). They are not added to `tests/csrf_route_baseline.txt`. The prefix `/api/demo-media` cannot be shadowed by SP3's `GET /api/demo-projects/{id}`.

`POST /upload` project selection: an explicit `project_id` → that project (404 if unknown, 409 `project_locked` if its stage is locked). Otherwise the active project (`get_active_id()`) is adopted only if it is unlocked and either still at stage `created` or already holds clips or audio; in every other case `create_project()` starts a new project. A recorded project is therefore never silently overwritten by an unrelated upload. Every mutating route returns 409 `project_locked` for a locked project. A successful mutation calls `demo_compose.schedule(pid)`.

The upload streams `request.stream()` into `source/.upload_<uuid>.part`, aborts with 413 once `MAX_FILE_BYTES` is exceeded, probes in an executor thread, then `add_item` renames the part file to `source/<id>_<safe_name>` (`safe_name` = `re.sub(r"[^A-Za-z0-9._-]+", "_", basename)[:80]`).

### Client (`demo-media.js`, plain-script global `DemoMedia`)

- `DemoMedia.classify(name)` → `"video" | "audio" | null` from the extension lists above.
- `DemoMedia.validateLocal(file)` → error message string or `null` (empty file, size ≤ 2 GiB) before any bytes leave the browser.
- `DemoMedia.upload(file, {projectId, onProgress})` → Promise of the server JSON. XHR (progress events), `X-CSRF-Token` from `window.__CSRF_TOKEN__`.
- `DemoMedia.parseTrim(startText, endText, duration)` → `{ok: true, trim_start, trim_end}` or `{ok: false, error}` (`trim_end` is `null` when blank; minimum length 0.5 s).
- `DemoMedia.moveId(ids, id, delta)` → reordered copy.
- `DemoMedia.mountPanel(el)` renders the clip list (name, duration, ↑ ↓, trim start/end, remove, build state) for the active media project and polls `GET /{pid}` every 2 s while `timeline.state` is `building`.
- `app.js` `processFiles`: before the doc branch, a file with `DemoMedia.classify(name)` goes through `validateLocal` and `upload`; a chip (`file-ref-chip`, `data-file-path` = the saved `source/` path) is appended when the upload completes. While an upload is in flight the chip carries `data-media-uploading` and the submit handler refuses to send.
- `index.html`: `<div id="demo-media-panel" class="demo-media-panel hidden">` above `#chat-input-row`, the `demo-media.js` script tag before `app.js`, and the media extensions added to the file input's `accept`.

### Agent side (SKILL.md "Import Mode")

Trigger: a `[File: <path>]` chip whose extension is in the media lists and whose path is inside a demo project's `source/`, or the user asking to narrate existing footage. The agent:

1. Reads `~/.gator/demo_projects.json` → `active_project_id` → project folder → `project.json`.
2. Reads `ext.clips.timeline.state`. `building` → poll `project.json` every 5 s for up to 10 minutes. `failed` → report `timeline.error` and stop. `ready` → `video_path = <project>/work/timeline.mp4`.
3. Phase 2: extracts one frame at each `timeline.frame_times` entry (`-ss t -i video -frames:v 1`), passes them to `describe_images` with `analyze_sequence`, and uses `timeline.clips[].start/end/name` to label scene boundaries.
4. Phase 3 widget, unchanged.
5. Phase 4: same call plus `--soundtrack <timeline folder>/soundtrack.m4a` when that file exists next to the timeline video. Detection is by file presence, so it needs no extra state and does not apply to ordinary screen recordings.
6. The agent never calls `/api/demo-media` mutating routes.

### Merge (`tts_pipeline.py`)

`build_merge_argv(ffmpeg, video, audio, out, soundtrack=None)` returns the final argv. Without a soundtrack it adds explicit `-map 0:v:0 -map 1:a:0` to today's command. With one:

`-filter_complex "[2:a]volume=0.25[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]" -map 0:v:0 -map [aout]`

`merge_audio_video(video_path, audio_path, out_path, soundtrack=None)` keeps its extend/pad logic and calls `build_merge_argv`. `main` gains `--soundtrack` (default `None`).

## Decisions

1. **Prefix `/api/demo-media`**, not `/api/demo-projects/...`. SP3's `GET /{id}` would shadow sibling GETs, and keeping media in its own router keeps SP3 small.
2. **Namespace `ext["clips"]`.** SP5 owns `ext["media"]`.
3. **Compose in the backend scheduler.** The agent has no CSRF token, so it cannot trigger a build. Building eagerly on every mutation means the timeline is usually ready before the agent looks.
4. **Single-worker executor.** ffmpeg already saturates cores; a queue keeps CPU predictable and makes the in-flight set trivial.
5. **Fingerprint-guarded writes.** A build that finishes after a newer mutation discards its result and re-schedules, so a stale timeline is never published as `ready`.
6. **Clip audio dropped, soundtrack at 0.25.** Narration is the audio story. Explicit `-map` makes that independent of ffmpeg's default stream selection.
7. **Timeline becomes `project.raw`.** Phases 2–5 and the delivery widget keep working with one raw file and need no multi-clip awareness.
8. **Raw-body streaming upload with `?filename=`**, following the size-limited streaming pattern in `routes/jira.py`, instead of multipart `UploadFile`, which buffers the whole file before the handler runs. A 2 GiB cap is only enforceable while streaming.
9. **Uniform frame spacing.** Matches the existing 8-frame cap and 5 s gap, and `timeline.clips` gives the agent the boundaries.
10. **Locked stages.** After narration is approved the timeline timings are baked into the narration; clip edits would desynchronize it, so mutations return 409.
11. **No new generic upload route.** The grandfathered Downloads routes stay untouched; media never lands in Downloads.

## Error handling

`MediaRejected.code` values and HTTP status:

| Code | Status | When |
|---|---|---|
| `unsupported_type` | 415 | extension not in `VIDEO_EXTS + AUDIO_EXTS`, or missing `filename` |
| `tools_missing` | 503 | ffprobe is not installed |
| `too_large` | 413 | body exceeds `MAX_FILE_BYTES` |
| `unreadable` | 422 | ffprobe fails or returns no usable JSON |
| `no_video_stream` / `no_audio_stream` | 422 | extension says video/audio but the stream is absent |
| `codec_unsupported` | 422 | codec outside the allow-lists |
| `zero_duration` / `too_long` | 422 | duration ≤ 0 or > `MAX_CLIP_SECONDS` |
| `too_big_dimensions` | 422 | width or height > `MAX_DIMENSION` |
| `too_many` | 409 | more than `MAX_VIDEO_CLIPS` clips or `MAX_AUDIO_ASSETS` audio assets |
| `bad_order` | 422 | `ids` is not a permutation of the clip ids |
| `bad_trim` | 422 | not `0 ≤ start < end ≤ duration`, or length < 0.5 s |
| `not_found` | 404 | unknown project or item |
| `project_locked` | 409 | stage `narration_approved` or `delivered` |

Responses use `{"ok": false, "code": ..., "message": ...}`. A rejected upload deletes its `.part` file and leaves the registry untouched. A failed ffmpeg run sets `timeline.state = "failed"` with the last 400 characters of stderr in `timeline.error`; the next mutation (which changes the fingerprint) re-schedules, and a plain `GET` does not retry an unchanged failure. Source files are never deleted by a failed build.

## Testing

Python (`tests/demo_media/`, pytest; `conftest.py` provides a `store` fixture that monkeypatches the SP3 module the same way SP3's fixture does, plus a `fake_ffprobe` helper):

- `test_probe.py` — canned ffprobe JSON → accept/reject for each code; extension case-insensitivity; audio vs video kind.
- `test_clips.py` — add/remove/reorder/trim, limits, id monotonicity, fingerprint changes with trim/order, `frame_times` worked examples.
- `test_compose.py` — argv builders (exact lists), canvas sizing, concat escaping, `build` with a fake `_run` that writes the outputs: ready state, `raw` update, stale-build discard, failure state, `ensure_current` scheduling, zero-clip reset.
- `test_routes.py` — `TestClient` with `get_csrf_token("testserver")`: upload happy path, missing CSRF → 403, 415, 413, 422, 409 (locked, too many), order, trim, delete, `GET` re-schedule.
- `test_compose_integration.py` — real ffmpeg (skipped when absent): two lavfi clips → `timeline.mp4` of the expected duration, h264, no audio stream; soundtrack built.
- `test_tts_merge.py` — `build_merge_argv` exact argv with/without soundtrack, and the `--soundtrack` flag (module loaded with `importlib` from the skill scripts dir).
- `test_skill_clip_rules.py` — SKILL.md contains the Import Mode markers and the Phase 4 soundtrack call.

JS (`tests/demo_media_ui.test.js`, node `assert`, vm extraction like the existing JS tests): `classify`, `validateLocal`, `parseTrim`, `moveId`, `formatDuration`.

Manual (Playwright): attach two `.mp4` files and one `.mp3`, reorder, trim, remove, watch the build state, send a message with the chip, and check that submit is blocked mid-upload.

## Depends on SP2

- **Tab pin.** After a successful upload the client pins the active tab to the Demo Recorder skill and the project (`_setTabPin(_activeTabId, {skill, projectId})`), guarded by `typeof` so the code works before SP2's helpers exist.
- **Approval transaction.** The timeline is the project's `raw`, so SP2's media fingerprint covers it with no extra work. In the locked stages (`narration_approved`, `delivered`) every clip mutation returns 409, which keeps that fingerprint stable between approval and delivery.
- The Phase 4 invocation is a shell call the user approves through SP2's approval transaction; the added `--soundtrack` argument is part of that approved command text, so the SKILL.md snippet builds the whole argv list in one place.
- SP6's SKILL.md edits must keep SP3's and SP2's SKILL.md contract tests green.

## Depends on SP3

Uses `create_project`, `get_active_id`, `get_project`, `project_path`, `set_ext`, `update_project` and the project layout (`source/`, `work/normalized/`, `work/`). No SP3 change is required.

## Requested additions to SP3 interfaces

None blocking. `demo_clips` serializes its read-modify-write of `ext["clips"]` with its module-level `_LOCK` (`threading.RLock`), because SP3's `set_ext` replaces a whole namespace. If SP3 later adds an atomic `ext_update(pid, ns, fn)`, the registry's write helpers in `demo_clips` are the place to switch over.
