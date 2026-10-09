import pytest

from oauth import storage

FAKE = "aigator-fake-api-key"


@pytest.fixture(autouse=True)
def _tmp_oauth_dir(tmp_path, monkeypatch):
    # Old implementation reads _DIR; the new one has no such attribute.
    monkeypatch.setattr(storage, "_DIR", tmp_path / "oauth", raising=False)


def test_load_missing_is_empty():
    assert storage.load("p1") == {}


def test_save_load_round_trip():
    storage.save("p1", {"id": "p1", "client_id": "c"})
    assert storage.load("p1") == {"id": "p1", "client_id": "c"}


def test_update_token_merges_under_token_key():
    storage.save("p1", {"id": "p1"})
    storage.update_token("p1", {"access_token": FAKE})
    assert storage.load("p1") == {"id": "p1", "token": {"access_token": FAKE}}


def test_save_without_token_preserves_existing_token():
    storage.update_token("p1", {"access_token": FAKE})
    storage.save("p1", {"id": "p1", "client_id": "c2"})
    assert storage.load("p1")["token"] == {"access_token": FAKE}


def test_save_with_token_replaces_it():
    storage.update_token("p1", {"access_token": FAKE})
    storage.save("p1", {"id": "p1", "token": {"access_token": "aigator-fake-api-key-2"}})
    assert storage.load("p1")["token"]["access_token"] == "aigator-fake-api-key-2"


def test_delete_removes_record_and_is_idempotent():
    storage.update_token("p1", {"access_token": FAKE})
    storage.delete("p1")
    storage.delete("p1")
    assert storage.load("p1") == {}


@pytest.mark.parametrize("bad", ["../x", "a b", "a/b", ""])
def test_invalid_provider_id_rejected(bad):
    with pytest.raises(ValueError):
        storage.load(bad)


def test_legacy_plaintext_record_is_migrated(tmp_path):
    import json

    import secure_store

    legacy = secure_store._home() / ".gator" / "oauth" / "p9.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"id": "p9", "token": {"access_token": FAKE}}))
    assert storage.load("p9")["token"]["access_token"] == FAKE
    assert not legacy.exists()
