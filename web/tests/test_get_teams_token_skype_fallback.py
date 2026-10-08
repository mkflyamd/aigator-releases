"""get_teams_token() must use the FOCI skype_token.json when teams_token.json
is absent or expired.

Bug: get_teams_token() only checked teams_token.json, then fell through to
GraphClient().get_token() (a Graph Bearer token). The AMS image CDN at
asm.skype.com requires a Skype token — sending a Graph Bearer token returns
401 Unauthorized, so every AMSImage fetch failed even after the content_html
fix surfaced the image URLs.

Fix: check skype_token.json (written by the FOCI swap in read_chats.py) as
priority 2, before the Graph fallback.
"""

import json
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_skype_token_file(tmp_path: Path, expired: bool = False) -> Path:
    f = tmp_path / "skype_token.json"
    f.write_text(
        json.dumps(
            {
                "skype_token": "SKYPE-TOKEN-XYZ",
                "expires_at": time.time() + (-60 if expired else 3600),
                "messaging_service": "https://fake.msging.net",
                "global_service": "",
            }
        )
    )
    return f


def _make_teams_token_file(tmp_path: Path, expired: bool = False) -> Path:
    f = tmp_path / "teams_token.json"
    f.write_text(
        json.dumps(
            {
                "access_token": "BROWSER-TOKEN-ABC",
                "expires_at": time.time() + (-60 if expired else 3600),
            }
        )
    )
    return f


class TestGetTeamsToken:
    def test_uses_skype_token_when_teams_token_absent(self, tmp_path, monkeypatch):
        """Priority 2: no teams_token.json -> returns skype_token.json token."""
        _make_skype_token_file(tmp_path)
        import skills._m365.helpers as h

        monkeypatch.setattr(h, "_teams_token_warned", False)
        token = _call_with_cfg(h, tmp_path)
        assert token == "SKYPE-TOKEN-XYZ", f"Expected skype token, got: {token!r}"

    def test_prefers_browser_token_when_valid(self, tmp_path, monkeypatch):
        """Priority 1: valid teams_token.json wins over skype_token.json."""
        _make_teams_token_file(tmp_path)
        _make_skype_token_file(tmp_path)
        import skills._m365.helpers as h

        monkeypatch.setattr(h, "_teams_token_warned", False)
        token = _call_with_cfg(h, tmp_path)
        assert token == "BROWSER-TOKEN-ABC"

    def test_falls_through_to_skype_when_browser_token_expired(
        self, tmp_path, monkeypatch
    ):
        """Expired teams_token.json -> falls through to skype_token.json."""
        _make_teams_token_file(tmp_path, expired=True)
        _make_skype_token_file(tmp_path)
        import skills._m365.helpers as h

        monkeypatch.setattr(h, "_teams_token_warned", False)
        token = _call_with_cfg(h, tmp_path)
        assert token == "SKYPE-TOKEN-XYZ"

    def test_expired_skype_token_falls_through_to_graph(self, tmp_path, monkeypatch):
        """Expired skype_token.json -> falls through to Graph Bearer token."""
        _make_skype_token_file(tmp_path, expired=True)
        import skills._m365.helpers as h

        fake_gc = MagicMock()
        fake_gc.get_token.return_value = "GRAPH-BEARER-TOKEN"
        monkeypatch.setattr(h, "_teams_token_warned", False)
        with patch("skills._m365.helpers.GraphClient", return_value=fake_gc):
            token = _call_with_cfg(h, tmp_path)
        assert token == "GRAPH-BEARER-TOKEN"


def _call_with_cfg(h, cfg_dir: Path) -> str:
    """Call get_teams_token with a patched home dir so it uses cfg_dir."""
    import time as _t

    _log_mock = MagicMock()
    cfg = cfg_dir / ".config" / "microsoft-graph"
    cfg.mkdir(parents=True, exist_ok=True)

    # Copy any files from cfg_dir root into the nested path if needed
    for name in ("teams_token.json", "skype_token.json"):
        src = cfg_dir / name
        dst = cfg / name
        if src.exists() and not dst.exists():
            dst.write_text(src.read_text())

    import skills._m365.helpers as mod

    warned_before = mod._teams_token_warned

    def patched_home():
        return cfg_dir

    with patch.object(Path, "home", patched_home):
        # Reset warned flag so expiry warning path is exercised cleanly
        mod._teams_token_warned = False
        result = mod.get_teams_token()
        mod._teams_token_warned = warned_before
        return result
