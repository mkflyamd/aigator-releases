"""Source-presence check for the skill-drawer live-refresh fix.

A newly-created/renamed Mine skill must appear in the Settings drawer's
Skills tab (marketplace-pane.js's Installed list) without a hard reload —
registerUserSkill()/the skill_renamed patch only update
SKILL_REGISTRY/SKILL_MAP (the "/" compose-bar dropdown's data source),
which is a disjoint array from marketplace-pane.js's own private
_installed list, fetched once via GET /api/marketplace/installed and
never re-fetched by the notification handler otherwise.
"""
import pathlib

APP_JS = (
    pathlib.Path(__file__).parent.parent / "static" / "app.js"
).read_text(encoding="utf-8")


def test_skill_registered_and_renamed_refresh_marketplace_pane():
    idx = APP_JS.index("if (msg.type === 'skill_registered'")
    body = APP_JS[idx: idx + 1500]
    assert "window.MarketplacePane?.refresh" in body

    idx2 = APP_JS.index("if (msg.type === 'skill_renamed'")
    body2 = APP_JS[idx2: idx2 + 700]
    assert "window.MarketplacePane?.refresh" in body2
