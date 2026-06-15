"""Calendar-specific time utilities."""
from datetime import datetime, timedelta, timezone
from .._m365.helpers import get_cal_client

_user_win_tz_cache: str | None = None


def get_user_win_tz() -> str:
    global _user_win_tz_cache
    if _user_win_tz_cache:
        return _user_win_tz_cache
    try:
        gc = get_cal_client()
        settings = gc.get("/me/mailboxSettings")
        _user_win_tz_cache = settings.get("timeZone", "UTC")
    except Exception:
        _user_win_tz_cache = "UTC"
    return _user_win_tz_cache


def fmt_cal_time(dt_str: str) -> str:
    try:
        t = datetime.fromisoformat(dt_str.split("+")[0].rstrip("Z"))
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return dt_str[:5]


def cal_day_range_utc(date: str, days: int = 1):
    local_tz = datetime.now().astimezone().tzinfo
    if date:
        day = datetime.fromisoformat(date).replace(tzinfo=local_tz)
    else:
        day = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    end = start + timedelta(days=max(days, 1))
    return start, end
