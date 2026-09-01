# Demo Recorder — Architecture & Ship Plan

**Status:** Production-ready, shipping in next release
**Last updated:** August 2026

---

## Architecture

The demo recorder is a built-in feature split across four layers:

| Component | Location | Ships with |
|-----------|----------|------------|
| Recorder backend API | `web/routes/recorder.py` | Gator app (built-in) |
| postMessage bridge + hotkeys | `web/static/app.js` | Gator app (built-in) |
| HUD window (floating widget host) | `shell/main.js`, `shell/hud-preload.js` | Gator app (built-in) |
| Skill (widget HTML + TTS pipeline + preflight) | `web/skills/gator-demo-recorder/` | Gator app (built-in) |
| ffmpeg | Runtime install via winget/brew/apt | Not bundled |
| Lemonade TTS | Runtime install via winget/pip | Not bundled (optional) |

The skill is a **built-in skill** — auto-discovered by `shared.py` at startup, no marketplace install required. Every user gets it with the app.

### Runtime flow

```
User: "/gator-demo-recorder"
  │
  ▼
Agent reads SKILL.md → runs preflight.py (checks ffmpeg + Lemonade)
  │
  ▼
Agent renders recorder widget (Phase 1)
  │
  ▼  Widget calls /api/recorder/* directly (no agent during recording)
  │
  │  Record ──→ /api/recorder/start ──→ ffmpeg subprocess (gdigrab/avfoundation/x11grab)
  │  Pause  ──→ /api/recorder/pause  ──→ stop segment, accumulate elapsed
  │  Resume ──→ /api/recorder/resume ──→ new ffmpeg segment
  │  Stop   ──→ /api/recorder/stop   ──→ stitch segments → final.mp4
  │
  ▼  Widget posts "Recording complete. File: <path>" to chat
  │
  ▼
Agent re-enters: extract keyframes (≤8) → describe_images(analyze_sequence)
  │
  ▼
Agent renders narration editor widget (Phase 3) — user MUST approve
  │
  ▼  User clicks Approve → "NARRATION_APPROVED:<json>"
  │
  ▼
Agent runs tts_pipeline.py → Lemonade kokoro-v1 → merge audio+video
  │
  ▼
Agent renders playback widget (Phase 5) — inline video, download, edit
```

### API surface (`/api/recorder/*`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/recorder/status` | GET | Current state: idle / recording / paused + ffmpeg path + log path |
| `/api/recorder/screens` | GET | Enumerate all monitors (physical pixels via GetDeviceCaps) |
| `/api/recorder/start` | POST | Start recording. Params: `screen_index`, `crop_x/y/w/h`, `framerate`, `force` |
| `/api/recorder/pause` | POST | Pause (Windows: stops segment; POSIX: SIGSTOP) |
| `/api/recorder/resume` | POST | Resume (Windows: new segment; POSIX: SIGCONT) |
| `/api/recorder/stop` | POST | Stop and stitch all segments into final MP4 |
| `/api/recorder/pick-region` | POST | Spawn fullscreen drag-to-select overlay, return `{x,y,w,h}` |
| `/api/recorder/notify` | POST | HUD → chat message injection (after Stop) |
| `/api/recorder/pending` | GET | Frontend polls every 2s for notifications + open-widget requests |
| `/api/recorder/open-widget` | POST | REC badge click → open widget manager |
| `/api/recorder/tts-preview` | POST | Lemonade TTS preview (audio/mpeg response) |
| `/api/recorder/serve-file` | GET | Serve MP4/MP3 for inline playback (sandboxed to gator_demos/) |
| `/api/recorder/debug` | GET | Screens + ffmpeg log tail (diagnostics) |

### Widget → backend flow

```
Inline chat widget (srcdoc iframe, allow-same-origin)
  → fetch(window._GATOR + '/api/recorder/<action>', ...)
  → result rendered from response JSON

Floating HUD (BrowserWindow, no parent frame)
  → fetch(window._GATOR + '/api/recorder/<action>', ...)
  → result rendered from response JSON
  → after Stop: POST /api/recorder/notify → frontend polls /pending → injects into chat
```

### Recording border overlay

A tkinter window in a daemon thread shows an orange border + REC badge around the capture area while recording. Key properties:

- **Excluded from recording** via `WDA_EXCLUDEFROMCAPTURE` (Windows) — never appears in the output video
- **Click-through** via `WS_EX_LAYERED` + transparent color key — the transparent interior passes clicks to apps below, the orange REC badge is clickable
- **REC badge click** → `POST /api/recorder/open-widget` → frontend opens widget manager
- **Thread-safe teardown** via `root.after(0, ...)` — no `Tcl_AsyncDelete` crashes on any platform
- **Cross-platform**: `after()` is the only tkinter method safe from any thread (Tcl_ThreadQueueEvent on all platforms)

### Hotkeys

Global keyboard shortcuts in `app.js` (work regardless of widget open/closed):

| Shortcut | Action |
|----------|--------|
| Alt+R | Record |
| Alt+P | Pause / Resume (toggles based on current state) |
| Alt+S | Stop |

Disabled when typing in input/textarea/select. Alt chosen to avoid conflicts with browser/Electron shortcuts (Ctrl+R refresh, Ctrl+P print, Ctrl+S save).

### Screen capture DPI handling

Windows DPI scaling causes logical ≠ physical pixels. The recorder uses `GetDeviceCaps(hdc, DESKTOPHORZRES/DESKTOPVERTRES)` which returns true physical pixels regardless of process DPI awareness. `GetDpiForMonitor` lies (returns 96) for DPI-unaware processes. gdigrab always works in physical pixels, so the ffmpeg command uses physical dimensions from `GetDeviceCaps`.

### describe_images frame analysis

`_analyze_frame_sequence` in `web/skills/_always_on/tools.py` sends up to 8 frames in a single vision API call. Uses `httpx.AsyncClient` (async) instead of the sync Anthropic SDK — never blocks the uvicorn event loop. Returns a per-frame timeline `{frame, time_sec, time_label, description}` + summary.

---

## Skill phases

### Phase 1: Preflight → Render Widget

1. Run `scripts/preflight.py` — checks ffmpeg + Lemonade TTS availability
2. If missing, ask user consent → auto-install via winget (Windows) / brew (macOS) / pip (macOS/Linux)
3. Render recorder widget with screen picker, crop selector, Record/Pause/Stop buttons, hide-from-recording toggle

### Phase 2: Analyze

1. Extract keyframes (max 8, evenly spaced via ffprobe duration probe)
2. Call `describe_images(task='analyze_sequence', image_paths=[...], fps=<interval>)`
3. Build scene summary as markdown pipe table

### Phase 3: Narration Edit (MUST NOT be skipped)

1. Render editable narration widget from SKILL.md template (verbatim — agent must not design its own)
2. Widget includes: voice picker (7 kokoro voices), speed selector, per-segment preview buttons, raw recording video preview, "Approve & Generate TTS" button
3. User edits text, previews voices, clicks Approve → sends `NARRATION_APPROVED:<json>`
4. Agent waits for approval — never generates TTS without it

### Phase 4: TTS + Merge

1. Parse `NARRATION_APPROVED:<json>` (voice + speed from first segment)
2. Run `scripts/tts_pipeline.py` — generates TTS per segment via Lemonade kokoro-v1, inserts silence to sync to timeline, merges with video via ffmpeg
3. Output: `final_with_narration.mp4`

### Phase 5: Deliver

1. Render playback widget with inline `<video>` player, clickable file path, duration
2. Buttons: Download, Edit narration & regenerate, Delete intermediates
3. "Save" button hidden on this widget (transient — not worth persisting)

---

## Dependencies

### ffmpeg (required)

- **Runtime install** via preflight: winget (Windows), brew (macOS), apt/dnf/pacman (Linux)
- **Backend fallback**: `_try_install_ffmpeg()` silently attempts winget install if ffmpeg missing when Record is hit
- **Not bundled** — runtime install works on most machines. If corporate machines block winget, bundle ffmpeg in a future patch (the `_find_ffmpeg()` function already has a bundled-path check ready)

### Lemonade TTS (optional)

- **Runtime install** via preflight: winget `AMD.LemonadeServer` (Windows), `pip install lemonade-server` (macOS/Linux)
- **Graceful fallback**: if not installed, preflight reports `lemonade.ok = false`, skill delivers video without narration
- **Preflight validates the actual TTS endpoint** (`/v1/audio/speech`) with a 3-word test call — not just a TCP check
- **Never bundle** — Lemonade is NPU-specific on Windows, CPU-only elsewhere; bundling the wrong build would break things

---

## Pre-release checklist

```bash
# 1. Verify skill loads as built-in
uv run python -c "import sys; sys.path.insert(0,'web'); import shared; print('gator-demo-recorder' in shared.SKILL_PROMPTS)"

# 2. Lock check + sync
uv lock --check && uv sync --locked

# 3. Pre-release packaging tests
uv run pytest tests/test_desktop_packaging.py -v

# 4. Build installer
uv run pyinstaller --clean --noconfirm packaging/aigator-backend.spec --distpath dist/backend --workpath build/pyinstaller-desktop
npm --prefix shell run dist -- --win --x64 --publish never

# 5. Smoke test the installer
# Install dist/installers/*.exe
# Launch app → /gator-demo-recorder → record 10s → stop → approve narration → verify final MP4 plays
```

---

## Test cases

| # | Test | Expected |
|---|------|----------|
| 1 | Ask "/gator-demo-recorder" | Widget renders in chat with Record/Pause/Stop buttons |
| 2 | Screen dropdown | Shows all monitors with physical resolution (e.g. 1920x1200, not 1280x800) |
| 3 | Click Record | Orange border + REC badge appears around capture area, timer ticks |
| 4 | Click Stop | Border disappears instantly, file saved to ~/Downloads/gator_demos/, agent receives path |
| 5 | Pause → Resume → Stop | Border hides on pause, reappears on resume, file contains stitched segments |
| 6 | Select Region | Orange drag box appears fullscreen, crop applied to recording |
| 7 | Float widget as HUD | HUD opens, Record/Stop work, file saved correctly |
| 8 | REC badge click | Opens widget manager |
| 9 | Alt+R / Alt+P / Alt+S | Hotkeys trigger record/pause/stop |
| 10 | Full pipeline | Agent extracts ≤8 frames, narration widget appears with voice picker + preview, user approves, TTS generates, final MP4 delivered with inline player |
| 11 | Edit narration & regenerate | Clicking button in playback widget re-renders Phase 3 template (not a custom widget) |
| 12 | Close Gator while recording | Recording stops cleanly via lifespan shutdown, no orphaned ffmpeg processes |

---

## Known limitations

- **macOS screen capture permissions** — avfoundation requires Screen Recording permission. No user-facing prompt yet.
- **Linux x11grab** — works but screen enumeration returns hardcoded 1920x1080 fallback.
- **Scene detection** — narration timestamps are assigned by the agent based on frame analysis, not auto-aligned to scene changes via ffmpeg `select=gt(scene,0.3)`. Future enhancement.
- **winget on corporate machines** — runtime ffmpeg install fails if winget is blocked by policy. Bundle ffmpeg in a patch if reported.

---

## What we are shipping

- **Built-in skill** at `web/skills/gator-demo-recorder/` — no marketplace install needed
- **Recorder API** at `web/routes/recorder.py` — 13 endpoints
- **HUD window** in `shell/main.js` — floating widget host with minimize-to-pill, subtle border
- **Hotkeys** in `web/static/app.js` — Alt+R/P/S
- **Widget manager drawer** in `web/static/app.js` — slides in from right like agents pane
- **DPI-aware screen capture** — `GetDeviceCaps` for physical pixels
- **Recording border overlay** — tkinter, excluded from capture, clickable REC badge
- **Narration editor widget** — voice picker, preview, per-segment edit, video preview
- **Playback widget** — inline video, download, edit narration, delete intermediates
- **Async frame analysis** — `httpx.AsyncClient`, 8-frame cap, no event loop blocking
- **Runtime ffmpeg/Lemonade install** — preflight with consent, graceful fallback
