---
name: Gator Demo Recorder
description: Record your screen manually, then analyze, narrate with TTS, and deliver a polished MP4.
version: '2.0'
---

# Gator Demo Recorder

Record your screen manually using the in-chat widget. After recording, analyze the video, write and edit a narration script, generate TTS voiceover, merge, and deliver a final MP4.

## Pipeline

```
Phase 1: RENDER WIDGET      — user clicks Record / Stop in chat
Phase 2: ANALYZE            — describe_images(analyze_video), build scene summary
Phase 3: NARRATION EDIT     — draft script, show editable widget, user approves
Phase 4: TTS + MERGE        — demo_merge_narration: Lemonade audio, merge, verified output
Phase 5: DELIVER            — report final MP4 path, offer to save to OneDrive
```

**Import Mode:** when the user attached existing video or audio instead of recording, skip Phase 1 and follow the Import Mode section below. It produces the same inputs Phase 2 expects.

---

## Project folder

Every demo lives in its own project folder, chosen by the user (Settings → General, or "Save project to…" when the project is created). Resolve it from the active-project index; never hard-code a path:

```python
import json, pathlib
idx = json.loads((pathlib.Path.home() / ".gator" / "demo_projects.json").read_text(encoding="utf-8"))
proj = next(p for p in idx["projects"] if p["project_id"] == idx["active_project_id"])
PROJECT_DIR = pathlib.Path(proj["path"])
```

Layout: `source/` (recorded segments and `recording.mp4`), `work/` (`narration.json`, `tts/`, `logs/`), `final/` (the delivered video), `previous/` (archived earlier finals).

- The approved narration is loaded and verified by `demo_merge_narration` (see Phase 4); `work/narration.json` is a mirror, not the source of truth.
- Write TTS audio and intermediates under `work/tts/` and logs under `work/logs/`.
- `demo_merge_narration` writes the deliverable as `final/<project name>_v<N>.mp4`. The file's presence in `final/` is the registration — there is nothing to call.
- Never call a mutating `/api/` route from agent code. Read files and write files only.

---

## CRITICAL RULES — Read first

- **Shell:** always `shell='powershell'` or `shell='cmd'`. Never `shell='bash'`.
- **ffmpeg:** never search with `Get-ChildItem -Recurse` — it times out. Call `GET /api/recorder/status` — it returns `ffmpeg_path` AND `ffprobe_path` with the exact binary locations. Use those fields directly. Never derive ffprobe from ffmpeg via string replace — the paths differ. If `ffmpeg` is false, tell user: `winget install Gyan.FFmpeg` (Windows), `brew install ffmpeg` (macOS).
- **File path:** the widget sends `"Recording complete. File: <path> ..."` after Stop. Extract the path from that message directly — **never ask the user for the path**. It is the value between `"File: "` and `" ("` — or, when no size is shown, `". Please"`.
- **Trigger:** any message matching `"Recording complete. File:"` means the user just stopped recording. Immediately proceed to Phase 2 using the path from the message.
- **Recording:** the widget calls `/api/recorder/start` and `/api/recorder/stop` directly — **do not invoke ffmpeg manually**. Do not call `run_shell` for record/stop.
- **Output size:** never generate more than ~300 lines of output in one turn. Split long work across turns.
- **NEVER skip Phase 3 (Narration Edit):** you MUST render the editable narration widget with the "✓ Approve & Generate TTS" button and WAIT for the user to click it. Do NOT generate TTS until you receive `"NARRATION_APPROVED:<json>"`. Generating TTS without showing the approval widget is a critical violation — the user must be able to review, edit text, preview voices, and approve before any audio is generated.
- **Use the EXACT Phase 3 widget template:** do not design your own narration widget. Do not change the message prefix from `NARRATION_APPROVED` to anything else (e.g. `NARRATION_V2_APPROVED` will silently break Phase 4). Do not remove the voice selector, speed selector, preview buttons, or the raw recording video preview from the template. The template is in SKILL.md — copy it verbatim, only replacing `SEGMENTS_PLACEHOLDER` and `PROJECT_ID_PLACEHOLDER`. The video path is fetched automatically.
- **Re-edit flow:** when the user clicks "Edit narration & regenerate" in the Phase 5 delivery widget, go back to Phase 3 and render the **exact same Phase 3 widget template** again (with voice selector, preview buttons, video preview). Do NOT design a custom "v2" editor. Do NOT change the `NARRATION_APPROVED` prefix. The re-edit widget must be identical to the first-pass widget.
- **Never embed file paths in widget JS.** Widget templates have no `PATH_PLACEHOLDER` strings — they fetch the active project's paths from `GET /api/demo-projects/active` on load.

## Audio/Video Quality Rules — Non-negotiable

The final video must be **professional quality**. Apply these without being asked:

- **Audio/video sync:** narration `start_at` timestamps must align with the actual on-screen action. A segment narrating "clicking the button" must start when the click is visible, not 2 seconds before or after. After TTS generation, compare each segment's `start_at` to the video duration — if the narration ends significantly before the video ends (>2s gap), add a closing segment; if narration runs much longer than the video (>3× video duration), shorten the script and re-generate.
- **Sync validation:** `demo_merge_narration` measures the video and audio streams of the output and refuses to deliver a file whose durations differ by more than 1s. Report `video_stream_sec` and `audio_stream_sec` from its result; when `video_extended_by_sec` is above 0, say the last frame was held that long.
- **Segment timing:** `start_at` values must be monotonically increasing and respect the video timeline. Segment 1 at `start_at: 0`, Segment 2 no earlier than `start_at: 2` (give each segment breathing room). Do not bunch all segments at `start_at: 0, 1, 2, 3` for an 8-second video.
- **Professional pacing:** narration should feel like a polished product demo, not a speed-read. Prefer 3-5 well-paced segments over 8 rushed ones. Each spoken segment should be 1-2 natural sentences (~5-12 seconds of audio). Leave silence at the start (0.5s) and end.
- **Background music:** when mixing, target narration at -3dB and music at -20dB to -18dB. Music must fade in (0.5s) and fade out (1s before video end). Never let music overpower narration.

---

## Truthful Media Claims — Non-negotiable

Every statement about a video's duration, a moment in it, or an edit must come from a `demo_*` tool result obtained in this turn. Never estimate, remember, or infer one. Pass `project_id` (the id on the `PINNED PROJECT:` line) to every `demo_*` call.

- **Facts first:** call `demo_media_manifest` before stating a duration or listing files.
- **Moments:** to say what happens at a time, call `demo_inspect_frames` for that time, pass the returned `frames[].path` values to `describe_images`, and describe only what those frames show. Times must be inside `duration_sec`. On `out_of_range`, report its `duration_sec` and `options`; do not retry with another guessed time.
- **Edits:** use `demo_replace_interval` or `demo_append_clip`. Quote `replaced_interval_sec`, `inserted_from` / `appended_from` and `output.duration_sec` exactly as returned. Say an edit was made only after the result has `ok: true`.
- **Shortening:** when the user wants a target length, call `demo_media_manifest` for the real duration, inspect frames to find dead time (loading waits, dropdowns), then use `demo_cut_intervals` to remove it or `demo_speed_interval` to fast-forward it. Quote `cut_intervals_sec`, `removed_sec`, `sped_interval_sec`, `saved_sec` and `output.duration_sec` exactly; if the result is still longer than the target, say by how much instead of claiming it fits.
- **After a cut or speed-up:** narration `start_at` values were written for the old timeline. Move each one through the result's `time_map` (find the entry whose `old_sec` contains it and map it into `new_sec`), reword or drop any segment whose moment was removed, and render the Phase 3 widget again. The earlier approval is stale, so the user must approve again before `demo_merge_narration`.
- **Narration merge:** `demo_merge_narration` is the only way to produce the final video. Quote `video_extended_by_sec`, `video_stream_sec`, `audio_stream_sec` and `intro` from its result.
- **Intro wording:** "Hold" freezes the first frame; "Title card" shows the title text on a plain card. Use the word that matches `intro.mode`.
- **On any `error`:** relay `message` and the measured numbers, offer the listed `options`, and do not claim success.

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
- The first screen or record action shows an Allow prompt above the widget, outside it. The user clicks it once; do not try to work around it
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
var _actionError = '';

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

// Inline in chat the widget is sandboxed (opaque origin): it cannot call the
// backend, so each call is a named gator:recorder action handled by the parent.
// In the floating HUD window (parent === window) it calls the backend directly.
var _INLINE = window.parent !== window;
var _rid = 0, _pending = {};
window.addEventListener('message', function(ev) {
  var m = ev.data;
  if (ev.source !== parent || !m || m.type !== 'gator:recorder-result') return;
  var cb = _pending[m.rid];
  if (!cb) return;
  delete _pending[m.rid];
  cb(null, m.data);
});

function bridgeCall(action, params, cb) {
  var id = ++_rid;
  _pending[id] = cb;
  var msg = {type:'gator:recorder', action:action, rid:id};
  if (params) msg.params = params;
  parent.postMessage(msg, '*');
  setTimeout(function() {
    if (!_pending[id]) return;
    delete _pending[id];
    cb(new Error('no reply from AI Gator'), null);
  }, action === 'pick-region' ? 600000 : 60000);
}

function apiFetch(action, params, cb) {
  if (_INLINE) { bridgeCall(action, params, cb); return; }
  var m = (action==='status'||action==='screens') ? 'GET' : 'POST';
  var opts = {method:m};
  if (m==='POST' && params) { opts.body=JSON.stringify(params); opts.headers={'Content-Type':'application/json'}; }
  fetch(_BASE+'/api/recorder/'+action, opts)
    .then(function(r){return r.json();})
    .then(function(d){cb(null,d);})
    .catch(function(e){cb(e,null);});
}

function actionFailed(err, data, label) {
  if (!err && data && data.ok) return false;
  _actionError = label + ': ' + ((data && data.error) || (err && err.message) || 'request failed');
  if (data && data.session_dir) _actionError += ' (' + data.session_dir + ')';
  var st = document.getElementById('status');
  st.className = 'status error';
  st.textContent = _actionError;
  return true;
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
  if (_actionError) { st.className = 'status error'; st.textContent = _actionError; }
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
  apiFetch('select-screen', {screen_index: si}, function() {});
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
    _crop = {x:data.screen_x, y:data.screen_y, w:data.w, h:data.h};
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
  _busy = true; _stopPath = ''; _actionError = '';
  var p = {screen_index: parseInt(document.getElementById('sel-screen').value)||0, force:true};
  if (_crop) { p.crop_x=_crop.x; p.crop_y=_crop.y; p.crop_w=_crop.w; p.crop_h=_crop.h; }
  document.getElementById('status').textContent = 'Starting...';
  apiFetch('start', p, function(err, data) {
    _busy = false;
    actionFailed(err, data, 'Error');
  });
}

function doPause() {
  _busy = true; _actionError = '';
  apiFetch('pause', null, function(err, data) { _busy = false; actionFailed(err, data, 'Pause error'); });
}

function doResume() {
  _busy = true; _actionError = '';
  apiFetch('resume', null, function(err, data) { _busy = false; actionFailed(err, data, 'Resume error'); });
}

function doStop() {
  _busy = true; _actionError = '';
  document.getElementById('status').textContent = 'Stopping...';
  document.getElementById('btn-stop').disabled = true;
  apiFetch('stop', null, function(err, data) {
    _busy = false;
    if (!err && data && data.ok) {
      _stopPath = data.path || '';
      var mb = data.size_bytes ? (data.size_bytes/1048576).toFixed(1)+'MB' : '';
      document.getElementById('status').className = 'status done';
      document.getElementById('status').textContent = '✓ Saved' + (mb ? ' ' + mb : '');
      document.getElementById('filepath').textContent = _stopPath;
      // Reset crop after each recording so the next Record starts fresh.
      // User can re-select a region if needed — no stale state carried over.
      clearCrop();
      // Notify the Gator chat.
      // Inline widget: parent.postMessage triggers the bridge in app.js.
      // HUD widget: parent === window so postMessage goes nowhere — instead
      // POST to /api/recorder/notify which the Gator frontend polls every 2s.
      var msg = 'Recording complete. File: '+_stopPath+(mb ? ' ('+mb+')' : '')+'. Please analyze it and draft a narration script.';
      try { parent.postMessage({type:'gator:send-message', pin_skill:'gator-demo-recorder', project_id:(data&&data.project_id)||'', text:msg},'*'); } catch(e){}
      if (!_INLINE) {
        try {
          fetch(_BASE+'/api/recorder/notify', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({message:msg})
          });
        } catch(e){}
      }
    } else {
      actionFailed(err, data, 'Stop error');
    }
  });
}
</script>
</body>
</html>
```

---

## Import Mode

Use this instead of Phase 1 when the message contains `[File: <path>]` chips whose paths end in a video or audio extension and sit inside a project's `source/` folder (`<PROJECT_DIR>/source/<id>_<name>`), or when the user asks you to narrate footage they already have. There is no recording to wait for.

The browser uploads each file and builds one combined, trimmed timeline in the background. The user orders and trims clips in the clips panel above the chat box. You only read the result: `<PROJECT_DIR>/project.json` holds it under `ext["clips"]` (`clips`, `audio`, and `timeline` with `state`, `file`, `duration`, `frame_times`, `clips`, `error`).

- **Never call** `/api/demo-media` routes that change anything (upload, order, trim, delete) — they are for the browser. To change clips, tell the user to use the clips panel.
- Audio-only attachments are a music bed. If there is no video clip yet, ask the user to attach one.

Run this once per request. It waits for the timeline and prints its path:

```python
import json, time
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
    print(f"VIDEO={PROJECT_DIR / tl['file']}")
    print(f"DURATION={tl['duration']}")
    print("FRAME_TIMES=", json.dumps(tl["frame_times"]))
    print("CLIPS=", json.dumps(tl["clips"]))
```

Outcomes:

- `TIMELINE FAILED` → tell the user the `error` text and stop; they can remove or replace the clip in the panel.
- `TIMELINE NOT READY` → tell the user no video clip is attached yet, or the build has not started, and stop.
- Otherwise `VIDEO` is the file Phase 4 merges into (it is also the project's `raw`). Continue at **Phase 2, Step 1** with `video_path` set to `VIDEO`: call `describe_images(task='analyze_video', video_path='<VIDEO>')`. It samples the combined timeline at the moments listed in `frame_times`. Use the `CLIPS` boundaries (`start`/`end` seconds per source clip) to say which clip each frame belongs to in the scene summary, then continue to Phase 3. Do not run ffmpeg yourself.
- Phase 3 timing: narration `start_at` values are seconds on the combined timeline, so a segment about the second clip starts at or after that clip's `start`.
- Phase 4: `demo_merge_narration` merges into the project's recording (`VIDEO` is also its `raw`), so pass no `video`. The combined music bed, if any, is `work/soundtrack.m4a`, and `demo_merge_narration` mixes it in automatically once the timeline is ready.

---

## Phase 2: Analyze

When you receive `"Recording complete. File: <path> ..."`:

1. Extract the video path: it is the text between `"File: "` and the next `" ("` — or, when the message shows no size, up to `". Please"`. Example: `"Recording complete. File: C:\Users\...\final.mp4 (46MB). Please analyze it…"` → path = `C:\Users\...\final.mp4`
2. Proceed immediately — do not ask the user for the path, and do not run ffmpeg or ffprobe yourself.

**Step 1 — Analyze the video**: call `describe_images(task='analyze_video', video_path='<path>')`. The tool finds ffmpeg/ffprobe, extracts up to 8 evenly spaced keyframes (at least ~5 s apart) into a private temporary folder, analyzes them, and deletes them.

**Do not ask the user to upload or drag-and-drop frames.**

Returns: `{timeline: [{frame, time_sec, time_label, description}, ...], summary: "..."}`

**Step 2 — Build scene summary**: from the extracted data, produce a list of `{time_sec, description}` entries covering the key moments. Show it to the user as a markdown pipe table, then immediately continue to the narration widget without waiting for user input.

**Follow-up inspection:** to look at a specific moment after the first analysis, call `demo_inspect_frames(source='<project-relative path>', times_sec=[...])` (at most 8 times, all inside the video's duration) and pass the returned frame paths to `describe_images`. Do not write your own frame-extraction code.

---

## Phase 3: Narration Edit

Draft a narration script from the scene summary. Each segment has a start time and spoken text.

**You MUST use the exact widget template below verbatim.** Do not design your own widget. Do not change the message format. Do not rename the `NARRATION_APPROVED` prefix. The only modifications allowed are replacing `SEGMENTS_PLACEHOLDER` with the narration JSON array and `PROJECT_ID_PLACEHOLDER` with the project id.

Replace:

- `SEGMENTS_PLACEHOLDER` with a JSON array of `[{start_at: <seconds>, text: "<spoken text>"}]`. Each item may also carry an optional `pause_after` (seconds of silence after that segment, 0 to 10) — the widget shows it in the "Pause after" box.
- `PROJECT_ID_PLACEHOLDER` with the project id from the `PINNED PROJECT:` line of your context (for example `demo_20261019_101500`)

The widget learns the raw video's project-relative path from the parent (`gator:demo-summary`) and plays it through the project's file route (`/api/demo-projects/<id>/file`) using the project id — do NOT embed any file path in the widget HTML.

The widget's Approve button sends `NARRATION_APPROVED:<json> PROJECT_ID:<id>` — Phase 4 listens for this exact prefix. The app records the approval first and then starts the Phase 4 turn with the approval id. Any other prefix (e.g. `NARRATION_V2_APPROVED`) will NOT trigger TTS generation.

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
  .seg-pause{display:flex;align-items:center;gap:4px;font-size:.68rem;color:#6b8db5;margin-left:auto}
  .seg-pause input{width:56px;background:#111827;border:1px solid #1e3a52;border-radius:5px;color:#dbeafe;padding:3px 6px;font-size:.72rem;font-family:inherit}
  .seg-pause input:focus{outline:none;border-color:#4ade80}
  .seg-pause-hint{color:#f97316;font-weight:600}
  .help{position:relative;display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border:1px solid #1e3a52;border-radius:50%;color:#6b8db5;font-size:.7rem;cursor:help}
  .help:hover,.help:focus{border-color:#f97316;color:#f97316;outline:none}
  .tip{display:none;position:absolute;top:24px;left:0;width:min(260px,calc(100vw - 80px));z-index:5;background:#0f1a28;border:1px solid #1e3a52;border-radius:8px;padding:8px 10px;font-size:.7rem;line-height:1.4;color:#dbeafe;text-align:left;cursor:default}
  .help:hover .tip,.help:focus .tip,.help:focus-within .tip{display:block}
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
    <span class="help" tabindex="0" role="button" aria-describedby="pacing-tip" aria-label="Pacing tips">?<span class="tip" role="tooltip" id="pacing-tip"><b>Pacing tips</b> — Use commas and periods for natural breaths; use <code>…</code> for a longer, trailing pause. For an exact silent gap after this section, set <b>Pause after</b>.</span></span>
  </div>
  <audio id="global-audio" controls></audio>
  <div class="status" id="status"></div>

  <div id="segs"></div>

  <div class="video-section" id="video-section" style="display:none">
    <h4>📹 Raw recording preview</h4>
    <video id="video-player" controls preload="metadata"></video>
  </div>

  <button id="btn-approve" class="btn-approve" onclick="approve()">✓ Approve & Generate TTS</button>
  <div class="status" id="merge-status"></div>
</div>
<script>
var _BASE = window._GATOR || 'http://localhost:8003';
var data = SEGMENTS_PLACEHOLDER;
var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER';
var _approving = false;

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

// The frame is sandboxed and cannot call the backend; the parent runs the preview.
var _previewRid=0, _previewPending={};

function fetchPreview(text, voice, cb){
  var id=++_previewRid;
  _previewPending[id]=cb;
  parent.postMessage({type:'gator:tts-preview', rid:id, text:text, voice:voice}, '*');
  setTimeout(function(){
    var c=_previewPending[id];
    if(!c){ return; }
    delete _previewPending[id];
    c(null, 'no reply from AI Gator');
  }, 60000);
}

function onPreviewResult(ev){
  var m=ev.data;
  if(ev.source!==parent || !m || m.type!=='gator:tts-preview-result'){ return; }
  var cb=_previewPending[m.rid];
  if(!cb){ return; }
  delete _previewPending[m.rid];
  if(!m.ok || !m.blob){ cb(null, m.error||'preview failed'); return; }
  cb(URL.createObjectURL(m.blob), null, m.blob);
}
window.addEventListener('message', onPreviewResult);

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
      fetchPreview(seg.text, voice, function(url, err, blob){
        resolve(err||!blob ? null : blob);
      });
    });
  })).then(function(blobs){
    if(!_playAllActive) return;
    // Decode each blob to an AudioBuffer
    var ctx=new (window.AudioContext||window.webkitAudioContext)();
    _playAllCtx=ctx;
    setStatus('Decoding audio...','#f97316');
    return Promise.all(blobs.map(function(blob){
      if(!blob) return Promise.resolve(null);
      return blob.arrayBuffer()
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

function pauseValue(raw){
  var n=parseFloat(raw);
  if(!isFinite(n)||n<0){ return 0; }
  return Math.min(10, Math.round(n*10)/10);
}

function pauseHint(raw){
  if(raw===''||raw==null){ return ''; }
  var n=parseFloat(raw);
  return (!isFinite(n)||n<0||n>10) ? 'Limited to 0–10 s' : '';
}

function segOut(s, text, voice, speed, pauseRaw){
  return {start_at:s.start_at||s.start||0, text:text, voice:voice, speed:speed, pause_after:pauseValue(pauseRaw)};
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
  var pl=document.createElement('label'); pl.className='seg-pause';
  pl.appendChild(document.createTextNode('Pause after (s)'));
  var pi=document.createElement('input'); pi.type='number'; pi.id='pa'+i;
  pi.min='0'; pi.max='10'; pi.step='0.1'; pi.value=pauseValue(s.pause_after);
  var ph=document.createElement('span'); ph.className='seg-pause-hint';
  pi.oninput=function(){ document.getElementById('dirty'+i).style.display='inline'; ph.textContent=pauseHint(pi.value); };
  pi.onchange=function(){ if(pauseHint(pi.value)){ pi.value=pauseValue(pi.value); } };
  pl.appendChild(pi); pl.appendChild(ph); acts.appendChild(pl);
  var sa=document.createElement('audio'); sa.controls=true; sa.id='sa'+i;
  sa.className='seg-audio';
  d.appendChild(l); d.appendChild(t); d.appendChild(acts); d.appendChild(sa);
  c.appendChild(d);
});

// ── Video preview — summary comes from the parent; the video is a resource load ─
function requestDemoData(type, projectId){
  parent.postMessage({type:type, project_id:projectId}, '*');
}

var _pid=/^demo_\d/.test(_PROJECT_ID)?_PROJECT_ID:'';
if(_pid){ requestDemoData('gator:demo-summary', _pid); requestDemoData('gator:demo-progress', _pid); }

window.addEventListener('message', function(ev){
  var m=ev.data||{};
  if(m.type!=='gator:demo-summary-result' || m.project_id!==_pid){ return; }
  var rel=m.ok && m.summary && m.summary.raw_rel;
  if(!rel){ return; }
  var vp=document.getElementById('video-player');
  var vs=document.getElementById('video-section');
  vp.src=_BASE+'/api/demo-projects/'+_pid+'/file?rel='+encodeURIComponent(rel);
  vp.onerror=function(){ vs.style.display='none'; };
  vs.style.display='block';
});

// ── Approve ───────────────────────────────────────────────────────────────────
function approve(){
  if(_approving) return;
  var voice=getVoice();
  var speed=getSpeed();
  var out=data.map(function(s,i){
    return segOut(s, document.getElementById('s'+i).value, voice, speed, document.getElementById('pa'+i).value);
  });
  var pid=/^demo_\d/.test(_PROJECT_ID)?_PROJECT_ID:'';
  _approving=true;
  var btn=document.getElementById('btn-approve');
  btn.disabled=true; btn.textContent='Approving…';
  parent.postMessage({type:'gator:send-message', pin_skill:'gator-demo-recorder', project_id:pid,
    text:'NARRATION_APPROVED:'+JSON.stringify(out)+(pid?' PROJECT_ID:'+pid:'')},'*');
}
window.addEventListener('message',function(ev){
  var m=ev.data;
  if(!m||m.type!=='gator:narration-approval-result') return;
  var btn=document.getElementById('btn-approve');
  if(m.ok){
    btn.textContent='✓ Approved'+(m.approval&&m.approval.version?' (v'+m.approval.version+')':'');
  }else{
    _approving=false;
    btn.disabled=false;
    btn.textContent='✓ Approve & Generate TTS';
    alert('Approval failed: '+(m.error||'unknown error'));
  }
});

// ── Merge progress ────────────────────────────────────────────────────────────
var _progressTimer=null;

function progressView(p, approvalId, waitedMs, sinceMs){
  var mine=!!p && p.approval_id===approvalId && (p.updated_at||0)*1000>=sinceMs;
  if(mine && p.state==='done'){
    return {text:'Done — your demo video is ready.', color:'#4ade80', stop:true, retry:false};
  }
  if(mine && p.state==='failed'){
    return {text:'Generation failed: '+(p.error||p.message||'unknown error'), color:'#f87171', stop:true, retry:true};
  }
  if(mine && p.state==='running'){
    return {text:p.message||'Generating…', color:'#f97316', stop:false, retry:false};
  }
  if(waitedMs>=120000){
    return {text:'Generation has not started yet. Check that the AI Gator agent is still working, or click Approve to retry.', color:'#f87171', stop:true, retry:true};
  }
  return {text:'Waiting for generation to start…', color:'#6b8db5', stop:false, retry:false};
}

function setMergeStatus(text, color){
  var s=document.getElementById('merge-status');
  s.textContent=text||''; s.style.color=color||'#6b8db5';
}

function stopProgress(){
  if(_progressTimer){ clearInterval(_progressTimer); _progressTimer=null; }
}

var _progressApproval=null, _progressSince=0;

function pollProgress(projectId){
  _progressTimer=setInterval(function(){ requestDemoData('gator:demo-progress', projectId); },1500);
  requestDemoData('gator:demo-progress', projectId);
}

function startProgress(approvalId, projectId){
  stopProgress();
  _progressApproval=approvalId; _progressSince=Date.now();
  pollProgress(projectId);
}

function resumeProgress(p, projectId){
  if(!p || p.state!=='running' || !p.approval_id){ return; }
  var since=(p.updated_at||0)*1000;
  if(Date.now()-since>=120000){ return; }
  _approving=true;
  var btn=document.getElementById('btn-approve');
  btn.disabled=true; btn.textContent='✓ Approved';
  stopProgress();
  _progressApproval=p.approval_id; _progressSince=since;
  pollProgress(projectId);
}

window.addEventListener('message', function(ev){
  var m=ev.data||{};
  if(m.type==='gator:demo-progress-result'){
    if(m.project_id!==_pid){ return; }
    if(!_progressApproval){ resumeProgress(m.ok?m.progress:null, _pid); return; }
    var v=progressView(m.ok?m.progress:{state:'none'}, _progressApproval, Date.now()-_progressSince, _progressSince);
    setMergeStatus(v.text, v.color);
    if(v.stop){ stopProgress(); }
    if(v.retry){
      _approving=false;
      var rb=document.getElementById('btn-approve');
      rb.disabled=false; rb.textContent='✓ Approve & Generate TTS';
    }
    return;
  }
  if(m.type!=='gator:narration-approval-result'){ return; }
  var a=m.approval||m;
  if(m.ok && a.approval_id && _pid){ startProgress(a.approval_id, _pid); }
  else { stopProgress(); setMergeStatus('',''); }
});
</script>
</body>
</html>
```

---

## Phase 4: TTS + Merge

When you receive `"Narration approved (N segments, approval appr_<n>_<hash>)..."` or `"✓ Approve..."`:

1. Call `demo_merge_narration` with `project_id` set to the id on the `PINNED PROJECT:` line. The tool loads the approved narration itself and verifies it; do not read narration files, take segments from the trigger message, or run TTS, ffmpeg or ffprobe yourself. If the trigger message contains `approval (appr_\d+_[0-9a-f]{8})`, pass the captured id as `approval_id`.
2. Leave `intro_mode` out unless the user asked to change the intro; the approved narration already carries `intro_mode`, `intro_duration_sec` and `intro_title`. "Hold" freezes the first frame and "Title card" shows the title. The tool adds the intro length to every narration start time, so never adjust timestamps yourself.
3. Handle the result:
   - `ok: true`: go to Phase 5 with `output.path`. Report `video_extended_by_sec` (when above 0, say the last frame was held that long), the `intro`, and `video_stream_sec` / `audio_stream_sec` exactly as returned.
   - `approval_superseded`: stop; a newer approval has its own turn.
   - `narration_not_approved`, `approval_corrupt`, `approval_stale_media`: tell the user the narration must be approved again.
   - `out_of_range`: quote `message`, `duration_sec` and `options`, and ask which to take.
   - `sync_mismatch`, `output_verification_failed`, `tts_failed`, `ffmpeg_failed`, `ffmpeg_timeout`: report `message` and any measured durations, and offer to retry once or to deliver the video without narration. No file was delivered.
   - Any other `error`: report `message`.
     Do not retry in a loop and do not describe a video that was not produced.

The tool writes its stage to `work/logs/merge_progress.json`; the narration editor polls it through `GET /api/demo-projects/<id>/progress` and shows "Generating speech N of M", "Merging audio and video", "Done", or the error text.

If Lemonade TTS is unavailable (preflight `lemonade.ok` is false), tell the user and offer to deliver the video without narration. The TTS endpoint is `/v1/audio/speech` (OpenAI-compatible) and the model is `kokoro-v1` — both confirmed by preflight. Do not probe other endpoints.

---

## Phase 5: Deliver

The merged video in `PROJECT_DIR / "final"` is the deliverable; the widget finds it from the active project without any path embedded in JS (eliminates all backslash-escaping bugs). `demo_merge_narration` has already moved any earlier file from `final/` into `previous/`.

Output this widget verbatim, replacing only `PROJECT_ID_PLACEHOLDER` with the project id (`PROJECT_DIR.name`, the id on the `PINNED PROJECT:` line of your context):

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
  .meta{font-size:.72rem;color:#6b8db5;margin-bottom:6px;word-break:break-all}
  .status{font-size:.7rem;color:#f87171;margin-bottom:8px;min-height:14px}
  .actions{display:flex;gap:8px;flex-wrap:wrap}
  .btn{padding:8px 14px;border-radius:7px;border:none;font-size:.78rem;font-weight:700;cursor:pointer}
  .btn-open{background:rgba(74,222,128,.15);border:1px solid rgba(74,222,128,.35);color:#4ade80}
  .btn-open:hover{background:rgba(74,222,128,.25)}
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
  <div class="meta" id="summary">Loading...</div>
  <div class="meta" id="duration"></div>
  <div class="status" id="open-status"></div>
  <div class="actions">
    <button class="btn btn-open" onclick="openFinal()">📁 Open final folder</button>
    <button class="btn btn-open" onclick="openProject()">Open project folder</button>
    <button class="btn btn-edit" onclick="editNarration()">✏️ Edit narration & regenerate</button>
    <button class="btn btn-clean" onclick="cleanup()">🗑 Delete intermediates</button>
  </div>
</div>
<script>
var _BASE=window._GATOR||'http://localhost:8003';
var _PROJECT_ID = 'PROJECT_ID_PLACEHOLDER';
var _pid=/^demo_\d/.test(_PROJECT_ID)?_PROJECT_ID:'';
var vp=document.getElementById('vp');

function formatBytes(n){
  n=Number(n)||0;
  if(n<1024){ return n+' B'; }
  if(n<1048576){ return Math.round(n/1024)+' KB'; }
  if(n<1073741824){ return Math.round(n/1048576)+' MB'; }
  return (n/1073741824).toFixed(1)+' GB';
}

function summaryLine(s){
  return 'Final: '+(s.final_rel||'none')+' · Sources: '+s.source_count+' · Working files: '+formatBytes(s.work_bytes);
}

function setOpenStatus(msg){
  document.getElementById('open-status').textContent=msg||'';
}

function requestOpen(target){
  if(!_pid){ return; }
  setOpenStatus('');
  parent.postMessage({type:'gator:demo-open-folder', project_id:_pid, target:target}, '*');
}

function openFinal(){
  requestOpen('final');
}

function openProject(){
  requestOpen('project');
}

function handleOpenResult(m){
  if(m.project_id!==_pid){ return; }
  setOpenStatus(m.ok===false ? (m.message||'Could not open the folder.') : '');
}

function applySummary(m){
  if(m.project_id!==_pid){ return; }
  if(!m.ok || !m.summary){
    document.getElementById('summary').textContent='Error loading: '+(m.error||'summary unavailable');
    return;
  }
  var s=m.summary;
  document.getElementById('summary').textContent=summaryLine(s);
  if(s.final_rel){
    vp.src=_BASE+'/api/demo-projects/'+_pid+'/file?rel='+encodeURIComponent(s.final_rel);
  } else {
    document.getElementById('duration').textContent='No final video was found in this project.';
  }
}

window.addEventListener('message', function(ev){
  var m=ev.data||{};
  if(m.type==='gator:demo-summary-result'){ applySummary(m); }
  else if(m.type==='gator:demo-open-folder-result'){ handleOpenResult(m); }
});

if(!_pid){
  document.getElementById('summary').textContent='Project not specified — cannot load the final video.';
} else {
  parent.postMessage({type:'gator:demo-summary', project_id:_pid}, '*');
}

vp.onloadedmetadata=function(){
  document.getElementById('duration').textContent='Duration: '+Math.round(vp.duration)+'s';
};
vp.onerror=function(){
  document.getElementById('duration').textContent='Could not load the final video.';
};

function editNarration(){
  parent.postMessage({type:'gator:send-message', pin_skill:'gator-demo-recorder', project_id:_PROJECT_ID,
    text:'NARRATION_REEDIT: Re-show the Phase 3 narration editor widget now.'},'*');
}
function cleanup(){
  parent.postMessage({type:'gator:send-message', pin_skill:'gator-demo-recorder', project_id:_PROJECT_ID,
    text:'Please delete the work/tts intermediates for the current project.'},'*');
}
</script>
</body>
</html>
```

After showing the widget, report the file path, size and `output.duration_sec` in plain text. State only facts that the `demo_merge_narration` result contains.

Always clean up: delete the `work/tts/` directory after delivery (user can trigger via Delete intermediates button).
