"""update_calendar_event stages an approval card and only touches Graph on approve.

Graph replaces the whole attendees array on PATCH, so adding one required
attendee used to silently remove every optional attendee from the event.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token
from skills._drafts import create_draft, get_draft
from skills._m365 import helpers as m365_helpers
from skills.calendar import helpers as cal_helpers
from skills.calendar.tools import _build_calendar_update, _tool_update_calendar_event, apply_calendar_update

WIN_TZ = "Pacific Standard Time"


def _person(address, kind, name=""):
    return {"emailAddress": {"address": address, "name": name or address}, "type": kind, "status": {"response": "none"}}


CURRENT = [
    _person("req@example.com", "required"),
    _person("opt1@example.com", "optional"),
    _person("opt2@example.com", "optional"),
    _person("room@example.com", "resource"),
]

EVENT = {
    "subject": "Sync",
    "start": {"dateTime": "2026-11-04T09:00:00.0000000", "timeZone": WIN_TZ},
    "end": {"dateTime": "2026-11-04T09:30:00.0000000", "timeZone": WIN_TZ},
    "location": {"displayName": "Room 4"},
    "attendees": CURRENT,
    "isOnlineMeeting": False,
    "isOrganizer": True,
    "type": "occurrence",
    "webLink": "https://outlook.office.com/calendar/item/EVENT1",
}


def _build(**kwargs):
    return _build_calendar_update(EVENT, WIN_TZ, **kwargs)


def _sent(payload):
    return {(a["emailAddress"]["address"], a["type"]) for a in payload["attendees"]}


def test_adding_a_required_attendee_keeps_the_optional_ones_and_the_room():
    payload = _build(attendees=["req@example.com", "new@example.com"])
    assert _sent(payload) == {
        ("req@example.com", "required"),
        ("new@example.com", "required"),
        ("opt1@example.com", "optional"),
        ("opt2@example.com", "optional"),
        ("room@example.com", "resource"),
    }


def test_replacing_the_optional_list_keeps_the_required_ones():
    payload = _build(optional_attendees=["opt3@example.com"])
    assert _sent(payload) == {
        ("req@example.com", "required"),
        ("opt3@example.com", "optional"),
        ("room@example.com", "resource"),
    }


def test_moving_someone_between_lists_does_not_duplicate_them():
    payload = _build(attendees=["req@example.com", "opt1@example.com"])
    addresses = [a["emailAddress"]["address"] for a in payload["attendees"]]
    assert addresses.count("opt1@example.com") == 1
    assert ("opt1@example.com", "required") in _sent(payload)


def test_an_update_without_attendees_does_not_touch_them():
    assert "attendees" not in _build(subject="New title")


def test_unchanged_fields_are_left_out_of_the_payload():
    payload = _build(subject="Sync", start="2026-11-04T09:00:00", location="Room 4", attendees=["req@example.com"])
    assert payload == {}


def _stage(event=EVENT, **kwargs):
    gc = MagicMock()
    gc.get.return_value = event
    with patch.object(m365_helpers, "get_cal_client", return_value=gc), patch.object(
        cal_helpers, "get_user_win_tz", return_value=WIN_TZ
    ):
        result = _tool_update_calendar_event("EVENT1", **kwargs)
    return result, gc


def test_the_tool_stages_a_card_and_writes_nothing():
    result, gc = _stage(start="2026-11-05T10:00:00", end="2026-11-05T10:30:00", attendees=["req@example.com", "new@example.com"])
    gc.patch.assert_not_called()
    assert result["_draft"] == "calendar-update"
    data = result["data"]
    assert data["scope"] == "occurrence"
    assert data["before"]["start"] == "2026-11-04T09:00:00"
    assert data["after"]["start"] == "2026-11-05T10:00:00"
    assert data["changed"] == ["when", "attendees"]
    assert [p["email"] for p in data["added"]] == ["new@example.com"]
    assert data["removed"] == [] and data["moved"] == []
    assert data["web_link"] == EVENT["webLink"]
    assert get_draft(data["draft_id"])["type"] == "calendar-update"


def test_a_series_master_is_labelled_as_the_whole_series():
    result, _ = _stage({**EVENT, "type": "seriesMaster"}, subject="Renamed")
    assert result["data"]["scope"] == "series"


def test_only_the_organizer_can_stage_an_update():
    result, gc = _stage({**EVENT, "isOrganizer": False}, subject="Renamed")
    assert result["updated"] is False and "organize" in result["error"]
    gc.patch.assert_not_called()


def test_a_no_op_update_stages_nothing():
    result, _ = _stage(subject="Sync")
    assert result["updated"] is False and "_draft" not in result


def test_if_the_event_cannot_be_read_nothing_is_staged():
    gc = MagicMock()
    gc.get.side_effect = RuntimeError("boom")
    with patch.object(m365_helpers, "get_cal_client", return_value=gc), patch.object(
        cal_helpers, "get_user_win_tz", return_value=WIN_TZ
    ):
        result = _tool_update_calendar_event("EVENT1", attendees=["new@example.com"])
    assert result["updated"] is False
    gc.patch.assert_not_called()


def _post(client, path):
    return client.post(path, headers={"X-CSRF-Token": get_csrf_token("testserver")}, json=None)


def _staged_draft():
    result, _ = _stage(subject="Renamed", attendees=["req@example.com", "new@example.com"])
    return result["data"]["draft_id"]


def test_approving_patches_the_merged_payload_once():
    client = TestClient(app)
    did = _staged_draft()
    gc = MagicMock()
    gc.get.return_value = EVENT
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 200 and res.json()["ok"] is True
    path, payload = gc.patch.call_args.args
    assert path == "/me/events/EVENT1?sendUpdates=All"
    assert payload["subject"] == "Renamed"
    assert ("opt1@example.com", "optional") in _sent(payload)
    assert get_draft(did) is None


def test_an_event_edited_after_staging_is_not_overwritten():
    client = TestClient(app)
    did = _staged_draft()
    edited = {**EVENT, "attendees": CURRENT + [_person("added-in-outlook@example.com", "required")]}
    gc = MagicMock()
    gc.get.return_value = edited
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 409 and "changed" in res.json()["detail"]
    gc.patch.assert_not_called()
    assert get_draft(did)["status"] == "pending"


def test_a_body_edited_in_outlook_after_staging_is_not_overwritten():
    client = TestClient(app)
    did = _staged_draft()
    edited = {**EVENT, "body": {"contentType": "html", "content": "<p>Agenda added in Outlook</p>"}}
    gc = MagicMock()
    gc.get.return_value = edited
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 409
    gc.patch.assert_not_called()


def test_a_failed_update_keeps_the_draft_for_retry():
    client = TestClient(app)
    did = _staged_draft()
    gc = MagicMock()
    gc.get.return_value = EVENT
    gc.patch.side_effect = RuntimeError("graph down")
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post(client, f"/api/drafts/{did}/approve")
    assert res.status_code == 500
    assert get_draft(did)["status"] == "pending"


def test_open_in_outlook_returns_the_event_link_without_writing():
    client = TestClient(app)
    did = _staged_draft()
    with patch("skills._m365.helpers.get_cal_client", side_effect=AssertionError("no Graph call")):
        res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert res.status_code == 200
    assert res.json()["url"] == EVENT["webLink"]
    assert get_draft(did)["status"] == "handed_off"
    assert _post(client, f"/api/drafts/{did}/open-in-outlook").status_code == 409
    assert _post(client, f"/api/drafts/{did}/approve").status_code == 409


def test_open_in_outlook_falls_back_when_the_link_is_not_https():
    client = TestClient(app)
    did = create_draft("calendar-update", {"event_id": "E", "payload": {}, "web_link": "javascript:alert(1)"}, {})
    res = _post(client, f"/api/drafts/{did}/open-in-outlook")
    assert res.json()["url"] == "https://outlook.office.com/calendar"


def test_apply_reports_the_refreshed_event():
    gc = MagicMock()
    gc.get.return_value = {"subject": "Sync", "start": {"dateTime": "a"}, "end": {"dateTime": "b"}, "attendees": CURRENT}
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        out = apply_calendar_update("EVENT1", {"subject": "Sync"}, "None")
    assert out["updated"] is True and out["attendee_count"] == 4
    assert gc.patch.call_args.args[0] == "/me/events/EVENT1?sendUpdates=None"
