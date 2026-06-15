"""Tests for Settings drawer theme tokens — Issue #80.

Several Settings controls (LLM select, persona textarea, option lists) used
`var(--bg-1, #1e293b)`. `--bg-1` is NEVER defined anywhere in style.css, so the
hardcoded dark fallback `#1e293b` always wins — even in light theme, leaving those
controls stuck dark while the rest of the drawer turns light.

The fix: swap every `var(--bg-1, ...)` to a real, theme-switched token (`--surface`,
which is defined for both dark (#111827) and light (#ffffff) themes), so the
controls follow the active theme.
"""

import pathlib
import re

CSS = (pathlib.Path(__file__).parent.parent / "static" / "style.css").read_text(encoding="utf-8")


class TestNoUndefinedBgToken:
    def test_bg_1_token_is_never_referenced(self):
        """No rule may reference var(--bg-1, ...) — it's an undefined token whose
        hardcoded fallback defeats theme switching."""
        refs = re.findall(r"var\(\s*--bg-1\b", CSS)
        assert not refs, (
            f"found {len(refs)} reference(s) to undefined token --bg-1; "
            "swap to a defined theme token like --surface (#80)."
        )

    def test_bg_1_is_not_defined_either(self):
        """Sanity: --bg-1 was never a real token (so swapping it loses nothing)."""
        assert not re.search(r"--bg-1\s*:", CSS), "--bg-1 unexpectedly defined"

    def test_surface_token_is_theme_switched(self):
        """The replacement token must be defined for both themes."""
        defs = re.findall(r"--surface\s*:", CSS)
        assert len(defs) >= 2, (
            "--surface must be defined for both dark and light themes so the "
            "swapped controls follow the active theme."
        )
