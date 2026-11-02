"""Calendar route group -- calendar view, event detail, RSVP."""

from fastapi import APIRouter, HTTPException, Depends
from security import verify_csrf
from pydantic import BaseModel
from urllib.parse import quote as _url_quote

import shared

router = APIRouter()

_eid = lambda eid: _url_quote(eid, safe="")  # encode Graph resource ID for path segment


# ── Pydantic models ──────────────────────────────────────────────────────────


class CalendarRsvpRequest(BaseModel):
    response: str  # "accept", "decline", or "tentativelyAccept"
    send_response: bool = True


class AvailabilityDaysRequest(BaseModel):
    emails: list[str]
    after_date: str = ""
    dates: list[str] = []
    duration_minutes: int = 30


# ── Calendar third-pane endpoints ────────────────────────────────────────────


@router.get("/api/calendar/events")
async def tp_calendar_events(start: str, end: str):
    """Return events in FullCalendar format for a date range."""
    try:
        from skills._m365.helpers import get_cal_client
        from skills.calendar.helpers import get_user_win_tz

        gc = get_cal_client()
        win_tz = get_user_win_tz()
        result = gc.get(
            "/me/calendarView",
            params={
                "startDateTime": start,
                "endDateTime": end,
                "$top": "200",
                "$select": "id,subject,start,end,location,isAllDay,organizer,attendees,bodyPreview,isOnlineMeeting,onlineMeeting,showAs,responseStatus",
                "$orderby": "start/dateTime",
            },
            extra_headers={"Prefer": f'outlook.timezone="{win_tz}"'},
        )
        return [
            {
                "id": e.get("id", ""),
                "title": e.get("subject", "(no subject)"),
                "start": e.get("start", {}).get("dateTime", ""),
                "end": e.get("end", {}).get("dateTime", ""),
                "allDay": e.get("isAllDay", False),
                "extendedProps": {
                    "location": (e.get("location") or {}).get("displayName", ""),
                    "organizer": (e.get("organizer") or {})
                    .get("emailAddress", {})
                    .get("name", ""),
                    "showAs": e.get("showAs", ""),
                    "responseStatus": (e.get("responseStatus") or {}).get(
                        "response", ""
                    ),
                    "bodyPreview": (e.get("bodyPreview") or "")[:200],
                    "isOnlineMeeting": e.get("isOnlineMeeting", False),
                    "joinUrl": (e.get("onlineMeeting") or {}).get("joinUrl", ""),
                    "attendees": [
                        {
                            "name": a.get("emailAddress", {}).get("name", ""),
                            "email": a.get("emailAddress", {}).get("address", ""),
                            "status": (a.get("status") or {}).get("response", ""),
                        }
                        for a in (e.get("attendees") or [])
                    ],
                },
            }
            for e in result.get("value", [])
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/calendar/events/{event_id}")
async def tp_calendar_event_detail(event_id: str):
    """Full event detail including body HTML."""
    try:
        from skills._m365.helpers import get_cal_client
        from skills.calendar.helpers import get_user_win_tz

        gc = get_cal_client()
        win_tz = get_user_win_tz()
        e = gc.get(
            f"/me/events/{_eid(event_id)}",
            params={
                "$select": "id,subject,start,end,location,isAllDay,organizer,attendees,body,isOnlineMeeting,onlineMeeting,showAs,importance,recurrence,responseStatus,isOrganizer,seriesMasterId,type",
            },
            extra_headers={"Prefer": f'outlook.timezone="{win_tz}"'},
        )
        return e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/calendar/events/{event_id}/respond", dependencies=[Depends(verify_csrf)])
async def tp_calendar_respond(event_id: str, req: CalendarRsvpRequest):
    """Accept, decline, or tentatively accept a calendar event."""
    if req.response not in ("accept", "decline", "tentativelyAccept"):
        raise HTTPException(
            status_code=400,
            detail="response must be accept, decline, or tentativelyAccept",
        )
    try:
        from skills._m365.helpers import get_cal_client

        gc = get_cal_client()
        try:
            gc.post(
                f"/me/events/{_eid(event_id)}/{req.response}",
                {"sendResponse": req.send_response},
            )
        except RuntimeError as e:
            # If organizer disabled responses, retry without sending a response email
            if "hasn't requested a response" in str(e) and req.send_response:
                gc.post(
                    f"/me/events/{_eid(event_id)}/{req.response}", {"sendResponse": False}
                )
            else:
                raise
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GridSeriesRequest(BaseModel):
    start: str
    end: str
    timezone: str
    attendees: list[str] = []
    optional_attendees: list[str] = []
    repeat: dict | None = None


_INDEXES = {"first", "second", "third", "fourth", "last"}


def _graph_recurrence(spec: dict, start_date: str) -> dict:
    """Turns the availability grid's repeat choice into a Graph recurrence object."""
    kind = spec.get("type")
    interval = int(spec.get("interval") or 1)
    if not 1 <= interval <= 999:
        raise ValueError("Repeat interval is out of range.")
    day = lambda name: str(name).lower()
    index = spec.get("ordinal")
    if kind == "daily" and spec.get("weekdaysOnly"):
        pattern = {"type": "weekly", "interval": 1, "daysOfWeek": ["monday", "tuesday", "wednesday", "thursday", "friday"]}
    elif kind == "daily":
        pattern = {"type": "daily", "interval": interval}
    elif kind == "weekly":
        days = [day(d) for d in spec.get("days") or []]
        if not days:
            raise ValueError("Pick at least one weekday.")
        pattern = {"type": "weekly", "interval": interval, "daysOfWeek": days, "firstDayOfWeek": "sunday"}
    elif kind == "monthly" and spec.get("mode") == "nth":
        if index not in _INDEXES:
            raise ValueError("Unknown week of the month.")
        pattern = {"type": "relativeMonthly", "interval": interval, "daysOfWeek": [day(spec.get("weekday"))], "index": index}
    elif kind == "monthly":
        pattern = {"type": "absoluteMonthly", "interval": interval, "dayOfMonth": int(spec.get("day") or 1)}
    elif kind == "yearly" and spec.get("mode") == "nth":
        if index not in _INDEXES:
            raise ValueError("Unknown week of the month.")
        pattern = {
            "type": "relativeYearly",
            "interval": interval,
            "daysOfWeek": [day(spec.get("weekday"))],
            "index": index,
            "month": int(spec.get("month") or 1),
        }
    elif kind == "yearly":
        pattern = {
            "type": "absoluteYearly",
            "interval": interval,
            "dayOfMonth": int(spec.get("day") or 1),
            "month": int(spec.get("month") or 1),
        }
    else:
        raise ValueError("Unknown repeat type.")
    end = spec.get("end")
    if end == "date" and spec.get("endDate"):
        rng = {"type": "endDate", "startDate": start_date, "endDate": spec["endDate"]}
    elif end == "count":
        rng = {"type": "numbered", "startDate": start_date, "numberOfOccurrences": max(1, int(spec.get("count") or 1))}
    elif end == "none":
        rng = {"type": "noEnd", "startDate": start_date}
    else:
        raise ValueError("Choose when the repeat ends.")
    return {"pattern": pattern, "range": rng}


@router.post("/api/calendar/grid-draft-series", dependencies=[Depends(verify_csrf)])
async def tp_calendar_grid_draft_series(req: GridSeriesRequest):
    """Creates the grid's picked slot as an unsent draft event (recurring when a repeat is given) and returns its Outlook web link."""
    import asyncio

    from routes.drafts import _calendar_event_payload
    from skills._m365.helpers import get_cal_client

    recurrence = None
    if req.repeat:
        try:
            recurrence = _graph_recurrence(req.repeat, req.start[:10])
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
    if not (req.attendees or req.optional_attendees):
        raise HTTPException(status_code=400, detail="No attendees specified")
    event = _calendar_event_payload(
        {
            "start": req.start,
            "end": req.end,
            "timezone": req.timezone,
            "attendees": req.attendees,
            "optional_attendees": req.optional_attendees,
            "recurrence": recurrence,
        }
    )
    event["isDraft"] = True
    try:
        created = await asyncio.to_thread(lambda: get_cal_client().post("/me/events", event))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Outlook did not create the draft ({e}). Check your calendar before trying again.")
    return {"url": (created or {}).get("webLink") or "https://outlook.office.com/calendar"}


@router.post("/api/calendar/availability-days", dependencies=[Depends(verify_csrf)])
async def tp_calendar_availability_days(req: AvailabilityDaysRequest):
    """Free/busy for the availability grid's "later weeks" button (after_date) and "add person" (dates)."""
    import asyncio

    from skills.calendar.tools import _tool_load_availability_days

    if len(req.emails) > 20:
        raise HTTPException(status_code=400, detail="Too many people.")
    try:
        result = await asyncio.to_thread(
            _tool_load_availability_days, req.emails, req.after_date, req.duration_minutes, 10, req.dates
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
