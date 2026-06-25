"""Teams search must paginate the Skype fetch, not request one oversized page (#118 P2).

Bug: tp_teams_search called list_chats(limit=1000). Skype rejects pageSize=1000 with
HTTP 400, so /api/teams/search returned HTTP 500 and produced no results at all.

Fix: accumulate chats by following the Skype backward_link cursor in a bounded loop
(safe page size, capped total) so search reaches a wide window without an oversized
request.

System Python lacks fastapi/httpx, so these are source-structure assertions over the
search handler (same approach as the other teams tests).
"""

import pathlib

SRC = (pathlib.Path(__file__).resolve().parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


def _search_body() -> str:
    start = SRC.find("def tp_teams_search(")
    assert start != -1, "tp_teams_search must exist"
    nxt = SRC.find("\n@router", start + 1)
    return SRC[start:nxt if nxt != -1 else start + 2000]


class TestSearchPagination:

    def test_no_oversized_page_request(self):
        """Must NOT request a giant single page (Skype 400s on pageSize=1000)."""
        body = _search_body()
        assert "limit=1000" not in body, (
            "tp_teams_search must not call list_chats(limit=1000) — Skype rejects it"
        )

    def test_follows_backward_link_cursor(self):
        """Must paginate by following the Skype backward_link cursor."""
        body = _search_body()
        assert "backward_link" in body, (
            "tp_teams_search must follow backward_link to accumulate a wide window"
        )

    def test_has_bounded_loop(self):
        """Pagination must be bounded (a loop with a page/total cap) to limit latency."""
        body = _search_body()
        assert ("while" in body or "for " in body), (
            "tp_teams_search must loop to accumulate pages"
        )
        # A numeric cap should be present (max pages or max chats).
        import re
        assert re.search(r"\b(range\(|<\s*\d{2,}|>=?\s*\d{2,}|_MAX|max_)", body), (
            "tp_teams_search pagination must be bounded by an explicit cap"
        )

    def test_uses_normalizer(self):
        """Search must use _normalize_skype_chats for names (fast, no network)."""
        body = _search_body()
        assert "_normalize_skype_chats" in body

    def test_does_not_call_slow_resolver(self):
        """Search must NOT call _resolve_chat_names — it does dozens of sequential
        Graph/Skype lookups and took 20-30s for ~400 chats, making search feel broken.
        _normalize_skype_chats already resolves ~99% of names with no network (#118)."""
        body = _search_body()
        assert "_resolve_chat_names" not in body, (
            "tp_teams_search must not call _resolve_chat_names — it's the 20-30s "
            "bottleneck; normalize alone resolves names fast enough"
        )

    def test_default_top_not_small(self):
        """The result cap must NOT default to a small value like 50 — that truncated
        368 real matches down to 50, so most name/group matches never showed (#118 P0).
        Default must be large enough to return all matches in the scanned window."""
        import re
        sig = SRC[SRC.find("def tp_teams_search("):]
        sig = sig[:sig.find(")")]
        m = re.search(r"top:\s*int\s*=\s*(\d+)", sig)
        assert m, "tp_teams_search must declare a top default"
        assert int(m.group(1)) >= 500, (
            f"search top default is {m.group(1)} — too small; it caps visible matches. "
            f"Must be >= 500 so all name/group matches in the window are returned."
        )
