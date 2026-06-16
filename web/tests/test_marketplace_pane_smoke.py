"""Playwright smoke test for the Skills & Plugins (marketplace) pane.

Catches render regressions like the merge that left `_renderInstalled` referencing
undefined `top`/`card` vars — `top` silently resolved to `window.top`, threw
`top.appendChild is not a function`, and blanked the Installed tab (Browse was fine).

Runs against an already-running dev server (default http://127.0.0.1:8000, override
with GATOR_BASE_URL). Skips cleanly when Playwright isn't installed or the server
isn't reachable, so it never breaks the unit-test suite in CI.
"""

import os
import urllib.request

import pytest

BASE_URL = os.environ.get("GATOR_BASE_URL", "http://127.0.0.1:8000")

playwright_sync = pytest.importorskip("playwright.sync_api")


def _server_up() -> bool:
    try:
        urllib.request.urlopen(f"{BASE_URL}/api/marketplace/catalog", timeout=3)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_up(),
    reason=f"dev server not reachable at {BASE_URL} (set GATOR_BASE_URL to point at one)",
)


def test_every_marketplace_tab_renders_without_console_error():
    """Open the Skills panel and click each tab; none may throw or render empty."""
    from playwright.sync_api import sync_playwright

    page_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        # Open the settings drawer on the Skills panel.
        page.evaluate("window.openSettingsPanel && window.openSettingsPanel('skills')")
        page.wait_for_selector(".mp-tab", timeout=5000)

        for tab in ("browse", "installed", "add"):
            page.click(f".mp-tab[data-tab='{tab}']")
            page.wait_for_timeout(600)
            child_count = page.eval_on_selector(
                "#mp-content", "el => el.children.length"
            )
            assert child_count > 0, f"'{tab}' tab rendered no content"
            assert not page_errors, f"console pageerror on '{tab}' tab: {page_errors}"

        browser.close()

    assert not page_errors, f"unexpected console pageerrors: {page_errors}"
