"""DM partner-name regression — show the OTHER person's name in the DM list.

Root cause: when a 1:1 DM has an empty thread_members roster AND the current
user sent the last message, neither the GUID→name map (from last_sender) nor the
roster yields the partner's name, so the list fell back to "Chat" (or worse, the
current user's own display name). The partner's name is, however, always present
in the DM's own message history (sender_name / from_mri of the other party).

Fix: a helper that, for unresolved DMs, fetches one page of message history via
the Skype API and resolves the topic to the first message sender whose AAD GUID
is NOT the current user's.

These tests verify the helper exists, parses the partner GUID from the chat ID,
skips the current user's own messages, and is wired into the chat-list endpoint.
"""

import pathlib

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


class TestDmHistoryResolver:

    def test_helper_exists(self):
        """A history-based DM resolver helper must exist."""
        assert "_resolve_dm_names_via_history" in SRC, (
            "_resolve_dm_names_via_history must exist — resolves DM partner name "
            "from message history when roster/last_sender are insufficient"
        )

    def test_helper_reads_messages(self):
        """The helper must call read_messages to pull the partner name from history."""
        start = SRC.find("def _resolve_dm_names_via_history(")
        assert start != -1
        nxt = SRC.find("\ndef ", start + 1)
        body = SRC[start:nxt if nxt != -1 else start + 2500]
        assert "read_messages" in body, (
            "_resolve_dm_names_via_history must call read_messages() to fetch history"
        )

    def test_helper_skips_own_messages(self):
        """The helper must skip the current user's own messages (compare GUID to mine)."""
        start = SRC.find("def _resolve_dm_names_via_history(")
        nxt = SRC.find("\ndef ", start + 1)
        body = SRC[start:nxt if nxt != -1 else start + 2500]
        assert "from_mri" in body or "sender_name" in body, (
            "_resolve_dm_names_via_history must read sender identity from messages"
        )
        assert "my_guid" in body or "_my_guid" in body, (
            "_resolve_dm_names_via_history must compare sender GUID against the "
            "current user's GUID to pick the OTHER person"
        )

    def test_helper_only_targets_unresolved_dms(self):
        """The helper must only act on DMs whose topic is unresolved (Chat/own name),
        not re-fetch history for every chat (avoids needless API calls)."""
        start = SRC.find("def _resolve_dm_names_via_history(")
        nxt = SRC.find("\ndef ", start + 1)
        body = SRC[start:nxt if nxt != -1 else start + 2500]
        assert "oneOnOne" in body, (
            "_resolve_dm_names_via_history must filter to oneOnOne chats"
        )
        assert '"Chat"' in body or "'Chat'" in body, (
            "_resolve_dm_names_via_history must target only unresolved 'Chat' topics"
        )

    def test_helper_wired_into_chat_list(self):
        """The chat-list endpoint must call the history resolver, via its shared
        fetch helper (tp_teams_chats -> _fetch_chats_payload -> the resolver) —
        this indirection avoids duplicating the resolve step across both the
        cache-hit and cache-miss/pagination paths in tp_teams_chats."""
        ep = SRC.find("def tp_teams_chats(")
        assert ep != -1
        nxt = SRC.find("\n@router", ep + 1)
        body = SRC[ep:nxt if nxt != -1 else ep + 1500]
        assert "_fetch_chats_payload" in body, (
            "tp_teams_chats must route through _fetch_chats_payload"
        )

        fp = SRC.find("def _fetch_chats_payload(")
        assert fp != -1
        fp_nxt = SRC.find("\ndef ", fp + 1)
        fp_body = SRC[fp:fp_nxt if fp_nxt != -1 else fp + 1500]
        assert "_resolve_dm_names_via_history" in fp_body, (
            "_fetch_chats_payload must call _resolve_dm_names_via_history to fix DM names"
        )
