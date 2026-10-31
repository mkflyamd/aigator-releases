"""The availability grid payload: per-person status per half hour, and columns where everyone is free."""

from datetime import date, timedelta
from unittest.mock import patch

from skills.calendar.tools import _tool_show_availability_grid


class _Gc:
    def __init__(self, views):
        self.views = views
        self.calls = []

    def post(self, path, body):
        self.calls.append(body)
        return {
            "value": [
                {"scheduleId": e, "availabilityView": self.views[e]}
                for e in body["schedules"]
                if e in self.views
            ]
        }


def _run(views, **kw):
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401

    gc = _Gc(views)
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills._m365.helpers.get_cached_me", return_value={"mail": "me@example.com"}),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        return _tool_show_availability_grid(**kw), gc


def test_everyone_free_columns_are_marked_and_one_hour_needs_two_free_halves():
    me = "0" * 20
    sherry = "22" + "0" * 17 + "2"
    out, gc = _run({"me@example.com": me, "sherry@example.com": sherry}, attendees=["Sherry@Example.com"], dates=["2030-01-07"], duration_minutes=60)
    grid = out["_availability_grid"]
    assert [p["email"] for p in grid["people"]] == ["me@example.com", "sherry@example.com"]
    assert grid["people"][0]["you"] and grid["people"][1]["name"] == "Sherry"
    day = grid["days"][0]
    assert day["rows"] == [me.replace("0", "f"), "bb" + "f" * 17 + "b"]
    assert day["fit"][:2] == "00" and day["fit"][2] == "1"
    assert day["fit"][17] == "1" and day["fit"][18] == "0" and day["fit"][19] == "0"
    assert out["mutual_free_examples"][0] == "Monday, Jan 7, 9:00 AM - 10:00 AM"
    assert gc.calls[0]["availabilityViewInterval"] == 30


def test_a_person_with_no_data_does_not_block_and_shows_unknown():
    out, _ = _run({"me@example.com": "0" * 20}, attendees=["ghost@example.com"], dates=["2030-01-07"])
    day = out["_availability_grid"]["days"][0]
    assert day["rows"][1] == "?" * 20
    assert day["fit"] == "1" * 20


def test_defaults_to_the_next_ten_working_days():
    out, _ = _run({"me@example.com": "0" * 20}, attendees=["a@example.com"])
    days = out["_availability_grid"]["days"]
    assert len(days) == 10
    assert all(__import__("datetime").date.fromisoformat(d["date"]).weekday() < 5 for d in days)


def test_explicit_dates_go_past_two_weeks_in_order():
    dates = [f"2030-01-{d:02d}" for d in range(7, 28)]
    out, _ = _run({"me@example.com": "0" * 20}, attendees=["a@example.com"], dates=dates)
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
    gc = _Gc({"me@example.com": "0" * 20, "sherry@example.com": "2" * 20})
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        out = _tool_load_availability_days(["me@example.com", "sherry@example.com"], after.isoformat(), 30, 3)
    dates = [date.fromisoformat(d["date"]) for d in out["days"]]
    assert len(dates) == 3 and dates == sorted(dates) and all(d > after and d.weekday() < 5 for d in dates)
    assert out["days"][0]["rows"] == ["f" * 20, "b" * 20]
    assert out["days"][0]["fit"] == "0" * 20


def test_later_weeks_rejects_a_bad_or_far_future_date():
    from skills.calendar.tools import _tool_load_availability_days

    assert "error" in _tool_load_availability_days(["a@example.com"], "not-a-date")
    assert "error" in _tool_load_availability_days(["a@example.com"], "2999-01-01")
