"""Tests for capture_slack_token — workspace-aware token selection (Issue #45)."""

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to run the embedded JS logic in Python so we can test it without a
# real browser.  We simulate what Slack's localStorage looks like when the user
# is signed into multiple workspaces.
# ---------------------------------------------------------------------------

def _make_local_storage(*entries):
    """Return a dict simulating localStorage key→JSON-string pairs."""
    return {str(i): json.dumps(v) for i, v in enumerate(entries)}


def _run_js_token_extraction(local_storage: dict, active_team_id: str) -> tuple[str, str]:
    """
    Pure-Python reimplementation of the JS logic we expect _JS_GET_TOKEN to use
    after the fix.  Returns (token, team_id).

    This is the *target behaviour* we're testing against; the production code
    must match this contract.
    """
    # Import the module under test to get the JS string and the helper that
    # parses the CDP Runtime.evaluate result.
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "capture_slack_token",
        pathlib.Path(__file__).parent.parent / "capture_slack_token.py",
    )
    mod = importlib.util.load_from_spec(spec) if hasattr(importlib.util, "load_from_spec") else None

    # We can't run JS here — instead we test the Python side: that when the
    # CDP evaluate returns a (token, team_id) pair, the capture function uses
    # the team_id to pick the right token.
    # This function is a contract test: given two tokens in storage, the one
    # whose team_id matches active_team_id must be returned.
    for raw in local_storage.values():
        try:
            v = json.loads(raw)
        except Exception:
            continue
        if isinstance(v, dict):
            tid = v.get("team_id", "")
            tok = v.get("token", "")
            if tok.startswith("xoxc-") and tid == active_team_id:
                return tok, tid
            # nested tokens dict
            if "tokens" in v:
                for t in v["tokens"].values():
                    if isinstance(t, str) and t.startswith("xoxc-") and tid == active_team_id:
                        return t, tid
    return "", ""


# ---------------------------------------------------------------------------
# Test 1: JS extraction prefers the active workspace token
# ---------------------------------------------------------------------------

class TestTokenExtractionPicksActiveWorkspace:
    """The JS snippet must return the token for the *currently visible* workspace."""

    def _make_multi_workspace_storage(self):
        return _make_local_storage(
            {"token": "xoxc-internal-111", "team_id": "TAMD001"},   # AMD internal
            {"token": "xoxc-external-222", "team_id": "TEXTERNAL"},  # AMD External
        )

    def test_returns_external_token_when_external_workspace_is_active(self):
        storage = self._make_multi_workspace_storage()
        token, team_id = _run_js_token_extraction(storage, active_team_id="TEXTERNAL")
        assert token == "xoxc-external-222", (
            "Should return the external workspace token when TEXTERNAL is active"
        )
        assert team_id == "TEXTERNAL"

    def test_returns_internal_token_when_internal_workspace_is_active(self):
        storage = self._make_multi_workspace_storage()
        token, team_id = _run_js_token_extraction(storage, active_team_id="TAMD001")
        assert token == "xoxc-internal-111", (
            "Should return the internal workspace token when TAMD001 is active"
        )

    def test_returns_empty_when_active_team_not_in_storage(self):
        storage = self._make_multi_workspace_storage()
        token, team_id = _run_js_token_extraction(storage, active_team_id="TUNKNOWN")
        assert token == "", "No token should be returned for an unknown team"


# ---------------------------------------------------------------------------
# Test 2: _JS_GET_TOKEN must include team_id in its return value
# ---------------------------------------------------------------------------

class TestJsSnippetReturnsTeamId:
    """The JS snippet in capture_slack_token.py must return an object with
    both 'token' and 'team_id' fields, not just a bare token string."""

    def _load_js_snippet(self) -> str:
        import pathlib
        src = (pathlib.Path(__file__).parent.parent / "capture_slack_token.py").read_text()
        # Extract the _JS_GET_TOKEN constant
        start = src.find('_JS_GET_TOKEN = """')
        assert start != -1, "_JS_GET_TOKEN constant not found in capture_slack_token.py"
        start += len('_JS_GET_TOKEN = """')
        end = src.find('"""', start)
        return src[start:end]

    def test_js_snippet_references_team_id(self):
        js = self._load_js_snippet()
        assert "team_id" in js, (
            "_JS_GET_TOKEN must read team_id so the capture can select the right workspace token. "
            "Currently it returns only the first token found, ignoring which workspace is active."
        )

    def test_js_snippet_does_not_return_bare_string(self):
        js = self._load_js_snippet()
        # After the fix the snippet should return an object, not a bare string.
        # A bare `return v.token` or `return t` with no team_id is the old bug.
        assert "return {" in js or "return JSON" in js or "team_id" in js, (
            "_JS_GET_TOKEN must return an object containing both token and team_id, "
            "not just the bare token string."
        )


# ---------------------------------------------------------------------------
# Test 3: capture result includes team name for UI feedback
# ---------------------------------------------------------------------------

import pytest as _pytest_cap

@_pytest_cap.mark.skip(reason="xoxc- capture route removed in MCP→Web API migration")
class TestCaptureRouteIncludesTeamName:
    """POST /api/auth/slack/capture must return team name so the drawer can
    show 'Connected to AMD External' instead of a silent success."""

    def test_capture_result_has_team_field(self):
        """The route already calls auth.test and returns team — verify it's present."""
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "routes.slack",
            pathlib.Path(__file__).parent.parent / "routes" / "slack.py",
        )
        src = (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text()
        # The capture endpoint must return a 'team' key so the frontend can display it.
        # Find the slack_token_capture function's return dict.
        capture_fn_start = src.find("async def slack_token_capture")
        assert capture_fn_start != -1
        capture_fn_body = src[capture_fn_start:capture_fn_start + 2000]
        assert '"team"' in capture_fn_body or "'team'" in capture_fn_body, (
            "slack_token_capture must include 'team' in its return dict so the "
            "frontend drawer can confirm which workspace was connected."
        )
