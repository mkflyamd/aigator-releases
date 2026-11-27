"""Remote control has its own Settings tab; General no longer holds its rows."""

import pathlib
import re

INDEX = (pathlib.Path(__file__).parent.parent / "web" / "static" / "index.html").read_text(
    encoding="utf-8"
)

MOVED_IDS = [
    "teams-remote-control-toggle",
    "slack-remote-control-toggle",
    "rc-autosend-toggle",
    "remote-default-project-slot",
    "remote-session-idle-hours",
    "remote-stale-minutes",
    "remote-armed-max-hours",
    "remote-settings-error",
]


def _panel(panel_id: str) -> str:
    start = INDEX.index(f'id="{panel_id}"')
    end = INDEX.index('class="smodal-panel', start)
    return INDEX[start:end]


def test_remote_control_tab_button_and_panel_exist():
    assert re.search(r'<button class="smodal-tab" data-tab="remote">', INDEX)
    assert INDEX.count('id="spanel-remote"') == 1


def test_moved_rows_live_in_the_remote_panel_only():
    remote = _panel("spanel-remote")
    general = _panel("spanel-general")
    for element_id in MOVED_IDS:
        assert INDEX.count(f'id="{element_id}"') == 1, element_id
        assert f'id="{element_id}"' in remote, element_id
        assert f'id="{element_id}"' not in general, element_id


def test_general_has_no_remote_control_section():
    assert ">Remote control</div>" not in _panel("spanel-general")


def test_remote_panel_has_an_empty_slot_for_agent_messaging():
    assert '<div id="remote-agents-slot"></div>' in _panel("spanel-remote")
