"""The settings drawer exit must not look like the app's window-close button."""

from pathlib import Path


STATIC = Path(__file__).parent.parent / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STYLE = (STATIC / "style.css").read_text(encoding="utf-8")


def test_settings_drawer_exit_is_a_labelled_back_button_not_a_window_close():
    start = INDEX.index('id="drawer-close"')
    button = INDEX[INDEX.rindex("<button", 0, start) : INDEX.index("</button>", start)]

    assert "drawer-back-btn" in button
    assert "win-close" not in button
    assert "<span>Back</span>" in button
    assert 'title="Back to chat"' in button
    assert ".drawer-back-btn {" in STYLE
