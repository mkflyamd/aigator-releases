# Recorder Capture Fixes — Design (SP4, issue #55 items 1–5)

Sub-project 4 of the Demo Recorder overhaul. Scope is issue mkflyamd/aigator-releases#55 items 1–5: the recorder keeps the selected screen/crop across pause/resume, failures surface instead of vanishing, stop never hands back a bogus file, the prompt-bar Stop click is made robust, and post-recording analysis no longer depends on an LLM-built shell runner.

Evidence line numbers refer to `web/routes/recorder.py` unless noted, in the tree with PRs #79/#82/#83/#84 merged.

## Problem

### 1. Windows pause/resume loses the selected screen and crop

- `_last_start_req: StartRequest = StartRequest()` is declared at line 837 and **never assigned**. `recorder_start` (679) validates and clamps `req` (734–753) and starts segment 0 from it (764), but never stores it.
- `recorder_resume` on Windows calls `_start_segment(ffmpeg, _last_start_req, screens, seg_index)` (~853), so segment 1 is built by `_build_ffmpeg_cmd` (582) from screen 0 / no crop: no `-offset_x/-offset_y`, `-video_size` of Display 1.
- Resume then restores the border from `_last_start_req` (876–881) on both Windows and POSIX, so on POSIX the video is correct but the border is drawn on the wrong screen.

### 2. Reopened widget: Resume appears inert

- `doPause`/`doResume` in the widget template (`web/skills/gator-demo-recorder/SKILL.md`, first `html:widget` block) are `apiFetch('resume', null, function(err, data) { _busy = false; });` — the result is dropped.
- When Windows resume fails, `recorder_resume` has already appended the new segment to `_segments` (~857) and, on `poll()` not None, returns 500 `"ffmpeg failed to restart"` (860) without cleaning up. State stays paused, the dead segment stays in `_segments`, and the user sees nothing.
- The direct trigger of the restart failure cannot be proven statically (needs the session's `ffmpeg_log.txt`). The two defects above are the provable root causes: a stale request and no feedback or clean state on failure.

### 3. Stop falls back to the last segment; `()` in the completion message

- `recorder_stop` (906–962): `_stitch_segments` failure is swallowed and `final = _segments[-1]`. After a failed resume that is a 0-byte `seg_01.mp4`, which is reported as the recording and written to `latest_output.json`.
- `_stitch_segments` (888–903) runs concat with `check=True, capture_output=True` and discards stderr; the concat list is not removed on failure.
- The widget `doStop` builds `' ('+mb+')'` unconditionally, so an empty size yields `File: ...\seg_01.mp4 (). Please analyze…`.
- Incompatible segments (the "incompatible display/crop" in the issue) come from item 1; once segments are uniform, `-c copy` concat is valid.

### 4. Prompt-bar Stop: Escape works, mouse click fails in fullscreen

- `#send-btn` stop is wired per turn by `sendBtn.addEventListener('click', _onStop)` (`web/static/app.js:12875`); Escape by a `document` keydown listener (12881). Both call the same `_onStop` (12848).
- Static review found no cause: `.is-streaming` forces `pointer-events:auto !important`; fullscreen is `requestFullscreen()` + body class `tab-fullscreen` (4881–4902). The failure is therefore event delivery or hit-testing at runtime (a target-specific `click` that never lands on the button, or the one-time listener being detached by `_detachStop` at 13293/13785/13970 / `_resetBtn`).

### 5. Post-recording analysis: Windows/Bash/path mismatch, 42 frames

- `SKILL.md` Phase 2 (lines ~416–449) tells the model to run a Python snippet via an LLM-chosen runner (the failures: Bash without ffprobe, quoted Windows exe path rejected, `/tmp/code_runner_out/frames/...` unreachable by the image tool).
- `_tool_describe_images` (`web/skills/_always_on/tools.py:418`) checks that **all** `image_paths` exist before any cap, so 42 unreachable paths report "42 of 42 do not exist"; `_analyze_frame_sequence` (545) silently truncates to `MAX_FRAMES = 8` afterwards. The 8-frame rule is advisory prose only.

## Design

### Backend (`web/routes/recorder.py`)

1. **Test seam.** `_IS_WINDOWS = os.name == "nt"` module constant; every `os.name` check uses it (no behaviour change).
2. **Item 1.** Move the `_last_start_req: StartRequest = StartRequest()` declaration from line 837 to directly after `class StartRequest` (it cannot join the state globals at line ~95 because the class is defined later at 572). `recorder_start` declares `global _last_start_req` and assigns the post-validation `req` (clamped screen/crop) immediately before `_start_segment(..., 0)`. Resume, border restore, and the first segment now share one request.
3. **Item 2 (backend).** Windows resume starts the new segment, waits, and only if the process survived sets `_ffmpeg_proc`/`_recording_path` and appends to `_segments`. On failure: `_ffmpeg_proc = None`, `_segments` unchanged, still paused (so retry works and reuses the same `seg_NN`), response 500 `{"ok": False, "error": "ffmpeg failed to restart — check ffmpeg_log.txt", "log": <path>}` (same shape as the existing start failure).
4. **Item 3 (backend).**
   - `_stitch_segments` captures concat stderr, raises `RuntimeError` with the last 400 chars (or the exit code) on non-zero exit, and always removes `concat_list.txt` (`try/finally`).
   - `recorder_stop` stitches only segments that exist with size > 0. If none exist, or stitching fails, it resets pause state and the border, does **not** write `latest_output.json`, and returns 500 `{"ok": False, "status": "idle", "error": ..., "segments": [paths], "session_dir": ...}`. The success payload is unchanged.

### Widget template (`SKILL.md`, first `html:widget` block)

5. **Items 2 and 3.** Add `_actionError` and `actionFailed(err, data, label)`: returns false when `!err && data && data.ok`; otherwise stores `label + ': ' + (data.error || err.message || 'request failed')` (plus `(session_dir)` when present), paints it as `status error`, returns true. `doRecord/doPause/doResume/doStop` clear `_actionError` at start and call `actionFailed` on the response. `render()` re-applies `_actionError` after setting each branch's status, so the 1 s poll cannot overwrite it; it clears on the next user action. `doStop` builds the completion message as `'Recording complete. File: ' + path + (mb ? ' (' + mb + ')' : '') + '. Please analyze it and draft a narration script.'`, shows `✓ Saved` plus the size only when known, and on failure sends nothing to chat.
6. SKILL.md path-extraction wording (Phase 2 step 1 and the CRITICAL RULES "File path" bullet): the path ends at `" ("` or, when no size is shown, at `". Please"`.
7. Saved widgets already in the DB are stale copies of the template; they are not migrated.

### Prompt-bar Stop (`web/static/app.js`)

8. **Diagnose first** (plan Task 5): on a runtime reproduction in fullscreen, log `elementFromPoint` at the button centre and `pointerdown/mousedown/mouseup/click` in the capture phase; record findings in the PR.
9. **Defensive fix** (independent of the diagnosis; labelled as such): replace the per-turn `sendBtn.addEventListener('click', _onStop)` with a module-level `_activeStops: Set<() => void>` and **one** persistent `document` capture-phase `click` listener. It fires when `_shouldStopFromClick(e, btn, rect, streaming)` is true: `streaming && e.button === 0 && (btn.contains(e.target) || point inside rect)`. It calls `e.preventDefault()` then every registered `_onStop` (each still self-filters by `_activeTabId !== requestTabId`, preserving multi-tab semantics). `click` is dispatched to the common ancestor of mousedown/mouseup, so this survives the button moving between press and release and survives overlays. `_detachStop` deletes this turn's `_onStop` from the set; `_onStop` gets an `if (_userStopped) return;` re-entry guard. Escape handling is unchanged.

### Frame analysis (`web/skills/_always_on/tools.py`, `gator-demo-recorder/SKILL.md`)

10. **Cap enforced in the tool.** `describe_images(task='analyze_sequence')` rejects more than 8 `image_paths` before the existence check: `"analyze_sequence accepts at most 8 frames, got N. For a video file use task='analyze_video' with video_path."`.
11. **`task='analyze_video'` + `video_path` parameter.** Runs server-side in the backend process, so no runner, shell, or temp-path mismatch:
    - ffmpeg/ffprobe from `routes.recorder._FFMPEG/_FFPROBE` (the same values `/api/recorder/status` returns), falling back to `_find_ffmpeg()/_find_ffprobe()`.
    - ffprobe duration; `n = min(8, max(1, ceil(duration / 5)))`, `interval = duration / n`.
    - Frame `i` is `ffmpeg -y -ss <i*interval> -i <video> -frames:v 1 <tmp>/frame_NNNN.png`, argv lists only (no shell), into `tempfile.mkdtemp(prefix="gator_frames_")`, removed in `finally`.
    - Calls `_analyze_frame_sequence(paths, 1 / interval)`; its result is returned verbatim.
    - `video_path` is subject to the same `is_secrets_path` guard as `image_paths`.
12. **SKILL.md Phase 2** collapses to: extract path → `describe_images(task='analyze_video', video_path=<path>)`. The python snippet, the "never pass more than 8 frames" runner instructions, and the `frames/` cleanup are removed (the tool owns the 8-frame cap and its temp dir).

## Decisions

1. **`_IS_WINDOWS` constant** — the `os.name` checks cannot be monkeypatched; a constant is the smallest seam that lets CI exercise the Windows branch on Linux without ffmpeg.
2. **Failed stop returns an error, no silent last-segment fallback, no re-encode fallback** — a 0-byte or partial file reported as "the recording" is the defect; after item 1 the segments are uniform, so `-c copy` is correct and a failure means real corruption the user must see.
3. **Failed resume stays paused and does not record the dead segment** — retry then works and `_segments` never contains a file that was never captured.
4. **Saved widgets in the DB are not migrated** — only the template changes; users get the fix on the next generated recorder widget, and migrating stored HTML is out of scope for #55.
5. **Item 4 is a defensive fix behind a diagnostic step** — static review proved nothing; a delegated capture-phase click handler is correct under every cause previously suspected, and a cause outside the page (an Electron shell-level issue) becomes a separate follow-up issue instead of widening this PR.
6. **`_activeStops` is a Set, not a single slot** — the old per-turn listeners coexisted across tabs, each filtering by tab; a single slot would let the newest turn shadow another tab's turn.
7. **Item 5 fixed in the tool (`analyze_video`), not a skill script or new route** — the root cause is an LLM-composed runner; a tool removes the runner. A new POST route would need CSRF and the same ffmpeg access the backend already has.
8. **Reject (not truncate) more than 8 frames** — silent truncation hid the 42-frame failure and returns a timeline for frames the caller did not choose; a clear error teaches the correct call.
9. **Frame count `min(8, ceil(duration/5))`, offsets `i*interval`** — preserves the existing "evenly spaced, ≥5 s apart, ≤8" behaviour from SKILL.md while never seeking to the end of the file.
10. **Tests keep real `asyncio.sleep`** (0.4–0.6 s per start/resume) — avoids patching global `asyncio.sleep`; the suite adds a few seconds.
11. **No new routes** — nothing is added to `tests/csrf_route_baseline.txt`; the existing recorder POST routes stay grandfathered.
12. **`_last_screen_index` / `_last_crop` hotkey memory untouched** — separate concern (global-hotkey defaults), not part of #55 items 1–5.
13. **Item 2's direct trigger is not claimed fixed** — the plan fixes the provable causes (stale request, no feedback, dirty failure state) and adds a manual log-reading step to confirm on a real reopened HUD.

## Error handling

- Resume restart failure: 500 with `error` and `log` path; state stays paused; widget shows the error until the next action.
- Stop: no usable segment or concat failure → 500 with `error`, `segments`, `session_dir`; border and pause state reset; `latest_output.json` untouched; widget shows `Stop error: … (<session_dir>)` and sends nothing to chat.
- `analyze_video`: missing `video_path`, non-existent file, missing ffmpeg/ffprobe (message includes the `winget`/`brew` install hint), unreadable duration, or a failed frame extraction each return `{"ok": False, "error": ...}`; the temp frame directory is always removed.
- `analyze_sequence` with >8 paths returns an error before touching the filesystem.

## Testing

Python (`tests/test_recorder_capture.py`, no ffmpeg: `subprocess.Popen`/`run` are faked and argv asserted; `_IS_WINDOWS` and screen enumeration are patched):

- **Item 1:** resumed segment argv carries Display 2 offsets and crop (`-offset_x 2020 -offset_y 50 -video_size 640x480`, `seg_01.mp4`); border restored on `Display 2` with the crop on both Windows and POSIX; the stored request is the clamped one (`2460x1390`).
- **Item 2:** failed restart → 500 with `log`, `_segments` unchanged, still paused; retry succeeds and reuses `seg_01.mp4`.
- **Item 3:** two segments produce the exact concat argv and remove `concat_list.txt`; a concat failure returns 500 with stderr in `error`, the segment paths, no `latest_output.json` write, and state reset; zero-byte capture returns "No video was captured"; the single-segment success path needs no ffmpeg run.

JS (`tests/recorder_widget.test.js`, node `assert` + `vm` over the template extracted from SKILL.md): failed resume/pause show the error and `render()` keeps it until the next action; failed stop shows the error with `session_dir` and posts nothing; success message has `(3.0MB)` with a size and no `()` without.

JS (`tests/stop_button_click.test.js`): `_shouldStopFromClick` truth table (target is button, target is child, point inside rect with different target, outside rect, not streaming, non-primary button); the click path registers via `_activeStops` and no longer via `sendBtn.addEventListener('click', _onStop)`.

Python (`tests/test_describe_images_video.py`; `subprocess.run` and `_analyze_frame_sequence` faked): 42 explicit paths are rejected with the 8-frame message (not "do not exist"); a 210 s video yields exactly 8 frames at `i*26.25` s with argv lists and no `shell`; a 12 s video yields 3 frames; frame temp dir removed; missing ffmpeg, missing video, and secrets path return clear errors.

Manual (recorded in the PR): item 2 log read on a reopened HUD; item 4 fullscreen event trace before and after the fix.
