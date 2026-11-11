"""The availability grid payload: per-person status per half hour, and columns where everyone is free."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

from skills.calendar.tools import _tool_show_availability_grid


class _Gc:
    """Answers each getSchedule with the person's one-day view repeated for every day in the range."""

    def __init__(self, views, dst_shift=False):
        self.views = views
        self.dst_shift = dst_shift
        self.calls = []

    def post(self, path, body):
        self.calls.append(body)
        first = datetime.fromisoformat(body["startTime"]["dateTime"])
        last = datetime.fromisoformat(body["endTime"]["dateTime"])
        n_days = (last - first).days
        trim = 2 if self.dst_shift and n_days > 1 else 0
        return {
            "value": [
                {"scheduleId": e, "availabilityView": (self.views[e] * n_days)[: len(self.views[e]) * n_days - trim]}
                for e in body["schedules"]
                if e in self.views
            ]
        }


class _ZoneGc(_Gc):
    """Adds working hours to the one-hour getSchedule that reads each person's time zone."""

    def __init__(self, views, zones):
        super().__init__(views)
        self.zones = zones

    def post(self, path, body):
        out = super().post(path, body)
        if body.get("availabilityViewInterval") == 60:
            for item in out["value"]:
                zone = self.zones.get(item["scheduleId"])
                if zone:
                    item["workingHours"] = {
                        "timeZone": {"name": zone},
                        "startTime": "08:00:00.0000000",
                        "endTime": "17:00:00.0000000",
                    }
        return out


def _run(views, gc=None, **kw):
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401

    gc = gc or _Gc(views)
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills._m365.helpers.get_cached_me", return_value={"mail": "me@example.com"}),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        return _tool_show_availability_grid(**kw), gc


def test_everyone_free_columns_are_marked_and_one_hour_needs_two_free_halves():
    me = "0" * 48
    sherry = "0" * 16 + "22" + "0" * 17 + "2" + "0" * 12
    out, gc = _run({"me@example.com": me, "sherry@example.com": sherry}, attendees=["Sherry@Example.com"], dates=["2030-01-07"], duration_minutes=60)
    grid = out["_availability_grid"]
    assert [p["email"] for p in grid["people"]] == ["me@example.com", "sherry@example.com"]
    assert grid["people"][0]["you"] and grid["people"][1]["name"] == "Sherry"
    day = grid["days"][0]
    assert day["rows"] == ["f" * 48, "f" * 16 + "bb" + "f" * 17 + "b" + "f" * 12]
    assert day["fit"] == "0" * 18 + "1" * 16 + "0" * 14
    assert grid["first_minute"] == 0 and grid["work_start_minute"] == 480 and grid["work_end_minute"] == 1080
    assert not grid["people"][1]["optional"]
    assert out["mutual_free_examples"][0] == "Monday, Jan 7, 9:00 AM - 10:00 AM"
    assert gc.calls[0]["availabilityViewInterval"] == 30


def test_repeat_defaults_to_one_time_and_accepts_a_known_cadence():
    views = {"me@example.com": "0" * 48}
    base = {"attendees": ["a@example.com"], "dates": ["2030-01-07"]}
    assert _run(views, **base)[0]["_availability_grid"]["repeat"] == "none"
    assert _run(views, recurrence="Weekly", **base)[0]["_availability_grid"]["repeat"] == "weekly"
    assert _run(views, recurrence="Yearly", **base)[0]["_availability_grid"]["repeat"] == "yearly"
    assert _run(views, recurrence="daily", **base)[0]["_availability_grid"]["repeat"] == "daily"
    assert _run(views, recurrence="every other tuesday", **base)[0]["_availability_grid"]["repeat"] == "none"


def test_a_person_with_no_data_does_not_block_and_shows_unknown():
    out, _ = _run({"me@example.com": "0" * 48}, attendees=["ghost@example.com"], dates=["2030-01-07"])
    day = out["_availability_grid"]["days"][0]
    assert day["rows"][1] == "?" * 48
    assert day["fit"] == "0" * 16 + "1" * 20 + "0" * 12
    assert day["open"] == day["fit"]


def test_defaults_to_the_next_ten_working_days():
    out, _ = _run({"me@example.com": "0" * 48}, attendees=["a@example.com"])
    days = out["_availability_grid"]["days"]
    assert len(days) == 10
    assert all(__import__("datetime").date.fromisoformat(d["date"]).weekday() < 5 for d in days)


def test_explicit_dates_go_past_two_weeks_in_order():
    dates = [f"2030-01-{d:02d}" for d in range(7, 28)]
    out, _ = _run({"me@example.com": "0" * 48}, attendees=["a@example.com"], dates=dates)
    days = out["_availability_grid"]["days"]
    assert [d["date"] for d in days] == dates[:20]


def test_requires_an_attendee_other_than_the_user():
    out, _ = _run({}, attendees=["me@example.com"])
    assert "error" in out


def test_later_weeks_returns_the_next_working_days_after_a_date_in_people_order():
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401
    from skills.calendar.tools import _tool_load_availability_days

    after = date.today() + timedelta(days=7)
    gc = _Gc({"me@example.com": "0" * 48, "sherry@example.com": "2" * 48})
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        out = _tool_load_availability_days(["me@example.com", "sherry@example.com"], after.isoformat(), 30, 3)
    dates = [date.fromisoformat(d["date"]) for d in out["days"]]
    assert len(dates) == 3 and dates == sorted(dates) and all(d > after and d.weekday() < 5 for d in dates)
    assert out["days"][0]["rows"] == ["f" * 48, "b" * 48]
    assert out["days"][0]["fit"] == "0" * 48
    assert out["days"][0]["open"] == "0" * 16 + "1" * 20 + "0" * 12


def test_adding_a_person_loads_the_same_dates_in_order():
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401
    from skills.calendar.tools import _tool_load_availability_days

    start = date.today() + timedelta(days=30)
    dates = [(start + timedelta(days=n)).isoformat() for n in (3, 0, 1)]
    gc = _Gc({"new@example.com": "0" * 48})
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        out = _tool_load_availability_days(["new@example.com"], dates=dates)
    assert [d["date"] for d in out["days"]] == dates
    assert all(d["rows"] == ["f" * 48] for d in out["days"])
    assert gc.calls[0]["endTime"]["dateTime"].endswith("T00:00:00")


def test_later_weeks_rejects_a_bad_or_far_future_date():
    from skills.calendar.tools import _tool_load_availability_days

    assert "error" in _tool_load_availability_days(["a@example.com"], "not-a-date")
    assert "error" in _tool_load_availability_days(["a@example.com"], "2999-01-01")


def test_consecutive_days_are_read_in_one_call_and_split_per_day():
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401
    from skills.calendar.tools import _tool_load_availability_days

    start = date.today() + timedelta(days=30)
    dates = [(start + timedelta(days=n)).isoformat() for n in range(5)]
    gc = _Gc({"new@example.com": "0" * 20 + "2" * 4 + "0" * 24})
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        out = _tool_load_availability_days(["new@example.com"], dates=dates)
    assert len(gc.calls) == 1
    assert all(d["rows"] == ["f" * 20 + "b" * 4 + "f" * 24] for d in out["days"])
    assert [d["date"] for d in out["days"]] == dates


def test_a_range_with_a_shifted_slot_count_is_read_day_by_day():
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401
    from skills.calendar.tools import _tool_load_availability_days

    start = date.today() + timedelta(days=30)
    dates = [(start + timedelta(days=n)).isoformat() for n in range(3)]
    gc = _Gc({"new@example.com": "0" * 20 + "2" * 4 + "0" * 24}, dst_shift=True)
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        out = _tool_load_availability_days(["new@example.com"], dates=dates)
    assert len(gc.calls) == 1 + 3
    assert all(d["rows"] == ["f" * 20 + "b" * 4 + "f" * 24] for d in out["days"])


def test_days_with_a_gap_are_separate_runs():
    from skills.calendar.tools import _grid_day_runs

    start = date(2030, 1, 7)
    days = [start + timedelta(days=n) for n in (0, 1, 2, 3, 4, 7, 8)]
    assert [len(r) for r in _grid_day_runs(days)] == [5, 2]
    assert [len(r) for r in _grid_day_runs([start + timedelta(days=n) for n in range(9)])] == [7, 2]


class _FixedViewGc:
    def __init__(self, views):
        self.views = views

    def post(self, path, body):
        return {"value": [{"scheduleId": e, "availabilityView": self.views[e]} for e in body["schedules"]]}


def _eastern_day(day, view):
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401
    from skills.calendar.tools import _tool_load_availability_days

    with (
        patch("skills._m365.helpers.get_cal_client", return_value=_FixedViewGc({"a@example.com": view})),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Eastern Standard Time"),
    ):
        return _tool_load_availability_days(["a@example.com"], dates=[day])["days"][0]["rows"][0]


def test_a_spring_forward_day_reads_each_slot_at_its_elapsed_position():
    # 23 hours, 46 half hours: 10:00 AM wall time is the 18th half hour elapsed.
    row = _eastern_day("2027-03-14", "0" * 18 + "2" + "0" * 27)
    assert row[20] == "b" and row[18] == "f" and row[19] == "f"
    assert row[4:6] == "??"
    assert row[:4] == "f" * 4 and len(row) == 48


def test_a_fall_back_day_reads_each_slot_at_its_elapsed_position():
    # 25 hours, 50 half hours: 2:00 AM wall time follows the repeated 1:00 hour, so it is the 7th half hour.
    row = _eastern_day("2026-11-01", "0" * 6 + "2" + "0" * 43)
    assert row[4] == "b" and row[6] == "f" and row[2] == "f"
    assert len(row) == 48


def test_people_carry_their_time_zone_from_working_hours():
    views = {e: "0" * 48 for e in ("me@example.com", "tej@example.com", "faisal@example.com", "ghost@example.com")}
    gc = _ZoneGc(views, {"tej@example.com": "Central Standard Time", "faisal@example.com": "GMT Standard Time"})
    out, _ = _run(
        views,
        gc=gc,
        attendees=["tej@example.com", "faisal@example.com", "ghost@example.com"],
        dates=["2030-01-07"],
    )
    zones = {p["email"]: p.get("timezone") for p in out["_availability_grid"]["people"]}
    assert zones == {
        "me@example.com": None,
        "tej@example.com": "Central Standard Time",
        "faisal@example.com": "GMT Standard Time",
        "ghost@example.com": None,
    }


def test_the_grid_carries_the_title_and_message_it_was_given():
    views = {"me@example.com": "0" * 48}
    base = {"attendees": ["a@example.com"], "dates": ["2030-01-07"]}
    grid = _run(views, subject="Design sync", body="Agenda: roadmap", **base)[0]["_availability_grid"]
    assert grid["subject"] == "Design sync" and grid["body"] == "Agenda: roadmap"
    grid = _run(views, **base)[0]["_availability_grid"]
    assert grid["subject"] == "" and grid["body"] == ""


def test_adding_a_person_can_return_their_zone():
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401
    from skills.calendar.tools import _tool_load_availability_days

    dates = [(date.today() + timedelta(days=30)).isoformat()]
    gc = _ZoneGc({"new@example.com": "0" * 48}, {"new@example.com": "Arabian Standard Time"})
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        with_zones = _tool_load_availability_days(["new@example.com"], dates=dates, with_zones=True)
        without = _tool_load_availability_days(["new@example.com"], dates=dates)
    assert with_zones["zones"] == {"new@example.com": "Arabian Standard Time"}
    assert "zones" not in without


def _free_except(*slots):
    return "".join("2" if i in slots else "0" for i in range(48))


def test_the_grid_opens_on_the_first_slot_everyone_is_free():
    out, _ = _run({"me@example.com": "0" * 48, "sam@example.com": "0" * 48}, attendees=["sam@example.com"], dates=["2030-01-07"])
    assert out["_availability_grid"]["pick"] == {"date": "2030-01-07", "minute": 480}


def test_the_grid_opens_on_the_asked_time_even_outside_work_hours():
    views = {"me@example.com": "0" * 48, "sam@example.com": "0" * 48}
    out, _ = _run(views, attendees=["sam@example.com"], dates=["2030-01-07", "2030-01-08"], start_time="18:00")
    assert out["_availability_grid"]["pick"] == {"date": "2030-01-07", "minute": 1080}


def test_the_grid_falls_back_when_someone_is_busy_at_the_asked_time():
    views = {"me@example.com": "0" * 48, "sam@example.com": _free_except(36)}
    out, _ = _run(views, attendees=["sam@example.com"], dates=["2030-01-07"], start_time="18:00")
    assert out["_availability_grid"]["pick"] == {"date": "2030-01-07", "minute": 480}


def test_the_grid_falls_back_when_the_asked_time_is_not_a_time():
    views = {"me@example.com": "0" * 48, "sam@example.com": "0" * 48}
    out, _ = _run(views, attendees=["sam@example.com"], dates=["2030-01-07"], start_time="evening")
    assert out["_availability_grid"]["pick"] == {"date": "2030-01-07", "minute": 480}


def test_the_grid_has_no_pick_when_nobody_fits():
    views = {"me@example.com": "2" * 48, "sam@example.com": "0" * 48}
    out, _ = _run(views, attendees=["sam@example.com"], dates=["2030-01-07"])
    assert out["_availability_grid"]["pick"] is None


def test_the_grids_now_is_the_mailbox_clock_not_the_computers():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from skills.calendar.tools import _mailbox_now

    expected = datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
    got = _mailbox_now("Tokyo Standard Time")
    assert got.tzinfo is None and abs((got - expected).total_seconds()) < 5
    assert _mailbox_now("No Such Zone").tzinfo is None
