"""The only place that creates a calendar event in Microsoft Graph.

An event with attendees is created as an unsent draft unless the caller says it is delivering it,
and only the draft-approval route does that. tests/test_calendar_event_creation_inventory.py fails
if any other file posts to /me/events.
"""

import re
from urllib.parse import quote


class NoAttendeesError(ValueError):
    pass


class NotHeldAsDraftError(RuntimeError):
    """Graph created the event but did not keep it as an unsent draft, so invites may have gone out."""

    def __init__(self, event: dict):
        super().__init__("The meeting was created but is not an unsent draft")
        self.event = event


def event_payload(params: dict) -> dict:
    tz = params.get("timezone", "")
    event: dict = {
        "subject": params.get("subject", ""),
        "start": {"dateTime": params.get("start", ""), "timeZone": tz},
        "end": {"dateTime": params.get("end", ""), "timeZone": tz},
    }
    attendees = [
        {"emailAddress": {"address": a}, "type": kind}
        for kind, key in (("required", "attendees"), ("optional", "optional_attendees"))
        for a in (params.get(key) or [])
    ]
    if attendees:
        event["attendees"] = attendees
    body = params.get("body") or ""
    if body:
        is_html = not params.get("body_plain") and bool(re.search(r"<\w+[^>]*>", body))
        event["body"] = {"contentType": "HTML" if is_html else "text", "content": body}
    if params.get("location"):
        event["location"] = {"displayName": params["location"]}
    if params.get("teams"):
        event["isOnlineMeeting"] = True
        event["onlineMeetingProvider"] = "teamsForBusiness"
    if params.get("recurrence"):
        event["recurrence"] = params["recurrence"]
    if params.get("ooo"):
        event.update(isAllDay=True, showAs="oof", responseRequested=False, isReminderOn=False)
    return event


def create_event(event: dict, *, deliver: bool = False) -> dict:
    """Create `event`. With attendees it stays an unsent draft (isDraft) unless `deliver` is True."""
    from skills._m365.helpers import get_cal_client

    body = dict(event)
    hold = bool(body.get("attendees")) and not deliver
    if hold:
        body["isDraft"] = True
    gc = get_cal_client()
    created = gc.post("/me/events", body)
    if hold:
        try:
            saved = gc.get(f"/me/events/{quote((created or {}).get('id', ''), safe='')}", params={"$select": "isDraft"})
        except Exception:
            saved = None
        if (saved or {}).get("isDraft") is not True:
            raise NotHeldAsDraftError(created or {})
    return created


def create_meeting(params: dict, *, deliver: bool = False) -> dict:
    """Create a meeting from a calendar draft's params; it needs at least one attendee."""
    if not (params.get("attendees") or params.get("optional_attendees")):
        raise NoAttendeesError("No attendees specified")
    return create_event(event_payload(params), deliver=deliver)
