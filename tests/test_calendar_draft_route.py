from unittest.mock import patch
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


def test_approving_a_calendar_draft_is_rejected():
    client = TestClient(app)
    did = _draft()
    res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 400
