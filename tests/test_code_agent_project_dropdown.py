"""Regression checks for the Code Projects menu, chip, empty state and left-view wiring."""

from pathlib import Path


ROOT = Path(__file__).parent.parent
STYLE = (ROOT / "web" / "static" / "style.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "tp-code-agent.js").read_text(encoding="utf-8")


def test_project_dropdown_is_viewport_bounded_and_scrollable():
    rule = STYLE.split(".ca-project-dropdown {", 1)[1].split("}", 1)[0]
    assert "max-height: calc(100vh - 16px)" in rule
    assert "overflow-y: auto" in rule
    assert "scrollbar-width: thin" in STYLE
    assert ".ca-project-dropdown::-webkit-scrollbar" in STYLE


def test_project_dropdown_flips_above_chip_when_below_space_is_smaller():
    dropdown = SCRIPT.split("function _caShowSessionDropdown()", 1)[1].split(
        "function _caSetActiveProject", 1
    )[0]
    assert "const spaceBelow" in dropdown
    assert "const spaceAbove" in dropdown
    assert "const openBelow = spaceBelow >= spaceAbove" in dropdown
    assert "dropdown.style.maxHeight = availableHeight" in dropdown


def _between(start, end):
    return SCRIPT.split(start, 1)[1].split(end, 1)[0]


def test_project_chip_shows_the_project_branch_and_the_attention_count():
    chip = _between("function _caRenderProjectSwitcher", "// ── Topbar population")
    assert "_CA_AGENT_LABELS" not in SCRIPT
    assert "'● ' + proj.name + (branch ? ' · ' + branch : '') + ' ▾'" in chip
    assert "attn.id = 'ca-topbar-attn'" in chip
    assert "agentHistory.updateDot()" in chip


def test_projects_menu_lists_recent_searches_and_opens_a_folder():
    menu = _between("function _caShowSessionDropdown()", "function _caSetActiveProject")
    assert "CODING AGENT" not in menu
    assert "Add app" not in menu
    assert "'Open folder…'" in menu
    assert "codePickerHelpers" in menu
    assert "helpers.sortProjects" in menu and "helpers.filterProjects" in menu
    assert "'Recent'" in menu and "'All projects'" in menu
    assert "setAttribute('role', 'menu')" in menu
    assert "setAttribute('role', 'menuitem')" in menu


def test_removing_a_project_confirms_inline_and_never_offers_the_open_one():
    menu = _between("function _caShowSessionDropdown()", "function _caSetActiveProject")
    assert "Remove from Gator? Your files are not touched." in menu
    current = menu.split("if (isCurrent) {", 1)[1].split("} else {", 1)[0]
    assert "ca-project-remove" not in current
    remove = _between("async function _caRemoveProject", "const _CA_RECENT_COUNT")
    assert "method: 'DELETE'" in remove
    assert "_caFetchWithCsrfRetry" in remove


def test_agent_chosen_in_the_plus_menu_is_remembered_as_the_project_default():
    remember = _between("async function _caRememberProjectAgent", "function _caOpenProject")
    assert "'/api/code_agent/projects/agent'" in remember
    assert "method: 'PUT'" in remember
    assert "_caFetchWithCsrfRetry" in remember


def test_left_view_defaults_to_history_and_persists_per_project():
    assert "let _caLeftView = 'history';" in SCRIPT
    assert "const _CA_LEFT_VIEWS = ['history', 'scm', 'explorer'];" in SCRIPT
    assert "'gator.codeagent.leftview.'" in SCRIPT
    assert "_caSetLeftView(_caStoredLeftView(name))" in SCRIPT


def test_empty_state_asks_to_open_a_project_folder():
    empty = _between("function _caEmptyState()", "function _caNoProjectSelectedState")
    assert "Open a project folder" in empty
    assert "Connect your first app" not in empty


def test_picker_helpers_load_before_the_code_agent_script():
    index = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert index.index("code-picker-helpers.js") < index.index("tp-code-agent.js")
    assert index.index("code-branch-helpers.js") < index.index("tp-code-agent.js")


def test_changes_header_branch_button_opens_the_branch_and_worktree_menu():
    app = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "'_caShowBranchMenu'" in app
    assert "async function _caShowBranchMenu" in SCRIPT
    menu = _between("async function _caShowBranchMenu", "function _caSetActiveProject")
    assert "git/checkout" in menu and "git/worktree" in menu
    assert "confirm_dirty" in menu
    assert "innerHTML" not in menu
    assert "setAttribute('role', 'menuitem')" in menu


def test_git_views_are_keyed_and_fetched_per_selected_folder():
    assert "_caCacheKey(_caActiveProject)" in SCRIPT
    assert "_caApiUrl('git/status', _project)" in SCRIPT
    assert "worktree: _caSelectedWorktree(_caActiveProject)" in SCRIPT


def test_tab_strip_supports_drag_and_keyboard_reorder():
    term = (ROOT / "web" / "static" / "tp-generic-agent-terminal.js").read_text(encoding="utf-8")
    assert "codePickerHelpers.moveTab" in term
    assert "codePickerHelpers.stepTab" in term
    assert "'Move left'" in term and "'Move right'" in term
    assert "e.altKey" in term
    assert ".gtp-drop-before" in STYLE and ".gtp-drop-after" in STYLE


def test_terminals_start_in_the_worktree_selected_when_the_user_clicks():
    term = (ROOT / "web" / "static" / "tp-generic-agent-terminal.js").read_text(encoding="utf-8")
    assert "function _genAgentFolder" in term
    assert "_caActiveFolder(state.projectId)" in term
    prompt = term.split("function _genAgentShowStartPrompt", 1)[1].split("\nfunction ", 1)[0]
    assert "_caActiveFolder(projectId)" in prompt
    assert "setTimeout(() => _genAgentStart(tabId, agent, projectId, folder), 0)" in prompt


def test_loading_projects_drops_an_active_project_that_no_longer_exists():
    load = _between("function _caLoadProjects()", "function _caAddLocalProject")
    assert "_caProjects.some((p) => p.name === _caActiveProject)" in load
