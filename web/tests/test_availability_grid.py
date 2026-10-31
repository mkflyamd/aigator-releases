"""The availability grid payload: per-person status per half hour, and columns where everyone is free."""

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


def test_defaults_to_the_next_three_working_days():
    out, _ = _run({"me@example.com": "0" * 20}, attendees=["a@example.com"])
    days = out["_availability_grid"]["days"]
    assert len(days) == 3


def test_requires_an_attendee_other_than_the_user():
    out, _ = _run({}, attendees=["me@example.com"])
    assert "error" in out
