# Media Provenance and Ops — Design

Sub-project 5 of the issue #55 Demo Recorder overhaul (mkflyamd/aigator-releases #55). Covers item 13, the video-extension and title/intro part of item 12, and remediation plan item C (1-3). Builds on sub-project 3 (`web/demo_projects.py`) and reads approvals written by sub-project 2.

## Problem

The agent edits and narrates demo video by writing ad-hoc ffmpeg code, then tells the user what it did without any evidence:

- A correction claimed frames at 390 s and 405 s in a 62.2 s file. No probe was run; the times were invented.
- "Slack outro fixed" was reported with no record of which source interval replaced which part of the recording.
- A title/intro and a longer-than-video narration are handled by inline Python in `SKILL.md` Phase 4. The intro duration is not part of the narration sync, and the video extension is not reported.

## Goals

1. Every media claim the agent makes comes from a tool result built from ffprobe/ffmpeg output on real files.
2. Seek times are validated against the probed duration before ffmpeg runs; an impossible time is an error carrying the real duration, never a clamp.
3. Supported operations, each verified after it runs: extract frames, replace an interval with an interval of another clip, append a clip, hold the first frame or add a title card, extend the video to a longer narration, merge narration.
4. Every operation is recorded in a per-project ledger so a later question ("what replaced the outro?") is answered from disk.
5. The intro duration shifts the narration start times in one computed timeline before TTS, so sync holds.

Non-goals: audio editing of the recording itself, transitions, a general timeline editor, new HTTP routes (so no CSRF surface), changes to the narration editor UI (sub-project 7).

## Delivery shape

First-class tools in `web/skills/gator-demo-recorder/tools.py` backed by one FastAPI-free module `web/demo_media.py`, not skill scripts.

- The agent cannot fabricate a result: the tool returns only what ffprobe measured after ffmpeg ran, and the skill rule is to quote that result.
- Tools run in-process (sync handlers go through `asyncio.to_thread`), so they avoid sandbox prompts and the `run_python` missing-`code` failure class.
- The module is testable with plain pytest and real ffmpeg on generated fixtures.

`tts_pipeline.py` stays the TTS and audio-mux engine. `demo_merge_narration` runs it as a subprocess with the existing flags.

## Tools

All tools take an optional `project_id` (default: the active project) and return `{"error": code, "message": ..., ...}` on failure (a truthy `error` marks a tool error for the executor). All paths in arguments and results are project-relative (`source/recording.mp4`).

| Tool                    | Arguments                                                                                         | Result (success)                                                                                                                                                                                                                                             |
| ----------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `demo_media_manifest`   | none                                                                                              | `{ok, current, files:[{rel, duration_sec, width, height, fps, has_video, has_audio, size_bytes}], generated_at}` from ffprobe over `source/`, `work/normalized/`, `work/edits/`, `final/`                                                                    |
| `demo_inspect_frames`   | `source`, `times_sec` (1-8)                                                                       | `{ok, source, duration_sec, frames:[{time_sec, rel, path, bytes}], op_id}`; PNGs in `work/frames/`                                                                                                                                                           |
| `demo_replace_interval` | `start_sec`, `end_sec`, `insert_source`, `insert_start_sec=0`, `base=""`                          | `{ok, output:{rel, path, duration_sec}, base, replaced_interval_sec, inserted_from:{rel, interval_sec}, inserted_audio_dropped, timeline_shifted:false, op_id}`                                                                                              |
| `demo_append_clip`      | `clip`, `clip_start_sec=0`, `clip_end_sec`, `base=""`                                             | `{ok, output, base, appended_from:{rel, interval_sec}, appended_at_sec, inserted_audio_dropped, timeline_shifted:false, op_id}`                                                                                                                              |
| `demo_merge_narration`  | `intro_mode`, `intro_duration_sec`, `intro_title`, `voice`, `video`, `approval_id` (all optional) | `{ok, output:{rel, path, duration_sec, version}, video, intro:{mode, duration_sec, title, applied, source}, narration:{segments, offset_sec, first_start_sec}, video_extended_by_sec, video_stream_sec, audio_stream_sec, sync_ok:true, approval_id, op_id}` |

`base` defaults to the project's current video (see "Current video"). `video` for the merge defaults the same way.

## Validation rules

- Every file is probed first (`ffprobe -show_format -show_streams`). A time must satisfy `0 <= t < duration`; an interval end may exceed the duration by at most 0.05 s and is clamped to it. Violations raise `out_of_range` with `requested_sec`, `duration_sec`, `valid_range_sec`, and `options` (choose a real interval, supply another clip, re-record).
- `demo_inspect_frames` rejects the whole call when any time is out of range, so no partial evidence is produced.
- `demo_replace_interval` needs `insert_start_sec + (end_sec - start_sec)` inside the insert clip; otherwise `out_of_range` with `needed_sec`.
- Edits run only on silent video. A base with an audio track fails with `base_has_audio` (edit the silent recording, then merge again). Replace keeps the duration, so approved narration timing stays valid; append extends only the end, so earlier timing is unchanged (`timeline_shifted` is always `false`).
- Each output is written as `*.partial.mp4`, probed, and renamed only if its duration is within max(0.30 s, 2 frames) of the expected sum of the pieces; otherwise it is deleted and `output_verification_failed` is returned.
- Paths resolve through `dp.resolve_file`, which rejects traversal.

## Current video, ledger, and `ext["media"]`

Edits never overwrite the recording. Outputs go to `work/edits/edit_NNN.mp4`; intro renders to `work/edits/intro_NNN.mp4`.

`project.json` `ext["media"]` (written with `dp.set_ext` under a module lock):

```json
{
  "schema": 1,
  "current": "work/edits/edit_002.mp4",
  "current_base": "source/recording.mp4",
  "output_version": 2,
  "manifest": { "generated_at": "...", "files": [] },
  "ops": []
}
```

- `current` is the video later tools and the merge default to. It is honored only while `current_base` equals the project's current `raw` (sub-project 6 repoints `raw` to `work/timeline.mp4` when clips change), so a stale edit chain is dropped automatically.
- `ops` holds the last 50 operation summaries. The full truth is the append-only `work/logs/media_ops.jsonl`; one JSON object per line with `op_id`, `at`, `operation`, the base, the exact source interval(s), the output block, and for merges the approval id, intro, and measured stream durations.
- `output_version` numbers the delivered files (`final/<project name>_v<N>.mp4`).

## Intro option and sync

Three flat fields, stored in the approved narration `flags` (sub-project 7 sets them; the tool arguments override):

| Field                | Values                                                                       |
| -------------------- | ---------------------------------------------------------------------------- |
| `intro_mode`         | `none` (default), `hold` (freeze the first frame), `card` (solid title card) |
| `intro_duration_sec` | 0.5-10, default 2                                                            |
| `intro_title`        | up to 80 characters; required for `card`, optional for `hold`                |

User-facing wording is exact: "Hold" freezes the first frame; "Title card" shows a title. The tool never calls a hold a title card.

Sync rule: `build_timeline` computes `final_start_at = start_at + intro_duration` for every segment and writes both `work/timeline.json` and `work/narration_final.json` (segments with `start_at` replaced by `final_start_at`) before TTS runs. `tts_pipeline.py` timing code is unchanged. A segment whose `start_at` is negative, beyond the source duration, non-numeric, or earlier than the previous segment is rejected before any TTS call.

Titles are drawn with ffmpeg `drawtext` from a text file with `expansion=none`, so `:`, `'` and `%` in a title are literal. The font is copied next to the render so no drive-letter path reaches the filter graph. If no system font exists the tool returns `font_missing`.

## Merge flow

`demo_merge_narration`:

1. Resolve the project, load the approval (see below), and write `work/logs/merge_progress.json` `state: running`.
2. Probe the video; build the timeline; render the intro if requested.
3. Run `tts_pipeline.py` (`--video --timeline --narration --output --work-dir --voice`, plus `--soundtrack` when `ext["clips"]["timeline"]` is `ready` with a soundtrack file) to `work/out/final_candidate.mp4`. One line changes in `tts_pipeline.py`: the extended-video temp file goes next to the output, not next to the source video, so the source folder is never written.
4. Probe the candidate. It must contain video and audio and the two stream durations must agree within 1.0 s, else `sync_mismatch` with both measured durations and the file is not delivered.
5. `dp.archive_final(pid)`, then move the candidate to `final/<name>_v<N>.mp4`; record the op; write progress `done`.

When narration is longer than the video, `merge_audio_video` already holds the last frame; the result reports `video_extended_by_sec = video_stream_sec - input video duration` (measured, not computed from the script).

### Approval check

The merge reads `ext["approval"]` (sub-project 2): `current_id`, `sha256`, `media_fingerprint`. It loads `work/approvals/<current_id>.json`, recomputes `narration_approval.canonical_hash(segments, flags)` and compares it to `sha256`. A supplied `approval_id` different from `current_id` returns `approval_superseded`. Missing approval: `narration_not_approved`. Hash mismatch or unreadable record: `approval_corrupt`. A `raw` whose `narration_approval.media_fingerprint` differs from the recorded one: `approval_stale_media`. These replace the skill-side `load_approval.py` calls for Phase 4.

## Progress file

`work/logs/merge_progress.json`, written atomically by the tool: `{approval_id, state: running|done|failed, stage, step, total, message, error, updated_at}`. Sub-project 7's progress panel polls it.

## Error codes

`no_project`, `project_not_found`, `no_video`, `file_not_found`, `path_outside_project`, `unreadable_media`, `out_of_range`, `bad_interval`, `bad_argument`, `too_many_frames`, `frame_not_extracted`, `base_has_audio`, `output_verification_failed`, `font_missing`, `ffmpeg_missing`, `ffmpeg_failed`, `ffmpeg_timeout`, `tts_failed`, `sync_mismatch`, `narration_not_approved`, `approval_superseded`, `approval_corrupt`, `approval_stale_media`, `media_op_failed`.

## SKILL.md rules

- New section "Truthful Media Claims" after the Audio/Video Quality Rules: state a duration, a timestamp, or an edit only from a `demo_*` tool result; before describing a moment call `demo_inspect_frames` and describe only the returned frames; quote `inserted_from` / `appended_from` / `video_extended_by_sec` verbatim; on an error, relay `message`, `duration_sec` and `options`, never retry with a guessed time.
- Phase 4 becomes a `demo_merge_narration` call with error handling by code; the python/ffmpeg block is removed.
- Phase 2 keeps the sub-project 4 `analyze_video` flow and gains a pointer to `demo_inspect_frames` for follow-up inspection.
- Phase 5 reports size, duration and intro/extension from the merge result only.

## Testing

All under `tests/demo_media_ops/` with real ffmpeg on generated lavfi fixtures (a 62.2 s silent video as the project recording):

- `test_demo_media_ops.py`: probe durations; 390 s rejected with the real duration and no frame files written; frames plus ledger line; replace proves its source interval and keeps duration; replace rejects out-of-range and a too-short insert; append extends; audio base refused; intro hold/card duration with `:`, `'`, `%` in the title; intro normalization rules; timeline shift and validation; manifest; replaced pixels come from the insert (frame colors at 10/22/40 s); the edit chain is dropped when `raw` changes.
- `test_demo_media_merge.py`: narration longer than the source extends the video and reports it; intro hold shifts `start_at` and adds duration; second merge archives the first and bumps the version; narration start past the source is rejected; superseded, corrupt and stale approvals refused; progress file on success and failure; soundtrack forwarded only when the timeline is ready; unapproved narration refused. TTS is replaced by a generated sine track; the real `merge_audio_video` runs.
- `test_demo_media_tools.py`: tool contract validates; schema properties equal handler parameters; handlers return error dicts; replace works through the tool layer.
- `test_demo_media_skill_contract.py`: SKILL.md Phase 4 calls `demo_merge_narration` and contains no ffmpeg code; the Truthful Media Claims section names every tool.

## Interfaces for other sub-projects

- **SP2 (approval transaction):** SP5 depends on `narration_approval.canonical_hash` and `media_fingerprint` at import time and reads `ext.approval.{current_id, sha256, media_fingerprint}` and `work/approvals/<id>.json`. SP5's SKILL.md task replaces SP2's Phase 4 loader text and updates SP2's `test_phase4_uses_the_verified_loader` to match.
- **SP6 (media intake, multi-clip):** SP6 stays in `ext["clips"]`. SP5 follows `project.raw` (so `work/timeline.mp4` becomes the edit base) and forwards `--soundtrack` only when `ext["clips"]["timeline"].state == "ready"`. SP6 owns `tests/demo_media/`; SP5 uses `tests/demo_media_ops/`.
- **SP7 (narration editor UX):** put `intro_mode`, `intro_duration_sec`, `intro_title` in the `NARRATION_APPROVED` flags; preview `ext.media.current`; poll `work/logs/merge_progress.json`.
- **SP4 (recorder fixes):** no interaction.

SKILL.md ordering: SP3, SP2, SP6, SP7 and SP5 all edit Phase 4/5 text. SP5's SKILL.md task lands last and anchors on headings, not line numbers. Suggested order: SP3, SP2, SP6, SP7, SP5. `tts_pipeline.py` is also edited by SP6 and SP7; SP5's one-line change does not overlap.

## Requested additions to SP3 interfaces

- `GET /api/demo-projects/{id}/file` and `serve-file` serve `.png` as `image/png` (today `mp4`, `mp3`, `m4a`), so inspected frames can be shown as proof thumbnails.

Nothing else: SP5 uses `create_project`, `get_project`, `project_path`, `resolve_file`, `archive_final`, `set_ext`, `update_project`, `get_active_id`, and `atomic_write_json` as specified.

## Decisions

1. Tools, not skill scripts: results cannot be fabricated and run in-process without sandbox prompts.
2. Validate against probed duration before running ffmpeg; out-of-range is an error with the real duration, never a clamp.
3. Edit outputs go to `work/edits/`; the recording is never overwritten; `current` is honored only while its base matches `raw`.
4. Edits and intro apply to silent video only; replace preserves duration so approved narration stays valid.
5. The ledger (`media_ops.jsonl`) is the provenance truth; `ext["media"]` keeps the last 50 summaries and the manifest.
6. Intro is three flat flags (`intro_mode`, `intro_duration_sec`, `intro_title`); the tool argument overrides the approved flags; hold and title card are different words and different renders.
7. Intro shifts narration through one computed timeline (`final_start_at`) before TTS; `tts_pipeline.py` timing is untouched.
8. Merge verifies video and audio streams and a 1.0 s sync tolerance before delivery; failure returns the measured numbers and delivers nothing.
9. Approval is verified in-process against SP2's hash and media fingerprint.
10. The tool writes `merge_progress.json` itself for SP7.
11. No new HTTP routes, so no CSRF changes.
12. One line changes in `tts_pipeline.py` (temp file beside the output).
