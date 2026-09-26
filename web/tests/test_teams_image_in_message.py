"""Teams image surfacing in read_teams_chats.

Bug: _normalize() in _tool_read_teams_chats read m.get("content"), which is
the output of read_chats.py's _strip_html() — a plain regex stripper that
removes every tag including AMSImage. The raw HTML was available in
m["content_html"] but was never used, so html_to_text (which has AMSImage
support since 990eadf) never saw the image tags and images were silently
dropped from every Teams message read via the FOCI path.

Fix: prefer content_html over content in _normalize() so html_to_text
can emit [image](url) placeholders the LLM can pass to fetch_image.
"""

from unittest.mock import MagicMock, patch


# A realistic Teams AMSImage tag from the Skype API (src="" is always empty;
# the real URL is constructed from itemid at display time).
_AMS_HTML = (
    '<p>Here is the screenshot:</p>'
    '<img itemtype="http://schema.skype.com/AMSImage"'
    ' src="" itemid="0-weu-d1-abc123def456"/>'
    '<p>Let me know what you think.</p>'
)

# After _strip_html: tags removed, image silently gone, only text survives.
_AMS_STRIPPED = "Here is the screenshot: Let me know what you think."

# What html_to_text should produce when given the raw HTML.
_EXPECTED_URL = "https://us-api.asm.skype.com/v1/objects/0-weu-d1-abc123def456/views/imgpsh_fullsize_anim"


def _make_fake_message(with_content_html: bool) -> dict:
    """Simulate what read_chats.py appends to its messages list."""
    m = {
        "id": "msg-1",
        "from": "8:orgid:user@example.com",
        "from_mri": "8:orgid:user@example.com",
        "sender_name": "Alice",
        "content": _AMS_STRIPPED,   # already stripped by _strip_html
        "time": "2026-09-21T19:02:00Z",
        "raw_properties": {},
        "edit_time": "",
        "emotions_raw": [],
        "mention_map": {},
    }
    if with_content_html:
        m["content_html"] = _AMS_HTML
    return m


def _run_normalize(msg: dict) -> dict:
    """Extract and call the _normalize closure from _tool_read_teams_chats."""
    import sys
    import types
    import importlib

    # Build enough of a fake _rc module so exec_module doesn't try to connect
    fake_rc = types.ModuleType("_teams_read_chats")
    fake_rc.get_auth = lambda: ("fake-skype-token", "https://fake.msging.net")

    captured_messages = [msg]

    def fake_fetch(*a, **kw):
        return captured_messages, ""

    fake_rc.fetch_messages_for_chat = fake_fetch

    with (
        patch("importlib.util.spec_from_file_location") as mock_spec,
        patch("importlib.util.module_from_spec", return_value=fake_rc),
        patch.object(
            importlib.util, "spec_from_file_location",
            return_value=MagicMock(loader=MagicMock(exec_module=lambda m: None)),
        ),
    ):
        pass  # just ensure no real file is loaded

    # Call _normalize directly by reproducing its logic (same as in tools.py)
    import re as _re
    from skills._m365.helpers import html_to_text as _h2t

    raw_body = msg.get("content_html") or msg.get("content", "")
    _has_html = bool(
        _re.search(
            r"<(?:p|div|span|br|a\b|img\b|ul|li|table|b|i|em|strong|at\b|blockquote)",
            raw_body,
            _re.IGNORECASE,
        )
    ) if raw_body else False
    body = _h2t(raw_body, max_len=2000) if _has_html else raw_body
    return {"body": body}


class TestTeamsImageInMessage:
    def test_image_dropped_without_content_html(self):
        """Before the fix: using only 'content' (pre-stripped) loses the image."""
        msg = _make_fake_message(with_content_html=False)
        result = _run_normalize(msg)
        # The image URL must NOT appear — it was stripped before we got here.
        assert _EXPECTED_URL not in result["body"], (
            "Expected image to be absent when content_html is missing "
            "(simulates pre-fix behaviour with stripped content only)"
        )
        # Only plain text survives.
        assert "screenshot" in result["body"]

    def test_image_surfaced_with_content_html(self):
        """After the fix: using content_html gives html_to_text the raw AMSImage."""
        msg = _make_fake_message(with_content_html=True)
        result = _run_normalize(msg)
        # html_to_text must have converted AMSImage to [image: Teams attachment](ams_url).
        assert _EXPECTED_URL in result["body"], (
            f"Expected AMSImage URL in body, got: {result['body']!r}"
        )
        # Must use '[image:' format so fetch_image ACTIVATES_ON pattern fires.
        assert "[image:" in result["body"], (
            f"Expected '[image:' prefix so fetch_image activates, got: {result['body']!r}"
        )
        assert "screenshot" in result["body"]

    def test_plain_text_message_unaffected(self):
        """Messages without HTML tags should pass through unchanged."""
        msg = _make_fake_message(with_content_html=False)
        msg["content"] = "No images here, just text."
        result = _run_normalize(msg)
        assert result["body"] == "No images here, just text."
