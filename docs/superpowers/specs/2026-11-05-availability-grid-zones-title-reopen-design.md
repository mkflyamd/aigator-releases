# Availability grid: attendee time zones, Title and Message, reopen in Outlook

Branch: `feat/calendar-draft-and-transcripts`

## Goals

1. The availability grid shows what the picked slot is in each attendee's time zone, as the draft card does.
2. The grid has Title and Message, and Open in Outlook carries them.
3. After the Outlook window is closed, the Open in Outlook button works again.

## 1. Time zones in the grid

- `_tool_show_availability_grid` calls `timezones.attendee_zones` once for the people on the grid and adds each person's zone name to `grid.people[i].timezone`. People added later through "+ Add person" get their zone from the `/api/calendar/availability-days` response, which returns a `zones` map next to `days`.
- New route `POST /api/calendar/slot-zones` (CSRF protected). Request: `start`, `end`, `timezone` (the grid zone) and `zones` (`{email: zone name}`). It calls `timezones.fmt_range` per person, groups people by identical result, and returns `[{"label": "11:00 AM – 11:30 AM CST", "people": ["Aswin", "Tej"]}]`. It makes no Graph call.
- Picking a slot requests this and shows the lines under the chosen-slot text, one per zone, for example `11:00 AM – 11:30 AM CST · Aswin, Tej`. People whose zone is unknown are left out. The grid zone's own line is omitted because the chosen-slot text already shows it.
- Labels come from `fmt_range`, so they match the draft card, including `(+1 day)`.

## 2. Title and Message

- The grid card gets a Title line field and a Message text field, built like the draft card's `_jiraEditRow` fields.
- `show_availability_grid` gains optional `subject` and `body` parameters. They go into the grid payload and pre-fill the fields; the user can edit them.
- Open in Outlook, one-off without optional attendees: `_availabilityGridComposeUrl` adds `subject` and `body` query parameters.
- Open in Outlook, repeating or with optional attendees: `GridSeriesRequest` gains `subject` and `body`, passed to `_calendar_event_payload`.
- "Use this time" adds the Title and Message to the reply sent to the model, so the final draft card keeps them.

## 3. Reopen after the Outlook window closes

- `outlook-pane:open-compose-window` sends `outlook-pane:compose-closed` with the original URL to the calling window when the compose window closes. `preload.js` exposes `onOutlookComposeClosed(callback)`, which returns an unsubscribe function.
- Draft card (`app.js` near line 12531) and grid button: after opening, the card remembers the URL. When the close signal for that URL arrives, the button goes back to enabled "Open in Outlook ↗" and reopens the stored URL with no server call, so no second draft is created.
- Send invite stays disabled after any hand-off.
- The one-off path reopens Outlook's compose link, which opens a new invite. Its tooltip reads: "Opens a new invite. If you already sent it in Outlook, don't send it again."
- Without the Electron shell there is no close signal, so the button is re-enabled right after the click.
- The grid's current stuck "Draft opened in Outlook" state is replaced by the same behaviour.

## Tests

- Python: `slot-zones` grouping and unknown-zone handling; `zones` in the grid payload and the add-person response; `subject` and `body` reaching `_calendar_event_payload` through `grid-draft-series`; the new route is in the CSRF inventory.
- JS: compose URL contains `subject` and `body`; zone lines render under the chosen slot; the button re-enables on the close signal and reopens the stored URL.
