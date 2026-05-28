---
name: calendar
description: "Microsoft 365 Calendar — read events, check availability, schedule meetings, create OOO."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
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
  🟢 = Free  🔴 = Busy  🟡 = Tentative  ⭐ = Mutual free slot
- Format example:
  📅 Apr 22 — Mutual Availability (PST)
  8 AM  [🔴 Ram][🔴 You]
  9 AM  [🔴 Ram][🔴 You]
  10 AM [🟢 Ram][🟢 You] ⭐ MEET HERE
  11 AM [🔴 Ram][🟡 You]
- Lead with a one-line summary of the best mutual slot (e.g. "Only 1 mutual free slot today: 10–10:30 AM PST").
- Bold/highlight the recommended slot — never bury it.
- Tentative (🟡) means the slot may free up — flag it but don't call it fully available.
- All times must be in the user's local timezone (PST/PDT) — never raw UTC.

## Pre-flight Checks (run BEFORE any calendar tool call)

These three checks are mandatory gates. Do not call create_calendar_event, check_availability, or find_meeting_times until all applicable checks pass.

### 1. Day-of-week ↔ Date Cross-validation

Whenever the user names a meeting by day (e.g. "Thursday", "next Monday"):
1. Resolve the target date from today's date (injected in the system prompt as YYYY-MM-DD).
2. Compute the day-of-week for that resolved date.
3. If the computed day does not match the day the user named, **stop and surface the conflict** before proceeding:
   > "Just to confirm — May 8 is actually a Friday. Did you mean Thursday May 7 or Friday May 8?"
4. Wait for the user to clarify. Never silently proceed with a mismatched day/date.

### 2. Attendee Disambiguation

Determine the attendee input type first, then act accordingly:

| Input type | Example | Action |
|---|---|---|
| Direct email | `ram@company.com` | Use as-is. Skip `search_people`. |
| @mention | `@Ram Iyer` | Treat as already resolved — use the identity the app surfaces for that mention. Skip `search_people`. |
| Name only | `Ram` | Call `search_people`. Disambiguate if multiple results (see below). |

**When search_people returns multiple matches:**
1. Present all options and wait for explicit user confirmation — never auto-select:
   > "I found multiple people named Ram:
   >  1. Ram Iyer — ram.iyer@company.com (Engineering)
   >  2. Ram Patel — ram.patel@company.com (Finance)
   >  Which one did you mean?"
2. Once the user confirms, cache that resolved email for the rest of the conversation — do not re-resolve on retries, which could silently pick a different person.
3. If exactly one result matches, proceed without asking.

### 3. Timezone-aware Datetime

Before passing start/end datetimes to any calendar tool:
1. Confirm the user's local timezone if it is not already known (e.g. "Just to confirm — are you scheduling in Pacific Time?").
2. Express all datetimes with an explicit UTC offset or IANA timezone (e.g. `2026-05-08T14:00:00-07:00` for PDT). Never pass a naive datetime without an offset.
3. All times displayed back to the user must be in their local timezone — never raw UTC.

---

## Calendar Scheduling Workflow

- "Find a time" / "Schedule a meeting with X" → call find_meeting_times first, present the available slots to the user, ask them to confirm the slot + subject + attendees. Once the user confirms, show the **Event Draft** (see below) before calling create_calendar_event.
- "Is X available?" → call check_availability (for free/busy view) or find_meeting_times (to get concrete open slots).
- "Cancel / delete meeting" → call read_calendar first to get the event ID, confirm the right event with the user, then call delete_calendar_event. You MUST call delete_calendar_event and receive `deleted=true` before telling the user the event was deleted. If read_calendar cannot find the event (404 / error), tell the user you could not locate it — do not assume it was already deleted.
- "I'm OOO / taking PTO" → call create_ooo_event. Ask for dates and who to notify if not specified.
- Always resolve names to emails via search_people before any calendar tool that takes email addresses.
- NEVER say "I don't have a tool to create calendar events" — you DO have create_calendar_event. Use it.

## Tool Result Guardrails

- **Never claim success without calling the tool and confirming the response.** The ONLY evidence of a successful delete is `deleted=true` in the `delete_calendar_event` response. A 404 on `read_calendar` or `get_calendar_event_detail` does NOT mean the event was deleted — it may be a stale ID, a sync delay, or a prior partial failure. If you cannot read the event, tell the user you could not find it and ask them to verify in Outlook.
- Always inspect the tool response before claiming success. Confirm flags like `deleted`, `updated`, `forwarded`, `responded`, or `created` are `true`, and check for `error`, `organizer_required`, or `series_master`.
- If a tool returns `deleted=false`, `updated=false`, or includes an `error`, surface that to the user and propose the next step (retry with the correct occurrence ID, decline instead, edit in Outlook, etc.). Never mark the task done when the tool reports failure.
- **Never fabricate a success message.** If a tool was not called or its response does not contain the expected success flag, say so honestly.

## Recurrence Handling

- When the user requests a repeating meeting (“every day”, “recurring daily”, “weekdays only”, etc.), clarify the cadence **before** calling a tool. Confirm pattern type (daily/weekly/monthly), interval, exact weekdays (if weekly), and end condition (no end, end date, or number of occurrences).
- Once confirmed, pass a full Graph recurrence object into `create_calendar_event` or `update_calendar_event`. Example:

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
- Confirm the new date/time and any content tweaks with the user, then populate the **Event Draft** with the retrieved attendee lists (required vs optional) before calling `create_calendar_event`.

## Rescheduling an Existing Event

1. Use `read_calendar` (and `get_calendar_event_detail` if needed) to let the user pick the exact meeting. For recurring series, choose the specific occurrence ID from the `instances` list.
2. Confirm the new time range, location, and any other changes.
3. Render a concise **Update Summary**: list the before/after time, highlight attendee changes, and confirm the user wants to send updates to everyone.
4. Call `update_calendar_event` with the new start/end (and any other fields). Default `send_updates` to `All` unless the user explicitly says otherwise.
5. After the tool runs, acknowledge success and remind the user that attendees receive an update rather than a fresh invite.

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

## Event Draft (show before every create_calendar_event call)

Before calling create_calendar_event, always render a structured draft and wait for explicit user approval. Do not send until the user says "send", "looks good", "go ahead", or equivalent.

Format the draft exactly like this:

---
📅 **[Title]**

🕐 **When:** Mon May 8, 2:00 – 3:00 PM PDT
🔁 **Recurrence:** None *(or e.g. "Weekly, every Monday")*
📍 **Location:** *(room, address, or blank)*
🔗 **Teams link:** Auto-generated *(or "None")*

👥 **Required:** Name — email@company.com
👤 **Optional:** Name — email@company.com *(or "None")*

📝 **Body:**
[Full meeting body / agenda text]

---
*Anything to change before I send this?*

Rules:
- Every field must be present. If a value is unknown or not provided, show it as `—` so the user can spot gaps.
- Recurrence: spell it out plainly — "Weekly, every Tuesday until Jun 30" — never leave it as a raw API parameter.
- Teams link: if the tool will auto-generate one, say "Auto-generated"; if not applicable, say "None".
- Required vs Optional: list each attendee on their own line with resolved name and email. Never collapse into a comma list.
- After the user requests a change (e.g. "make it 30 min", "add Priya as optional"), update the draft in-place and re-render the full block. Do not call create_calendar_event until the user explicitly approves the final draft.
