# Narration Approval Transaction and Skill Pinning — Design (Sub-project 2)

Issue: mkflyamd/aigator-releases #55, items #10 and #11, remediation plan B items 2-4, and the routing half of #12.
Builds on: `2026-10-19-demo-project-state-design.md` (SP3). SP3's store, layout and routes are used as written and not redefined here.

## Problem

1. **Approval is a race (#10).** On Approve, `app.js` (bridge, ~18190-18236) fires `fetch('/api/recorder/narration-approved')` without `await` and with `.catch(() => {})`, ignores `response.ok`, and submits the chat turn immediately. If the write fails or is slow, Phase 4 starts anyway and reads whatever is on disk.
2. **Approval is anonymous and global (#11).** `recorder.py` writes one `~/.gator/narration_pending.json` with no ID. Phase 4 never checks that the file belongs to the current project or the current recording, so a stale file or an "Ask again" replay of an old trigger produces a video with the wrong narration.
3. **Widget messages lose the skill (#10, #12).** `Recording complete`, `NARRATION_APPROVED`, `NARRATION_REEDIT` and the cleanup message carry no `skill`. `chat.py` then runs the continuation classifier plus keyword and LLM inference (1541-1623) and activates unrelated skills (Calendar, Jira, Slack, Teams) for a message that is plainly a Demo Recorder step.

## Goals

- Approval is a server-confirmed transaction: no Phase 4 turn is dispatched unless the server has durably stored that exact narration.
- Every approval has an ID. Phase 4 proves it is running the current approval for the current recording, and refuses otherwise.
- A tab that is working with a skill keeps that skill (and its project) without re-inference, until the user unpins it. The mechanism is generic; Demo Recorder is the first consumer.

## Non-goals

- The narration editor UI (SP7), media import (SP6), and recorder capture fixes (SP4).
- Tool-call repair (SP1).
- Pinning skills other than Demo Recorder in this sub-project. The provider registry is generic, but only the Demo Recorder provider is registered.

## Approval transaction

### Storage (inside the SP3 project folder)

```
<project>/work/approvals/<approval_id>.json   immutable record
<project>/work/narration.json                 mirror of the current approval (SP3 path)
<project>/project.json  ext.approval          {current_id, version, sha256, approved_at, media_fingerprint}
```

Record `work/approvals/<approval_id>.json`:

```json
{"approval_id": "appr_2_9f3c1ab0", "version": 2, "project_id": "demo_20261019_143012",
 "approved_at": "2026-10-19T14:40:00+00:00", "segments": [...], "flags": {...},
 "sha256": "<64 hex>", "media_fingerprint": "<64 hex or null>"}
```

- `sha256` is SHA-256 of `json.dumps({"segments": segments, "flags": flags}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8.
- `approval_id` is `appr_<version>_<first 8 hex of sha256>`. `version` starts at 1 and increases by one per distinct approval of the project.
- `media_fingerprint` is SHA-256 over the decimal file size, the first 64 KiB, and (when the file is larger than 64 KiB) the 64 KiB starting at `max(size - 64 KiB, 64 KiB)` of the project's raw recording (`project.json` `raw`). It is `null` when there is no raw file. File times are not used, so a moved or synced folder still validates.
- `work/narration.json` is `{"segments", "flags", "timestamp", "approval_id", "version"}`. It is a convenience mirror; the record is the source of truth.

### Backend

New `web/narration_approval.py` (no FastAPI dependency):

```python
class ApprovalError(ValueError): ...
def canonical_hash(segments: list, flags: dict) -> str
def media_fingerprint(path: Path | None) -> str | None
def approve(project_id: str, segments: list, flags: dict) -> dict
```

`approve()` runs under a module lock:

1. Validate: `segments` is a non-empty list of objects each with a string `text`; `flags` is an object. Otherwise `ApprovalError`.
2. Compute `sha256` and the media fingerprint.
3. If `ext.approval` has the same `sha256` and `media_fingerprint` and its record file exists, return the project plus `approval` with `reused: true` and write nothing.
4. Otherwise `version = previous + 1`; write the record, then `work/narration.json`, then `update_project(stage="narration_approved", narration={"approved_at": ...})`, then `set_ext("approval", {...})`. The `set_ext` write is the commit point: Phase 4 only trusts `ext.approval.current_id`, so a crash between steps leaves the previous approval current.
5. Write the legacy `narration_pending.json` next to the SP3 index (`dp.INDEX_PATH.parent`), best effort, for skill copies installed before this change. The bundled skill never reads it.
6. Return the SP3 project dict plus `approval: {approval_id, version, approved_at, sha256, segment_count, reused}`.

Routes (no new routes):

- `POST /api/demo-projects/{project_id}/narration` (SP3 route, CSRF already required) calls `approve()`; `ApprovalError` maps to 400, unknown project to 404.
- `POST /api/recorder/narration-approved` (SP3 legacy shim) calls `approve()` for the active project instead of writing the pending file itself.

### Frontend (`web/static/app.js` bridge)

`NARRATION_APPROVED:<json> [FLAG:value ...]` is handled by `_handleNarrationApproved(text, source)`:

1. `_parseNarrationApproval(text)` returns `{segments, flags, projectId}`; `PROJECT_ID` is removed from `flags`.
2. Resolve the project: `projectId`, else `GET /api/demo-projects/active`. No project: fail.
3. `await fetch('/api/demo-projects/<id>/narration', POST)`. The `window.fetch` wrapper in `app.js` attaches the CSRF token. A non-OK response fails the transaction with the server's `detail`.
4. On success: pin the tab to Demo Recorder with this project, reply to the iframe `{type: 'gator:narration-approval-result', ok: true, approval_id, version, segment_count, reused, project_id}`, then submit the trigger `Narration approved (N segments, approval <approval_id>). Please generate TTS and merge.` (music variant keeps the same prefix and adds `, approval <id>`).
5. On failure: reply `{ok: false, error}` and submit nothing.

The `gator_narration_approved` and `gator_narration_flags` sessionStorage writes are deleted (no readers exist).

The widget disables the Approve button while pending, shows `Approved (N segments)` on success, and re-enables it with the error on failure. The widget learns the project from a `PROJECT_ID_PLACEHOLDER` the agent fills in (next to `SEGMENTS_PLACEHOLDER`) and sends it as `PROJECT_ID:<id>`; when the placeholder is unfilled the bridge falls back to the active project.

### Agent read path (staleness)

The agent never calls a mutating route. New `web/skills/gator-demo-recorder/scripts/load_approval.py` is stdlib-only (the skill can run from `~/.gator/skills/mine`, where `web/` modules are not importable) and carries its own copies of `canonical_hash` and `media_fingerprint`; a parity test keeps them identical to `narration_approval.py`.

```
python load_approval.py --project-dir <PROJECT_DIR> [--approval-id <id>] [--segments-out <file>]
```

It prints one JSON object. Exit 0: `{"ok": true, "approval_id", "version", "approved_at", "flags", "segment_count", "project_dir"}` and, with `--segments-out`, writes the segments list (the shape `tts_pipeline.py --narration` already reads). Exit 2: `{"ok": false, "code", "error"}`.

| Condition | `code` | Agent action |
|---|---|---|
| no `ext.approval` | `missing` | ask the user to click Approve |
| `--approval-id` differs from `current_id` | `superseded` | stop; a newer approval exists and its own turn handles it |
| record unreadable, or its hash differs from `ext.approval.sha256` | `corrupt` | ask the user to re-open the narration editor and approve again |
| raw recording fingerprint differs from `media_fingerprint` | `stale_media` | ask the user to re-approve against the new recording |
| otherwise | (ok) | run Phase 4 with the returned segments |

An "Ask again" replay of an old Phase 4 trigger carries the old approval ID and is refused as `superseded`.

## Skill pinning

### Client (`app.js`)

- Pin state per tab: `{skill, projectId}` in `localStorage` key `tab-pin-<tabId>` (removed on tab close next to `tab-chips-<tabId>`), cached in a `Map`.
- A pin is set by a `gator:send-message` that carries `pin_skill` (and optional `project_id`), by a successful approval, or by legacy inference: a widget message starting with `Recording complete.`, `NARRATION_APPROVED:`, `NARRATION_REEDIT:` or `Please delete the frames/ and tts_work/` pins Demo Recorder, so already-saved widgets work. A pin without a project keeps the project of the existing pin.
- A `skill-pin-chip` ("Pinned: Demo Recorder ×") is drawn in `#chat-chip-row`. `_restoreChipsForTab` and `doSend` clear that row, so both re-render the pin chip. The × removes the pin.
- `doSend` adds `pinned_skill` and `pinned_project_id` to `/api/chat` (also to the permission re-POST payload) unless the message starts with `/` — a slash command is the user choosing another skill, and the pin stays for later messages.

### Server (`chat.py`, new `web/skill_pin.py`)

- `ChatRequest` gains `pinned_skill: str | None = None` and `pinned_project_id: str | None = None`.
- `skill_pin.resolve_pin(pinned_skill, pinned_project_id, known_skills, slash_active)` returns `Pin(skill, project_id)` or `None` when the skill is unknown, a slash command is active, or the skill is empty. `project_id` is kept only when it matches `^[A-Za-z0-9_.-]{1,80}$`.
- `_skills_locked = bool(req.scoped_skill or _pin)` replaces `req.scoped_skill` at the four gating sites: the classifier branch (1541), keyword/LLM inference (1556), and the image-analysis checks (1625, 1626). The locked skill is added to `_active_sids` and `_explicit_skill_ids` (explicit skills are exempt from `_MAX_AUTO_SKILLS`), and injected into `_all_active` the way `scoped_skill` is. Declared `requires:` dependencies still expand.
- A generic registry `PIN_CONTEXT_PROVIDERS: dict[str, Callable[[str | None], str | None]]` maps a skill ID to a function returning an extra system-prompt block. After the skill prompts are appended, `pin_context_block(pin)` is appended when it returns text. Provider errors are swallowed so a provider can never fail a chat turn.
- The Demo Recorder provider returns the project ID, `PROJECT_DIR` (from `get_project`), stage, and current approval ID and version, and tells the agent to use that `PROJECT_DIR` instead of the active-project resolver.

## SKILL.md changes (applied on top of SP3's edits)

- Phase 3 widget: `PROJECT_ID_PLACEHOLDER` added to the placeholder rules; `approve()` replaced by the pending/result version above; Approve button gets `id="btn-approve"`.
- Every `gator:send-message` in the skill (Recording complete, NARRATION_APPROVED, NARRATION_REEDIT, cleanup) gets `pin_skill:'gator-demo-recorder'` and `project_id`. A contract test enforces that none is missed.
- Phase 4 step 1: run `load_approval.py` with `--project-dir`, the approval ID parsed from the trigger, and `--segments-out`, handle the failure codes, and feed the segments file to `tts_pipeline.py --narration`. No `narration_pending.json` reference remains (SP3's contract test forbids it). `work/narration.json` and `final/` stay documented (SP3's contract test requires them).

## Files

| File | Change |
|---|---|
| `web/narration_approval.py` | new |
| `web/skill_pin.py` | new |
| `web/skills/gator-demo-recorder/scripts/load_approval.py` | new |
| `web/routes/demo_projects.py` | narration route calls `approve()` |
| `web/routes/recorder.py` | `narration-approved` shim calls `approve()` |
| `web/routes/chat.py` | `ChatRequest` fields, `_skills_locked`, pin context block |
| `web/static/app.js` | approval handler, pin state/chip, `doSend` fields |
| `web/static/style.css` | `.skill-pin-chip` |
| `web/skills/gator-demo-recorder/SKILL.md` | widget, messages, Phase 4 |
| `tests/approval_transaction/*`, `tests/narration_approval.test.js` | new |

## Testing

- Unit: hashing, fingerprint (content-sensitive, mtime-insensitive), `approve()` (record, mirror, `ext`, stage, idempotence, version bump on text or media change, validation), `load_approval` (all codes, CLI exit codes, parity with the backend copies).
- Route: approval summary in the response, 400/404, CSRF required, legacy shim.
- Pinning: `resolve_pin`, provider output, source-structure assertions on `chat.py` gating sites.
- JS: pure functions (`_parseNarrationApproval`, `_approvalTrigger`, `_pinFromMessage`, `_mergePin`, `_pinForSend`) extracted from `app.js` and run in `vm`; source assertions that the bridge awaits the fetch, checks `res.ok`, and no longer swallows errors.
- Skill contract: every `gator:send-message` carries `pin_skill`; Phase 4 uses `load_approval.py`; no `narration_pending.json`.
- Manual (Playwright against the running app): approve with the backend write failing (no chat turn, widget shows the error), approve then replay the old trigger (refused as superseded), approve and confirm only Demo Recorder tools load for the turn.

## Interfaces with other sub-projects

- **SP3:** uses `get_project`, `project_path`, `update_project`, `set_ext`, `atomic_write_json`, `INDEX_PATH`. SP2 edits SP3's narration route handler and the legacy shim body (one call each). Stage `narration_approved` is still set, now by `approve()`.
- **SP7 (narration editor):** the editor must keep the `NARRATION_APPROVED:<json> PROJECT_ID:<id>` message, send `pin_skill`, disable Approve while pending, and listen for `gator:narration-approval-result`.
- **SP6 (multi-clip):** adding clips re-stitches `source/recording.mp4`, which changes the media fingerprint, so the earlier approval is refused as `stale_media` until the user approves again.

## Decisions

1. Approval is a server-confirmed transaction; the chat turn is dispatched only after the stored narration is confirmed.
2. IDs are `appr_<version>_<sha8>`; records are immutable; `ext.approval.current_id` is the commit point.
3. Re-approving identical content is idempotent (same ID, nothing rewritten).
4. The media fingerprint ignores file times.
5. The agent reads approvals through stdlib-only `load_approval.py` and never calls a route.
6. `narration_pending.json` is a best-effort legacy mirror; the bundled skill does not read it.
7. Pinning is per tab, persists until the user clicks ×, suppresses auto-inference, and yields to slash commands.
8. The pin context provider is a generic registry; the Demo Recorder provider is the only one registered.
9. The bridge infers a Demo Recorder pin from the four legacy widget message prefixes so saved widgets keep working.
10. `PROJECT_ID` travels as a flag on the `NARRATION_APPROVED` message and is filled into the widget by the agent.
