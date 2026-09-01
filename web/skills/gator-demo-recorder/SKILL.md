---
name: Gator Demo Recorder
description: Record your screen manually, then analyze, narrate with TTS, and deliver a polished MP4.
version: "2.0"
---

# Gator Demo Recorder

Record your screen manually using the in-chat widget. After recording, analyze the video, write and edit a narration script, generate TTS voiceover, merge, and deliver a final MP4.

## Pipeline

```
Phase 1: RENDER WIDGET      — user clicks Record / Stop in chat
Phase 2: ANALYZE            — extract keyframes, describe_images, build scene summary
Phase 3: NARRATION EDIT     — draft script, show editable widget, user approves
Phase 4: TTS + MERGE        — generate audio via Lemonade, merge with ffmpeg
Phase 5: DELIVER            — report final MP4 path, offer to save to OneDrive
```

---

## CRITICAL RULES — Read first

- **Shell:** always `shell='powershell'` or `shell='cmd'`. Never `shell='bash'`.
- **ffmpeg:** never search with `Get-ChildItem -Recurse` — it times out. Call `GET /api/recorder/status` — it returns `ffmpeg_path` AND `ffprobe_path` with the exact binary locations. Use those fields directly. Never derive ffprobe from ffmpeg via string replace — the paths differ. If `ffmpeg` is false, tell user: `winget install Gyan.FFmpeg` (Windows), `brew install ffmpeg` (macOS).
- **File path:** the widget sends `"Recording complete. File: <path> ..."` after Stop. Extract the path from that message directly — **never ask the user for the path**. It is always the value between `"File: "` and `" ("`.
- **Trigger:** any message matching `"Recording complete. File:"` means the user just stopped recording. Immediately proceed to Phase 2 using the path from the message.
- **Recording:** the widget calls `/api/recorder/start` and `/api/recorder/stop` directly — **do not invoke ffmpeg manually**. Do not call `run_shell` for record/stop.
- **Output size:** never generate more than ~300 lines of output in one turn. Split long work across turns.
- **NEVER skip Phase 3 (Narration Edit):** you MUST render the editable narration widget with the "✓ Approve & Generate TTS" button and WAIT for the user to click it. Do NOT generate TTS until you receive `"NARRATION_APPROVED:<json>"`. Generating TTS without showing the approval widget is a critical violation — the user must be able to review, edit text, preview voices, and approve before any audio is generated.
- **Use the EXACT Phase 3 widget template:** do not design your own narration widget. Do not change the message prefix from `NARRATION_APPROVED` to anything else (e.g. `NARRATION_V2_APPROVED` will silently break Phase 4). Do not remove the voice selector, speed selector, preview buttons, or the raw recording video preview from the template. The template is in SKILL.md — copy it verbatim, only replacing `SEGMENTS_PLACEHOLDER`. The video path is fetched automatically.
- **Re-edit flow:** when the user clicks "Edit narration & regenerate" in the Phase 5 delivery widget, go back to Phase 3 and render the **exact same Phase 3 widget template** again (with voice selector, preview buttons, video preview). Do NOT design a custom "v2" editor. Do NOT change the `NARRATION_APPROVED` prefix. The re-edit widget must be identical to the first-pass widget.
- **Never embed file paths in widget JS.** All file paths go through `/api/recorder/set-output` → `/api/recorder/latest-output`. Widget templates have no `PATH_PLACEHOLDER` strings — they fetch paths from the API on load.

## Audio/Video Quality Rules — Non-negotiable

The final video must be **professional quality**. Apply these without being asked:

- **Audio/video sync:** narration `start_at` timestamps must align with the actual on-screen action. A segment narrating "clicking the button" must start when the click is visible, not 2 seconds before or after. After TTS generation, compare each segment's `start_at` to the video duration — if the narration ends significantly before the video ends (>2s gap), add a closing segment; if narration runs much longer than the video (>3× video duration), shorten the script and re-generate.
- **Sync validation (always run):** after merge, run ffprobe on both the video stream and audio stream of the output file. Report duration of each. If they differ by more than 1s, explain why (e.g. "video held on last frame for 8s to match 12s narration") and offer to re-edit.
- **Segment timing:** `start_at` values must be monotonically increasing and respect the video timeline. Segment 1 at `start_at: 0`, Segment 2 no earlier than `start_at: 2` (give each segment breathing room). Do not bunch all segments at `start_at: 0, 1, 2, 3` for an 8-second video.
- **Professional pacing:** narration should feel like a polished product demo, not a speed-read. Prefer 3-5 well-paced segments over 8 rushed ones. Each spoken segment should be 1-2 natural sentences (~5-12 seconds of audio). Leave silence at the start (0.5s) and end.
- **Background music:** when mixing, target narration at -3dB and music at -20dB to -18dB. Music must fade in (0.5s) and fade out (1s before video end). Never let music overpower narration.

---

## Phase 1: Preflight → Render Widget

**Step 1 — Run preflight** before rendering the widget:

```python
import subprocess, sys, json
from pathlib import Path

# Works for both built-in (web/skills/) and user-installed (~/.gator/skills/) skills
_skill_dirs = [
    Path.home() / ".gator/skills/mine/gator-demo-recorder/scripts",
    Path(__file__).parent / "scripts" if "__file__" in dir() else None,
    Path.cwd() / "web/skills/gator-demo-recorder/scripts",
]
skill_scripts = next((d for d in _skill_dirs if d and d.exists()), _skill_dirs[0])
r = subprocess.run([sys.executable, str(skill_scripts / "preflight.py")],
                   capture_output=True, text=True, timeout=30)
result = json.loads(r.stdout)
print(json.dumps(result, indent=2))
```

**If `result["ready"]` is True** → render the widget immediately.

**If `result["ready"]` is False** → show the user `result["message"]` and ask for consent.
- If user says yes → re-run with `--auto-consent` flag (installs silently, may take 1-2 min)
- If user says no → tell them to install manually and try again

Lemonade (`result["lemonade"]["ok"]`) is **optional** — if False, warn the user that narration
won't be available but recording and analysis will still work. Do not block on Lemonade.

**Step 2 — Render the widget** (only after ffmpeg confirmed ready):

The widget:
- Calls `GET /api/recorder/screens` on load to populate the screen selector
- Lets the user pick screen and optionally enter a crop region (x, y, w, h)
- Record/Pause/Resume/Stop all call the backend API directly via `gator:recorder` postMessage — no agent involvement
- After Stop, sends one chat message with the file path

### Tab navigation note
The widget lives in the chat iframe. If the user switches to a different Gator tab (Teams, OneNote, etc.) the widget stays in the DOM and keeps ticking — it does not stop or lose state. The recording continues on the backend regardless of which tab is visible. The user can return to the chat tab at any time to hit Stop.

```html:widget
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#111827;font-family:system-ui,sans-serif;padding:14px}
  .panel{background:#1a2332;border:1px solid #1e3a52;border-radius:12px;padding:14px;max-width:420px}
  h3{color:#4ade80;font-size:.88rem;font-weight:700;margin-bottom:10px;letter-spacing:.04em}
  label{font-size:.72rem;color:#6b8db5;display:block;margin-bottom:3px}
  select{width:100%;background:#111827;border:1px solid #1e3a52;border-radius:6px;color:#dbeafe;padding:5px 8px;font-size:.78rem;font-family:inherit;margin-bottom:8px}
  .crop-row{display:flex;gap:6px;align-items:center;margin-bottom:8px}
  .btn-crop{background:none;border:1px solid #1e3a52;border-radius:6px;color:#6b8db5;padding:5px 10px;font-size:.75rem;cursor:pointer;white-space:nowrap}
  .btn-crop:hover{border-color:#f97316;color:#f97316}
  .crop-hint{font-size:.65rem;color:#4a6a8a;margin-bottom:10px}
  .status{font-size:.78rem;color:#6b8db5;margin-bottom:6px;min-height:16px}
  .status.recording{color:#ef4444}.status.paused{color:#facc15}.status.done{color:#4ade80}.status.error{color:#f87171}
  .timer{font-size:1.5rem;font-weight:800;color:#dbeafe;text-align:center;margin:6px 0;font-variant-numeric:tabular-nums}
  .timer.recording{color:#ef4444}.timer.paused{color:#facc15}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#ef4444;margin-right:5px;animation:blink 1s infinite;vertical-align:middle}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
  .btns{display:flex;gap:6px;flex-wrap:wrap}
  .btn{flex:1;min-width:72px;padding:8px 10px;border-radius:7px;border:none;font-size:.78rem;font-weight:700;cursor:pointer;transition:opacity .15s}
  .btn:hover:not(:disabled){opacity:.82}.btn:disabled{opacity:.32;cursor:not-allowed}
  .btn-record{background:#ef4444;color:#fff}
  .btn-pause{background:#facc15;color:#111}
  .btn-resume{background:#4ade80;color:#111}
  .btn-stop{background:#374151;color:#dbeafe;border:1px solid #4b5563}
  .hk{font-size:.6rem;opacity:.5;font-weight:400;margin-left:4px}
  .filepath{margin-top:6px;font-size:.68rem;color:#4a6a8a;word-break:break-all}
  .hide-row{display:flex;align-items:center;gap:7px;margin-top:8px;padding:6px 8px;background:rgba(74,222,128,.06);border:1px solid rgba(74,222,128,.15);border-radius:6px;cursor:pointer;user-select:none}
  .hide-row input[type=checkbox]{appearance:none;-webkit-appearance:none;width:14px;height:14px;border:1.5px solid #1e3a52;border-radius:3px;background:#111827;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center}
  .hide-row input[type=checkbox]:checked{background:#4ade80;border-color:#4ade80}
  .hide-row input[type=checkbox]:checked::after{content:'✓';color:#111;font-size:10px;font-weight:700;display:block;text-align:center;line-height:14px}
  .hide-label{font-size:.72rem;color:#6b8db5;flex:1}
  .hide-label b{color:#4ade80}
</style>
</head>
<body>
<div class="panel">
  <h3>🎬 Demo Recorder</h3>
  <label>Screen</label>
  <div style="display:flex;gap:5px;align-items:center;margin-bottom:8px">
    <select id="sel-screen" onchange="onScreenChange()" style="flex:1;margin-bottom:0"></select>
    <button class="btn-crop" id="btn-refresh-screens" onclick="loadScreens(null)" title="Re-detect monitors">↺</button>
  </div>
  <label>Crop region (optional)</label>
  <div class="crop-row">
    <button class="btn-crop" id="btn-crop" onclick="doCrop()">⊞ Select Region</button>
    <span id="crop-label" style="font-size:.72rem;color:#4a6a8a;flex:1">Full screen</span>
  </div>
  <div class="crop-hint">Click "Select Region" then drag on your screen</div>
  <div class="status" id="status">Loading...</div>
  <div class="timer" id="timer">00:00</div>
  <div class="btns">
    <button class="btn btn-record" id="btn-record" onclick="doRecord()" disabled>⏺ Record <span class="hk">Alt+R</span></button>
    <button class="btn btn-pause"  id="btn-pause"  onclick="doPause()"  disabled>⏸ Pause <span class="hk">Alt+P</span></button>
    <button class="btn btn-resume" id="btn-resume" onclick="doResume()" disabled style="display:none">▶ Resume <span class="hk">Alt+P</span></button>
    <button class="btn btn-stop"   id="btn-stop"   onclick="doStop()"   disabled>⏹ Stop <span class="hk">Alt+S</span></button>
  </div>
  <label class="hide-row" onclick="toggleHideWidget()">
    <input type="checkbox" id="chk-hide" checked>
    <span class="hide-label">Hide this widget from recording <b>(recommended)</b></span>
  </label>
  <div class="filepath" id="filepath"></div>
</div>
<script>
// ── Core: all state comes from backend, never from JS variables ──────────────
var _BASE = window._GATOR || 'http://localhost:8003';
var _crop = null, _busy = false, _lastStatus = 'idle', _stopPath = '';

// ── Hide-from-recording toggle ────────────────────────────────────────────────
// When checked (default), the floating HUD window is excluded from screen
// capture so it doesn't appear in the recording. Works via Electron's
// setContentProtection API (WDA_EXCLUDEFROMCAPTURE on Windows).
// Only meaningful when widget is a floating HUD — inline iframe is never captured.
function toggleHideWidget() {
  var chk = document.getElementById('chk-hide');
  var excluded = chk ? chk.checked : true;
  // HUD context: notify shell to set/unset capture exclusion
  if (window.hudControls && window.hudControls.setCaptureExcluded) {
    window.hudControls.setCaptureExcluded(excluded);
  }
  // Inline chat context: postMessage to parent (no-op if no handler)
  try {
    parent.postMessage({ type: 'gator:hud-capture-excluded', excluded: excluded }, '*');
  } catch(e) {}
}

// Apply default on load — excluded by default
window.addEventListener('load', function() {
  if (window.hudControls && window.hudControls.setCaptureExcluded) {
    window.hudControls.setCaptureExcluded(true);
  }
});

function apiFetch(action, params, cb) {
  var m = (action==='status'||action==='screens') ? 'GET' : 'POST';
  var opts = {method:m};
  if (m==='POST' && params) { opts.body=JSON.stringify(params); opts.headers={'Content-Type':'application/json'}; }
  fetch(_BASE+'/api/recorder/'+action, opts)
    .then(function(r){return r.json();})
    .then(function(d){cb(null,d);})
    .catch(function(e){cb(e,null);});
}

function fmt(s) {
  s=Math.floor(s||0);
  return (Math.floor(s/60)<10?'0':'')+Math.floor(s/60)+':'+(s%60<10?'0':'')+(s%60);
}

// ── Render: derives ALL UI state from backend status response ─────────────────
function render(s) {
  _lastStatus = s.status || 'idle';
  document.getElementById('timer').textContent = fmt(s.elapsed);
  document.getElementById('filepath').textContent = s.path || _stopPath || '';

  var st = document.getElementById('status');
  var t  = document.getElementById('timer');
  var br = document.getElementById('btn-record');
  var bp = document.getElementById('btn-pause');
  var bres = document.getElementById('btn-resume');
  var bs = document.getElementById('btn-stop');

  if (_lastStatus === 'recording') {
    st.className='status recording';
    st.innerHTML='<span class="dot"></span>Recording';
    t.className='timer recording';
    br.disabled=true; bp.disabled=false; bp.style.display=''; bres.style.display='none'; bs.disabled=false;
  } else if (_lastStatus === 'paused') {
    st.className='status paused';
    st.textContent='⏸ Paused';
    t.className='timer paused';
    br.disabled=true; bp.style.display='none'; bres.style.display=''; bres.disabled=false; bs.disabled=false;
  } else {
    st.className='status';
    st.textContent = _stopPath ? '✓ Saved — ready to record again' : 'Ready — configure and click Record';
    t.className='timer';
    br.disabled=false; bp.disabled=true; bp.style.display=''; bres.style.display='none'; bs.disabled=true;
  }
}

// ── Poll backend every second — survives tab switches and iframe reloads ──────
setInterval(function() {
  if (_busy) return;
  apiFetch('status', null, function(err, s) {
    if (!err && s) render(s);
  });
}, 1000);

// ── Screen selector ───────────────────────────────────────────────────────────
var _screens = [];
var _screenCount = 0;

function loadScreens(cb) {
  apiFetch('screens', null, function(err, data) {
    var sel = document.getElementById('sel-screen');
    var prev = parseInt(sel.value) || 0;
    var prevCount = _screenCount;
    _screens = (data && data.screens) || [];
    if (!_screens.length) _screens = [{index:0, label:'Display 1', primary:true}];
    _screenCount = _screens.length;

    sel.innerHTML = '';
    _screens.forEach(function(s, i) {
      var o = document.createElement('option');
      o.value = i; o.textContent = s.label + (s.primary?' (primary)':'');
      sel.appendChild(o);
    });

    // Screen topology changed (monitor plugged/unplugged) or selected screen gone
    var topologyChanged = prevCount > 0 && prevCount !== _screenCount;
    var screenGone = prev >= _screens.length;

    if (topologyChanged || screenGone) {
      sel.value = '0';
      // Always clear crop when display topology changes — coordinates are invalid
      if (_crop) {
        clearCrop();
        var msg = screenGone
          ? 'Monitor disconnected — crop and screen selection reset.'
          : 'Display configuration changed — crop cleared.';
        document.getElementById('status').textContent = msg;
        document.getElementById('status').className = 'status error';
      }
    } else {
      sel.value = String(prev);
    }

    if (cb) cb();
  });
}

// Load on init
loadScreens(function() {
  apiFetch('status', null, function(e, s) { if (!e && s) render(s); });
});

// Refresh screen list when user returns to this tab (e.g. after plugging/unplugging a monitor)
document.addEventListener('visibilitychange', function() {
  if (document.visibilityState === 'visible' && _lastStatus === 'idle') {
    loadScreens(null);
  }
});
window.addEventListener('focus', function() {
  if (_lastStatus === 'idle') loadScreens(null);
});

// ── Crop ──────────────────────────────────────────────────────────────────────
function onScreenChange() {
  clearCrop();
  // Tell the backend which screen is selected so global hotkeys use it
  var si = parseInt(document.getElementById('sel-screen').value) || 0;
  try {
    fetch(_BASE + '/api/recorder/select-screen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ screen_index: si })
    });
  } catch(e) {}
}

function clearCrop() {
  _crop = null;
  document.getElementById('crop-label').textContent = 'Full screen';
  document.getElementById('crop-label').style.color = '';
  var btn = document.getElementById('btn-crop');
  btn.textContent = '⊞ Select Region'; btn.style.borderColor = '';
  btn.onclick = doCrop;
  document.getElementById('sel-screen').disabled = false;
  document.getElementById('sel-screen').style.opacity = '';
}

function doCrop() {
  var si = parseInt(document.getElementById('sel-screen').value) || 0;
  var btn = document.getElementById('btn-crop');
  btn.disabled = true; btn.textContent = 'Drawing...';
  document.getElementById('crop-label').textContent = 'Drag on your screen';
  apiFetch('pick-region', {screen_index:si}, function(err, data) {
    btn.disabled = false;
    if (err || !data || data.cancelled) { clearCrop(); return; }
    if (!data.ok) { document.getElementById('crop-label').textContent = 'Error: '+(data.error||''); return; }
    _crop = {x:data.x, y:data.y, w:data.w, h:data.h};
    document.getElementById('crop-label').textContent = data.label;
    document.getElementById('crop-label').style.color = '#f97316';
    btn.textContent = '✕ Clear'; btn.style.borderColor = '#f97316';
    btn.onclick = function() { clearCrop(); };
    document.getElementById('sel-screen').disabled = true;
    document.getElementById('sel-screen').style.opacity = '0.5';
  });
}

// ── Actions ───────────────────────────────────────────────────────────────────
function doRecord() {
  _busy = true; _stopPath = '';
  var p = {screen_index: parseInt(document.getElementById('sel-screen').value)||0, force:true};
  if (_crop) { p.crop_x=_crop.x; p.crop_y=_crop.y; p.crop_w=_crop.w; p.crop_h=_crop.h; }
  document.getElementById('status').textContent = 'Starting...';
  apiFetch('start', p, function(err, data) {
    _busy = false;
    if (err || !data || !data.ok) {
      document.getElementById('status').className = 'status error';
      document.getElementById('status').textContent = 'Error: ' + ((data&&data.error)||String(err));
    }
  });
}

function doPause() {
  _busy = true;
  apiFetch('pause', null, function(err, data) { _busy = false; });
}

function doResume() {
  _busy = true;
  apiFetch('resume', null, function(err, data) { _busy = false; });
}

function doStop() {
  _busy = true;
  document.getElementById('status').textContent = 'Stopping...';
  document.getElementById('btn-stop').disabled = true;
  apiFetch('stop', null, function(err, data) {
    _busy = false;
    if (!err && data && data.ok) {
      _stopPath = data.path || '';
      var mb = data.size_bytes ? (data.size_bytes/1048576).toFixed(1)+'MB' : '';
      document.getElementById('status').className = 'status done';
      document.getElementById('status').textContent = '✓ Saved ' + mb;
      document.getElementById('filepath').textContent = _stopPath;
      // Reset crop after each recording so the next Record starts fresh.
      // User can re-select a region if needed — no stale state carried over.
      clearCrop();
      // Notify the Gator chat.
      // Inline widget: parent.postMessage triggers the bridge in app.js.
      // HUD widget: parent === window so postMessage goes nowhere — instead
      // POST to /api/recorder/notify which the Gator frontend polls every 2s.
      var msg = 'Recording complete. File: '+_stopPath+' ('+mb+'). Please analyze it and draft a narration script.';
      try { parent.postMessage({type:'gator:send-message', text:msg},'*'); } catch(e){}
      // HUD fallback — always fire, Gator deduplicates if both arrive
      try {
        fetch(_BASE+'/api/recorder/notify', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({message:msg})
        });
      } catch(e){}
    } else {
      document.getElementById('status').className = 'status error';
      document.getElementById('status').textContent = 'Stop error: ' + ((data&&data.error)||'');
    }
  });
}
</script>
</body>
</html>
```

---

## Phase 2: Analyze

When you receive `"Recording complete. File: <path> ..."`:

1. Extract the video path: it is between `"File: "` and the next `" ("`. Example: `"Recording complete. File: C:\Users\...\final.mp4 (46MB)."` → path = `C:\Users\...\final.mp4`
2. Get ffmpeg path: `GET /api/recorder/status` → use `ffmpeg_path` field directly. Do not search for ffmpeg any other way.
3. Proceed immediately — do not ask the user for the path or for ffmpeg location.

**Step 1 — Extract keyframes** (max 8 frames, evenly spaced):

```python
import subprocess, urllib.request, json
from pathlib import Path

video = Path(r"<path extracted from message>")
frames_dir = video.parent / "frames"
frames_dir.mkdir(exist_ok=True)

status = json.loads(urllib.request.urlopen("http://localhost:8003/api/recorder/status").read())
ffmpeg = status["ffmpeg_path"]
ffprobe = status.get("ffprobe_path") or str(Path(ffmpeg).parent / "ffprobe.exe")

# Get duration so we can space frames evenly
probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
  "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
  capture_output=True, text=True)
duration = float(probe.stdout.strip() or 30)

# Hard cap: 8 frames max — more causes gateway timeouts (large base64 payload)
MAX_FRAMES = 8
interval = max(duration / MAX_FRAMES, 5)
fps_val = round(1 / interval, 4)

subprocess.run([ffmpeg, "-y", "-i", str(video), "-vf", f"fps={fps_val}",
  str(frames_dir / "frame_%04d.png")], shell=False, check=True)
frames = sorted(frames_dir.glob("frame_*.png"))[:MAX_FRAMES]
print(f"Extracted {len(frames)} frames (every {interval:.1f}s) to {frames_dir}")
```

**Step 2 — Analyze frames**: call `describe_images` with `task='analyze_sequence'`, passing the frame paths as `image_paths` and `fps` set to `round(1/interval, 4)` from above. **Never pass more than 8 frames** — the gateway times out on larger payloads and hangs the entire backend.

**Do not ask the user to upload or drag-and-drop frames.** `analyze_sequence` reads from disk directly.

Example:
```
describe_images(
  task='analyze_sequence',
  image_paths=[
    'C:\\...\\frames\\frame_0001.png',
    'C:\\...\\frames\\frame_0002.png',
    # up to 8 frames only
  ],
  fps=0.0667
)
```

Returns: `{timeline: [{frame, time_sec, time_label, description}, ...], summary: "..."}`

**Step 3 — Build scene summary**: from the extracted data, produce a list of `{time_sec, description}` entries covering the key moments. Show it to the user as a markdown pipe table, then immediately continue to the narration widget without waiting for user input.

---

## Phase 3: Narration Edit

Draft a narration script from the scene summary. Each segment has a start time and spoken text.

**You MUST use the exact widget template below verbatim.** Do not design your own widget. Do not change the message format. Do not rename the `NARRATION_APPROVED` prefix. The only modification allowed is replacing `SEGMENTS_PLACEHOLDER` with the narration JSON array.

Replace:
- `SEGMENTS_PLACEHOLDER` with a JSON array of `[{start_at: <seconds>, text: "<spoken text>"}]`

The raw video path is fetched automatically by the widget from `/api/recorder/latest-output` — do NOT embed any file path in the widget HTML.

The widget's Approve button sends `NARRATION_APPROVED:<json>` — Phase 4 listens for this exact prefix. Any other prefix (e.g. `NARRATION_V2_APPROVED`) will NOT trigger TTS generation.

```html:widget
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#111827;font-family:system-ui,sans-serif;padding:16px}
  .panel{background:#1a2332;border:1px solid #1e3a52;border-radius:12px;padding:16px;max-width:560px}
  h3{color:#4ade80;font-size:.9rem;font-weight:700;margin-bottom:12px}
  .voice-row{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
  .voice-row label{font-size:.72rem;color:#6b8db5;white-space:nowrap}
  select{background:#111827;border:1px solid #1e3a52;border-radius:6px;color:#dbeafe;padding:5px 8px;font-size:.78rem;font-family:inherit}
  .btn-preview{background:none;border:1px solid #1e3a52;border-radius:6px;color:#6b8db5;padding:5px 10px;font-size:.75rem;cursor:pointer;white-space:nowrap}
  .btn-preview:hover{border-color:#f97316;color:#f97316}
  .btn-preview:disabled{opacity:.4;cursor:not-allowed}
  audio{width:100%;margin-top:6px;accent-color:#f97316;display:none}
  .seg{margin-bottom:14px}
  .seg-label{font-size:.68rem;color:#4a6a8a;margin-bottom:3px;display:flex;align-items:center;gap:6px}
  .seg-dirty{font-size:.6rem;color:#f97316;font-weight:700;display:none}
  .seg-text{width:100%;background:#111827;border:1px solid #1e3a52;border-radius:6px;color:#dbeafe;padding:7px 10px;font-size:.8rem;font-family:inherit;resize:vertical;min-height:52px;transition:border-color .15s}
  .seg-text:focus{outline:none;border-color:#4ade80}
  .seg-text.dirty{border-color:#f97316}
  .seg-actions{display:flex;gap:6px;margin-top:4px;align-items:center}
  .btn-seg-preview{background:none;border:1px solid #1e3a52;border-radius:5px;color:#6b8db5;padding:3px 8px;font-size:.7rem;cursor:pointer}
  .btn-seg-preview:hover{border-color:#f97316;color:#f97316}
  .seg-audio{width:100%;margin-top:4px;accent-color:#f97316;display:none}
  .btn-play-all{background:none;border:1px solid #1e3a52;border-radius:6px;color:#6b8db5;padding:5px 12px;font-size:.75rem;cursor:pointer;white-space:nowrap}
  .btn-play-all:hover{border-color:#f97316;color:#f97316}
  .btn-play-all.playing{border-color:#f97316;color:#f97316}
  .video-section{margin-top:14px;border-top:1px solid #1e3a52;padding-top:12px}
  .video-section h4{font-size:.75rem;color:#6b8db5;margin-bottom:6px}
  video{width:100%;border-radius:8px;background:#000;display:block}
  .btn-approve{width:100%;padding:10px;background:rgba(74,222,128,.15);border:1px solid rgba(74,222,128,.35);border-radius:8px;color:#4ade80;font-size:.85rem;font-weight:700;cursor:pointer;margin-top:12px}
  .btn-approve:hover{background:rgba(74,222,128,.25)}
  .status{font-size:.7rem;color:#6b8db5;margin-top:6px;min-height:14px}
</style>
</head>
<body>
<div class="panel">
  <h3>✏️ Edit Narration Script</h3>

  <div class="voice-row">
    <label>Voice</label>
    <select id="sel-voice" onchange="clearGlobalPreview()">
      <option value="af_heart">af_heart — warm female (default)</option>
      <option value="af_alloy">af_alloy — neutral female</option>
      <option value="af_nova">af_nova — bright female</option>
      <option value="am_echo">am_echo — neutral male</option>
      <option value="am_onyx">am_onyx — deep male</option>
      <option value="bf_emma">bf_emma — British female</option>
      <option value="bm_george">bm_george — British male</option>
    </select>
    <label>Speed</label>
    <select id="sel-speed">
      <option value="0.9">0.9×</option>
      <option value="1.0" selected>1.0×</option>
      <option value="1.1">1.1×</option>
      <option value="1.2">1.2×</option>
    </select>
    <button class="btn-preview" id="btn-global-preview" onclick="previewGlobal()">▶ Preview voice</button>
    <button class="btn-play-all" id="btn-play-all" onclick="playAll()">▶▶ Play all</button>
  </div>
  <audio id="global-audio" controls></audio>
  <div class="status" id="status"></div>

  <div id="segs"></div>

  <div class="video-section" id="video-section" style="display:none">
    <h4>📹 Raw recording preview</h4>
    <video id="video-player" controls preload="metadata"></video>
  </div>

  <button class="btn-approve" onclick="approve()">✓ Approve & Generate TTS</button>
</div>
<script>
var _BASE = window._GATOR || 'http://localhost:8003';
var data = SEGMENTS_PLACEHOLDER;
var _videoPath = '';

// ── Voice preview ─────────────────────────────────────────────────────────────
function getVoice(){ return document.getElementById('sel-voice').value; }
function getSpeed(){ return parseFloat(document.getElementById('sel-speed').value)||1.0; }

function setStatus(msg, color){ 
  var s=document.getElementById('status');
  s.textContent=msg; s.style.color=color||'#6b8db5';
}

function clearGlobalPreview(){
  var a=document.getElementById('global-audio');
  a.style.display='none'; a.src='';
}

function previewGlobal(){
  var voice=getVoice();
  var sampleText='Hello, this is a preview of the '+voice+' voice for your demo narration.';
  var btn=document.getElementById('btn-global-preview');
  btn.disabled=true; btn.textContent='Loading...';
  setStatus('Generating preview...','#f97316');
  fetchPreview(sampleText, voice, function(url, err){
    btn.disabled=false; btn.textContent='▶ Preview voice';
    if(err){ setStatus('Preview failed: '+err,'#f87171'); return; }
    var a=document.getElementById('global-audio');
    a.src=url; a.style.display='block'; a.play();
    setStatus('','');
  });
}

function previewSeg(i){
  var text=document.getElementById('s'+i).value.trim();
  if(!text){ return; }
  var btn=document.getElementById('pb'+i);
  btn.disabled=true; btn.textContent='...';
  fetchPreview(text, getVoice(), function(url, err){
    btn.disabled=false; btn.textContent='▶';
    if(err){ return; }
    var a=document.getElementById('sa'+i);
    a.src=url; a.style.display='block'; a.play();
  });
}

function fetchPreview(text, voice, cb){
  fetch(_BASE+'/api/recorder/tts-preview', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:text, voice:voice, model:'kokoro-v1'})
  }).then(function(r){
    if(!r.ok){ return r.json().then(function(d){ cb(null, d.error||r.status); }); }
    return r.blob().then(function(b){ cb(URL.createObjectURL(b), null); });
  }).catch(function(e){ cb(null, String(e)); });
}

var _playAllActive=false;
var _playAllCtx=null;
var _playAllSource=null;

function playAll(){
  if(_playAllActive){ _stopPlayAll(); return; }
  var btn=document.getElementById('btn-play-all');
  _playAllActive=true; btn.textContent='■ Stop'; btn.classList.add('playing');
  setStatus('Fetching all segments...','#f97316');

  var segs=data.map(function(s,i){
    return {text:document.getElementById('s'+i).value.trim(), idx:i};
  }).filter(function(s){ return s.text; });

  // Fetch all segments in parallel, then concatenate into one AudioBuffer
  // for perfectly gapless playback — same as the final merged MP4.
  var voice=getVoice();
  Promise.all(segs.map(function(seg){
    return new Promise(function(resolve){
      fetchPreview(seg.text, voice, function(url, err){
        resolve(err||!url ? null : url);
      });
    });
  })).then(function(urls){
    if(!_playAllActive) return;
    // Fetch each blob and decode to AudioBuffer
    var ctx=new (window.AudioContext||window.webkitAudioContext)();
    _playAllCtx=ctx;
    setStatus('Decoding audio...','#f97316');
    return Promise.all(urls.map(function(url){
      if(!url) return Promise.resolve(null);
      return fetch(url).then(function(r){ return r.arrayBuffer(); })
        .then(function(ab){ return ctx.decodeAudioData(ab); })
        .catch(function(){ return null; });
    }));
  }).then(function(buffers){
    if(!_playAllActive||!_playAllCtx) return;
    var ctx=_playAllCtx;
    // Concatenate all decoded buffers into one
    buffers=buffers.filter(Boolean);
    if(!buffers.length){ _stopPlayAll(); return; }
    var sampleRate=buffers[0].sampleRate;
    var channels=buffers[0].numberOfChannels;
    var totalLen=buffers.reduce(function(acc,b){ return acc+b.length; },0);
    var merged=ctx.createBuffer(channels, totalLen, sampleRate);
    var offset=0;
    buffers.forEach(function(b){
      for(var c=0;c<channels;c++){
        merged.getChannelData(c).set(b.getChannelData(c), offset);
      }
      offset+=b.length;
    });
    // Play the single merged buffer
    var src=ctx.createBufferSource();
    _playAllSource=src;
    src.buffer=merged;
    src.connect(ctx.destination);
    src.onended=function(){ _stopPlayAll(); };
    src.start(0);
    setStatus('Playing...','#4ade80');
  }).catch(function(e){
    setStatus('Playback error: '+e,'#f87171');
    _stopPlayAll();
  });
}

function _stopPlayAll(){
  _playAllActive=false;
  if(_playAllSource){ try{ _playAllSource.stop(); }catch(e){} _playAllSource=null; }
  if(_playAllCtx){ try{ _playAllCtx.close(); }catch(e){} _playAllCtx=null; }
  var btn=document.getElementById('btn-play-all');
  if(btn){ btn.textContent='▶▶ Play all'; btn.classList.remove('playing'); }
  setStatus('','');
}

// ── Segments ──────────────────────────────────────────────────────────────────
var c=document.getElementById('segs');
data.forEach(function(s,i){
  var d=document.createElement('div'); d.className='seg';
  var l=document.createElement('div'); l.className='seg-label';
  var ltext=document.createElement('span'); ltext.textContent='Segment '+(i+1)+' — '+(s.start_at||s.start||0)+'s';
  var dirty=document.createElement('span'); dirty.className='seg-dirty'; dirty.id='dirty'+i; dirty.textContent='● edited';
  l.appendChild(ltext); l.appendChild(dirty);
  var t=document.createElement('textarea'); t.className='seg-text'; t.value=s.text; t.id='s'+i;
  t.oninput=function(){
    t.classList.add('dirty');
    document.getElementById('dirty'+i).style.display='inline';
  };
  var acts=document.createElement('div'); acts.className='seg-actions';
  var pb=document.createElement('button'); pb.className='btn-seg-preview';
  pb.id='pb'+i; pb.textContent='▶'; pb.title='Preview this segment';
  pb.onclick=function(){ previewSeg(i); };
  acts.appendChild(pb);
  var sa=document.createElement('audio'); sa.controls=true; sa.id='sa'+i;
  sa.className='seg-audio';
  d.appendChild(l); d.appendChild(t); d.appendChild(acts); d.appendChild(sa);
  c.appendChild(d);
});

// ── Video preview — path fetched from server, never embedded in JS ────────────
fetch(_BASE+'/api/recorder/latest-output')
  .then(function(r){ return r.json(); })
  .then(function(d){
    _videoPath=d.raw||d.final||'';
    if(_videoPath){
      var vp=document.getElementById('video-player');
      var vs=document.getElementById('video-section');
      vp.src=_BASE+'/api/recorder/serve-file?path='+encodeURIComponent(_videoPath);
      vp.onerror=function(){ vs.style.display='none'; };
      vs.style.display='block';
    }
  })
  .catch(function(){});

// ── Approve ───────────────────────────────────────────────────────────────────
function approve(){
  var voice=getVoice();
  var speed=getSpeed();
  var out=data.map(function(s,i){
    return {start_at:s.start_at||s.start||0, text:document.getElementById('s'+i).value, voice:voice, speed:speed};
  });
  parent.postMessage({type:'gator:send-message',
    text:'NARRATION_APPROVED:'+JSON.stringify(out)},'*');
}
</script>
</body>
</html>
```

---

## Phase 4: TTS + Merge

When you receive `"Narration approved (N segments)..."` or `"✓ Approve..."`:

1. Read the approved segments from `~/.gator/narration_pending.json` — this file is written by the Approve button and contains `{segments: [...], flags: {...}}`. **Always read from this file rather than parsing the trigger message** — the trigger message is just a notification, the actual edited text is in the file. If the file doesn't exist, ask the user to click the Approve button in the widget.
2. Run `scripts/tts_pipeline.py`:

```python
import subprocess, sys, json, urllib.request
from pathlib import Path

video_path = r"<path from 'Recording complete' message>"
pending = json.loads((Path.home() / ".gator/narration_pending.json").read_text())
segments = pending["segments"]   # always read from file — has the edited text
flags = pending.get("flags", {})
session_dir = Path(video_path).parent
narration_file = session_dir / "narration.json"
narration_file.write_text(json.dumps(segments))
timeline_file = session_dir / "timeline.json"
timeline_file.write_text(json.dumps({}))
output_path = session_dir / "final_with_narration.mp4"

# Locate tts_pipeline.py — check both built-in and user-installed locations
_skill_dirs = [
    Path.home() / ".gator/skills/mine/gator-demo-recorder/scripts",
    Path(__file__).parent / "scripts" if "__file__" in dir() else None,
    Path.cwd() / "web/skills/gator-demo-recorder/scripts",
]
skill_dir = next((d for d in _skill_dirs if d and d.exists()), _skill_dirs[0])

voice = segments[0].get("voice", "af_heart") if segments else "af_heart"
speed = str(segments[0].get("speed", 1.0)) if segments else "1.0"

result = subprocess.run([
    sys.executable,
    str(skill_dir / "tts_pipeline.py"),
    "--video", video_path,
    "--timeline", str(timeline_file),
    "--narration", str(narration_file),
    "--output", str(output_path),
    "--work-dir", str(session_dir / "tts_work"),
    "--voice", voice,
], capture_output=True, text=True, timeout=600, shell=False)
print(result.stdout[-3000:])
if result.stderr: print("STDERR:", result.stderr[-500:])

# Always check output regardless of return code — tts_pipeline.py can succeed
# even with non-zero exit on some platforms
if output_path.exists():
    size_mb = output_path.stat().st_size / 1048576
    print(f"SUCCESS: {output_path} ({size_mb:.1f} MB)")
    # Register the final path server-side so Phase 5 widget can fetch it
    # without any path embedded in JS (eliminates backslash-escaping bugs)
    import urllib.request as _ur2
    _req = _ur2.Request(
        'http://localhost:8003/api/recorder/set-output',
        data=json.dumps({'final': str(output_path), 'raw': video_path}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    try: _ur2.urlopen(_req, timeout=5).read()
    except Exception as e: print(f"Note: set-output failed: {e}")
else:
    print(f"ERROR: output file not found at {output_path}")
```

After running this code:
- If output file exists → immediately proceed to Phase 5 with that path
- If output file missing → report the stderr and offer to deliver video without narration
- **Do not stop and ask the user** — check the file yourself and move on

If Lemonade TTS is unavailable (preflight `lemonade.ok` is false), tell the user and offer to deliver the video without narration. The TTS endpoint is `/v1/audio/speech` (OpenAI-compatible) and the model is `kokoro-v1` — both confirmed by preflight. Do not probe other endpoints.

---

## Phase 5: Deliver

Before showing the widget, call `POST /api/recorder/set-output` with the final merged path so the widget can fetch it without any path embedded in JS (eliminates all backslash-escaping bugs):

```python
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:8003/api/recorder/set-output',
    data=json.dumps({'final': str(output_path), 'raw': video_path}).encode(),
    headers={'Content-Type': 'application/json'}, method='POST')
urllib.request.urlopen(req, timeout=5).read()
print('Output registered.')
```

Then output this widget verbatim — no placeholders to replace:

```html:widget
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#111827;font-family:system-ui,sans-serif;padding:16px}
  .panel{background:#1a2332;border:1px solid #1e3a52;border-radius:12px;padding:16px;max-width:560px}
  h3{color:#4ade80;font-size:.9rem;font-weight:700;margin-bottom:10px}
  video{width:100%;border-radius:8px;background:#000;display:block;margin-bottom:10px}
  .meta{font-size:.72rem;color:#6b8db5;margin-bottom:10px;word-break:break-all}
  .actions{display:flex;gap:8px;flex-wrap:wrap}
  .btn{padding:8px 14px;border-radius:7px;border:none;font-size:.78rem;font-weight:700;cursor:pointer}
  .btn-download{background:rgba(74,222,128,.15);border:1px solid rgba(74,222,128,.35);color:#4ade80}
  .btn-download:hover{background:rgba(74,222,128,.25)}
  .btn-edit{background:rgba(96,165,250,.1);border:1px solid rgba(96,165,250,.3);color:#60a5fa}
  .btn-edit:hover{background:rgba(96,165,250,.2)}
  .btn-clean{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#f87171}
  .btn-clean:hover{background:rgba(239,68,68,.2)}
</style>
</head>
<body>
<div class="panel">
  <h3>🎬 Demo Ready</h3>
  <video id="vp" controls preload="metadata"></video>
  <div class="meta" id="meta">Loading...</div>
  <div class="actions">
    <button class="btn btn-download" onclick="download()">⬇ Download</button>
    <button class="btn btn-edit" onclick="editNarration()">✏️ Edit narration & regenerate</button>
    <button class="btn btn-clean" onclick="cleanup()">🗑 Delete intermediates</button>
  </div>
</div>
<script>
var _BASE=window._GATOR||'http://localhost:8003';
var _finalPath='', _encoded='';
var vp=document.getElementById('vp');

fetch(_BASE+'/api/recorder/latest-output')
  .then(function(r){ return r.json(); })
  .then(function(d){
    _finalPath=d.final||d.raw||'';
    _encoded=encodeURIComponent(_finalPath);
    vp.src=_BASE+'/api/recorder/serve-file?path='+_encoded;
  })
  .catch(function(e){ document.getElementById('meta').textContent='Error loading: '+e; });

vp.onloadedmetadata=function(){
  document.getElementById('meta').innerHTML=
    '<span style="color:#6b8db5">'+_finalPath+'</span> — '+Math.round(vp.duration)+'s';
};
vp.onerror=function(){
  document.getElementById('meta').textContent='Could not load video. Check path via /api/recorder/latest-output';
};
function download(){
  var a=document.createElement('a');
  a.href=_BASE+'/api/recorder/serve-file?path='+_encoded;
  a.download=_finalPath.replace(/^.*[\\\/]/,'');
  document.body.appendChild(a); a.click(); a.remove();
}
function editNarration(){
  parent.postMessage({type:'gator:send-message',
    text:'NARRATION_REEDIT: Re-show the Phase 3 narration editor widget now.'},'*');
}
function cleanup(){
  parent.postMessage({type:'gator:send-message',
    text:'Please delete the frames/ and tts_work/ intermediates for the current session.'},'*');
}
</script>
</body>
</html>
```

After showing the widget, report the file path and size in plain text for reference.

Always clean up: delete the `frames/` and `tts_work/` directories after delivery (user can trigger via Delete intermediates button).
