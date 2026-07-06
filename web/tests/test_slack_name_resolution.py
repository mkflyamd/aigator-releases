"""Tests for Slack name resolution fix — Phase 1 of Slack feature parity.

Verifies:
1. Backend message response has user=display_name and user_id=UID
2. clear_user_cache() wipes the disk file (not just in-memory dict)
3. Frontend JS does NOT pass msg.user through _slackDisplayName (source check)
"""

import json
import pathlib
import sys
import tempfile
from unittest.mock import patch

import pytest

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text(encoding="utf-8")
JS_SRC = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


class TestBackendMessageShape:
    """Backend must return user=display_name AND user_id=UID in message objects."""

    def test_slack_channel_messages_returns_user_and_user_id(self):
        """slack_channel_messages response must include both 'user' (name) and 'user_id' (UID)."""
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            import routes.slack as slack_mod

        slack_mod._USER_CACHE.clear()
        slack_mod._USER_CACHE_LOADED = True

        history = {
            "ok": True,
            "messages": [
                {"user": "U0MAHGAONK", "text": "hello", "ts": "1700000001.000000"},
            ],
            "response_metadata": {"next_cursor": ""},
        }

        def fake_api(endpoint, params=None):
            if endpoint == "conversations.history":
                return history
            if endpoint == "users.info":
                uid = (params or {}).get("user", "")
                return {"ok": True, "user": {"profile": {
                    "display_name": "mahgaonk", "real_name": "M Gaonk",
                }}}
            return {"ok": False}

        import asyncio
        async def _run():
            with patch.object(slack_mod, "_slack_web_api", side_effect=fake_api):
                from fastapi.testclient import TestClient
                from fastapi import FastAPI
                app = FastAPI()
                app.include_router(slack_mod.router)
                client = TestClient(app)
                resp = client.get("/api/slack/channels/C123/messages?limit=1")
                return resp.json()

        data = asyncio.run(_run())
        messages = data.get("messages", [])
        assert len(messages) == 1
        msg = messages[0]
        assert "user" in msg, "Response must include 'user' field (display name)"
        assert "user_id" in msg, "Response must include 'user_id' field (UID)"
        assert msg["user_id"] == "U0MAHGAONK", f"user_id must be the Slack UID, got: {msg['user_id']}"
        # The 'user' field must be the resolved display name, not the UID
        assert msg["user"] != "U0MAHGAONK", (
            f"'user' field must be the display name, not the UID. Got: {msg['user']}"
        )


class TestClearUserCacheDiskWipe:
    """clear_user_cache() must wipe user_cache.json on disk."""

    def test_clear_user_cache_writes_empty_json_to_disk(self):
        """After clear_user_cache(), _USER_CACHE_FILE must contain '{}'."""
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={}):
            import routes.slack as slack_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_cache_file = pathlib.Path(tmpdir) / "user_cache.json"
            fake_cache_file.write_text(json.dumps({"U123": "Mayuresh Kulkarni"}))

            # Patch the module-level file path
            orig_file = slack_mod._USER_CACHE_FILE
            slack_mod._USER_CACHE_FILE = fake_cache_file
            try:
                # Pre-populate in-memory cache
                with slack_mod._USER_CACHE_LOCK:
                    slack_mod._USER_CACHE["U123"] = "Mayuresh Kulkarni"
                    slack_mod._USER_CACHE_LOADED = True

                slack_mod.clear_user_cache()

                # In-memory must be cleared
                assert "U123" not in slack_mod._USER_CACHE, "In-memory cache must be cleared"
                assert not slack_mod._USER_CACHE_LOADED, "_USER_CACHE_LOADED must be False"

                # Disk file must be empty JSON object
                content = fake_cache_file.read_text()
                assert content == "{}", (
                    f"user_cache.json must contain '{{}}' after clear, got: {content!r}"
                )
            finally:
                slack_mod._USER_CACHE_FILE = orig_file


class TestFrontendNoSlackDisplayNameOnMsgUser:
    """Frontend _slackBuildChannelMessage must NOT pass msg.user to _slackDisplayName."""

    def test_build_channel_message_does_not_call_slackDisplayName_with_msguser(self):
        """_slackBuildChannelMessage must use msg.user directly, not via _slackDisplayName."""
        fn_start = JS_SRC.find("function _slackBuildChannelMessage(")
        assert fn_start != -1
        # Find the end of the function (next top-level function)
        fn_end = JS_SRC.find("\nfunction ", fn_start + 1)
        fn_body = JS_SRC[fn_start: fn_end if fn_end != -1 else fn_start + 2000]

        # Must NOT have _slackDisplayName(user) or _slackDisplayName(msg.user)
        assert "_slackDisplayName(user)" not in fn_body, (
            "_slackBuildChannelMessage must NOT call _slackDisplayName(user). "
            "msg.user is already the resolved display name from the backend."
        )
        assert "_slackDisplayName(msg.user)" not in fn_body, (
            "_slackBuildChannelMessage must NOT call _slackDisplayName(msg.user)."
        )

    def test_build_channel_message_uses_msg_user_id_for_data_attribute(self):
        """data-slack-user must be keyed on msg.user_id (UID), not msg.user (display name)."""
        fn_start = JS_SRC.find("function _slackBuildChannelMessage(")
        assert fn_start != -1
        fn_end = JS_SRC.find("\nfunction ", fn_start + 1)
        fn_body = JS_SRC[fn_start: fn_end if fn_end != -1 else fn_start + 2000]

        # Must use userId (msg.user_id) for the data-slack-user attribute
        assert "userId" in fn_body, "_slackBuildChannelMessage must extract userId = msg.user_id"
        assert "dataset.slackUser = userId" in fn_body or "slackUser = userId" in fn_body, (
            "data-slack-user attribute must be set to userId (the Slack UID), not the display name"
        )

    def test_build_message_does_not_call_slackDisplayName(self):
        """_slackBuildMessage must also use msg.user directly."""
        fn_start = JS_SRC.find("function _slackBuildMessage(")
        assert fn_start != -1
        fn_end = JS_SRC.find("\nfunction ", fn_start + 1)
        fn_body = JS_SRC[fn_start: fn_end if fn_end != -1 else fn_start + 2000]

        assert "_slackDisplayName(user)" not in fn_body, (
            "_slackBuildMessage must NOT call _slackDisplayName(user). "
            "msg.user is already the resolved display name."
        )
