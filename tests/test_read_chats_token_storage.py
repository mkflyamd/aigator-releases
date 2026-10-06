import importlib.util
import json
import time
from pathlib import Path

import pytest

import secure_store

FAKE = "aigator-fake-api-key"
SRC = (
    Path(__file__).resolve().parents[1]
    / "web"
    / "skills"
    / "m365-teams"
    / "scripts"
    / "read_chats.py"
)


@pytest.fixture
def rc():
    spec = importlib.util.spec_from_file_location("read_chats_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _legacy_dir():
    d = secure_store._home() / ".config" / "microsoft-graph"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_missing_graph_token_raises(rc):
    with pytest.raises(RuntimeError):
        rc._load_graph_tokens()


def test_graph_token_loaded_from_secure_store(rc):
    secure_store.set_json("graph/token", {"refresh_token": FAKE, "tenant_id": "t"})
    assert rc._load_graph_tokens()["refresh_token"] == FAKE


def test_skype_token_cache_round_trip_encrypted(rc):
    rc._save_skype_token(
        FAKE, "https://example.invalid/ms", 3600, "https://example.invalid/g"
    )
    cached = rc._load_cached_skype_token()
    assert cached["skype_token"] == FAKE
    assert cached["messaging_service"] == "https://example.invalid/ms"
    assert cached["global_service"] == "https://example.invalid/g"
    assert not list(secure_store._home().rglob("*.json"))
    assert secure_store.get_json("graph/skype_token")["skype_token"] == FAKE


def test_expired_skype_cache_is_ignored(rc):
    secure_store.set_json(
        "graph/skype_token",
        {
            "skype_token": FAKE,
            "messaging_service": "m",
            "global_service": "g",
            "expires_at": time.time() + 60,  # inside the 5-minute buffer
        },
    )
    assert rc._load_cached_skype_token() is None


def test_legacy_graph_token_is_migrated_and_shredded(rc):
    legacy = _legacy_dir() / "token.json"
    legacy.write_text(json.dumps({"refresh_token": "legacy-r", "tenant_id": "t"}))
    assert rc._load_graph_tokens()["refresh_token"] == "legacy-r"
    assert not legacy.exists()
    assert secure_store.get_json("graph/token")["refresh_token"] == "legacy-r"


@pytest.mark.parametrize("filename", ["skype_token.json", "skypetoken.json"])
def test_legacy_skype_cache_is_migrated_and_shredded(rc, filename):
    legacy = _legacy_dir() / filename
    legacy.write_text(
        json.dumps(
            {
                "skype_token": FAKE,
                "messaging_service": "m",
                "global_service": "g",
                "expires_at": time.time() + 3600,
            }
        )
    )
    cached = rc._load_cached_skype_token()
    assert cached and cached["skype_token"] == FAKE
    assert not legacy.exists()
    assert secure_store.get_json("graph/skype_token")["skype_token"] == FAKE
