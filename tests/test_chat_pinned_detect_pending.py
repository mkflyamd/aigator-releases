"""detect_pending is used after every turn, so it must be bound even when a skill is pinned."""

import pathlib
import re

SRC = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "chat.py").read_text(encoding="utf-8")


def test_detect_pending_import_is_not_inside_the_unpinned_branch():
    imp = SRC.index("detect_pending as _detect_pending")
    line_start = SRC.rfind("\n", 0, imp) + 1
    indent = len(SRC[line_start:imp]) - len(SRC[line_start:imp].lstrip())
    assert indent == 4, "import must sit at function level, not inside `else:` of `if _skills_locked`"
    assert re.search(r"if _skills_locked:", SRC[imp:]), "import must come before the skills-locked branch"
