"""Cancelling a meeting that has attendees is an approval card, and nothing is cancelled until it is approved.

Every Graph call here goes to a mock, so none of these tests can email an attendee.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from skills._drafts import get_draft
from skills.calendar.tools import _tool_delete_calendar_event

ANN = {"emailAddress": {"name": "Ann", "address": "ann@amd.com"}, "type": "required"}
ROOM = {"emailAddress": {"name": "Room 4", "address": "room4@amd.com"}, "type": "resource"}


class _Gone(RuntimeError):
    status_code = 404


def _event(**kw):
    return {
        "id": "evt1",
        "subject": "Sync",
        "isOrganizer": True,
        "type": "singleInstance",
        "attendees": [ANN],
        "start": {"dateTime": "2026-11-20T09:00:00.0000000"},
        "end": {"dateTime": "2026-11-20T09:30:00.0000000"},
        **kw,
    }


def _client(event):
    """A calendar client that returns the event until it is deleted, then 404s."""
    gc = MagicMock()
    state = {"deleted": False}

    def get(path, params=None, **kw):
        if state["deleted"]:
            raise _Gone("gone")
        return event

    def delete(path, *a, **kw):
        state["deleted"] = True

    gc.get.side_effect = get
    gc.delete.side_effect = delete
    return gc


def _stage(event=None, **kw):
    gc = _client(event or _event())
    with patch("skills._m365.helpers.get_cal_client", return_value=gc), patch(
        "skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"
    ):
        return _tool_delete_calendar_event("evt1", **kw), gc


def _approve(draft_id, gc):
    from security import get_csrf_token

    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        return TestClient(app).post(
            f"/api/drafts/{draft_id}/approve",
            headers={"X-CSRF-Token": get_csrf_token("testserver")},
            json={},
        )


def test_cancelling_a_meeting_with_attendees_makes_a_card_and_cancels_nothing():
    result, gc = _stage(comment="  Moving to next week  ")
    assert result["_draft"] == "calendar-cancel"
    gc.delete.assert_not_called()
    gc.post.assert_not_called()
    params = get_draft(result["data"]["draft_id"])["params"]
    assert params["comment"] == "Moving to next week"
    assert params["attendees"] == [{"name": "Ann", "email": "ann@amd.com"}]
    assert params["scope"] == "single" and params["notify"] == "All"


def test_rooms_alone_do_not_count_as_people_to_notify():
    result, gc = _stage(_event(attendees=[ROOM]))
    assert result["deleted"] is True
    gc.delete.assert_called_once()


def test_a_meeting_with_no_attendees_is_deleted_directly():
    result, gc = _stage(_event(attendees=[]))
    assert result["deleted"] is True
    gc.delete.assert_called_once()


def test_telling_no_one_deletes_directly():
    result, gc = _stage(send_updates="None")
    assert result["deleted"] is True
    assert gc.delete.call_args.args[0].endswith("sendUpdates=None")


def test_a_meeting_the_user_does_not_organize_is_refused_without_a_card():
    result, gc = _stage(_event(isOrganizer=False))
    assert result["organizer_required"] is True and "_draft" not in result
    gc.delete.assert_not_called()


def test_a_series_master_needs_delete_series_before_a_card_is_made():
    result, gc = _stage(_event(type="seriesMaster"))
    assert result["series_master"] is True and "_draft" not in result
    gc.delete.assert_not_called()


def test_a_whole_series_card_says_so():
    result, _ = _stage(_event(type="seriesMaster"), delete_series=True)
    assert result["data"]["scope"] == "series" and result["data"]["delete_series"] is True


def test_approving_cancels_the_meeting_and_notifies_attendees():
    result, _ = _stage(comment="Moving to next week")
    gc = _client(_event())
    r = _approve(result["data"]["draft_id"], gc)
    assert r.status_code == 200, r.text
    assert gc.delete.call_args.args[0] == "/me/events/evt1?sendUpdates=All"
    assert gc.post.call_args.args == ("/me/events/evt1/cancel", {"Comment": "Moving to next week"})


def test_approving_an_event_that_is_gone_says_so_and_keeps_the_card_retryable():
    result, _ = _stage()
    gc = MagicMock()
    gc.get.side_effect = _Gone("gone")
    r = _approve(result["data"]["draft_id"], gc)
    assert r.status_code == 409
    assert "no longer exists" in r.json()["detail"]
    assert get_draft(result["data"]["draft_id"]) is not None
    gc.delete.assert_not_called()


def _stage_with(gc):
    with patch("skills._m365.helpers.get_cal_client", return_value=gc), patch(
        "skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"
    ):
        return _tool_delete_calendar_event("evt1")


def test_a_failed_pre_read_cancels_nothing():
    gc = MagicMock()
    gc.get.side_effect = RuntimeError("503")
    result = _stage_with(gc)
    assert result["deleted"] is False
    assert "503" in result["error"]
    gc.delete.assert_not_called()
    gc.post.assert_not_called()


def test_an_event_that_is_gone_or_empty_cancels_nothing():
    gone = MagicMock()
    gone.get.side_effect = _Gone("gone")
    empty = MagicMock()
    empty.get.return_value = None
    for gc in (gone, empty):
        result = _stage_with(gc)
        assert result["deleted"] is False and result["not_found"] is True
        gc.delete.assert_not_called()
