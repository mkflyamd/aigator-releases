"""TDD tests for the final 4 fixes agreed by adversarial panel.

1. html.escape must be REMOVED from _resolve_uid_sync — frontend _slackMrkdwn
   already calls _slackEsc(), pre-escaping causes double-encoding.
2. _refresh_token must preserve team_id.
3. JS sends thread_ts (not thread_id) to match SlackPostRequest model.
4. HITL backend token: /post issues a confirm_token, /send requires it.
"""

import asyncio
import json
import pathlib
import sys
import time
from unittest.mock import patch

import pytest

SRC     = (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text(encoding="utf-8")
MCP_SRC = (pathlib.Path(__file__).parent.parent / "skills" / "slack" / "mcp_client.py").read_text(encoding="utf-8")
JS_SRC  = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Fix 1: html.escape must NOT be in _resolve_uid_sync
#         (double-encode: frontend _slackMrkdwn already calls _slackEsc)
# ─────────────────────────────────────────────────────────────────────────────

class TestNoDoubleEscaping:
    """Display names must be stored RAW in _USER_CACHE.
    _slackMrkdwn in the frontend calls _slackEsc() unconditionally on msg.text,
    so pre-escaping on the backend produces double-encoded output visible to users."""

    def test_resolve_uid_sync_does_not_html_escape(self):
        """_resolve_uid_sync must NOT apply html.escape to the display name."""
        fn_start = SRC.find("def _resolve_uid_sync(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 900]
        assert "html.escape" not in fn_body, (
            "_resolve_uid_sync must NOT apply html.escape(). "
            "The frontend _slackMrkdwn() calls _slackEsc() on msg.text before any "
            "innerHTML assignment. Pre-escaping in the backend causes double-encoding: "
            "'Jones & Smith' → cache stores 'Jones &amp; Smith' → frontend renders "
            "'Jones &amp;amp; Smith' — visible HTML entities in the UI."
        )

    def test_ampersand_in_display_name_stored_raw(self):
        """A name containing '&' must be stored as-is, not as '&amp;'."""
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            import routes.slack as slack_mod

        slack_mod._USER_CACHE.clear()
        slack_mod._USER_CACHE_LOADED = True

        def fake_web_api(endpoint, params=None):
            if endpoint == "users.info":
                return {"ok": True, "user": {"profile": {
                    "display_name": "Jones & Smith",
                    "real_name": "",
                }}}
            return {"ok": False}

        with patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
            uid, name = slack_mod._resolve_uid_sync("UAMP01", "T1")

        cached = slack_mod._USER_CACHE.get("UAMP01", "")
        assert cached == "Jones & Smith", (
            f"Name was modified before caching — got {cached!r}. "
            "Store raw names; the frontend escapes at render time."
        )

    def test_frontend_slackEsc_exists_and_escapes_before_innerHTML(self):
        """_slackMrkdwn must call _slackEsc on text before assigning to innerHTML."""
        mrkdwn_start = JS_SRC.find("function _slackMrkdwn(")
        assert mrkdwn_start != -1
        mrkdwn_body = JS_SRC[mrkdwn_start: mrkdwn_start + 300]
        assert "_slackEsc" in mrkdwn_body, (
            "_slackMrkdwn must call _slackEsc() as its first operation to HTML-escape "
            "the raw text before any innerHTML assignment. Without this, backend-stored "
            "raw names containing '<' would be XSS vectors."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2: _refresh_token must preserve team_id
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshTokenPreservesTeamId:
    """_refresh_token in mcp_client.py must include team_id in the token_data
    it writes to disk. Currently it omits it, breaking multi-workspace support
    after the first token refresh."""

    def test_refresh_token_writes_team_id(self):
        """token_data in _refresh_token must include 'team_id' key."""
        fn_start = MCP_SRC.find("def _refresh_token(")
        assert fn_start != -1
        # Find end of function (next def or EOF)
        next_def = MCP_SRC.find("\ndef ", fn_start + 1)
        fn_body = MCP_SRC[fn_start: next_def if next_def != -1 else fn_start + 1000]
        assert '"team_id"' in fn_body or "'team_id'" in fn_body, (
            "_refresh_token must write 'team_id' into token_data. "
            "Currently it omits team_id, so every token refresh overwrites the "
            "stored file without team_id, breaking multi-workspace API calls that "
            "require a team_id parameter."
        )

    def test_refresh_token_reads_team_id_from_team_object(self):
        """team_id must be read from d.get('team', {}).get('id', '') — same as _exchange_code."""
        fn_start = MCP_SRC.find("def _refresh_token(")
        assert fn_start != -1
        next_def = MCP_SRC.find("\ndef ", fn_start + 1)
        fn_body = MCP_SRC[fn_start: next_def if next_def != -1 else fn_start + 1000]
        # Verify the correct read path is used
        assert ".get(\"team\"" in fn_body or ".get('team'" in fn_body, (
            "_refresh_token must read team_id from d.get('team', {}).get('id', ''), "
            "matching the structure of the Slack OAuth token response."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fix 3: JS must send thread_ts (not thread_id) to match SlackPostRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestThreadTsKeyInJS:
    """_slackPostMessage must use payload.thread_ts (not payload.thread_id).
    SlackPostRequest expects thread_ts; thread_id is silently dropped by Pydantic."""

    def test_slackPostMessage_sends_thread_ts_not_thread_id(self):
        """JS payload must use thread_ts, not thread_id."""
        fn_start = JS_SRC.find("async function _slackPostMessage(")
        assert fn_start != -1
        fn_end = JS_SRC.find("\nasync function ", fn_start + 1)
        fn_body = JS_SRC[fn_start: fn_end if fn_end != -1 else fn_start + 4000]
        assert "payload.thread_id" not in fn_body, (
            "_slackPostMessage uses payload.thread_id but SlackPostRequest expects "
            "thread_ts. Pydantic silently ignores thread_id, so threaded replies "
            "are always sent to the channel root instead of the thread. "
            "Change to payload.thread_ts."
        )
        assert "thread_ts" in fn_body, (
            "_slackPostMessage must include 'thread_ts' in the payload for thread replies."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fix 4: HITL backend token — /post issues confirm_token, /send requires it
# ─────────────────────────────────────────────────────────────────────────────

class TestHITLBackendToken:
    """The /post endpoint must issue a single-use confirm_token.
    The /send endpoint must validate and consume that token before sending.
    This provides backend-enforceable HITL without a database."""

    def test_pending_drafts_registry_exists(self):
        """routes/slack.py must define _PENDING_DRAFTS dict."""
        assert "_PENDING_DRAFTS" in SRC, (
            "routes/slack.py must define _PENDING_DRAFTS: dict[str, dict] "
            "as the in-memory single-use token registry for HITL enforcement."
        )

    def test_post_endpoint_returns_confirm_token(self):
        """POST /api/slack/channels/{id}/post must return a confirm_token in the draft."""
        fn_start = SRC.find("async def slack_post_message(")
        assert fn_start != -1
        next_route = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start: next_route if next_route != -1 else fn_start + 600]
        assert "confirm_token" in fn_body, (
            "slack_post_message must issue a confirm_token and include it in the "
            "draft response: {'draft': True, 'confirm_token': '...', ...}. "
            "The /send endpoint validates this token before dispatching."
        )

    def test_send_endpoint_validates_confirm_token(self):
        """POST /api/slack/channels/{id}/send must require and consume confirm_token."""
        fn_start = SRC.find("async def slack_send_message_confirmed(")
        assert fn_start != -1
        next_route = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start: next_route if next_route != -1 else fn_start + 800]
        assert "confirm_token" in fn_body, (
            "slack_send_message_confirmed must read confirm_token from the request "
            "and call _consume_draft_token() before calling slack_send_message. "
            "Without this, /send can be called directly without a prior /post approval."
        )

    def test_confirm_token_is_single_use(self):
        """_consume_draft_token must remove the token from _PENDING_DRAFTS (pop, not get)."""
        assert "_consume_draft_token" in SRC, (
            "routes/slack.py must define _consume_draft_token() that pops "
            "the token from _PENDING_DRAFTS (single-use) and checks expiry."
        )
        fn_start = SRC.find("def _consume_draft_token(")
        if fn_start != -1:
            fn_body = SRC[fn_start: fn_start + 400]
            assert ".pop(" in fn_body, (
                "_consume_draft_token must use dict.pop() to remove the token "
                "on first use, making it single-use. dict.get() would allow replay."
            )

    def test_confirm_token_has_expiry(self):
        """Issued tokens must have a TTL (not valid forever)."""
        fn_start = SRC.find("def _issue_draft_token(")
        if fn_start != -1:
            fn_body = SRC[fn_start: fn_start + 400]
            assert "expires" in fn_body or "time.time()" in fn_body, (
                "_issue_draft_token must set an expiry timestamp so tokens "
                "cannot be replayed hours later."
            )

    def test_send_rejected_without_valid_token(self):
        """POST /send with no confirm_token must return 403, not send."""
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            import routes.slack as slack_mod

        async def _run():
            from fastapi.testclient import TestClient
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(slack_mod.router)
            client = TestClient(app)
            resp = client.post(
                "/api/slack/channels/C123/send",
                json={"message": "hello", "confirm_token": "bad-token"},
            )
            return resp.status_code, resp.json()

        status, body = asyncio.run(_run())
        assert status == 403, (
            f"Expected 403 for invalid confirm_token but got {status}. "
            "/send must reject requests without a valid token issued by /post."
        )
