from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token
from skills._drafts import create_draft, get_draft

PARAMS = {
    "subject": "Sync & plan",
    "start": "2026-11-02T09:00:00",
    "end": "2026-11-02T09:30:00",
    "timezone": "Pacific Standard Time",
    "attendees": ["a@x.com", "b@y.com"],
    "optional_attendees": ["c@z.com"],
    "body": '<a href="https://x/Doc.docx">Doc</a>',
    "location": "Room 4",
    "teams": True,
    "recurrence": None,
}


def _post(client, path):
    return client.post(path, headers={"X-CSRF-Token": get_csrf_token("testserver")}, json=None)


def _draft():
    return create_draft("calendar-event", dict(PARAMS), {"subject": "Sync & plan"})


def _compose_draft(**changes):
    return create_draft(
        "calendar-event", {**PARAMS, "optional_attendees": [], **changes}, {"subject": "Sync & plan"}
    )


def test_open_with_an_optional_attendee_creates_a_draft_that_keeps_them_optional():
    client = TestClient(app)
    did = create_draft("calendar-event", dict(PARAMS), {"subject": "Sync & plan"})
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert res.status_code == 200
    assert res.json() == {"url": "https://outlook.office365.com/owa/?itemid=evt1"}
    path, event = gc.post.call_args.args
    assert path == "/me/events" and event["isDraft"] is True
    assert [(a["emailAddress"]["address"], a["type"]) for a in event["attendees"]] == [
        ("a@x.com", "required"),
        ("b@y.com", "required"),
        ("c@z.com", "optional"),
    ]
    assert "recurrence" not in event
    assert get_draft(did)["status"] == "handed_off"


def test_open_returns_compose_deeplink_with_all_fields():
    client = TestClient(app)
    did = _compose_draft()
    with patch("skills._m365.helpers.get_graph_client", side_effect=AssertionError("no Graph call")):
        res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert res.status_code == 200
    url = urlparse(res.json()["url"])
    assert url.netloc == "outlook.office.com" and url.path == "/calendar/0/deeplink/compose"
    q = parse_qs(url.query)
    assert q["subject"] == ["Sync & plan"]
    assert q["to"] == ["a@x.com;b@y.com"]
    assert q["startdt"] == [PARAMS["start"]] and q["enddt"] == [PARAMS["end"]]
    assert q["body"] == [PARAMS["body"]] and q["location"] == ["Room 4"]
    assert q["online"] == ["1"]


def test_open_without_teams_leaves_the_online_toggle_off():
    client = TestClient(app)
    did = _compose_draft(teams=False)
    res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert "online" not in parse_qs(urlparse(res.json()["url"]).query)


def test_open_marks_handed_off_and_second_open_is_409():
    client = TestClient(app)
    did = _compose_draft()
    assert _post(client, f"/api/drafts/{did}/open-in-outlook").status_code == 200
    assert get_draft(did)["status"] == "handed_off"
    assert _post(client, f"/api/drafts/{did}/open-in-outlook").status_code == 409


WEEKLY = {
    "pattern": {"type": "weekly", "interval": 1, "daysOfWeek": ["monday"]},
    "range": {"type": "numbered", "startDate": "2026-11-02", "numberOfOccurrences": 4},
}


def _recurring_draft():
    return create_draft("calendar-event", {**PARAMS, "recurrence": WEEKLY}, {"subject": "Sync & plan"})


def test_recurring_open_creates_a_draft_series_and_returns_its_web_link():
    client = TestClient(app)
    did = _recurring_draft()
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert res.status_code == 200
    assert res.json() == {"url": "https://outlook.office365.com/owa/?itemid=evt1"}
    path, event = gc.post.call_args.args
    assert path == "/me/events"
    assert event["isDraft"] is True
    assert event["recurrence"] == WEEKLY
    assert get_draft(did)["status"] == "handed_off"


def test_recurring_open_rejected_by_graph_returns_the_draft_to_pending():
    client = TestClient(app)
    did = _recurring_draft()
    gc = MagicMock()
    err = RuntimeError("bad request")
    err.status_code = 400
    gc.post.side_effect = err
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert res.status_code == 500
    assert get_draft(did)["status"] == "pending"


def test_recurring_open_with_uncertain_failure_is_terminal_so_it_cannot_duplicate():
    client = TestClient(app)
    did = _recurring_draft()
    gc = MagicMock()
    err = RuntimeError("gateway timeout")
    err.status_code = 504
    gc.post.side_effect = err
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert res.status_code == 502
    assert get_draft(did)["status"] == "handed_off"


def test_approving_a_calendar_draft_creates_the_event_once():
    client = TestClient(app)
    did = _draft()
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    path, event = gc.post.call_args.args
    assert path == "/me/events"
    assert event["subject"] == "Sync & plan"
    assert event["start"] == {"dateTime": PARAMS["start"], "timeZone": PARAMS["timezone"]}
    assert event["end"] == {"dateTime": PARAMS["end"], "timeZone": PARAMS["timezone"]}
    assert [(a["emailAddress"]["address"], a["type"]) for a in event["attendees"]] == [
        ("a@x.com", "required"),
        ("b@y.com", "required"),
        ("c@z.com", "optional"),
    ]
    assert event["body"] == {"contentType": "HTML", "content": PARAMS["body"]}
    assert event["location"] == {"displayName": "Room 4"}
    assert event["isOnlineMeeting"] is True
    assert event["onlineMeetingProvider"] == "teamsForBusiness"
    assert "recurrence" not in event
    assert get_draft(did) is None


def test_failed_calendar_send_keeps_the_draft_for_retry():
    client = TestClient(app)
    did = _draft()
    gc = MagicMock()
    gc.post.side_effect = RuntimeError("graph down")
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 500
    assert get_draft(did)["status"] == "pending"


def test_calendar_draft_opened_in_outlook_cannot_also_be_sent():
    client = TestClient(app)
    did = _compose_draft()
    assert _post(client, f"/api/drafts/{did}/open-in-outlook").status_code == 200
    with patch("skills._m365.helpers.get_cal_client", side_effect=AssertionError("no Graph call")):
        res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 409


def _post_edits(client, path, edits):
    return client.post(
        path, headers={"X-CSRF-Token": get_csrf_token("testserver")}, json={"edited_fields": edits}
    )


def test_approving_applies_the_edited_title_and_message_as_plain_text():
    client = TestClient(app)
    did = _draft()
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1"}

    gc.get.return_value = {"isDraft": True}
    edits = {"subject": "  Kickoff  ", "body": "Agenda <b>first</b>\nthen Q&A"}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post_edits(client, f"/api/drafts/{did}/approve", edits)
    assert res.status_code == 200
    _, event = gc.post.call_args.args
    assert event["subject"] == "Kickoff"
    assert event["body"] == {"contentType": "text", "content": "Agenda <b>first</b>\nthen Q&A"}


def test_approving_with_only_a_title_edit_leaves_the_message_untouched():
    client = TestClient(app)
    did = _draft()
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post_edits(client, f"/api/drafts/{did}/approve", {"subject": "Kickoff"})
    assert res.status_code == 200
    _, event = gc.post.call_args.args
    assert event["subject"] == "Kickoff"
    assert event["body"] == {"contentType": "HTML", "content": PARAMS["body"]}


def test_open_in_outlook_uses_the_edited_title_and_message():
    client = TestClient(app)
    did = _compose_draft()
    res = _post_edits(client, f"/api/drafts/{did}/open-in-outlook", {"subject": "Kickoff", "body": "Hello"})
    assert res.status_code == 200
    q = parse_qs(urlparse(res.json()["url"]).query)
    assert q["subject"] == ["Kickoff"] and q["body"] == ["Hello"]


def test_open_in_outlook_series_uses_the_edited_title_and_message():
    client = TestClient(app)
    did = _recurring_draft()
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}

    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post_edits(client, f"/api/drafts/{did}/open-in-outlook", {"subject": "Kickoff", "body": "Hello"})
    assert res.status_code == 200
    _, event = gc.post.call_args.args
    assert event["subject"] == "Kickoff"
    assert event["body"] == {"contentType": "text", "content": "Hello"}


@pytest.mark.parametrize(
    "edits",
    [
        {"subject": "   "},
        {"subject": "two\nlines"},
        {"subject": "x" * 256},
        {"body": "x" * 32769},
        {"body": 5},
        {"location": "Room 9"},
    ],
)
@pytest.mark.parametrize("route", ["approve", "open-in-outlook"])
def test_invalid_edits_are_rejected_and_the_draft_stays_pending(edits, route):
    client = TestClient(app)
    did = _draft()
    with patch("skills._m365.helpers.get_cal_client", side_effect=AssertionError("no Graph call")):
        res = _post_edits(client, f"/api/drafts/{did}/{route}", edits)
    assert res.status_code == 400
    assert get_draft(did)["status"] == "pending"


def test_edited_fields_that_are_not_an_object_are_rejected():
    client = TestClient(app)
    did = _draft()
    res = _post_edits(client, f"/api/drafts/{did}/approve", ["subject"])
    assert res.status_code == 400
    assert get_draft(did)["status"] == "pending"
