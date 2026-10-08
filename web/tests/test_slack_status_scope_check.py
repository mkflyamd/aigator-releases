"""Regression test: slack_token_status() must not report "configured": True
for a token that passes auth.test but lacks a scope SLACK_SCOPES requires
(e.g. users:read, needed for the @mention directory lookup).

Root cause: auth.test only proves a token is valid/not revoked — it does not
validate scopes. A refresh_token keeps minting access tokens carrying
whatever scopes were granted at the ORIGINAL OAuth consent, so if
SLACK_SCOPES gains scopes later, an existing user's token never picks them
up until they explicitly reconnect. Before this fix, such a token showed as
permanently "connected" in the UI while users.list (directory warm-up) failed
silently forever, leaving the @mention dropdown stuck on "warming" with no
results and no surfaced error.
"""

import asyncio
import json
import pathlib
import sys
from unittest.mock import patch

import pytest


APP_JS = (pathlib.Path(__file__).parent.parent / "static" / "app.js").read_text(
    encoding="utf-8"
)
THIRD_PANE_JS = (
    pathlib.Path(__file__).parent.parent / "static" / "third-pane.js"
).read_text(encoding="utf-8")


def _fresh_slack_module():
    for key in list(sys.modules):
        if key in ("routes.slack", "routes"):
            del sys.modules[key]
    with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), patch(
        "skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}
    ):
        import routes.slack as slack_mod
    return slack_mod


class TestMissingScopeDetection:
    """Unit tests for the new _missing_slack_scopes helper."""

    def test_no_missing_scopes_when_all_granted(self):
        slack_mod = _fresh_slack_module()

        assert (
            slack_mod._missing_slack_scopes("users:read,chat:write,channels:read")
            == []
        )

    def test_missing_scope_detected(self):
        slack_mod = _fresh_slack_module()

        missing = slack_mod._missing_slack_scopes("chat:write,channels:read")
        assert "users:read" in missing

    def test_empty_granted_scope_is_treated_as_unknown_not_missing(self):
        """An empty granted_scope must NOT be read as "everything is missing":
        a token-refresh response may legitimately omit `scope` to mean
        "unchanged from the original grant" (standard OAuth 2.0 semantics), so
        treating a data gap here as proof of a broken connection would create
        false "disconnected" reports for perfectly healthy tokens."""
        slack_mod = _fresh_slack_module()

        assert slack_mod._missing_slack_scopes("") == []

    def test_only_checks_scopes_the_directory_feature_needs(self):
        """Must not be diffed against the full SLACK_SCOPES list: that list
        also requests scopes this OAuth app isn't actually approved to grant
        (the search:read family — see the comment in mcp_client.py and the
        graceful missing_scope handling in _slack_search_messages). Diffing
        against all of it would report a fully-working connection as
        scope-deficient forever."""
        slack_mod = _fresh_slack_module()
        from skills.slack.mcp_client import SLACK_SCOPES

        assert slack_mod._missing_slack_scopes(SLACK_SCOPES) == []
        # A grant that only ever had the non-search scopes (i.e. never
        # included search:read.*, which this app can't get approved anyway)
        # must still be considered fully-scoped for our purposes.
        granted_without_search = ",".join(
            s
            for s in SLACK_SCOPES.split(",")
            if s.strip() and not s.strip().startswith("search:read")
        )
        assert slack_mod._missing_slack_scopes(granted_without_search) == []


class TestDirectoryFailureReporting:
    def test_live_lookup_passes_team_id_and_surfaces_restriction(self):
        slack_mod = _fresh_slack_module()
        slack_mod._USER_CACHE.clear()
        calls = []

        def fake_api(endpoint, params=None, method="GET"):
            calls.append((endpoint, params or {}))
            return {"ok": False, "error": "team_access_not_granted"}

        with patch(
            "skills.slack.mcp_client._load_token",
            return_value={"team_id": "T1", "team": "AMD"},
        ), patch.object(
            slack_mod, "_warm_workspace_directory", return_value=None
        ), patch.object(
            slack_mod, "_slack_web_api", side_effect=fake_api
        ):
            result = asyncio.run(slack_mod.slack_user_lookup("alice"))

        users_list_calls = [params for endpoint, params in calls if endpoint == "users.list"]
        assert users_list_calls == [{"limit": 200, "team_id": "T1"}]
        assert result["users"] == []
        assert result["error"] == "team_access_not_granted"
        assert result["directory_status"] == "restricted"
        assert "restricted" in result["hint"].lower()

    def test_transient_directory_failure_is_not_called_admin_restricted(self):
        slack_mod = _fresh_slack_module()
        result = slack_mod._directory_error_response("ratelimited")

        assert result["users"] == []
        assert result["error"] == "ratelimited"
        assert result["directory_status"] == "unavailable"
        assert "temporarily unavailable" in result["hint"].lower()


class TestDirectoryHintRendering:
    def test_hint_is_part_of_atomic_render_state(self):
        assert "slackDirectoryStatus" in APP_JS
        assert "slackDirectoryHint" in APP_JS
        assert "showSlackDirectoryHint" in APP_JS
        assert "showSlackEmptyState" in APP_JS
        assert "slackLookupComplete" in APP_JS
        assert "hint.dataset.directoryStatus" in APP_JS
        assert "frag.appendChild(hint)" in APP_JS
        assert "addAction('Reconnect Slack'" in APP_JS
        assert "'Open Slack channel'" in APP_JS
        assert "'Open another Slack channel'" in APP_JS
        assert "addAction('Retry'" in APP_JS
        assert "slackSigninBtn.click()" in APP_JS
        assert "No Slack people found in the workspace directory" in APP_JS
        assert "the current Slack channel" in APP_JS
        assert "No matching Slack members in members of" not in APP_JS
        assert "Open Slack, select another channel where this person participates" in APP_JS
        assert "openSlackBtn.textContent = 'Open another Slack channel'" in APP_JS

    def test_lookup_callback_does_not_append_hint_before_render(self):
        lookup_start = APP_JS.index(".then((lookup) =>")
        lookup_end = APP_JS.index(".catch((err) =>", lookup_start)
        lookup_callback = APP_JS[lookup_start:lookup_end]

        assert "slackDirectoryHint = lookup.hint" in lookup_callback
        assert "_mentionDropdown.appendChild(hint)" not in lookup_callback

    def test_native_slack_channel_is_used_when_no_channel_chip_is_selected(self):
        assert "_nativeSlack._currentCtx || _nativeSlack._lastChannelCtx" in APP_JS
        assert "channel_id: nativeCtx.channel" in APP_JS
        assert "_lastChannelCtx: null" in THIRD_PANE_JS
        assert "this._lastChannelCtx = ctx" in THIRD_PANE_JS


class TestSlackTokenStatusEndpoint:
    """/api/auth/slack/status must reflect scope-deficient tokens as
    disconnected instead of "configured": True."""

    def _client(self, slack_mod):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(slack_mod.router)
        return TestClient(app)

    def test_status_reports_disconnected_when_scope_missing(self):
        slack_mod = _fresh_slack_module()

        base = {
            "configured": True,
            "team": "AMD",
            "team_id": "T1",
            "user": "U1",
            "scope": "chat:write,channels:read",
            "expires_at": 9999999999.0,
        }

        def fake_web_api(endpoint, params=None):
            if endpoint == "auth.test":
                return {"ok": True}
            raise AssertionError(
                f"users.list/other Slack API calls must not happen once scope "
                f"validation fails, but got a call to {endpoint!r}"
            )

        with patch("skills.slack.mcp_client.get_slack_auth_status", return_value=base), patch(
            "skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"
        ), patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
            client = self._client(slack_mod)
            resp = client.get("/api/auth/slack/status")

        data = resp.json()
        assert data["configured"] is False, (
            "A token missing a required scope (users:read) must not be "
            f"reported as configured/connected. Got: {data}"
        )
        assert data.get("error") == "missing_scope"
        assert "users:read" in data.get("missing_scopes", [])

    def test_status_reports_connected_when_all_scopes_granted(self):
        slack_mod = _fresh_slack_module()

        base = {
            "configured": True,
            "team": "AMD",
            "team_id": "T1",
            "user": "U1",
            "scope": "users:read,chat:write,channels:read",
            "expires_at": 9999999999.0,
        }

        def fake_web_api(endpoint, params=None):
            if endpoint == "auth.test":
                return {"ok": True}
            # Directory/channel warm-up threads may call users.list /
            # conversations.list off-thread; keep them harmless no-ops.
            return {"ok": True, "members": [], "channels": []}

        with patch("skills.slack.mcp_client.get_slack_auth_status", return_value=base), patch(
            "skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"
        ), patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
            client = self._client(slack_mod)
            resp = client.get("/api/auth/slack/status")

        data = resp.json()
        assert data["configured"] is True, (
            f"A token with every required scope granted must report connected. Got: {data}"
        )
        assert "error" not in data or data.get("error") is None

    def test_status_still_reports_auth_failure_before_scope_check(self):
        """A genuinely invalid/revoked token must still fail via auth.test,
        not be reclassified as a scope problem."""
        slack_mod = _fresh_slack_module()
        base = {
            "configured": True,
            "team": "AMD",
            "team_id": "T1",
            "user": "U1",
            "scope": "",
            "expires_at": 9999999999.0,
        }

        def fake_web_api(endpoint, params=None):
            if endpoint == "auth.test":
                return {"ok": False, "error": "invalid_auth"}
            raise AssertionError("must not proceed past a failed auth.test")

        with patch("skills.slack.mcp_client.get_slack_auth_status", return_value=base), patch(
            "skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"
        ), patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
            client = self._client(slack_mod)
            resp = client.get("/api/auth/slack/status")

        data = resp.json()
        assert data["configured"] is False
        assert data.get("error") == "invalid_auth"


class TestDirectoryWarmupLogsFailure:
    """_warm_workspace_directory must not silently swallow a users.list
    error — it must be observable (printed) so a stuck "warming" state can
    be diagnosed without guessing."""

    def test_users_list_failure_is_logged(self, capsys):
        slack_mod = _fresh_slack_module()

        def fake_web_api(endpoint, params=None):
            assert endpoint == "users.list"
            return {"ok": False, "error": "missing_scope"}

        with patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
            slack_mod._DIRECTORY_CACHE.update(
                {
                    "team_id": "",
                    "members": {},
                    "loading": False,
                    "complete": False,
                    "loaded_at": 0.0,
                }
            )
            slack_mod._warm_workspace_directory("T1")
            # The warm-up spawns a daemon thread; give it a moment to run.
            import time as _t

            for _ in range(50):
                with slack_mod._DIRECTORY_CACHE_LOCK:
                    if not slack_mod._DIRECTORY_CACHE["loading"]:
                        break
                _t.sleep(0.02)

        out = capsys.readouterr().out
        assert "missing_scope" in out, (
            "A failed users.list call during directory warm-up must have its "
            f"Slack error reason printed for diagnosis. Captured stdout: {out!r}"
        )


class TestRefreshTokenPreservesScope:
    """_refresh_token() must not blank a token's stored scope when Slack's
    refresh response omits the `scope` field — standard OAuth 2.0 semantics
    allow that omission to mean "unchanged from the prior grant". Without
    this, the new scope check above would eventually see an empty granted
    scope on any token that ever refreshes this way... except an empty scope
    is now treated as "unknown" defensively, so the real risk this guards
    against is a PERMANENT, silent loss of the true granted-scope value in
    the persisted token file."""

    def _fresh_mcp_client(self):
        for key in list(sys.modules):
            if key == "skills.slack.mcp_client":
                del sys.modules[key]
        import skills.slack.mcp_client as mcp_client

        return mcp_client

    def test_scope_omitted_on_refresh_falls_back_to_previous_scope(self):
        mcp_client = self._fresh_mcp_client()

        class _FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        refresh_response = json.dumps(
            {
                "ok": True,
                "access_token": "xoxp-new",
                "team": {"name": "AMD", "id": "T1"},
                "authed_user": {"id": "U1", "name": "Alice"},
                # `scope` deliberately omitted, as Slack/OAuth 2.0 may do.
            }
        ).encode()

        saved = {}
        with patch.object(
            mcp_client, "_load_token", return_value={"scope": "users:read,chat:write"}
        ), patch.object(
            mcp_client, "_save_token", side_effect=lambda d: saved.update(d)
        ), patch.object(
            mcp_client.urllib.request,
            "urlopen",
            return_value=_FakeResponse(refresh_response),
        ):
            result = mcp_client._refresh_token("refresh-abc")

        assert result == "xoxp-new"
        assert saved.get("scope") == "users:read,chat:write", (
            "A refresh response omitting `scope` must preserve the "
            f"previously stored scope, not blank it. Saved token: {saved!r}"
        )

    def test_scope_present_on_refresh_overwrites_previous_scope(self):
        mcp_client = self._fresh_mcp_client()

        class _FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        refresh_response = json.dumps(
            {
                "ok": True,
                "access_token": "xoxp-new",
                "team": {"name": "AMD", "id": "T1"},
                "authed_user": {"id": "U1", "name": "Alice"},
                "scope": "users:read,chat:write,channels:read",
            }
        ).encode()

        saved = {}
        with patch.object(
            mcp_client, "_load_token", return_value={"scope": "users:read"}
        ), patch.object(
            mcp_client, "_save_token", side_effect=lambda d: saved.update(d)
        ), patch.object(
            mcp_client.urllib.request,
            "urlopen",
            return_value=_FakeResponse(refresh_response),
        ):
            mcp_client._refresh_token("refresh-abc")

        assert saved.get("scope") == "users:read,chat:write,channels:read"

    def test_refresh_prefers_nested_user_token_and_metadata(self):
        """A user refresh must not be replaced by the top-level bot token."""
        mcp_client = self._fresh_mcp_client()

        class _FakeResponse:
            def read(self):
                return json.dumps(
                    {
                        "ok": True,
                        "access_token": "xoxb-bot-token",
                        "refresh_token": "xoxe-bot-refresh",
                        "expires_in": 3600,
                        "team": {"name": "AMD", "id": "T1"},
                        "authed_user": {
                            "id": "U1",
                            "name": "Alice",
                            "access_token": "xoxp-user-token",
                            "refresh_token": "xoxe-user-refresh",
                            "expires_in": 7200,
                            "scope": "users:read,channels:history",
                        },
                    }
                ).encode()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        saved = {}
        with patch.object(
            mcp_client,
            "_load_token",
            return_value={"scope": "channels:history", "team_id": "T1"},
        ), patch.object(
            mcp_client, "_save_token", side_effect=lambda d: saved.update(d)
        ), patch.object(
            mcp_client.urllib.request, "urlopen", return_value=_FakeResponse()
        ):
            result = mcp_client._refresh_token("old-user-refresh")

        assert result == "xoxp-user-token"
        assert saved["access_token"] == "xoxp-user-token"
        assert saved["refresh_token"] == "xoxe-user-refresh"
        assert saved["scope"] == "users:read,channels:history"
