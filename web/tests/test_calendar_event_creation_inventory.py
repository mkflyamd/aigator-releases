"""Every calendar event is created through skills/calendar/events.py, which keeps attendee events unsent unless told to deliver."""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skills.calendar.events import NoAttendeesError, NotHeldAsDraftError, create_event, create_meeting

WEB = Path(__file__).resolve().parent.parent
SERVICE = WEB / "skills" / "calendar" / "events.py"
CREATE_CALL = re.compile(r"""\.post\(\s*f?["']/me/[^"']*events["']""")

PARAMS = {
    "subject": "Sync",
    "start": "2026-11-10T10:00:00",
    "end": "2026-11-10T10:30:00",
    "timezone": "Pacific Standard Time",
    "attendees": ["a@example.com"],
}


def test_only_the_calendar_events_service_posts_to_me_events():
    offenders = [
        str(path.relative_to(WEB))
        for path in WEB.rglob("*.py")
        if "tests" not in path.relative_to(WEB).parts
        and path != SERVICE
        and CREATE_CALL.search(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == [], f"create events through skills.calendar.events: {offenders}"


def _post(**kw):
    gc = MagicMock()
    gc.post.return_value = {"id": "evt"}
    gc.get.return_value = {"isDraft": True}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        create_meeting(PARAMS, **kw)
    path, event = gc.post.call_args.args
    assert path == "/me/events"
    return event


def test_a_meeting_with_attendees_is_an_unsent_draft_by_default():
    assert _post()["isDraft"] is True


def test_only_deliver_true_sends_the_invite():
    assert "isDraft" not in _post(deliver=True)


def test_an_event_without_attendees_is_created_as_is():
    gc = MagicMock()
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        create_event({"subject": "OOF", "isAllDay": True})
    assert "isDraft" not in gc.post.call_args.args[1]


def test_a_meeting_needs_an_attendee_and_makes_no_graph_call():
    gc = MagicMock()
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        with pytest.raises(NoAttendeesError):
            create_meeting({**PARAMS, "attendees": [], "optional_attendees": []})
    gc.post.assert_not_called()


def _held(saved=None, read_error=None):
    gc = MagicMock()
    gc.post.return_value = {"id": "evt"}
    if read_error:
        gc.get.side_effect = read_error
    else:
        gc.get.return_value = saved
    return gc


@pytest.mark.parametrize("saved", [{"isDraft": False}, {}, None])
def test_a_meeting_graph_did_not_hold_as_a_draft_is_refused(saved):
    with patch("skills._m365.helpers.get_cal_client", return_value=_held(saved)):
        with pytest.raises(NotHeldAsDraftError):
            create_meeting(PARAMS)


def test_a_failed_read_back_is_treated_as_not_confirmed():
    with patch("skills._m365.helpers.get_cal_client", return_value=_held(read_error=RuntimeError("503"))):
        with pytest.raises(NotHeldAsDraftError):
            create_meeting(PARAMS)


def test_the_draft_is_read_back_by_id_and_a_delivered_meeting_is_not():
    gc = _held({"isDraft": True})
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        create_meeting(PARAMS)
    assert gc.get.call_args.args[0] == "/me/events/evt"
    gc = _held({"isDraft": False})
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        create_meeting(PARAMS, deliver=True)
    gc.get.assert_not_called()
