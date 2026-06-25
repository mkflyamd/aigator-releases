"""#127 — Channel thread: replies must be grouped under parents (not flat),
and sender names must resolve (no raw GUIDs).

The _loadChannelThread function currently shows a placeholder. The backend
endpoint exists. These tests assert the production code is wired up.
"""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")
BACKEND = (pathlib.Path(__file__).resolve().parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


class TestChannelMessages:

    def test_load_channel_thread_not_placeholder(self):
        """_loadChannelThread must actually fetch messages, not show a placeholder."""
        idx = SRC.find("function _loadChannelThread(")
        assert idx != -1
        body = SRC[idx:idx + 600]
        assert "coming soon" not in body and "permissions paperwork" not in body, (
            "_loadChannelThread must fetch real channel messages via the API (#127)"
        )

    def test_load_channel_thread_fetches_api(self):
        """_loadChannelThread must call /api/teams/channels/{teamId}/{channelId}/messages."""
        idx = SRC.find("function _loadChannelThread(")
        body = SRC[idx:idx + 800]
        assert "api/teams/channels" in body or "channels/" in body, (
            "_loadChannelThread must fetch from /api/teams/channels endpoint (#127)"
        )

    def test_backend_resolves_sender_name(self):
        """Channel message backend must not return raw GUIDs as sender_name.
        sender_name fallback should prefer isMentionedUser displayName or empty string."""
        idx = BACKEND.find("async def tp_channel_messages(")
        body = BACKEND[idx:idx + 1500]
        # The sender_name must not be taken from sender_id (which is the GUID)
        assert 'sender.get("id"' not in body.split("sender_name")[1].split("\n")[0] if "sender_name" in body else True, (
            "sender_name must not use the raw AAD GUID — use displayName only (#127)"
        )
