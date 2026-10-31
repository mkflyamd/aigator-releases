# Calendar meeting set-up: native tools, timezone-aware slots, draft card

## Goal

Make AI Gator's meeting set-up faster and safer:

1. One approval click for a meeting set-up instead of one card per data source.
2. Slots are timezone-aware for every attendee, with an option to ignore timezones.
3. The meeting is a draft the user can edit in Outlook, including the Scheduling Assistant, before anything is sent.

The custom FullCalendar pane (`web/static/third-pane.js`, `/api/calendar/events`) is unchanged.

## 1. Native calendar tools

The calendar skill (`web/skills/calendar/tools.py`) is already native. Keep `read_calendar`, `find_meeting_times` and `check_availability`. Replace `create_calendar_event`, which calls `POST /me/events` and sends invites immediately, with `draft_calendar_event`, which creates a `calendar-event` draft and sends nothing.

- The agent has no tool that calls `POST /me/events` for a meeting. Invites go out only when the user presses Send in Outlook.
- `create_ooo_event`, `update_calendar_event`, `delete_calendar_event`, `add_calendar_attendees` and `respond_calendar_event` keep their current confirmation rules.

## 1a. One-click approvals

The prompts are per-tab data-source cards (`web/data_sources.py`, `agent_loop._ask_source`), one each for calendar, people, contacts, mail and Teams.

- Approving the Outlook calendar, the people directory or Outlook contacts card allows all three for the tab, in one card.
- Mail and Teams keep their own cards.
- The admin `blocked_data_flows` policy still applies.

## 2. Timezones

- `find_meeting_times` returns every slot with an explicit timezone label and renders it in each attendee's local time.
- Each attendee's timezone and working hours come from `getSchedule` (`workingHours.timeZone`).
- Default: respect attendee working hours. When the user says to ignore timezones, search with `activityDomain: unrestricted`.
- The default timezone is the user's own mailbox timezone, not `America/Los_Angeles`.

## 3. Calendar draft card

- `draft_calendar_event` stores a `calendar-event` draft in `skills/_drafts` with subject, body, start, end, timezone, attendees and Teams flag.
- The card shows title, time in each attendee's timezone, and attendees. Its only button is "Open in Outlook".
- The existing `open_draft_in_outlook` route (`web/routes/drafts.py`) handles `calendar-event`. It builds the Outlook calendar compose deeplink without any Graph call and returns the URL. The route keeps `dependencies=[Depends(verify_csrf)]`.
- The renderer opens the URL with `gatorShell.openOutlookDraft`. The draft then moves to `handed_off`, using the existing claim and complete handoff helpers.
- The draft type is provider-neutral so a Google Calendar handoff can be added separately.

## 4. Transcript button discoverability

The meeting transcript button is an icon-only `speaker_notes` button, so users don't find it. Make it explicit with a visible text label.

- Surfaces: the calendar event popover header (`_renderCalendarTranscriptCard`, mounted in `third-pane.js` next to the pin button) and the Teams meeting chat header (`tp-teams-transcripts`).
- Both open the same `_openTranscriptsPanel`, so the label and placement should be consistent.
- Placement and wording are decided when this item is built, by iterating on the UI with the user.

## 5. Transcript list: loading, errors, depth

Three problems in the transcripts list (`_renderTranscriptsList`, `GET /api/teams/chats/{id}/recordings`):

- **Slow, all-or-nothing load.** The backend resolves every recording's SharePoint share URL to a drive/item id one after another before it returns anything. The client then builds rows serially, and each row fetches its transcript list and then a header that downloads the full VTT. The list shows only "Loading recordings…" until all of that finishes.
- **Misleading "sign in (Settings)" text.** A row shows it whenever the share URL could not be resolved (`resolve_recordings_from_chat` swallows every exception into empty ids). The same session loads the newer rows, so the cause is not sign-in. Log the real Graph status, then show a message per cause (recording expired or deleted vs. sign-in needed).
- **History depth.** The chat scan reads at most 500 messages (`_MAX_SCAN_PAGES` 10 x pageSize 50), so a busy meeting chat can hide older recordings. Transcripts per recording are capped at 5 (`RECURRING_OCCURRENCES_CAP`).

Direction:

- `/recordings` returns the Skype-derived rows immediately (date, title, has_transcript, share URL). Drive/item resolution moves to a per-row call, cached by share URL.
- The client renders every row at once and fills each row in with bounded concurrency, visible rows and newest first.
- The duration/speaker header is fetched only when a row is visible.
- Reopening the panel reuses the cached list.

## 6. Tests

- `draft_calendar_event` never calls `/me/events`.
- One approval of the calendar, people or contacts card allows all three for that tab; mail and Teams stay separate.
- Every slot carries a timezone label.
- "Ignore timezones" switches `activityDomain` to `unrestricted`.
- The deeplink keeps subject, body, times, attendees and Teams flag.
- Approving a `calendar-event` draft is rejected.
- Opening a draft marks it `handed_off` and a second open returns 409.
- `tests/test_csrf_route_inventory.py` passes without baseline changes.
- The transcript button renders a visible text label on the calendar popover and the Teams meeting header.
- `/recordings` returns without any Graph share-URL resolution; a row whose resolution fails shows a cause-specific message, not the sign-in text.
- The transcripts panel paints all rows before any per-row fetch completes.

## Open items to verify on a real tenant

- `getSchedule` returns working hours for colleagues.
- The compose deeplink keeps all attendees and the Teams toggle.

## Out of scope

- Google Calendar draft handoff (separate build, via `workspace-mcp`).
- Replacing the custom calendar pane with the native Outlook calendar. Planned as a later phase; it starts with a spike on the real OWA calendar to confirm the event URL and id format, the event card markup, and that injected buttons are allowed, and the Transcripts button is the first parity item.
