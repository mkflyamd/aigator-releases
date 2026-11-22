"""The terminal "+" (new terminal) button must sit outside the scrolling tab container.

Inside .gtp-tabs-scroll (overflow-x: auto) it scrolled away with the tabs once many
terminals were open, so a new terminal could no longer be started.
"""

import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "web" / "static"
TERMINAL = (STATIC / "terminal.js").read_text(encoding="utf-8")
GENERIC = (STATIC / "tp-generic-agent-terminal.js").read_text(encoding="utf-8")
STYLE = (STATIC / "style.css").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    matches = re.findall(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", STYLE)
    assert matches, f"{selector} rule not found in style.css"
    return "".join(matches)


def test_terminal_panel_new_button_is_a_sibling_of_the_scroller():
    assert "tabsScroll.appendChild(newTabBtn)" not in TERMINAL
    assert "STATE.tabsEl.appendChild(STATE.newTabBtn)" not in TERMINAL
    assert "tabs.appendChild(newTabBtn)" in TERMINAL
    row = TERMINAL.split("tabs.appendChild(tabsScroll);", 1)[1]
    assert row.index("tabs.appendChild(newTabBtn)") < row.index("tabs.appendChild(actions)")


def test_agent_header_strip_new_button_is_a_sibling_of_the_scroller():
    assert "scroll.appendChild(newBtn)" not in GENERIC
    assert "scroll.insertBefore(tab, newBtn)" not in GENERIC
    assert "strip.appendChild(newBtn)" in GENERIC
    render = GENERIC.split("function _genAgentRenderTabs", 1)[1]
    assert "strip.querySelector('.gtp-tab-new')" in render
    assert "scroll.appendChild(tab)" in render


def test_new_button_never_shrinks_and_scroller_only_takes_the_room_it_needs():
    assert "flex-shrink: 0" in _rule(".gtp-tab-new")
    scroller = _rule(".gtp-tabs-scroll")
    assert "flex: 0 1 auto" in scroller
    assert "min-width: 0" in scroller
    assert "margin-left: auto" in _rule(".gtp-actions")
