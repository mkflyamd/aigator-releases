"""Teams channel search must paginate the Skype group-chat fetch, not request a
single un-paginated page.

Bug: /api/channels/search's group-chat enumeration called
list_chats(skype_token, messaging_service, limit=50) exactly once. Skype
orders conversations by recent activity, so any group chat that wasn't
among the 50 most recently active ones was silently dropped from the
cache -- e.g. a group named "Cohere Leads" (and 5 sibling "Cohere ..."
groups) intermittently vanished from "#coh" search results depending on
how recently they'd had activity, even though the user was still a
member.

Fix: follow the Skype backward_link cursor in a bounded loop (same
pattern already used by tp_teams_search, see
test_teams_search_pagination.py) so the group-chat list isn't truncated
to a single page.

System Python lacks fastapi/httpx, so these are source-structure
assertions over the route handler (same approach as the other teams/
channel-search tests in this file's sibling suite).
"""

import pathlib
import re

SRC = (
    pathlib.Path(__file__).resolve().parent.parent / "routes" / "health.py"
).read_text(encoding="utf-8")


def _channels_search_body() -> str:
    start = SRC.find("def channels_search(")
    assert start != -1, "channels_search must exist"
    # channels_search is the last function in health.py at the time of
    # writing; fall back to end-of-file if no later def/route follows.
    nxt = SRC.find("\n@router", start + 1)
    nxt_def = SRC.find("\ndef ", start + 1)
    candidates = [n for n in (nxt, nxt_def) if n != -1]
    end = min(candidates) if candidates else len(SRC)
    return SRC[start:end]


class TestChannelsSearchGroupChatPagination:
    def test_follows_backward_link_cursor(self):
        """Must paginate by following the Skype backward_link cursor."""
        body = _channels_search_body()
        assert "backward_link" in body, (
            "channels_search must follow backward_link to accumulate group "
            "chats beyond the first page"
        )

    def test_has_bounded_loop(self):
        """Pagination must be bounded (a loop with a page cap) to limit latency."""
        body = _channels_search_body()
        assert "while" in body or "for " in body, (
            "channels_search must loop to accumulate group-chat pages"
        )
        assert re.search(r"\b(range\(|<\s*\d{2,}|>=?\s*\d{2,}|_MAX|max_)", body), (
            "channels_search group-chat pagination must be bounded by an "
            "explicit cap"
        )

    def test_does_not_call_list_chats_only_once_unbounded(self):
        """Must not go back to a single un-paginated list_chats(...) call —
        that's the exact regression (silently drops less-recently-active
        group chats like 'Cohere Leads')."""
        body = _channels_search_body()
        # A single, un-looped assignment of the form `convs, _ = ... list_chats(`
        # (discarding the cursor) is the broken shape; the fixed shape reuses
        # the cursor across iterations.
        assert "convs, _ = _rc.list_chats" not in body, (
            "channels_search must not discard the backward_link cursor from "
            "list_chats — that silently truncates group chats to one page"
        )
        assert "backward_link=backward_link" in body or "backward_link=" in body, (
            "channels_search must pass the cursor back into list_chats to "
            "page through group chats"
        )
