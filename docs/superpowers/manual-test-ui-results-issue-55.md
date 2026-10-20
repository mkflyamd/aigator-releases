# Issue #55 Demo Recorder: front-end (browser UI) test results

Branch `feat/issue-55-demo-recorder-overhaul`. Run on 2026-10-20 against an isolated AI Gator instance (127.0.0.1:8095, throwaway HOME, scripted OpenAI-wire fake model on 8096, headed Chromium driven by Playwright, fake credential `aigator-fake-api-key`). This complements `manual-test-results-issue-55.md` (API/tool level). The cases that were Blocked there for lack of a browser are covered here.

Screenshots were kept under `%TEMP%/issue55-ui/shots` during the run and deleted with the scratch directory.

## Summary

| Sub-project | Pass | Fail | Inconclusive / Blocked |
|---|---|---|---|
| SP1 (stalled-tool banner, repair) | 9 | 1 (SP1-03) | SP1-05 Blocked, SP1-11 Inconclusive |
| SP2 (skill pin chip) | 2 (02, 03) | 3 (01, 04, 05) | SP2-09 left to the fix fork |
| SP3 (demo projects folder row) | 3 (01, 05, 12b) | 1 (12a) | folder picker Blocked (Electron) |
| SP4 (prompt-bar Stop) | 0 | 0 | SP4-05/06 Blocked (need a real recording) |
| SP5 (agent/UI legs) | 0 | 0 | SP5-01/02/14 Blocked (need real agent tool behaviour) |
| SP6 (attach chip, upload) | 2 (01, 02) | 2 (04 partial, 14) | SP6-03 observed only (Import Mode unobservable) |
| SP7 (widgets) | 8 (01, 02, 04, 05, 06, 07 progress, 10, 14) | 2 (03, 13) | 08, 09, 12 Blocked; 11 left to the fix fork |

## Fails

### SP1-03 Rejected call row text
Observed: the tool row shows `describe_images (0 arguments) missing_required_params`. Expected: "Rejected describe_images: missing task".
Suspected cause: `web/app.py:626-627` (`_tool_toast` returns the raw error code) fed by the error text built at `agent_loop.py:708-715`.

### SP2-01 Pin chip label
Observed: the chip reads `Pinned: gator-demo-recorder`. Expected `Pinned: Demo Recorder`. Also there is no Demo Recorder entry in any skills list to start it from (Settings > Skills shows only marketplace bundles, `/api/skills` has no demo recorder id, `/demo` finds nothing), so the literal "start from the skills list" step cannot be done. The pin was created through the clip upload instead, which is the real entry path.
Suspected cause: built-in skill ids are excluded from the user skills list (`web/routes/health.py:463,495`, `web/shared.py:307`), so `SKILL_MAP` has no entry and `web/static/app.js:4228` falls back to the raw id.

### SP2-04 Pin is per tab (display)
Observed: with tab A pinned, opening a new tab B still shows the `Pinned:` chip. The data is correct: tab B has no stored pin and a message sent from B does not carry the Demo Recorder prompt. Only the chip is stale, so the user sees a pin that is not applied. Switching tabs through the tab bar re-renders correctly.
Suspected cause: `createTab` (`web/static/app.js:4425-4444`) does not call `_restoreChipsForTab` or `_renderPinChip`; only `switchTab` (`app.js:4514`) does.

### SP2-05 Pin restored after reload (display)
Observed: after a page reload the chip is gone, but `tab-pin-<id>` is still in localStorage and the next message from that tab does carry the Demo Recorder prompt. A hidden pin keeps steering the agent with no visible chip and no way to remove it (the chip's X is the only unpin control).
Suspected cause: `_initTabSystem` (`web/static/app.js:4331-4352`) never calls `_renderPinChip`; it is only called from `switchTab`, after a send (`app.js:13012`) and from `_setTabPin`.

### SP3-12a Change button without Electron
Observed: in a plain browser the Change button is visible and enabled with no title or hint, and clicking it does nothing. Expected: hidden, or disabled with a hint. Reset works (SP3-12b).
Suspected cause: `web/static/app.js:19017-19020` only skips the picker when `gatorShell.pickDemoFolder` is missing; `web/static/index.html:1009` always renders the button.

### SP6-04 Clip panel details (partial)
Observed: the panel shows name and duration (`big60.mp4  1:00`) with reorder, trim and remove controls. Resolution is not shown. Expected (checklist): duration and resolution.
Suspected cause: `web/static/demo-media.js:180-190` renders no resolution field.

### SP6-14 Cancel an upload midway
Observed: at about 70% of a throttled upload, clicking the chip X removes the chip, but the upload still completes: the project's clip count goes from 1 to 2 and `source/c2_clipA.mp4` exists. Expected: the upload is aborted and nothing is registered.
Suspected cause: removing the chip only calls `chip.remove()` (`web/static/app.js:1402-1407`) and `DemoMedia.upload` never exposes or aborts its XHR (`web/static/demo-media.js:71-95`).

### SP7-03 Pause after (s) feedback
Observed: 0, 2.5 and 10 are accepted. 11 and -1 stay in the input as typed and are only clamped to 10 and 0 when the approval is built (`pauseValue`). "abc" is not accepted by the number input (stays empty). No message or visual change appears for 11 or -1. Expected: out-of-range values rejected or clamped, with feedback.
Suspected cause: Phase 3 widget in `web/skills/gator-demo-recorder/SKILL.md:787` sets only `min`/`max`; no `:invalid` style or message, and clamping happens silently at send. Low severity: the value sent is always valid.

### SP7-13 Reload mid-merge
Observed: with `merge_progress.json` in state `running`, after a page reload the re-rendered narration widget shows an enabled Approve button and an empty `#merge-status`; updating the file does not change it. Expected: the progress resumes from the file.
Suspected cause: the widget only starts polling from `startProgress` (`SKILL.md:876`) after a `gator:narration-approval-result` in the same page session; at load it only requests the summary (`SKILL.md:802`).

## Passes worth noting
- SP1-01, 02, 04, 06, 07, 08, 09, 10, 12 pass. SP1-02 has only a Continue button (the checklist also lists Stop and Retry). SP1-09's banner says "after one repair attempt" although the provider died before the repair ran (minor wording).
- SP1-06 was verified at function level in the live page (a tab with no history cannot be made to stall).
- SP2-02: the pin chip stays across three unrelated messages and each request carries the Demo Recorder prompt. SP2-03: the X removes the pin, localStorage is cleared and the next request has no pin.
- SP3-01, SP3-05, SP3-12b: the folder row shows, and Reset restores the default root from the UI.
- SP6-01: chip shows live progress (7% then 18%). SP6-02: submit during an upload is blocked with "Wait for the upload to finish" and 0 model calls. SP6-03: the request carries the Demo Recorder prompt and the pinned project; Import Mode itself cannot be observed with a scripted model.
- SP7-01/02: scroll position is stable when the widget grows (forced +500 px growth: `#messages` scrollTop unchanged). The widget has no separate "replacement editor", only the inline textarea.
- SP7-04: the Pacing tips tooltip is shown and not clipped.
- SP7-05, 06, 07: the merge status line follows `merge_progress.json` (waiting, running with message, done), and after about 130 s with no job it shows "has not started" with the Approve button re-enabled as retry. The real merge and TTS were not run.
- SP7-10: the delivery widget has Open final folder and Open project folder and no Download button.
- SP7-14: no blocked-parent-access errors; summary and video load through the bridge. The only console message is the browser warning about `allow-scripts` plus `allow-same-origin`.

## Blocked / not verified
- SP1-05: the wrong-tab Continue button is not in the DOM when the other tab is active, so it cannot be clicked.
- SP1-11: waited 421 s; the UI showed "Connection issue - retrying (n/5)" and no banner. Inconclusive. SP1-05b was also inconclusive (0 banners after returning to tab A).
- SP3 folder picker, SP7-08/09 Explorer reveal: Electron only. In a plain browser the folder buttons give no visible feedback (empty `#open-status`).
- SP4-05/06 (prompt-bar Stop), SP5-01/02/14: need real screen recording or real agent tool behaviour, not available with a scripted model.
- SP7-12: no intro controls exist in any widget (the intro mode comes from the approval flags and agent arguments, `SKILL.md:914`), so the case cannot be run as written.
- Real recording, two monitors and fullscreen clicks stay Blocked.
- SP2-09, SP3-09, SP7-11 and the SP4-08 / SP6-16 checklist wording are being fixed separately and were not retested here.

## Environment notes
Expected console noise in the isolated instance, not failures: 401 `/api/teams/chats`, 500 `/api/calendar/events`, 404 `localhost:8001/status`. The scripted model answers by `[[S:name]]` markers, so agent behaviour (Import Mode, tool choices) is not exercised. No messages were sent to Email, Teams or Slack.

## Retest after fixes (8c6aba0, b50eea1, 97308c2)

Run on 2026-10-20 in a headed Microsoft Edge window (Playwright `channel="msedge"`, slow_mo 400 ms, 1400x900) against an isolated instance (127.0.0.1:8095, throwaway HOME, scripted OpenAI-wire fake model on 8096, fake credential `aigator-fake-api-key`). Real clip upload, real ffprobe/ffmpeg compose; the model only returns "ok" or the narration widget. All 33 checks below passed.

| Case | Commit | Result |
|---|---|---|
| SP2-04 new tab shows no stale Pinned chip | 8c6aba0 | Fixed. Tab A pinned via clip upload; new tab via "+" shows no chip; back to A the chip is back. `createTabWithId` was called directly from the page (no UI path reaches it without a stored task context) and also shows no chip. |
| SP2-05 chip redrawn after reload | 8c6aba0 | Fixed. After reload the chip is drawn from `tab-pin-<id>`; its X removes the chip and the localStorage key; the next message carries no `pinned_skill`; reload with no pin shows no chip. |
| SP6-14 cancel an upload midway | b50eea1 | Fixed. Throttled 30 MB upload cancelled at 45 %: chip gone, no error toast, request `net::ERR_ABORTED`, clip count unchanged (`c1`), no `.upload_*.part` and no `bigclip` file in `source/`, no traceback in the server log. A following unthrottled upload registered as `c2`; clicking X on the completed chip broke nothing (no page errors). |
| SP7-13 reload mid-merge | 97308c2 | Fixed. A `running` record with a fresh `updated_at` is resumed after reload (running message shown, button disabled "Approved"); a new running message is followed, then `done` ends with "Done — your demo video is ready.". A `done` record, a `failed` record and a STALE `running` record (300 s old) are not resumed (empty status, Approve enabled). |

Regression smoke, all passed: SP2-02 (pin survives two messages, each request carries `pinned_skill`), SP2-03 (X unpins, next request has none), SP6-01 (live progress, 29 distinct percentages), SP6-02 (Enter during upload is blocked with "Wait for the upload to finish" and 0 `/api/chat` calls), SP7-05/06/07 (real Approve → "Waiting for generation to start…" → running message → done, driven by `merge_progress.json` with the real approval id). Console showed only the known noise (401 `/api/teams/chats`, 500 `/api/calendar/events`, 404/refused `localhost:8001/status`) and no page errors.

Nothing is still open from this document: SP2-01, SP1-03, SP3-12a, SP6-04 and SP7-03 were fixed and re-verified in the section below.

## Retest of the five remaining fixes and the unverified items

Headed Microsoft Edge (Playwright `channel="msedge"`, slow_mo 400, viewport 1400x900) against an isolated instance: app on 8095, fake LLM on 8096, throwaway HOME under `%TEMP%`, credential `aigator-fake-api-key`. Branch `feat/issue-55-demo-recorder-overhaul`, HEAD 1b01540. 42 checks, 42 passed.

| Case | Commit | Result | Evidence |
|---|---|---|---|
| SP1-03 rejected tool call text | aa7e1b8 | Pass | A call to `describe_images` with no `task` shows `Rejected describe_images: missing task` in both the toast (`status-line status-line-error`) and the tool row (`tc-detail`). The SSE carries the same text in the tool_result summary and the toast. The raw error code is not shown. |
| SP2-01 pin chip label | 806b6db | Pass | After a real clip upload the chip reads `Pinned: Demo Recorder`. X removes the chip and clears `tab-pin-<id>`. A second upload re-pins with the same label. |
| SP3-12a Change hidden without a native picker | 59a5af4 | Pass | Plain browser: Change has class `hidden` and is not in layout while Reset is visible. Reset works (PUT 200, default root restored). With `window.gatorShell.pickDemoFolder` injected, Change is visible, sets the picked folder, and Reset restores the default. |
| SP6-04 clip resolution | 8409d2b | Pass | The clip row reads `demo1280.mp4`, `0:03`, `1280x720`. |
| SP7-03 pause after range | 1b01540 | Pass | 11 shows the orange hint `Limited to 0-10 s` and clamps to 10. -1 shows the hint and clamps to 0. 0, 2.5 and 10 show no hint and keep their value. Approve writes `pause_after` [10, 2.5] in the approval record. |
| SP2-09 stale approval after media change | c2d1db2 | Pass | Control: a merge with unchanged media is not refused (output `final/..._v1.mp4`). After appending a clip, and again after replacing an interval, merge is refused with `approval_stale_media` (SSE and DOM). Re-approval creates a second approval record. |
| SP3-09 agent continuing a deleted project | cf6890e | Pass | With the project folder deleted, `demo_media_manifest` for that project id returns `project_not_found` as the tool result and toast. The app keeps running with no page errors. |
| SP7-11 deleted project folder in the delivery widget | cf6890e | Pass | With the folder present the summary loads. With it deleted and after reload, the summary request is 404 (not 500), the widget shows `Error loading: HTTP 404`, and Open final folder shows `Could not load the project (HTTP 404).`. |
| Regression: SP2-04, SP2-05, SP2-02, SP6-01, SP6-02, SP6-14, SP7-13 | various | Pass | New tab shows no chip and tab A keeps it. Reload redraws the chip, X clears it and the next message carries no pin. Live upload progress, Enter blocked during upload, cancel leaves no chip, toast, `.part` file or traceback. Reload mid-merge resumes, follows the update and ends with Done. A stale `running` record is not resumed. |
| Console | | Pass | No unexpected console errors or page errors (only the known 401/500/404 noise). |

### New findings

1. `NameError: cannot access free variable '_detect_pending'` at `web/routes/chat.py:2249`. The import at line 1555 (`from continuation_classifier import classify as _classify, detect_pending as _detect_pending`) is in the `else:` branch of `if _skills_locked:`, so with a skill pinned the name is never bound. It is logged on every assistant text reply in a pinned tab (78 occurrences in this run). The UI still receives tokens and `[DONE]` and shows no error, but continuation detection never runs for pinned-skill replies. Introduced by 7961614. Fixed afterwards in 4e7b3b6 (the import now sits above the `if _skills_locked:` branch); covered by a source test, not re-run in a browser.
2. One transient `PermissionError: [WinError 5]` from `os.replace` of `project.json.<id>.tmp` in `atomic_write_json` (`web/demo_projects.py:40`) made `demo_append_clip` return `media_op_failed` in one of three runs; the project was left unchanged and a rerun on a fresh HOME passed. Likely a Windows file lock from a concurrent reader (progress polling or antivirus). Not reproduced.
