"""#135 — Chat list preview missing space between sender attribution and message body
for forwarded messages.

Root cause: _strip_html does a naive regex tag-strip — block-level tags like
<blockquote>, <strong>, <div>, <p> collapse to nothing, concatenating adjacent
text runs with no separator.

Fix: block-level tags should be replaced with a space before stripping.
"""
import sys
from pathlib import Path

# Import _strip_html from read_chats.py directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "m365-teams" / "scripts"))
from read_chats import _strip_html


class TestPreviewSpacing:

    def test_blockquote_attribution_has_space(self):
        """Forwarded message: sender name inside <strong> must be separated from body text."""
        html = '<div>FYI:<blockquote><strong>Kulkarni, Mayuresh</strong>Here is the original message</blockquote></div>'
        result = _strip_html(html)
        assert 'Mayuresh' in result and 'Here' in result
        assert 'MayureshHere' not in result, (
            f"No space between attribution and body: {result!r}"
        )

    def test_adjacent_block_elements_have_space(self):
        """Adjacent block tags produce a space, not direct concatenation."""
        html = '<div>Sender A</div><div>Message text here</div>'
        result = _strip_html(html)
        assert 'ASender' not in result and 'AMessage' not in result, (
            f"Block elements concatenated without space: {result!r}"
        )

    def test_nbsp_still_decoded(self):
        """Regression: html entities still decoded after fix (#126)."""
        html = '<span>Hello&nbsp;World</span>'
        result = _strip_html(html)
        assert '&nbsp;' not in result
        assert 'Hello' in result and 'World' in result

    def test_inline_tags_no_extra_space(self):
        """Inline tags like <at> or <span> within a word don't add spurious spaces."""
        html = 'Hello <at>Mayuresh</at> how are you'
        result = _strip_html(html)
        assert result == 'Hello Mayuresh how are you', repr(result)
