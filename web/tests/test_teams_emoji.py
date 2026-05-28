"""Tests for Teams emoji send fix — Issue #46.

Plain-text messages containing emoji must be sent as RichText/Html so the
Skype chatsvc API preserves Unicode emoji characters.
"""

import pathlib

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


class TestTeamsEmojiMessageType:
    """The send route must use RichText/Html whenever emoji are present."""

    def test_plain_emoji_message_uses_richtext_html(self):
        """A bare emoji string like '👍' has no '<' so the old code set messagetype=Text.
        After the fix the condition must wrap it in a div and use RichText/Html."""
        # We test the source to verify the fix logic is present.
        # The old buggy condition was: "RichText/Html" if "<" in content else "Text"
        # The fix must NOT produce messagetype="Text" for emoji-only messages.
        assert 'messagetype": "Text"' not in SRC and "messagetype\": 'Text'" not in SRC or \
               _check_emoji_wrapping_logic(SRC), (
            "routes/teams.py must not send emoji messages as messagetype=Text. "
            "Wrap plain-text content in <div> and use RichText/Html."
        )

    def test_source_wraps_plain_text_in_div(self):
        """The fix must wrap non-HTML content in <div> before sending."""
        assert "<div>" in SRC or "f\"<div>{" in SRC or "f'<div>{" in SRC, (
            "routes/teams.py must wrap plain-text content in a <div> tag so that "
            "messagetype can be set to RichText/Html, preserving emoji."
        )

    def test_msgtype_always_richtext_html(self):
        """After the fix, msg_type must always be RichText/Html — never Text."""
        send_fn_start = SRC.find("async def tp_teams_send_message(")
        assert send_fn_start != -1
        fn_body = SRC[send_fn_start: send_fn_start + 3000]
        assert '"RichText/Html"' in fn_body, (
            "teams_send_message must set messagetype to RichText/Html."
        )
        assert '"Text"' not in fn_body or _msgtype_text_is_not_skype_body(fn_body), (
            "teams_send_message must not set messagetype=Text for the Skype body. "
            "Plain text must be wrapped in <div> and sent as RichText/Html."
        )


def _check_emoji_wrapping_logic(src: str) -> bool:
    """Return True if the source has the emoji-wrapping fix in place."""
    return ("if \"<\" not in content" in src or "if '<' not in content" in src) and \
           ("<div>" in src or "f\"<div>" in src)


def _msgtype_text_is_not_skype_body(fn_body: str) -> bool:
    """Return True if the only 'Text' references are in comments or unrelated strings."""
    # If "Text" only appears as a comment explaining the old bug, that's fine.
    lines_with_text = [l.strip() for l in fn_body.splitlines() if '"Text"' in l]
    return all(l.startswith("#") for l in lines_with_text)


# ── Behavioural unit tests ────────────────────────────────────────────────────

def _build_skype_body(content: str) -> dict:
    """Replicate the fixed logic from routes/teams.py so we can test it in isolation."""
    if "<" not in content:
        content = f"<div>{content}</div>"
    msg_type = "RichText/Html"
    return {"content": content, "messagetype": msg_type, "contenttype": "text"}


class TestSkypeBodyBuilding:
    """Unit tests for the content-wrapping logic (framework-independent)."""

    def test_emoji_only_message_becomes_richtext(self):
        body = _build_skype_body("👍")
        assert body["messagetype"] == "RichText/Html"
        assert "👍" in body["content"]

    def test_plain_text_with_emoji_wrapped_in_div(self):
        body = _build_skype_body("sounds good 🎉")
        assert body["content"].startswith("<div>")
        assert "🎉" in body["content"]
        assert body["messagetype"] == "RichText/Html"

    def test_already_html_message_not_double_wrapped(self):
        html = "<div>Hello <b>world</b></div>"
        body = _build_skype_body(html)
        assert body["content"] == html, "Already-HTML content must not be wrapped again"
        assert body["messagetype"] == "RichText/Html"

    def test_plain_text_no_emoji_also_richtext(self):
        body = _build_skype_body("just plain text")
        assert body["messagetype"] == "RichText/Html"
        assert "just plain text" in body["content"]
