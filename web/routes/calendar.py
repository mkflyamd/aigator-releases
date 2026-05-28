"""Calendar route group -- calendar view, event detail, RSVP."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import shared

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────


class CalendarRsvpRequest(BaseModel):
    response: str  # "accept", "decline", or "tentativelyAccept"
    send_response: bool = True


# ── Calendar third-pane endpoints ────────────────────────────────────────────


@router.get("/api/calendar/events")
async def tp_calendar_events(start: str, end: str):
    """Return events in FullCalendar format for a date range."""
    try:
        from skills._m365.helpers import get_cal_client
        from skills.calendar.helpers import get_user_win_tz
        gc = get_cal_client()
        win_tz = get_user_win_tz()
        result = gc.get("/me/calendarView", params={
            "startDateTime": start,
            "endDateTime": end,
            "$top": "50",
            "$select": "id,subject,start,end,location,isAllDay,organizer,attendees,bodyPreview,isOnlineMeeting,onlineMeeting,showAs,responseStatus",
            "$orderby": "start/dateTime",
        }, extra_headers={"Prefer": f'outlook.timezone="{win_tz}"'})
        return [
            {
                "id": e.get("id", ""),
                "title": e.get("subject", "(no subject)"),
                "start": e.get("start", {}).get("dateTime", ""),
                "end": e.get("end", {}).get("dateTime", ""),
                "allDay": e.get("isAllDay", False),
                "extendedProps": {
                    "location": (e.get("location") or {}).get("displayName", ""),
                    "organizer": (e.get("organizer") or {}).get("emailAddress", {}).get("name", ""),
                    "showAs": e.get("showAs", ""),
                    "responseStatus": (e.get("responseStatus") or {}).get("response", ""),
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
        e = gc.get(f"/me/events/{event_id}", params={
            "$select": "id,subject,start,end,location,isAllDay,organizer,attendees,body,isOnlineMeeting,onlineMeeting,showAs,importance,recurrence,responseStatus,isOrganizer,seriesMasterId,type",
        }, extra_headers={"Prefer": f'outlook.timezone="{win_tz}"'})
        return e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/calendar/events/{event_id}/respond")
async def tp_calendar_respond(event_id: str, req: CalendarRsvpRequest):
    """Accept, decline, or tentatively accept a calendar event."""
    if req.response not in ("accept", "decline", "tentativelyAccept"):
        raise HTTPException(status_code=400, detail="response must be accept, decline, or tentativelyAccept")
    try:
        from skills._m365.helpers import get_cal_client
        gc = get_cal_client()
        try:
            gc.post(f"/me/events/{event_id}/{req.response}", {"sendResponse": req.send_response})
        except RuntimeError as e:
            # If organizer disabled responses, retry without sending a response email
            if "hasn't requested a response" in str(e) and req.send_response:
                gc.post(f"/me/events/{event_id}/{req.response}", {"sendResponse": False})
            else:
                raise
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
