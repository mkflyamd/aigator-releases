"""A multi-day calendar read returns every event, with dates, and says when it had to stop early."""
from unittest.mock import MagicMock, patch

from skills.calendar import helpers as cal_helpers
from skills.calendar.tools import _tool_read_calendar
from skills._m365 import helpers as m365_helpers


def _event(i, day):
    return {
        "id": f"E{i}",
        "subject": f"Meeting {i}",
        "start": {"dateTime": f"2026-11-{day:02d}T09:00:00.0000000"},
        "end": {"dateTime": f"2026-11-{day:02d}T09:30:00.0000000"},
    }


def _read(gc):
    with patch.object(m365_helpers, "get_cal_client", return_value=gc), patch.object(
        cal_helpers, "get_user_win_tz", return_value="Pacific Standard Time"
    ):
        return _tool_read_calendar("2026-10-30", 7)


def test_events_past_the_first_page_are_returned():
    gc = MagicMock()
    gc.get.return_value = {"value": [_event(i, 2) for i in range(100)], "@odata.nextLink": "https://graph/next"}
    gc.get_absolute.return_value = {"value": [_event(100 + i, 4) for i in range(30)]}

    result = _read(gc)

    assert len(result["events"]) == 130
    assert result["events"][-1]["date"] == "2026-11-04"
    assert "truncated" not in result
    assert gc.get_absolute.call_args.kwargs["extra_headers"]["Prefer"].startswith("outlook.timezone=")


def test_every_event_carries_its_date():
    gc = MagicMock()
    gc.get.return_value = {"value": [_event(1, 2), _event(2, 3)]}

    result = _read(gc)

    assert [e["date"] for e in result["events"]] == ["2026-11-02", "2026-11-03"]
    assert result["events"][0]["start"] == "9:00 AM"


def test_a_read_that_hits_the_cap_says_it_is_incomplete():
    gc = MagicMock()
    gc.get.return_value = {"value": [_event(i, 2) for i in range(100)], "@odata.nextLink": "https://graph/p2"}
    gc.get_absolute.return_value = {"value": [_event(100 + i, 3) for i in range(100)], "@odata.nextLink": "https://graph/p3"}

    result = _read(gc)

    assert len(result["events"]) == 200
    assert result["truncated"] is True
    assert "2026-11-03" in result["note"]
    assert gc.get_absolute.call_count == 1
