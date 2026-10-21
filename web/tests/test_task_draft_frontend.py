"""Source-presence checks for the _openTaskResult draft-rendering fix
(issue #54) — mirrors this repo's existing convention (see
tests/test_skill_slash_alias.py, tests/test_hitl_draft_unification.py) of
asserting key literals exist in app.js rather than running a JS test
runner, since none exists in this suite.
"""
import pathlib

APP_JS = (
    pathlib.Path(__file__).parent.parent / "static" / "app.js"
).read_text(encoding="utf-8")


def test_open_task_result_checks_drafts_array():
    assert "Array.isArray(t.drafts)" in APP_JS, (
        "_openTaskResult must read the drafts array GET /api/tasks/{id} now returns"
    )
    assert "_renderTaskDraft(d)" in APP_JS


def test_render_task_draft_renders_actionable_card_for_pending():
    idx = APP_JS.index("function _renderTaskDraft(d)")
    body = APP_JS[idx: idx + 1500]
    assert "d.status === 'pending' && !d.expired" in body
    assert "_injectDraftApprovalCard(d.draft_type, d.draft_data)" in body


def test_render_task_draft_covers_all_nonactionable_states():
    idx = APP_JS.index("function _renderTaskDraft(d)")
    body = APP_JS[idx: idx + 2000]
    # Acceptance criteria (issue #54): sent, failed, expired, and
    # unavailable/in-progress drafts must all render an explicit
    # non-actionable state, never silently nothing.
    assert "sent:" in body
    assert "handed_off:" in body
    assert "sending:" in body
    assert "handing_off:" in body
    assert "already sent" in body
    assert "expired" in body


def test_skill_registered_and_renamed_refresh_marketplace_pane():
    """A newly-created/renamed Mine skill must appear in the Settings
    drawer's Skills tab (marketplace-pane.js's Installed list) without a
    hard reload — registerUserSkill()/the skill_renamed patch only update
    SKILL_REGISTRY/SKILL_MAP (the "/" dropdown's data source), which is a
    disjoint array from marketplace-pane.js's own private _installed list."""
    idx = APP_JS.index("if (msg.type === 'skill_registered'")
    body = APP_JS[idx: idx + 1500]
    assert "window.MarketplacePane?.refresh" in body

    idx2 = APP_JS.index("if (msg.type === 'skill_renamed'")
    body2 = APP_JS[idx2: idx2 + 700]
    assert "window.MarketplacePane?.refresh" in body2
