---
name: calendar
description: 'Microsoft 365 Calendar — read events, check availability, schedule meetings, create OOO.'
metadata:
  author: Mayuresh Kulkarni
  version: '1.0'
  format: agentskills-1.0
---

# Calendar Formatting

- NEVER use markdown pipe tables for calendar events or availability — they collapse into unreadable single lines in chat UIs.
- Instead, list each event as a compact block, one per line group:
  **Time** — Event name
  Organizer · Location (if any)
- Lead with a one-line summary (e.g. "6 meetings tomorrow, morning is free.").
- Call out conflicts or OOO notes as a separate bullet.
- **Time formatting (applies everywhere, including any table):** Never display raw ISO strings (e.g. `2026-05-08T14:00:00-07:00`). Always render times as human-readable: `2:00 PM`, `2:00 – 3:00 PM`, or `Thu May 8, 2:00 PM PDT`. Dates as `Mon May 8` or `May 8`. Duration as `1 hr` / `30 min`.

## Availability Display (check_availability results)

- NEVER use a markdown table. Use a visual timeline — one row per hour, emoji blocks for status:
  🟢 = Free 🔴 = Busy 🟡 = Tentative ⭐ = Mutual free slot
- Format example:
  📅 Apr 22 — Mutual Availability (PST)
  8 AM [🔴 Ram][🔴 You]
  9 AM [🔴 Ram][🔴 You]
  10 AM [🟢 Ram][🟢 You] ⭐ MEET HERE
  11 AM [🔴 Ram][🟡 You]
- Lead with a one-line summary of the best mutual slot (e.g. "Only 1 mutual free slot today: 10–10:30 AM PST").
- Bold/highlight the recommended slot — never bury it.
- Tentative (🟡) means the slot may free up — flag it but don't call it fully available.
- All times must be in the user's local timezone (PST/PDT) — never raw UTC.

## Pre-flight Checks (run BEFORE any calendar tool call)

These three checks are mandatory gates. Do not call draft_calendar_event, check_availability, or find_meeting_times until all applicable checks pass.

### 1. Day-of-week ↔ Date Cross-validation

Whenever the user names a meeting by day (e.g. "Thursday", "next Monday"):

1. Resolve the target date from today's date (injected in the system prompt as YYYY-MM-DD).
2. Compute the day-of-week for that resolved date.
3. If the computed day does not match the day the user named, **stop and surface the conflict** before proceeding:
   > "Just to confirm — May 8 is actually a Friday. Did you mean Thursday May 7 or Friday May 8?"
4. Wait for the user to clarify. Never silently proceed with a mismatched day/date.

### 2. Attendee Disambiguation

Determine the attendee input type first, then act accordingly:

| Input type                    | Example                      | Action                                                                                                                                                                                               |
| ----------------------------- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Direct email                  | `ram@company.com`            | Use as-is. Skip `search_people`.                                                                                                                                                                     |
| @mention                      | `@Ram Iyer`                  | Treat as already resolved — use the identity the app surfaces for that mention. Skip `search_people`.                                                                                                |
| Name only                     | `Ram`                        | Call `search_people`. Disambiguate if multiple results (see below).                                                                                                                                  |
| Name seen in a chat or thread | `James` (in the pinned chat) | Read the chat or thread first, then call `search_people` after it returns. People from what you read (`participants`) come first; if `resolved_from_context` is set, use that person without asking. |

**When search_people returns multiple matches:**

1. Present all options and wait for explicit user confirmation — never auto-select:
   > "I found multiple people named Ram:
   >
   > 1. Ram Iyer — ram.iyer@company.com (Engineering)
   > 2. Ram Patel — ram.patel@company.com (Finance)
   >    Which one did you mean?"
2. Once the user confirms, cache that resolved email for the rest of the conversation — do not re-resolve on retries, which could silently pick a different person.
3. If exactly one result matches, proceed without asking.

### 3. Timezone-aware Datetime

Before passing start/end datetimes to any calendar tool:

1. Confirm the user's local timezone if it is not already known (e.g. "Just to confirm — are you scheduling in Pacific Time?").
2. Express all datetimes with an explicit UTC offset or IANA timezone (e.g. `2026-05-08T14:00:00-07:00` for PDT). Never pass a naive datetime without an offset.
3. All times displayed back to the user must be in their local timezone — never raw UTC.

---

## Calendar Scheduling Workflow

- "Find a time" / "Schedule a meeting with X" (any meeting, one-off or recurring) → once the attendees are resolved, call show_availability_grid (the day or days they named, else its default of the next ten working days, up to 20 if you pass dates; pass the meeting length, and `recurrence` when the user named a cadence). It shows an Outlook-style card where the user clicks any time (everyone-free columns are highlighted, but they may pick a time where someone is busy), and the pick arrives as their next message ("Let's do Thursday, Nov 5, 10:00 AM - 10:30 AM (Pacific Standard Time)."). The card has a One time / repeat selector with Outlook's recurrence options (daily, weekly on chosen days, monthly by day or by "first Sunday", yearly, and an end by date, after N occurrences or never), and the pick message states the user's final choice ("This is a one-time meeting, not recurring." or "Make it recurring every 2 weeks on Monday and Wednesday, ending after 10 occurrences."): follow it exactly, drafting a single event for one time, or the matching Graph recurrence object for a repeat (startDate is the first meeting: the picked day, or the date the pick message gives when it says the picked day is not on the repeat, at the picked time, with no question to the user; "ending by" is the range endDate). After calling it, end your turn with one short sentence and do not also call ask_user. Never ask the user to pick a day or time from slots you made up. Once the pick arrives, call draft_calendar_event (see **Event Draft** below), using only the required and optional attendees listed in the pick message (the user may have added or removed people or marked some optional in the grid, so never carry over anyone from earlier in the chat). If show_availability_grid fails, call find_meeting_times (one call per candidate date) and offer the real slots with `ask_user`, recommended first, each option's description carrying the slot's `availability` line exactly as returned, then each attendee's local time.
- "Is X available?" → call check_availability (for free/busy view) or find_meeting_times (to get concrete open slots).
- "Cancel / delete meeting" → call read_calendar first to get the event ID, confirm the right event with the user, then call delete_calendar_event. You MUST call delete_calendar_event and receive `deleted=true` before telling the user the event was deleted. If read_calendar cannot find the event (404 / error), tell the user you could not locate it — do not assume it was already deleted.
- "I'm OOO / taking PTO" → call create_ooo_event. Ask for dates and who to notify if not specified. When people are to be notified, the invite appears as an approval card; do not say it was sent until the user approves it.
- Always resolve names to emails via search_people before any calendar tool that takes email addresses.
- NEVER say "I don't have a tool to create calendar events" — you DO have draft_calendar_event. Use it.

## Tool Result Guardrails

- **Never claim success without calling the tool and confirming the response.** The ONLY evidence of a successful delete is `deleted=true` in the `delete_calendar_event` response. A 404 on `read_calendar` or `get_calendar_event_detail` does NOT mean the event was deleted — it may be a stale ID, a sync delay, or a prior partial failure. If you cannot read the event, tell the user you could not find it and ask them to verify in Outlook.
- Always inspect the tool response before claiming success. Confirm flags like `deleted`, `updated`, `forwarded`, `responded`, or `created` are `true`, and check for `error`, `organizer_required`, or `series_master`.
- If a tool returns `deleted=false`, `updated=false`, or includes an `error`, surface that to the user and propose the next step (retry with the correct occurrence ID, decline instead, edit in Outlook, etc.). Never mark the task done when the tool reports failure.
- **Never fabricate a success message.** If a tool was not called or its response does not contain the expected success flag, say so honestly.

## Recurrence Handling

- When the user requests a repeating meeting (“every day”, “recurring daily”, “weekdays only”, etc.), settle the cadence from the request: pattern type (daily/weekly/monthly), interval, exact weekdays (if weekly), and end condition (no end, end date, or number of occurrences). Use a sensible default for anything not stated (weekly, 30 min, no end) and say so. Ask only about a cadence detail you cannot default.
- For a weekly series, offer the weekday and time of the next occurrence from real open slots (see **Calendar Scheduling Workflow**) and note that it repeats.
- Once confirmed, pass a full Graph recurrence object into `draft_calendar_event` or `update_calendar_event`. Example:

  ```json
  {
    "pattern": { "type": "daily", "interval": 1 },
    "range": { "type": "noEnd", "startDate": "2026-05-07" }
  }
  ```

- Never guess at the recurrence rule. If the request is ambiguous (“daily” without specifying weekends), ask a follow-up question.
- If Graph rejects the recurrence update, surface the error and either adjust the pattern or hand the user a manual Outlook/Teams fallback — never claim success on failure.

## Event Detail Lookup

- Use `get_calendar_event_detail` after `read_calendar` whenever you need the attendee list, online meeting link, or body text for a specific event.
- Set `include_body=true` only if you need the full HTML body (for cloning or editing the agenda); otherwise rely on `body_preview`.
- The tool returns required and optional attendees separately. Reuse those lists when drafting follow-up sessions or migrations so the user never has to retype addresses.

## Forwarding / Sharing a Calendar Invite

"Forward this to X" / "Send the invite to X" / "Invite him/her" on an **existing** event:

1. Call `read_calendar` to get the event and its `id`.
2. (Optional) Call `get_calendar_event_detail` if you need to confirm current attendees before adding new people.
3. Resolve the recipient via `search_people` (apply attendee disambiguation rules above).
4. Confirm with the user before adding:
   > "Add **[Recipient Name]** to **[Event Title]** ([date/time]) as a required attendee? They'll receive a calendar invite and appear in your attendee list."
5. Once confirmed, call `forward_calendar_event` with the `event_id` and resolved email(s).
   - The tool attempts a Graph PATCH with `sendUpdates=All` so the attendee is added to the meeting and receives a real invite.
   - If Graph refuses to add the attendee (e.g. you're not the organizer), the tool falls back to the legacy `/forward` email flow and tells the user that the person won't show up in the attendee list.
   - If they are already an attendee, the tool will tell you — do not add them again.
6. Do NOT use `email_open_compose`, `send_email`, or the Graph `/forward` action directly — rely on `forward_calendar_event` so we only fall back to `/forward` when Graph blocks a proper attendee update.

## Cloning / Follow-up Sessions

- Use `read_calendar` to surface the original event and its `event_id`.
- Call `get_calendar_event_detail` to pull required and optional attendees, location, online meeting info, and the existing agenda text. When the source event is a series master, use the returned `instances` list to grab the right occurrence ID before cloning.
- Confirm the new date/time and any content tweaks with the user, then call `draft_calendar_event` with the retrieved attendee lists (required vs optional).

## Rescheduling an Existing Event

1. Use `read_calendar` (and `get_calendar_event_detail` if needed) to let the user pick the exact meeting. For recurring series, choose the specific occurrence ID from the `instances` list.
2. Confirm the new time range, location, and any other changes.
3. Call `update_calendar_event` with the new start/end (and any other fields). Default `send_updates` to `All` unless the user explicitly says otherwise. `attendees` and `optional_attendees` are each the complete list for that type, so include everyone who should stay. Leave one out entirely and the tool keeps that type as it is, along with rooms. The card lists anyone being removed.
4. The tool does not change the event. It shows an approval card with the before/after time, the attendee changes, whether it is this occurrence or the whole series, and who is notified. Tell the user the update is ready and that nothing changes until they press **Send update**. Never say the meeting was already updated.
5. If the user wants to add or remove people, ask them to tell you in chat and call the tool again, or to press **Open in Outlook** and edit the event there.

## Skipping One Occurrence of a Series

- Call `get_calendar_event_detail` to determine whether the signed-in user is the organizer (`organizer_is_self`). If the event is a series master, use the returned `instances` array to pick the specific occurrence ID for the date the user mentioned — never operate on the series master when the request is “today only” or similar.
- If the user **is** the organizer, call `delete_calendar_event` with the occurrence’s `event_id` (optionally include a short comment, which Graph sends to attendees). Graph will cancel only that instance and keep the rest of the series intact. The tool will refuse if `isOrganizer` is false, or if you pass the series master ID without explicitly asking to delete the whole series.
- If the delete tool responds with `organizer_required`, `series_master`, or `deleted=false`, explain the limitation and offer to decline the occurrence or ask the organizer to handle it. Re-run with the correct occurrence ID from `instances` if available.
- If the user is **not** the organizer, use `respond_calendar_event` with `response="decline"` (and `send_response=true` unless the user says otherwise) to decline just that instance on their own calendar.
- Always confirm the plan with the user first (e.g. “Cancel today’s occurrence for everyone?” vs “Decline just for you?”) and summarize the outcome after the tool call.

### Deleting an Entire Recurring Series

- Confirm the user truly wants to remove every future occurrence for all attendees.
- Pass the series master `event_id` (or any occurrence ID — the tool will resolve to the series master automatically) along with `delete_series=true` to `delete_calendar_event`.
- The tool will delete the series and send cancellations to all attendees. Only claim success if the response contains `deleted=true` and `series_deleted=true`.
- If Graph returns `organizer_required`, you cannot remove the series — offer to draft a message asking the organizer to handle the cancellation.

## Event Draft (draft_calendar_event)

Once the user confirms the slot, subject and attendees, call draft_calendar_event directly. It shows a draft card and sends nothing; the user presses **Send invite** to create the meeting and send the invites, or **Open in Outlook** to review, edit and send it from a new-event window. Do not render a markdown draft block and do not ask for a second confirmation.

Rules:

- Fill every field you know: subject, start, end, required and optional attendees, location, recurrence and an HTML body.
- Every draft gets a Teams meeting link automatically, including in-person meetings, so people can share screens. Do not ask about it or mention it as optional. If the user wants it removed, tell them to press **Open in Outlook** and remove it there.
- Recurrence: spell it out plainly in your reply ("Weekly, every Tuesday until Jun 30") and pass the Graph recurrence object.
- After the card appears, tell the user the meeting is not sent yet, that they can edit the title and message right on the card, that Send invite sends it as shown, and that Open in Outlook lets them add attendees or change anything else first.
- For a recurring draft, Open in Outlook creates the whole series as an unsent draft in Outlook, because Outlook's new-event link cannot carry a repeat. Tell the user to press Send there. Send invite in the card still creates and sends the whole series.
- If the user asks for a change, call draft_calendar_event again with the updated values.

## Timezones

- find_meeting_times returns each slot with its timezone and each attendee's local time (`attendee_local`). State the slot in the user's timezone and add each attendee's local time, flagging attendees whose slot falls outside their working hours or on another day.
- By default slots respect attendee working hours. If the user says to ignore timezones or working hours, call find_meeting_times with `ignore_timezones=true`.
