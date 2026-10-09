import json
import time

import secure_store
from skills.slack import mcp_client as mc

FAKE = "aigator-fake-api-key"


def _legacy_dir():
    return secure_store._home() / ".config" / "slack-mcp"


def test_token_round_trip_encrypted():
    mc._save_token({"access_token": FAKE, "refresh_token": "r1", "expires_at": time.time() + 3600})
    assert mc._load_token()["access_token"] == FAKE
    assert secure_store.get_json("slack/token")["refresh_token"] == "r1"
    assert not list(secure_store._home().rglob("*.json"))
    blobs = list((secure_store._home() / ".gator" / "secrets").glob("*.bin"))
    assert blobs
    assert all(FAKE.encode() not in b.read_bytes() for b in blobs)


def test_load_token_missing_is_empty_dict():
    assert mc._load_token() == {}


def test_save_token_writes_no_legacy_file():
    mc._save_token({"access_token": FAKE})
    assert not (_legacy_dir() / "token.json").exists()


def test_save_token_still_clears_display_name_cache(monkeypatch):
    import routes.slack as slack_routes

    calls = []
    monkeypatch.setattr(slack_routes, "clear_user_cache", lambda: calls.append(1), raising=False)
    mc._save_token({"access_token": FAKE})
    assert calls == [1]


def test_legacy_plaintext_token_is_migrated_and_shredded():
    legacy = _legacy_dir() / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE, "refresh_token": "r1"}))
    assert mc._load_token()["access_token"] == FAKE
    assert not legacy.exists()
    assert secure_store.get_json("slack/token")["refresh_token"] == "r1"


def test_auth_status_sees_token_saved_by_mcp_client():
    from routes import auth

    mc._save_token(
        {"access_token": FAKE, "refresh_token": "r1", "expires_at": time.time() + 3600, "team": "T"}
    )
    block = auth._slack_status_block()
    assert block["ok"] is True
    assert block["has_refresh_token"] is True
    assert block["team"] == "T"


def test_refresh_adopts_rotated_refresh_token(monkeypatch):
    mc._save_token({"access_token": "old", "refresh_token": "r1", "expires_at": 0})

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"ok": True, "access_token": FAKE, "refresh_token": "r2", "expires_in": 3600}
            ).encode()

    monkeypatch.setattr(mc.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert mc.get_oauth_token() == FAKE
    stored = secure_store.get_json("slack/token")
    assert stored["refresh_token"] == "r2"
    assert stored["access_token"] == FAKE
    assert not list(secure_store._home().rglob("*.json"))


def test_pkce_state_round_trip_and_clear():
    mc._save_pkce({"code_verifier": FAKE, "state": "s"})
    assert mc._load_pkce() == {"code_verifier": FAKE, "state": "s"}
    assert not list(secure_store._home().rglob("*pkce*.json"))
    blobs = list((secure_store._home() / ".gator" / "secrets").glob("*.bin"))
    assert all(FAKE.encode() not in b.read_bytes() for b in blobs)
    mc._clear_pkce()
    assert mc._load_pkce() == {}
    assert secure_store.get_json("slack/pkce") is None


def test_clear_pkce_when_absent_is_noop():
    mc._clear_pkce()
    assert mc._load_pkce() == {}


def test_legacy_pkce_file_is_migrated_and_shredded():
    legacy = _legacy_dir() / ".pkce_pending.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"code_verifier": FAKE, "state": "s"}))
    assert mc._load_pkce()["state"] == "s"
    assert not legacy.exists()
