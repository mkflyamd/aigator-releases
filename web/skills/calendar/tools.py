"""Calendar skill tools for Microsoft 365 Calendar."""
import re
from datetime import datetime, timedelta, timezone


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _parse_email_list(addresses) -> list[str]:
    """Normalize attendee input from the LLM into a flat list of email strings.

    Accepts None, a string, a list of strings, or nested combinations. Tolerates
    semicolons, commas, whitespace, and surrounding quotes — we extract emails
    via regex so stray punctuation (quotes, brackets, "<>") never reaches Graph.
    """
    if not addresses:
        return []
    if isinstance(addresses, str):
        addresses = [addresses]
    flat: list[str] = []
    seen: set[str] = set()
    for item in addresses:
        if not isinstance(item, str):
            continue
        for match in _EMAIL_RE.findall(item):
            key = match.lower()
            if key in seen:
                continue
            seen.add(key)
            flat.append(match)
    return flat

SKILL_ID = "calendar"
ALWAYS_ON = False

DIRECT_INTENTS = [
    {
        "patterns": ["my schedule", "my calendar", "meetings today", "my meetings",
                     "what meetings", "today's schedule", "calendar today",
                     "what's on my calendar", "check my calendar"],
        "tool": "read_calendar",
        "args": {"days": 1},
    },
]


def _normalize_send_updates(value: str | None) -> str:
    """
    Map historical Outlook-style sendUpdates values (SendToAll, SendToNone, etc.)
    to the Microsoft Graph parameters (All, None, ExternalGuestsOnly).
    """
    if not value:
        return "All"
    key = value.strip().lower()
    mapping = {
        "all": "All",
        "sendtoall": "All",
        "sendtoallandsavecopy": "All",
        "sendupdatesall": "All",
        "externalguestsonly": "ExternalGuestsOnly",
        "externalguests": "ExternalGuestsOnly",
        "externalonly": "ExternalGuestsOnly",
        "sendtoexternalguests": "ExternalGuestsOnly",
        "none": "None",
        "sendtonone": "None",
    }
    return mapping.get(key, "All")

TOOL_DEFS = [
    {
        "name": "read_calendar",
        "description": "Fetch calendar events for a specific date or date range. Use when user asks about their schedule, meetings, calendar, what's on for a day, or any day-specific plans (today, tomorrow, Monday, next week, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "ISO date string (YYYY-MM-DD) for the day to fetch. Defaults to today if omitted."},
                "days": {"type": "integer", "description": "Number of days to fetch starting from date. Default 1.", "default": 1},
            },
            "required": [],
        },
    },
    {
        "name": "get_calendar_event_detail",
        "description": "Fetch full details for a calendar event (subject, timing, attendees, body preview, online meeting info) by event ID. Use this when you need the attendee list or to clone/update an event. IMPORTANT: event_id must come from read_calendar results — do NOT pass email message IDs from search_email or read_email, those are different and will fail with 400.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The event ID from read_calendar results"},
                "include_body": {
                    "type": "boolean",
                    "description": "Set true to include the full HTML body content. Defaults to false.",
                    "default": False,
                },
                "include_instances": {
                    "type": "boolean",
                    "description": "If true and the event is a recurring series master, return upcoming occurrence instances.",
                    "default": True,
                },
                "instances_days": {
                    "type": "integer",
                    "description": "When include_instances is true, how many days ahead to fetch occurrences (1-30). Defaults to 7.",
                    "default": 7,
                    "minimum": 1,
                    "maximum": 30,
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "update_calendar_event",
        "description": "Update an existing calendar event in place (reschedule, rename, adjust location/attendees) and send the appropriate update. Prefer this over cancelling and recreating when the user says 'reschedule' or 'move this meeting'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The event ID from read_calendar results"},
                "subject": {"type": "string", "description": "New meeting title (leave blank to keep current)"},
                "start": {"type": "string", "description": "New start datetime in ISO format YYYY-MM-DDTHH:MM[:SS] in the user's local time"},
                "end": {"type": "string", "description": "New end datetime in ISO format YYYY-MM-DDTHH:MM[:SS] in the user's local time"},
                "location": {"type": "string", "description": "New location name"},
                "body": {"type": "string", "description": "Meeting body/agenda. ALWAYS use HTML so Outlook recipients can reply with rich formatting. Use <ul><li>...</li></ul> for bullets, <br> for line breaks, <a href='...'>text</a> for links. HTML is detected automatically and sent as HTML contentType."},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Complete list of required attendees (omit to keep existing)"},
                "optional_attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Complete list of optional attendees (omit to keep existing)",
                },
                "teams": {"type": "boolean", "description": "Set true to force-enable Teams link, false to disable"},
                "recurrence": {
                    "type": "object",
                    "description": "Graph recurrence object ({pattern, range}). Provide the complete recurrence definition when changing the repeat rule.",
                },
                "send_updates": {
                    "type": "string",
                    "enum": ["All", "ExternalGuestsOnly", "None", "SendToAll", "SendToAllAndSaveCopy", "SendToNone"],
                    "description": "Graph sendUpdates mode. Accepts legacy values (SendToAll/SendToNone) and maps them to the supported All/ExternalGuestsOnly/None set. Defaults to All.",
                    "default": "All",
                },
                "response_requested": {
                    "type": "boolean",
                    "description": "Whether attendees must respond. Leave null to keep existing value.",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a calendar event and send invites to attendees. Call this as soon as the user confirms the meeting details (time, subject, attendees). Do not ask for confirmation more than once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Meeting title"},
                "start": {"type": "string", "description": "Start datetime in ISO format YYYY-MM-DDTHH:MM:SS in the user's local time"},
                "end": {"type": "string", "description": "End datetime in ISO format YYYY-MM-DDTHH:MM:SS in the user's local time"},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of required attendee email addresses. Each item must be ONE bare email like 'a@b.com' (no quotes, no semicolons, no display names)."},
                "optional_attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of optional attendee email addresses. Each item must be ONE bare email like 'a@b.com' (no quotes, no semicolons, no display names).",
                },
                "body": {"type": "string", "description": "Meeting description or agenda. ALWAYS use HTML so Outlook recipients can reply with rich formatting. Use <ul><li>...</li></ul> for bullets, <br> for line breaks, <a href='...'>text</a> for links. HTML is detected automatically and sent as HTML contentType."},
                "location": {"type": "string", "description": "Optional location name"},
                "teams": {"type": "boolean", "description": "If true, adds a Microsoft Teams meeting link", "default": False},
                "recurrence": {
                    "type": "object",
                    "description": "Graph recurrence object ({pattern, range}). Leave blank for one-off meetings.",
                },
            },
            "required": ["subject", "start", "end"],
        },
    },
    {
        "name": "find_meeting_times",
        "description": "Find available meeting slots with one or more attendees using Microsoft's findMeetingTimes API. Use when the user asks to find a time, schedule a meeting, or wants to know when everyone is free. Call this BEFORE create_calendar_event when a specific time hasn't been agreed on.",
        "input_schema": {
            "type": "object",
            "properties": {
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee email addresses"},
                "date": {"type": "string", "description": "ISO date string (YYYY-MM-DD) to search. Defaults to tomorrow."},
                "duration_minutes": {"type": "integer", "description": "Required meeting duration in minutes. Default 30.", "default": 30},
                "max_suggestions": {"type": "integer", "description": "Max number of slot suggestions to return. Default 5.", "default": 5},
            },
            "required": ["attendees"],
        },
    },
    {
        "name": "delete_calendar_event",
        "description": "Delete (cancel) a calendar event by its ID. Use when the user asks to cancel or delete a meeting. Requires an event ID \u2014 call read_calendar first if you don't have it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The event ID from read_calendar results"},
                "comment": {"type": "string", "description": "Optional note to include in the cancellation email", "default": ""},
                "delete_series": {
                    "type": "boolean",
                    "description": "Set true to delete the entire recurring series (series master). Leave false to cancel a single occurrence.",
                    "default": False,
                },
                "send_updates": {
                    "type": "string",
                    "enum": ["All", "ExternalGuestsOnly", "None", "SendToAll", "SendToAllAndSaveCopy", "SendToNone"],
                    "description": "Who should receive cancellation emails. Legacy Outlook values map to Graph's All/ExternalGuestsOnly/None set. Defaults to All.",
                    "default": "All",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "respond_calendar_event",
        "description": "RSVP to a calendar event (accept, decline, or tentative). Use when the user wants to skip a single occurrence without cancelling the whole series.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The event ID from read_calendar results"},
                "response": {
                    "type": "string",
                    "enum": ["accept", "decline", "tentative"],
                    "description": "RSVP choice (accept, decline, or tentative).",
                },
                "send_response": {
                    "type": "boolean",
                    "description": "Whether to send a response email to the organizer (default true).",
                    "default": True,
                },
            },
            "required": ["event_id", "response"],
        },
    },
    {
        "name": "create_ooo_event",
        "description": "Create an Out of Office (OOO/PTO) all-day event on the user's calendar. Marks the user as OOF and optionally notifies colleagues (shows as Free on their calendars, no response required).",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date inclusive (YYYY-MM-DD). Same as start_date for a single day."},
                "notify": {"type": "array", "items": {"type": "string"}, "description": "Email addresses to notify (optional)"},
                "subject": {"type": "string", "description": "Custom subject. Defaults to 'OOF: <your name>'."},
                "body": {"type": "string", "description": "Optional message (e.g. backup contact info)"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "forward_calendar_event",
        "description": "Forward an existing calendar event as a proper calendar invite to one or more recipients. Use when the user says 'forward this to X', 'send the invite to X', or 'invite him/her to this meeting'. This sends a real calendar invite (not just an email) that the recipient can Accept/Decline. Requires the event_id from read_calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The event ID from read_calendar results"},
                "to": {"type": "array", "items": {"type": "string"}, "description": "List of recipient email addresses to forward the invite to"},
                "comment": {"type": "string", "description": "Optional message to include with the forwarded invite", "default": ""},
            },
            "required": ["event_id", "to"],
        },
    },
    {
        "name": "check_availability",
        "description": "Check free/busy availability for one or more people by email. Use when the user asks if someone is available, free, or busy on a given day or time range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "emails": {"type": "array", "items": {"type": "string"}, "description": "List of email addresses to check"},
                "date": {"type": "string", "description": "ISO date string (YYYY-MM-DD). Defaults to today if omitted."},
                "start_time": {"type": "string", "description": "Optional start time HH:MM (24h). Defaults to 08:00."},
                "end_time": {"type": "string", "description": "Optional end time HH:MM (24h). Defaults to 18:00."},
            },
            "required": ["emails"],
        },
    },
]

TOOL_STATUS = {
    "read_calendar": "\U0001f4c5 Checking calendar...",
    "get_calendar_event_detail": "\U0001f4c5 Loading event details...",
    "update_calendar_event": "\U0001f4c5 Updating calendar event...",
    "create_calendar_event": "\U0001f4c5 Creating calendar event...",
    "find_meeting_times": "\U0001f4c5 Finding available slots...",
    "delete_calendar_event": "\U0001f4c5 Cancelling event...",
    "respond_calendar_event": "\U0001f4c5 Updating RSVP...",
    "create_ooo_event": "\U0001f4c5 Creating OOO event...",
    "forward_calendar_event": "\U0001f4c5 Forwarding calendar invite...",
    "check_availability": "\U0001f4c5 Checking availability...",
}


def _tool_read_calendar(date: str = "", days: int = 1) -> dict:
    from .._m365.helpers import get_cal_client
    from .helpers import get_user_win_tz, fmt_cal_time, cal_day_range_utc
    gc = get_cal_client()
    start, end = cal_day_range_utc(date, days)
    events = gc.get("/me/calendarView", params={
        "startDateTime": start.isoformat().replace("+00:00", "Z"),
        "endDateTime": end.isoformat().replace("+00:00", "Z"),
        "$top": "20",
        "$select": "id,subject,start,end,location,isAllDay,organizer,isOrganizer,seriesMasterId,type",
        "$orderby": "start/dateTime",
    }, extra_headers={"Prefer": f'outlook.timezone="{get_user_win_tz()}"'})
    return {"events": [
        {
            "id": e.get("id", ""),
            "subject": e.get("subject", "(no subject)"),
            "start": fmt_cal_time(e.get("start", {}).get("dateTime", "")),
            "end": fmt_cal_time(e.get("end", {}).get("dateTime", "")),
            "location": e.get("location", {}).get("displayName", ""),
            "isAllDay": e.get("isAllDay", False),
            "organizer": e.get("organizer", {}).get("emailAddress", {}).get("name", ""),
            "isOrganizer": e.get("isOrganizer", False),
            "seriesMasterId": e.get("seriesMasterId", ""),
            "type": e.get("type", ""),
        }
        for e in events.get("value", [])
    ]}


def _tool_create_calendar_event(subject: str, start: str, end: str, attendees: list = None,
                                optional_attendees: list = None, body: str = "", location: str = "",
                                teams: bool = False, recurrence: dict | None = None) -> dict:
    from .._m365.helpers import get_cal_client
    from .helpers import get_user_win_tz, fmt_cal_time
    gc = get_cal_client()
    win_tz = get_user_win_tz()
    event = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": win_tz},
        "end": {"dateTime": end, "timeZone": win_tz},
    }
    attendee_entries = []
    seen_addresses = set()

    def _append_attendees(addresses, attendee_type):
        for email in _parse_email_list(addresses):
            email = email.strip()
            if not email:
                continue
            key = email.lower()
            if key in seen_addresses:
                continue
            attendee_entries.append({
                "emailAddress": {"address": email},
                "type": attendee_type,
            })
            seen_addresses.add(key)

    _append_attendees(attendees, "required")
    _append_attendees(optional_attendees, "optional")

    if attendee_entries:
        event["attendees"] = attendee_entries

    if body:
        # Auto-detect HTML: any tag present → send as HTML so <a>, <br>, etc. render.
        is_html = bool(re.search(r"<\w+[^>]*>", body))
        event["body"] = {"contentType": "HTML" if is_html else "text", "content": body}
    if location:
        event["location"] = {"displayName": location}
    if teams:
        event["isOnlineMeeting"] = True
        event["onlineMeetingProvider"] = "teamsForBusiness"
    if recurrence:
        event["recurrence"] = recurrence
    try:
        result = gc.post("/me/events", event)
    except Exception as ex:
        return {"created": False, "error": f"Unable to create event: {ex}"}
    return {
        "created": True,
        "subject": result.get("subject", ""),
        "start": fmt_cal_time(result.get("start", {}).get("dateTime", "")),
        "end": fmt_cal_time(result.get("end", {}).get("dateTime", "")),
        "teams_link": (result.get("onlineMeeting") or {}).get("joinUrl", ""),
        "id": result.get("id", ""),
    }


def _tool_find_meeting_times(attendees: list, date: str = "", duration_minutes: int = 30, max_suggestions: int = 5) -> dict:
    from .._m365.helpers import get_cal_client
    from .helpers import get_user_win_tz, fmt_cal_time
    gc = get_cal_client()
    win_tz = get_user_win_tz()
    local_tz = datetime.now().astimezone().tzinfo
    if date:
        day = datetime.fromisoformat(date).replace(tzinfo=local_tz).strftime("%Y-%m-%d")
    else:
        day = (datetime.now(local_tz) + timedelta(days=1)).strftime("%Y-%m-%d")
    result = gc.post("/me/findMeetingTimes", {
        "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in attendees],
        "timeConstraint": {
            "timeslots": [{
                "start": {"dateTime": f"{day}T08:00:00", "timeZone": win_tz},
                "end": {"dateTime": f"{day}T18:00:00", "timeZone": win_tz},
            }]
        },
        "meetingDuration": f"PT{duration_minutes}M",
        "maxCandidates": max_suggestions,
    })
    suggestions = []
    for slot in result.get("meetingTimeSuggestions", []):
        s = slot.get("meetingTimeSlot", {})
        suggestions.append({
            "start": fmt_cal_time(s.get("start", {}).get("dateTime", "")),
            "end": fmt_cal_time(s.get("end", {}).get("dateTime", "")),
            "confidence": round(slot.get("confidence", 0) * 100),
        })
    return {"date": day, "duration_minutes": duration_minutes, "suggestions": suggestions}


def _tool_delete_calendar_event(event_id: str, comment: str = "", delete_series: bool = False,
                                send_updates: str = "All") -> dict:
    from .._m365.helpers import get_cal_client
    gc = get_cal_client()

    normalized_send_updates = _normalize_send_updates(send_updates)

    def _parse_dt(dt_str: str) -> datetime | None:
        """Return a timezone-aware UTC datetime if possible."""
        if not dt_str:
            return None
        cleaned = dt_str.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _datetime_key(dt_str: str) -> str:
        dt = _parse_dt(dt_str)
        if dt:
            return dt.isoformat(timespec="seconds")
        return (dt_str or "").strip()

    try:
        event = gc.get(
            f"/me/events/{event_id}",
            {"$select": "id,subject,isOrganizer,type,seriesMasterId,start"},
        )
    except Exception as ex:
        status_code = getattr(ex, "status_code", 0)
        if status_code == 404:
            return {"deleted": False, "not_found": True, "error": "This event no longer exists — it may have been deleted or cancelled."}
        return {"deleted": False, "error": f"Unable to load event: {ex}"}
    if not event:
        return {"deleted": False, "not_found": True, "error": "This event no longer exists — it may have been deleted or cancelled."}
    if not event.get("isOrganizer", False):
        return {
            "deleted": False,
            "organizer_required": True,
            "error": "You can only cancel an occurrence you organize. Decline it or ask the organizer instead.",
            "subject": event.get("subject", ""),
        }

    event_type = (event.get("type") or "").lower()
    series_master_id = (event.get("seriesMasterId") or "").strip()
    occurrence_start_raw = ((event.get("start") or {}).get("dateTime") or "").strip()
    occurrence_key = _datetime_key(occurrence_start_raw)

    is_series_master = event_type == "seriesmaster"
    if is_series_master and not delete_series:
        return {
            "deleted": False,
            "series_master": True,
            "error": "Got the recurring series master. Provide the specific occurrence ID from get_calendar_event_detail.instances to cancel just one date or set delete_series=true to remove the full series.",
            "subject": event.get("subject", ""),
        }

    # When delete_series=True and the caller passed an occurrence ID, resolve to the
    # series master so we delete the entire series, not just one instance.
    delete_target = event_id
    if delete_series and not is_series_master and series_master_id:
        delete_target = series_master_id
        is_series_master = True

    # DELETE first — removes the event from the organizer's calendar and sends
    # cancellation emails to attendees (when sendUpdates=All).
    delete_succeeded = False
    try:
        gc.delete(f"/me/events/{delete_target}?sendUpdates={normalized_send_updates}")
        delete_succeeded = True
    except Exception as ex:
        status_code = getattr(ex, "status_code", 0)
        if status_code == 404:
            # Event ID already gone from API — may have been deleted by a prior
            # attempt.  Do NOT claim success; we can't verify it was cleaned up.
            pass
        else:
            return {"deleted": False, "error": f"Unable to delete event: {ex}", "subject": event.get("subject", "")}

    # If the caller included a comment, send a cancel notification so attendees
    # see the reason.  This is best-effort — the event is already deleted above.
    cancel_comment = (comment or "").strip()
    if cancel_comment and delete_succeeded:
        try:
            gc.post(f"/me/events/{delete_target}/cancel", {"Comment": cancel_comment})
        except Exception:
            pass  # event already deleted; cancel may 404 — that's fine

    # ── Verification ──────────────────────────────────────────────────
    # Confirm the event is actually gone before reporting success.
    verified_deleted = False
    try:
        remaining = gc.get(f"/me/events/{delete_target}", {"$select": "id,isCancelled,type"})
        if remaining and not remaining.get("isCancelled", False):
            return {
                "deleted": False,
                "error": "Graph still shows this event as active after DELETE. Try again or cancel it manually in Outlook.",
                "subject": event.get("subject", ""),
            }
        if remaining and remaining.get("isCancelled", False):
            verified_deleted = True
    except Exception as verify_err:
        status_code = getattr(verify_err, "status_code", 0)
        if status_code in (0, 404):
            # 404 after a successful DELETE = event is gone = success
            if delete_succeeded:
                verified_deleted = True
        else:
            return {
                "deleted": False,
                "error": f"Unable to verify deletion: {verify_err}",
                "subject": event.get("subject", ""),
            }

    # For single occurrences of a recurring series, also check the series master
    if not verified_deleted and not is_series_master and series_master_id:
        try:
            occ_dt = _parse_dt(occurrence_start_raw)
            if occ_dt:
                start_range = (occ_dt - timedelta(hours=12)).isoformat()
                end_range = (occ_dt + timedelta(hours=12)).isoformat()
            else:
                now = datetime.now(timezone.utc)
                start_range = (now - timedelta(days=30)).isoformat()
                end_range = (now + timedelta(days=60)).isoformat()
            instances_raw = gc.get(
                f"/me/events/{series_master_id}/instances",
                {
                    "startDateTime": start_range,
                    "endDateTime": end_range,
                    "$select": "id,start,isCancelled",
                },
            )
            for occ in instances_raw.get("value", []):
                occ_id = occ.get("id", "")
                occ_key = _datetime_key((occ.get("start") or {}).get("dateTime", ""))
                still_active = not occ.get("isCancelled", False)
                if occ_id == event_id or (occurrence_key and occ_key == occurrence_key):
                    if still_active:
                        return {
                            "deleted": False,
                            "error": "Graph still lists this occurrence in the series. Cancel it from Outlook or retry with the refreshed occurrence ID.",
                            "subject": event.get("subject", ""),
                        }
                    verified_deleted = True
                    break
        except Exception as inst_err:
            status_code = getattr(inst_err, "status_code", 0)
            if status_code not in (0, 404):
                return {
                    "deleted": False,
                    "error": f"Unable to verify against the series master: {inst_err}",
                    "subject": event.get("subject", ""),
                }

    if not verified_deleted:
        return {
            "deleted": False,
            "error": "Could not confirm the event was removed. It may still appear on your calendar — try deleting it directly in Outlook.",
            "subject": event.get("subject", ""),
        }

    result = {"deleted": True, "event_id": event_id, "subject": event.get("subject", "")}
    if is_series_master:
        result["series_deleted"] = True
    return result


def _tool_respond_calendar_event(event_id: str, response: str, send_response: bool = True) -> dict:
    """RSVP to an event (accept, decline, tentative)."""
    from .._m365.helpers import get_cal_client

    gc = get_cal_client()
    response_map = {
        "accept": "accept",
        "decline": "decline",
        "tentative": "tentativelyAccept",
        "tentativelyaccept": "tentativelyAccept",
    }
    key = response_map.get((response or "").strip().lower())
    if not key:
        return {"responded": False, "error": f"Unsupported response '{response}'"}
    payload = {"sendResponse": bool(send_response)}
    try:
        gc.post(f"/me/events/{event_id}/{key}", payload)
    except Exception as ex:
        # If organizer disabled responses, retry silently without sending a response email.
        if "hasn't requested a response" in str(ex).lower() and payload["sendResponse"]:
            try:
                gc.post(f"/me/events/{event_id}/{key}", {"sendResponse": False})
            except Exception as retry_err:
                return {"responded": False, "error": f"Unable to update RSVP: {retry_err}"}
        else:
            return {"responded": False, "error": f"Unable to update RSVP: {ex}"}
    return {"responded": True, "event_id": event_id, "response": key, "send_response": bool(send_response)}


def _tool_create_ooo_event(start_date: str, end_date: str, notify: list = None,
                            subject: str = "", body: str = "") -> dict:
    from .._m365.helpers import get_cal_client
    from .helpers import get_user_win_tz
    gc = get_cal_client()
    win_tz = get_user_win_tz()
    if not subject:
        me = gc.get("/me", params={"$select": "displayName"})
        subject = f"OOF: {me.get('displayName', '')}"
    end_midnight = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
    event = {
        "subject": subject,
        "isAllDay": True,
        "start": {"dateTime": f"{start_date}T00:00:00", "timeZone": win_tz},
        "end": {"dateTime": end_midnight, "timeZone": win_tz},
        "showAs": "oof",
        "responseRequested": False,
        "isReminderOn": False,
    }
    if notify:
        event["attendees"] = [{"emailAddress": {"address": a}, "type": "optional"} for a in notify if a]
    if body:
        event["body"] = {"contentType": "text", "content": body}
    result = gc.post("/me/events", event)
    event_id = result.get("id", "")
    date_label = start_date if start_date == end_date else f"{start_date} to {end_date}"
    return {
        "created": True, "subject": subject, "dates": date_label,
        "your_calendar": "Out of Office", "notified": notify or [],
        "id": event_id,
    }


def _tool_check_availability(emails: list, date: str = "", start_time: str = "08:00", end_time: str = "18:00") -> dict:
    from .._m365.helpers import get_cal_client
    from .helpers import get_user_win_tz
    gc = get_cal_client()
    local_tz = datetime.now().astimezone().tzinfo
    if date:
        day_local = datetime.fromisoformat(date).replace(tzinfo=local_tz)
    else:
        day_local = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    sh, sm = (int(x) for x in start_time.split(":"))
    eh, em = (int(x) for x in end_time.split(":"))
    start_local = day_local.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end_local = day_local.replace(hour=eh, minute=em, second=0, microsecond=0)
    win_tz = get_user_win_tz()

    def _fmt_local(dt_str: str) -> str:
        """Convert a UTC datetime string to local time HH:MM AM/PM."""
        try:
            dt_utc = datetime.fromisoformat(dt_str.split("+")[0].rstrip("Z")).replace(tzinfo=timezone.utc)
            dt_local = dt_utc.astimezone(local_tz)
            return dt_local.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return dt_str[:5]

    result = gc.post("/me/calendar/getSchedule", {
        "schedules": emails,
        "startTime": {"dateTime": start_local.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": win_tz},
        "endTime": {"dateTime": end_local.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": win_tz},
        "availabilityViewInterval": 15,
    })
    schedules = []
    for s in result.get("value", []):
        items = s.get("scheduleItems", [])
        schedules.append({
            "email": s.get("scheduleId", ""),
            "busy_slots": [
                {
                    "subject": i.get("subject", "(busy)") or "(busy)",
                    "status": i.get("status", "busy") or "busy",
                    "start": _fmt_local(i.get("start", {}).get("dateTime", "")),
                    "end": _fmt_local(i.get("end", {}).get("dateTime", "")),
                }
                for i in items
                if i.get("status", "busy").lower() in ("busy", "tentative", "oof", "workingelsewhere")
            ],
            "note": "Tentative means tentative (may free up). Busy/OOF means hard-blocked. All times are in your local timezone.",
        })
    return {"schedules": schedules}


def _tool_get_calendar_event_detail(event_id: str, include_body: bool = False,
                                    include_instances: bool = True, instances_days: int = 7) -> dict:
    """Return a rich description of a single event, including attendees split by type,
    timing details, and body preview so the caller can clone or edit the meeting."""
    from .._m365.helpers import get_cal_client, get_cached_me
    from .helpers import fmt_cal_time

    def _format_display(dt_str: str, tz_label: str) -> str:
        if not dt_str:
            return ""
        try:
            # Graph often returns fractional seconds; strip trailing Z for fromisoformat compatibility
            cleaned = dt_str.rstrip("Z")
            dt = datetime.fromisoformat(cleaned)
            time_label = dt.strftime("%I:%M %p").lstrip("0")
            display = f"{dt.strftime('%a %b')} {dt.day}, {time_label}"
            if tz_label:
                display += f" {tz_label}"
            return display
        except Exception:
            return f"{dt_str}{f' ({tz_label})' if tz_label else ''}"

    # Guard: email message IDs start with AAMkAD and go to /me/messages — they're NOT calendar event IDs.
    # Calendar event IDs from calendarView go to /me/events and look similar but are different objects.
    # If caller passed an email ID by mistake, return a clear error instead of a confusing Graph 400.
    if event_id and len(event_id) > 100 and "AAMkAD" in event_id and event_id.count("AAMkAD") > 1:
        return {"error": "This looks like an email message ID, not a calendar event ID. Call read_calendar to get event IDs, then pass the id from those results."}

    gc = get_cal_client()
    select_fields = [
        "subject",
        "start",
        "end",
        "location",
        "isAllDay",
        "attendees",
        "organizer",
        "responseRequested",
        "isOnlineMeeting",
        "onlineMeetingUrl",
        "bodyPreview",
        "isOrganizer",
        "seriesMasterId",
        "type",
        "recurrence",
    ]
    if include_body:
        select_fields.append("body")

    try:
        event = gc.get(
            f"/me/events/{event_id}",
            {"$select": ",".join(select_fields)},
        )
    except Exception as ex:
        status_code = getattr(ex, "status_code", 0)
        if status_code == 404:
            return {"not_found": True, "error": "This event no longer exists — it may have been deleted or cancelled."}
        return {"error": f"Unable to load event: {ex}"}

    start_info = event.get("start") or {}
    end_info = event.get("end") or {}
    attendees_raw = event.get("attendees") or []

    attendees_all = []
    attendees_required = []
    attendees_optional = []
    for attendee in attendees_raw:
        if not isinstance(attendee, dict):
            continue
        email_info = attendee.get("emailAddress") or {}
        email = (email_info.get("address") or "").strip()
        if not email:
            continue
        name = email_info.get("name", "")
        att_type = (attendee.get("type") or "required").lower()
        status = ((attendee.get("status") or {}).get("response") or "none").lower()
        entry = {
            "name": name,
            "email": email,
            "type": att_type,
            "status": status,
            "is_optional": att_type != "required",
        }
        attendees_all.append(entry)
        if att_type == "required":
            attendees_required.append(entry)
        else:
            attendees_optional.append(entry)

    organizer_info = (event.get("organizer") or {}).get("emailAddress") or {}
    body_content = ""
    if include_body:
        body_content = (event.get("body") or {}).get("content", "") or ""

    me = get_cached_me(gc)
    me_display = me.get("displayName", "")
    me_email = (me.get("mail") or me.get("userPrincipalName") or "").strip().lower()
    organizer_email = (organizer_info.get("address") or "").strip()
    organizer_name = organizer_info.get("name", "")
    organizer_is_self = bool(
        event.get("isOrganizer") or
        (organizer_email and me_email and organizer_email.lower() == me_email) or
        (organizer_name and me_display and organizer_name.lower() == me_display.lower())
    )

    instances = []
    if include_instances and (event.get("type", "").lower() == "seriesmaster"):
        try:
            horizon = max(1, min(int(instances_days or 7), 30))
        except Exception:
            horizon = 7
        local_tz = datetime.now().astimezone().tzinfo
        anchor = datetime.now(local_tz)
        start_range = anchor.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        end_range = (anchor + timedelta(days=horizon)).replace(hour=23, minute=59, second=59, microsecond=0)
        instances_raw = gc.get(
            f"/me/events/{event_id}/instances",
            {
                "startDateTime": start_range.isoformat(),
                "endDateTime": end_range.isoformat(),
                "$select": "id,subject,start,end,isCancelled,isOrganizer",
            },
        )
        for occ in instances_raw.get("value", []):
            start_occ = occ.get("start", {}) or {}
            end_occ = occ.get("end", {}) or {}
            instances.append({
                "id": occ.get("id", ""),
                "subject": occ.get("subject", ""),
                "isCancelled": occ.get("isCancelled", False),
                "isOrganizer": occ.get("isOrganizer", False),
                "start": {
                    "dateTime": start_occ.get("dateTime", ""),
                    "timeZone": start_occ.get("timeZone", ""),
                    "time": fmt_cal_time(start_occ.get("dateTime", "")),
                },
                "end": {
                    "dateTime": end_occ.get("dateTime", ""),
                    "timeZone": end_occ.get("timeZone", ""),
                    "time": fmt_cal_time(end_occ.get("dateTime", "")),
                },
            })
        instances.sort(key=lambda x: x["start"]["dateTime"])
    else:
        instances = []

    return {
        "event_id": event_id,
        "subject": event.get("subject", ""),
        "is_all_day": event.get("isAllDay", False),
        "response_requested": event.get("responseRequested", True),
        "event_type": event.get("type", ""),
        "series_master_id": event.get("seriesMasterId", ""),
        "recurrence": event.get("recurrence") or {},
        "start": {
            "dateTime": start_info.get("dateTime", ""),
            "timeZone": start_info.get("timeZone", ""),
            "display": _format_display(start_info.get("dateTime", ""), start_info.get("timeZone", "")),
            "time": fmt_cal_time(start_info.get("dateTime", "")),
        },
        "end": {
            "dateTime": end_info.get("dateTime", ""),
            "timeZone": end_info.get("timeZone", ""),
            "display": _format_display(end_info.get("dateTime", ""), end_info.get("timeZone", "")),
            "time": fmt_cal_time(end_info.get("dateTime", "")),
        },
        "location": (event.get("location") or {}).get("displayName", ""),
        "organizer": {
            "name": organizer_name,
            "email": organizer_email,
        },
        "organizer_is_self": organizer_is_self,
        "attendees": {
            "required": attendees_required,
            "optional": attendees_optional,
            "all": attendees_all,
        },
        "online_meeting": {
            "is_online": event.get("isOnlineMeeting", False),
            "url": event.get("onlineMeetingUrl", ""),
        },
        "body_preview": event.get("bodyPreview", "") or "",
        "body": body_content,
        "instances": instances,
    }


def _normalize_local_datetime(dt_str: str, target_tz) -> str:
    """Convert any ISO-ish string to the user's local wall time (no offset), falling back to the raw string."""
    if not dt_str:
        return ""
    dt_str = dt_str.strip()
    try:
        # Support strings like 2026-05-07T09:00, 2026-05-07T09:00:00, or with offsets.
        cleaned = dt_str.replace("Z", "+00:00") if dt_str.endswith("Z") else dt_str
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            # Already naive — assume it's local
            if len(dt_str) == 16:
                return dt.strftime("%Y-%m-%dT%H:%M")
            if len(dt_str) == 19:
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        local_dt = dt.astimezone(target_tz)
        return local_dt.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        # Try to normalize HH:MM inputs
        if len(dt_str) == 5 and dt_str[2] == ":":
            today = datetime.now(target_tz)
            combined = today.replace(hour=int(dt_str[:2]), minute=int(dt_str[3:5]), second=0, microsecond=0)
            return combined.strftime("%Y-%m-%dT%H:%M:%S")
        return dt_str


def _tool_update_calendar_event(event_id: str, subject: str = "", start: str = "", end: str = "",
                                location: str = "", body: str = "", attendees: list = None,
                                optional_attendees: list = None, teams: bool | None = None,
                                recurrence: dict | None = None,
                                send_updates: str = "All", response_requested: bool | None = None) -> dict:
    """Reschedule or edit an existing event in place."""
    from .._m365.helpers import get_cal_client
    from .helpers import get_user_win_tz

    gc = get_cal_client()
    win_tz = get_user_win_tz()
    local_tz = datetime.now().astimezone().tzinfo

    update_payload = {}

    if subject:
        update_payload["subject"] = subject

    if start:
        update_payload["start"] = {
            "dateTime": _normalize_local_datetime(start, local_tz),
            "timeZone": win_tz,
        }
    if end:
        update_payload["end"] = {
            "dateTime": _normalize_local_datetime(end, local_tz),
            "timeZone": win_tz,
        }

    if location:
        update_payload["location"] = {"displayName": location}

    if body:
        is_html = bool(re.search(r"<\w+[^>]*>", body))
        update_payload["body"] = {"contentType": "HTML" if is_html else "text", "content": body}

    attendee_entries = []
    seen_addresses = set()

    def _append(addresses, att_type):
        for email in _parse_email_list(addresses):
            email = email.strip()
            if not email:
                continue
            key = email.lower()
            if key in seen_addresses:
                continue
            attendee_entries.append({
                "emailAddress": {"address": email},
                "type": att_type,
            })
            seen_addresses.add(key)

    _append(attendees, "required")
    _append(optional_attendees, "optional")

    if attendee_entries:
        update_payload["attendees"] = attendee_entries

    if teams is True:
        update_payload["isOnlineMeeting"] = True
        update_payload["onlineMeetingProvider"] = "teamsForBusiness"
    elif teams is False:
        update_payload["isOnlineMeeting"] = False
        update_payload["onlineMeetingProvider"] = "unknown"

    if response_requested is not None:
        update_payload["responseRequested"] = bool(response_requested)
    if recurrence is not None:
        update_payload["recurrence"] = recurrence

    if not update_payload:
        return {"updated": False, "note": "No changes provided."}

    normalized_send_updates = _normalize_send_updates(send_updates)
    try:
        gc.patch(
            f"/me/events/{event_id}?sendUpdates={normalized_send_updates}",
            update_payload,
        )
    except Exception as ex:
        return {"updated": False, "error": f"Unable to update event: {ex}"}

    try:
        refreshed = gc.get(
            f"/me/events/{event_id}",
            {"$select": "subject,start,end,location,attendees,isOnlineMeeting,onlineMeetingUrl"},
        )
    except Exception:
        refreshed = {}

    return {
        "updated": True,
        "event_id": event_id,
        "subject": refreshed.get("subject", subject),
        "start": (refreshed.get("start") or {}).get("dateTime", ""),
        "end": (refreshed.get("end") or {}).get("dateTime", ""),
        "location": (refreshed.get("location") or {}).get("displayName", ""),
        "attendee_count": len(refreshed.get("attendees") or attendee_entries),
        "online_meeting": (refreshed.get("onlineMeetingUrl") or ""),
    }


def _tool_forward_calendar_event(event_id: str, to: list, comment: str = "") -> dict:
    """Add attendees to an existing event via PATCH so they appear in the attendee list
    and receive a proper invite they can Accept/Decline. Falls back to the Graph
    /forward endpoint only if PATCH fails."""
    from .._m365.helpers import get_cal_client
    gc = get_cal_client()

    def _forward_fallback(recipients: list[str], reason: str):
        payload = [{"emailAddress": {"address": email}} for email in recipients]
        try:
            gc.post(f"/me/events/{event_id}/forward", {
                "toRecipients": payload,
                "comment": comment or "",
            })
            return {
                "forwarded": False,
                "fallback_forward": True,
                "note": (
                    "Graph refused to add the attendee as a proper participant, so I sent them the "
                    "invite via the legacy forward flow. They will receive an email copy, but they "
                    "will not appear in your attendee list or RSVP tracking."
                ),
                "attempted": recipients,
                "error": reason,
            }
        except Exception as forward_ex:
            return {
                "forwarded": False,
                "fallback_forward": False,
                "attempted": recipients,
                "error": f"{reason}; forward fallback also failed: {forward_ex}",
            }

    new_emails = [addr.strip() for addr in to if isinstance(addr, str) and addr.strip()]
    if not new_emails:
        return {"error": "No valid recipients provided"}

    try:
        event = gc.get(f"/me/events/{event_id}", {"$select": "attendees,subject,isOrganizer"})
    except Exception as ex:
        return {"error": f"Unable to load event: {ex}"}

    if not event.get("isOrganizer", False):
        return {
            "forwarded": False,
            "error": "You can only add attendees for meetings you organize. Ask the organizer to update the invite.",
        }

    existing = list(event.get("attendees") or [])
    existing_addresses = {
        (a.get("emailAddress", {}) or {}).get("address", "").lower()
        for a in existing
        if isinstance(a, dict)
    }

    added = []
    for email in new_emails:
        key = email.lower()
        if key in existing_addresses:
            continue
        existing.append({
            "emailAddress": {"address": email},
            "type": "required",
            "status": {"response": "none"}
        })
        existing_addresses.add(key)
        added.append(email)

    if not added:
        return {"forwarded": False, "note": "All recipients are already attendees on this event."}

    try:
        gc.patch(
            f"/me/events/{event_id}?sendUpdates={_normalize_send_updates('All')}",
            {
                "attendees": existing,
                "responseRequested": True,
            },
        )
    except Exception as ex:
        return _forward_fallback(added, f"Unable to add attendees via Graph PATCH: {ex}")

    try:
        updated = gc.get(f"/me/events/{event_id}", {"$select": "attendees"})
    except Exception as refetch_error:
        return _forward_fallback(added, f"Unable to verify attendee list after update: {refetch_error}")

    updated_addresses = {
        (a.get("emailAddress", {}) or {}).get("address", "").lower()
        for a in (updated.get("attendees") or [])
        if isinstance(a, dict)
    }
    missing = [email for email in added if email.lower() not in updated_addresses]

    if missing:
        return _forward_fallback(missing, "Graph accepted the update but did not confirm the attendee in the event")

    note = (
        "Added as attendees via PATCH — they will receive a calendar invite, appear in your meeting's attendee list, "
        "and their RSVP will flow back once they respond."
    )
    if comment:
        note += " (Graph does not support forwarding comments when adding attendees; send a separate note if needed.)"
    return {
        "forwarded": True,
        "added_as_attendees": added,
        "note": note,
    }


TOOL_HANDLERS = {
    "read_calendar": _tool_read_calendar,
    "get_calendar_event_detail": _tool_get_calendar_event_detail,
    "update_calendar_event": _tool_update_calendar_event,
    "create_calendar_event": _tool_create_calendar_event,
    "find_meeting_times": _tool_find_meeting_times,
    "delete_calendar_event": _tool_delete_calendar_event,
    "respond_calendar_event": _tool_respond_calendar_event,
    "create_ooo_event": _tool_create_ooo_event,
    "forward_calendar_event": _tool_forward_calendar_event,
    "check_availability": _tool_check_availability,
}
