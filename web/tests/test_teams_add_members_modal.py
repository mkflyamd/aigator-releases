"""#128 — Add Members modal: light-mode input styling + existing member visibility.

Two bugs:
1. The search input uses var(--bg-1,#0f172a). At the time, --bg-1 was not defined
   in style.css, so it always fell back to #0f172a (dark navy), making the input
   dark in light mode. #142 later defined --bg-1 project-wide as a theme-switched
   alias (--bg-1: var(--surface1)), so this fallback no longer bites even where
   var(--bg-1, ...) is still referenced.
2. The existing member list renders correctly when chat.members is populated, but
   must always show even in DM chats being converted to group chats (empty members).
"""
import pathlib
import re

SRC = (pathlib.Path(__file__).resolve().parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")
CSS = (pathlib.Path(__file__).resolve().parent.parent / "static" / "style.css").read_text(encoding="utf-8")


class TestAddMembersModal:

    def test_search_input_does_not_use_undefined_bg1_var(self):
        """The search input must NOT use var(--bg-1,...) — --bg-1 is undefined so
        the dark-navy fallback always applies, breaking light mode (#128)."""
        # Find the input HTML in the Add Members modal template string
        idx = SRC.find("id=\"tp-add-search\"")
        assert idx != -1
        block = SRC[idx:idx + 300]
        assert "--bg-1" not in block, (
            "Search input must not use var(--bg-1,...) — that variable is undefined "
            "in style.css so the dark fallback always applies in light mode (#128)"
        )

    def test_search_input_uses_theme_aware_bg(self):
        """Search input background must use a defined CSS variable that adapts to theme."""
        idx = SRC.find("id=\"tp-add-search\"")
        block = SRC[idx:idx + 300]
        assert ("var(--surface" in block or "var(--bg-input" in block or "var(--input" in block), (
            "Search input background must use a defined theme variable (--surface, --surface2) "
            "that adapts correctly between light and dark mode (#128)"
        )

    def test_bg1_is_theme_switched_not_hardcoded(self):
        """--bg-1 is now defined (#142) as an alias of a real theme-switched token,
        not left undefined — so the search input's fallback resolves correctly."""
        assert re.search(r"--bg-1\s*:\s*var\(--surface1\)", CSS), (
            "--bg-1 must alias a real theme-switched token (--surface1), not be "
            "undefined or hardcoded (#142)"
        )
