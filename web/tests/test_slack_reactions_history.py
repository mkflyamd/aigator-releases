"""Tests for Slack emoji reactions + message history features."""
import pathlib
import sys
from unittest.mock import patch

import pytest

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text(encoding="utf-8")
JS_SRC = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


class TestUnreactRoute:
    """POST /api/slack/unreact must call reactions.remove via Web API."""

    def test_unreact_route_exists(self):
        assert "async def slack_remove_reaction" in SRC, \
            "slack_remove_reaction route must exist in routes/slack.py"

    def test_unreact_calls_reactions_remove(self):
        fn_start = SRC.find("async def slack_remove_reaction")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start: fn_end if fn_end != -1 else fn_start + 800]
        assert "reactions.remove" in fn_body, \
            "slack_remove_reaction must call reactions.remove Slack API"

    def test_unreact_uses_post_method(self):
        fn_start = SRC.find("async def slack_remove_reaction")
        fn_end = SRC.find("\n@router.", fn_start + 1)
        fn_body = SRC[fn_start: fn_end if fn_end != -1 else fn_start + 800]
        assert "POST" in fn_body or "post" in fn_body.lower(), \
            "reactions.remove must be called via POST"


class TestSlackEmojiNameHelper:
    """_slackEmojiName must reverse-map emoji char → shortcode name."""

    def test_slackEmojiName_function_exists(self):
        assert "function _slackEmojiName(" in JS_SRC, \
            "_slackEmojiName() helper must exist in third-pane.js"

    def test_slackEmojiName_uses_shortcodes(self):
        fn_start = JS_SRC.find("function _slackEmojiName(")
        fn_end = JS_SRC.find("\n}", fn_start + 1) + 2
        fn_body = JS_SRC[fn_start:fn_end]
        assert "EMOJI_SHORTCODES" in fn_body or "_SLACK_EMOJI" in fn_body, \
            "_slackEmojiName must use EMOJI_SHORTCODES or _SLACK_EMOJI for lookup"


class TestSlackReactHelper:
    """_slackReact must call /api/slack/react or /api/slack/unreact depending on state."""

    def test_slackReact_function_exists(self):
        assert "async function _slackReact(" in JS_SRC, \
            "_slackReact() helper must exist in third-pane.js"

    def test_slackReact_calls_both_endpoints(self):
        fn_start = JS_SRC.find("async function _slackReact(")
        # Find closing brace of the async function (depth-based)
        depth = 0; i = fn_start; fn_end = fn_start + 2000
        while i < min(fn_start + 3000, len(JS_SRC)):
            if JS_SRC[i] == '{': depth += 1
            elif JS_SRC[i] == '}':
                depth -= 1
                if depth == 0: fn_end = i + 1; break
            i += 1
        fn_body = JS_SRC[fn_start:fn_end]
        assert "/api/slack/react" in fn_body, "_slackReact must call /api/slack/react"
        assert "/api/slack/unreact" in fn_body, "_slackReact must call /api/slack/unreact"

    def test_slackReact_adds_to_recent(self):
        fn_start = JS_SRC.find("async function _slackReact(")
        fn_end = fn_start + 3000
        fn_body = JS_SRC[fn_start:fn_end]
        assert "_addRecentEmoji" in fn_body, \
            "_slackReact must call _addRecentEmoji to track recently used emojis"


class TestSlackBuildReactionsRow:
    """_slackBuildReactionsRow must build clickable reaction pill buttons."""

    def test_reactions_row_function_exists(self):
        assert "function _slackBuildReactionsRow(" in JS_SRC, \
            "_slackBuildReactionsRow() must exist in third-pane.js"

    def test_reactions_row_makes_buttons(self):
        fn_start = JS_SRC.find("function _slackBuildReactionsRow(")
        fn_end = fn_start + 2000
        fn_body = JS_SRC[fn_start:fn_end]
        assert "createElement('button')" in fn_body or 'createElement("button")' in fn_body, \
            "_slackBuildReactionsRow must create button elements for clickability"


class TestChannelMessageReactionBar:
    """_slackBuildChannelMessage hover bar must include emoji reaction buttons."""

    def _fn_body(self):
        start = JS_SRC.find("function _slackBuildChannelMessage(")
        # Find next top-level function after this one
        next_fn = JS_SRC.find("\nfunction ", start + 1)
        end = next_fn if next_fn != -1 else start + 6000
        return JS_SRC[start:end]

    def test_disabled_comment_removed(self):
        body = self._fn_body()
        assert "Reaction picker disabled" not in body, \
            "The 'Reaction picker disabled' comment must be removed"

    def test_quick_react_buttons_removed(self):
        body = self._fn_body()
        assert "slack-react-quick" not in body, \
            "Quick-react buttons (class slack-react-quick) must NOT be in _slackBuildChannelMessage — removed by fix 1c"

    def test_add_reaction_button_added(self):
        body = self._fn_body()
        assert "slack-react-add" in body, \
            "Add-reaction button (class slack-react-add) must be in _slackBuildChannelMessage"

    def test_material_symbol_svg_used(self):
        body = self._fn_body()
        assert "viewBox=\"0 -960 960 960\"" in body or "sentiment_satisfied" in body, \
            "Must use Material Symbols SVG for the add-reaction button"

    def test_uses_slackBuildReactionsRow(self):
        body = self._fn_body()
        assert "_slackBuildReactionsRow" in body, \
            "_slackBuildChannelMessage must use _slackBuildReactionsRow for clickable reaction pills"


class TestThreadReplyReactionBar:
    """_slackBuildMessage (thread replies) must also use _slackBuildReactionsRow."""

    def _fn_body(self):
        start = JS_SRC.find("function _slackBuildMessage(")
        next_fn = JS_SRC.find("\nfunction ", start + 1)
        return JS_SRC[start: next_fn if next_fn != -1 else start + 3000]

    def test_thread_reply_uses_reactions_row(self):
        body = self._fn_body()
        assert "_slackBuildReactionsRow" in body, \
            "_slackBuildMessage must use _slackBuildReactionsRow for thread reply reactions"

    def test_thread_reply_has_add_reaction_button(self):
        body = self._fn_body()
        assert "slack-react-add" in body or "_openFullEmojiPicker" in body, \
            "_slackBuildMessage must include an add-reaction button"


CSS_SRC = (pathlib.Path(__file__).parent.parent / "static" / "style.css").read_text(encoding="utf-8")

class TestNewCSSRules:
    def test_slack_react_add_css_exists(self):
        assert ".slack-react-add" in CSS_SRC, ".slack-react-add CSS rule must exist"

    def test_slack_reaction_btn_css_exists(self):
        assert ".slack-reaction-btn" in CSS_SRC, ".slack-reaction-btn CSS rule must exist"

    def test_slack_history_loading_css_exists(self):
        assert ".slack-history-loading" in CSS_SRC, ".slack-history-loading CSS rule must exist"


class TestMessageHistory:
    """Scroll-up history loading must be wired in _slackRenderMessages."""

    def test_slackLoadOlderMessages_exists(self):
        assert "async function _slackLoadOlderMessages(" in JS_SRC, \
            "_slackLoadOlderMessages() must exist"

    def test_slackOnScroll_exists(self):
        assert "function _slackOnScroll(" in JS_SRC, \
            "_slackOnScroll() scroll handler must exist"

    def test_slackState_has_cursor_fields(self):
        state_start = JS_SRC.find("const _slackState = {")
        state_end = JS_SRC.find("};", state_start) + 2
        state_body = JS_SRC[state_start:state_end]
        assert "_slackCursor" in state_body, "_slackState must include _slackCursor field"
        assert "_slackLoadingOlder" in state_body, "_slackState must include _slackLoadingOlder field"

    def test_load_older_uses_cursor(self):
        fn_start = JS_SRC.find("async function _slackLoadOlderMessages(")
        fn_body = JS_SRC[fn_start: fn_start + 3000]
        assert "_slackCursor" in fn_body, "_slackLoadOlderMessages must use _slackState._slackCursor"

    def test_load_older_preserves_scroll(self):
        fn_start = JS_SRC.find("async function _slackLoadOlderMessages(")
        fn_body = JS_SRC[fn_start: fn_start + 3000]
        assert "scrollHeight" in fn_body, "_slackLoadOlderMessages must preserve scroll using scrollHeight diff"

    def test_load_older_prepends_messages(self):
        fn_start = JS_SRC.find("async function _slackLoadOlderMessages(")
        fn_body = JS_SRC[fn_start: fn_start + 3000]
        assert "prepend" in fn_body or "insertBefore" in fn_body, \
            "_slackLoadOlderMessages must prepend older messages above existing ones"
