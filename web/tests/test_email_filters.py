"""Baseline tests for email filter behavior (All / Unread / future Sent / Drafts).

These tests confirm the existing All/Unread filter behavior is correct and provide
a regression baseline before adding Sent/Draft folder support in Phase 4.
"""
from unittest.mock import patch, MagicMock, call

import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def _make_messages(n: int, unread_count: int = 0):
    """Build n fake Graph messages, first unread_count are unread."""
    return [
        {
            "id": f"MSG{i}",
            "subject": f"Subject {i}",
            "from": {"emailAddress": {"name": f"Sender {i}", "address": f"s{i}@x.com"}},
            "toRecipients": [],
            "ccRecipients": [],
            "receivedDateTime": f"2026-06-2{i % 8}T10:00:00Z",
            "body": {"contentType": "text", "content": f"Body {i}"},
            "isRead": i >= unread_count,
            "importance": "normal",
            "conversationId": f"conv{i}",
            "bodyPreview": f"Preview {i}",
        }
        for i in range(n)
    ]


def _setup_gc(messages, total_unread=0):
    gc = MagicMock()
    gc.get.side_effect = lambda path, params=None: (
        {"value": messages, "@odata.deltaLink": None}
        if "messages" in path
        else {"unreadItemCount": total_unread}
    )
    return gc


# ── Baseline: All filter ──────────────────────────────────────────────────────

def test_inbox_all_returns_messages():
    """GET /api/email/inbox returns a list of messages."""
    msgs = _make_messages(5)
    gc = _setup_gc(msgs, total_unread=2)

    with patch("routes.email.GraphClient", return_value=gc):
        resp = client.get("/api/email/inbox?top=5")

    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert len(data["messages"]) == 5


def test_inbox_all_uses_inbox_folder():
    """GET /api/email/inbox without folder param fetches from mailFolders/inbox."""
    msgs = _make_messages(3)
    gc = _setup_gc(msgs)

    with patch("routes.email.GraphClient", return_value=gc):
        client.get("/api/email/inbox?top=3")

    # All calls should reference inbox folder
    called_paths = [str(c) for c in gc.get.call_args_list]
    assert any("inbox" in p for p in called_paths), (
        f"Expected Graph call to inbox folder, got: {called_paths}"
    )


# ── Baseline: Unread filter ───────────────────────────────────────────────────

def test_inbox_unread_filter_passes_filter_param():
    """GET /api/email/inbox?filter=unread passes filter to Graph or returns filtered results."""
    msgs = _make_messages(10, unread_count=3)
    gc = _setup_gc(msgs, total_unread=3)

    with patch("routes.email.GraphClient", return_value=gc):
        resp = client.get("/api/email/inbox?filter=unread&top=10")

    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert "total_unread" in data


def test_inbox_returns_total_unread_count():
    """Response includes total_unread field reflecting inbox unread count."""
    msgs = _make_messages(5, unread_count=2)
    gc = _setup_gc(msgs, total_unread=2)

    with patch("routes.email.GraphClient", return_value=gc):
        resp = client.get("/api/email/inbox?top=5")

    assert resp.status_code == 200
    data = resp.json()
    assert "total_unread" in data
    assert isinstance(data["total_unread"], int)


# ── Phase 4: folder param ─────────────────────────────────────────────────────

def test_folder_sentitems_fetches_sent_folder():
    """GET /api/email/inbox?folder=sentitems fetches from SentItems Graph folder."""
    msgs = _make_messages(3)
    gc = MagicMock()
    gc.get.return_value = {"value": msgs}

    with patch("routes.email.GraphClient", return_value=gc):
        resp = client.get("/api/email/inbox?folder=sentitems&top=3")

    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    # Confirm the call referenced SentItems
    called_paths = [str(c) for c in gc.get.call_args_list]
    assert any("SentItems" in p for p in called_paths), (
        f"Expected Graph call to SentItems, got: {called_paths}"
    )


def test_folder_drafts_fetches_drafts_folder():
    """GET /api/email/inbox?folder=drafts fetches from Drafts Graph folder."""
    msgs = _make_messages(2)
    gc = MagicMock()
    gc.get.return_value = {"value": msgs}

    with patch("routes.email.GraphClient", return_value=gc):
        resp = client.get("/api/email/inbox?folder=drafts&top=2")

    assert resp.status_code == 200
    called_paths = [str(c) for c in gc.get.call_args_list]
    assert any("Drafts" in p for p in called_paths), (
        f"Expected Graph call to Drafts, got: {called_paths}"
    )


def test_folder_inbox_param_equivalent_to_default():
    """GET /api/email/inbox?folder=inbox behaves identically to no folder param."""
    msgs = _make_messages(4)
    gc = _setup_gc(msgs, total_unread=1)

    with patch("routes.email.GraphClient", return_value=gc):
        resp = client.get("/api/email/inbox?folder=inbox&top=4")

    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert "total_unread" in data


def test_folder_unknown_returns_400():
    """GET /api/email/inbox?folder=unknown returns HTTP 400."""
    with patch("routes.email.GraphClient", return_value=MagicMock()):
        resp = client.get("/api/email/inbox?folder=junkfolder")

    assert resp.status_code == 400
    assert "junkfolder" in resp.json().get("detail", "")


def test_sent_folder_total_unread_is_zero():
    """Sent/Drafts folder responses always return total_unread=0 (not inbox count)."""
    msgs = _make_messages(3)
    gc = MagicMock()
    gc.get.return_value = {"value": msgs}

    with patch("routes.email.GraphClient", return_value=gc):
        resp = client.get("/api/email/inbox?folder=sentitems&top=3")

    assert resp.status_code == 200
    assert resp.json().get("total_unread") == 0


def test_format_email_message_reused_for_all_folders():
    """_format_email_message is the single formatter — verify no duplication by checking
    all folder paths produce the same message shape (same keys)."""
    msgs = _make_messages(1)
    gc = _setup_gc(msgs, total_unread=0)

    with patch("routes.email.GraphClient", return_value=gc):
        inbox_resp = client.get("/api/email/inbox?folder=inbox&top=1").json()

    gc2 = MagicMock()
    gc2.get.return_value = {"value": msgs}
    with patch("routes.email.GraphClient", return_value=gc2):
        sent_resp = client.get("/api/email/inbox?folder=sentitems&top=1").json()

    inbox_keys = set(inbox_resp["messages"][0].keys()) if inbox_resp["messages"] else set()
    sent_keys = set(sent_resp["messages"][0].keys()) if sent_resp["messages"] else set()
    assert inbox_keys == sent_keys, (
        f"Inbox and Sent messages have different shapes: {inbox_keys} vs {sent_keys}"
    )
