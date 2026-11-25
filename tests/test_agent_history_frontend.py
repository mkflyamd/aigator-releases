"""Source-string wiring checks for the agent history UI (the DOM paths need a real browser)."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
TERM = (STATIC / "tp-generic-agent-terminal.js").read_text(encoding="utf-8")
HANDOFF = (STATIC / "agent-handoff.js").read_text(encoding="utf-8")
CODE = (STATIC / "tp-code-agent.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
HISTORY = (STATIC / "agent-history.js").read_text(encoding="utf-8")


def test_spawn_requests_carry_the_resume_id():
    assert TERM.count("resume_id: opts.resumeId") == 2  # _ocFetch and fetch branches


def test_activating_a_session_marks_it_viewed():
    assert "if (sess) sess._viewedAt = Date.now();" in TERM


def test_output_in_the_viewed_terminal_counts_as_seen():
    assert "agentHistory.isViewing(sess))\n          sess._viewedAt = sess._lastOutputAt;" in TERM


def test_echo_and_repaint_output_does_not_count_as_working():
    helpers = (STATIC / "tp-term-helpers.js").read_text(encoding="utf-8")
    assert "if (Date.now() >= (sess._quietUntil || 0)) {" in TERM
    assert TERM.index("if (Date.now() >= (sess._quietUntil || 0)) {") < TERM.index("sess._lastOutputAt = Date.now();")
    on_open = TERM.index("sess.ws.onopen = () => {")
    assert "_ocNoteEcho(sess);" in TERM[on_open : on_open + 120]
    on_data = helpers.index("sess.term.onData((data) => {")
    assert "_ocNoteEcho(sess);" in helpers[on_data : helpers.index("type: 'input'", on_data)]
    resize = helpers.index("type: 'resize'")
    assert "_ocNoteEcho(sess);" in helpers[resize - 120 : resize]


def test_handoff_dialog_takes_a_stored_session():
    assert "opts.stored" in HANDOFF
    assert "keepStateAgent: !!state.agent" in HANDOFF
    assert "_genAgentEnsureTermsContainer(opts.tabId)" in HANDOFF


def test_left_panel_has_three_icon_tabs():
    for name in ("explorer", "scm", "history"):
        assert f'id="ca-viewtab-{name}"' in CODE
        assert f"gatorActionAttrs('_caSetLeftView', ['{name}'])" in CODE
    for label in ("Files", "Changes", "History"):
        assert f'aria-label="{label}"' in CODE
        assert f'title="{label}"' in CODE
    assert ">Source Control</button>" not in CODE
    assert ">Explorer</button>" not in CODE


def test_history_pane_markup_is_in_the_left_panel():
    for el in ('id="ca-hist-view"', 'id="ca-hist-search"', 'id="ca-hist-list"'):
        assert el in CODE


def test_switching_views_covers_history_and_survives_a_pane_rebuild():
    assert "agentHistory.show()" in CODE
    assert "agentHistory.refresh()" in CODE
    assert "if (_caLeftView !== 'scm') _caSetLeftView(_caLeftView);" in CODE


def test_history_script_loads_after_handoff_and_before_the_terminal_module():
    h, a, t = (INDEX.index(n) for n in ("agent-handoff.js", "agent-history.js", "tp-generic-agent-terminal.js"))
    assert h < a < t


def test_history_styles_use_theme_variables_only():
    block = CSS.split("/* agent session history: start */")[1].split("/* agent session history: end */")[0]
    assert ".ah-row" in block and ".ca-hist-view" in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", block)


def test_history_panel_never_builds_markup_from_session_text():
    ctl = HISTORY.split("Browser panel")[1]
    assert "innerHTML" not in ctl
    assert "insertAdjacentHTML" not in ctl


def test_a_project_switch_clears_the_old_rows_straight_away():
    branch = HISTORY.split("if (ui.project !== project.name) {")[1].split("ui.wslPolls = 0;")[1][:40]
    assert branch.strip().startswith("render();")


def test_rebuilding_the_list_keeps_keyboard_focus_on_the_same_row_and_button():
    assert "item.dataset.key = row.key;" in HISTORY
    assert "const focused = focusedTarget(list);" in HISTORY
    assert "restoreFocus(list, focused);" in HISTORY


def test_row_actions_are_icon_only_buttons_with_tooltips_and_labels():
    for label in ("Resume", "Hand off to another agent", "Go to terminal"):
        assert f"'{label}'" in HISTORY
    assert "btn.title = " in HISTORY
    assert "btn.setAttribute('aria-label', " in HISTORY
    assert "resume: ['▶'," in HISTORY
    assert "handoff: ['↪'," in HISTORY
    assert "createElementNS" in HISTORY
    assert "Continue in another agent" not in HISTORY


def test_go_to_terminal_is_disabled_while_that_terminal_is_on_screen():
    assert "btn.disabled = true;" in HISTORY
    assert "'Already open'" in HISTORY
    assert "'Go to terminal (already open)'" in HISTORY
    assert "isViewing(" in HISTORY.split("function rowViewing")[1].split("function ")[0]
    # the state is part of the render signature so the 2s tick refreshes it
    sig = HISTORY.split("const sig = JSON.stringify([")[1].split("if (sig === ui.sig")[0]
    assert "rowViewing(r)" in sig


def test_restoring_focus_skips_a_button_that_became_disabled():
    restore = HISTORY.split("function restoreFocus")[1].split("function ")[0]
    assert "!next.disabled" in restore
    # rebuilt chips are hidden until :focus-within, so they are revealed for the focus call
    assert "item.classList.add('ah-restoring');" in restore
    assert ".ah-item.ah-restoring .ah-actions" in CSS


def test_history_has_no_solid_primary_button_variant():
    assert "ah-btn-primary" not in HISTORY
    assert "ah-btn-primary" not in CSS


def _history_css():
    return CSS.split("/* agent session history: start */")[1].split("/* agent session history: end */")[0]


def test_row_actions_are_tinted_chips_with_their_own_hue_and_retry_keeps_a_text_button():
    block = _history_css()
    assert "el('button', 'ah-icon-btn ah-chip-' + action)" in HISTORY
    for chip in (".ah-chip-resume", ".ah-chip-handoff", ".ah-chip-go"):
        assert chip in block
    # Handoff gets a hue other than the green accent so it never blends with Resume
    handoff = block.split(".ah-chip-handoff {")[1].split("}")[0]
    assert "--ah-chip: var(--ah-handoff)" in handoff
    assert ".ah-icon-btn:focus-visible" in block
    # the hover fill is a stronger tint than the resting chip, never the row surface token
    hover = block.split(".ah-icon-btn:hover {")[1].split("}")[0]
    assert "color-mix(in srgb, var(--ah-chip) 26%" in hover
    assert "var(--bg-hover)" not in hover
    # the disabled rule comes after hover so a disabled chip shows no hover fill
    disabled = block.split(".ah-icon-btn:disabled {")[1].split("}")[0]
    assert "background: transparent" in disabled
    assert block.index(".ah-icon-btn:disabled") > block.index(".ah-icon-btn:hover")
    assert "el('button', 'ah-btn', 'Retry')" in HISTORY
    assert re.search(r"\.ah-btn\s*\{", block)


def test_rows_no_longer_expand_in_place():
    for gone in ("buildDetail", "toggleOpen", "openKey", "aria-expanded", "ah-detail"):
        assert gone not in HISTORY
    assert "ah-detail" not in _history_css()


def test_the_preview_is_one_tooltip_card_outside_the_list():
    assert "const HOVER_MS = 300;" in HISTORY
    assert "card.setAttribute('role', 'tooltip');" in HISTORY
    assert "document.body.appendChild(card);" in HISTORY
    assert "setAttribute('aria-describedby', 'ah-flyout')" in HISTORY
    assert "removeAttribute('aria-describedby')" in HISTORY
    block = _history_css()
    rules = re.findall(r"\n\.ah-flyout \{([^}]*)\}", block)
    assert any("position: fixed" in r and "pointer-events: none" in r for r in rules)


def test_the_preview_card_hides_on_escape_blur_scroll_and_project_switch():
    assert "e.key === 'Escape'" in HISTORY
    assert "list.addEventListener('focusout'" in HISTORY
    assert "list.addEventListener('scroll'" in HISTORY
    assert "list.addEventListener('mouseleave'" in HISTORY
    switch = HISTORY.split("if (ui.project !== project.name) {")[1].split("render();")[0]
    assert "hideFlyout();" in switch
    tick = HISTORY.split("function tick()")[1].split("function ")[0]
    assert "hideFlyout();" in tick


def test_the_preview_fetch_is_debounced_and_cached():
    assert "PREVIEW_DEBOUNCE_MS" in HISTORY
    assert "ui.previews[row.key]" in HISTORY
    assert "loadPreview(" in HISTORY.split("function showFlyout")[1].split("function ")[0]


def test_chips_live_on_the_row_and_appear_on_hover_or_focus():
    assert "rowActions(row).forEach((a) => bar.appendChild(actionButton(row, a)));" in HISTORY
    block = _history_css()
    assert ".ah-item:hover .ah-actions" in block
    assert ".ah-item:focus-within .ah-actions" in block
    actions = block.split(".ah-actions {")[1].split("}")[0]
    assert "position: absolute" in actions
    assert "visibility: hidden" in actions


def test_a_resume_failure_shows_as_a_note_under_the_row_meta():
    row = HISTORY.split("function buildRow(")[1].split("function ")[0]
    assert "el('span', 'ah-row-note', ui.notice[row.key])" in row
    sig = HISTORY.split("const sig = JSON.stringify([")[1].split("if (sig === ui.sig")[0]
    assert "ui.notice[r.key]" in sig


def test_new_motion_respects_reduced_motion():
    block = _history_css()
    reduced = block.split("@media (prefers-reduced-motion: reduce)")[1]
    assert ".ah-flyout" in reduced and ".ah-actions" in reduced


def test_history_list_has_a_valid_list_structure_and_named_rows():
    assert 'id="ca-hist-list" class="ah-list"></div>' in CODE  # no role on the container
    assert "section.setAttribute('role', 'list');" in HISTORY
    assert "label.id = 'ah-group-label-' + g.key;" in HISTORY
    assert "section.setAttribute('aria-labelledby', label.id);" in HISTORY
    row = HISTORY.split("function buildRow(")[1].split("function ")[0]
    assert "item.setAttribute('role', 'listitem');" in row
    assert "head.setAttribute('role', 'button');" in row
    assert "'aria-label'," in row


def test_row_button_semantics_only_when_a_primary_action_exists():
    row = HISTORY.split("function buildRow(")[1].split("function ")[0]
    gated = row.split("if (primary) {")[1].split("\n    }\n")[0]
    for part in ("head.tabIndex = 0;", "head.setAttribute('role', 'button');", "'aria-label',"):
        assert part in gated
        assert part not in row.replace(gated, "")


def test_current_terminal_is_conveyed_by_aria_current_not_the_row_label():
    assert "current terminal" not in HISTORY
    assert "head.setAttribute('aria-current', 'true')" in HISTORY
    assert "head.removeAttribute('aria-current')" in HISTORY


def test_left_view_tabs_expose_which_pane_is_active():
    assert 'id="ca-viewtab-scm" aria-pressed="true"' in CODE
    for name in ("explorer", "history"):
        assert f'id="ca-viewtab-{name}" aria-pressed="false"' in CODE
    assert "tab?.setAttribute('aria-pressed', String(name === view));" in CODE


def test_resume_failure_note_does_not_guess_the_cause():
    assert "'Could not resume this session.'" in HISTORY
    assert "may have been deleted" not in HISTORY


def test_the_preview_card_never_paints_while_the_panel_is_hidden():
    for fn in ("function showFlyout", "function paintFlyout"):
        body = HISTORY.split(fn)[1].split("function ")[0]
        assert "if (!panelVisible()) {" in body


def test_terminal_tabs_use_the_history_state_dot():
    assert "window.agentHistory.applyTabState(tab, sess, Date.now());" in TERM
    assert "updateTabDots();" in HISTORY
    assert ".gtp-tab .gtp-tab-icon {" in CSS


def test_tab_label_shows_its_full_name_on_hover():
    assert "label.title = sess.label;" in TERM
    assert "labelEl.title = sess.label;" in TERM


def test_whole_row_activates_primary_action_and_marks_active_terminal():
    bind = HISTORY.split("function bindList()")[1].split("\n  }\n")[0]
    assert "e.target.closest('button, a, input')" in bind
    assert "e.key !== 'Enter' && e.key !== ' '" in bind
    assert "activateRow(" in bind
    assert "primaryAction(row, rowViewing(row))" in HISTORY
    assert "'aria-current'" in HISTORY
    assert "rowActive(r)," in HISTORY
    css = _history_css()
    assert ".ah-item.ah-active::before" in css


def test_a_session_open_elsewhere_is_taken_over_never_duplicated():
    assert "allow_duplicate" not in TERM and "allowDuplicate" not in TERM
    assert "allowDuplicate" not in HISTORY and "Open anyway" not in HISTORY
    assert "/api/generic-agent/takeover" in HISTORY
    assert "Close and open here" in HISTORY
    assert "failure.where" in TERM
