from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from routes.calendar import _graph_recurrence
from security import get_csrf_token

BODY = {
    "start": "2026-11-03T09:00:00",
    "end": "2026-11-03T09:30:00",
    "timezone": "Pacific Standard Time",
    "attendees": ["a@x.com"],
    "optional_attendees": ["c@z.com"],
    "repeat": {"type": "weekly", "interval": 2, "days": ["Tuesday", "Wednesday"], "end": "count", "count": 10},
}


@pytest.fixture(autouse=True)
def _forget_grid_drafts():
    from routes import calendar

    calendar._grid_drafts.clear()
    yield
    calendar._grid_drafts.clear()


def _post(body):
    return TestClient(app).post(
        "/api/calendar/grid-draft-series", headers={"X-CSRF-Token": get_csrf_token("testserver")}, json=body
    )


@pytest.mark.parametrize(
    "spec, pattern, rng",
    [
        (
            {"type": "daily", "interval": 3, "end": "none"},
            {"type": "daily", "interval": 3},
            {"type": "noEnd", "startDate": "2026-11-03"},
        ),
        (
            {"type": "daily", "weekdaysOnly": True, "end": "none"},
            {"type": "weekly", "interval": 1, "daysOfWeek": ["monday", "tuesday", "wednesday", "thursday", "friday"]},
            {"type": "noEnd", "startDate": "2026-11-03"},
        ),
        (
            {"type": "weekly", "interval": 2, "days": ["Tuesday", "Wednesday"], "end": "count", "count": 10},
            {"type": "weekly", "interval": 2, "daysOfWeek": ["tuesday", "wednesday"], "firstDayOfWeek": "sunday"},
            {"type": "numbered", "startDate": "2026-11-03", "numberOfOccurrences": 10},
        ),
        (
            {"type": "monthly", "mode": "day", "day": 15, "interval": 1, "end": "date", "endDate": "2027-04-18"},
            {"type": "absoluteMonthly", "interval": 1, "dayOfMonth": 15},
            {"type": "endDate", "startDate": "2026-11-03", "endDate": "2027-04-18"},
        ),
        (
            {"type": "monthly", "mode": "nth", "ordinal": "first", "weekday": "Sunday", "interval": 3, "end": "none"},
            {"type": "relativeMonthly", "interval": 3, "daysOfWeek": ["sunday"], "index": "first"},
            {"type": "noEnd", "startDate": "2026-11-03"},
        ),
        (
            {"type": "yearly", "mode": "date", "month": 11, "day": 1, "interval": 1, "end": "none"},
            {"type": "absoluteYearly", "interval": 1, "dayOfMonth": 1, "month": 11},
            {"type": "noEnd", "startDate": "2026-11-03"},
        ),
        (
            {"type": "yearly", "mode": "nth", "ordinal": "last", "weekday": "Friday", "month": 3, "interval": 2, "end": "none"},
            {"type": "relativeYearly", "interval": 2, "daysOfWeek": ["friday"], "index": "last", "month": 3},
            {"type": "noEnd", "startDate": "2026-11-03"},
        ),
    ],
)
def test_grid_repeat_becomes_a_graph_recurrence(spec, pattern, rng):
    assert _graph_recurrence(spec, "2026-11-03") == {"pattern": pattern, "range": rng}


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "weekly", "days": [], "end": "none"},
        {"type": "hourly", "end": "none"},
        {"type": "daily", "end": "date"},
        {"type": "monthly", "mode": "nth", "ordinal": "fifth", "weekday": "Monday", "end": "none"},
    ],
)
def test_incomplete_grid_repeat_is_rejected(spec):
    with pytest.raises(ValueError):
        _graph_recurrence(spec, "2026-11-03")


def test_route_creates_an_unsent_draft_series_and_returns_its_link():
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(BODY)
    assert res.status_code == 200
    assert res.json() == {"url": "https://outlook.office365.com/owa/?itemid=evt1"}
    path, event = gc.post.call_args.args
    assert path == "/me/events"
    assert event["isDraft"] is True
    assert event["start"] == {"dateTime": BODY["start"], "timeZone": BODY["timezone"]}
    assert [(a["emailAddress"]["address"], a["type"]) for a in event["attendees"]] == [
        ("a@x.com", "required"),
        ("c@z.com", "optional"),
    ]
    assert event["recurrence"]["pattern"]["type"] == "weekly"
    assert event["recurrence"]["range"]["startDate"] == "2026-11-03"


def test_route_without_a_repeat_creates_a_one_time_draft_with_optional_attendees():
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post({k: v for k, v in BODY.items() if k != "repeat"})
    assert res.status_code == 200
    event = gc.post.call_args.args[1]
    assert event["isDraft"] is True and "recurrence" not in event
    assert [(a["emailAddress"]["address"], a["type"]) for a in event["attendees"]] == [
        ("a@x.com", "required"),
        ("c@z.com", "optional"),
    ]


def test_route_rejects_a_bad_repeat_without_calling_graph():
    with patch("skills._m365.helpers.get_cal_client", side_effect=AssertionError("no Graph call")):
        res = _post({**BODY, "repeat": {"type": "weekly", "days": [], "end": "none"}})
    assert res.status_code == 400


def test_route_tells_the_user_to_check_outlook_when_graph_fails():
    gc = MagicMock()
    gc.post.side_effect = RuntimeError("gateway timeout")
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(BODY)
    assert res.status_code == 502
    assert "Check your calendar" in res.json()["detail"]


def test_route_carries_the_title_and_message_into_the_draft():
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post({**BODY, "subject": "Design sync", "body": "Agenda: roadmap"})
    assert res.status_code == 200
    event = gc.post.call_args.args[1]
    assert event["subject"] == "Design sync"
    assert event["body"] == {"contentType": "text", "content": "Agenda: roadmap"}


@pytest.mark.parametrize("plain, content_type", [(False, "HTML"), (True, "text")])
def test_route_sends_html_unless_the_message_was_edited_as_plain_text(plain, content_type):
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post({**BODY, "body": "<p>Agenda</p>", "body_plain": plain})
    assert res.status_code == 200
    assert gc.post.call_args.args[1]["body"] == {"contentType": content_type, "content": "<p>Agenda</p>"}


def test_route_tells_the_user_not_to_retry_when_the_event_was_not_held_as_a_draft():
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}
    gc.get.return_value = {"isDraft": False}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(BODY)
    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "invites may have gone out" in detail and "do not try again" in detail
    assert "before trying again" not in detail
    assert "outlook.office365.com" not in res.text


def test_the_same_pick_sent_twice_creates_one_event_and_returns_the_same_link():
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}
    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        first = _post(BODY)
        second = _post(BODY)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert gc.post.call_count == 1


def test_a_different_pick_still_creates_its_own_event():
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}
    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        _post(BODY)
        _post({**BODY, "start": "2026-11-04T09:00:00", "end": "2026-11-04T09:30:00"})
    assert gc.post.call_count == 2


def test_a_retry_after_a_failure_is_allowed_but_a_not_held_refusal_is_replayed_without_another_create():
    gc = MagicMock()
    gc.post.side_effect = [RuntimeError("gateway timeout"), {"id": "evt1", "webLink": "https://x/evt1"}]
    gc.get.return_value = {"isDraft": False}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        assert _post(BODY).status_code == 502
        assert gc.post.call_count == 1
        second = _post(BODY)
        assert second.status_code == 502 and "do not try again" in second.json()["detail"]
        assert gc.post.call_count == 2
        third = _post(BODY)
    assert third.status_code == 502 and "do not try again" in third.json()["detail"]
    assert gc.post.call_count == 2
