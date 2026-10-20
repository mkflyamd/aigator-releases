# Manual Test Checklist: Issue #55 Demo Recorder Overhaul (SP1-SP7)

Branch: `feat/issue-55-demo-recorder-overhaul`. SP8 (widget Edit with Gator) is excluded.

Mark each case Pass or Fail. Record the build, OS and any log excerpt next to every Fail.

## Global prerequisites

- Windows 11 machine with the Electron shell (`npm start` in `shell/`), a configured gateway in `config.json` and a working LLM.
- Real `ffmpeg` and `ffprobe` on PATH. Check with `ffmpeg -version`. Automated tests only exercise ffmpeg on CI; this checklist covers the real Windows run.
- Lemonade TTS running for the narration cases (SP2, SP5, SP7).
- Two monitors for SP4-10 and SP4-11. One monitor is enough for everything else.
- Any short screen-recordable app to demo, for example Notepad.
- Test media for SP6: a 10 s MP4 (H.264 with audio), a 10 s MP4 without audio, a second 10 s clip at a different resolution, a 15 s MP3, a WAV, a `.txt` renamed to `.mp4`, and a file larger than 2 GiB (a sparse or dummy file is fine).
- Use the fake credential `aigator-fake-api-key` wherever a key is typed.
- Demo projects live under the demo projects folder (default `~/.gator/demo_projects` or the configured root). Inspect them in Explorer when a case says "check the folder".

Project layout to expect: `final/`, `previous/`, `source/`, `work/{normalized,frames,tts,logs}`, `project.json`.

---

## SP1: Tool-call repair (`web/tool_repair.py`, `agent_loop.py`, Continue banner)

Setup: start the app, open a new chat tab, choose a model that sometimes omits required arguments (or use a small on-prem model). Use a prompt that forces a tool with a required argument, for example "Run a Python snippet that prints 2+2" with a model that tends to call `run_python` with no `code`.

| ID | Steps | Expected | Result |
|---|---|---|---|
| SP1-01 | Provoke a rejected tool call (omit a required argument). Watch the chat. | The tool does not run. The model gets one repair turn, calls again with the argument and the task completes. No banner. | [ ] Pass [ ] Fail |
| SP1-02 | Provoke a rejection that the model repeats on the repair turn. | One `stalled` banner appears that names the tool and fields (for example "run_python ... code"). It has Continue and Stop or Retry buttons. | [ ] Pass [ ] Fail |
| SP1-03 | In SP1-02, expand the tool result row. | The row reads "Rejected <tool>: missing <field>" and not just `Error: missing_required_params`. | [ ] Pass [ ] Fail |
| SP1-04 | Click Continue on the SP1-02 banner. | The original request is resubmitted in the same tab with a note naming the failed tool and fields. It is not the bare text "Continue where you left off." | [ ] Pass [ ] Fail |
| SP1-05 | Start a stall in tab A, switch to tab B, then click Continue in tab A's banner (switch back first if the banner is only visible there). Repeat by clicking Continue from tab B if the banner is reachable. | A note-carrying Continue clicked from a different tab than the one that streamed does nothing. Nothing is submitted into the wrong conversation. | [ ] Pass [ ] Fail |
| SP1-06 | Trigger a stall in a fresh tab with no prior user message (for example reload and restore a tab with no history), then click Continue. | Falls back to "Continue where you left off." with no error. | [ ] Pass [ ] Fail |
| SP1-07 | Trigger a schema violation (wrong argument type, for example a string where a number is required). | Counts as a rejected call: one repair turn, then a stall naming the field. | [ ] Pass [ ] Fail |
| SP1-08 | After a successful repair, trigger a second, separate rejection later in the same turn. | The repair budget resets. The second rejection also gets its own repair turn. | [ ] Pass [ ] Fail |
| SP1-09 | Stop the LLM provider (or point the gateway at a dead port) right after a rejected call. | The stop ends with the structured stalled banner naming the failed tool, not plain "LLM error" text with no Continue. | [ ] Pass [ ] Fail |
| SP1-10 | Run a multi-step task that uses the executor loop (a skill-driven task) and provoke a repeated rejection. | Same stalled banner with field names and Continue. | [ ] Pass [ ] Fail |
| SP1-11 | Make the model go silent after a rejection (slow on-prem model). Wait for the idle watchdog. | The watchdog banner quotes the rejection with the field names, for example "Rejected run_python: missing code". | [ ] Pass [ ] Fail |
| SP1-12 | Regression: run a normal successful tool call. | No repair turn, no banner, no extra LLM call. | [ ] Pass [ ] Fail |

Negative checks: Retry and Stop buttons still work on every stalled banner (SP1-02, SP1-09).

---

## SP2: Approval transaction and per-tab skill pin

Setup: Demo Recorder skill available. A project with an analysed recording and the narration editor widget visible. TTS available.

| ID | Steps | Expected | Result |
|---|---|---|---|
| SP2-01 | Start the Demo Recorder from the skills list. | The prompt area shows a chip "Pinned: Demo Recorder" with an X. | [ ] Pass [ ] Fail |
| SP2-02 | Send three unrelated messages (for example "what next", "ok", "go on") in the pinned tab. | The skill stays selected on every turn. | [ ] Pass [ ] Fail |
| SP2-03 | Click the X on the chip. | The chip disappears. The next message uses normal skill routing. | [ ] Pass [ ] Fail |
| SP2-04 | Pin in tab A. Open tab B. | Tab B has no chip. Tab A keeps its chip when you switch back. | [ ] Pass [ ] Fail |
| SP2-05 | Pin in a tab, reload the app. | The chip is restored on the same tab. | [ ] Pass [ ] Fail |
| SP2-06 | Edit narration and click Approve in the editor. | An approval id is created (`appr_<version>_<hash>`). Check `project.json` or the approvals file in the project. | [ ] Pass [ ] Fail |
| SP2-07 | Ask for "merge narration" after approving. | Merge uses the approved narration exactly. | [ ] Pass [ ] Fail |
| SP2-08 | Approve, then edit the narration again in the widget without re-approving. Ask to merge. | The merge is refused with code `superseded`. The agent tells you to re-approve. | [ ] Pass [ ] Fail |
| SP2-09 | Approve, then replace an interval or append a clip. Ask to merge. | Refused with `stale_media`. | [ ] Pass [ ] Fail |
| SP2-10 | Approve, then corrupt the approval file by hand (invalid JSON). Ask to merge. | Refused with `corrupt`. | [ ] Pass [ ] Fail |
| SP2-11 | Ask to merge before any approval exists. | Refused with `missing`. | [ ] Pass [ ] Fail |
| SP2-12 | Live run: Approve, then narration (Lemonade TTS), then merge, end to end. | A narrated MP4 is created in `final/`. See also SP5-12 and SP7-07. | [ ] Pass [ ] Fail |

---

## SP3: Demo project state and storage (`web/demo_projects.py`)

Setup: note the current demo projects folder in Settings, General. Close the app before cases that change it only if stated.

| ID | Steps | Expected | Result |
|---|---|---|---|
| SP3-01 | Open Settings, General. | A "Demo projects folder" row shows the current path, with Change and Reset buttons. | [ ] Pass [ ] Fail |
| SP3-02 | Click Change. | The Electron folder picker opens with the title "Save project to...". The New Folder button works. | [ ] Pass [ ] Fail |
| SP3-03 | Pick a new empty folder (path with spaces, for example `D:\My Demos`). | The path updates in the row. New recordings are created under it. | [ ] Pass [ ] Fail |
| SP3-04 | Click Change, then cancel the dialog. | Nothing changes. No error toast. | [ ] Pass [ ] Fail |
| SP3-05 | Click Reset. | Reverts to the default folder. The row shows the default path. | [ ] Pass [ ] Fail |
| SP3-06 | Record a short demo. Inspect the project folder. | Contains `final/ previous/ source/ work/normalized work/frames work/tts work/logs` and `project.json`. | [ ] Pass [ ] Fail |
| SP3-07 | Inspect `~/.gator/demo_projects.json`. | Lists the project with its path. | [ ] Pass [ ] Fail |
| SP3-08 | Put a legacy demo folder (old layout from before this branch) in the demo root and restart. | It is adopted into the index. Files are not lost. Check `project.json` is created. | [ ] Pass [ ] Fail |
| SP3-09 | Delete a project folder in Explorer, then ask the agent to continue that project. | A clear "project missing" style message. No crash. | [ ] Pass [ ] Fail |
| SP3-10 | Point the root at a read-only or non-existent location (type it into config if the picker will not allow it). | A clear error. The old root is kept. | [ ] Pass [ ] Fail |
| SP3-11 | Change the root with existing projects, then reload. | Old projects remain reachable via the index. New ones go to the new root. | [ ] Pass [ ] Fail |
| SP3-12 | Browser-only run (no Electron, the web UI opened in Chrome). | The Change button degrades gracefully (hidden or disabled with a hint). Reset still works. | [ ] Pass [ ] Fail |

---

## SP4: Recorder capture fixes

Setup: the recorder widget open, real ffmpeg, Windows desktop.

| ID | Steps | Expected | Result |
|---|---|---|---|
| SP4-01 | Start a recording on one screen, with a crop region set. Pause. Resume. | Resume keeps the same screen and the same crop. The recording continues in the same area. | [ ] Pass [ ] Fail |
| SP4-02 | Break resume (for example, disconnect or disable the capture device so resume fails). | The recording stays paused and a Retry is possible. It does not silently lose the take. | [ ] Pass [ ] Fail |
| SP4-03 | Restore the device and retry resume. | The recording resumes. | [ ] Pass [ ] Fail |
| SP4-04 | Cause stop to fail (kill ffmpeg during recording, then click Stop). | The API returns an error (500). No bogus 0-byte file appears in the project. | [ ] Pass [ ] Fail |
| SP4-05 | Click the Stop button in the prompt bar while a recording is active. | Recording stops. The prompt-bar Stop keeps working after the widget re-renders. | [ ] Pass [ ] Fail |
| SP4-06 | Start a recording, send chat messages that re-render the widget, then Stop from the prompt bar. | Still stops. The persistent click handler is not lost. | [ ] Pass [ ] Fail |
| SP4-07 | Run `describe_images` with `analyze_video` on a recorded MP4. | Returns a description built from sampled frames. | [ ] Pass [ ] Fail |
| SP4-08 | Call `analyze_sequence` with more than 8 frames. | The request is rejected with an error saying at most 8 frames are accepted. Nothing is analysed. | [ ] Pass [ ] Fail |
| SP4-09 | Run `analyze_video` on a missing or wrong-type file. | A clear error. | [ ] Pass [ ] Fail |
| SP4-10 | Two monitors: pause on monitor 2, then resume. | Resume captures monitor 2, not the primary. | [ ] Pass [ ] Fail |
| SP4-11 | End to end: record, pause, resume, stop. Open the output. | One continuous video with no gap, and the correct screen and crop throughout. | [ ] Pass [ ] Fail |
| SP4-12 | Fullscreen click diagnostic (Task 6): record a fullscreen app (for example a browser at F11) and click inside it. | Clicks are captured and shown by the diagnostic. Note the result if clicks are not captured. | [ ] Pass [ ] Fail |

---

## SP5: Media provenance and operations (`web/demo_media.py`)

Setup: a recorded project with a source MP4. Tools: `demo_media_manifest`, `demo_inspect_frames`, `demo_replace_interval`, `demo_append_clip`, `demo_merge_narration`.

| ID | Steps | Expected | Result |
|---|---|---|---|
| SP5-01 | Ask "what media do we have?" | The agent calls `demo_media_manifest` and reports real durations and files from the tool, not from memory. | [ ] Pass [ ] Fail |
| SP5-02 | Ask for frames at 3 s and 7 s. | `demo_inspect_frames` returns PNG frames. They display in the UI. | [ ] Pass [ ] Fail |
| SP5-03 | Open a frame URL from the project file route in the browser. | Served as `image/png`. | [ ] Pass [ ] Fail |
| SP5-04 | Replace an interval (2-5 s) with a new clip. | The video is rebuilt. The `ext["media"]` ledger at `work/logs/media_ops.jsonl` gains an entry. | [ ] Pass [ ] Fail |
| SP5-05 | Replace an interval outside the video range. | Error `out_of_range`. | [ ] Pass [ ] Fail |
| SP5-06 | Append a clip. | Appended at the end. The ledger is updated. | [ ] Pass [ ] Fail |
| SP5-07 | Append a clip whose base already has audio when it should not. | Error `base_has_audio` (or the equivalent). | [ ] Pass [ ] Fail |
| SP5-08 | Merge narration with intro mode `none`. | Narration starts at 0 s. | [ ] Pass [ ] Fail |
| SP5-09 | Merge with intro mode `hold` (still frame). | The first frame holds. Narration is shifted by the hold. Audio and video stay in sync. | [ ] Pass [ ] Fail |
| SP5-10 | Merge with intro mode `card` (title card). | A title card shows. Narration is shifted. In sync. | [ ] Pass [ ] Fail |
| SP5-11 | Merge twice. | Versioned finals `final/<name>_v1.mp4` and `_v2.mp4`. The older final moves or stays per the layout. Nothing is overwritten. | [ ] Pass [ ] Fail |
| SP5-12 | Live run: approve, then narration (Lemonade), then merge with real ffmpeg. Play the final. | Audio is in sync. Length is correct. The reported durations match `ffprobe`. | [ ] Pass [ ] Fail |
| SP5-13 | Force a `sync_mismatch` (shorten the narration clip file by hand before merge). | The merge reports `sync_mismatch`, not success. | [ ] Pass [ ] Fail |
| SP5-14 | Ask the agent to claim something about the media that the tools did not return (for example, "is there a logo at 12 s?" when no frame was inspected). | It inspects frames first or says it has not verified. It does not invent. | [ ] Pass [ ] Fail |
| SP5-15 | Watch `work/logs/merge_progress.json` during a merge. | Updates during the merge. See SP7. | [ ] Pass [ ] Fail |

---

## SP6: Media intake and multi-clip (`/api/demo-media`)

Setup: Demo Recorder pinned in the tab. Test media from the global prerequisites.

| ID | Steps | Expected | Result |
|---|---|---|---|
| SP6-01 | Use the chat attach control to attach the 10 s MP4. | An attach chip appears with an upload progress indicator. | [ ] Pass [ ] Fail |
| SP6-02 | Try to submit while the upload is in progress. | Submit is blocked until the upload finishes (`data-media-uploading`). | [ ] Pass [ ] Fail |
| SP6-03 | After upload, submit "use this clip". | The agent enters Import Mode and uses the clip. | [ ] Pass [ ] Fail |
| SP6-04 | The clip panel (`#demo-media-panel`) shows the clip with duration and resolution. | Correct values. | [ ] Pass [ ] Fail |
| SP6-05 | Upload three more clips, then reorder them in the panel. | The order is saved and survives a reload. | [ ] Pass [ ] Fail |
| SP6-06 | Trim a clip (set start and end). | The trim is saved. The timeline length updates. | [ ] Pass [ ] Fail |
| SP6-07 | Delete a clip. | It is removed from the panel and the registry. | [ ] Pass [ ] Fail |
| SP6-08 | Upload the `.txt` renamed to `.mp4`. | Rejected with a clear error. Nothing is registered. | [ ] Pass [ ] Fail |
| SP6-09 | Upload the file larger than 2 GiB. | Rejected with a size error. | [ ] Pass [ ] Fail |
| SP6-10 | Upload more than 8 clips. | The ninth is rejected with a clear limit message. | [ ] Pass [ ] Fail |
| SP6-11 | Upload more than 4 audio assets. | The fifth is rejected. | [ ] Pass [ ] Fail |
| SP6-12 | Upload media longer than 1800 s or wider than 7680 px (if available). | Rejected with a limit message. | [ ] Pass [ ] Fail |
| SP6-13 | Upload a file whose name has spaces and non-ASCII characters. | Accepted. Stored safely. Plays. | [ ] Pass [ ] Fail |
| SP6-14 | Cancel an upload midway. | The chip is removed. No partial file is left in the project. | [ ] Pass [ ] Fail |
| SP6-15 | Ask the agent to build the timeline (`demo_compose`). | `work/timeline.mp4` is created. Clips joined in panel order. | [ ] Pass [ ] Fail |
| SP6-16 | Add the MP3 as a soundtrack and compose again, then approve narration and merge. | `work/timeline.mp4` stays silent and `work/soundtrack.m4a` is written. The merged final mixes the soundtrack under the narration at low volume (0.25). | [ ] Pass [ ] Fail |
| SP6-17 | Edit clips (upload, trim, delete) while a compose or merge is running. | Rejected with 409 `project_locked`. The UI explains it. | [ ] Pass [ ] Fail |
| SP6-18 | Clips with different resolutions (the second clip). | The timeline normalises them. No stretched frames. | [ ] Pass [ ] Fail |

---

## SP7: Narration editor UX and delivery

Setup: a project with an analysed recording and the narration widget. TTS available.

| ID | Steps | Expected | Result |
|---|---|---|---|
| SP7-01 | In the narration editor, scroll down to a segment and edit its text. | The scroll position does not jump when the widget resizes. | [ ] Pass [ ] Fail |
| SP7-02 | Open a tall replacement editor (a long text segment). | It reveals once into view and does not keep scrolling. | [ ] Pass [ ] Fail |
| SP7-03 | Use the "Pause after (s)" input on a segment: values 0, 2.5, 10, 11, -1, "abc". | 0 to 10 accepted. Values outside the range or non-numeric are rejected or clamped, with feedback. | [ ] Pass [ ] Fail |
| SP7-04 | Hover the Pacing tips tooltip. | Shows guidance text. Readable and not clipped. | [ ] Pass [ ] Fail |
| SP7-05 | Start the merge. | A `#merge-status` line shows progress, polled from `merge_progress.json`. | [ ] Pass [ ] Fail |
| SP7-06 | Make the merge not start (stop the backend job before it begins) and wait 120 s. | The status shows "has not started" retry text with a retry option. | [ ] Pass [ ] Fail |
| SP7-07 | Complete the merge. | The delivery widget appears, and the progress state reaches done. | [ ] Pass [ ] Fail |
| SP7-08 | Click "Open final folder". | Windows Explorer opens at the `final/` folder with the file selected (reveal). | [ ] Pass [ ] Fail |
| SP7-09 | Click "Open project folder". | Explorer opens the project folder. | [ ] Pass [ ] Fail |
| SP7-10 | Look for a Download button. | There is none. It was replaced by the two folder buttons. | [ ] Pass [ ] Fail |
| SP7-11 | Delete the project folder, then click Open final folder. | A clear error, no crash. | [ ] Pass [ ] Fail |
| SP7-12 | Intro controls: choose `none`, `hold` and `card` in the narration editor and merge each. | Each matches SP5-08 to SP5-10. | [ ] Pass [ ] Fail |
| SP7-13 | Reload the page mid-merge. | The progress resumes from `merge_progress.json` and does not restart or vanish. | [ ] Pass [ ] Fail |
| SP7-14 | Widget safety: confirm the widget works with no console errors about blocked parent access. | Folder, summary and progress calls go through the `gator:*` bridge actions. | [ ] Pass [ ] Fail |

---

## Known-unverified items (must be run by a human)

Run these in particular because automated tests cannot cover them:

- Real Windows recording with real ffmpeg and Electron: SP4-01, SP4-11, SP5-12.
- Electron folder picker and Settings row: SP3-01 to SP3-05.
- Fullscreen click diagnostic and two-monitor pause/resume: SP4-10, SP4-12.
- Live approve, narration, merge: SP2-12, SP5-12.
- Real Explorer reveal: SP7-08, SP7-09.
- Progress states including done: SP7-05, SP7-07.
- Chat attach chip, upload progress, clip panel, submit gate, soundtrack mix: SP6-01 to SP6-04, SP6-16.
- Replace and append intervals, hold and card intros, narration shift, versioned finals, PNG serving: SP5-03 to SP5-11.
- Provoke a rejected tool call and the Continue banner: SP1-01 to SP1-04.
