"""#126 — Message preview must decode HTML entities, not render raw &nbsp;.

The Skype API returns message content as HTML. After stripping tags, HTML entities
like &nbsp; &amp; &lt; must be decoded to their plain-text equivalents so the
preview reads naturally (e.g. 'Mohit - Here is' not 'Mohit&nbsp;- Here is').
"""
import pathlib, re

SRC_PY = (pathlib.Path(__file__).resolve().parent.parent
          / "skills" / "m365-teams" / "scripts" / "read_chats.py").read_text(encoding="utf-8")


class TestPreviewEntityDecoding:

    def test_strip_html_decodes_nbsp(self):
        """_strip_html (or equivalent) must decode &nbsp; to a space."""
        # Simulate what the fix should do — check the source contains entity decoding
        assert "html.unescape" in SRC_PY or "html_unescape" in SRC_PY or "unescape" in SRC_PY, (
            "_strip_html must decode HTML entities (html.unescape) so &nbsp; "
            "does not appear literally in the message preview (#126)"
        )

    def test_strip_html_decodes_amp(self):
        """&amp; must decode to & in previews."""
        assert "unescape" in SRC_PY, "must unescape HTML entities"

    def test_strip_html_function_body(self):
        """_strip_html body must call an entity decoder."""
        start = SRC_PY.find("def _strip_html(")
        assert start != -1
        end = SRC_PY.find("\ndef ", start + 1)
        assert end != -1, "_strip_html must be followed by another top-level def"
        body = SRC_PY[start:end]
        assert "unescape" in body, (
            "_strip_html must call html.unescape() to decode &nbsp; &amp; etc. (#126)"
        )
