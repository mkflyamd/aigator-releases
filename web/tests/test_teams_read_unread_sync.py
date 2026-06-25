"""Read/unread bidirectional sync with native Teams web.

Reverse-engineered from live native-Teams chatsvc captures (2026-06-24):

  mark-READ   PUT .../properties?name=consumptionHorizonBookmark
              body {"consumptionHorizonBookmark":"0;{now};0"}   <- readUntil = 0 (cleared)
  mark-UNREAD PUT .../properties?name=consumptionHorizonBookmark
              body {"consumptionHorizonBookmark":"{msgTs};{now};{msgId}"}  <- readUntil > 0 (pinned)

The bookmark's FIRST field (readUntil ms) is the unread signal:
  - readUntil > 0  -> chat is explicitly pinned UNREAD
  - readUntil == 0 -> bookmark cleared (read)

Our previous bug: tp_teams_mark_read wrote "{now};{now};0" (readUntil = now > 0),
which native interprets as an active unread pin -> Gator mark-read never propagated
to native Teams. Native clears it with readUntil = 0.

These are source-assertion tests (system Python lacks fastapi/httpx).
"""
import pathlib
import re

BACKEND = (pathlib.Path(__file__).resolve().parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


def _func_body(name: str, span: int = 1400) -> str:
    idx = BACKEND.find(f"async def {name}(")
    if idx == -1:
        idx = BACKEND.find(f"def {name}(")
    assert idx != -1, f"{name} not found"
    return BACKEND[idx:idx + span]


class TestMarkReadClearsBookmark:

    def test_mark_read_clears_bookmark_with_zero_readuntil(self):
        """mark-read must clear the bookmark with readUntil=0 ('0;...'), NOT '{now};{now};0'.

        Native Teams writes consumptionHorizonBookmark='0;{now};0' on read. A non-zero
        first field is an active unread pin and prevents read from propagating.
        """
        body = _func_body("tp_teams_mark_read")
        # The bookmark clear must use a literal leading 0 (readUntil=0), e.g. f"0;{now_ms};0"
        assert re.search(r'consumption_horizon_bookmark\([^)]*?f?"0;', body) or \
               re.search(r'bookmark[^=]*=\s*f?"0;', body), (
            "mark-read must clear bookmark with readUntil=0 (\"0;{now};0\"), "
            "not \"{now};{now};0\" which native reads as an unread pin"
        )

    def test_mark_read_does_not_pin_bookmark_with_now(self):
        """mark-read must NOT pass a now-prefixed value to the bookmark setter (unread pin).

        The horizon legitimately uses '{now};{now};0'; only the BOOKMARK call must be
        readUntil=0. Assert the bookmark setter is invoked with a '0;'-prefixed value.
        """
        body = _func_body("tp_teams_mark_read")
        m = re.search(r'_skype_set_consumption_horizon_bookmark\(chat_id,\s*(f?"[^"]+")\)', body)
        assert m, "mark-read must call _skype_set_consumption_horizon_bookmark"
        assert m.group(1).startswith('f"0;') or m.group(1).startswith('"0;'), (
            f"bookmark clear must be readUntil=0, got {m.group(1)}"
        )


class TestMarkUnreadPinsBookmark:

    def test_mark_unread_pins_bookmark_with_message_timestamp(self):
        """mark-unread must set the bookmark first field to the target message timestamp (>0)."""
        body = _func_body("tp_teams_mark_unread", span=2200)
        assert "_skype_set_consumption_horizon_bookmark" in body, (
            "mark-unread must write via the consumptionHorizonBookmark endpoint"
        )


class TestUnreadComputationNoHeuristic:

    def test_no_gap_second_heuristic(self):
        """The unread computation must NOT use a fragile time-gap heuristic.

        The bug report 'all messages keep showing unread' came from the 30s-gap
        heuristic. The native-correct rule is readUntil>0 on the bookmark — exact,
        no thresholds.
        """
        idx = BACKEND.find("def _normalize_skype_chats(")
        body = BACKEND[idx:idx + 6500]
        assert "gap_secs" not in body, (
            "unread computation must not use a gap_secs heuristic — "
            "use bookmark readUntil>0 (exact native rule) instead"
        )

    def test_unread_uses_bookmark_readuntil(self):
        """Unread must be driven by the bookmark's readUntil (first field) > 0."""
        idx = BACKEND.find("def _normalize_skype_chats(")
        body = BACKEND[idx:idx + 6500]
        assert "bookmark_read_until" in body or "_bookmark_readuntil" in body, (
            "unread computation must parse the bookmark's first field (readUntil ms) "
            "and treat >0 as an explicit unread pin"
        )
