# Calendar Draft Card, Timezone-Aware Slots and Transcript List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-click meeting set-up approvals, timezone-aware slot suggestions, a `calendar-event` draft that is handed to Outlook (never sent by Gator), and a fast, honest transcripts list.

**Architecture:** Bundle the calendar, people and contacts data-source approvals into one card (`Source.group_keys`). Add a small `timezones` module used by `find_meeting_times`. Replace the invite-sending `create_calendar_event` tool with `draft_calendar_event`, which stores a `calendar-event` draft; the existing `open-in-outlook` route turns it into an Outlook compose deeplink. Split transcript recording resolution into an instant list plus a per-row resolve call.

**Tech Stack:** Python 3.12, FastAPI, pytest (`asyncio_mode=auto`, `pythonpath = web .`), `zoneinfo`, vanilla JS (`web/static/app.js`, `web/static/third-pane.js`), node `vm` JS tests.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-31-calendar-draft-and-native-tools-design.md`.
- Do not add `Co-Authored-By` lines in commit messages.
- The project is called AI Gator, never "POC".
- Use `aigator-fake-api-key` as the only fake credential in tests, examples, fixtures and docs.
- Every new POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]`; do not touch `tests/csrf_route_baseline.txt`.
- Email, Teams and Slack messages never auto-send. The calendar draft card has only "Open in Outlook"; the agent has no tool that calls `POST /me/events` for a meeting.
- All LLM calls go through `llm.gateway` (no LLM calls are added here).
- The custom FullCalendar pane is unchanged. Native Outlook calendar migration and Google Calendar handoff are out of scope.
- Do the least that meets the spec; no caveat notes in docs.
- Run tests from the repo root: `python -m pytest <path> -q`.

## File Structure

- `web/data_sources.py` (modify): grouped sources, `allow_source`, `deny_source`, `approval_key`.
- `web/agent_loop.py` (modify `_ask_source`): use the grouped helpers.
- `web/skills/calendar/timezones.py` (create): Windows to IANA map, `zone`, `fmt_range`, `attendee_zones`.
- `web/skills/calendar/tools.py` (modify): tz-aware `find_meeting_times`, new `draft_calendar_event`, remove `create_calendar_event`.
- `web/skills/calendar/SKILL.md`, `web/skills/aigator/SKILL.md` (modify): prompt text.
- `web/routes/drafts.py` (modify `open_draft_in_outlook`): `calendar-event` branch.
- `web/static/app.js` (modify `_injectDraftApprovalCard`): `calendar-event` card.
- `web/skills/m365-teams/scripts/transcript_recording.py` (modify): `list_recordings_from_chat`, `resolve_share`.
- `web/routes/teams.py` (modify): `/recordings` without Graph resolution, new `GET /api/recordings/resolve`.
- `web/static/third-pane.js` (modify): async transcript rows, text label on both transcript buttons.
- Tests: `tests/prompt_injection/test_data_sources.py`, `tests/test_calendar_timezones.py` (create), `tests/test_calendar_invite_parsing.py`, `tests/test_calendar_draft.py` (create), `tests/test_calendar_draft_route.py` (create), `tests/calendar_draft_card.test.js` (create), `tests/test_teams_transcripts_route.py`, `tests/test_transcript_resolve.py` (create), `tests/transcripts_panel.test.js` (create).

---

### Task 1: One approval for calendar, people and contacts

**Files:**

- Modify: `web/data_sources.py`
- Modify: `web/agent_loop.py` (`_ask_source`, ~line 591)
- Test: `tests/prompt_injection/test_data_sources.py`

**Interfaces:**

- Produces: `Source.group_keys: tuple[str, ...]`, `Source.group_label: str`; `data_sources.approval_key(source) -> str`; `data_sources.allow_source(context_id, source) -> None`; `data_sources.deny_source(context_id, source) -> None`.

- [ ] **Step 1: Write failing tests** (append to `tests/prompt_injection/test_data_sources.py`)

```python
def test_calendar_people_and_contacts_share_one_approval():
    cal = ds.source_for_call("read_calendar", {})
    people = ds.source_for_call("search_people", {})
    contacts = ds.source_for_call("search_contacts", {})
    assert ds.approval_key(cal) == ds.approval_key(people) == ds.approval_key(contacts)
    ds.allow_source("tab1", cal)
    assert ds.is_allowed("tab1", people.key) and ds.is_allowed("tab1", contacts.key)


def test_mail_and_teams_keep_their_own_approval():
    cal = ds.source_for_call("read_calendar", {})
    mail = ds.source_for_call("search_email", {})
    teams = ds.source_for_call("read_channel_messages", {})
    ds.allow_source("tab1", cal)
    assert not ds.is_allowed("tab1", mail.key)
    assert not ds.is_allowed("tab1", teams.key)
    assert ds.approval_key(mail) == mail.key


def test_group_card_names_all_three_sources():
    text = ds.prompt_for(ds.source_for_call("search_people", {}), "search_people", {})
    assert "Outlook calendar" in text["title"] and "Outlook contacts" in text["title"]


def test_denying_a_group_source_denies_all_three():
    cal = ds.source_for_call("read_calendar", {})
    people = ds.source_for_call("search_people", {})
    ds.deny_source("tab1", cal)
    assert ds.recently_denied("tab1", people.key)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/prompt_injection/test_data_sources.py -q`
Expected: FAIL (`approval_key` missing).

- [ ] **Step 3: Implement in `web/data_sources.py`**

Add to `Source`:

```python
    group_keys: tuple = ()  # approving this source approves all of these keys together
    group_label: str = ""
```

Below `_NATIVE_SOURCES`:

```python
_SCHEDULING = ("calendar", "people", "contacts")
_SCHEDULING_LABEL = "Outlook calendar, the people directory and Outlook contacts"
```

Replace `_native_source`:

```python
def _native_source(tool_name: str) -> Source | None:
    for skill_id, label in _NATIVE_SOURCES.items():
        if tool_name in shared.SKILL_TOOLS_MAP.get(skill_id, ()):
            grouped = skill_id in _SCHEDULING
            return Source(
                key=f"data:{label}", label=label, kind="data", flow_id=skill_id.removeprefix("m365-"),
                group_keys=tuple(f"data:{_NATIVE_SOURCES[s]}" for s in _SCHEDULING) if grouped else (),
                group_label=_SCHEDULING_LABEL if grouped else "",
            )
    return None
```

In `prompt_for`, in the `else` branch and the title use `shown = source.group_label or source.label` (keep the web branch on `source.label`):

```python
    else:
        shown_label = source.group_label or source.label
        action = (
            f"AI Gator wants to use {shown_label} (tool: {tool_name}). "
            "This stays allowed until you close this tab."
        )
    return {
        "title": f"Allow access to {source.group_label or source.label}?",
```

After `deny`:

```python
def approval_key(source: Source) -> str:
    return source.group_keys[0] if source.group_keys else source.key


def allow_source(context_id: str, source: Source) -> None:
    for key in source.group_keys or (source.key,):
        allow(context_id, key)


def deny_source(context_id: str, source: Source) -> None:
    for key in source.group_keys or (source.key,):
        deny(context_id, key)
```

- [ ] **Step 4: Update `_ask_source` in `web/agent_loop.py`**

Lock key `(context_id, data_sources.approval_key(source))`; `data_sources.allow(context_id, source.key)` becomes `data_sources.allow_source(context_id, source)`; `data_sources.deny(...)` becomes `data_sources.deny_source(context_id, source)`; status text uses `source.group_label or source.label`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/prompt_injection -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/data_sources.py web/agent_loop.py tests/prompt_injection/test_data_sources.py
git commit -m "feat: one approval card for calendar, people directory and contacts"
```

---

### Task 2: Timezone helpers

**Files:**

- Create: `web/skills/calendar/timezones.py`
- Test: `tests/test_calendar_timezones.py`

**Interfaces:**

- Produces: `WINDOWS_TO_IANA: dict[str, str]`; `zone(name: str) -> ZoneInfo | None`; `fmt_range(start: str, end: str, from_tz: str, to_tz: str) -> str | None`; `attendee_zones(gc, emails: list[str], day: str, win_tz: str) -> dict[str, dict]` returning `{email_lower: {"timezone": str, "working_hours": str}}` and `{}` on any error.

- [ ] **Step 1: Write failing tests**

```python
from zoneinfo import ZoneInfo

from skills.calendar import timezones as tz


def test_every_mapped_zone_loads():
    for win, iana in tz.WINDOWS_TO_IANA.items():
        ZoneInfo(iana)


def test_zone_accepts_windows_and_iana_names():
    assert tz.zone("Pacific Standard Time").key == "America/Los_Angeles"
    assert tz.zone("Europe/London").key == "Europe/London"
    assert tz.zone("No Such Zone") is None


def test_fmt_range_converts_and_flags_day_shift():
    out = tz.fmt_range("2026-11-02T09:00:00.0000000", "2026-11-02T09:30:00.0000000",
                       "Pacific Standard Time", "India Standard Time")
    assert out == "10:30 PM – 11:00 PM IST"
    late = tz.fmt_range("2026-11-02T20:00:00.0000000", "2026-11-02T20:30:00.0000000",
                        "Pacific Standard Time", "India Standard Time")
    assert late.endswith("(+1 day)")


def test_fmt_range_unknown_zone_is_none():
    assert tz.fmt_range("2026-11-02T09:00:00", "2026-11-02T09:30:00", "Pacific Standard Time", "Nope") is None


def test_attendee_zones_reads_working_hours():
    class GC:
        def post(self, path, body, **kw):
            return {"value": [{"scheduleId": "A@x.com", "workingHours": {
                "startTime": "08:00:00.0000000", "endTime": "17:00:00.0000000",
                "timeZone": {"name": "India Standard Time"}}}]}
    out = tz.attendee_zones(GC(), ["a@x.com"], "2026-11-02", "Pacific Standard Time")
    assert out["a@x.com"] == {"timezone": "India Standard Time", "working_hours": "8:00 AM – 5:00 PM"}


def test_attendee_zones_swallows_errors():
    class GC:
        def post(self, *a, **k):
            raise RuntimeError("boom")
    assert tz.attendee_zones(GC(), ["a@x.com"], "2026-11-02", "UTC") == {}
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_calendar_timezones.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `web/skills/calendar/timezones.py`**

Check first how `_tool_check_availability` (`tools.py` ~875) calls `getSchedule` (client method, body keys) and match it in `attendee_zones`. `fmt_range` parses with `datetime.fromisoformat(s.split(".")[0].rstrip("Z"))`, attaches `zone(from_tz)`, converts with `astimezone(zone(to_tz))`, formats `%I:%M %p` with leading zero stripped and the destination `tzname()`, appends `(+1 day)`/`(-1 day)` when the date differs. `WINDOWS_TO_IANA` covers: UTC, GMT Standard Time, W. Europe Standard Time, Central Europe Standard Time, Romance Standard Time, Central European Standard Time, E. Europe Standard Time, GTB Standard Time, FLE Standard Time (Europe/Kiev), Russian Standard Time, Turkey Standard Time, Israel Standard Time, Arabian Standard Time, Arab Standard Time, India Standard Time (Asia/Kolkata), Nepal Standard Time, Bangladesh Standard Time, SE Asia Standard Time, China Standard Time, Singapore Standard Time, Taipei Standard Time, Tokyo Standard Time, Korea Standard Time, AUS Eastern Standard Time, E. Australia Standard Time, New Zealand Standard Time, Pacific Standard Time, Mountain Standard Time, US Mountain Standard Time, Central Standard Time, Eastern Standard Time, US Eastern Standard Time (America/Indiana/Indianapolis), Atlantic Standard Time, Canada Central Standard Time, Hawaiian Standard Time, Alaskan Standard Time, E. South America Standard Time, Argentina Standard Time, SA Pacific Standard Time, Mexico Standard Time, South Africa Standard Time, Egypt Standard Time, W. Central Africa Standard Time, E. Africa Standard Time. Unknown Windows names return None from `zone` (caller falls back to the name).

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/calendar/timezones.py tests/test_calendar_timezones.py
git commit -m "feat: timezone helpers for attendee-local meeting times"
```

---

### Task 3: Timezone-aware `find_meeting_times`

**Files:**

- Modify: `web/skills/calendar/tools.py` (`find_meeting_times` TOOL_DEF ~243, `_tool_find_meeting_times` ~543)
- Test: `tests/test_calendar_timezones.py`

**Interfaces:**

- Consumes: `timezones.attendee_zones`, `timezones.fmt_range`.
- Produces: `_tool_find_meeting_times(attendees, date="", duration_minutes=30, max_suggestions=5, ignore_timezones=False)` returning `{date, duration_minutes, timezone, ignore_timezones, attendee_timezones, suggestions:[{start, end, confidence, timezone, attendee_local:{email: "9:00 AM – 9:30 AM PST"}}]}`.

- [ ] **Step 1: Write failing tests** (fake `get_cal_client` via monkeypatching `_m365.helpers.get_cal_client` the way `tests/test_calendar_invite_parsing.py` does; the fake `post` records the body)
  - every suggestion has `timezone`;
  - `ignore_timezones=True` puts `"activityDomain": "unrestricted"` in `timeConstraint`; default does not set it to unrestricted;
  - when `getSchedule` raises, suggestions still return, with `attendee_timezones == {}`.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** Call `attendee_zones` once for the requested day; build each suggestion's `attendee_local` with `fmt_range(start, end, win_tz, att_tz)` falling back to `f"{start[11:16]}-{end[11:16]} {win_tz}"` when it returns None. Add `ignore_timezones` boolean to the TOOL_DEF properties (description: "Set true when the user asks to ignore timezones / working hours") and to the handler signature. Update the TOOL_DEF description so the model states each slot in the user's timezone plus each attendee's local time.

- [ ] **Step 4: Run** `python -m pytest tests/test_calendar_timezones.py tests/test_calendar_invite_parsing.py -q` → PASS.

- [ ] **Step 5: Commit** — `feat: label meeting slots with every attendee's local time and add ignore-timezones option`.

---

### Task 4: `draft_calendar_event` replaces `create_calendar_event`

**Files:**

- Modify: `web/skills/calendar/tools.py` (TOOL_DEFS ~200-242, `_tool_create_calendar_event` 472-540, TOOL_STATUS ~420, TOOL_HANDLERS 1466)
- Modify: `web/skills/calendar/SKILL.md` (every `create_calendar_event` mention, and the "Event Draft" section lines ~161-192), `web/skills/aigator/SKILL.md:46`
- Modify: `tests/test_calendar_invite_parsing.py` (migrate `test_create_event_sends_html_body_when_tags_present`)
- Test: `tests/test_calendar_draft.py`

**Interfaces:**

- Consumes: `skills._drafts.create_draft(draft_type, params, preview)`; `_parse_email_list`; `timezones.attendee_zones`, `timezones.fmt_range`.
- Produces: tool `draft_calendar_event(subject, start, end, attendees, optional_attendees=None, body="", location="", teams=False, recurrence=None)` returning `{"_draft": "calendar-event", "data": {subject, start, end, timezone, attendees, optional_attendees, body, location, teams, recurrence, attendee_local, draft_id}, "_user_message": str}`. Draft params hold `subject, start, end, timezone, attendees, optional_attendees, body, location, teams, recurrence`.

- [ ] **Step 1: Write failing tests**
  - calling the tool never calls `post` on the fake client (assert the fake raises on any `post`);
  - returns `_draft == "calendar-event"` and a `draft_id` that `get_draft` finds with the same params;
  - HTML body is preserved, plain body is preserved;
  - `"create_calendar_event"` is not in `TOOL_HANDLERS` and `"draft_calendar_event"` is.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** Follow `_tool_email_open_compose` (`web/skills/email/tools.py:633`) for the return shape. Timezone is `get_user_win_tz()`. `attendee_local` maps each attendee email to `fmt_range(...)` using `attendee_zones` (empty when unavailable). `_user_message`: "Meeting draft ready. Press Open in Outlook to review and send it from there." Delete `_tool_create_calendar_event`; rename the TOOL_DEF, TOOL_STATUS ("\U0001f4c5 Drafting calendar event...") and handler. In `find_meeting_times` description replace "Call this BEFORE create_calendar_event" with "Call this BEFORE draft_calendar_event".

- [ ] **Step 4: Update SKILL.md.** Rewrite the "Event Draft" section: call `draft_calendar_event` directly (the draft card replaces the markdown preview); tell the user to press Open in Outlook to edit and send; state slots in the user's timezone plus each attendee's local time; if the user says to ignore timezones pass `ignore_timezones=true` to `find_meeting_times`. Replace the other `create_calendar_event` mentions and the `aigator/SKILL.md:46` row with `draft_calendar_event`. Confirm none remain: `grep -rn create_calendar_event web docs tests` should only show history docs.

- [ ] **Step 5: Run** `python -m pytest tests/test_calendar_draft.py tests/test_calendar_invite_parsing.py -q` → PASS.

- [ ] **Step 6: Commit** — `feat: meeting set-up creates an Outlook draft instead of sending invites`.

---

### Task 5: Open a `calendar-event` draft in Outlook

**Files:**

- Modify: `web/routes/drafts.py` (`open_draft_in_outlook`, gate at ~line 1057)
- Test: `tests/test_calendar_draft_route.py`

**Interfaces:**

- Consumes: draft params from Task 4.
- Produces: `POST /api/drafts/{draft_id}/open-in-outlook` returns `{"url": "<compose deeplink>"}` for `calendar-event`; helper `_calendar_compose_url(params: dict) -> str` in `web/routes/drafts.py`.

- [ ] **Step 1: Write failing tests** (pattern from `web/tests/test_outlook_native_hitl.py`: `TestClient(app)`, `get_csrf_token("testserver")`, `create_draft("calendar-event", params, preview)`)
  - 200 and `url` starts with `https://outlook.office.com/calendar/0/deeplink/compose` and contains encoded subject, `to=` with all attendees joined by `;`, `startdt`, `enddt`, `location`;
  - the draft status is `handed_off` afterwards and a second POST returns 409;
  - `POST /api/drafts/{id}/approve` on a `calendar-event` draft returns 400;
  - no Graph client is touched (monkeypatch `get_graph_client` to raise).

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** Add:

```python
def _calendar_compose_url(params: dict) -> str:
    from urllib.parse import quote
    q = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": params.get("subject", ""),
        "startdt": params.get("start", ""),
        "enddt": params.get("end", ""),
        "body": params.get("body", ""),
        "location": params.get("location", ""),
        "to": ";".join(params.get("attendees") or []),
    }
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in q.items() if v)
    return f"https://outlook.office.com/calendar/0/deeplink/compose?{query}"
```

Change the type gate to allow `calendar-event`; after `claim_for_handoff` (and its 409 handling) branch on `dtype == "calendar-event"`: build the URL, call `complete_handoff`, `_sync_task_draft_status` as the email path does, and return `{"url": url}` before any Graph code. The route already carries `dependencies=[Depends(verify_csrf)]`.

- [ ] **Step 4: Run** `python -m pytest tests/test_calendar_draft_route.py tests/test_csrf_route_inventory.py -q` → PASS.

- [ ] **Step 5: Commit** — `feat: hand calendar drafts to Outlook through a compose deeplink`.

---

### Task 6: `calendar-event` draft card in the chat UI

**Files:**

- Modify: `web/static/app.js` (`_injectDraftApprovalCard` at ~10853: config map, card HTML ~11062-11125, approve listener ~11158, open-in-outlook handler ~11285-11362)
- Test: `tests/calendar_draft_card.test.js`

**Interfaces:**

- Consumes: draft `data` from Task 4; `POST /api/drafts/{id}/open-in-outlook` from Task 5.

- [ ] **Step 1: Write failing JS test** (vm-extraction pattern of `tests/draft_rich_editor.test.js`): build a card for `calendar-event` data and assert the markup has a `gcc-open-outlook-btn` (or the existing open-in-outlook class), has no `gcc-approve-btn`, and contains the subject, the attendee emails and a per-attendee local time row.

- [ ] **Step 2: Run to verify failure** — `node tests/calendar_draft_card.test.js`.

- [ ] **Step 3: Implement.** Add a `'calendar-event'` config: `paneLabel '@outlook'`, a calendar icon, `service 'calendar'`, `customBody` rows (Subject, When with timezone, Attendees with `attendee_local`, Location, Teams meeting yes/no), and a flag so the footer renders a primary "Open in Outlook" button instead of the approve button. Guard `approveBtn.addEventListener` for a missing button. In the open-in-outlook handler show the button regardless of `window.gatorShell.isShell` for this type and fall back to `window.open(url, "_blank", "noopener")` when not in the shell.

- [ ] **Step 4: Run** the node test plus `node tests/draft_rich_editor.test.js` → PASS.

- [ ] **Step 5: Verify in the browser.** Start the app, trigger a draft (or inject via `_injectDraftApprovalCard` in devtools), confirm the card shows and the button opens the compose URL. Report if the UI cannot be exercised.

- [ ] **Step 6: Commit** — `feat: calendar draft card with Open in Outlook`.

---

### Task 7: Transcript backend — instant list and per-row resolve

**Files:**

- Modify: `web/skills/m365-teams/scripts/transcript_recording.py` (keep `resolve_recordings_from_chat` unchanged; other code and tests depend on it)
- Modify: `web/routes/teams.py` (~4380-4568)
- Test: `tests/test_transcript_resolve.py`, `tests/test_teams_transcripts_route.py`

**Interfaces:**

- Produces:
  - `list_recordings_from_chat(chat_id: str) -> list[RecordingInfo]`: scan only, `drive_id=""`, `item_id=""`, `web_url=share_url`.
  - `resolve_share(share_url: str) -> dict`: `{"drive_id","item_id","web_url","error"}` where `error` is `None`, `"expired"` (status 404/410), `"auth"` (401/403) or `"failed"`; successes cached by share URL; the real status is logged with `logging`.
  - `GET /api/recordings/resolve?share_url=<url>` returns the `resolve_share` dict. GET, so no CSRF.
  - `/api/teams/chats/{chat_id}/recordings` rows gain `share_url`.

- [ ] **Step 1: Write failing tests**
  - `list_recordings_from_chat` never calls `_resolve_share_to_drive_item` (patch it to raise);
  - `resolve_share` maps an exception with `status_code=404` to `error="expired"`, 403 to `"auth"`, other to `"failed"`, success to ids with `error=None`, and a second call for the same URL does not call Graph again;
  - the `/recordings` route returns rows with `share_url` and does not call the resolver;
  - the resolve route rejects a `share_url` that is not an https `sharepoint.com` URL (400), so it cannot be used as an open Graph proxy.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement** per the interfaces. The resolve route reuses `_SHARE_HREF_RE`'s host rule (`https://…sharepoint.com`). Add `_tx_list_chat` as a patchable name next to the existing `_tx_*` names.

- [ ] **Step 4: Run** `python -m pytest tests/test_transcript_resolve.py tests/test_teams_transcripts_route.py web/tests/test_teams_transcript_detection.py web/tests/test_meeting_transcript_tools.py tests/test_transcript_review_followups.py -q` → PASS.

- [ ] **Step 5: Commit** — `feat: list meeting recordings instantly and resolve each share link on demand`.

---

### Task 8: Transcript panel — async rows and a visible button label

**Files:**

- Modify: `web/static/third-pane.js` (`_openTranscriptsPanel` ~1742, `_renderTranscriptsList` ~1780, `_buildRecordingRow` ~1806, `_buildTranscriptRow` ~1874, `_renderCalendarTranscriptCard` ~2026, header action `tp-teams-transcripts` ~6653)
- Test: `tests/transcripts_panel.test.js`

**Interfaces:**

- Consumes: `/recordings` rows with `share_url` and `GET /api/recordings/resolve` from Task 7.

- [ ] **Step 1: Write failing JS test:** with a fake `fetch`, `_renderTranscriptsList` creates a row for every recording before any resolve call finishes; a resolve response with `error: "expired"` renders text containing "expired" and not "sign in"; `error: "auth"` renders the sign-in text; at most 4 resolves run at once; `_renderCalendarTranscriptCard` markup contains a visible text label ("Transcripts") beside the icon.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** Render all rows immediately from the list. Resolve rows with a small worker pool (4), newest first, resolving a row when it is rendered. Fetch the header only for rows in view (IntersectionObserver, fall back to fetching on expand). Cache the rendered list per chat id so reopening paints instantly. Add the text label to the calendar popover button and the Teams header action; the final wording and placement are iterated with the user after the first working version.

- [ ] **Step 4: Run** the node test; open the panel in the browser with a real meeting chat and confirm rows paint first.

- [ ] **Step 5: Commit** — `feat: transcripts panel paints rows immediately and explains rows that cannot load`.

---

### Task 9: Verification

- [ ] **Step 1:** Run `python -m pytest tests -q` and the JS tests under `tests/*.test.js`; compare against `main` for pre-existing failures.
- [ ] **Step 2:** On a real tenant, check: `getSchedule` returns working hours for colleagues; the compose deeplink keeps all attendees, the HTML body and the Teams toggle; old recording rows that showed "sign in" now report their real cause.
- [ ] **Step 3:** Record any deviations and open follow-ups.

---

## Self-Review

- Spec 1/1a: Tasks 1 and 4. Spec 2: Tasks 2 and 3. Spec 3: Tasks 4, 5, 6. Spec 4: Task 8. Spec 5: Tasks 7 and 8 (history depth: the scan window stays at 500 messages and the 5-transcript cap is unchanged; the per-row cause message makes the limit visible). Spec 6 tests: each task lists its own.
- Names are consistent across tasks: `draft_calendar_event`, `calendar-event`, `approval_key`, `allow_source`, `list_recordings_from_chat`, `resolve_share`, `fmt_range`, `attendee_zones`.
- No `/me/events` POST remains for meetings; the new route stays under the existing CSRF-protected endpoint and the new resolve route is a GET.
