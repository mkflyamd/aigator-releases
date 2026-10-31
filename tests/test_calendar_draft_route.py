from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

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


def test_open_returns_compose_deeplink_with_all_fields():
    client = TestClient(app)
    did = _draft()
    with patch("skills._m365.helpers.get_graph_client", side_effect=AssertionError("no Graph call")):
        res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert res.status_code == 200
    url = urlparse(res.json()["url"])
    assert url.netloc == "outlook.office.com" and url.path == "/calendar/0/deeplink/compose"
    q = parse_qs(url.query)
    assert q["subject"] == ["Sync & plan"]
    assert q["to"] == ["a@x.com;b@y.com;c@z.com"]
    assert q["startdt"] == [PARAMS["start"]] and q["enddt"] == [PARAMS["end"]]
    assert q["body"] == [PARAMS["body"]] and q["location"] == ["Room 4"]


def test_open_marks_handed_off_and_second_open_is_409():
    client = TestClient(app)
    did = _draft()
    assert _post(client, f"/api/drafts/{did}/open-in-outlook").status_code == 200
    assert get_draft(did)["status"] == "handed_off"
    assert _post(client, f"/api/drafts/{did}/open-in-outlook").status_code == 409


def test_approving_a_calendar_draft_creates_the_event_once():
    client = TestClient(app)
    did = _draft()
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1"}
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
    did = _draft()
    assert _post(client, f"/api/drafts/{did}/open-in-outlook").status_code == 200
    with patch("skills._m365.helpers.get_cal_client", side_effect=AssertionError("no Graph call")):
        res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 409
