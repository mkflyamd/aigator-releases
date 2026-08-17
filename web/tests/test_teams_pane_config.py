"""Regression tests for native Teams pane config + draft-approval routing."""

import pathlib

CONFIG_SRC = (pathlib.Path(__file__).parent.parent / "config.py").read_text(
    encoding="utf-8"
)
EMAIL_ROUTE_SRC = (
    pathlib.Path(__file__).parent.parent / "routes" / "email.py"
).read_text(encoding="utf-8")
TEAMS_TOOLS_SRC = (
    pathlib.Path(__file__).parent.parent / "skills" / "teams" / "tools.py"
).read_text(encoding="utf-8")
APP_JS_SRC = (pathlib.Path(__file__).parent.parent / "static" / "app.js").read_text(
    encoding="utf-8"
)


class TestTeamsPaneModeConfigKey:
    def test_teams_pane_mode_is_allowed_key(self):
        assert '"teams_pane_mode"' in CONFIG_SRC

    def test_teams_pane_mode_near_slack_pane_mode(self):
        slack_idx = CONFIG_SRC.find('"slack_pane_mode"')
        teams_idx = CONFIG_SRC.find('"teams_pane_mode"')
        assert slack_idx != -1 and teams_idx != -1
        assert abs(teams_idx - slack_idx) < 500, (
            "teams_pane_mode and slack_pane_mode should be near each other in config.py"
        )


class TestTeamsDraftApproval:
    def test_teams_message_dtype_in_approval_route(self):
        assert 'dtype == "teams-message"' in EMAIL_ROUTE_SRC, (
            "email.py approve_draft must handle teams-message dtype"
        )

    def test_teams_approval_calls_send_handler_directly(self):
        # The approval must call tp_teams_send_message() in-process, NOT self-POST
        # to a hardcoded port (the old self-HTTP call broke on any other port).
        assert "tp_teams_send_message" in EMAIL_ROUTE_SRC, (
            "teams-message approval must call tp_teams_send_message() directly"
        )
        # No self-HTTP POST to a localhost teams send endpoint (comments allowed).
        assert (
            'post(\n                "http://localhost' not in EMAIL_ROUTE_SRC
            and '"http://localhost:8000/api/teams/send-message"' not in EMAIL_ROUTE_SRC
        ), "teams-message approval must NOT self-POST to a hardcoded localhost port"

    def test_edited_message_applied_before_dtype_branch(self):
        edited_idx = EMAIL_ROUTE_SRC.find(
            'draft["params"]["message"] = body["edited_message"]'
        )
        dtype_idx = EMAIL_ROUTE_SRC.find('dtype = draft["type"]')
        assert edited_idx != -1, "edited_message override must exist in approve_draft"
        assert dtype_idx != -1
        assert edited_idx < dtype_idx, (
            "edited_message must be applied BEFORE the dtype branch so user edits "
            "reach the Teams send call"
        )

    def test_teams_open_compose_creates_draft(self):
        assert "create_draft" in TEAMS_TOOLS_SRC, (
            "_tool_teams_open_compose must call create_draft() so the approval card "
            "has a draft_id"
        )
        assert '"teams-message"' in TEAMS_TOOLS_SRC, (
            "draft type must be 'teams-message'"
        )

    def test_draft_id_included_in_pane_data(self):
        assert '"draft_id": draft_id' in TEAMS_TOOLS_SRC, (
            "draft_id must be included in paneData so the frontend approval card "
            "can POST to /api/drafts/{id}/approve"
        )


class TestTeamsNativeShellRouting:
    def test_teams_compose_shell_branch_in_app_js(self):
        assert "gatorShell.isShell" in APP_JS_SRC, (
            "app.js must check gatorShell.isShell to route teams-compose to "
            "approval card in native mode"
        )
        assert "_injectDraftApprovalCard('teams-message'" in APP_JS_SRC, (
            "app.js must call _injectDraftApprovalCard for teams-message in shell mode"
        )

    def test_teams_message_in_draft_approval_card_config(self):
        assert "'teams-message'" in APP_JS_SRC, (
            "_injectDraftApprovalCard config map must include 'teams-message'"
        )

    def test_approve_handler_keeps_pane_open_in_shell(self):
        assert "window.gatorShell.isShell" in APP_JS_SRC, (
            "approve handler must use window.gatorShell.isShell (not _nativeSlack) "
            "so Teams pane also stays open after approval"
        )

    def test_classic_teams_flow_unchanged(self):
        assert "_teamsReceiveComposeData" in APP_JS_SRC, (
            "classic Teams compose flow (_teamsReceiveComposeData) must still exist"
        )
        assert "openThirdPane('teams')" in APP_JS_SRC, (
            "classic mode must still call openThirdPane('teams')"
        )
