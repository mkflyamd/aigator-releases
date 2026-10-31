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
