"""#125 — Mark read/unread must preserve chat list scroll position.

Both context-menu actions (Mark as Read, Mark as Unread) call renderTeamsList
which recreates the scroll container. The scroll position must be saved before
and restored after the re-render so the user stays in place.

Already fixed in the codebase — this test is the regression guard.
"""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")
_BLOCK = 700  # wide enough to capture save + render + restore


class TestMarkReadScrollPreserve:

    def test_mark_read_saves_and_restores_scroll(self):
        """Mark-as-read must save scrollTop before render and restore after."""
        idx = SRC.find("'Mark as read'")
        assert idx != -1
        block = SRC[idx:idx + _BLOCK]
        assert "_savedTop" in block or "savedTop" in block, "must save scrollTop"
        assert "scrollTop = _savedTop" in block or "scrollTop = savedTop" in block, (
            "must restore scrollTop after renderTeamsList"
        )

    def test_mark_unread_saves_and_restores_scroll(self):
        """Mark-as-unread must save scrollTop before render and restore after."""
        idx = SRC.find("'Mark as unread'")
        assert idx != -1
        block = SRC[idx:idx + _BLOCK]
        assert "_savedTop" in block or "savedTop" in block, "must save scrollTop"
        assert "scrollTop = _savedTop" in block or "scrollTop = savedTop" in block, (
            "must restore scrollTop after renderTeamsList"
        )
