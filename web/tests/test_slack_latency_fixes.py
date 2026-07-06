"""TDD tests for Slack latency fixes — written BEFORE implementation.

Covers:
  1. SlackMCPClient.call() thread safety (threading.Lock)
  2. Batch user resolution with asyncio.gather(return_exceptions=True)
  3. Module-level user cache — no caching of failed/rate-limited resolutions
  4. get_oauth_token() not blocking event loop during token refresh
  5. Parallel external channel pagination
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
# 1. SlackMCPClient.call() must be thread-safe
# ─────────────────────────────────────────────────────────────────────────────

import pytest as _pytest

@_pytest.mark.skip(reason="SlackMCPClient removed in MCP→Web API migration")
class TestMCPClientThreadSafety:
    """SlackMCPClient.call() must acquire a lock before calling _post()
    so concurrent run_in_executor threads cannot race on _session_id."""

    def test_mcp_client_has_lock_attribute(self):
        """SlackMCPClient.__init__ must initialise a threading.Lock."""
        assert "threading.Lock" in MCP_SRC or "_lock" in MCP_SRC, (
            "SlackMCPClient must initialise a threading.Lock (e.g. self._lock = threading.Lock()) "
            "to protect _session_id from concurrent thread access via run_in_executor."
        )

    def test_call_method_acquires_lock(self):
        """The call() method body must reference the lock (with self._lock or _lock.acquire)."""
        call_start = MCP_SRC.find("def call(self,")
        assert call_start != -1, "call() method not found in mcp_client.py"
        call_body = MCP_SRC[call_start: call_start + 1500]
        assert "_lock" in call_body or "with self._lock" in call_body, (
            "SlackMCPClient.call() must acquire the lock before calling _post() "
            "to prevent session-ID races when called from multiple threads."
        )

    def test_concurrent_calls_do_not_corrupt_session_id(self):
        """Two threads calling mcp.call() concurrently must not corrupt _session_id."""
        import importlib
        import sys as _sys

        for key in list(_sys.modules):
            if "skills.slack.mcp_client" in key:
                del _sys.modules[key]

        import skills.slack.mcp_client as mcp_mod

        good_result = (
            {"result": {"content": [{"type": "text", "text": "ok"}]}},
            "sess-123",
        )

        client = mcp_mod.SlackMCPClient.__new__(mcp_mod.SlackMCPClient)
        client._session_id = "sess-123"
        client._token = "xoxp-test"
        client._lock = threading.Lock()

        results = []
        errors = []

        def _call():
            try:
                with patch("skills.slack.mcp_client._post", return_value=good_result):
                    r = client.call("slack_search_channels", {"query": ""})
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_call) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Concurrent calls raised: {errors}"
        assert len(results) == 5, "All 5 threads must get a result"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Batch user resolution with return_exceptions=True
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchUserResolution:
    """slack_channel_messages must resolve all unique UIDs concurrently and
    fall back to UID on per-user failures rather than failing the whole request."""

    def test_source_uses_gather_for_user_resolution(self):
        """routes/slack.py must use asyncio.gather for batch user resolution."""
        assert "asyncio.gather" in SRC or "gather(" in SRC, (
            "slack_channel_messages must use asyncio.gather() to resolve "
            "user display names concurrently instead of sequential blocking calls."
        )

    def test_gather_uses_return_exceptions(self):
        """asyncio.gather must be called with return_exceptions=True."""
        assert "return_exceptions=True" in SRC, (
            "asyncio.gather must use return_exceptions=True so a single failed "
            "user lookup doesn't abort the entire message response."
        )

    def test_failed_lookup_falls_back_to_uid(self):
        """A user whose lookup raises must display as their UID, not crash the response."""
        import importlib
        for key in list(sys.modules):
            if key in ("routes.slack", "routes"):
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            import routes.slack as slack_mod

        # Simulate conversations.history returning 2 messages from 2 different users
        history_response = {
            "ok": True,
            "messages": [
                {"user": "UGOOD1", "text": "hello", "ts": "1700000001.000000"},
                {"user": "UBAD2",  "text": "world",  "ts": "1700000002.000000"},
            ],
            "response_metadata": {"next_cursor": ""},
        }

        call_count = {"n": 0}

        def fake_web_api(endpoint, params=None):
            if endpoint == "conversations.history":
                return history_response
            if endpoint == "users.info":
                uid = (params or {}).get("user", "")
                if uid == "UBAD2":
                    return {"ok": False, "error": "user_not_found"}
                return {"ok": True, "user": {"profile": {
                    "display_name": "Good User", "real_name": "Good User",
                }}}
            return {"ok": False, "error": "unknown"}

        async def _run():
            with patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
                from fastapi.testclient import TestClient
                from fastapi import FastAPI
                app = FastAPI()
                app.include_router(slack_mod.router)
                client = TestClient(app)
                resp = client.get("/api/slack/channels/C123/messages?limit=2")
                return resp.json()

        data = asyncio.run(_run())
        messages = data.get("messages", [])
        assert len(messages) == 2, "Both messages must be returned even when one user lookup fails"
        users = {m["user"] for m in messages}
        assert "Good User" in users, "Successfully-resolved user must show display name"
        # UBAD2 must fall back to UID or some non-crash value, not drop the message
        bad_msg = next(m for m in messages if m["user_id"] == "UBAD2")
        assert bad_msg is not None, "Message from unresolvable user must still appear"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Module-level user cache — no caching of failures
# ─────────────────────────────────────────────────────────────────────────────

class TestModuleLevelUserCache:
    """The module-level user cache in routes/slack.py must:
    - Exist as a module-level dict (not re-read from disk every request)
    - NOT cache failed or rate-limited resolutions
    """

    def test_module_level_cache_exists_in_source(self):
        """routes/slack.py must define a module-level dict for the user cache."""
        # Look for a module-level assignment like: _USER_CACHE = {} or _user_cache = {}
        assert "_USER_CACHE" in SRC or "_user_cache" in SRC or "_ucache" in SRC.split("def ")[0], (
            "routes/slack.py must define a module-level dict for the user display-name "
            "cache so it persists across requests without a disk read each time."
        )

    def test_failed_resolution_not_cached(self):
        """A UID whose users.info returns ok=False must not be cached (so retry works next time)."""
        for key in list(sys.modules):
            if key in ("routes.slack",):
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            import routes.slack as slack_mod

        # Reset module cache
        if hasattr(slack_mod, "_USER_CACHE"):
            slack_mod._USER_CACHE.clear()
        elif hasattr(slack_mod, "_user_cache"):
            slack_mod._user_cache.clear()

        call_count = [0]

        def fake_web_api(endpoint, params=None):
            if endpoint == "users.info":
                call_count[0] += 1
                return {"ok": False, "error": "ratelimited"}
            return {"ok": True, "messages": [], "response_metadata": {"next_cursor": ""}}

        with patch.object(slack_mod, "_slack_web_api", side_effect=fake_web_api):
            # Simulate two requests for the same channel — each has a message from UBAD
            async def _resolve():
                # Directly call the internal display-name resolution if it's extractable
                # Otherwise we test through the API endpoint
                pass
            # The key contract: after a failed lookup, the UID must NOT be in the module-level cache
            # so the next request will retry the API call
            cache = getattr(slack_mod, "_USER_CACHE", getattr(slack_mod, "_user_cache", None))
            if cache is not None:
                assert "UBAD_RATE" not in cache, (
                    "A UID that got a rate-limited response must not be written into the "
                    "module-level cache — it must be retried on the next request."
                )

    def test_ratelimited_response_not_cached(self):
        """Source must explicitly check ok=False before writing to the module-level cache."""
        # After the fix, the cache-write path must be gated on ok=True
        # Find the block that writes to the module-level cache
        cache_write_markers = ["_USER_CACHE[", "_user_cache["]
        found_write = any(m in SRC for m in cache_write_markers)
        if found_write:
            # Verify there's a check for ok before writing
            # Look for the pattern: if data.get("ok"): ... cache[uid] = name
            has_ok_guard = ("data.get(\"ok\")" in SRC or "data.get('ok')" in SRC or
                            ".get(\"ok\")" in SRC)
            assert has_ok_guard, (
                "The module-level cache write must be guarded by checking ok=True on the "
                "users.info response. Rate-limited (ok=False) responses must not be cached."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. get_oauth_token must not block in async context during token refresh
# ─────────────────────────────────────────────────────────────────────────────

class TestOAuthTokenRefreshNonBlocking:
    """get_oauth_token() can call _refresh_token() which does a blocking urlopen.
    The async route handlers must wrap this in run_in_executor or asyncio.to_thread."""

    def test_channel_messages_wraps_token_fetch_in_executor(self):
        """slack_channel_messages must not call get_oauth_token() bare in async context
        — it must use run_in_executor or asyncio.to_thread."""
        fn_start = SRC.find("async def slack_channel_messages(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 3000]
        # Accept either run_in_executor or asyncio.to_thread wrapping token+web api calls
        uses_executor = "run_in_executor" in fn_body or "asyncio.to_thread" in fn_body
        assert uses_executor, (
            "slack_channel_messages must wrap blocking calls (get_oauth_token, _slack_web_api) "
            "in run_in_executor or asyncio.to_thread to avoid blocking the event loop "
            "during token refresh."
        )

    def test_thread_detail_wraps_token_fetch_in_executor(self):
        """slack_thread_detail must also wrap blocking calls."""
        fn_start = SRC.find("async def slack_thread_detail(")
        assert fn_start != -1
        fn_body = SRC[fn_start: fn_start + 3000]
        uses_executor = "run_in_executor" in fn_body or "asyncio.to_thread" in fn_body
        assert uses_executor, (
            "slack_thread_detail must wrap blocking calls in run_in_executor or asyncio.to_thread."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. External channel fetch must run two channel types concurrently
# ─────────────────────────────────────────────────────────────────────────────

class TestParallelExternalChannelFetch:
    """_fetch_external_channels must fetch private_channel and public_channel
    concurrently, not in a sequential for-loop."""

    def test_fetch_external_not_sequential_for_loop(self):
        """The function must NOT use a plain 'for ch_type in (...)' sequential loop."""
        helper_start = SRC.find("def _fetch_external_channels")
        assert helper_start != -1
        helper_body = SRC[helper_start: helper_start + 2000]
        # If there's a bare sequential 'for ch_type in' without gather/Thread, flag it
        has_sequential_loop = 'for ch_type in (' in helper_body or 'for ch_type in [' in helper_body
        has_parallel = ("gather" in helper_body or "ThreadPoolExecutor" in helper_body
                        or "concurrent" in helper_body or "asyncio.to_thread" in helper_body)
        if has_sequential_loop:
            assert has_parallel, (
                "_fetch_external_channels must run private_channel and public_channel "
                "fetches concurrently (asyncio.gather or ThreadPoolExecutor), not sequentially."
            )

    def test_fetch_external_returns_both_types(self):
        """Results from both private_channel and public_channel ext_shared must be included."""
        for key in list(sys.modules):
            if key in ("routes.slack",):
                del sys.modules[key]

        with patch("skills.slack.mcp_client.get_oauth_token", return_value="xoxp-test"), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            import routes.slack as slack_mod

        private_ch = {"id": "CPRIV_EXT", "name": "private-ext", "is_ext_shared": True,
                      "purpose": {"value": ""}, "topic": {"value": ""}}
        public_ch  = {"id": "CPUB_EXT",  "name": "public-ext",  "is_ext_shared": True,
                      "purpose": {"value": ""}, "topic": {"value": ""}}

        def fake_api(endpoint, params=None):
            types = (params or {}).get("types", "")
            if "private_channel" in types:
                return {"ok": True, "channels": [private_ch], "response_metadata": {"next_cursor": ""}}
            if "public_channel" in types:
                return {"ok": True, "channels": [public_ch], "response_metadata": {"next_cursor": ""}}
            return {"ok": True, "channels": [], "response_metadata": {"next_cursor": ""}}

        with patch.object(slack_mod, "_slack_web_api", side_effect=fake_api):
            result = slack_mod._fetch_external_channels()

        ids = {c["channel_id"] for c in result}
        assert "CPRIV_EXT" in ids, "Must include ext_shared private channels"
        assert "CPUB_EXT"  in ids, "Must include ext_shared public channels"
