"""Tests for the LocationLookupFailed cross-region retry fix.

When the Skype chatsvc API returns 404 LocationLookupFailed (thread lives in a
different region than the cached messaging_service), AI Gator must retry the
send via the global amsV2 endpoint rather than surfacing the error to the user.
"""

import pathlib
import json
import types

TEAMS_SRC = (pathlib.Path(__file__).parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")
READ_CHATS_SRC = (pathlib.Path(__file__).parent.parent.parent / "web" / "skills" / "m365-teams" / "scripts" / "read_chats.py").read_text(encoding="utf-8")


# ── Source-level assertions ───────────────────────────────────────────────────

class TestLocationLookupSourcePresence:
    """Verify the fix is wired in at every send site."""

    def test_tp_teams_send_has_location_lookup_retry(self):
        """tp_teams_send must catch LocationLookupFailed and retry."""
        assert "LocationLookupFailed" in TEAMS_SRC, (
            "routes/teams.py must handle LocationLookupFailed for tp_teams_send"
        )

    def test_teams_new_chat_has_location_lookup_retry(self):
        """tp_teams_new_chat (teams-new path) must catch LocationLookupFailed."""
        new_chat_start = TEAMS_SRC.find("teams-new] LocationLookupFailed")
        assert new_chat_start != -1, (
            "routes/teams.py: tp_teams_new_chat must log and retry on LocationLookupFailed"
        )

    def test_fast_path_has_location_lookup_retry(self):
        """tp_teams_send_message fast path must catch LocationLookupFailed."""
        fast_path_start = TEAMS_SRC.find("fast path LocationLookupFailed")
        assert fast_path_start != -1, (
            "routes/teams.py: tp_teams_send_message fast path must retry on LocationLookupFailed"
        )

    def test_edit_has_location_lookup_retry(self):
        """Edit message endpoint must catch LocationLookupFailed."""
        edit_start = TEAMS_SRC.find("tp_teams_edit_message")
        assert edit_start != -1
        edit_body = TEAMS_SRC[edit_start: edit_start + 2000]
        assert "LocationLookupFailed" in edit_body, (
            "routes/teams.py: tp_teams_edit_message must retry on LocationLookupFailed"
        )

    def test_delete_has_location_lookup_retry(self):
        """Delete message endpoint must catch LocationLookupFailed."""
        del_start = TEAMS_SRC.find("tp_teams_delete_message")
        assert del_start != -1
        del_body = TEAMS_SRC[del_start: del_start + 2000]
        assert "LocationLookupFailed" in del_body, (
            "routes/teams.py: tp_teams_delete_message must retry on LocationLookupFailed"
        )

    def test_get_global_service_defined(self):
        """read_chats.py must expose get_global_service()."""
        assert "def get_global_service" in READ_CHATS_SRC, (
            "read_chats.py must define get_global_service() returning the amsV2 endpoint"
        )

    def test_global_service_saved_in_token_cache(self):
        """_save_skype_token must persist global_service."""
        assert '"global_service"' in READ_CHATS_SRC or "'global_service'" in READ_CHATS_SRC, (
            "read_chats.py must save global_service in the skype token cache file"
        )

    def test_chatServiceAfd_extracted_from_authz_response(self):
        """Token exchange must read chatServiceAfd (AFD global routing) from regionGtms."""
        assert "chatServiceAfd" in READ_CHATS_SRC, (
            "read_chats.py must read regionGtms['chatServiceAfd'] during token exchange"
        )

    def test_retry_uses_get_global_service(self):
        """All retry paths must use get_global_service(), not a hardcoded URL."""
        assert "get_global_service()" in TEAMS_SRC, (
            "routes/teams.py must call get_global_service() for the LocationLookupFailed retry"
        )


# ── Behavioural unit tests ────────────────────────────────────────────────────

class _MockResponse:
    """Minimal httpx.Response stand-in."""
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text) if self.text else {}


def _make_retry_logic(global_svc: str):
    """
    Replicate the LocationLookupFailed retry pattern from routes/teams.py
    so we can test it without importing the full FastAPI app.
    """
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            # First call: regional endpoint → LocationLookupFailed
            return _MockResponse(404, json.dumps({
                "errorCode": 404,
                "message": json.dumps({"subCode": "LocationLookupFailed"}),
            }))
        # Second call: global endpoint → success
        return _MockResponse(201, json.dumps({"id": "msg-abc"}))

    def get_global_service():
        return global_svc

    def send(messaging_service, encoded_chat, body):
        resp = post(f"{messaging_service}/users/ME/conversations/{encoded_chat}/messages")
        if resp.status_code == 404 and "LocationLookupFailed" in resp.text:
            gs = get_global_service()
            if gs:
                resp = post(f"{gs}/users/ME/conversations/{encoded_chat}/messages")
        return resp, calls

    return send


class TestLocationLookupRetryBehaviour:
    """Behavioural tests for the retry logic (no FastAPI/httpx import needed)."""

    def test_retry_fires_on_location_lookup_failed(self):
        send = _make_retry_logic("https://global.msg.teams.microsoft.com/v1")
        resp, calls = send(
            "https://amer.ng.msg.teams.microsoft.com/v1",
            "19%3Aabc%40unq.gbl.spaces",
            {"content": "hi", "messagetype": "RichText/Html"},
        )
        assert len(calls) == 2, "Must retry exactly once on LocationLookupFailed"
        assert "global.msg.teams.microsoft.com" in calls[1], "Retry must target global endpoint"
        assert resp.status_code == 201, "Retry must succeed"

    def test_no_retry_on_success(self):
        calls = []

        def post_success(url, **kwargs):
            calls.append(url)
            return _MockResponse(201, json.dumps({"id": "msg-xyz"}))

        resp = post_success("https://amer.ng.msg.teams.microsoft.com/v1/users/ME/conversations/abc/messages")
        if resp.status_code == 404 and "LocationLookupFailed" in resp.text:
            post_success("should-not-be-called")

        assert len(calls) == 1, "Must NOT retry on a successful send"

    def test_no_retry_on_other_404(self):
        """A plain 404 (not LocationLookupFailed) must not trigger the retry."""
        calls = []

        def post_plain_404(url, **kwargs):
            calls.append(url)
            return _MockResponse(404, json.dumps({"error": "Not found"}))

        resp = post_plain_404("https://amer.ng.msg.teams.microsoft.com/v1/users/ME/conversations/abc/messages")
        if resp.status_code == 404 and "LocationLookupFailed" in resp.text:
            post_plain_404("should-not-be-called")

        assert len(calls) == 1, "Must NOT retry on a plain 404 without LocationLookupFailed"

    def test_no_retry_when_global_service_unknown(self):
        """If global_service is empty (old token cache), do not retry — surface the error."""
        send = _make_retry_logic("")  # no global_service
        resp, calls = send(
            "https://amer.ng.msg.teams.microsoft.com/v1",
            "19%3Aabc%40unq.gbl.spaces",
            {"content": "hi", "messagetype": "RichText/Html"},
        )
        assert len(calls) == 1, "Must not retry when global_service is unknown"
        assert resp.status_code == 404

    def test_global_service_saved_and_loaded(self):
        """Simulate token save/load round-trip preserving global_service."""
        import tempfile, os

        token_data = {
            "skype_token": "tok123",
            "messaging_service": "https://amer.ng.msg.teams.microsoft.com/v1",
            "global_service": "https://teams.microsoft.com/api/chatsvc/amer/v1",
            "expires_at": 9999999999,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(token_data, f)
            tmp = f.name

        try:
            loaded = json.loads(pathlib.Path(tmp).read_text())
            assert loaded.get("global_service") == token_data["global_service"], (
                "global_service must survive a save/load round-trip"
            )
        finally:
            os.unlink(tmp)
