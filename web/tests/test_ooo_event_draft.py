"""An out-of-office block that notifies colleagues is an approval card, and nothing is sent until it is approved.

Every Graph call here goes to a mock, so none of these tests can send an invite.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from skills._drafts import get_draft
from skills.calendar.tools import _tool_create_ooo_event


def _create(**kw):
    gc = MagicMock()
    gc.get.return_value = {"displayName": "Mia"}
    gc.post.return_value = {"id": "evt1"}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc), patch(
        "skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"
    ):
        result = _tool_create_ooo_event("2026-11-20", "2026-11-22", **kw)
    return result, gc


def _post(client, draft_id, action, body=None):
    from security import get_csrf_token

    return client.post(
        f"/api/drafts/{draft_id}/{action}",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=body,
    )


def test_notifying_colleagues_makes_a_draft_card_and_sends_nothing():
    result, gc = _create(notify=["ann@amd.com", "bob@amd.com", "ann@amd.com"])
    assert result["_draft"] == "calendar-event"
    gc.post.assert_not_called()
    params = get_draft(result["data"]["draft_id"])["params"]
    assert params["optional_attendees"] == ["ann@amd.com", "bob@amd.com"]
    assert params["ooo"] is True and params["start"] == "2026-11-20T00:00:00"
    assert params["end"] == "2026-11-23T00:00:00"


def test_approving_sends_an_all_day_out_of_office_with_optional_attendees():
    result, gc = _create(notify=["ann@amd.com"])
    cal = MagicMock()
    cal.post.return_value = {"id": "evt1"}
    with patch("skills._m365.helpers.get_cal_client", return_value=cal):
        r = _post(TestClient(app), result["data"]["draft_id"], "approve")
    assert r.status_code == 200, r.text
    path, event = cal.post.call_args.args
    assert path == "/me/events"
    assert event["isAllDay"] is True and event["showAs"] == "oof"
    assert event["responseRequested"] is False and event["isReminderOn"] is False
    assert event["attendees"] == [{"emailAddress": {"address": "ann@amd.com"}, "type": "optional"}]
    assert "isDraft" not in event and "onlineMeetingProvider" not in event


def test_opening_it_in_outlook_keeps_the_invite_unsent():
    result, _ = _create(notify=["ann@amd.com"])
    cal = MagicMock()
    cal.post.return_value = {"id": "evt1", "webLink": "https://outlook.office.com/calendar/item/evt1"}
    cal.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=cal):
        r = _post(TestClient(app), result["data"]["draft_id"], "open-in-outlook")
    assert r.status_code == 200, r.text
    assert cal.post.call_args.args[1]["isDraft"] is True


def test_without_colleagues_the_block_goes_straight_onto_the_users_calendar():
    result, gc = _create(notify=[])
    assert result["created"] is True and result["notified"] == []
    event = gc.post.call_args.args[1]
    assert event["isAllDay"] is True and event["showAs"] == "oof"
    assert "attendees" not in event
