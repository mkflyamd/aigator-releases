"""#120 — @mention picker in New Conversation must anchor to quill.root, not msgWrap.

The New Conversation compose called _wireMentionDropdownQuill(editor.quill, msgWrap)
where msgWrap is the outer wrapper div. At first @-trigger, msgWrap has zero or wrong
bounding rect so FloatingUI positioned the dropdown at the bottom of the screen.
On typing, autoUpdate fires, Quill root now has proper bounds → picker jumps to correct
position. Fix: pass editor.quill.root as the anchor so FloatingUI has the correct
element with proper bounds from the first keystroke.
"""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


class TestMentionPickerPosition:

    def test_new_compose_uses_quill_root_as_anchor(self):
        """New Conversation compose must pass editor.quill.root (not msgWrap) to
        _wireMentionDropdownQuill so FloatingUI has correct bounds at first trigger."""
        idx = SRC.find("_wireMentionDropdownQuill(editor.quill, msgWrap)")
        assert idx == -1, (
            "New Conversation must not pass msgWrap to _wireMentionDropdownQuill — "
            "msgWrap has wrong bounds at first trigger causing bottom-screen position. "
            "Use editor.quill.root instead (#120)"
        )

    def test_new_compose_uses_quill_root(self):
        """_wireMentionDropdownQuill in New Conversation context uses quill.root."""
        # Should use editor.quill.root (or q.root) — same pattern as inline thread
        idx = SRC.find("_wireMentionDropdownQuill(editor.quill, editor.quill.root)")
        assert idx != -1, (
            "_wireMentionDropdownQuill in New Conversation must pass editor.quill.root "
            "as the anchor element (#120)"
        )
