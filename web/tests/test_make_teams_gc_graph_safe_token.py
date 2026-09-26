"""make_teams_gc() must never use the Skype-audience token from
get_teams_token()'s skype_token.json tier.

Bug: get_teams_token() gained a skype_token.json tier (see
test_get_teams_token_skype_fallback.py) to fix AMS image-CDN 401s. But
make_teams_gc() built its GraphClient from that same function's return
value, and that GraphClient is used all over teams.py for real Microsoft
Graph calls (/me, /users, /chats). A Skype-audience token sent to
graph.microsoft.com is rejected with 401 "Issuer claim is malformed" --
so once teams_token.json expired/was absent and skype_token.json was
valid (the common case, since skype_token.json is refreshed on every
Teams chat read), every Graph call through make_teams_gc() broke,
including tp_teams_new_chat's recipient-resolution lookup when messaging
someone with no already-known chat_id.

Fix: make_teams_gc() now sources its token from
_get_graph_compatible_teams_token(), which mirrors get_teams_token()'s
tiers 1 (teams_token.json) and 3 (Graph OAuth Bearer) only, deliberately
skipping the Skype-only tier.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_skype_token_file(cfg: Path, expired: bool = False) -> None:
    (cfg / "skype_token.json").write_text(
        json.dumps(
            {
                "skype_token": "SKYPE-TOKEN-XYZ",
                "expires_at": time.time() + (-60 if expired else 3600),
                "messaging_service": "https://fake.msging.net",
                "global_service": "",
            }
        )
    )


def _make_teams_token_file(cfg: Path, expired: bool = False) -> None:
    (cfg / "teams_token.json").write_text(
        json.dumps(
            {
                "access_token": "BROWSER-TOKEN-ABC",
                "expires_at": time.time() + (-60 if expired else 3600),
            }
        )
    )


def _reset_teams_gc_cache(mod) -> None:
    mod._teams_gc_instance = None
    mod._teams_gc_token = None


class TestMakeTeamsGcGraphSafeToken:
    def test_never_uses_skype_token_even_when_it_is_the_only_valid_token(
        self, tmp_path, monkeypatch
    ):
        """The exact regression scenario: teams_token.json absent,
        skype_token.json present and valid. make_teams_gc() must fall
        through to a genuine Graph Bearer token, NOT the Skype token.
        """
        cfg = tmp_path / ".config" / "microsoft-graph"
        cfg.mkdir(parents=True)
        _make_skype_token_file(cfg)

        import skills._m365.helpers as h

        _reset_teams_gc_cache(h)
        fake_gc = MagicMock()
        fake_gc.get_token.return_value = "GRAPH-BEARER-TOKEN"

        with patch.object(Path, "home", return_value=tmp_path), patch(
            "skills._m365.helpers.GraphClient", return_value=fake_gc
        ):
            gc = h.make_teams_gc()

        assert gc._access_token == "GRAPH-BEARER-TOKEN"
        assert gc._access_token != "SKYPE-TOKEN-XYZ"

    def test_uses_browser_token_when_valid(self, tmp_path, monkeypatch):
        """Tier 1 (teams_token.json) still wins when valid -- unchanged
        behavior, just routed through the new Graph-safe accessor."""
        cfg = tmp_path / ".config" / "microsoft-graph"
        cfg.mkdir(parents=True)
        _make_teams_token_file(cfg)
        _make_skype_token_file(cfg)

        import skills._m365.helpers as h

        _reset_teams_gc_cache(h)

        with patch.object(Path, "home", return_value=tmp_path):
            gc = h.make_teams_gc()

        assert gc._access_token == "BROWSER-TOKEN-ABC"

    def test_expired_browser_token_falls_through_to_graph_not_skype(
        self, tmp_path, monkeypatch
    ):
        """Expired teams_token.json + valid skype_token.json must still
        resolve to a Graph Bearer, not the Skype token (this is the
        precise combination that caused the original bug)."""
        cfg = tmp_path / ".config" / "microsoft-graph"
        cfg.mkdir(parents=True)
        _make_teams_token_file(cfg, expired=True)
        _make_skype_token_file(cfg)

        import skills._m365.helpers as h

        _reset_teams_gc_cache(h)
        fake_gc = MagicMock()
        fake_gc.get_token.return_value = "GRAPH-BEARER-TOKEN"

        with patch.object(Path, "home", return_value=tmp_path), patch(
            "skills._m365.helpers.GraphClient", return_value=fake_gc
        ):
            gc = h.make_teams_gc()

        assert gc._access_token == "GRAPH-BEARER-TOKEN"
