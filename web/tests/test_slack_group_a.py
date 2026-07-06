"""Tests for Slack Group A fixes."""
import pathlib
import sys

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text(encoding="utf-8")
JS_SRC = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")
CSS_SRC = (pathlib.Path(__file__).parent.parent / "static" / "style.css").read_text(encoding="utf-8")


class TestRealNamePreference:
    """Fix 1b: _resolve_uid_sync must prefer real_name over display_name."""

    def test_resolve_uid_sync_prefers_real_name(self):
        fn_start = SRC.find("def _resolve_uid_sync(")
        fn_end = SRC.find("\ndef ", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        # real_name must appear BEFORE display_name in the name resolution
        real_idx = fn_body.find('"real_name"')
        display_idx = fn_body.find('"display_name"')
        assert real_idx != -1, "_resolve_uid_sync must reference real_name"
        assert display_idx != -1, "_resolve_uid_sync must reference display_name"
        assert real_idx < display_idx, (
            "real_name must be preferred over display_name — "
            "change: p.get('display_name') or p.get('real_name') "
            "to: p.get('real_name') or p.get('display_name')"
        )


class TestNoQuickReactEmojis:
    """Fix 1c: hover bar must NOT include quick-react emoji buttons."""

    def _channel_msg_fn(self):
        start = JS_SRC.find("function _slackBuildChannelMessage(")
        end = JS_SRC.find("\nfunction ", start + 1)
        return JS_SRC[start:end]

    def _thread_msg_fn(self):
        start = JS_SRC.find("function _slackBuildMessage(")
        end = JS_SRC.find("\nfunction ", start + 1)
        return JS_SRC[start:end]

    def test_no_quick_react_in_channel_message(self):
        body = self._channel_msg_fn()
        assert "slack-react-quick" not in body, (
            "_slackBuildChannelMessage must not contain slack-react-quick buttons. "
            "Remove the _getRecentEmojis().slice(0,2).forEach(...) block."
        )

    def test_no_quick_react_in_thread_message(self):
        body = self._thread_msg_fn()
        assert "slack-react-quick" not in body, (
            "_slackBuildMessage must not contain slack-react-quick buttons."
        )


class TestForwardButton:
    """Fix 1d: channel message hover bar must include a forward button."""

    def _channel_msg_fn(self):
        start = JS_SRC.find("function _slackBuildChannelMessage(")
        end = JS_SRC.find("\nfunction ", start + 1)
        return JS_SRC[start:end]

    def test_forward_button_exists_in_channel_message(self):
        body = self._channel_msg_fn()
        assert "slack-forward-btn" in body, (
            "_slackBuildChannelMessage must include a forward button with class slack-forward-btn"
        )

    def test_forward_button_calls_dm_compose(self):
        body = self._channel_msg_fn()
        assert "_slackShowDMCompose" in body, (
            "Forward button must call _slackShowDMCompose"
        )

    def test_forward_css_exists(self):
        assert ".slack-forward-btn" in CSS_SRC, (
            ".slack-forward-btn CSS rule must exist in style.css"
        )

    def test_dm_compose_accepts_prefill(self):
        fn_start = JS_SRC.find("function _slackShowDMCompose(")
        fn_body = JS_SRC[fn_start: fn_start + 100]
        assert "prefillText" in fn_body or "prefill" in fn_body.lower(), (
            "_slackShowDMCompose must accept a prefillText parameter for forward content"
        )


class TestForwardedMessageText:
    """Fix 2: _slack_extract_text and message filter must handle forwarded messages."""

    def test_extract_text_reads_attachments_even_when_text_present(self):
        """Bug B: attachments must be read even when text is non-empty (boilerplate)."""
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]
        from unittest.mock import patch
        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"):
            import routes.slack as slack_mod

        msg = {
            "text": "shared a message",
            "attachments": [
                {
                    "author_name": "Alice",
                    "text": "This is the real forwarded content",
                    "fallback": "Alice: This is the real forwarded content",
                }
            ],
        }
        result = slack_mod._slack_extract_text(msg)
        assert "real forwarded content" in result, (
            f"_slack_extract_text must include attachment content even when msg.text is non-empty. Got: {result!r}"
        )

    def test_extract_text_reads_attachments_when_text_empty(self):
        """Basic attachment extraction works."""
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]
        from unittest.mock import patch
        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"):
            import routes.slack as slack_mod

        msg = {
            "text": "",
            "attachments": [{"fallback": "Hello from the attachment", "author_name": "Bob"}],
        }
        result = slack_mod._slack_extract_text(msg)
        assert "Hello from the attachment" in result, (
            f"_slack_extract_text must read attachment fallback when text is empty. Got: {result!r}"
        )

    def test_bot_message_with_attachment_not_filtered(self):
        """Bug A: bot_message filter must use _slack_extract_text not msg.get('text')."""
        fn_start = SRC.find("def slack_channel_messages(")
        filter_idx = SRC.find("bot_message", fn_start)
        filter_line_start = SRC.rfind("\n", 0, filter_idx) + 1
        filter_line_end = SRC.find("\n", filter_idx)
        filter_line = SRC[filter_line_start:filter_line_end]
        assert "_slack_extract_text" in filter_line, (
            f"The bot_message filter must use _slack_extract_text(msg), not msg.get('text'). "
            f"Current filter line: {filter_line.strip()!r}"
        )


class TestSlackMentionDropdown:
    """Fix 3: Slack compose must use Slack people search not M365."""

    def test_wireMentionDropdownSlack_exists(self):
        assert "function _wireMentionDropdownSlack(" in JS_SRC, (
            "_wireMentionDropdownSlack must exist in third-pane.js"
        )

    def test_wireMentionDropdownSlack_calls_slack_users_api(self):
        fn_start = JS_SRC.find("function _wireMentionDropdownSlack(")
        fn_end = fn_start + 4000
        depth = 0; i = fn_start
        while i < fn_start + 5000 and i < len(JS_SRC):
            if JS_SRC[i] == '{': depth += 1
            elif JS_SRC[i] == '}':
                depth -= 1
                if depth == 0: fn_end = i + 1; break
            i += 1
        fn_body = JS_SRC[fn_start:fn_end]
        assert "/api/slack/users/" in fn_body, (
            "_wireMentionDropdownSlack must call /api/slack/users/{query}"
        )

    def test_channel_compose_uses_slack_mention(self):
        fn_start = JS_SRC.find("function _slackRenderMessages(")
        fn_end = JS_SRC.find("\nasync function _slackSelectChannel", fn_start + 1)
        fn_body = JS_SRC[fn_start:fn_end if fn_end != -1 else fn_start + 8000]
        assert "_wireMentionDropdownSlack" in fn_body, (
            "Channel compose (_wireQuill inside _slackRenderMessages) must call _wireMentionDropdownSlack"
        )

    def test_thread_reply_compose_uses_slack_mention(self):
        fn_start = JS_SRC.find("function _slackRenderThreadDetail(")
        fn_end = JS_SRC.find("\nfunction ", fn_start + 1)
        fn_body = JS_SRC[fn_start:fn_end if fn_end != -1 else fn_start + 8000]
        assert "_wireMentionDropdownSlack" in fn_body, (
            "_wireReply inside _slackRenderThreadDetail must call _wireMentionDropdownSlack"
        )


class TestMPIMDmNames:
    """Fix 4: MPIM (group DM) channels must resolve participant names via conversations.members."""

    def test_slack_dms_fetches_members_for_mpim(self):
        fn_start = SRC.find("async def slack_dms()")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "conversations.members" in fn_body, (
            "slack_dms must call conversations.members for MPIM channels to get participant names"
        )

    def test_slack_dms_guards_authed_user_uid(self):
        fn_start = SRC.find("async def slack_dms()")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start:fn_end]
        assert "authed_user_id" in fn_body and "is_mpim" in fn_body, (
            "slack_dms must check is_mpim and filter out authed_user_id from member list"
        )
