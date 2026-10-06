import json
import logging
import sys
from pathlib import Path

import pytest

import secure_store

FAKE = "aigator-fake-api-key"


def _secrets_dir():
    return secure_store._home() / ".gator" / "secrets"


def test_round_trip_and_not_plaintext_on_disk():
    secure_store.set("slack/token", FAKE)
    assert secure_store.get("slack/token") == FAKE
    blob = (_secrets_dir() / "slack~token.bin").read_bytes()
    assert FAKE.encode() not in blob


def test_missing_returns_none_and_delete_is_idempotent():
    assert secure_store.get("graph/token") is None
    secure_store.delete("graph/token")
    secure_store.set("graph/token", FAKE)
    secure_store.delete("graph/token")
    assert secure_store.get("graph/token") is None


def test_json_helpers_round_trip():
    secure_store.set_json("graph/token", {"access_token": FAKE, "n": 1})
    assert secure_store.get_json("graph/token") == {"access_token": FAKE, "n": 1}
    secure_store.set("graph/teams_token", "not json")
    assert secure_store.get_json("graph/teams_token") is None


def test_list_names_prefix():
    secure_store.set("oauth/a", "1")
    secure_store.set("oauth/b", "2")
    secure_store.set("slack/token", "3")
    assert secure_store.list_names("oauth/") == ["oauth/a", "oauth/b"]
    assert secure_store.list_names() == ["oauth/a", "oauth/b", "slack/token"]


@pytest.mark.parametrize("bad", ["", "../x", "a/../b", "a//b", "a b", "a~b", "/a", "a\n", "."])
def test_invalid_names_rejected(bad):
    with pytest.raises(ValueError):
        secure_store.set(bad, FAKE)


def test_corrupted_blob_returns_none_never_plaintext(caplog):
    secure_store.set("slack/token", FAKE)
    path = _secrets_dir() / "slack~token.bin"
    path.write_bytes(FAKE.encode())  # raw plaintext, not a valid blob
    with caplog.at_level(logging.ERROR, logger="secure_store"):
        assert secure_store.get("slack/token") is None
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    assert FAKE not in caplog.text


def test_unsupported_platform_raises_and_never_writes(monkeypatch):
    monkeypatch.undo()  # drop the fake backend from the autouse fixture
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(secure_store, "_home", lambda: Path("/nonexistent-aigator-home"))
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.set("slack/token", FAKE)
    assert not list(Path("/nonexistent-aigator-home").rglob("*.bin"))


def test_unsupported_platform_get_with_legacy_file_raises_and_keeps_it(monkeypatch, tmp_path):
    legacy = tmp_path / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE}))
    monkeypatch.undo()  # drop the fake backend from the autouse fixture
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(secure_store, "_home", lambda: tmp_path)
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.get("slack/token")
    assert legacy.exists()
    assert json.loads(legacy.read_text()) == {"access_token": FAKE}
    assert not list(tmp_path.rglob("*.bin"))


def test_migrates_legacy_plaintext_and_removes_it():
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE}))
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}
    assert not legacy.exists()
    # second read comes from the encrypted store
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}


def test_migration_keeps_plaintext_when_verification_fails(monkeypatch):
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE}))
    monkeypatch.setattr(secure_store, "_unprotect", lambda b: b"garbage")
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}
    assert legacy.exists()
    assert not (_secrets_dir() / "slack~token.bin").exists()


def test_old_sharepoint_token_location_migrates_into_graph_token():
    old = secure_store._home() / ".config" / "sharepoint-files" / "token.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"refresh_token": FAKE}))
    assert secure_store.get_json("graph/token") == {"refresh_token": FAKE}
    assert not old.exists()


def test_oauth_legacy_file_migrates():
    legacy = secure_store._home() / ".gator" / "oauth" / "mcp-atlassian.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"id": "mcp-atlassian"}))
    assert secure_store.get_json("oauth/mcp-atlassian") == {"id": "mcp-atlassian"}
    assert not legacy.exists()


def test_set_and_delete_remove_legacy_plaintext():
    legacy = secure_store._home() / ".config" / "microsoft-graph" / "teams_token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}")
    secure_store.set_json("graph/teams_token", {"access_token": FAKE})
    assert not legacy.exists()
    legacy.write_text("{}")
    secure_store.delete("graph/teams_token")
    assert not legacy.exists()
    assert secure_store.get("graph/teams_token") is None  # not resurrected


def test_migrate_all_sweeps_every_known_legacy_file():
    h = secure_store._home()
    files = {
        h / ".config" / "microsoft-graph" / "token.json": "graph/token",
        h / ".config" / "microsoft-graph" / "skype_token.json": "graph/skype_token",
        h / ".config" / "microsoft-graph" / "skypetoken.json": "graph/skype_token",
        h / ".config" / "slack-mcp" / ".pkce_pending.json": "slack/pkce",
        h / ".gator" / "oauth" / "prov1.json": "oauth/prov1",
        h / ".config" / "microsoft-graph" / "teams_token.json": "graph/teams_token",
        h / ".config" / "slack-mcp" / "token.json": "slack/token",
    }
    for p in files:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
    migrated = secure_store.migrate_all()
    assert set(migrated) == set(files.values())
    assert not any(p.exists() for p in files)
    assert secure_store.migrate_all() == []  # idempotent


def test_migrate_all_keeps_plaintext_when_existing_blob_does_not_decrypt(caplog):
    secure_store.set("slack/token", FAKE)
    (_secrets_dir() / "slack~token.bin").write_bytes(b"corrupt")
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE}))
    with caplog.at_level(logging.ERROR, logger="secure_store"):
        assert secure_store.migrate_all() == []
    assert legacy.exists()
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    assert FAKE not in caplog.text


def test_migrate_all_shreds_plaintext_when_existing_blob_decrypts():
    secure_store.set("slack/token", FAKE)
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}")
    assert secure_store.migrate_all() == []
    assert not legacy.exists()


def test_undecodable_legacy_file_returns_none_and_is_kept():
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"\xff\xfe\x00bad")
    assert secure_store.get("slack/token") is None
    assert legacy.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="real DPAPI is Windows-only")
def test_real_dpapi_round_trip(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setattr(secure_store, "_home", lambda: tmp_path)
    secure_store.set("config/jira_pat", FAKE)
    assert secure_store.get("config/jira_pat") == FAKE
    raw = next(secure_store._root().glob("*.bin")).read_bytes()
    assert FAKE.encode() not in raw


def test_nul_filled_legacy_file_is_not_migrated_over_existing_blob():
    secure_store.set_json("slack/token", {"access_token": FAKE})
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"\0" * 32)  # what a concurrent _shred leaves briefly
    assert secure_store._migrate_legacy("slack/token") is None
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}


def test_migration_does_not_overwrite_blob_written_by_another_process():
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": "stale"}))
    secure_store._write_blob(secure_store._path("slack/token"), json.dumps({"access_token": FAKE}))
    assert secure_store._migrate_legacy("slack/token") == json.dumps({"access_token": FAKE})


def test_write_blob_retries_transient_sharing_violation(monkeypatch):
    real = secure_store.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("sharing violation")
        return real(src, dst)

    monkeypatch.setattr(secure_store.os, "replace", flaky)
    secure_store.set("slack/token", FAKE)
    assert calls["n"] == 3
    assert secure_store.get("slack/token") == FAKE
