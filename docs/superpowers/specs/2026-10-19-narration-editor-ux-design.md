# Narration Editor and Delivery UX — Design (Sub-project 7)

Issue #55 items 8 and 9, remediation plan D1–D3, and "Delivery widget action: replace redundant Download with Open final folder".

Builds on `2026-10-19-demo-project-state-design.md` (SP3) and `2026-10-19-approval-transaction-design.md` (SP2). Does not redefine either; SP3's store, layout and routes and SP2's approval transaction are used as written.

Line numbers refer to the reference tree `.claude/worktrees/ref-merged` (commit `0e7581e` plus the staged security merge that carries `verify_csrf` and the CSRF inventory test). `SKILL.md` and `tts_pipeline.py` are identical in the main checkout; the main checkout's `app.js` is shorter, so locate `app.js` anchors by function name.

## Problem

### 1. The editor loses scroll position and caret (#8, D1)

- `web/static/app.js:17997` — `gatorWidgetResize.measure()` sets `iframe.style.height = '0'` before measuring, then regrows it. `measure` runs on iframe load (capture listener, `app.js:124`), at 0/50/300 ms, and on every `ResizeObserver` callback on the iframe body (`app.js:18038`). While the iframe is 0px tall the `#messages` scroller loses the widget's height, the browser clamps `#messages.scrollTop`, and regrowing does not restore it. Every body-size change in the editor (a wrapping line while typing, a textarea resize, an `<audio>` control appearing on preview) therefore moves the user's chat position. The same collapse resets the widget document's own scroll when it is taller than the 3000px cap (`app.js:18010`).
- Separate path — the replacement editor after "Edit narration & regenerate" arrives in a streamed turn. The per-event autoscroll (`app.js:13757`, guarded by `!_userScrolledUp`) follows the stream to the bottom. When the stream closes, `_userScrolledUp` is reset to `false` (`app.js:13352`, `:13769`) and the post-stream `_pinScrollToBottom(messages)` (`app.js:13947`) runs, so a replacement editor taller than the viewport is left scrolled past its top. `_userScrolledUp` is only updated while streaming (`app.js:4141-4146`) and is reset on send (`app.js:12899`).

### 2. The editor cannot express pauses (#9, D2)

- `web/skills/gator-demo-recorder/scripts/tts_pipeline.py:135` reads `seg.get("pause_after", 0)` and inserts FFmpeg silence (`:153-157`), but the Phase 3 editor template (`SKILL.md:489-749`) never displays or emits it: `approve()` (`SKILL.md:737-745`) builds `{start_at, text, voice, speed}` only.
- The pipeline compares `seg["pause_after"] > 0` with whatever the JSON held; a string or `null` from a widget raises `TypeError`, a huge value inserts minutes of silence.
- Inline `[pause:1.5s]` is unverified against the installed Lemonade/Kokoro; an unsupported server would speak it aloud.

### 3. Merge status is invisible (D3)

- SP2 turns Approve into a server-confirmed transaction and has the editor show pending / `Approved (N segments)` / error from its `gator:narration-approval-result` reply. After that, Phase 4 runs `tts_pipeline.py` through `subprocess.run(..., capture_output=True)` (`SKILL.md:786-797`); the widget never sees progress or a pipeline error, and a merge that never starts looks identical to one that is running.

### 4. The delivery widget duplicates the file instead of showing it (Delivery action)

- `SKILL.md:871` `⬇ Download` builds an anchor to `/api/recorder/serve-file` and downloads a copy of a file already on disk (`:897-902`).
- The widget shows a raw path and the duration only (`:890-893`); it has no project folder, source count or working-files size.
- Both widgets take their media from the `latest-output` singleton (`SKILL.md:722`, `:881`), which SP3 removes from the skill.
- `POST /api/open-file` (`web/routes/utils.py:265`, `_do_open_file` at `:215`, `OpenFileRequest` at `:197`) opens a file in its default app or a folder in the file manager; it has no "reveal this file in its folder" mode.

## Design

### Scroll and caret preservation (generic, in the wrapper)

In `gatorWidgetResize` (`app.js`), keep the collapse-and-measure (it is the one measurement that is right for every widget document) but make it side-effect free:

- `gatorWidgetScrollSnapshot(iframe)` records `scrollTop` for every ancestor of the iframe with `scrollTop > 0` (the chat scroller, a dock panel, any other scroller — each kept separately) and the iframe window's `scrollX/scrollY` when `scrollY > 0` (the widget's own inner scroll).
- `gatorWidgetScrollRestore(snapshot)` puts back only positions that were clamped *down* (`now < saved`). Growth and browser scroll anchoring are left alone.
- `measure()` becomes `snapshot → existing height logic → restore` in a `try/finally`, synchronously, so no scroll position survives the collapse.

Focus and caret are unaffected by the iframe height; nothing blurs the textarea, so once the scroll is stable the caret stays where the user left it.

### Reveal the replacement editor once

`gatorWidgetRevealOnce(iframe)` runs right after `gatorWidgetResize(el)` in the iframe `load` capture listener (`app.js:124`). It acts only when all of these hold: a stream is live for the active tab, the user is following it (`!_userScrolledUp`), and the widget wrapper is taller than the `#messages` viewport (pure decision: `gatorWidgetShouldReveal`). It then scrolls `#messages` so the widget's top is at the top of the viewport and sets two flags: `_userScrolledUp = true` (suppresses the per-event autoscroll for the rest of the stream) and a new module-level `_gatorWidgetRevealHold = true`. The hold is what survives stream close: the post-stream pin at `app.js:13947` becomes `!_userScrolledUp && !_gatorWidgetRevealHold`, because the close handlers reset `_userScrolledUp` first. `doSend` clears the hold next to its existing `_userScrolledUp = false` (`app.js:12899`). Reveal fires once (`following` is false afterwards), so it never fights the user's own scrolling. Short widgets and non-streaming loads (history, tab switch) are untouched.

### Pause after (editor template, `SKILL.md` Phase 3)

- Each segment row gets a labelled number input `Pause after (s)`: `min=0`, `max=10`, `step=0.1`, id `pa<i>`, initial value `pauseValue(s.pause_after)` so a re-edited narration keeps its pauses. Editing it shows the segment's `● edited` marker.
- `pauseValue(raw)` (in the template): non-numeric or negative → `0`; otherwise clamp to 10 and round to 0.1. `segOut(s, text, voice, speed, pauseRaw)` returns `{start_at, text, voice, speed, pause_after}`; `approve()` maps segments through it. That is SP7's only change to `approve()`; the transaction around it is SP2's.
- `pause_after` rides inside the segment objects SP2 already hashes, stores and hands to the pipeline (`load_approval.py --segments-out` → `tts_pipeline.py --narration`). A changed pause is a changed narration, so it produces a new approval ID.
- `tts_pipeline.py` gets `_pause_after(seg)`: float coercion; non-finite, negative or unparseable → `0.0`; cap `PAUSE_MAX = 10.0`; `build_synced_audio` uses it. Semantics are unchanged: `pause_after` is a minimum silence after the segment; a later `start_at` still wins because the pre-segment gap is computed from the position after the pause.
- Tooltip: a focusable `?` control in the voice row, shown on hover and focus, with the issue's text — **Pacing tips** — Use commas and periods for natural breaths; use `…` for a longer, trailing pause. For an exact silent gap after this section, set **Pause after**. Inline pause tokens are not mentioned anywhere.

### Open final folder / Open project folder / summary line (delivery template, Phase 5)

- Replace `⬇ Download` with `📁 Open final folder` and add `Open project folder`. Remove `download()` and `.btn-download`. Keep Edit narration & regenerate and Delete intermediates (their messages carry SP2's `pin_skill` and `project_id`).
- Extend `POST /api/open-file` with `reveal: bool = False`. `_do_open_file(path, is_dir, reveal)` for a file with `reveal`: Windows `explorer /select,<path>`, macOS `open -R <path>`, Linux `xdg-open <parent dir>`. No new route and no Electron IPC; `/api/open-file` is already in the CSRF baseline (`tests/csrf_route_baseline.txt:74`) and its method and path do not change, so the baseline is untouched.
- Open final folder: `{path: summary.final, reveal: true}`; when there is no final file, `{path: summary.final_dir, reveal: false}`. Open project folder: `{path: summary.path, reveal: false}`. An `ok:false` reply is shown in the widget as `message`.
- New read-only `GET /api/demo-projects/{id}/summary` returns `{project_id, path, final_dir, final, final_rel, source_count, work_bytes}`. `final_rel` is the project-relative POSIX path (`final/AI_Gator_Demo.mp4`) or `null`; `source_count = len(get_project()["segments"])`; `work_bytes` is the total size of files under `work/`. The widget renders `Final: final/AI_Gator_Demo.mp4 · Sources: 3 · Working files: 280 MB` and plays `GET /api/demo-projects/{id}/file?rel=<final_rel>`.
- Both widgets get the project through `PROJECT_ID_PLACEHOLDER` (the placeholder SP2 adds to the editor; SP7 adds it to the delivery widget). The `latest-output` fetches are removed from both templates, consistent with SP3's no-singleton test. The editor's raw-video preview uses `GET /api/demo-projects/{id}` (`path`, `raw`) and `GET /{id}/file?rel=`, with `projectRel(root, abs)` deriving `rel`.

### Merge progress and errors inside the editor (D3)

Contract with SP2 (SP7 consumes; SP2 owns the transaction and its UI):

- SP2's bridge replies to the editor iframe with `{type:'gator:narration-approval-result', ok:true, approval}` on success (`approval.approval_id`, `version`, `segment_count`, `reused`) and `{ok:false, error}` on failure. SP2's editor code shows pending, `Approved (N segments)` and the save error, and disables/re-enables `#btn-approve`. SP7 adds none of that.
- SP7 adds a second, independent `message` listener in the editor (accepts only `ev.source === parent` and `type === 'gator:narration-approval-result'`). On `ok:false` it stops any polling and clears the merge line. On `ok:true` it starts polling with the approval ID (`m.approval.approval_id`, or `m.approval_id` if the reply is flat), the project from SP2's `_PROJECT_ID`, and the time the reply arrived.

Widget side:

- A `#merge-status` line below the Approve button (separate from the preview `#status` and from SP2's save status).
- Every 1.5 s: `GET /api/demo-projects/<project_id>/progress`; `progressView(p, approvalId, waitedMs, sinceMs)` ignores records whose `approval_id` differs or whose `updated_at` is older than `sinceMs` (a finished run of the same approval, e.g. an idempotent re-approve, must not report this run as done), shows `Waiting for generation to start…`, then `p.message`, then `Done — your demo video is ready.` or `Generation failed: <error>`. After 120 s without a matching record it shows `Generation has not started yet. Check that the AI Gator agent is still working, or click Approve to retry.` Polling stops on done, failed or stall; on failed or stall the widget re-enables `#btn-approve` so retry is one click.
- Progress transport: `tts_pipeline.py` takes `--progress-file PATH` and `--approval-id ID` and atomically writes `{approval_id, state: running|done|failed, stage: tts|merge|done, step, total, message, error, updated_at (epoch seconds)}` before each segment's TTS, before the merge, at the end, and on any exception (then re-raises). The agent's Phase 4 call passes `--progress-file <PROJECT_DIR>/work/logs/merge_progress.json` and `--approval-id <approval_id>`, the `approval_id` printed by SP2's `load_approval.py`.
- New read-only `GET /api/demo-projects/{id}/progress` returns that file, or `{"state": "none"}` when absent or unreadable.

The helpers for `/summary` and `/progress` live in a new `web/demo_project_delivery.py`; `web/routes/demo_projects.py` only gains two `@router.get` wrappers.

### Depends on SP5: control must emit `<fields>`

SP5 defines the intro option and the fields its control emits; SP7 invents none. This section is a placeholder until SP5's spec fixes them. Location: a new `.intro-row` between `.voice-row` and `<audio id="global-audio">` in the Phase 3 template. Wiring: `approve()` reads the control's values and adds them to the `NARRATION_APPROVED` message in the form SP5 specifies; SP2's approval record carries them; generation is SP5's. When SP5's spec lands, add a plan task against it.

## Decisions

Every choice made in place of asking the user:

1. **Fix scroll in `gatorWidgetResize`, not per widget.** Every widget goes through it; the issue asks for a generic fix.
2. **Keep collapse-and-measure; snapshot and restore scroll around it.** It is the only measurement correct for every widget document; restoring removes the side effect without changing how heights are computed.
3. **Restore only positions clamped down.** Growth and scroll anchoring must not be fought.
4. **Snapshot every scrolled ancestor plus the widget's own scroll.** Satisfies "outer chat and any internally scrolling widget, separately" without naming containers.
5. **Reveal-once = scroll to the widget top, set `_userScrolledUp`, and set a new `_gatorWidgetRevealHold`.** The stream-close handlers reset `_userScrolledUp` before the post-stream pin runs, so the existing flag alone cannot stop the pull to the bottom; the hold is cleared on the next send.
6. **Reveal only widgets taller than the viewport during a live stream, while the user follows it.** Short widgets and history loads keep today's behaviour.
7. **Pause after is a number input, 0–10 s, step 0.1.** Matches "seconds, including 0"; the cap stops a typo from creating minutes of silence.
8. **The pipeline coerces and caps `pause_after` (`_pause_after`).** The pipeline must not trust widget JSON.
9. **Keep "minimum silence, later `start_at` wins".** It is the current behaviour; changing timeline math is out of scope.
10. **Do not advertise `[pause:…s]` and add no capability probe.** The issue forbids advertising it until verified; the explicit control is the reliable path.
11. **Play all does not insert pauses.** It previews voice only (it already ignores `start_at`).
12. **Editing a pause marks the segment `● edited`.** Reuses the existing indicator.
13. **`pause_after` travels inside the segments; no new field on SP2's transaction.** SP2 already hashes, stores and exports whole segment objects.
14. **Reveal via a `reveal` flag on `/api/open-file`.** The route already opens files and folders; no new route, no Electron IPC, no CSRF baseline change.
15. **Open project folder reuses `/api/open-file`** with the project path, for the same reason.
16. **Summary computed server-side (`/summary`).** Directory sizes cannot be computed in the sandboxed iframe.
17. **Sources = `len(segments)`; working files = bytes under `work/`.** Those are SP3's source clips and working folder.
18. **Widgets get the project from `PROJECT_ID_PLACEHOLDER`, replaced by the agent.** Same mechanism SP2 uses for the editor; widgets have no other way to learn the project.
19. **SP7 adds a listener beside SP2's, not inside it.** SP2 owns the approve transaction and its UI; two independent listeners cannot conflict in the template.
20. **Progress through a file and a polled GET route.** The agent runs the pipeline with captured output and has no channel to the widget; a file under `work/logs/` needs no change to the agent loop.
21. **Progress records carry `approval_id` and an epoch `updated_at`; the widget ignores mismatches and records older than the reply.** A leftover record from an earlier merge must not report success for this one, including an idempotent re-approve that reuses the same ID.
22. **`--progress-file` argument, not `--project-dir`.** Does not depend on how SP3 reshapes the pipeline's other arguments; the option is optional, so older callers still work.
23. **120 s "not started" message, retryable.** Without it a dropped agent turn leaves the widget waiting forever.
24. **No save timeout in SP7.** SP2's bridge always replies (`ok` true or false); a missing reply is SP2's to handle.
25. **Re-enable `#btn-approve` on merge failure or stall.** Retry stays one click; the id is SP2's.
26. **Intro control is a placeholder section.** SP5's spec owns its fields.
27. **The recorder widget's `(${mb})` size belongs to SP4.** It is in the recorder widget, not the delivery widget.
28. **Delivery widget messages carry `pin_skill` and `project_id`.** SP2's contract test requires them on every skill `gator:send-message`.
29. **Duration stays, on its own line below the summary line.** The issue fixes the summary line's exact content.
30. **The project for polling comes from SP2's `_PROJECT_ID`, and the approval ID is read from either reply shape.** SP2's spec shows a flat reply and its plan a nested `approval`; reading both removes the dependency on which one lands.

## Error handling

- Scroll snapshot/restore failures (cross-origin iframe window, detached nodes): wrapped in `try`; the resize proceeds as before.
- `pause_after` garbage (string, `null`, NaN, negative, huge): coerced by `pauseValue` in the widget and `_pause_after` in the pipeline.
- Save failure: SP2's UI (edits kept, Approve re-enabled, no agent turn). SP7 only clears its merge line.
- Merge failure: the pipeline writes `state: failed` with the exception text before exiting non-zero; the widget shows `Generation failed: <error>` and re-enables Approve.
- Progress never starts: 120 s message with retry. Progress file unreadable or mid-replace: the route returns `{"state":"none"}`; the widget keeps waiting.
- Unknown project ID on the new routes: 404, as SP3's routes.
- Open folder: `/api/open-file` already returns `{ok:false, reason, message}`; the widget shows `message`. Network failure: `Could not open the folder: <error>`.
- Delivery with no final file: summary shows `Final: none`, Open final folder opens `final/`.

## Testing

Automated (each confirmed defect):

- Scroll/caret loss: `tests/widget_resize_scroll.test.js` runs the real `gatorWidgetResize` from `app.js` against a fake iframe whose `height = '0'` clamps a fake scroller and a fake inner window; asserts both positions and the final height, that growth is not undone, and that an unscrolled widget is untouched. Fails on the current code.
- Pull to bottom: `tests/widget_reveal_once.test.js` covers `gatorWidgetShouldReveal` and `gatorWidgetRevealOnce` (reveals, sets both flags; does nothing for short widgets, non-streaming, or a user who scrolled up) and asserts on the `app.js` source that the post-stream pin checks `_gatorWidgetRevealHold` and `doSend` clears it.
- Pause not exposed: `tests/narration_editor_widget.test.js` extracts the editor template from `SKILL.md`; asserts `pauseValue`/`segOut` output, the control and tooltip text, no `[pause:`, `progressView` and `projectRel` behaviour, no `latest-output`.
- Pause unsanitised: `tests/test_tts_pipeline_pacing.py` covers `_pause_after` and `build_synced_audio` silence lengths (minimum silence; later `start_at` wins).
- Merge status: `tests/test_tts_pipeline_progress.py` covers `write_progress` and `main()` (running, done, failed-then-reraise); `tests/demo_project_state/test_delivery.py` covers `/summary` and `/progress`.
- Download duplicate / no reveal: `tests/test_open_file_reveal.py` covers `_do_open_file` per platform and the route's `reveal` pass-through; `tests/demo_ready_widget.test.js` asserts no Download control, both open buttons, `formatBytes`, `summaryLine` (`Final: final/AI_Gator_Demo.mp4 · Sources: 3 · Working files: 280 MB`) and the `/api/open-file` request bodies.
- `tests/test_csrf_route_inventory.py` stays green with `tests/csrf_route_baseline.txt` unchanged.

Manual (real scroll and caret cannot be asserted without a browser): the plan's final task lists exact steps.

## Interfaces with other sub-projects

### Requested additions to SP3 interfaces

- `get_project()` is unchanged. SP7 appends two read-only routes (`GET /{id}/summary`, `GET /{id}/progress`) to `web/routes/demo_projects.py` and puts their helpers in the new `web/demo_project_delivery.py`.
- Reserve `work/logs/merge_progress.json` (inside SP3's `work/logs/`) as the pipeline's progress record.

### Requested from SP2

- Keep the approval ID in the `gator:narration-approval-result` reply (`approval.approval_id` or `approval_id`), and keep `id="btn-approve"` and the editor's `_PROJECT_ID` variable.
- Phase 4's `tts_pipeline.py` call gets `--progress-file` and `--approval-id` (the `approval_id` in `load_approval.py`'s verdict) next to `--work-dir`; SP7's plan Task 8 adds them.
- Keep the `return {start_at:s.start_at||s.start||0, text:..., voice:voice, speed:speed};` line inside `approve()`'s `data.map`, so `segOut` replaces it (SP7 plan Task 7).
- Keep `type:'gator:send-message', pin_skill:'gator-demo-recorder', project_id:_PROJECT_ID,` in that order (their contract test reads 260 characters after `type:'gator:send-message'`); the delivery template follows it.
