"""Baseline TDD probes for open email bugs.

Each bug gets a test that will PASS once the bug is fixed.
xfail tests confirm the bug is still open; xpass means it's already fixed.

Bugs targeted:
  #121 / #122 — email body truncated (4000 char cap in get_email_detail)
  #141 / #136 — inline CID images not substituted with data: URIs
  compose UX gap — no guard before destroying compose with unsaved content
"""
import re
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_gc(body_content: str, content_type: str = "html"):
    gc = MagicMock()
    gc.get.return_value = {
        "id": "MSG1",
        "subject": "Test",
        "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
        "toRecipients": [],
        "ccRecipients": [],
        "receivedDateTime": "2026-06-28T10:00:00Z",
        "body": {"contentType": content_type, "content": body_content},
        "isRead": True,
        "importance": "normal",
        "conversationId": "conv1",
    }
    return gc


# ── Bug #121/#122 — body truncation in get_email_detail ──────────────────────

def test_get_email_detail_returns_full_body_over_4000_chars():
    """get_email_detail must return at least 32000 chars for a long email body.
    Currently fails because body_plain is sliced to [:4000] in tools.py line ~300.
    """
    long_body = "A" * 40_000
    gc = _make_gc(long_body, content_type="text")

    from skills.email.tools import _tool_get_email_detail
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        result = _tool_get_email_detail("MSG1")

    body = result.get("body", "")
    assert len(body) >= 32_000, (
        f"Expected body >= 32000 chars but got {len(body)}. "
        "Bug #121/#122: max_chars too low in get_email_detail."
    )


def test_tp_email_message_body_text_over_3000_chars():
    """tp_email_message body_text must not be truncated at 3000 chars.
    Currently fails because html_to_text(max_len=3000) is applied in email.py line ~368.
    Note: body_html is returned uncapped, but body_text (used by LLM) is truncated.
    """
    long_text = "<p>" + "Word " * 2000 + "</p>"  # ~10000 chars HTML
    gc_mock = _make_gc(long_text, content_type="html")

    with patch("routes.email.GraphClient", return_value=gc_mock):
        # Suppress the beta call (meeting detection)
        gc_mock.get.side_effect = [
            # First call: main message fetch
            {
                "id": "MSG1",
                "subject": "Long email",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@x.com"}},
                "toRecipients": [],
                "ccRecipients": [],
                "receivedDateTime": "2026-06-28T10:00:00Z",
                "body": {"contentType": "html", "content": long_text},
                "isRead": True,
                "importance": "normal",
                "conversationId": "C1",
            },
            # Second call: beta (meeting detection) — raises to short-circuit
            Exception("skip beta"),
        ]
        resp = client.get("/api/email/messages/MSG1")

    assert resp.status_code == 200
    body_text = resp.json().get("body_text", "")
    assert len(body_text) >= 5_000, (
        f"Expected body_text >= 5000 chars but got {len(body_text)}. "
        "Bug #121/#122: html_to_text max_len=3000 truncates body_text."
    )


# ── Bug #141/#136 — CID inline images not substituted ────────────────────────

CID_BODY = (
    '<html><body>'
    '<p>See attached chart:</p>'
    '<img src="cid:image001.png@01D7B3F2.4A8C1234" alt="chart">'
    '<p>And the logo:</p>'
    '<img src="cid:image002.jpg@01D7B3F2.4A8C5678" alt="logo">'
    '</body></html>'
)


def test_tp_email_message_cid_references_resolved():
    """tp_email_message must substitute cid: src references with data: URIs.
    Currently fails because no CID substitution is implemented in email.py.
    """
    gc_mock = MagicMock()

    def _gc_get(path, params=None, base_url=None):
        if base_url:
            raise Exception("skip beta")
        if "attachments" in path:
            return {
                "value": [
                    {
                        "id": "ATT1",
                        "isInline": True,
                        "contentType": "image/png",
                        "contentId": "image001.png@01D7B3F2.4A8C1234",
                        "contentBytes": "aVZCT1J3MEtHZ29BQUFBTlNVaEVVZ0FBQUFBQUFBQUJBQUFBQUFBQQ==",
                        "name": "image001.png",
                    },
                    {
                        "id": "ATT2",
                        "isInline": True,
                        "contentType": "image/jpeg",
                        "contentId": "image002.jpg@01D7B3F2.4A8C5678",
                        "contentBytes": "L9j/4AAQSkZJRgABAQEASABIAAD/2wBDAA==",
                        "name": "image002.jpg",
                    },
                ]
            }
        # Default: main message
        return {
            "id": "MSG1",
            "subject": "Email with inline images",
            "from": {"emailAddress": {"name": "Alice", "address": "alice@x.com"}},
            "toRecipients": [],
            "ccRecipients": [],
            "receivedDateTime": "2026-06-28T10:00:00Z",
            "body": {"contentType": "html", "content": CID_BODY},
            "isRead": True,
            "importance": "normal",
            "conversationId": "C1",
        }

    gc_mock.get.side_effect = _gc_get

    with patch("routes.email.GraphClient", return_value=gc_mock):
        resp = client.get("/api/email/messages/MSG1")

    assert resp.status_code == 200
    body_html = resp.json().get("body_html", "")
    assert "cid:" not in body_html, (
        "Bug #141/#136: body_html still contains cid: references. "
        "CID substitution with data: URIs is not implemented."
    )
    assert "data:image/png;base64," in body_html, (
        "Expected data: URI substitution for PNG attachment."
    )
