"""Timezone helpers for meeting slots: Windows zone names (Graph) to IANA, and attendee-local formatting."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

WINDOWS_TO_IANA = {
    "UTC": "UTC",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "Central European Standard Time": "Europe/Warsaw",
    "E. Europe Standard Time": "Europe/Chisinau",
    "GTB Standard Time": "Europe/Bucharest",
    "FLE Standard Time": "Europe/Kyiv",
    "Russian Standard Time": "Europe/Moscow",
    "Turkey Standard Time": "Europe/Istanbul",
    "Israel Standard Time": "Asia/Jerusalem",
    "Arabian Standard Time": "Asia/Dubai",
    "Arab Standard Time": "Asia/Riyadh",
    "India Standard Time": "Asia/Kolkata",
    "Nepal Standard Time": "Asia/Kathmandu",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "SE Asia Standard Time": "Asia/Bangkok",
    "China Standard Time": "Asia/Shanghai",
    "Singapore Standard Time": "Asia/Singapore",
    "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "E. Australia Standard Time": "Australia/Brisbane",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Pacific Standard Time": "America/Los_Angeles",
    "Mountain Standard Time": "America/Denver",
    "US Mountain Standard Time": "America/Phoenix",
    "Central Standard Time": "America/Chicago",
    "Eastern Standard Time": "America/New_York",
    "US Eastern Standard Time": "America/Indiana/Indianapolis",
    "Atlantic Standard Time": "America/Halifax",
    "Canada Central Standard Time": "America/Regina",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Alaskan Standard Time": "America/Anchorage",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Buenos_Aires",
    "SA Pacific Standard Time": "America/Bogota",
    "Mexico Standard Time": "America/Mexico_City",
    "South Africa Standard Time": "Africa/Johannesburg",
    "Egypt Standard Time": "Africa/Cairo",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "E. Africa Standard Time": "Africa/Nairobi",
}


def zone(name: str) -> ZoneInfo | None:
    """ZoneInfo for a Windows or IANA zone name, or None when it can't be resolved."""
    try:
        return ZoneInfo(WINDOWS_TO_IANA.get(name, name))
    except Exception:
        return None


def _parse(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str.split(".")[0].rstrip("Z"))


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def fmt_range(start: str, end: str, from_tz: str, to_tz: str) -> str | None:
    """"9:00 AM – 9:30 AM PST" for a slot given in from_tz, shown in to_tz; None when a zone is unknown."""
    src, dst = zone(from_tz), zone(to_tz)
    if src is None or dst is None:
        return None
    try:
        s = _parse(start).replace(tzinfo=src)
        e = _parse(end).replace(tzinfo=src)
    except ValueError:
        return None
    s_dst, e_dst = s.astimezone(dst), e.astimezone(dst)
    out = f"{_clock(s_dst)} – {_clock(e_dst)} {s_dst.tzname()}"
    shift = (s_dst.date() - s.date()).days
    if shift:
        out += f" ({shift:+d} day)"
    return out


def _hours(value: str) -> str:
    return _clock(datetime.strptime(value.split(".")[0], "%H:%M:%S"))


def attendee_zones(gc, emails: list[str], day: str, win_tz: str) -> dict[str, dict]:
    """{email: {"timezone", "working_hours"}} from getSchedule; {} when the lookup fails."""
    if not emails or not day:
        return {}
    try:
        result = gc.post(
            "/me/calendar/getSchedule",
            {
                "schedules": list(emails),
                "startTime": {"dateTime": f"{day}T08:00:00", "timeZone": win_tz},
                "endTime": {"dateTime": f"{day}T09:00:00", "timeZone": win_tz},
                "availabilityViewInterval": 60,
            },
        )
        out: dict[str, dict] = {}
        for item in result.get("value", []):
            wh = item.get("workingHours") or {}
            name = (wh.get("timeZone") or {}).get("name", "")
            if not name:
                continue
            out[item.get("scheduleId", "").lower()] = {
                "timezone": name,
                "working_hours": f"{_hours(wh['startTime'])} – {_hours(wh['endTime'])}",
            }
        return out
    except Exception:
        return {}
