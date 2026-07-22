"""Teams reply/forward must include a working deeplink back to the original
message. Real gap found via user report: an earlier change removed the
deeplink entirely on the theory that the Skype quote/forward markup already
gives recipients a way to jump back to the source - it doesn't (it's static
markup, not a working link), so replies and forwards had no way back to the
original thread at all. Restored the link, kept neutral (no raw formatted
timestamp baked into the message body).
"""
import pathlib

SRC = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


class TestReplyDeeplink:
    def _fn_body(self):
        # Anchor on the reply-composition block itself (renderTeamsThread is too
        # large for a fixed-size window from its own start to reliably reach it).
        start = SRC.find("if (_teamsReplyTo) {")
        assert start != -1, "reply-composition block not found"
        return SRC[start:start + 3000]

    def test_reply_builds_teams_deeplink_url(self):
        body = self._fn_body()
        assert "_replyDeeplink" in body
        assert "teams.microsoft.com/l/message/" in body

    def test_reply_appends_a_working_link(self):
        body = self._fn_body()
        assert '<a href="${_replyDeeplink}">View original message</a>' in body

    def test_reply_does_not_reintroduce_raw_timestamp_in_body(self):
        # The fix restores navigation, not the old baked-in formatted date/arrow.
        body = self._fn_body()
        assert "_tpFormatOrigWhen" not in body
        assert "↗" not in body


class TestForwardDeeplink:
    def _fn_body(self):
        start = SRC.find("function _buildTeamsMessage(")
        assert start != -1, "_buildTeamsMessage not found"
        return SRC[start:start + 20000]

    def test_forward_builds_teams_deeplink_url(self):
        body = self._fn_body()
        assert "_srcDeeplink" in body
        assert "teams.microsoft.com/l/message/" in body

    def test_forward_appends_a_working_link(self):
        body = self._fn_body()
        assert '<a href="${_srcDeeplink}">View original message</a>' in body

    def test_forward_does_not_reintroduce_raw_timestamp_in_body(self):
        body = self._fn_body()
        assert "_tpFormatOrigWhen" not in body
        assert "↗" not in body
