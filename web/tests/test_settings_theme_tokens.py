"""Tests for Settings drawer theme tokens — Issue #80, superseded by #142.

Several Settings controls (LLM select, persona textarea, option lists) used
`var(--bg-1, #1e293b)`. At the time, `--bg-1` was NEVER defined anywhere in
style.css, so the hardcoded dark fallback `#1e293b` always won — even in light
theme, leaving those controls stuck dark while the rest of the drawer turns light.

#80's fix swapped every Settings-drawer `var(--bg-1, ...)` to a real,
theme-switched token (`--surface`). #142 later generalized this project-wide:
`--bg-1` (and `--bg-2`, `--bg-3`, `--bg-hover`, etc.) are now defined once as
aliases of the canonical theme-switched tokens (e.g. `--bg-1: var(--surface1)`),
so any remaining `var(--bg-1, ...)` reference anywhere — including JS-injected
inline styles #80 never touched — resolves through the theme instead of the
hardcoded fallback.
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

    def test_bg_1_is_defined_as_a_theme_switched_alias(self):
        """--bg-1 is now defined project-wide as an alias of a real theme-switched
        token (#142), not left undefined or hardcoded — so it resolves correctly
        through the active theme wherever it's still referenced."""
        assert re.search(r"--bg-1\s*:\s*var\(--surface1\)", CSS), (
            "--bg-1 must alias a real theme-switched token (--surface1), not be "
            "undefined or hardcoded (#142)"
        )

    def test_surface_token_is_theme_switched(self):
        """The replacement token must be defined for both themes."""
        defs = re.findall(r"--surface\s*:", CSS)
        assert len(defs) >= 2, (
            "--surface must be defined for both dark and light themes so the "
            "swapped controls follow the active theme."
        )
