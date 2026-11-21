from pathlib import Path

ROOT = Path(__file__).parent.parent


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_pill_flips_the_app_theme_instead_of_keeping_its_own_state():
    js = _read("web", "static", "tp-code-agent.js")
    assert "ThemeManager.set(" in js
    assert "ThemeManager.getActive()" in js
    for gone in (
        "terminal_theme",
        "_caSaveTerminalTheme",
        "_caLoadTerminalTheme",
        "_caTerminalTheme",
    ):
        assert gone not in js, gone


def test_theme_change_event_retints_terminals_and_refreshes_the_pill():
    js = _read("web", "static", "tp-code-agent.js")
    assert js.count("addEventListener('gator:theme-change'") == 1
    handler = js.split("addEventListener('gator:theme-change'", 1)[1].split("});", 1)[0]
    assert "_caApplyTerminalTheme()" in handler
    assert "_caRefreshThemePill()" in handler


def test_terminal_palette_comes_from_the_document_theme_attribute():
    js = _read("web", "static", "tp-code-agent.js")
    probe = js.split("function _caIsLightTheme()", 1)[1].split("\n}\n", 1)[0]
    assert "getAttribute('data-theme') === 'light'" in probe
    body = js.split("function _caXtermTheme()", 1)[1].split("\n}\n", 1)[0]
    assert "_caIsLightTheme()" in body
    assert "#0b0d12" in body
    assert "_caThemeVar('--surface', '#ffffff')" in body


def test_config_no_longer_lists_the_terminal_theme_key():
    assert "terminal_theme" not in _read("web", "config.py")
