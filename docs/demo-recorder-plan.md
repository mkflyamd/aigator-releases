# Demo Recorder — Test & Ship Plan

**Status:** Phase 1 in progress  
**Last updated:** August 2026

---

## Architecture

The demo recorder is split across two components:

| Component | Location | Ships with |
|-----------|----------|------------|
| Recorder backend API | `web/routes/recorder.py` | Gator app |
| postMessage bridge | `web/static/app.js` | Gator app |
| HUD window | `shell/main.js`, `shell/hud-preload.js` | Gator app |
| Widget HTML + pipeline | `~/.gator/skills/mine/gator-demo-recorder/` | Marketplace skill |
| TTS pipeline | `SKILL.md scripts/tts_pipeline.py` | Marketplace skill |
| ffmpeg binary | `shell/bin/ffmpeg-*` | Gator app (Phase 2) |

The skill renders a widget in chat. The widget calls `/api/recorder/*` directly via `gator:recorder` postMessage — **no agent involvement during record/stop**. The agent re-enters only after Stop to analyze, narrate, and deliver.

### API surface (`/api/recorder/*`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/recorder/status` | GET | Current state: idle / recording / paused |
| `/api/recorder/screens` | GET | Enumerate all monitors |
| `/api/recorder/start` | POST | Start recording. Params: `screen_index`, `crop_x/y/w/h`, `framerate`, `force` |
| `/api/recorder/pause` | POST | Pause (Windows: stops segment; POSIX: SIGSTOP) |
| `/api/recorder/resume` | POST | Resume (Windows: new segment; POSIX: SIGCONT) |
| `/api/recorder/stop` | POST | Stop and stitch all segments into final MP4 |
| `/api/recorder/pick-region` | POST | Spawn fullscreen drag-to-select overlay, return `{x,y,w,h}` |

### Widget → backend flow

```
Inline chat widget (srcdoc iframe, allow-same-origin)
  → parent.postMessage({type:'gator:recorder', action, params})
  → app.js bridge catches it
  → fetch('/api/recorder/<action>', ...)
  → result posted back as gator:recorder-result

Floating HUD (BrowserWindow, no parent frame)
  → window.addEventListener intercepts gator:recorder
  → fetch(window.__GATOR_URL__ + '/api/recorder/<action>', ...)
  → result dispatched as MessageEvent back to widget JS
```

---

## Phase 1: Test (current)

Run after every `.\dev.ps1` restart. All 10 cases must pass before moving to Phase 2.

### Test cases

| # | Test | Expected |
|---|------|----------|
| 1 | Ask "lets record using /gator-demo-recorder" | Widget renders in chat with Record/Pause/Stop buttons |
| 2 | Screen dropdown | Shows all monitors (Display 1, 2, 3...) — not stuck on "Loading screens..." |
| 3 | Click ⏺ Record | Status shows blinking red dot + "Recording — Display N", timer ticks |
| 4 | Click ⏹ Stop | File saved to `~/Downloads/gator_demos/`, size > 0, agent receives path |
| 5 | Pause → Resume → Stop | File contains stitched segments, no black frames at join |
| 6 | Select Region | Orange drag box appears fullscreen, size label shows `WxH`, crop applied to recording |
| 7 | Change screen after crop | Crop clears, screen selector re-enables |
| 8 | Float widget | HUD opens, screens load, Record/Stop work, file saved correctly |
| 9 | Stale recording recovery | Close widget, re-open — shows "Already recording" with timer, Stop works |
| 10 | Full pipeline: analyze → narrate → TTS → deliver | Agent extracts frames, draft narration widget appears, user edits, TTS generates, final MP4 delivered |

### Known issues to resolve before Phase 2

- [ ] `pick-region` tkinter overlay — verify it appears on the correct screen and captures correct coordinates
- [ ] Pause/resume on Windows — verify stitched segments have no A/V sync drift
- [ ] HUD `gator:send-message` after Stop — verify it reaches the chat (no-op in HUD context is acceptable; user can type "analyze" manually)
- [ ] TTS pipeline — verify Lemonade kokoro-v1 is running and `tts_pipeline.py` merges correctly

---

## Phase 2: Bundle ffmpeg

**Trigger:** All Phase 1 test cases pass.  
**Estimated effort:** ~2 days

### Why bundle

ffmpeg is not installed on most user machines. Requiring manual install is a bad first-run experience. Bundling gives every user recording on first launch with no extra steps.

### License

ffmpeg with libx264 is **GPL 2+**. Bundling is permitted. Requirements:

1. Display ffmpeg version + GPL notice in Settings → About
2. Add `THIRD_PARTY_LICENSES.txt` to the installer with ffmpeg source link
3. Source link: https://ffmpeg.org/download.html

### Binary sources

| Platform | Source | Size |
|----------|--------|------|
| Windows x64 | https://github.com/GyanD/codexffmpeg/releases — `ffmpeg-N-full_build.zip` | ~80MB |
| macOS Intel | https://evermeet.cx/ffmpeg/ | ~50MB |
| macOS Apple Silicon | https://evermeet.cx/ffmpeg/ | ~50MB |
| Linux x64 | https://johnvansickle.com/ffmpeg/ — static build | ~80MB |

Place binaries in `shell/bin/`:

```
shell/bin/
  ffmpeg-win.exe
  ffmpeg-mac-x64
  ffmpeg-mac-arm64
  ffmpeg-linux-x64
  .gitignore          ← exclude binaries from git (large files)
```

Add to `.gitignore`:
```
shell/bin/ffmpeg*
```

Use Git LFS or download script for CI.

### Step 1 — Download script

Create `tools/download-ffmpeg.ps1` (Windows) and `tools/download-ffmpeg.sh` (macOS/Linux):

```powershell
# tools/download-ffmpeg.ps1
$url = "https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-full_build.zip"
$zip = "$env:TEMP\ffmpeg.zip"
Invoke-WebRequest $url -OutFile $zip
Expand-Archive $zip -DestinationPath "$env:TEMP\ffmpeg-extracted" -Force
$exe = Get-ChildItem "$env:TEMP\ffmpeg-extracted" -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
Copy-Item $exe.FullName "shell\bin\ffmpeg-win.exe"
Write-Output "Bundled: shell\bin\ffmpeg-win.exe ($([Math]::Round($exe.Length/1MB, 1)) MB)"
```

### Step 2 — Update `_find_ffmpeg()` in `web/routes/recorder.py`

Add bundled path as first check:

```python
def _find_ffmpeg() -> str | None:
    import sys

    # 1. Bundled with app — check resources/bin/ (packaged) or shell/bin/ (dev)
    if getattr(sys, 'frozen', False):
        # PyInstaller: binary is in resources/ next to the exe
        bundled = Path(sys.executable).parent / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    else:
        # Dev: shell/bin/
        bundled = Path(__file__).parent.parent / "shell" / "bin" / (
            "ffmpeg-win.exe" if os.name == "nt" else
            "ffmpeg-mac-arm64" if (os.uname().machine == "arm64") else
            "ffmpeg-mac-x64" if (os.uname().sysname == "Darwin") else
            "ffmpeg-linux-x64"
        )
    if bundled.exists():
        return str(bundled)

    # 2. System PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    # 3. WinGet / common locations (existing fallback)
    ...
```

### Step 3 — electron-builder config

Add to `shell/package.json` under `build`:

```json
"extraResources": [
  {
    "from": "bin/ffmpeg-win.exe",
    "to": "bin/ffmpeg.exe",
    "filter": ["**/*"],
    "platform": ["win"]
  },
  {
    "from": "bin/ffmpeg-mac-x64",
    "to": "bin/ffmpeg",
    "filter": ["**/*"],
    "platform": ["mac"],
    "arch": ["x64"]
  },
  {
    "from": "bin/ffmpeg-mac-arm64",
    "to": "bin/ffmpeg",
    "filter": ["**/*"],
    "platform": ["mac"],
    "arch": ["arm64"]
  },
  {
    "from": "bin/ffmpeg-linux-x64",
    "to": "bin/ffmpeg",
    "filter": ["**/*"],
    "platform": ["linux"]
  }
]
```

### Step 4 — PyInstaller spec

Add to `packaging/aigator-backend.spec` in the `datas` list:

```python
# Windows
datas=[
    ...
    ('shell/bin/ffmpeg-win.exe', 'bin'),
],
```

For macOS/Linux, replace with the appropriate binary name. The `_find_ffmpeg()` function already checks `Path(sys.executable).parent / "ffmpeg.exe"` which matches the PyInstaller output layout.

### Step 5 — GPL notice

Add to Settings → About panel (`web/static/index.html` about modal):

```html
<div class="about-third-party">
  <a href="https://ffmpeg.org" target="_blank">FFmpeg</a>
  — licensed under the
  <a href="https://www.gnu.org/licenses/old-licenses/gpl-2.0.html" target="_blank">GPL 2+</a>.
  Source: <a href="https://github.com/GyanD/codexffmpeg" target="_blank">github.com/GyanD/codexffmpeg</a>
</div>
```

### Step 6 — Packaged build test

On a machine with no ffmpeg on PATH:

```powershell
# Download binaries first
.\tools\download-ffmpeg.ps1

# Build
uv run pyinstaller --clean --noconfirm packaging/aigator-backend.spec `
  --distpath dist/backend --workpath build/pyinstaller-desktop
npm --prefix shell run dist -- --win --x64 --publish never

# Install and test
dist/installers/AI-Gator-Setup-*.exe
# Then: ask Gator to record a demo — should work with no manual ffmpeg install
```

---

## Phase 3: Publish skill

**Trigger:** Phase 2 packaged build test passes.  
**Estimated effort:** ~0.5 day

### Step 1 — Bump Gator version

`version.txt` → `2.1.0`

This is the public version that ships the recorder API. Skills can declare `requires_gator: ">=2.1"`.

### Step 2 — Add version check to skill

Add to top of `SKILL.md`:

```yaml
requires_gator: ">=2.1"
```

Add startup check in Phase 1 (widget init):

```javascript
api('status', null, function(data) {
  if (data.error && data.error.includes('404')) {
    document.getElementById('status').className = 'status error';
    document.getElementById('status').textContent =
      'Requires Gator 2.1+. Please update AI Gator.';
    document.getElementById('btn-record').disabled = true;
    return;
  }
  // ... normal init
});
```

### Step 3 — Package skill

Skill package contents:

```
gator-demo-recorder/
  SKILL.md                    ← widget HTML + pipeline instructions
  scripts/
    tts_pipeline.py           ← TTS + ffmpeg merge
    preflight.py              ← check ffmpeg + Lemonade availability
  references/
    tab_routing.md
```

No binaries. No backend code. The recorder API is in the app.

### Step 4 — Submit to marketplace

Skill listing:
- **Name:** Gator Demo Recorder
- **Description:** Record your screen, add AI narration, and deliver a polished MP4 — all from chat.
- **Requires:** Gator 2.1+
- **Note:** ffmpeg bundled with Gator 2.1+ — no manual installation needed.

---

## CI integration (post-Phase 3)

Add to `.github/workflows/release-desktop.yml`:

```yaml
- name: Download ffmpeg binaries
  run: |
    pwsh tools/download-ffmpeg.ps1          # Windows runner
    # or
    bash tools/download-ffmpeg.sh           # macOS/Linux runners

- name: Build
  run: npm --prefix shell run dist -- --win --x64 --publish never
```

Binaries are downloaded fresh each release build — not stored in git.

---

## Open questions

1. **tts_pipeline.py uses `requests`** — verify it's in `pyproject.toml` dependencies (it is via the existing `requests` dep, but confirm).
2. **Lemonade TTS availability** — for users without Lemonade, offer cloud TTS fallback (Azure or OpenAI TTS). Not blocking for Phase 2.
3. **ffmpeg binary size** — ~80MB adds ~80MB to the Windows installer. Acceptable for now; revisit with delta updates later.
4. **winget availability** — winget is NOT guaranteed on Windows 10. It requires the App Installer package from Microsoft Store, which is absent on enterprise/LTSC/government machines and fresh Windows 10 installs without Store. Runtime auto-install via winget works on most consumer machines but will silently fail on corporate machines. **This is exactly why Phase 2 (bundling ffmpeg) matters** — bundling eliminates the winget dependency entirely and works on all Windows installs regardless of Store/winget availability.
4. **macOS code signing** — bundled ffmpeg binary must be signed and notarized on macOS or Gatekeeper blocks it. Covered by existing `hardenedRuntime` + notarize config in Phase 1e of the security hardening plan.
