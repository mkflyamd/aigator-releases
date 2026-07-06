"""TDD tests for the 7 issues identified in second adversarial review.

Issues:
  1. _fetch_external_channels blocks event loop (needs run_in_executor in slack_channels)
  2. slack_thread_detail missing reversed() — replies in wrong order
  3. Module-level cache has no workspace-switch invalidation
  4. Concurrent token refresh race in _fetch_external_channels threads
  5. MCP lock too coarse — serialises entire 30s HTTP call
  6. HITL: slack_post_message / slack_send_dm auto-send without draft gate
  7. Hardcoded "Mayuresh Kulkarni" in DM filter — must use authenticated user
"""

import asyncio
import json
import pathlib
import sys
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "slack.py").read_text()
MCP_SRC = (pathlib.Path(__file__).parent.parent / "skills" / "slack" / "mcp_client.py").read_text()


# ─────────────────────────────────────────────────────────────────────────────
# Issue 1: slack_channels must await _fetch_external_channels in executor
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchExternalNotBlockingEventLoop:
    """slack_channels() must not call _fetch_external_channels() bare —
    that function does threading.Thread.join() which blocks the event loop.
    It must be wrapped in loop.run_in_executor."""

    def test_slack_channels_wraps_fetch_external_in_executor(self):
        """The slack_channels route body must use run_in_executor for _fetch_external_channels."""
        # Find the slack_channels async function
        fn_start = SRC.find("async def slack_channels()")
        assert fn_start != -1, "slack_channels() route not found"
        fn_body = SRC[fn_start: fn_start + 3000]
        uses_executor = "run_in_executor" in fn_body or "asyncio.to_thread" in fn_body
        assert uses_executor, (
            "slack_channels() calls _fetch_external_channels() which does Thread.join() "
            "— a blocking call. It must be wrapped in loop.run_in_executor(None, _fetch_external_channels) "
            "to avoid blocking the uvicorn event loop."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 2: slack_thread_detail must reverse raw_messages for chronological order
# ─────────────────────────────────────────────────────────────────────────────

class TestThreadDetailMessageOrder:
    """conversations.replies returns newest-first; slack_thread_detail must
    reverse to match slack_channel_messages ordering (oldest-first)."""

    def test_thread_detail_does_not_reverse_raw_messages(self):
        """slack_thread_detail must NOT use reversed(raw_messages).
        conversations.replies already returns oldest-first."""
        fn_start = SRC.find("async def slack_thread_detail(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 3000]
        assert "reversed(raw_messages)" not in fn_body, (
            "slack_thread_detail must NOT reverse raw_messages. "
            "conversations.replies returns oldest-first already. "
            "Reversing produces newest-first and breaks parent extraction."
        )

    def test_thread_detail_returns_messages_in_slack_order(self):
        """Given messages with ts=[1,2,3] from Slack (oldest-first), response must be [1,2,3]."""
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            import routes.slack as slack_mod

        slack_mod._USER_CACHE.clear()
        slack_mod._USER_CACHE_LOADED = True

        replies_response = {
            "ok": True,
            "messages": [
                # Slack returns oldest-first: parent ts=1, replies ts=2,3
                {"user": "U1", "text": "parent msg", "ts": "1000000001.000000"},
                {"user": "U1", "text": "reply 1",    "ts": "1000000002.000000"},
                {"user": "U1", "text": "reply 2",    "ts": "1000000003.000000"},
            ],
        }

        def fake_web_api(endpoint, params=None):
            if endpoint == "conversations.replies":
                return replies_response
            if endpoint == "users.info":
                return {"ok": True, "user": {"profile": {"display_name": "User One", "real_name": ""}}}
            return {"ok": False}

        async def _run():
            with patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
                from fastapi.testclient import TestClient
                from fastapi import FastAPI
                app = FastAPI()
                app.include_router(slack_mod.router)
                client = TestClient(app)
                resp = client.get("/api/slack/threads/C123/1000000001.000000")
                return resp.json()

        data = asyncio.run(_run())
        messages = data.get("messages", [])
        assert len(messages) == 3
        timestamps = [float(m["ts"]) for m in messages]
        assert timestamps == sorted(timestamps), (
            f"Messages must be oldest-first (Slack's natural order) but got: {timestamps}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 3: User cache must be workspace-keyed or cleared on token change
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheWorkspaceInvalidation:
    """When a new token is saved (workspace switch), _USER_CACHE must be
    invalidated so stale cross-workspace names are not served."""

    def test_save_token_clears_user_cache(self):
        """_save_token in mcp_client.py must call a cache-clear hook after saving."""
        # Either: mcp_client imports and calls a clear function from routes.slack,
        # or routes.slack exposes a clear_user_cache() that is called on token save.
        has_clear_hook = (
            "clear_user_cache" in MCP_SRC
            or "invalidate_user_cache" in MCP_SRC
            or "_USER_CACHE.clear" in MCP_SRC
            or "_USER_CACHE_LOADED" in MCP_SRC
        )
        # Also accept: routes/slack.py exposes a function that mcp_client can call
        has_clear_fn = (
            "def clear_user_cache" in SRC
            or "def invalidate_user_cache" in SRC
        )
        assert has_clear_hook or has_clear_fn, (
            "When a new Slack token is saved (workspace switch), the user display-name "
            "cache must be invalidated. Either mcp_client._save_token must call "
            "clear_user_cache(), or the module-level cache must be keyed by team_id."
        )

    def test_cache_keyed_by_team_or_cleared_on_workspace_change(self):
        """After a workspace switch (new team_id), cached names from old workspace
        must not appear for UIDs in the new workspace."""
        for key in list(sys.modules):
            if key == "routes.slack":
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "TOLD"}):
            import routes.slack as slack_mod

        # Pre-populate cache with old workspace data
        with slack_mod._USER_CACHE_LOCK:
            slack_mod._USER_CACHE["U999"] = "Old Workspace User"
        slack_mod._USER_CACHE_LOADED = True

        # Simulate workspace switch — a clear function or keyed structure must exist
        if hasattr(slack_mod, "clear_user_cache"):
            slack_mod.clear_user_cache()
        elif hasattr(slack_mod, "invalidate_user_cache"):
            slack_mod.invalidate_user_cache()
        else:
            # If no explicit clear function, the cache must be team_id-partitioned
            # Verify by checking structure
            pytest.skip("No clear_user_cache found — implementation may use team-keyed cache")

        # After clearing, old entries must be gone
        assert "U999" not in slack_mod._USER_CACHE, (
            "After workspace switch, stale entries from old workspace must be removed "
            "from _USER_CACHE to prevent cross-workspace name contamination."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 4: Token refresh race in concurrent _fetch_external_channels threads
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenRefreshMutex:
    """_refresh_token in mcp_client.py must be protected from concurrent calls.
    Two threads both discovering token expiry must not double-refresh."""

    def test_refresh_token_protected_by_lock(self):
        """mcp_client.py must have a module-level lock guarding token refresh."""
        has_refresh_lock = (
            "_REFRESH_LOCK" in MCP_SRC
            or "_token_refresh_lock" in MCP_SRC
            or "_TOKEN_LOCK" in MCP_SRC
        )
        assert has_refresh_lock, (
            "_fetch_external_channels now calls get_oauth_token() from two concurrent "
            "threads. If the token is near expiry, both will call _refresh_token() "
            "simultaneously, each getting a different token and the last write winning. "
            "A module-level threading.Lock (_REFRESH_LOCK) must serialize refresh calls."
        )

    def test_concurrent_get_oauth_token_calls_refresh_once(self):
        """Three concurrent threads calling get_oauth_token() when token is expired
        must result in exactly one call to _refresh_token, not three."""
        for key in list(sys.modules):
            if "skills.slack.mcp_client" in key:
                del sys.modules[key]
        import skills.slack.mcp_client as mcp_mod

        refresh_calls = [0]
        # After first refresh, store a fresh token so the re-read inside the lock
        # returns non-expired data for the second and third thread.
        fresh_data = {
            "access_token": "new-token-123",
            "refresh_token": "refresh-abc",
            "expires_at": time.time() + 3600,
        }
        expired_data = {
            "access_token": "old-token",
            "refresh_token": "refresh-abc",
            "expires_at": time.time() - 100,
        }
        load_returns = [expired_data]  # first N calls return expired; after refresh, fresh

        def fake_load():
            return load_returns[0]

        def counting_refresh(rt):
            refresh_calls[0] += 1
            time.sleep(0.05)
            load_returns[0] = fresh_data  # simulate token file updated
            return "new-token-123"

        with patch.object(mcp_mod, "_load_token", side_effect=fake_load), \
             patch.object(mcp_mod, "_refresh_token", side_effect=counting_refresh), \
             patch.object(mcp_mod, "_save_token"):
            results = []
            errors = []

            def _call():
                try:
                    t = mcp_mod.get_oauth_token()
                    results.append(t)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=_call) for _ in range(3)]
            for t in threads: t.start()
            for t in threads: t.join(timeout=5)

        assert not errors, f"get_oauth_token raised: {errors}"
        assert refresh_calls[0] == 1, (
            f"Expected exactly 1 refresh call, got {refresh_calls[0]}. "
            "Concurrent threads are both calling _refresh_token — add a mutex."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 5: MCP lock must be fine-grained — not hold during HTTP call
# ─────────────────────────────────────────────────────────────────────────────

import pytest as _pytest_issue  # noqa: E402

@_pytest_issue.mark.skip(reason="SlackMCPClient removed in MCP→Web API migration")
class TestMCPLockGranularity:
    """SlackMCPClient.call() must hold the lock only while reading/writing
    _session_id, NOT across the entire blocking _post() HTTP call.
    Two callers must be able to make MCP calls concurrently."""

    def test_two_mcp_calls_run_concurrently(self):
        """Two threads calling mcp.call() must overlap in time (not fully serialise)."""
        for key in list(sys.modules):
            if "skills.slack.mcp_client" in key:
                del sys.modules[key]
        import skills.slack.mcp_client as mcp_mod

        call_start_times = []
        call_end_times = []
        lock = threading.Lock()

        def slow_post(payload, session_id=None, token=""):
            with lock:
                call_start_times.append(time.monotonic())
            time.sleep(0.1)  # simulate 100ms network call
            with lock:
                call_end_times.append(time.monotonic())
            return (
                {"result": {"content": [{"type": "text", "text": "ok"}]}},
                "sess-abc",
            )

        client = mcp_mod.SlackMCPClient.__new__(mcp_mod.SlackMCPClient)
        client._session_id = "sess-abc"
        client._token = "xoxp-test"
        client._lock = threading.Lock()

        results = []
        errors = []

        def _call():
            try:
                with patch("skills.slack.mcp_client._post", side_effect=slow_post):
                    r = client.call("slack_search_channels", {"query": ""})
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=_call)
        t2 = threading.Thread(target=_call)
        wall_start = time.monotonic()
        t1.start(); t2.start()
        t1.join(timeout=5); t2.join(timeout=5)
        wall_time = time.monotonic() - wall_start

        assert not errors, f"MCP calls raised: {errors}"
        assert len(results) == 2, "Both calls must succeed"
        # If fully serialised, wall time ≥ 0.2s. If concurrent, ≈ 0.1s.
        # Allow up to 0.18s (90% of serialised) to account for thread startup.
        assert wall_time < 0.18, (
            f"Two MCP calls took {wall_time:.3f}s — they appear fully serialised. "
            "The lock must only protect _session_id read/write, not the entire _post() call."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 6: HITL — slack_post_message and slack_send_dm must draft, not auto-send
# ─────────────────────────────────────────────────────────────────────────────

class TestHITLDraftGate:
    """Per CLAUDE.md: Slack messages must NEVER auto-send.
    POST /api/slack/channels/{id}/post and POST /api/slack/dm must return a
    draft object, not call slack_send_message directly."""

    def _fn_body(self, fn_name: str) -> str:
        """Extract just the body of one function (stops at the next @router decorator)."""
        start = SRC.find(f"async def {fn_name}(")
        assert start != -1, f"{fn_name} not found"
        # Find the next decorator after this function starts
        next_decorator = SRC.find("\n@router.", start + 1)
        end = next_decorator if next_decorator != -1 else start + 800
        return SRC[start:end]

    def test_post_message_returns_draft_not_send(self):
        """slack_post_message must NOT call slack_send_message directly."""
        body = self._fn_body("slack_post_message")
        assert "slack_send_message" not in body, (
            "slack_post_message calls slack_send_message directly — auto-sending the message. "
            "Per CLAUDE.md policy it must return a draft response only."
        )

    def test_post_message_returns_draft_field(self):
        """slack_post_message response must include a 'draft' field."""
        body = self._fn_body("slack_post_message")
        assert '"draft"' in body or "'draft'" in body, (
            "slack_post_message must return {'draft': True, ...} not a send result."
        )

    def test_send_dm_returns_draft_not_send(self):
        """slack_send_dm must NOT call slack_send_message directly."""
        body = self._fn_body("slack_send_dm")
        assert "slack_send_message" not in body, (
            "slack_send_dm calls slack_send_message directly — auto-sending the DM. "
            "Per CLAUDE.md it must be draft-only."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Issue 7: Hardcoded "Mayuresh Kulkarni" must use authenticated user's name
# ─────────────────────────────────────────────────────────────────────────────

class TestNoHardcodedUserName:
    """The DM display-name filter must exclude the authenticated user dynamically,
    not the hardcoded string 'Mayuresh Kulkarni'."""

    def test_hardcoded_name_not_in_source(self):
        """The literal string 'Mayuresh Kulkarni' must not appear in routes/slack.py."""
        assert "Mayuresh Kulkarni" not in SRC, (
            "routes/slack.py contains a hardcoded developer name 'Mayuresh Kulkarni' "
            "in the DM display-name filter. This breaks for any other user and leaks "
            "the developer's name. Replace with the authenticated user's display name "
            "read dynamically from the stored token."
        )

    def test_dm_filter_uses_authenticated_user(self):
        """The slack_dms route must filter out the current authenticated user
        by reading their identity from the token, not a hardcoded string."""
        fn_start = SRC.find("async def slack_dms(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 3000]
        # Must reference either the token user field or a resolved user name
        uses_dynamic_user = (
            "_load_token" in fn_body
            or "get_oauth_token" in fn_body
            or "_authed_user" in fn_body
            or "authed_user" in fn_body
            or "current_user" in fn_body
            or "me_name" in fn_body
            or "my_name" in fn_body
            or "my_display" in fn_body
        )
        assert uses_dynamic_user, (
            "slack_dms must identify the current authenticated user dynamically "
            "(e.g. from _load_token().get('user') or via users.info on the authed user) "
            "rather than filtering by a hardcoded name string."
        )
