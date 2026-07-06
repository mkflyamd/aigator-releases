"""TDD tests for issues found in third adversarial review.

Issues:
  1. reversed() in slack_thread_detail is wrong (Slack replies are oldest-first)
  2. Frontend _slackPostMessage calls /post and shows "Sent!" — never calls /send
  3. asyncio.get_event_loop() must be get_running_loop() in route handlers
  4. slack_dms() blocks event loop on bare _load_token() call
  5. Unawaited run_in_executor future for _flush_user_cache
  6. user_display_name never written to token — dead code in _is_me()
  7. display names not html.escaped before cache storage
"""

import asyncio
import html
import json
import pathlib
import sys
from unittest.mock import patch

import pytest

SRC     = (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text(encoding="utf-8")
MCP_SRC = (pathlib.Path(__file__).parent.parent / "skills" / "slack" / "mcp_client.py").read_text(encoding="utf-8")
JS_SRC  = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Issue 1: reversed() must NOT be in slack_thread_detail
# ─────────────────────────────────────────────────────────────────────────────

class TestThreadDetailNoReverse:
    """Slack conversations.replies returns messages oldest-first.
    Applying reversed() to it produces newest-first — wrong order."""

    def test_thread_detail_does_not_reverse_raw_messages(self):
        """slack_thread_detail must NOT use reversed(raw_messages)."""
        fn_start = SRC.find("async def slack_thread_detail(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 3000]
        assert "reversed(raw_messages)" not in fn_body, (
            "slack_thread_detail must NOT reverse raw_messages. "
            "conversations.replies already returns messages oldest-first "
            "(parent at index 0, replies in ascending ts order). "
            "Reversing produces newest-first and breaks parent extraction."
        )

    def test_thread_detail_parent_is_first_message(self):
        """After the fix, messages[0] must be the parent (lowest ts)."""
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            import routes.slack as slack_mod

        slack_mod._USER_CACHE.clear()
        slack_mod._USER_CACHE_LOADED = True

        # Slack returns oldest-first: parent ts=1, reply ts=2
        replies_response = {
            "ok": True,
            "messages": [
                {"user": "U1", "text": "parent msg", "ts": "1000000001.000000"},
                {"user": "U1", "text": "reply 1",    "ts": "1000000002.000000"},
                {"user": "U1", "text": "reply 2",    "ts": "1000000003.000000"},
            ],
        }

        def fake_web_api(endpoint, params=None):
            if endpoint == "conversations.replies":
                return replies_response
            if endpoint == "users.info":
                return {"ok": True, "user": {"profile": {"display_name": "User", "real_name": ""}}}
            return {"ok": False}

        async def _run():
            with patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
                from fastapi.testclient import TestClient
                from fastapi import FastAPI
                app = FastAPI()
                app.include_router(slack_mod.router)
                client = TestClient(app)
                resp = client.get("/api/slack/threads/C123/1000000001.000000")
                return resp.json()

        data = asyncio.run(_run())
        messages = data.get("messages", [])
        assert len(messages) == 3
        # Parent must be messages[0] (lowest ts)
        assert messages[0]["ts"] == "1000000001.000000", (
            f"Parent (ts=1000000001) must be first but got ts={messages[0]['ts']}. "
            "Do not reverse — Slack already returns oldest-first."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 2: Frontend _slackPostMessage must handle draft response and call /send
# ─────────────────────────────────────────────────────────────────────────────

class TestFrontendDraftFlow:
    """The frontend _slackPostMessage must detect {draft: true} and route
    through a confirmation step, not show 'Sent!' immediately."""

    def test_slackPostMessage_does_not_show_sent_on_draft_response(self):
        """JS _slackPostMessage must NOT immediately set sendBtn.textContent='Sent!'
        when the response contains {draft: true}."""
        # Find the _slackPostMessage function body
        fn_start = JS_SRC.find("async function _slackPostMessage(")
        assert fn_start != -1
        # Find end of function (next top-level function declaration)
        fn_end = JS_SRC.find("\nasync function ", fn_start + 1)
        if fn_end == -1:
            fn_end = fn_start + 3000
        fn_body = JS_SRC[fn_start:fn_end]
        # Must check for draft before showing "Sent!"
        has_draft_check = "draft" in fn_body.lower() and (
            "resBody.draft" in fn_body or
            "res_body.draft" in fn_body or
            ".draft" in fn_body
        )
        assert has_draft_check, (
            "_slackPostMessage must inspect resBody.draft before showing 'Sent!'. "
            "When the server returns {draft: true}, the frontend must show a "
            "confirmation dialog (not 'Sent!') and then call /send on explicit approval."
        )

    def test_slackPostMessage_calls_send_endpoint_for_confirmation(self):
        """/api/slack/channels/{id}/send must be reachable from the frontend."""
        assert "/send" in JS_SRC or "confirm" in JS_SRC.lower(), (
            "The frontend must have a path to call /api/slack/channels/{id}/send "
            "after user confirmation. Currently it never calls /send."
        )

    def test_dm_send_handler_does_not_show_sent_on_draft(self):
        """DM send handler must also handle {draft: true} from /api/slack/dm."""
        # Find the DM send endpoint that POSTs (not the list /dms endpoint)
        search_from = 0
        dm_idx = -1
        while True:
            idx = JS_SRC.find("/api/slack/dm'", search_from)
            if idx == -1:
                break
            # Must be the POST endpoint (single /dm, not /dms)
            ctx_check = JS_SRC[max(0, idx - 10): idx + 20]
            if "/dms" not in ctx_check:
                dm_idx = idx
                break
            search_from = idx + 1
        assert dm_idx != -1, "DM POST call to /api/slack/dm not found in JS"
        ctx = JS_SRC[max(0, dm_idx - 500): dm_idx + 2000]
        has_draft = "draft" in ctx.lower()
        assert has_draft, (
            "The DM send handler must inspect the response for {draft: true} "
            "and not show 'DM sent!' when the message was only drafted."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 3: get_event_loop → get_running_loop
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRunningLoop:
    """Route handlers that are async must use asyncio.get_running_loop()
    not asyncio.get_event_loop() (deprecated in Python 3.10+)."""

    def test_no_get_event_loop_in_route_handlers(self):
        """routes/slack.py must not use asyncio.get_event_loop()."""
        assert "get_event_loop()" not in SRC, (
            "routes/slack.py uses asyncio.get_event_loop() which is deprecated "
            "inside a running async context (Python 3.10+). "
            "Replace all occurrences with asyncio.get_running_loop()."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 4: slack_dms must not block event loop on _load_token
# ─────────────────────────────────────────────────────────────────────────────

class TestSlackDmsNonBlocking:
    """slack_dms() must wrap _load_token() in run_in_executor like the other handlers."""

    def test_slack_dms_uses_executor_for_load_token(self):
        """slack_dms() must use run_in_executor or asyncio.to_thread for _load_token."""
        fn_start = SRC.find("async def slack_dms()")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 3000]
        uses_executor = "run_in_executor" in fn_body or "asyncio.to_thread" in fn_body
        assert uses_executor, (
            "slack_dms() calls _load_token() synchronously in an async handler, "
            "blocking the event loop on a file read. Use run_in_executor(None, _load_token)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 5: _flush_user_cache future must not be silently discarded
# ─────────────────────────────────────────────────────────────────────────────

class TestFlushFutureNotDiscarded:
    """The run_in_executor future for _flush_user_cache must be wrapped
    in asyncio.ensure_future (or equivalent) so it is not GC'd silently."""

    def test_flush_future_wrapped_in_ensure_future(self):
        """_resolve_uids_batch must wrap the flush in asyncio.ensure_future."""
        fn_start = SRC.find("async def _resolve_uids_batch(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 1000]
        has_ensure = (
            "ensure_future" in fn_body or
            "create_task" in fn_body or
            "asyncio.ensure_future" in fn_body
        )
        assert has_ensure, (
            "_resolve_uids_batch calls loop.run_in_executor(None, _flush_user_cache) "
            "without awaiting or storing the future. The future is GC'd immediately, "
            "causing Python 3.12+ warnings and potential write-loss on shutdown. "
            "Wrap with asyncio.ensure_future(loop.run_in_executor(None, _flush_user_cache))."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 6: user_display_name must be stored in token so _is_me() works
# ─────────────────────────────────────────────────────────────────────────────

class TestUserDisplayNameInToken:
    """_save_token / _exchange_code / _refresh_token must write user_display_name
    so slack_dms._is_me() can match by name as well as by user ID."""

    def test_save_token_stores_user_display_name(self):
        """mcp_client.py _save_token must persist a user_display_name key."""
        # Check _exchange_code and _refresh_token write user_display_name
        has_display_name = "user_display_name" in MCP_SRC
        assert has_display_name, (
            "mcp_client.py does not write 'user_display_name' to the token file. "
            "slack_dms._is_me() reads stored.get('user_display_name') to filter the "
            "authenticated user from group DM participant lists, but this key is never "
            "set, making the name-based branch permanently dead code. "
            "Add user_display_name to the token dict in _exchange_code and _refresh_token."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 7: Display names must be html.escaped before cache storage
# ─────────────────────────────────────────────────────────────────────────────

class TestDisplayNameStoredRaw:
    """Display names must be stored RAW in _USER_CACHE — NOT html.escaped.
    The frontend _slackMrkdwn calls _slackEsc() unconditionally before innerHTML,
    so pre-escaping on the backend causes double-encoding (visible HTML entities).
    XSS is prevented by the frontend's _slackEsc, not by backend escaping."""

    def test_resolve_uid_sync_does_not_html_escape(self):
        """_resolve_uid_sync must NOT apply html.escape — raw names stored, frontend escapes."""
        fn_start = SRC.find("def _resolve_uid_sync(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 900]
        assert "html.escape" not in fn_body, (
            "_resolve_uid_sync must not apply html.escape(). The frontend "
            "_slackMrkdwn calls _slackEsc() first — pre-escaping causes double-encoding."
        )

    def test_html_not_imported_for_escaping(self):
        """routes/slack.py must NOT import html just for escaping display names."""
        # html module may be absent OR present for other reasons — we just check
        # that it's not used in _resolve_uid_sync
        fn_start = SRC.find("def _resolve_uid_sync(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 900]
        assert "html.escape" not in fn_body, (
            "html.escape must not be used in _resolve_uid_sync."
        )

    def test_raw_name_stored_without_encoding(self):
        """A display name containing special chars must be cached verbatim."""
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
                    "display_name": "Jones & Smith <Dev>",
                    "real_name": "",
                }}}
            return {"ok": False}

        with patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
            uid, name = slack_mod._resolve_uid_sync("URAW01", "T1")

        cached = slack_mod._USER_CACHE.get("URAW01", "")
        assert cached == "Jones & Smith <Dev>", (
            f"Name was modified before caching — got {cached!r}. "
            "Store raw names; the frontend escapes at render time to avoid double-encoding."
        )
