"""Rail badge: Teams counts unread conversations that native Teams counts as chats.

Channels/teams keep a read marker that native Teams never advances, so the old
"last message newer than horizon" rule flagged them unread forever. Notes and
chats whose last message is the user's own are not unread either.
"""

import base64
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from routes import teams

ME = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
OLD_HORIZON = "1784655371466;1784655371466;0"  # July 2026
NEW_MSG = "2026-11-23T05:12:40.681Z"


def _token():
    payload = base64.urlsafe_b64encode(json.dumps({"oid": ME}).encode()).decode().rstrip("=")
    return {"access_token": f"h.{payload}.s"}


def _conv(cid, product_type, thread_type="chat", sender=OTHER, horizon=OLD_HORIZON):
    return {
        "id": cid,
        "thread_type": thread_type,
        "product_thread_type": product_type,
        "topic": cid,
        "last_message": "hello",
        "last_sender": "Someone",
        "last_sender_mri": f"8:orgid:{sender}",
        "last_time": NEW_MSG,
        "consumption_horizon": horizon,
        "consumption_horizon_bookmark": "",
        "thread_members": [],
    }


def _badge(monkeypatch, convs):
    monkeypatch.setattr(teams.secure_store, "get_json", lambda *_: _token())
    return {c["id"]: c for c in teams._normalize_skype_chats(convs)}


def test_unread_chat_counts_toward_badge(monkeypatch):
    out = _badge(monkeypatch, [_conv("19:chat@thread.v2", "Chat")])
    assert out["19:chat@thread.v2"]["badge_unread"] == 1


def test_channel_with_stale_horizon_does_not_count(monkeypatch):
    convs = [
        _conv("19:std@thread.skype", "TeamsStandardChannel", "topic"),
        _conv("19:shared@thread.skype", "TeamsSharedChannel", "topic"),
        _conv("19:team@thread.skype", "TeamsTeam", "topic"),
    ]
    out = _badge(monkeypatch, convs)
    assert [c["badge_unread"] for c in out.values()] == [0, 0, 0]
    # The list still shows channels as unread; only the rail badge ignores them.
    assert all(c["unread_count"] == 1 for c in out.values())


def test_chat_whose_last_message_is_mine_does_not_count(monkeypatch):
    out = _badge(monkeypatch, [_conv("19:mine@thread.v2", "Chat", sender=ME)])
    assert out["19:mine@thread.v2"]["badge_unread"] == 0


def test_notes_to_self_does_not_count(monkeypatch):
    out = _badge(monkeypatch, [_conv("48:notes", "StreamOfNotes", sender=ME)])
    assert out["48:notes"]["badge_unread"] == 0


def test_read_chat_does_not_count(monkeypatch):
    read = _conv("19:read@thread.v2", "Chat", horizon="1800000000000;1800000000000;27")
    out = _badge(monkeypatch, [read])
    assert out["19:read@thread.v2"]["badge_unread"] == 0
