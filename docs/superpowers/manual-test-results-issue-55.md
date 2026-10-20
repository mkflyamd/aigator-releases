# Manual Test Results: Issue #55 Demo Recorder Overhaul (SP1-SP7)

Run date: 2026-10-20. Branch `feat/issue-55-demo-recorder-overhaul`, HEAD `a667d96`, Windows 11, real `ffmpeg`/`ffprobe`, real Lemonade TTS (:13305).
Checklist: `docs/superpowers/manual-test-issue-55.md` (not edited). Raw evidence: `%TEMP%/issue55-manual/`.

## How this run was done (read first)

- The live-UI run was not performed. An attempt to drive the AI Gator page in the running Electron shell (file-input upload plus CDP network throttling) was denied by the auto-mode classifier and was not retried or worked around.
- Cases were instead run against real code at tool level (`web/demo_media.py`, `narration_approval.py`, `demo_projects.py`, `skills/_always_on/tools.py`) and route level (FastAPI TestClient on `routes/demo_clips.py`, `routes/demo_projects.py`) with real ffmpeg and real Lemonade TTS, inside an isolated sandbox store (`%TEMP%/issue55-manual/sandbox_gator`).
- Status rules: Pass only if the full expectation was observed at the layer tested. If any part needed the UI, a model, a second monitor or a human and was not observed, the case is Blocked. Blocked is not a failure.
- The user's live app was not mutated: projects list, active project, settings, `~/.gator/demo_projects.json` and `narration_pending.json` match their pre-run backups byte for byte. No Email/Teams/Slack action was taken. No commit, push, or branch change.

## Summary

| Sub-project | Pass | Fail | Blocked | Not run | Total |
|---|---|---|---|---|---|
| SP1 Tool-call repair | 0 | 0 | 12 | 0 | 12 |
| SP2 Approval and skill pin | 6 | 1 | 5 | 0 | 12 |
| SP3 Project state and storage | 7 | 1 | 4 | 0 | 12 |
| SP4 Recorder capture | 1 | 1 | 10 | 0 | 12 |
| SP5 Media provenance and ops | 12 | 0 | 3 | 0 | 15 |
| SP6 Media intake and multi-clip | 12 | 1 | 5 | 0 | 18 |
| SP7 Narration editor and delivery | 1 | 1 | 12 | 0 | 14 |
| **Total** | **39** | **5** | **51** | **0** | **95** |

Fails: SP2-09 (real defect), SP3-09 and SP7-11 (same root cause, real defect), SP4-08 and SP6-16 (checklist expectation differs from designed behaviour).

## Fails

### SP2-09 Replace/append after approval is not refused (defect)
- Expected: merge refused with a stale-media error.
- Observed: after `narration_approval.approve`, `replace_interval` (2-5 s) and separately `append_clip` both succeeded, and `merge_narration(intro_mode='none')` was then ACCEPTED. It merged `work/edits/edit_001.mp4` (final 10.0 s after replace, 14.0 s after append). A sandbox check where `raw` itself was changed did return `approval_stale_media`, so the check works only for a raw change.
- Suspected cause: the approval fingerprint covers only the project's `raw` file (`web/narration_approval.py:66`, checked at `web/demo_media.py:641`). Replace/append write `work/edits/edit_NNN.mp4` and call `set_current` (`web/demo_media.py:263-265`), which sets `ext.media.current` and never changes `raw`. Merge picks the edited file through `current_rel` (`web/demo_media.py:256-260`). The fingerprint therefore never changes. Fixing means fingerprinting the current video, not `raw`.
- Note: the code names the error `approval_stale_media`, not `stale_media`.

### SP3-09 Deleted project folder gives HTTP 500 (defect)
- Expected: clear "project missing" message, no crash.
- Observed (route level, folder deleted in Explorer): `GET /api/demo-projects/{id}` 500, `/summary` 500, `/file` 500. An unknown id correctly gives 404. `list` drops the missing project cleanly. The manifest tool raised `FileNotFoundError` instead of returning an error object.
- Suspected cause: `get_project` raises `KeyError` for an unknown id but `FileNotFoundError` when the index entry exists and the folder is gone (`web/demo_projects.py:149-151`, `119-120`). `_get` catches only `KeyError` (`web/routes/demo_projects.py:42-46`), as does `project_for` (`web/demo_media.py:215-222`).

### SP7-11 Open final folder after deleting the project (same defect)
- Expected: clear error, no crash.
- Observed: the summary and file routes the delivery widget uses return 500 once the folder is gone. The `/api/open-file` route itself handles a missing path cleanly (`reason: not_found`, `web/routes/utils.py:299-303`), but the widget does not reach it because the summary call fails first. The widget click itself was not run in the UI.
- Suspected cause: same as SP3-09.

### SP4-08 `analyze_sequence` with more than 8 frames errors instead of capping (checklist mismatch)
- Expected: capped at 8 frames, no error.
- Observed: `{'ok': False, 'error': 'analyze_sequence accepts at most 8 frames, got 9. For a video file use task=\'analyze_video\' with video_path.'}`.
- Cause: designed behaviour at `web/skills/_always_on/tools.py:500-507` (`_MAX_SEQUENCE_FRAMES = 8` at line 428). Only `analyze_video` caps (line 445: 1801 s video gave 8 frames). The checklist expectation is wrong, or the design should change. Needs a decision.

### SP6-16 Soundtrack mix and original audio (checklist mismatch)
- Expected: MP3 mixed at 0.25 during compose, original audio remains audible.
- Observed: `work/timeline.mp4` has no audio stream (probe shows video only). The MP3 is registered and concatenated separately into `work/soundtrack.m4a` (74.0 s with all audio assets). It is mixed at 0.25 only at merge time (`web/skills/gator-demo-recorder/scripts/tts_pipeline.py:206`). Clip audio is stripped by design in normalization (`web/demo_compose.py:39`, `-an`).
- Cause: designed behaviour. The checklist wording does not match it. Mix level 0.25 was confirmed statically, not by listening to a mixed file.

## Other findings (not checklist Fails)

- F-1 Windows read/write race: reading `project.json` while the compose thread was writing raised `PermissionError` in my polling loop (`web/demo_projects.py:34-47` atomic write via `os.replace`; readers at `119-120` and `63/73` do not retry). This could cause an intermittent 500 on a status-polling route during compose. Seen once, not reproduced under the live app.
- SP3-12 suspected, not observed: the Change button is not hidden or disabled in browser-only mode (`web/static/app.js:19017-19020`, `web/static/index.html:1009`, picker bridge at `shell/main.js:4966` and `shell/preload.js:132`). Static reading only, so the case is Blocked.
- Checklist wording to fix: SP2 error names are `narration_not_approved`, `approval_superseded`, `approval_corrupt`, `approval_stale_media`. SP6-17: the lock is by stage (narration approved), not "while a compose or merge is running". SP5-07 wording is ambiguous (the error fires when the base recording already has audio). SP5-13 was forced by making the narration shorter in code, not by hand-shortening a clip.

## Per-case results

Layer: T = tool/code level, R = route level (TestClient), S = static code reading, UI = live UI (not run).

### SP1 Tool-call repair

| ID | Status | Evidence |
|---|---|---|
| SP1-01 | Blocked | Needs a model that omits required arguments plus the chat UI. Not run. |
| SP1-02 | Blocked | Same. Stalled banner is UI. |
| SP1-03 | Blocked | Same. |
| SP1-04 | Blocked | Same. |
| SP1-05 | Blocked | Same. Needs two tabs. |
| SP1-06 | Blocked | Same. |
| SP1-07 | Blocked | Needs a model producing a schema violation. |
| SP1-08 | Blocked | Needs a model producing repeated rejections. |
| SP1-09 | Blocked | Needs the provider stopped mid-turn. Not done on the user's live gateway. |
| SP1-10 | Blocked | Needs a skill-driven executor loop with a misbehaving model. |
| SP1-11 | Blocked | Needs a silent model and the idle watchdog. |
| SP1-12 | Blocked | Needs a live chat turn. |

### SP2 Approval and skill pin

| ID | Status | Evidence |
|---|---|---|
| SP2-01 | Blocked | Pin chip is UI. Not run. |
| SP2-02 | Blocked | Needs live chat turns. |
| SP2-03 | Blocked | UI. |
| SP2-04 | Blocked | UI, two tabs. |
| SP2-05 | Blocked | UI reload. |
| SP2-06 | Pass | T/R: `appr_1_34cc3034` created, `ext.approval` set with sha256 and media_fingerprint, `work/approvals/appr_1_34cc3034.json` present, legacy mirror written. Approve route returned 200 `appr_1_46e9f0ed`. Re-approving the same content reused the id, changed content gave `appr_2_5ae27153`. |
| SP2-07 | Pass | T: merge loads the approved record (2 segments, hash verified) and produced the final. Agent leg not run. |
| SP2-08 | Pass | T: merge with a superseded approval id returns `approval_superseded` (checklist says `superseded`). The widget-edit leg was not run in the UI. |
| SP2-09 | Fail | See Fails. Merge accepted after replace and after append. |
| SP2-10 | Pass | T: corrupted approval record gives `approval_corrupt`. |
| SP2-11 | Pass | T: merge before approval gives `narration_not_approved` (checklist says `missing`). |
| SP2-12 | Pass | T/R: approve route, then real Lemonade TTS, then real ffmpeg merge gave `final/routes_v1.mp4` and progress `done`. Sandbox project, not the live agent. |

### SP3 Project state and storage

| ID | Status | Evidence |
|---|---|---|
| SP3-01 | Blocked | `#demo-root-row` exists in `web/static/index.html:1002-1012`, but the rendered row was not verified in the live Settings page. |
| SP3-02 | Blocked | Electron picker dialog. Not opened. |
| SP3-03 | Pass | R: set root with spaces (`.../My Demos`) returned the path, config `demo_projects_root` updated, a new project was created under it. |
| SP3-04 | Blocked | Electron picker cancel. |
| SP3-05 | Pass | R: reset returned the default root and cleared the config key. |
| SP3-06 | Pass | T: layout `final previous source work/{frames,logs,normalized,tts} project.json`. |
| SP3-07 | Pass | T: index entry maps the project id to its path. |
| SP3-08 | Pass | T: legacy folder adopted, `project.json` created, `source/recording.mp4`, `seg_001/002.mp4` and logs kept, stage `recorded`. |
| SP3-09 | Fail | See Fails. HTTP 500 after folder deletion. |
| SP3-10 | Pass | R: relative path, `Z:/nonexistent_drive/x` and an access-denied path were each rejected with a clear message. The root was unchanged afterwards. |
| SP3-11 | Pass | R: after a root change 9 projects were still listed. A new project went to the new root. |
| SP3-12 | Blocked | Needs a browser-only run. Static reading suggests Change is not hidden (see findings). |

### SP4 Recorder capture

| ID | Status | Evidence |
|---|---|---|
| SP4-01 | Blocked | Needs a real screen recording with crop. |
| SP4-02 | Blocked | Needs a broken capture device. |
| SP4-03 | Blocked | Same. |
| SP4-04 | Blocked | Needs killing ffmpeg during a live recording. Not done on the user's processes. |
| SP4-05 | Blocked | Prompt-bar Stop is UI. |
| SP4-06 | Blocked | UI. |
| SP4-07 | Blocked | T: frame extraction worked (10 s video gave 2 frames at 5.0 s interval, 1801 s video capped at 8). The vision call failed with `CERTIFICATE_VERIFY_FAILED` in my standalone process (no corporate CA), so the description leg was not observed. |
| SP4-08 | Fail | See Fails. Error, not a cap. |
| SP4-09 | Pass | T: a missing file gave `Video not found: ...`. A `.txt` renamed to `.mp4` gave `Could not read the video duration with ffprobe ... Invalid data found`. |
| SP4-10 | Blocked | Needs two monitors. |
| SP4-11 | Blocked | Needs a real recording. |
| SP4-12 | Blocked | Needs a fullscreen app. |

### SP5 Media provenance and operations

| ID | Status | Evidence |
|---|---|---|
| SP5-01 | Blocked | T: `manifest` returned real files and durations (`source/recording.mp4` 10.0, `source/clipc.mp4` 10.0). The agent leg was not run. |
| SP5-02 | Blocked | T: `inspect_frames` for 3 s and 7 s wrote `work/frames/recording_3.00s.png` and `recording_7.00s.png`. UI display not observed. |
| SP5-03 | Pass | R: frame file route gave 200 `image/png` with PNG magic bytes. Path traversal gave 403, missing file 404. |
| SP5-04 | Pass | T: replace 2-5 s gave `work/edits/edit_001.mp4` (10.0 s). The ledger `work/logs/media_ops.jsonl` and `ext.media.ops` gained entries. |
| SP5-05 | Pass | T: replace 20-25 s on a 10 s video gave `out_of_range`. |
| SP5-06 | Pass | T: append of a 4 s clip gave a 14.0 s output, `timeline_shifted` False, ledger updated. |
| SP5-07 | Pass | T: append and replace on a base with audio gave `base_has_audio`. |
| SP5-08 | Pass | T: intro `none` gave offset 0.0 and first segment start 0.0. |
| SP5-09 | Pass | T: intro `hold` gave `final/sp5intro_v1.mp4`, 12.0 s, offset 2.0, first segment at 3.0. ffprobe video 12.000 s and audio 11.989 s. |
| SP5-10 | Pass | T: intro `card` gave `sp5intro_v2.mp4`, 12.0 s, title "AI Gator Demo", offset 2.0. ffprobe video 12.000 s and audio 11.989 s. Title frame captured in `card_1s.png`. |
| SP5-11 | Pass | T: second merge gave `final/..._v2.mp4`, and the older one was archived to `previous/20261020T181756Z_sp5intro_v1.mp4`. Nothing overwritten. |
| SP5-12 | Pass | T: real Lemonade TTS and real ffmpeg. Reported durations match ffprobe (12.0 s video, 11.989 s audio). Playback by ear was not done. |
| SP5-13 | Pass | T: forced by shortening audio in code (not by hand). Result: `sync_mismatch - Video is 10.0s but audio is 3.0s; the file was not delivered.` `final/` unchanged, progress state `failed`. |
| SP5-14 | Blocked | Needs a live LLM agent. |
| SP5-15 | Pass | R: `merge_progress.json` states observed through the route: none, running/tts (3 messages), running/merge, done. |

### SP6 Media intake and multi-clip

| ID | Status | Evidence |
|---|---|---|
| SP6-01 | Blocked | Attach chip is UI. The live upload attempt was denied by the classifier. |
| SP6-02 | Blocked | Submit gate (`data-media-uploading`, `app.js` ~12779) is UI. Not run. |
| SP6-03 | Blocked | R: upload gave 200 item `c1`. The agent entering Import Mode was not run. |
| SP6-04 | Blocked | R: the API reports `a_audio.mp4` 10.0 s, 1280x720. The panel rendering was not observed. |
| SP6-05 | Pass | R: reorder gave 200 and the order persisted on re-read. |
| SP6-06 | Pass | R: trim 2.0-6.0 on `c1` saved. The timeline total was 34.0 s, consistent with 4 + 10 + 10 + 10. |
| SP6-07 | Pass | R: delete route gave 200. The clip left the registry and its file left `source/`. |
| SP6-08 | Pass | R: `.txt` as `.mp4` gave 422 `unreadable`. Nothing registered. |
| SP6-09 | Pass | R: a 2 GiB + 1 MiB stream gave 413 `too_large` in 0.8 s. |
| SP6-10 | Pass | R: clips 1-8 accepted, 9th and 10th gave 409 `too_many` "At most 8 video clips per demo." |
| SP6-11 | Pass | R: audio 1-4 accepted, 5th and 6th gave 409 `too_many`. |
| SP6-12 | Pass | R: a 1801 s file gave 422 `too_long`. A file wider than 7680 px gave 422 `too_big_dimensions`. |
| SP6-13 | Pass | R: `clip é ü 日本 name.mp4` accepted as `c2`, stored under the project `source/`, probed 10.0 s. |
| SP6-14 | Blocked | R: a simulated client abort left `source/` and the registry unchanged. The chip removal is UI, not run. |
| SP6-15 | Pass | R: compose produced `work/timeline.mp4`, state ready, 34.0 s for 4+10+10+10, matching the panel order. |
| SP6-16 | Fail | See Fails. Timeline is silent. Soundtrack is mixed at merge. |
| SP6-17 | Pass | R: after narration approval, upload, reorder, trim and delete each gave 409 `project_locked` with "This demo's narration is already approved. Start a new demo to change clips." The lock is stage-based. A compose-only window was not tested. |
| SP6-18 | Pass | R: the 640x480 clip was normalized into the 16:9 canvas. Frame at 15 s shows letterboxing with no stretch (`sp6_18_frame15s.png`). |

### SP7 Narration editor and delivery

| ID | Status | Evidence |
|---|---|---|
| SP7-01 | Blocked | Scroll behaviour in the widget is UI. |
| SP7-02 | Blocked | UI. |
| SP7-03 | Blocked | S: `pause_after` 0-10 is documented at `SKILL.md:531` and the input is at line 785, but the clamping was not exercised in the UI. |
| SP7-04 | Blocked | S: tooltip markup exists at `SKILL.md:607`. Readability and clipping not observed. |
| SP7-05 | Blocked | R: progress states observed (see SP5-15). The `#merge-status` line was not observed in the UI. |
| SP7-06 | Blocked | S: "Generation has not started yet ..." retry text exists at `SKILL.md:860`. The 120 s wait was not run. |
| SP7-07 | Blocked | R: progress reached `done` and the summary returned `final/routes_v1.mp4`. The delivery widget appearing was not observed. |
| SP7-08 | Blocked | Explorer reveal not run. S: `/api/open-file` with `reveal` runs `explorer /select,` (`routes/utils.py:221-224`). |
| SP7-09 | Blocked | Explorer open not run. |
| SP7-10 | Pass | S: delivery template (`SKILL.md:967-968`) has only "Open final folder" and "Open project folder". No Download button anywhere in `SKILL.md`. |
| SP7-11 | Fail | See Fails. Summary and file routes give 500 once the folder is gone. |
| SP7-12 | Blocked | UI. Intro modes verified at tool level in SP5-08 to SP5-10. |
| SP7-13 | Blocked | UI reload mid-merge. |
| SP7-14 | Blocked | S: `gator:demo-summary`, `gator:demo-progress` and `gator:demo-open-folder` handlers exist in `app.js` ~18340-18375. Console not checked in a live widget. |

## What a human still needs to run

SP1 (all), SP2-01 to SP2-05, SP3-01/02/04/12, SP4 except 08/09, SP5-01/02/14, SP6-01 to SP6-04 and SP6-14 chip leg, SP7 except 10 and 11. Fix SP2-09 and the missing-folder 500 (SP3-09, SP7-11) before re-running the related cases.
