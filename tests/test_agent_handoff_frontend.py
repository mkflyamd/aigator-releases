"""Source-string wiring checks for the handoff UI (the DOM paths need a real browser)."""

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
TERM = (STATIC / "tp-generic-agent-terminal.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_scripts_load_before_terminal_module():
    limit = INDEX.index("agent-limit-detect.js")
    handoff = INDEX.index("agent-handoff.js")
    terminal = INDEX.index("tp-generic-agent-terminal.js")
    assert limit < terminal and handoff < terminal


def test_tab_kebab_menu_lists_hand_off_then_open_then_restart():
    assert "kebab.className = 'gtp-tab-restart gtp-tab-kebab';" in TERM
    assert "e.target === x || e.target === kebab" in TERM
    assert "gtp-tab-handoff" not in TERM and "gtp-tab-popout" not in TERM
    menu = TERM[TERM.index("function _genAgentOpenTabMenu"):TERM.index("function _genAgentForceRestartTab")]
    order = [menu.index(label) for label in ("Hand off to another agent", "Open in its own window", "Restart session")]
    assert order == sorted(order)
    assert "agentHandoff.openDialog({ tabId, sess })" in menu
    assert "_genAgentForceRestartTab(tabId, id, null)" in menu


def test_start_sends_handoff_id_and_delivers_prompt():
    assert "handoff_id: opts.handoffId" in TERM
    assert TERM.count("handoff_id: opts.handoffId") == 2  # _ocFetch and fetch branches
    assert "data.handoff_prompt" in TERM
    assert "agentHandoff.deliver(sess, data.handoff_prompt)" in TERM
    assert "sess._handedOffAt = Date.now()" in TERM


def test_project_agent_is_not_overwritten_by_a_handoff_tab():
    assert "const stateAgent = opts.keepStateAgent ? state.agent : agent;" in TERM
    assert "state.agent = stateAgent;" in TERM
    assert "current.agent !== stateAgent" in TERM
    assert "current.agent === stateAgent" in TERM


def test_restart_and_close_use_the_session_agent():
    assert "agent: sess.agent || state.agent," in TERM
    assert "keepStateAgent: sess.agent !== state.agent" in TERM


def test_plus_opens_the_agent_menu_and_keeps_the_project_agent():
    assert "newBtn.onclick = () => _genAgentOpenNewMenu(tabId, newBtn);" in TERM
    assert "gtp-tab-new-menu" not in TERM
    assert "_genAgentStart(tabId, agent, state.projectId, state.repoPath, {" in TERM
    assert "keepStateAgent: true," in TERM
    assert "_genAgentNewSession(tabId, agent)" in TERM


def test_new_tab_menu_lists_every_launchable_agent():
    assert (
        "const _GEN_NEW_TAB_AGENTS = ['claude', 'codex', 'crush', 'opencode-bare'];"
        in TERM
    )
    assert "item.appendChild(_genAgentTabIcon(agent));" in TERM
    assert "items.find((item) => item.dataset.agent === current) || items[0]" in TERM


def test_each_tab_shows_its_own_agent_icon():
    assert "tab.appendChild(_genAgentTabIcon(sess.agent || state.agent));" in TERM
    icon_map = TERM.split("const _GEN_AGENT_ICON_HTML")[1].split("function _genAgentTabIcon")[0]
    for key in ("claude:", "codex:", "crush:", "'opencode-bare':", "terminal:"):
        assert key in icon_map
    assert "/static/icons/agents/crush.png" in TERM
    assert (STATIC / "icons" / "agents" / "crush.png").is_file()


def test_every_extra_agent_has_a_label_and_an_icon():
    import re
    import sys

    sys.path.insert(0, str(STATIC.parent))
    import generic_agent

    label_map = TERM.split("const _GEN_EXTRA_AGENT_LABELS = {")[1].split("\n};")[0]
    labels = dict(re.findall(r"^  '?([\w-]+)'?: '([^']+)',$", label_map, re.M))
    for agent, (label, _, _) in generic_agent.EXTRA_AGENTS.items():
        assert labels.get(agent) == label, agent
    pngs = set(re.findall(r"'([\w-]+)'", re.search(r"_GEN_AGENT_PNG_ICONS = \[(.*?)\];", TERM, re.S).group(1)))
    for agent in pngs:
        assert (STATIC / "icons" / "agents" / f"{agent}.png").is_file(), agent
    assert (STATIC / "icons" / "agents" / "qoder.png").is_file()
    no_png = set(generic_agent.EXTRA_AGENTS) - pngs
    assert no_png == {"pi", "omp", "aider", "qoder-cn"}


def test_menu_lists_installed_extras_below_the_core_agents():
    assert "addItem(agent, divider)" in TERM
    assert "addItem('terminal');" in TERM
    assert "installed[a] === true" in TERM


def test_output_feeds_limit_detector_and_activity_clock():
    assert "sess._lastOutputAt = Date.now();" in TERM
    assert "agentLimitDetect.feed(sess, msg.data, (s) => agentHandoff.offerOnLimit(s))" in TERM


HANDOFF = (STATIC / "agent-handoff.js").read_text(encoding="utf-8")


def test_output_branch_tracks_bracketed_paste_mode():
    assert "agentHandoff.trackBracketedPaste(" in TERM
    assert "sess._bracketedPaste = paste.enabled;" in TERM
    assert "sess._bracketedPasteTail = paste.tail;" in TERM
    # tracked in the same branch that stamps the output clock
    assert TERM.index("sess._lastOutputAt = Date.now();") < TERM.index("sess._bracketedPaste = paste.enabled;")
    assert "const BRACKETED_ON = ESC + '[?2004h';" in HANDOFF
    assert "const BRACKETED_OFF = ESC + '[?2004l';" in HANDOFF


def test_readiness_requires_bracketed_paste():
    assert "if (!s.bracketedPaste) return false;" in HANDOFF
    # the probe deliver() uses builds the session-shaped object from the flag
    assert "bracketedPaste: !!sess._bracketedPaste," in HANDOFF
    assert "draftPrompt(sess, prompt, sessionProbe)" in HANDOFF


def test_readiness_clock_ignores_the_working_indicator_quiet_window():
    # output right after a connect or resize must still count, or a fast-painting target never looks ready
    assert "lastOutputAt: sess._lastRawOutputAt," in HANDOFF
    assert TERM.index("sess._lastRawOutputAt = Date.now();") < TERM.index("if (Date.now() >= (sess._quietUntil || 0)) {")


def test_paste_text_is_stripped_of_terminal_controls():
    assert r"\\u0000-\\u0008\\u000b-\\u001f\\u007f-\\u009f" in HANDOFF
    assert "replace(CONTROL_CHARS, '')" in HANDOFF


def test_continue_checks_for_a_start_in_flight_before_closing():
    assert "function _genAgentStartInFlight(tabId)" in TERM
    assert "state && state._starting" in TERM
    assert "_genAgentStartInFlight(tabId)" in HANDOFF
    assert "go.addEventListener('click', begin);" in HANDOFF
    begin = HANDOFF.index("function begin()")
    block = HANDOFF[begin : HANDOFF.index("function select(", begin)]
    assert block.index("startInFlight(tabId)") < block.index("close();")
    assert "Another agent is still starting. Try again in a moment." in block


def test_malformed_prepare_response_is_caught_with_the_dialog_render():
    inner = HANDOFF[HANDOFF.index("async function openDialog") :]
    assert inner.index("prep = body;") < inner.index("renderDialog(prep") < inner.index("} catch (_) {")
    assert inner.index("} finally {") > inner.index("renderDialog(prep")
    assert "dialogBusy = false;" in inner


def test_reconnect_shows_a_transient_banner_not_text_in_the_terminal():
    assert "[disconnected" not in TERM
    assert "_genAgentShowReconnecting(sess, attempt);" in TERM
    opened = TERM.index("sess.ws.onopen = () => {")
    assert TERM.index("_genAgentClearReconnecting(sess);", opened) < TERM.index("_ocFit(sess", opened)
    assert ".gtp-reconnect-banner" in (STATIC / "style.css").read_text(encoding="utf-8")


def test_dialog_is_a_searchable_listbox_with_no_hide_checkbox():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".agent-handoff-targets {" in css
    assert "overflow-y: auto" in css
    assert "setAttribute('role', 'listbox')" in HANDOFF
    assert "search.setAttribute('role', 'combobox')" in HANDOFF
    assert "(current agent)" not in HANDOFF
    assert "type = 'checkbox'" not in HANDOFF
    assert "type = 'radio'" not in HANDOFF


def test_dialog_shows_a_one_line_last_message_ahead_of_the_picker():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "oneLine(prep.last_user_message)" in HANDOFF
    assert "last.title = " in HANDOFF
    assert HANDOFF.index("agent-handoff-carry") < HANDOFF.index("'Continue in'")
    assert ".agent-handoff-last-text {" in css and "text-overflow: ellipsis" in css


def test_menu_badges_installed_agents_that_run_outside_the_gateway():
    assert "routed = body.gateway_routed || {};" in TERM
    assert "routed[item.dataset.agent] !== false" in TERM
    assert "badge.textContent = 'Unmanaged';" in TERM
    assert ".gtp-new-menu-badge" in (STATIC / "style.css").read_text(encoding="utf-8")
