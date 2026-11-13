from zoneinfo import ZoneInfo

from skills.calendar import timezones as tz


def test_every_mapped_zone_loads():
    for iana in tz.WINDOWS_TO_IANA.values():
        ZoneInfo(iana)


def test_zone_accepts_windows_and_iana_names():
    assert tz.zone("Pacific Standard Time").key == "America/Los_Angeles"
    assert tz.zone("Europe/London").key == "Europe/London"
    assert tz.zone("No Such Zone") is None


def test_fmt_range_converts_and_flags_day_shift():
    out = tz.fmt_range("2026-11-02T09:00:00.0000000", "2026-11-02T09:30:00.0000000",
                       "Pacific Standard Time", "India Standard Time")
    assert out == "10:30 PM – 11:00 PM IST"
    late = tz.fmt_range("2026-11-02T20:00:00.0000000", "2026-11-02T20:30:00.0000000",
                        "Pacific Standard Time", "India Standard Time")
    assert late.endswith("(+1 day)")


def test_fmt_range_unknown_zone_is_none():
    assert tz.fmt_range("2026-11-02T09:00:00", "2026-11-02T09:30:00", "Pacific Standard Time", "Nope") is None


def test_attendee_zones_reads_working_hours():
    class GC:
        def post(self, path, body, **kw):
            return {"value": [{"scheduleId": "A@x.com", "workingHours": {
                "startTime": "08:00:00.0000000", "endTime": "17:00:00.0000000",
                "timeZone": {"name": "India Standard Time"}}}]}
    out = tz.attendee_zones(GC(), ["a@x.com"], "2026-11-02", "Pacific Standard Time")
    assert out["a@x.com"] == {"timezone": "India Standard Time", "working_hours": "8:00 AM – 5:00 PM"}


def test_attendee_zones_swallows_errors():
    class GC:
        def post(self, *a, **k):
            raise RuntimeError("boom")
    assert tz.attendee_zones(GC(), ["a@x.com"], "2026-11-02", "UTC") == {}


import pytest


class _Client:
    def __init__(self, schedule_fails=False):
        self.calls = []
        self.schedule_fails = schedule_fails

    def post(self, path, body, **kw):
        self.calls.append((path, body))
        if path.endswith("getSchedule"):
            if self.schedule_fails:
                raise RuntimeError("AADSTS65002")
            return {"value": [{"scheduleId": "a@x.com", "workingHours": {
                "startTime": "08:00:00.0000000", "endTime": "17:00:00.0000000",
                "timeZone": {"name": "India Standard Time"}}}]}
        return {"meetingTimeSuggestions": [{"confidence": 100, "meetingTimeSlot": {
            "start": {"dateTime": "2026-11-02T09:00:00.0000000", "timeZone": "Pacific Standard Time"},
            "end": {"dateTime": "2026-11-02T09:30:00.0000000", "timeZone": "Pacific Standard Time"}}}]}


@pytest.fixture
def cal(monkeypatch):
    import skills._m365.helpers as m365
    import skills.calendar.helpers as cal_helpers
    import skills.calendar.tools as tools

    client = _Client()
    monkeypatch.setattr(m365, "get_cal_client", lambda: client, raising=False)
    monkeypatch.setattr(cal_helpers, "get_user_win_tz", lambda: "Pacific Standard Time", raising=False)
    tools._test_client = client
    return tools


def _find_call(client):
    return next(b for p, b in client.calls if p.endswith("findMeetingTimes"))


def test_every_slot_has_a_timezone_label_and_attendee_local_time(cal):
    out = cal._tool_find_meeting_times(["a@x.com"], date="2026-11-02")
    slot = out["suggestions"][0]
    assert slot["timezone"] == "Pacific Standard Time"
    assert slot["attendee_local"]["a@x.com"] == "10:30 PM – 11:00 PM IST"
    assert out["attendee_timezones"]["a@x.com"]["timezone"] == "India Standard Time"
    assert out["ignore_timezones"] is False


def test_ignore_timezones_searches_unrestricted(cal):
    cal._tool_find_meeting_times(["a@x.com"], date="2026-11-02", ignore_timezones=True)
    assert _find_call(cal._test_client)["timeConstraint"]["activityDomain"] == "unrestricted"


def test_default_search_does_not_use_unrestricted(cal):
    cal._tool_find_meeting_times(["a@x.com"], date="2026-11-02")
    assert _find_call(cal._test_client)["timeConstraint"].get("activityDomain") != "unrestricted"


def test_slots_still_returned_when_schedule_lookup_fails(cal, monkeypatch):
    import skills._m365.helpers as m365
    failing = _Client(schedule_fails=True)
    monkeypatch.setattr(m365, "get_cal_client", lambda: failing, raising=False)
    out = cal._tool_find_meeting_times(["a@x.com"], date="2026-11-02")
    assert out["suggestions"][0]["timezone"] == "Pacific Standard Time"
    assert out["attendee_timezones"] == {}


def test_an_attendee_zone_that_cannot_be_resolved_gets_no_local_time(cal, monkeypatch):
    monkeypatch.setattr(
        tz, "attendee_zones",
        lambda gc, emails, day, win_tz: {"a@x.com": {"timezone": "Pakistan Standard Time", "working_hours": ""}},
    )
    slot = cal._tool_find_meeting_times(["a@x.com"], date="2026-11-02")["suggestions"][0]
    assert "a@x.com" not in slot["attendee_local"]
